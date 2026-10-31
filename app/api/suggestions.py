"""Approve / reject AI suggestions (CLAUDE.md §8, Phase 2c: type `reply` at autonomy level 2).

Approve never sends: it re-runs the guards on the final body and prepares a reply draft in Koncepty that the person
opens, checks and sends from W4 like any other mail (AI_ASSISTANT §1 — external send is never automatic).
"""

from __future__ import annotations

import difflib
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.ai.guards import has_blocking
from app.ai.models import AiSuggestion
from app.ai.reply import recheck_reply
from app.api.mail import fail
from app.auth.deps import DB, ActivePerson, Auth, SettingsDep
from app.auth.models import Branch, Person
from app.core.audit import audit
from app.core.config import Settings
from app.mail.compose import create_draft, sync_draft_to_imap, text_to_html
from app.mail.mailboxes import accessible_mailboxes
from app.mail.models import Mailbox, Message

router = APIRouter(prefix="/api/suggestions", tags=["ai-suggestions"])

RejectReason = Literal["wrong_category", "wrong_data", "tone", "not_needed"]  # AI_ASSISTANT §10 chips


class ApproveIn(BaseModel):
    body: str | None = Field(default=None, max_length=20000)  # edited text; None = as proposed


class ApproveOut(BaseModel):
    suggestion_id: str
    draft_id: str
    edited: bool


class RejectIn(BaseModel):
    reasons: list[RejectReason] = Field(default_factory=list, max_length=4)
    note: str | None = Field(default=None, max_length=500)


async def _pending(db: DB, ctx: Auth, suggestion_id: uuid.UUID) -> tuple[AiSuggestion, Mailbox]:
    """The suggestion, locked against a second decision; shadow rows are invisible (404)."""
    row = await db.scalar(select(AiSuggestion).where(AiSuggestion.id == suggestion_id).with_for_update())
    allowed = {m.id: m for m in await accessible_mailboxes(db, ctx.account.id)}
    if row is None or row.shadow or row.mailbox_id not in allowed:
        raise fail(404, "suggestion_not_found")
    if row.status != "pending":
        raise fail(409, "suggestion_decided", decided=row.status)
    return row, allowed[row.mailbox_id]


body_to_html = text_to_html  # kept name: tests and callers of Phase 2c


