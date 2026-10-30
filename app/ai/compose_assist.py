"""Phase 2d compose AI panel (W4a / M17): Napíš za mňa, rewrite chips, Preložiť do…, Doplniť odpoveď na všetky otázky.

The model only ever sees and returns the person's own text — never the signature (CLAUDE.md: never invent a
signature) and never the quoted mail as something to edit. The result is a proposal; the editor shows it as a diff
and the person decides „Použiť“ / „Zahodiť“. Nothing is saved or sent here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.ai.categories import LANGUAGE_IDS
from app.ai.classify import neutralize_untrusted_wrapper
from app.ai.guards import PLACEHOLDER
from app.ai.provider import LLMProvider, LLMRequest
from app.ai.reply import COMPANY_NAME, render_prompt, thread_block
from app.mail.models import Message

Action = Literal["write", "shorter", "formal", "friendly", "grammar", "translate", "answer_all"]
TargetLanguage = Literal["sk", "cs", "en", "de", "pl", "hu"]
PROPOSE_TEXT = "propose_text"
MAX_TEXT = 20000

_LANGUAGE_NAMES = {"sk": "Slovak", "cs": "Czech", "en": "English", "de": "German", "pl": "Polish", "hu": "Hungarian"}

_TASKS: dict[str, str] = {
    "write": "Write the e-mail text from the employee's instruction: {instruction}. "
    "Answer the quoted e-mail if there is one. Language: the language of the quoted e-mail, else Slovak.",
    "shorter": "Make the text shorter and clearer. Same language.",
    "formal": "Make the text more formal (vykanie in Slovak/Czech, Sie in German). Same language.",
    "friendly": "Make the text friendlier while staying professional. Same language.",
    "grammar": "Fix spelling, grammar and punctuation only. Change nothing else. Same language.",
    "translate": "Translate the text into {language}. Keep names, numbers and [[DOPLNIŤ…]] placeholders as they are.",
    "answer_all": "Check that the text answers every question of the quoted e-mail. Add short answers for the "
    "missing ones (with [[DOPLNIŤ: …]] where a fact is unknown) and list those questions in `unanswered`.",
}


class TextProposal(BaseModel):
    text: str = Field(description="The full new text of the draft (no signature, no quote).")
    language: str = Field(description="Language code of the text: sk, cs, en, de, pl, hu or other.")
    unanswered: list[str] = Field(default_factory=list, description="answer_all: questions not answered before.")

    @field_validator("text")
    @classmethod
    def _text(cls, value: str) -> str:
        return value.strip()[:MAX_TEXT]

    @field_validator("language")
    @classmethod
    def _lang(cls, value: str) -> str:
        return value if value in LANGUAGE_IDS else "other"

    @field_validator("unanswered")
    @classmethod
    def _questions(cls, value: list[str]) -> list[str]:
        return [q[:200] for q in value[:10]]


def propose_text_tool() -> dict[str, object]:
    return {
        "name": PROPOSE_TEXT,
        "description": "Return the rewritten or written e-mail text for the compose panel (W4a).",
        "input_schema": TextProposal.model_json_schema(),
    }


@dataclass(slots=True)
class AssistResult:
    proposal: TextProposal | None
    model: str
    cost_usd: Decimal = Decimal("0")
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    status: str = "ok"  # ok | invalid_output | error
    error_class: str | None = None
    placeholders: list[str] = field(default_factory=list)


def task_text(action: Action, *, instruction: str | None, language: TargetLanguage | None) -> str:
    template = _TASKS[action]
    return template.format(
        instruction=neutralize_untrusted_wrapper((instruction or "").strip()[:2000]) or "(none)",
        language=_LANGUAGE_NAMES.get(language or "", "Slovak"),
    )


async def assist(
    provider: LLMProvider,
    model: str,
    *,
    action: Action,
    text: str,
    instruction: str | None,
    language: TargetLanguage | None,
    source_thread: list[Message],
    style_guide: str | None = None,
    knowledge: str = "(no matching company knowledge)",
) -> AssistResult:
    """One LLM call; never raises for provider errors (the caller records the run and answers 502)."""
    system = render_prompt("system_base", company_name=COMPANY_NAME, style_guide=style_guide or "(none yet)")
    user = render_prompt(
        "compose",
        task=task_text(action, instruction=instruction, language=language),
        thread=thread_block(source_thread) if source_thread else "(no quoted e-mail)",
        knowledge=knowledge,
        draft=neutralize_untrusted_wrapper(text[:MAX_TEXT]).replace("</draft>", "‹/draft›"),
    )
    try:
        response = await provider.complete(
            LLMRequest(
                purpose="draft",
                system=system,
                user=user,
                model=model,
                max_tokens=2000,
                tools=(propose_text_tool(),),
                tool_choice={"type": "tool", "name": PROPOSE_TEXT},
            )
        )
    except Exception as exc:
        return AssistResult(proposal=None, model=model, status="error", error_class=type(exc).__name__)
    result = AssistResult(
        proposal=None,
        model=response.model,
        cost_usd=response.cost_usd,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        latency_ms=response.latency_ms,
    )
    try:
        result.proposal = TextProposal.model_validate(dict(response.tool_input or {}))
    except ValidationError:
        result.status = "invalid_output"
        return result
    result.placeholders = [m.group(0) for m in PLACEHOLDER.finditer(result.proposal.text)]
    return result
