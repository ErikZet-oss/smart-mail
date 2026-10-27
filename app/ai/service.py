"""Enqueue and gate AI work after mail sync (Phase 2a skeleton — no classify UI)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.budget import budget_allows_call, budget_day_start
from app.ai.models import AiRun, Classification, FeatureFlag
from app.ai.pipeline import (
    folder_eligible_for_ai,
    message_eligible_for_ai,
    normalize_message_id_header,
    plan_attachments_for_ai,
)
from app.ai.pricing import estimate_purpose_cost_usd
from app.core.config import Settings
from app.mail.models import Attachment, FolderMeta, Mailbox, Message

log = structlog.get_logger(__name__)

SHADOW_FLAG = "ai_shadow_mode"


async def shadow_mode_enabled(db: AsyncSession, person_id: uuid.UUID | None = None) -> bool:
    if person_id is not None:
        row = await db.scalar(
            select(FeatureFlag).where(FeatureFlag.key == SHADOW_FLAG, FeatureFlag.person_id == person_id)
        )
        if row is not None:
            return row.enabled
    global_row = await db.scalar(
        select(FeatureFlag).where(FeatureFlag.key == SHADOW_FLAG, FeatureFlag.person_id.is_(None))
    )
    return bool(global_row and global_row.enabled)


async def daily_spend_usd(db: AsyncSession, day: datetime | None = None) -> Decimal:
    """Sum of ok ai_runs cost since the start of the Europe/Bratislava calendar day."""
    start = budget_day_start(day)
    total = await db.scalar(
        select(func.coalesce(func.sum(AiRun.cost_usd), 0)).where(AiRun.created_at >= start, AiRun.status == "ok")
    )
    return Decimal(str(total or 0))


async def budget_allows(db: AsyncSession, settings: Settings, *, estimate_usd: Decimal) -> bool:
    """Check before a specific LLM call (estimate of that call)."""
    budget = Decimal(str(settings.ai_daily_budget_usd))
    spent = await daily_spend_usd(db)
    return budget_allows_call(spent_usd=spent, estimate_usd=estimate_usd, budget_usd=budget)


async def classification_exists_for_header(db: AsyncSession, message_id_header: str | None) -> bool:
    header = normalize_message_id_header(message_id_header)
    if not header:
        return False
    found = await db.scalar(select(Classification.id).where(Classification.message_id_header == header).limit(1))
    return found is not None


async def process_mailbox_ai(
    db: AsyncSession,
    mailbox: Mailbox,
    settings: Settings,
    *,
    message_ids: list[uuid.UUID] | None = None,
) -> dict[str, int]:
    """Select eligible new messages and record skip/idempotent markers. Classify lands in 2b.

    Budget is re-checked before each would-be LLM call (using a classify cost estimate), not once
    at the start of the batch. Unscanned attachments do not drop the message — body text proceeds
    with note code ``attachment_unscanned``.
    """
    stats = {
        "seen": 0,
        "eligible": 0,
        "skipped_history": 0,
        "skipped_folder": 0,
        "skipped_idempotent": 0,
        "skipped_budget": 0,
        "queued": 0,
        "unscanned_attachment_notes": 0,
    }
    if not mailbox.ai_enabled or mailbox.ai_enabled_at is None:
        log.info("ai.pipeline_skipped", mailbox_id=str(mailbox.id), reason="ai_disabled")
        return stats

    model = (settings.llm_model_classify or "").strip() or "unknown"
    estimate = estimate_purpose_cost_usd(model, "classify")
    budget = Decimal(str(settings.ai_daily_budget_usd))
    spent = await daily_spend_usd(db)

    q = (
        select(Message, FolderMeta)
        .join(FolderMeta, FolderMeta.id == Message.folder_id)
        .where(Message.mailbox_id == mailbox.id)
    )
    if message_ids:
        q = q.where(Message.id.in_(message_ids))
    else:
        q = q.where(Message.received_at.is_not(None), Message.received_at >= mailbox.ai_enabled_at)
    rows = (await db.execute(q)).all()
    shadow = await shadow_mode_enabled(db)

    for message, folder in rows:
        stats["seen"] += 1
        if not folder_eligible_for_ai(folder):
            stats["skipped_folder"] += 1
            continue
        if not message_eligible_for_ai(mailbox, folder, message):
            stats["skipped_history"] += 1
            continue
        header = normalize_message_id_header(message.message_id)
        existing_msg = await db.scalar(
            select(Classification.id).where(Classification.message_id == message.id).limit(1)
        )
        if existing_msg is not None or await classification_exists_for_header(db, header):
            stats["skipped_idempotent"] += 1
            continue

        # Per-call budget check (Bratislava day) before we would hit the LLM
        if not budget_allows_call(spent_usd=spent, estimate_usd=estimate, budget_usd=budget):
            stats["skipped_budget"] += 1
            log.info(
                "ai.pipeline_budget_stop",
                mailbox_id=str(mailbox.id),
                spent_usd=str(spent),
                estimate_usd=str(estimate),
                budget_usd=str(budget),
            )
            break

        atts = list((await db.execute(select(Attachment).where(Attachment.message_id == message.id))).scalars())
        plan = plan_attachments_for_ai(atts)
        payload: dict[str, object] = {"note_codes": list(plan.note_codes)}
        if plan.note_codes:
            stats["unscanned_attachment_notes"] += 1

        stats["eligible"] += 1
        db.add(
            Classification(
                mailbox_id=mailbox.id,
                message_id=message.id,
                message_id_header=header,
                status="pending",
                payload=payload,
                shadow=shadow,
            )
        )
        stats["queued"] += 1
        spent += estimate  # provisional — real cost lands in ai_runs when 2b calls the LLM

    if stats["queued"]:
        await db.flush()
    log.info("ai.pipeline_skeleton", mailbox_id=str(mailbox.id), **stats)
    return stats


async def ensure_shadow_flag(db: AsyncSession, *, enabled: bool = False) -> FeatureFlag:
    row = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == SHADOW_FLAG, FeatureFlag.person_id.is_(None)))
    if row is None:
        row = FeatureFlag(key=SHADOW_FLAG, person_id=None, enabled=enabled, data={})
        db.add(row)
        await db.flush()
    return row


def enable_ai_on_mailbox(mailbox: Mailbox, *, now: datetime | None = None) -> None:
    """Turn AI on: sets ai_enabled and ai_enabled_at (history before this instant stays out)."""
    mailbox.ai_enabled = True
    if mailbox.ai_enabled_at is None:
        mailbox.ai_enabled_at = now or datetime.now(UTC)


def disable_ai_on_mailbox(mailbox: Mailbox) -> None:
    mailbox.ai_enabled = False