@router.post("/{suggestion_id}/approve")
async def approve(
    suggestion_id: uuid.UUID, body: ApproveIn, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> ApproveOut:
    row, mailbox = await _pending(db, ctx, suggestion_id)
    if row.suggestion_type == "invoice_attach":
        return await _approve_invoice(row, mailbox, body, ctx, person, db, settings)
    if row.suggestion_type != "reply":
        raise fail(422, "unsupported_type")
    message = await db.get(Message, row.message_id) if row.message_id else None
    if message is None:
        raise fail(409, "message_gone")
    proposed = str((row.payload or {}).get("body") or "")
    final = proposed if body.body is None else body.body.strip()
    checks = await recheck_reply(
        db,
        mailbox,
        settings,
        message,
        body=final,
        language=(row.payload or {}).get("language"),
        knowledge_ids=list((row.payload or {}).get("knowledge_ids") or []),
    )
    if has_blocking(checks):
        raise fail(409, "suggestion_blocked", checks=checks)

    person_row = await db.get(Person, person.id)
    branch = await db.get(Branch, person.branch_id) if person.branch_id else None
    draft = await create_draft(
        db,
        settings,
        mailbox=mailbox,
        account_id=ctx.account.id,
        person=person_row,
        branch=branch,
        mode="reply",
        source=message,
        user_html=body_to_html(final),
    )
    edited = final != proposed
    row.status = "approved"
    row.decided_by = person.id
    row.decided_at = datetime.now(UTC)
    row.checks = checks
    row.final_payload = {**(row.payload or {}), "body": final, "draft_id": str(draft.id)}
    diff: dict[str, Any] = {"edited": edited}
    if edited:
        diff["unified"] = "\n".join(
            difflib.unified_diff(proposed.splitlines(), final.splitlines(), "ai", "final", lineterm="")
        )[:20000]
    row.diff = diff
    audit(
        db,
        "ai.suggestion_approved",
        person_id=person.id,
        object_type="ai_suggestion",
        object_id=str(row.id),
        details={"actor": "user", "type": row.suggestion_type, "draft_id": str(draft.id), "edited": edited},
    )
    await db.commit()
    await sync_draft_to_imap(db, settings, draft)  # level 2: the draft waits in Koncepty, nothing is sent
    await db.commit()
    return ApproveOut(suggestion_id=str(row.id), draft_id=str(draft.id), edited=edited)


async def _approve_invoice(
    row: AiSuggestion, mailbox: Mailbox, body: ApproveIn, ctx: Auth, person: Person, db: DB, settings: Settings
) -> ApproveOut:
    """Phase 3d: every check again, live against Money (owner, recipient, report), then the draft with the PDFs."""
    from app.money.bridge_client import BridgeClient, BridgeUnavailable
    from app.money.invoice_attach import evaluate
    from app.money.invoice_draft import InvoiceDraftError, build_invoice_draft

    if not settings.feature_money:
        raise fail(409, "money_disabled")
    message = await db.get(Message, row.message_id) if row.message_id else None
    if message is None:
        raise fail(409, "message_gone")
    payload = row.payload or {}
    proposed = str(payload.get("body") or "")
    final = proposed if body.body is None else body.body.strip()
    numbers = [str(i.get("number")) for i in payload.get("invoices") or [] if i.get("number")]
    to = [str(e) for e in payload.get("to") or []]
    if not numbers or len(to) != 1:
        raise fail(409, "suggestion_blocked", checks=[{"id": "no_invoice", "level": "blocking", "params": {}}])
    person_row = await db.get(Person, person.id)
    branch = await db.get(Branch, person.branch_id) if person.branch_id else None
    async with BridgeClient(settings) as bridge:
        try:
            ev = await evaluate(
                db,
                settings,
                bridge,
                email=to[0],
                body_text=message.body_text,
                refs=numbers,
                language=payload.get("language"),
            )
            if ev.blocked or str(ev.company_money_id) != str(payload.get("company_money_id")):
                raise fail(409, "suggestion_blocked", checks=ev.checks)
            draft = await build_invoice_draft(
                db,
                settings,
                bridge,
                mailbox=mailbox,
                message=message,
                account_id=ctx.account.id,
                person=person_row,
                branch=branch,
                evaluation=ev,
                body=final,
                language=payload.get("language"),
            )
        except BridgeUnavailable as exc:
            raise fail(503, "money_unavailable", reason=exc.code) from None
        except InvoiceDraftError as exc:
            raise fail(409, exc.code, number=exc.number) from None
    edited = final != proposed
    row.status = "approved"
    row.decided_by = person.id
    row.decided_at = datetime.now(UTC)
    row.checks = ev.checks
    row.final_payload = {**payload, "body": final, "draft_id": str(draft.id)}
    row.diff = {"edited": edited}
    audit(
        db,
        "ai.suggestion_approved",
        person_id=person.id,
        object_type="ai_suggestion",
        object_id=str(row.id),
        details={
            "actor": "user",
            "type": row.suggestion_type,
            "draft_id": str(draft.id),
            "edited": edited,
            "invoices": [i.number for i in ev.invoices],
            "company_money_id": str(ev.company_money_id),
        },
    )
    await db.commit()
    await sync_draft_to_imap(db, settings, draft)  # level 2: waits in Koncepty; sending is the person's click
    await db.commit()
    return ApproveOut(suggestion_id=str(row.id), draft_id=str(draft.id), edited=edited)


@router.post("/{suggestion_id}/reject")
async def reject(suggestion_id: uuid.UUID, body: RejectIn, ctx: Auth, person: ActivePerson, db: DB) -> dict[str, str]:
    row, _mailbox = await _pending(db, ctx, suggestion_id)
    reasons = list(dict.fromkeys(body.reasons))
    row.status = "rejected"
    row.decided_by = person.id
    row.decided_at = datetime.now(UTC)
    row.final_payload = {"reject_reasons": reasons, "note": (body.note or "").strip() or None}
    audit(
        db,
        "ai.suggestion_rejected",
        person_id=person.id,
        object_type="ai_suggestion",
        object_id=str(row.id),
        details={"actor": "user", "type": row.suggestion_type, "reasons": reasons},
    )
    await db.commit()
    return {"status": "rejected"}
