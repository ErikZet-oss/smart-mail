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

from app.ai.guards import check, has_blocking
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
    # #215: checks of level `requires_ack` the person explicitly confirmed (e.g. „invoice_other_customer“)
    acknowledged_checks: list[str] = Field(default_factory=list, max_length=10)
    # #217: invoice numbers the person picked on the card (invoice_attach with `pick`); None = the pre-selection
    selected: list[str] | None = Field(default=None, max_length=5)


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
    if row.suggestion_type == "delivery_note_attach":
        return await _approve_delivery_note(row, mailbox, body, ctx, person, db, settings)
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
    from app.money.invoice_attach import ACK_CHECK, draft_body, evaluate
    from app.money.invoice_draft import InvoiceDraftError, build_invoice_draft

    if not settings.feature_money:
        raise fail(409, "money_disabled")
    message = await db.get(Message, row.message_id) if row.message_id else None
    if message is None:
        raise fail(409, "message_gone")
    payload = row.payload or {}
    proposed = str(payload.get("body") or "")
    numbers = [str(i.get("number")) for i in payload.get("invoices") or [] if i.get("number")]
    to = [str(e) for e in payload.get("to") or []]
    foreign = payload.get("foreign") is True
    owner_expected = str(payload.get("owner_money_id"))
    if payload.get("pick") is True:
        # #217: only the picked invoices; one customer per draft; another company's invoice needs the #215 tick
        items = [i for i in payload.get("invoices") or [] if isinstance(i, dict) and i.get("number")]
        picked = body.selected if body.selected is not None else [str(i["number"]) for i in items if i.get("selected")]
        chosen = [i for i in items if str(i["number"]) in set(picked)]
        if not picked or len(chosen) != len(set(picked)):
            raise fail(409, "selection_invalid")
        owners = {"own" if i.get("own") else str(i.get("owner_money_id")) for i in chosen}
        if len(owners) != 1:
            one = [{"id": "one_customer_per_draft", "level": "blocking", "params": {}}]
            raise fail(409, "suggestion_blocked", checks=one)
        numbers = [str(i["number"]) for i in chosen]
        foreign = not chosen[0].get("own")
        owner_expected = str(chosen[0].get("owner_money_id")) if foreign else "None"
        orders = list(dict.fromkeys(str(i.get("order")) for i in chosen if i.get("order")))
        proposed = draft_body(payload.get("language"), numbers, orders)
    final = proposed if body.body is None else body.body.strip()
    if not numbers or len(to) != 1:
        raise fail(409, "suggestion_blocked", checks=[{"id": "no_invoice", "level": "blocking", "params": {}}])
    if foreign and ACK_CHECK not in body.acknowledged_checks:
        raise fail(409, "ack_required", check=ACK_CHECK)  # #215: the person must tick „Overil som…“
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
                allow_other_owner=foreign,
            )
            if ev.blocked or str(ev.company_money_id) != str(payload.get("company_money_id")):
                raise fail(409, "suggestion_blocked", checks=ev.checks)
            if ev.foreign != foreign or str(ev.owner_money_id) != owner_expected:
                # the invoice's customer changed in Money since the suggestion → a new decision is needed
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
    row.final_payload = {**payload, "body": final, "draft_id": str(draft.id), "selected": numbers}
    if foreign:
        row.final_payload["ack"] = {
            "check": ACK_CHECK,
            "email": to[0].strip().lower(),  # the one address the person saw on the card
            "owner_money_id": str(ev.owner_money_id),  # #217: the owner of the PICKED invoices
            "person_id": str(person.id),
            "account_id": str(ctx.account.id),
            "at": datetime.now(UTC).isoformat(),
        }
        audit(
            db,
            "money.invoice_other_customer_ack",
            account_id=ctx.account.id,
            person_id=person.id,
            object_type="ai_suggestion",
            object_id=str(row.id),
            details={
                "invoices": [i.number for i in ev.invoices],
                "owner_money_id": str(ev.owner_money_id),
                "requester_email": to[0],
                "draft_id": str(draft.id),
            },
        )
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


