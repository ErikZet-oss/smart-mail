"""#143 „Zmeniť kategóriu“ (a person's correction) and „Znova zaradiť (AI)“ (classify again with today's prompt).

A correction is stored on the existing classification (`payload.corrected_*`, no new column). It wins: neither the
pipeline (which never touches a finished classification) nor „Znova zaradiť“ overwrites it. Corrections double as eval
labels (`eval_cli run --labels-from corrections`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.budget import budget_allows_call
from app.ai.category_settings import FALLBACK_ID, category_ids, load_category_data, prompt_categories
from app.ai.classify import classify_message
from app.ai.models import AiRun, Classification
from app.ai.org_settings import load_ai_limits
from app.ai.pipeline import normalize_message_id_header
from app.ai.pricing import estimate_purpose_cost_usd
from app.ai.provider import AnthropicLLMProvider, LLMProvider, get_llm_provider
from app.ai.service import daily_spend_usd, shadow_mode_enabled
from app.core.audit import audit
from app.core.config import Settings
from app.mail.models import Attachment, Mailbox, Message


class ReclassifyError(Exception):
    def __init__(self, code: str, status: int = 409) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def is_corrected(cls: Classification | None) -> bool:
    return bool(cls is not None and (cls.payload or {}).get("corrected_category"))


async def _classification(db: AsyncSession, message: Message) -> Classification | None:
    return await db.scalar(select(Classification).where(Classification.message_id == message.id).limit(1))


async def correct_category(
    db: AsyncSession, message: Message, category: str, *, person_id: uuid.UUID, account_id: uuid.UUID
) -> Classification:
    """Set the category by hand (only an enabled 17c category). The caller commits."""
    if category not in category_ids(prompt_categories(await load_category_data(db))):
        raise ReclassifyError("category_unknown", 422)
    cls = await _classification(db, message)
    before = cls.category if cls is not None else None
    if cls is None:
        cls = Classification(
            mailbox_id=message.mailbox_id,
            message_id=message.id,
            message_id_header=normalize_message_id_header(message.message_id),
            payload={},
        )
        db.add(cls)
    payload: dict[str, Any] = dict(cls.payload or {})
    if not payload.get("corrected_category"):
        payload["corrected_from"] = before  # what the AI said — kept from the first correction (eval label pair)
    payload.update(
        {
            "corrected_category": category,
            "corrected_by_person_id": str(person_id),
            "corrected_at": datetime.now(UTC).isoformat(),
        }
    )
    cls.category = category
    cls.payload = payload
    cls.status = "done"
    await db.flush()
    audit(
        db,
        "ai.category_corrected",
        account_id=account_id,
        person_id=person_id,
        object_type="message",
        object_id=str(message.id),
        details={"before": before, "after": category},
    )
    return cls


async def reclassify(
    db: AsyncSession,
    mailbox: Mailbox,
    message: Message,
    settings: Settings,
    *,
    person_id: uuid.UUID | None,
    account_id: uuid.UUID | None,
    provider: LLMProvider | None = None,
) -> Classification:
    """One classify call with today's prompt and 17c categories. Refuses a manual correction (409) and a spent
    budget (429). The caller commits."""
    cls = await _classification(db, message)
    if is_corrected(cls):
        raise ReclassifyError("category_corrected_manually", 409)
    provider = provider or get_llm_provider(settings)
    model = (settings.llm_model_classify or "").strip()
    if not model or not isinstance(provider, AnthropicLLMProvider):
        raise ReclassifyError("ai_unavailable", 409)
    budget = (await load_ai_limits(db, settings)).budget_usd
    if not budget_allows_call(
        spent_usd=await daily_spend_usd(db),
        estimate_usd=estimate_purpose_cost_usd(model, "classify"),
        budget_usd=budget,
    ):
        raise ReclassifyError("ai_budget_exceeded", 429)
    categories = prompt_categories(await load_category_data(db))
    atts = (await db.scalars(select(Attachment).where(Attachment.message_id == message.id))).all()
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
        recipients=[
            str(a.get("email")) for a in [*(message.to_addrs or []), *(message.cc_addrs or [])] if a.get("email")
        ],
        categories=categories,
    )
    run: AiRun | None = None
    if outcome.run_status is not None and outcome.model:
        run = AiRun(
            purpose="classify",
            provider="anthropic",
            model=outcome.model,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            cost_usd=outcome.ai_run_cost_usd,
            latency_ms=outcome.latency_ms,
            mailbox_id=mailbox.id,
            message_id=message.id,
            status=outcome.run_status,
            error_class=outcome.error_class,
        )
        db.add(run)
        await db.flush()
    if outcome.result is None or outcome.run_status != "ok":
        raise ReclassifyError("ai_failed", 502)  # the old classification stays as it was
    result = outcome.result
    if result.category not in category_ids(categories):
        result.category = FALLBACK_ID
    before = cls.category if cls is not None else None
    if cls is None:
        cls = Classification(
            mailbox_id=mailbox.id,
            message_id=message.id,
            message_id_header=normalize_message_id_header(message.message_id),
        )
        db.add(cls)
    cls.category = result.category
    cls.language = result.language
    cls.priority = result.priority
    cls.status = "done"
    cls.shadow = await shadow_mode_enabled(db)
    cls.ai_run_id = run.id if run else None
    cls.payload = {
        "note_codes": outcome.note_codes,
        "source": "reclassify",
        "entities": result.entities.model_dump(),
        "needs_reply": result.needs_reply,
        "sentiment": result.sentiment,
        "priority_reason": result.priority_reason,
        "deadline": result.deadline,
        "confidence": result.confidence,
        "summary_sk": result.summary_sk,
    }
    await db.flush()
    audit(
        db,
        "ai.reclassified",
        account_id=account_id,
        person_id=person_id,
        object_type="message",
        object_id=str(message.id),
        details={"before": before, "after": result.category, "cost_usd": str(outcome.ai_run_cost_usd or Decimal(0))},
    )
    return cls
