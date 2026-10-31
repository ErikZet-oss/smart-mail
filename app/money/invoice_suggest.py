"""Phase 3d: create `invoice_attach` suggestions for „invoice_request“ mail — deterministic, no model call.

Only when FEATURE_MONEY is on, the mail is eligible for AI, the sender is matched strongly to a Money company and
at least one written invoice number belongs to that company. Money down → nothing is created, the next run tries again.
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
from app.money.invoice_attach import SUGGESTION_TYPE, draft_body, evaluate, invoice_json, invoice_refs
from app.money.matching import counterparty

log = structlog.get_logger(__name__)
CATEGORY = "invoice_request"
MAX_PER_RUN = 20


async def _candidates(db: AsyncSession, mailbox: Mailbox) -> list[tuple[Message, Classification]]:
    has_one = (
        select(AiSuggestion.id)
        .where(AiSuggestion.message_id == Message.id, AiSuggestion.suggestion_type == SUGGESTION_TYPE)
        .exists()
    )
    rows = await db.execute(
        select(Message, FolderMeta, Classification)
        .join(FolderMeta, FolderMeta.id == Message.folder_id)
        .join(Classification, Classification.message_id == Message.id)
        .where(
            Message.mailbox_id == mailbox.id,
            Classification.status == "done",
            Classification.category == CATEGORY,
            ~has_one,
        )
        .order_by(Message.received_at.desc())
        .limit(MAX_PER_RUN)
    )
    return [(m, c) for m, folder, c in rows.all() if message_eligible_for_ai(mailbox, folder, m)]


async def suggest_invoice_attach(
    db: AsyncSession, mailbox: Mailbox, settings: Settings, *, shadow: bool, client: BridgeClient | None = None
) -> dict[str, int]:
    """The caller commits."""
    stats = {"candidates": 0, "created": 0, "no_refs": 0, "not_owned": 0, "money_down": 0}
    if not settings.feature_money or not mailbox.ai_enabled:
        return stats
    candidates = await _candidates(db, mailbox)
    if not candidates:
        return stats
    bridge = client or BridgeClient(settings)
    try:
        for message, cls in candidates:
            stats["candidates"] += 1
            email = counterparty(message, settings)
            refs = invoice_refs(f"{message.subject or ''}\n{message.body_text or message.preview or ''}")
            if email is None or not refs:
                stats["no_refs"] += 1
                continue
            try:
                ev = await evaluate(
                    db, settings, bridge, email=email, body_text=message.body_text, refs=refs, language=cls.language
                )
            except BridgeUnavailable:
                stats["money_down"] += 1
                break
            if not ev.invoices:
                stats["not_owned"] += 1  # nothing to send to this recipient — never a card with another's invoice
                continue
            numbers = [i.number for i in ev.invoices]
            # a number of another customer stays out of the draft; on the card it is only a warning, so the
            # sender's own invoices can still be prepared (approve checks the owner again, live)
            checks = [
                check("invoice_other_customer", "warning", number=c["params"].get("number"))
                if c["id"] == "recipient_not_document_owner"
                else c
                for c in ev.checks
            ]
            suggestion = AiSuggestion(
                mailbox_id=mailbox.id,
                message_id=message.id,
                thread_id=message.thread_id,
                suggestion_type=SUGGESTION_TYPE,
                payload={
                    "to": [ev.email],
                    "company_money_id": str(ev.company_money_id),
                    "company_name": ev.company_name,
                    "invoices": [invoice_json(i) for i in ev.invoices],
                    "refs": refs,
                    "language": cls.language,
                    "body": draft_body(cls.language, numbers),
                },
                rationale=None,
                confidence=Decimal("0.95") if not any(c["level"] == "blocking" for c in checks) else Decimal("0.5"),
                checks=checks,
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
            stats["created"] += 1
    finally:
        if client is None:
            await bridge.aclose()
    log.info("money.invoice_attach_suggested", mailbox_id=str(mailbox.id), **stats)
    return stats
