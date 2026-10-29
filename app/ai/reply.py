"""Phase 2c reply suggestions (AI_ASSISTANT §2 step 6–7, §6, §9): plan step for **reply** only, no Money tools.

After classification, a message that needs a reply gets one `ai_suggestions` row of type `reply` with the draft body,
the guard checks and the shadow flag. Nothing is sent or saved to Koncepty here — that happens only on approve.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.budget import budget_allows_call
from app.ai.categories import LANGUAGE_IDS
from app.ai.classify import neutralize_untrusted_wrapper
from app.ai.guards import SECURITY_PREFIX, reply_checks
from app.ai.models import AiRun, AiSuggestion, Classification
from app.ai.pipeline import message_eligible_for_ai, normalize_message_id_header
from app.ai.pricing import estimate_purpose_cost_usd
from app.ai.provider import AnthropicLLMProvider, LLMProvider, LLMRequest, NullLLMProvider, get_llm_provider
from app.core.audit import audit
from app.core.config import Settings
from app.mail.models import FolderMeta, Mailbox, Message

log = structlog.get_logger(__name__)

COMPANY_NAME = "Smart s.r.o."
# Categories that get a reply card (§2 step 6 without the Money-backed ones' tools).
REPLY_CATEGORIES = frozenset(
    {
        "inquiry",
        "order",
        "order_change",
        "order_cancel",
        "invoice_request",
        "complaint",
        "shipping",
        "payment",
        "document_request",
    }
)
THREAD_MESSAGES = 5
MESSAGE_CHARS = 3000
MAX_WORDS = 180
PROPOSE_REPLY = "propose_reply"
_PROMPTS = Path(__file__).parent / "prompts"
_PAID = ("ok", "invalid_output", "error")

BodyLoader = Callable[[Message], Awaitable[None]]


class ReplyProposal(BaseModel):
    body: str = Field(description="Reply body only, no subject and no signature.")
    language: str = Field(description="Language code of the draft: sk, cs, en, de, pl, hu or other.")
    rationale_sk: str = Field(default="", description="One sentence in Slovak: why this reply.")
    confidence: float = Field(default=0.5, description="0–1, how sure the draft is complete and correct.")

    @field_validator("body")
    @classmethod
    def _body(cls, value: str) -> str:
        return value.strip()[:8000]

    @field_validator("language")
    @classmethod
    def _lang(cls, value: str) -> str:
        return value if value in LANGUAGE_IDS else "other"

    @field_validator("rationale_sk")
    @classmethod
    def _why(cls, value: str) -> str:
        return value[:200]

    @field_validator("confidence")
    @classmethod
    def _conf(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))


def propose_reply_tool() -> dict[str, object]:
    return {
        "name": PROPOSE_REPLY,
        "description": "Propose one reply to the last e-mail of the thread (AI_ASSISTANT §5 propose_reply).",
        "input_schema": ReplyProposal.model_json_schema(),
    }


_VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render_prompt(name: str, **values: object) -> str:
    """`{{ name }}` placeholders of `app/ai/prompts/<name>.md` (AI_ASSISTANT §13). A missing value is an error, and the
    values are inserted once — text from an e-mail can never introduce a new placeholder."""
    template = (_PROMPTS / f"{name}.md").read_text(encoding="utf-8")

    def sub(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise KeyError(f"prompt {name}: missing value for {key}")
        return str(values[key])

    return _VAR.sub(sub, template)


def register_for(language: str) -> str:
    return {"sk": "vykanie", "cs": "vykání", "de": "Sie"}.get(language, "polite, formal")


def thread_block(messages: list[Message]) -> str:
    """Last messages, each wrapped as untrusted data (§9), oldest first."""
    parts = []
    for m in messages:
        body = neutralize_untrusted_wrapper((m.body_text or m.preview or "")[:MESSAGE_CHARS])
        parts.append(
            "<untrusted_email>\n"
            f"From: {neutralize_untrusted_wrapper(m.from_name)} <{m.from_email or ''}>\n"
            f"Date: {m.received_at.isoformat() if m.received_at else ''}\n"
            f"Subject: {neutralize_untrusted_wrapper(m.subject)}\n\n{body}\n"
            "</untrusted_email>"
        )
    return "\n".join(parts)


def reply_subject(subject: str | None) -> str:
    base = (subject or "").strip()
    return base if base.lower().startswith(("re:", "odp:", "aw:")) else f"Re: {base}".strip()


@dataclass(slots=True)
class ReplyStats:
    candidates: int = 0
    created: int = 0
    skipped_budget: int = 0
    llm_error: int = 0
    llm_invalid: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "candidates": self.candidates,
            "created": self.created,
            "skipped_budget": self.skipped_budget,
            "llm_error": self.llm_error,
            "llm_invalid": self.llm_invalid,
        }


async def _candidates(db: AsyncSession, mailbox: Mailbox) -> list[tuple[Message, FolderMeta, Classification]]:
    has_reply = (
        select(AiSuggestion.id)
        .where(AiSuggestion.message_id == Message.id, AiSuggestion.suggestion_type == "reply")
        .exists()
    )
    rows = await db.execute(
        select(Message, FolderMeta, Classification)
        .join(FolderMeta, FolderMeta.id == Message.folder_id)
        .join(Classification, Classification.message_id == Message.id)
        .where(
            Message.mailbox_id == mailbox.id,
            Classification.status == "done",
            Classification.category.in_(REPLY_CATEGORIES),
            ~has_reply,
        )
    )
    out = []
    for message, folder, cls in rows.all():
        if not (cls.payload or {}).get("needs_reply"):
            continue
        if not message_eligible_for_ai(mailbox, folder, message):
            continue  # private folder, Koncepty/Odoslané/Kôš/Nevyžiadaná, history before ai_enabled_at
        if (message.from_email or "").lower() == mailbox.email.lower():
            continue  # our own message
        out.append((message, folder, cls))
    return out


async def _reply_exists_for_header(db: AsyncSession, header: str | None) -> bool:
    """Once per Message-ID across mailboxes (§2): another copy already has a reply suggestion."""
    if not header:
        return False
    found = await db.scalar(
        select(AiSuggestion.id)
        .join(Classification, Classification.message_id == AiSuggestion.message_id)
        .where(AiSuggestion.suggestion_type == "reply", Classification.message_id_header == header)
        .limit(1)
    )
    return found is not None


async def thread_messages(db: AsyncSession, message: Message) -> list[Message]:
    if message.thread_id is None:
        return [message]
    rows = await db.execute(
        select(Message)
        .where(Message.thread_id == message.thread_id, Message.received_at <= message.received_at)
        .order_by(Message.received_at.desc())
        .limit(THREAD_MESSAGES)
    )
    found = list(rows.scalars())
    if message not in found:
        found = [message, *found[: THREAD_MESSAGES - 1]]
    return list(reversed(found))


async def _recipient_known(db: AsyncSession, mailbox: Mailbox, address: str, message: Message) -> bool:
    """Earlier mail from this address in the mailbox (not the message being answered)."""
    count = await db.scalar(
        select(func.count())
        .select_from(Message)
        .where(
            Message.mailbox_id == mailbox.id,
            func.lower(Message.from_email) == address.lower(),
            Message.id != message.id,
        )
    )
    return bool(count)


async def suggest_replies(
    db: AsyncSession,
    mailbox: Mailbox,
    settings: Settings,
    *,
    spent_usd: Decimal,
    shadow: bool,
    provider: LLMProvider | None = None,
    load_body: BodyLoader | None = None,
) -> dict[str, int]:
    """Create `reply` suggestions for classified messages that need a reply. The caller commits."""
    stats = ReplyStats()
    if not mailbox.ai_enabled or mailbox.ai_enabled_at is None:
        return stats.as_dict()
    provider = provider or get_llm_provider(settings)
    model = (settings.llm_model_draft or "").strip() or None
    if isinstance(provider, NullLLMProvider) or not model:
        return stats.as_dict()  # drafts need the LLM; no fallback text
    estimate = estimate_purpose_cost_usd(model, "draft")
    budget = Decimal(str(settings.ai_daily_budget_usd))
    live = isinstance(provider, AnthropicLLMProvider)
    spent = spent_usd

    for message, _folder, cls in await _candidates(db, mailbox):
        stats.candidates += 1
        header = normalize_message_id_header(message.message_id)
        if await _reply_exists_for_header(db, header):
            continue
        if live and not budget_allows_call(spent_usd=spent, estimate_usd=estimate, budget_usd=budget):
            stats.skipped_budget += 1
            log.info("ai.reply_budget_stop", mailbox_id=str(mailbox.id), spent_usd=str(spent))
            break
        if load_body is not None and not message.body_text:
            try:
                await load_body(message)
            except Exception as exc:  # body fetch is best effort; the preview still gives context
                log.warning("ai.reply_body_unavailable", message_id=str(message.id), error=type(exc).__name__)
        thread = await thread_messages(db, message)
        context = thread_block(thread)
        language = cls.language or "other"
        system = render_prompt("system_base", company_name=COMPANY_NAME, style_guide="(zatiaľ nenastavený — Phase 2e)")
        user = render_prompt(
            "draft",
            language=language,
            register=register_for(language),
            max_words=MAX_WORDS,
            category=cls.category,
            priority=cls.priority or "normal",
            thread=context,
        )
        try:
            response = await provider.complete(
                LLMRequest(
                    purpose="draft",
                    system=system,
                    user=user,
                    model=model,
                    max_tokens=1500,
                    tools=(propose_reply_tool(),),
                    tool_choice={"type": "tool", "name": PROPOSE_REPLY},
                )
            )
        except Exception as exc:  # never crash the pipeline; no row, retried on the next run
            stats.llm_error += 1
            db.add(
                AiRun(
                    purpose="draft",
                    provider="anthropic",
                    model=model,
                    mailbox_id=mailbox.id,
                    message_id=message.id,
                    status="error",
                    error_class=type(exc).__name__,
                )
            )
            log.warning("ai.reply_error", message_id=str(message.id), error=type(exc).__name__)
            continue

        run = AiRun(
            purpose="draft",
            provider=response.provider,
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=response.cost_usd,
            latency_ms=response.latency_ms,
            mailbox_id=mailbox.id,
            message_id=message.id,
            status="ok",
        )
        db.add(run)
        spent += response.cost_usd
        try:
            proposal = ReplyProposal.model_validate(dict(response.tool_input or {}))
        except ValidationError:
            run.status = "invalid_output"
            stats.llm_invalid += 1
            continue
        await db.flush()

        recipient = message.from_email
        notes: list[str] = list((cls.payload or {}).get("note_codes") or [])
        checks = reply_checks(
            body=proposal.body,
            context=context,
            recipient=recipient,
            recipient_known=bool(recipient) and await _recipient_known(db, mailbox, recipient or "", message),
            internal_domains=settings.internal_domain_list,
            security_notes=[n for n in notes if n.startswith(SECURITY_PREFIX)],
            expected_language=language,
            proposal_language=proposal.language,
        )
        payload: dict[str, Any] = {
            "to": [recipient] if recipient else [],
            "subject": reply_subject(message.subject),
            "body": proposal.body,
            "language": proposal.language,
            "in_reply_to": message.message_id,
            "category": cls.category,
            "ai_run_id": str(run.id),
        }
        suggestion = AiSuggestion(
            mailbox_id=mailbox.id,
            message_id=message.id,
            thread_id=message.thread_id,
            suggestion_type="reply",
            payload=payload,
            rationale=proposal.rationale_sk or None,
            confidence=Decimal(str(round(proposal.confidence, 3))),
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
            details={
                "actor": "ai",
                "type": "reply",
                "mailbox_id": str(mailbox.id),
                "shadow": shadow,
                "blocking": sum(1 for c in checks if c["level"] == "blocking"),
            },
        )
        stats.created += 1

    log.info("ai.pipeline_reply", mailbox_id=str(mailbox.id), **stats.as_dict())
    return stats.as_dict()


async def recheck_reply(
    db: AsyncSession, mailbox: Mailbox, settings: Settings, message: Message, *, body: str, language: str | None
) -> list[dict[str, Any]]:
    """The same guards as at creation, on the body being approved (CLAUDE.md §8: the backend re-runs all checks)."""
    cls = await db.scalar(select(Classification).where(Classification.message_id == message.id).limit(1))
    notes: list[str] = list(((cls.payload or {}) if cls else {}).get("note_codes") or [])
    recipient = message.from_email
    return reply_checks(
        body=body,
        context=thread_block(await thread_messages(db, message)),
        recipient=recipient,
        recipient_known=bool(recipient) and await _recipient_known(db, mailbox, recipient or "", message),
        internal_domains=settings.internal_domain_list,
        security_notes=[n for n in notes if n.startswith(SECURITY_PREFIX)],
        expected_language=cls.language if cls else None,
        proposal_language=language,
    )
