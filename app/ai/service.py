"""AI pipeline after mail sync — classify (Phase 2b); no reply suggestion cards."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.budget import budget_allows_call, budget_day_start
from app.ai.classify import classify_message
from app.ai.models import AiRun, Classification, FeatureFlag
from app.ai.pipeline import (
    folder_eligible_for_ai,
    message_eligible_for_ai,
    normalize_message_id_header,
    plan_attachments_for_ai,
)
from app.ai.pricing import estimate_purpose_cost_usd
from app.ai.provider import AnthropicLLMProvider, get_llm_provider
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
    start = budget_day_start(day)
    total = await db.scalar(
        select(func.coalesce(func.sum(AiRun.cost_usd), 0)).where(AiRun.created_at >= start, AiRun.status == "ok")
    )
    return Decimal(str(total or 0))


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
    """Classify eligible new messages. Private folders / history / budget gates apply."""
    stats = {
        "seen": 0,
        "eligible": 0,
        "skipped_history": 0,
        "skipped_folder": 0,
        "skipped_idempotent": 0,
        "skipped_budget": 0,
        "classified": 0,
        "rules_only": 0,
        "llm": 0,
        "unscanned_attachment_notes": 0,
    }
    if not mailbox.ai_enabled or mailbox.ai_enabled_at is None:
        log.info("ai.pipeline_skipped", mailbox_id=str(mailbox.id), reason="ai_disabled")
        return stats

    model = (settings.llm_model_classify or "").strip() or None
    estimate = estimate_purpose_cost_usd(model or "unknown", "classify")
    budget = Decimal(str(settings.ai_daily_budget_usd))
    spent = await daily_spend_usd(db)
    provider = get_llm_provider(settings)
    shadow = await shadow_mode_enabled(db)

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

    for message, folder in rows:
        stats["seen"] += 1
        if not folder_eligible_for_ai(folder):
            stats["skipped_folder"] += 1
            continue
        if not message_eligible_for_ai(mailbox, folder, message):
            stats["skipped_history"] += 1
            continue
        header = normalize_message_id_header(message.message_id)
        existing_done = await db.scalar(
            select(Classification.id)
            .where(
                Classification.message_id == message.id,
                Classification.status == "done",
            )
            .limit(1)
        )
        if existing_done is not None or await classification_exists_for_header(db, header):
            stats["skipped_idempotent"] += 1
            continue

        # Budget only when we may call the LLM (rules-only is free)
        atts = list((await db.execute(select(Attachment).where(Attachment.message_id == message.id))).scalars())
        plan = plan_attachments_for_ai(atts)
        if plan.note_codes:
            stats["unscanned_attachment_notes"] += 1

        # If the live Anthropic provider would be used, require budget before the call.
        live_llm = isinstance(provider, AnthropicLLMProvider) and bool(model)
        if live_llm and not budget_allows_call(spent_usd=spent, estimate_usd=estimate, budget_usd=budget):
            stats["skipped_budget"] += 1
            log.info("ai.pipeline_budget_stop", mailbox_id=str(mailbox.id), spent_usd=str(spent))
            break

        stats["eligible"] += 1
        outcome = await classify_message(
            provider=provider,
            model=model,
            from_email=message.from_email,
            from_name=message.from_name,
            subject=message.subject,
            body_text=message.body_text or message.preview,
            headers_text=None,
            attachment_names=[a.filename for a in atts],
            auth_results=message.auth_results,
            internal_domains=settings.internal_domain_list,
            extra_note_codes=list(plan.note_codes),
        )

        ai_run_id = None
        if outcome.source in {"llm", "rules+llm"} and outcome.model:
            if not budget_allows_call(
                spent_usd=spent, estimate_usd=outcome.ai_run_cost_usd or estimate, budget_usd=budget
            ):
                stats["skipped_budget"] += 1
                log.info("ai.pipeline_budget_stop", mailbox_id=str(mailbox.id), spent_usd=str(spent))
                break
            run = AiRun(
                purpose="classify",
                provider="anthropic",
                model=outcome.model,
                input_tokens=0,
                output_tokens=0,
                cost_usd=outcome.ai_run_cost_usd,
                latency_ms=0,
                mailbox_id=mailbox.id,
                message_id=message.id,
                status="ok",
            )
            db.add(run)
            await db.flush()
            ai_run_id = run.id
            spent += outcome.ai_run_cost_usd
            stats["llm"] += 1
        elif outcome.source == "rules":
            stats["rules_only"] += 1

        payload: dict[str, Any] = {
            "note_codes": outcome.note_codes,
            "source": outcome.source,
            "rule_id": outcome.rule.rule_id if outcome.rule else None,
            "entities": outcome.result.entities.model_dump(),
            "needs_reply": outcome.result.needs_reply,
            "sentiment": outcome.result.sentiment,
            "priority_reason": outcome.result.priority_reason,
            "deadline": outcome.result.deadline,
            "confidence": outcome.result.confidence,
        }
        # Upsert pending row or create new
        existing = await db.scalar(select(Classification).where(Classification.message_id == message.id).limit(1))
        if existing is None:
            existing = Classification(
                mailbox_id=mailbox.id,
                message_id=message.id,
                message_id_header=header,
                shadow=shadow,
            )
            db.add(existing)
        existing.category = outcome.result.category
        existing.language = outcome.result.language
        existing.priority = outcome.result.priority
        existing.payload = payload
        existing.status = "done"
        existing.ai_run_id = ai_run_id
        existing.shadow = shadow
        # store summary in payload (column set is fixed in 2a)
        payload["summary_sk"] = outcome.result.summary_sk
        existing.payload = payload
        stats["classified"] += 1

    if stats["classified"]:
        await db.flush()
    log.info("ai.pipeline_classify", mailbox_id=str(mailbox.id), **stats)
    return stats


async def ensure_shadow_flag(db: AsyncSession, *, enabled: bool = False) -> FeatureFlag:
    row = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == SHADOW_FLAG, FeatureFlag.person_id.is_(None)))
    if row is None:
        row = FeatureFlag(key=SHADOW_FLAG, person_id=None, enabled=enabled, data={})
        db.add(row)
        await db.flush()
    return row


def enable_ai_on_mailbox(mailbox: Mailbox, *, now: datetime | None = None) -> None:
    mailbox.ai_enabled = True
    if mailbox.ai_enabled_at is None:
        mailbox.ai_enabled_at = now or datetime.now(UTC)


def disable_ai_on_mailbox(mailbox: Mailbox) -> None:
    mailbox.ai_enabled = False


async def category_counts(db: AsyncSession, mailbox_id: uuid.UUID) -> dict[str, int]:
    """Unread-ish counts per category for AI TRIEDENIE (all done classifications)."""
    rows = await db.execute(
        select(Classification.category, func.count())
        .where(
            Classification.mailbox_id == mailbox_id,
            Classification.status == "done",
            Classification.category.is_not(None),
        )
        .group_by(Classification.category)
    )
    return {str(cat): int(cnt) for cat, cnt in rows.all() if cat}
