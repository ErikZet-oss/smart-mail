"""#222: create `delivery_note_attach` suggestions — deterministic, no model call.

Only when FEATURE_MONEY is on, at least one branch has the delivery note print report (11e), the mail is eligible for
AI, is a request (categories below) and names a delivery note (dodací list / DL / Lieferschein / delivery note).
Money down → nothing is created, the next run tries again.
"""

from __future__ import annotations

from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.guards import check
from app.ai.models import AiSuggestion, Classification
from app.ai.pipeline import message_eligible_for_ai
from app.core.audit import audit
from app.core.config import Settings
from app.mail.models import FolderMeta, Mailbox, Message
from app.money.bridge_client import BridgeClient, BridgeUnavailable
from app.money.delivery_note_attach import (
    SUGGESTION_TYPE,
    NotePick,
    any_report,
    asks_for_correction,
    draft_body,
    find_notes,
    note_json,
    pick_notes,
    wants_delivery_note,
)
from app.money.matching import counterparty

log = structlog.get_logger(__name__)
# a customer asking for a document; a supplier's own delivery note (`supplier_document`) never gets this card
CATEGORIES = ("document_request", "invoice_request", "shipping", "order_change", "complaint")
MAX_PER_RUN = 20


async def _candidates(db: AsyncSession, mailbox: Mailbox) -> list[tuple[Message, Classification]]:
    has_one = (
        select(AiSuggestion.id)
        .where(
            AiSuggestion.message_id == Message.id,
            AiSuggestion.suggestion_type == SUGGESTION_TYPE,
            AiSuggestion.status != "superseded",
        )
        .exists()
    )
    rows = await db.execute(
        select(Message, FolderMeta, Classification)
        .join(FolderMeta, FolderMeta.id == Message.folder_id)
        .join(Classification, Classification.message_id == Message.id)
        .where(
            Message.mailbox_id == mailbox.id,
            Classification.status == "done",
            Classification.category.in_(CATEGORIES),
            ~has_one,
        )
        .order_by(Message.received_at.desc())
        .limit(MAX_PER_RUN)
    )
    return [(m, c) for m, folder, c in rows.all() if message_eligible_for_ai(mailbox, folder, m)]


async def _add(
    db: AsyncSession,
    mailbox: Mailbox,
    message: Message,
    cls: Classification,
    pick: NotePick,
    *,
    corrected: bool,
    shadow: bool,
) -> None:
    checks = list(pick.checks)
    if corrected:
        checks.append(check("delivery_note_corrected", "warning"))
    for order in dict.fromkeys(i.ref for i in pick.items if i.how == "order"):
        checks.append(check("delivery_note_found_by_order", "warning", order=order))
    if any(i.how == "latest" for i in pick.items):
        checks.append(check("delivery_note_latest", "warning"))
    chosen = [i for i in pick.items if i.selected] or pick.items[:1]
    numbers = [i.note.number for i in chosen]
    orders = list(dict.fromkeys(i.ref for i in chosen if i.how == "order"))
    suggestion = AiSuggestion(
        mailbox_id=mailbox.id,
        message_id=message.id,
        thread_id=message.thread_id,
        suggestion_type=SUGGESTION_TYPE,
        payload={
            "to": [pick.email],
            "company_money_id": str(pick.company_money_id),
            "company_name": pick.company_name,
            "invoices": [note_json(i) for i in pick.items],  # same shape as invoice_attach (one card component)
            "pick": True,
            "language": cls.language,
            "body": draft_body(cls.language, numbers, orders),
            "orders": list(dict.fromkeys(i.ref for i in pick.items if i.how == "order")),
            "corrected": corrected,
            "foreign": pick.foreign,
            "owner_money_id": str(pick.owner_money_id) if pick.owner_money_id else None,
            "owner_name": pick.owner_name,
        },
        rationale=None,
        confidence=Decimal("0.95") if not any(c["level"] == "blocking" for c in checks) else Decimal("0.5"),
        checks=checks,
        batch_safe=False,  # a document of a customer always needs a person; never batch-approved
        status="pending",
        shadow=shadow,
        classification_id=cls.id,
    )
    db.add(suggestion)
    await db.flush()
    audit(
        db,
        "ai.suggestion_created",
        object_type="ai_suggestion",
        object_id=str(suggestion.id),
        details={"actor": "ai", "type": SUGGESTION_TYPE, "mailbox_id": str(mailbox.id), "shadow": shadow},
    )


async def suggest_delivery_note_attach(
    db: AsyncSession, mailbox: Mailbox, settings: Settings, *, shadow: bool, client: BridgeClient | None = None
) -> dict[str, int]:
    """The caller commits."""
    stats = {"candidates": 0, "created": 0, "not_asked": 0, "not_found": 0, "money_down": 0, "inactive": 0}
    if not settings.feature_money or not mailbox.ai_enabled:
        return stats
    if not await any_report(db):
        stats["inactive"] = 1  # no branch has the delivery note report yet (#222: off until Erik fills it in)
        return stats
    candidates = await _candidates(db, mailbox)
    if not candidates:
        return stats
    bridge = client or BridgeClient(settings)
    try:
        for message, cls in candidates:
            text = f"{message.subject or ''}\n{message.body_text or message.preview or ''}"
            if not wants_delivery_note(text):
                stats["not_asked"] += 1
                continue
            stats["candidates"] += 1
            email = counterparty(message, settings)
            if email is None:
                stats["not_found"] += 1
                continue
            try:
                found = await find_notes(db, settings, bridge, email=email, text=text, body_text=message.body_text)
                if not found:
                    stats["not_found"] += 1
                    continue
                pick = await pick_notes(db, settings, email=email, body_text=message.body_text, found=found)
            except BridgeUnavailable:
                stats["money_down"] += 1
                break
            await _add(db, mailbox, message, cls, pick, corrected=asks_for_correction(text), shadow=shadow)
            stats["created"] += 1
    finally:
        if client is None:
            await bridge.aclose()
    log.info("money.delivery_note_attach_suggested", mailbox_id=str(mailbox.id), **stats)
    return stats
