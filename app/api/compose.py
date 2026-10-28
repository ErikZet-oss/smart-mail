"""Compose API — drafts, send with undo, attachments, identities, Odpovede (Phase 1e / W4)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.api.mail import _mailbox, fail
from app.auth.deps import DB, ActivePerson, Auth, SettingsDep
from app.auth.models import Branch, Person
from app.mail import storage
from app.mail.compose import (
    Mode,
    cancel_send,
    create_draft,
    ensure_default_identity,
    pre_send_checks,
    queue_send,
)
from app.mail.compose_models import CannedResponse, ComposeAttachment, ComposeDraft, Identity
from app.mail.models import Message
from app.mail.sanitize import sanitize_html
from app.mail.send_guard import blocked_recipients, test_allowlist_addresses
from app.mail.signature import html_to_text, render_signature

router = APIRouter(prefix="/api/mail", tags=["compose"])

MAX_ATTACH_BYTES = 25 * 1024 * 1024


class AddrIn(BaseModel):
    name: str | None = None
    email: str


class DraftPatch(BaseModel):
    identity_id: uuid.UUID | None = None
    to_addrs: list[AddrIn] | None = None
    cc_addrs: list[AddrIn] | None = None
    bcc_addrs: list[AddrIn] | None = None
    subject: str | None = None
    body_html: str | None = None
    include_signature: bool | None = None
    signature_html_override: str | None = None
    priority: Literal["low", "normal", "high"] | None = None
    request_mdn: bool | None = None
    request_dsn: bool | None = None
    save_sent: bool | None = None
    scheduled_at: datetime | None = None


class CreateDraftIn(BaseModel):
    mode: Mode = "new"
    message_id: uuid.UUID | None = None


class SendIn(BaseModel):
    force: bool = False


class AttOut(BaseModel):
    id: str
    filename: str
    content_type: str
    size: int
    av_status: str


class DraftOut(BaseModel):
    id: str
    mailbox_id: str
    mode: str
    identity_id: str | None
    to_addrs: list[dict[str, Any]]
    cc_addrs: list[dict[str, Any]]
    bcc_addrs: list[dict[str, Any]]
    subject: str
    body_html: str
    body_text: str
    include_signature: bool
    signature_html_override: str | None
    signature_person_id: str | None
    priority: str
    request_mdn: bool
    request_dsn: bool
    save_sent: bool
    status: str
    scheduled_at: datetime | None
    undo_until: datetime | None
    send_error: str | None
    send_error_meta: dict[str, Any] | None = None
    attachments: list[AttOut]
    checks: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: datetime


class IdentityOut(BaseModel):
    id: str
    display_name: str
    email: str
    organization: str | None
    is_default: bool


class ResponseOut(BaseModel):
    id: str
    name: str
    language: str
    body_html: str
    shared: bool
    shortcut: str | None


def _send_error_meta(draft: ComposeDraft, settings: Any) -> dict[str, Any] | None:
    """Structured send failure for W4/W2 (pilot #18 B7) — never raw SMTP text."""
    raw = (draft.send_error or "").strip()
    if not raw:
        return None
    code, _, detail = raw.partition(":")
    if code == "recipient_not_allowed":
        blocked = [part.strip().lower() for part in detail.split(",") if part.strip()]
        return {
            "code": code,
            "blocked": blocked,
            "allowlist": test_allowlist_addresses(settings),
            "show_allowlist": settings.app_env == "test",
        }
    if code in {"server_unavailable", "smtp_host_not_allowed"} or code.endswith("Error") or code.endswith("Exception"):
        return {"code": "server_unavailable"}
    return {"code": code or raw}


def _draft_out(draft: ComposeDraft, atts: list[ComposeAttachment], settings: Any) -> DraftOut:
    return DraftOut(
        id=str(draft.id),
        mailbox_id=str(draft.mailbox_id),
        mode=draft.mode,
        identity_id=str(draft.identity_id) if draft.identity_id else None,
        to_addrs=list(draft.to_addrs or []),
        cc_addrs=list(draft.cc_addrs or []),
        bcc_addrs=list(draft.bcc_addrs or []),
        subject=draft.subject,
        body_html=draft.body_html,
        body_text=draft.body_text,
        include_signature=draft.include_signature,
        signature_html_override=draft.signature_html_override,
        signature_person_id=str(draft.signature_person_id) if draft.signature_person_id else None,
        priority=draft.priority,
        request_mdn=draft.request_mdn,
        request_dsn=draft.request_dsn,
        save_sent=draft.save_sent,
        status=draft.status,
        scheduled_at=draft.scheduled_at,
        undo_until=draft.undo_until,
        send_error=draft.send_error,
        send_error_meta=_send_error_meta(draft, settings),
        attachments=[
            AttOut(
                id=str(a.id),
                filename=a.filename,
                content_type=a.content_type,
                size=a.size,
                av_status=a.av_status,
            )
            for a in atts
        ],
        checks=pre_send_checks(draft, settings),
        updated_at=draft.updated_at,
    )


async def _load_atts(db: DB, draft_id: uuid.UUID) -> list[ComposeAttachment]:
    return list((await db.execute(select(ComposeAttachment).where(ComposeAttachment.draft_id == draft_id))).scalars())


async def _get_draft(db: DB, ctx: Auth, draft_id: uuid.UUID) -> ComposeDraft:
    draft = await db.get(ComposeDraft, draft_id)
    if draft is None or draft.account_id != ctx.account.id:
        raise fail(404, "draft_not_found")
    return draft


@router.get("/mailboxes/{ref}/identities")
async def list_identities(ref: str, ctx: Auth, db: DB) -> list[IdentityOut]:
    mailbox = await _mailbox(db, ctx, ref)
    await ensure_default_identity(db, mailbox, ctx.person.full_name if ctx.person else None)
    await db.commit()
    rows = list((await db.execute(select(Identity).where(Identity.mailbox_id == mailbox.id))).scalars())
    return [
        IdentityOut(
            id=str(i.id),
            display_name=i.display_name,
            email=i.email,
            organization=i.organization,
            is_default=i.is_default,
        )
        for i in rows
    ]


@router.get("/responses")
async def list_responses(ctx: Auth, db: DB) -> list[ResponseOut]:
    person_id = ctx.session.active_person_id
    q = select(CannedResponse).where(or_(CannedResponse.shared.is_(True), CannedResponse.person_id == person_id))
    rows = list((await db.execute(q.order_by(CannedResponse.name))).scalars())
    return [
        ResponseOut(
            id=str(r.id),
            name=r.name,
            language=r.language,
            body_html=r.body_html,
            shared=r.shared,
            shortcut=r.shortcut,
        )
        for r in rows
    ]


@router.post("/mailboxes/{ref}/compose")
async def post_compose(
    ref: str, body: CreateDraftIn, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> DraftOut:
    mailbox = await _mailbox(db, ctx, ref)
    source = None
    if body.message_id:
        source = await db.get(Message, body.message_id)
        if source is None or source.mailbox_id != mailbox.id:
            raise fail(404, "message_not_found")
    branch = None
    if ctx.person and ctx.person.branch_id:
        branch = await db.get(Branch, ctx.person.branch_id)
    person_row = await db.get(Person, person.id)
    draft = await create_draft(
        db,
        settings,
        mailbox=mailbox,
        account_id=ctx.account.id,
        person=person_row,
        branch=branch,
        mode=body.mode,
        source=source,
    )
    await db.commit()
    return _draft_out(draft, [], settings)


@router.get("/compose/{draft_id}")
async def get_draft(draft_id: uuid.UUID, ctx: Auth, db: DB, settings: SettingsDep) -> DraftOut:
    draft = await _get_draft(db, ctx, draft_id)
    return _draft_out(draft, await _load_atts(db, draft.id), settings)


@router.patch("/compose/{draft_id}")
async def patch_draft(
    draft_id: uuid.UUID, body: DraftPatch, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> DraftOut:
    draft = await _get_draft(db, ctx, draft_id)
    if draft.status not in {"editing", "failed", "scheduled"}:
        raise fail(409, "draft_not_editable")
    if body.identity_id is not None:
        identity = await db.get(Identity, body.identity_id)
        if identity is None or identity.mailbox_id != draft.mailbox_id:
            raise fail(404, "identity_not_found")
        draft.identity_id = identity.id
    if body.to_addrs is not None:
        draft.to_addrs = [a.model_dump() for a in body.to_addrs]
    if body.cc_addrs is not None:
        draft.cc_addrs = [a.model_dump() for a in body.cc_addrs]
    if body.bcc_addrs is not None:
        draft.bcc_addrs = [a.model_dump() for a in body.bcc_addrs]
    if body.subject is not None:
        draft.subject = body.subject
    if body.body_html is not None:
        draft.body_html = sanitize_html(body.body_html)
        draft.body_text = html_to_text(draft.body_html)
    if body.include_signature is not None:
        draft.include_signature = body.include_signature
    if body.signature_html_override is not None:
        draft.signature_html_override = sanitize_html(body.signature_html_override)
    if body.priority is not None:
        draft.priority = body.priority
    if body.request_mdn is not None:
        draft.request_mdn = body.request_mdn
    if body.request_dsn is not None:
        draft.request_dsn = body.request_dsn
    if body.save_sent is not None:
        draft.save_sent = body.save_sent
    if "scheduled_at" in body.model_fields_set:
        draft.scheduled_at = body.scheduled_at
        draft.status = "scheduled" if body.scheduled_at else "editing"
    draft.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(draft)
    return _draft_out(draft, await _load_atts(db, draft.id), settings)


@router.delete("/compose/{draft_id}")
async def delete_draft(
    draft_id: uuid.UUID, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> dict[str, bool]:
    draft = await _get_draft(db, ctx, draft_id)
    for att in await _load_atts(db, draft.id):
        storage.delete_key(settings, att.storage_key)
    await db.delete(draft)
    await db.commit()
    return {"ok": True}


@router.post("/compose/{draft_id}/attachments")
async def upload_attachment(
    draft_id: uuid.UUID,
    ctx: Auth,
    person: ActivePerson,
    db: DB,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
) -> DraftOut:
    draft = await _get_draft(db, ctx, draft_id)
    if draft.status not in {"editing", "failed", "scheduled"}:
        raise fail(409, "draft_not_editable")
    data = await file.read()
    if len(data) > MAX_ATTACH_BYTES:
        raise fail(413, "attachment_too_large")
    from app.mail.clamav import scan_bytes

    av = await scan_bytes(settings, data)
    if av == "infected":
        raise fail(422, "attachment_infected")
    key, digest = storage.put_bytes(settings, data, prefix=f"mail/{draft.mailbox_id}/compose")
    db.add(
        ComposeAttachment(
            draft_id=draft.id,
            filename=file.filename or "attachment.bin",
            content_type=file.content_type or "application/octet-stream",
            size=len(data),
            storage_key=key,
            sha256=digest,
            av_status=av,
        )
    )
    await db.commit()
    return _draft_out(draft, await _load_atts(db, draft.id), settings)


@router.post("/compose/{draft_id}/send")
async def send_draft(
    draft_id: uuid.UUID, body: SendIn, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> DraftOut:
    draft = await _get_draft(db, ctx, draft_id)
    if draft.status not in {"editing", "failed", "scheduled"}:
        raise fail(409, "draft_not_editable")
    # Prefer allowlist rejection on Send click (422) over a silent worker failure (pilot #18 B7).
    # Empty MAIL_SEND_TEST_ALLOWLIST does not block — only enforce when the list is non-empty.
    allowlist = test_allowlist_addresses(settings)
    if allowlist:
        emails = [
            str(a.get("email") or "")
            for a in list(draft.to_addrs or []) + list(draft.cc_addrs or []) + list(draft.bcc_addrs or [])
        ]
        blocked = blocked_recipients(settings, emails)
        if blocked:
            raise fail(
                422,
                "recipient_not_allowed",
                blocked=blocked,
                allowlist=allowlist,
                show_allowlist=settings.app_env == "test",
            )
    try:
        await queue_send(db, settings, draft, account_id=ctx.account.id, person_id=person.id, force=body.force)
    except ValueError as exc:
        if str(exc) == "pre_send_blocked":
            raise fail(409, "pre_send_blocked", checks=pre_send_checks(draft, settings)) from None
        raise
    await db.commit()
    await db.refresh(draft)
    delay = settings.undo_send_seconds
    if delay <= 0:
        from app.mail.compose import execute_send

        await execute_send(db, settings, draft.id)
        await db.refresh(draft)
    else:
        try:
            from arq import create_pool
            from arq.connections import RedisSettings

            redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
            await redis.enqueue_job("send_compose_draft", str(draft.id), _defer_by=delay)
            await redis.aclose()
        except Exception as exc:
            import structlog

            structlog.get_logger(__name__).warning("compose.enqueue_failed", error=type(exc).__name__)
    return _draft_out(draft, await _load_atts(db, draft.id), settings)


@router.post("/compose/{draft_id}/undo")
async def undo_draft(draft_id: uuid.UUID, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep) -> DraftOut:
    draft = await _get_draft(db, ctx, draft_id)
    try:
        await cancel_send(db, draft, account_id=ctx.account.id, person_id=person.id)
    except ValueError:
        raise fail(409, "not_queued") from None
    await db.commit()
    await db.refresh(draft)
    return _draft_out(draft, await _load_atts(db, draft.id), settings)


@router.get("/compose/{draft_id}/signature-preview")
async def signature_preview(draft_id: uuid.UUID, ctx: Auth, db: DB) -> dict[str, str]:
    draft = await _get_draft(db, ctx, draft_id)
    identity = await db.get(Identity, draft.identity_id) if draft.identity_id else None
    person_row = await db.get(Person, draft.person_id) if draft.person_id else None
    branch = await db.get(Branch, person_row.branch_id) if person_row and person_row.branch_id else None
    html = render_signature(
        person=person_row,
        branch=branch,
        identity=identity,
        email=identity.email if identity else "",
        override_html=draft.signature_html_override,
    )
    return {"html": html}