async def _approve_delivery_note(
    row: AiSuggestion, mailbox: Mailbox, body: ApproveIn, ctx: Auth, person: Person, db: DB, settings: Settings
) -> ApproveOut:
    """#222: only the picked notes, one company per draft, the #215 tick for another company's note; every check
    again live against Money (exists, owner, branch report) and then the draft with Money's own print PDFs."""
    from app.mail import storage
    from app.mail.compose import create_draft as make_draft
    from app.mail.compose_models import ComposeAttachment
    from app.money.bridge_client import BridgeClient, BridgeUnavailable
    from app.money.delivery_note_attach import (
        DOCUMENT_KIND,
        branch_reports,
        draft_body,
        pdf_filename,
        report_for,
    )
    from app.money.invoice_attach import ACK_CHECK, STRONG, storage_prefix
    from app.money.matching import match_sender

    if not settings.feature_money:
        raise fail(409, "money_disabled")
    message = await db.get(Message, row.message_id) if row.message_id else None
    if message is None:
        raise fail(409, "message_gone")
    payload = row.payload or {}
    to = [str(e) for e in payload.get("to") or []]
    items = [i for i in payload.get("invoices") or [] if isinstance(i, dict) and i.get("number")]
    picked = body.selected if body.selected is not None else [str(i["number"]) for i in items if i.get("selected")]
    chosen = [i for i in items if str(i["number"]) in set(picked)]
    if not picked or len(chosen) != len(set(picked)) or len(to) != 1:
        raise fail(409, "selection_invalid")
    owners = {"own" if i.get("own") else str(i.get("owner_money_id")) for i in chosen}
    if len(owners) != 1:
        raise fail(
            409, "suggestion_blocked", checks=[{"id": "one_customer_per_draft", "level": "blocking", "params": {}}]
        )
    foreign = not chosen[0].get("own")
    if foreign and ACK_CHECK not in body.acknowledged_checks:
        raise fail(409, "ack_required", check=ACK_CHECK)
    numbers = [str(i["number"]) for i in chosen]
    orders = list(dict.fromkeys(str(i.get("order")) for i in chosen if i.get("order")))
    proposed = draft_body(payload.get("language"), numbers, orders)
    final = proposed if body.body is None else body.body.strip()

    match = await match_sender(db, to[0], message.body_text, settings)
    strong = match.company is not None and match.method in STRONG
    expected_owner = (
        str(chosen[0].get("owner_money_id")) if foreign else str(match.company.money_id if match.company else None)
    )
    if not foreign and (not strong or expected_owner != str(payload.get("company_money_id"))):
        raise fail(
            409, "suggestion_blocked", checks=[{"id": "recipient_unconfirmed", "level": "blocking", "params": {}}]
        )
    reports = await branch_reports(db)
    pdfs: list[tuple[str, bytes]] = []
    async with BridgeClient(settings) as bridge:
        try:
            for number in numbers:
                found = await bridge.search_deliveries(number=number)
                note = next((d for d in found.items if d.number == number), None)
                if note is None:
                    raise fail(
                        409, "suggestion_blocked", checks=[check("delivery_note_not_found", "blocking", number=number)]
                    )
                if str(note.company_id) != expected_owner:
                    # the note's customer changed in Money since the suggestion → a new decision is needed
                    raise fail(
                        409,
                        "suggestion_blocked",
                        checks=[check("recipient_not_document_owner", "blocking", number=number)],
                    )
                branch_report = report_for(reports, note)
                if branch_report is None or not branch_report.report_id:
                    name = branch_report.branch_name if branch_report else "—"
                    raise fail(409, "delivery_note_report_missing", branch=name, number=number)
                data = await bridge.document_pdf(
                    DOCUMENT_KIND, note.id, branch_report.report_id, branch_report.design_id
                )
                if not data:
                    raise fail(409, "pdf_missing", number=number)
                pdfs.append((pdf_filename(number), data))
        except BridgeUnavailable as exc:
            raise fail(503, "money_unavailable", reason=exc.code) from None
    person_row = await db.get(Person, person.id)
    branch = await db.get(Branch, person.branch_id) if person.branch_id else None
    draft = await make_draft(
        db,
        settings,
        mailbox=mailbox,
        account_id=ctx.account.id,
        person=person_row,
        branch=branch,
        mode="reply",
        source=message,
        user_html=text_to_html(final),
    )
    draft.to_addrs = [{"name": None, "email": to[0]}]  # only the checked recipient
    draft.cc_addrs = []
    prefix = storage_prefix(draft.id, uuid.UUID(expected_owner))  # the send guard reads the owner from the key
    for filename, data in pdfs:
        key, digest = storage.put_bytes(settings, data, prefix=prefix)
        db.add(
            ComposeAttachment(
                draft_id=draft.id,
                filename=filename,
                content_type="application/pdf",
                size=len(data),
                storage_key=key,
                sha256=digest,
                av_status="clean",  # Money's own print report, fetched by the bridge
                is_inline=False,
            )
        )
    await db.flush()
    edited = final != proposed
    row.status = "approved"
    row.decided_by = person.id
    row.decided_at = datetime.now(UTC)
    row.final_payload = {**payload, "body": final, "draft_id": str(draft.id), "selected": numbers}
    if foreign:
        row.final_payload["ack"] = {
            "check": ACK_CHECK,
            "email": to[0].strip().lower(),
            "owner_money_id": expected_owner,
            "person_id": str(person.id),
            "account_id": str(ctx.account.id),
            "at": datetime.now(UTC).isoformat(),
        }
        audit(
            db,
            "money.delivery_note_other_customer_ack",
            account_id=ctx.account.id,
            person_id=person.id,
            object_type="ai_suggestion",
            object_id=str(row.id),
            details={
                "delivery_notes": numbers,
                "owner_money_id": expected_owner,
                "requester_email": to[0],
                "draft_id": str(draft.id),
            },
        )
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
            "delivery_notes": numbers,
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
