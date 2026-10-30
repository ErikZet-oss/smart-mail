"""W4a / M17 compose AI panel (Phase 2d): one endpoint for Napíš za mňa, the rewrite chips, Preložiť do… and
Doplniť odpoveď na všetky otázky. Returns a proposal only — the editor shows the diff, the person applies it."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.ai.budget import budget_allows_call
from app.ai.compose_assist import Action, TargetLanguage, assist
from app.ai.models import AiRun
from app.ai.org_settings import load_ai_limits
from app.ai.pricing import estimate_purpose_cost_usd
from app.ai.provider import get_llm_provider
from app.ai.reply import thread_messages
from app.ai.retrieval import default_retriever, knowledge_block, style_guide_text
from app.ai.service import daily_spend_usd
from app.ai.style_profile import profile_for_prompt
from app.api.compose import _get_draft
from app.api.mail import _ai_provider_configured, fail
from app.auth.deps import DB, ActivePerson, Auth, SettingsDep
from app.core.audit import audit
from app.mail.models import Mailbox, Message

router = APIRouter(prefix="/api/mail/compose", tags=["compose-ai"])  # next to the compose API


class AssistIn(BaseModel):
    action: Action
    text: str = Field(default="", max_length=20000)  # the person's own text (no signature, no quote)
    instruction: str | None = Field(default=None, max_length=2000)  # Napíš za mňa
    language: TargetLanguage | None = None  # Preložiť do…


class AssistOut(BaseModel):
    action: str
    text: str
    language: str
    unanswered: list[str]
    placeholders: list[str]


@router.post("/{draft_id}/ai")
async def compose_ai(
    draft_id: uuid.UUID, body: AssistIn, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> AssistOut:
    draft = await _get_draft(db, ctx, draft_id)
    mailbox = await db.get(Mailbox, draft.mailbox_id)
    model = (settings.llm_model_draft or "").strip()
    if mailbox is None or not mailbox.ai_enabled or mailbox.ai_enabled_at is None:
        raise fail(409, "ai_unavailable")
    if not _ai_provider_configured(settings) or not model:
        raise fail(409, "ai_unavailable")
    if body.action == "write" and not (body.instruction or "").strip():
        raise fail(422, "instruction_required")
    if body.action != "write" and not body.text.strip():
        raise fail(422, "text_required")
    if body.action == "translate" and body.language is None:
        raise fail(422, "language_required")
    budget = (await load_ai_limits(db, settings)).budget_usd
    if not budget_allows_call(
        spent_usd=await daily_spend_usd(db), estimate_usd=estimate_purpose_cost_usd(model, "draft"), budget_usd=budget
    ):
        raise fail(429, "ai_budget_exceeded")

    source = await db.get(Message, draft.in_reply_to_message_id) if draft.in_reply_to_message_id else None
    thread = await thread_messages(db, source) if source is not None and source.mailbox_id == mailbox.id else []
    result = await assist(
        get_llm_provider(settings),
        model,
        action=body.action,
        text=body.text,
        instruction=body.instruction,
        language=body.language,
        source_thread=thread,
        style_guide=await writer_style(db, person.id),
        knowledge=knowledge_block(
            await default_retriever().knowledge(
                db, "\n".join([body.instruction or "", body.text, *(m.body_text or m.preview or "" for m in thread)])
            )
        ),
    )
    db.add(
        AiRun(
            purpose="draft",
            provider="anthropic",
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=result.cost_usd,
            latency_ms=result.latency_ms,
            mailbox_id=mailbox.id,
            message_id=source.id if source is not None else None,
            status=result.status,
            error_class=result.error_class,
        )
    )
    audit(
        db,
        "ai.compose_assist",
        person_id=person.id,
        object_type="compose_draft",
        object_id=str(draft.id),
        details={"actor": "user", "action": body.action, "status": result.status},
    )
    await db.commit()
    if result.proposal is None:
        raise fail(502, "ai_failed")
    return AssistOut(
        action=body.action,
        text=result.proposal.text,
        language=result.proposal.language,
        unanswered=result.proposal.unanswered if body.action == "answer_all" else [],
        placeholders=result.placeholders,
    )


async def writer_style(db: DB, person_id: uuid.UUID) -> str | None:
    """Company style guide plus the writer's own style profile (opted in), for the person's drafts (07)."""
    parts = [await style_guide_text(db)]
    personal = await profile_for_prompt(db, person_id)
    if personal:
        parts.append(f"Personal style of the person writing this e-mail:\n{personal}")
    text = "\n\n".join(p for p in parts if p)
    return text or None
