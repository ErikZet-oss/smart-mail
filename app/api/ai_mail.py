"""AI triage views — category counts and filtered lists (Phase 2b W2f) and the reply suggestions of a message (2c)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import and_, case, desc, func, or_, select

from app.ai.category_settings import category_lookup, load_category_data, triage_categories
from app.ai.models import AiSuggestion, Classification
from app.ai.pipeline import normalize_message_id_header
from app.ai.service import category_counts
from app.api.mail import _ai_provider_configured, _mailbox, fail
from app.api.messages import MessageListItem
from app.auth.deps import DB, Auth, SettingsDep
from app.core.config import Settings
from app.mail.models import Mailbox, Message
from app.mail.prefs import get_list_prefs


def _ai_active(mailbox: Mailbox, settings: Settings) -> bool:
    return bool(mailbox.ai_enabled and mailbox.ai_enabled_at is not None and _ai_provider_configured(settings))


router = APIRouter(prefix="/api/mail", tags=["mail-ai"])

FilterName = Literal["all", "unread", "flagged", "attachments"]


class CategoryOut(BaseModel):
    id: str
    label_sk: str
    description_sk: str
    color_token: str
    count: int


class CategoriesOut(BaseModel):
    categories: list[CategoryOut]


class CategoryListOut(BaseModel):
    category: CategoryOut
    total: int
    page: int
    page_size: int
    messages: list[MessageListItem]


class ClassificationOut(BaseModel):
    category: str | None
    language: str | None
    priority: str | None
    summary_sk: str | None
    confidence: float | None
    note_codes: list[str]
    source: str | None


def _cls_fields(row: Classification | None) -> dict[str, Any]:
    if row is None:
        return {
            "ai_category": None,
            "ai_priority": None,
            "ai_summary": None,
            "ai_language": None,
            "ai_confidence": None,
            "ai_note_codes": [],
        }
    payload = row.payload or {}
    return {
        "ai_category": row.category,
        "ai_priority": row.priority,
        "ai_summary": payload.get("summary_sk"),
        "ai_language": row.language,
        "ai_confidence": payload.get("confidence"),
        "ai_note_codes": list(payload.get("note_codes") or []),
    }


@router.get("/mailboxes/{ref}/ai/categories")
async def list_ai_categories(ref: str, ctx: Auth, db: DB, settings: SettingsDep) -> CategoriesOut:
    mailbox = await _mailbox(db, ctx, ref)
    if not _ai_active(mailbox, settings):
        return CategoriesOut(categories=[])
    counts = await category_counts(db, mailbox.id)
    return CategoriesOut(
        categories=[
            CategoryOut(
                id=c.id,
                label_sk=c.label_sk,
                description_sk=c.description_sk,
                color_token=c.color_token,
                count=counts.get(c.id, 0),
            )
            for c in triage_categories(await load_category_data(db))
        ]
    )


@router.get("/mailboxes/{ref}/ai/views/{category}/messages")
async def list_category_messages(
    ref: str,
    category: str,
    ctx: Auth,
    db: DB,
    settings: SettingsDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int | None, Query(ge=1, le=200)] = None,
    filter: FilterName = "all",
    q: str | None = None,
) -> CategoryListOut:
    # every known category, also a switched-off one: stored classifications keep opening (17c, #116)
    known = category_lookup(await load_category_data(db))
    if category not in known:
        raise fail(404, "category_not_found")
    mailbox = await _mailbox(db, ctx, ref)
    cdef = known[category]
    if not _ai_active(mailbox, settings):
        # AI off / no provider — empty list, never 500 (pilot #18 B3).
        return CategoryListOut(
            category=CategoryOut(
                id=cdef.id,
                label_sk=cdef.label_sk,
                description_sk=cdef.description_sk,
                color_token=cdef.color_token,
                count=0,
            ),
            total=0,
            page=page,
            page_size=page_size or 50,
            messages=[],
        )
    prefs = await get_list_prefs(db, ctx.session.active_person_id)
    size = page_size or prefs.page_size

    cond = [
        Classification.mailbox_id == mailbox.id,
        Classification.category == category,
        Classification.status == "done",
        Message.deleted.is_(False),
    ]
    if filter == "unread":
        cond.append(Message.seen.is_(False))
    elif filter == "flagged":
        cond.append(Message.flagged.is_(True))
    elif filter == "attachments":
        cond.append(Message.has_attachments.is_(True))
    if q:
        like = f"%{q.strip()}%"
        cond.append(or_(Message.subject.ilike(like), Message.from_email.ilike(like), Message.from_name.ilike(like)))

    base = (
        select(Message, Classification).join(Classification, Classification.message_id == Message.id).where(and_(*cond))
    )
    total = int(
        await db.scalar(
            select(func.count())
            .select_from(Message)
            .join(Classification, Classification.message_id == Message.id)
            .where(and_(*cond))
        )
        or 0
    )
    # Priority first (urgent > normal > low), then date.
    # Must use sqlalchemy.case — func.case(..., else_=) raises TypeError (pilot #18 B8).
    priority_order = case(
        (Classification.priority == "urgent", 0),
        (Classification.priority == "normal", 1),
        else_=2,
    )
    rows = list(
        (
            await db.execute(
                base.order_by(priority_order, desc(Message.received_at), desc(Message.uid))
                .offset((page - 1) * size)
                .limit(size)
            )
        ).all()
    )
    messages: list[MessageListItem] = []
    for m, cls in rows:
        extra = _cls_fields(cls)
        messages.append(
            MessageListItem(
                id=str(m.id),
                thread_id=str(m.thread_id) if m.thread_id else None,
                folder_id=str(m.folder_id),
                uid=m.uid,
                subject=m.subject,
                from_name=m.from_name,
                from_email=m.from_email,
                preview=m.preview,
                received_at=m.received_at,
                sent_at=m.sent_at,
                size=m.size,
                seen=m.seen,
                flagged=m.flagged,
                answered=m.answered,
                has_attachments=m.has_attachments,
                thread_count=1,
                ai_category=extra["ai_category"],
                ai_priority=extra["ai_priority"],
                ai_summary=extra["ai_summary"],
                ai_language=extra["ai_language"],
                ai_confidence=extra["ai_confidence"],
                ai_note_codes=extra["ai_note_codes"],
            )
        )
    return CategoryListOut(
        category=CategoryOut(
            id=cdef.id,
            label_sk=cdef.label_sk,
            description_sk=cdef.description_sk,
            color_token=cdef.color_token,
            count=total,
        ),
        total=total,
        page=page,
        page_size=size,
        messages=messages,
    )


@router.get("/mailboxes/{ref}/messages/{message_id}/classification")
async def get_message_classification(ref: str, message_id: uuid.UUID, ctx: Auth, db: DB) -> ClassificationOut:
    mailbox = await _mailbox(db, ctx, ref)
    message = await db.get(Message, message_id)
    if message is None or message.mailbox_id != mailbox.id:
        raise fail(404, "message_not_found")
    row = await db.scalar(select(Classification).where(Classification.message_id == message.id).limit(1))
    if row is None:
        return ClassificationOut(
            category=None,
            language=None,
            priority=None,
            summary_sk=None,
            confidence=None,
            note_codes=[],
            source=None,
        )
    payload = row.payload or {}
    return ClassificationOut(
        category=row.category,
        language=row.language,
        priority=row.priority,
        summary_sk=payload.get("summary_sk"),
        confidence=payload.get("confidence"),
        note_codes=list(payload.get("note_codes") or []),
        source=payload.get("source"),
    )


class SuggestionCheckOut(BaseModel):
    id: str
    level: str
    params: dict[str, Any]


class SuggestionOut(BaseModel):
    id: str
    type: str
    status: str
    to: list[str]
    subject: str
    body: str
    language: str | None
    rationale: str | None
    confidence: float | None
    checks: list[SuggestionCheckOut]
    blocked: bool


def suggestion_out(row: AiSuggestion) -> SuggestionOut:
    payload = row.payload or {}
    checks = [SuggestionCheckOut.model_validate(c) for c in row.checks or []]
    return SuggestionOut(
        id=str(row.id),
        type=row.suggestion_type,
        status=row.status,
        to=[str(a) for a in payload.get("to") or []],
        subject=str(payload.get("subject") or ""),
        body=str(payload.get("body") or ""),
        language=payload.get("language"),
        rationale=row.rationale,
        confidence=float(row.confidence) if row.confidence is not None else None,
        checks=checks,
        blocked=any(c.level == "blocking" for c in checks),
    )


@router.get("/mailboxes/{ref}/messages/{message_id}/suggestions")
async def get_message_suggestions(ref: str, message_id: uuid.UUID, ctx: Auth, db: DB) -> list[SuggestionOut]:
    """Pending suggestions for the reading pane (2c). Shadow-mode rows are never returned (AI_ASSISTANT §2)."""
    mailbox = await _mailbox(db, ctx, ref)
    message = await db.get(Message, message_id)
    if message is None or message.mailbox_id != mailbox.id:
        raise fail(404, "message_not_found")
    # Copies of the same e-mail in other folders share one set of suggestions (§2, once per Message-ID) — but only
    # inside this mailbox: a suggestion made for a mailbox the caller cannot open must never show here (#99 review).
    header = normalize_message_id_header(message.message_id)
    same_mail = AiSuggestion.message_id == message.id
    if header:
        copies = select(Classification.message_id).where(
            Classification.message_id_header == header, Classification.mailbox_id == mailbox.id
        )
        same_mail = or_(same_mail, AiSuggestion.message_id.in_(copies))
    rows = await db.execute(
        select(AiSuggestion)
        .where(
            same_mail,
            AiSuggestion.mailbox_id == mailbox.id,
            AiSuggestion.status == "pending",
            AiSuggestion.shadow.is_(False),
        )
        .order_by(AiSuggestion.created_at)
    )
    return [suggestion_out(row) for row in rows.scalars()]
