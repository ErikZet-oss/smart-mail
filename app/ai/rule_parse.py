"""17e: the Slovak rule sentence → `StructuredRule` (preview only; the person confirms the code-generated text)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pydantic import ValidationError

from app.ai.categories import CATEGORIES
from app.ai.classify import neutralize_untrusted_wrapper
from app.ai.provider import LLMProvider, LLMRequest
from app.ai.user_rules import StructuredRule

STRUCTURE_RULE = "structure_rule"

SYSTEM = (
    "You turn one company e-mail rule written in Slovak into the structure_rule tool input. "
    "Conditions use only these fields: from_email, from_domain, subject, body, attachment_name, has_attachment; "
    "ops: contains, equals, ends_with. Actions only: set_category (value = a category id), set_priority "
    "(urgent|normal|low), needs_reply, no_reply. Categories: "
    + ", ".join(f"{c.id} ({c.label_sk})" for c in CATEGORIES)
    + ". If the rule asks for anything else (sending, forwarding, moving, deleting, writing to Money), "
    "return an empty actions list."
)


@dataclass(slots=True)
class ParseResult:
    rule: StructuredRule | None
    model: str
    cost_usd: Decimal = Decimal("0")
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    status: str = "ok"
    error_class: str | None = None


def structure_rule_tool() -> dict[str, object]:
    return {
        "name": STRUCTURE_RULE,
        "description": "Structured form of one e-mail triage rule (Settings 17e).",
        "input_schema": StructuredRule.model_json_schema(),
    }


async def parse_rule(provider: LLMProvider, model: str, nl_text: str) -> ParseResult:
    try:
        response = await provider.complete(
            LLMRequest(
                purpose="classify",
                system=SYSTEM,
                user=f"<rule>\n{neutralize_untrusted_wrapper(nl_text[:1000]).replace('</rule>', '')}\n</rule>",
                model=model,
                max_tokens=600,
                tools=(structure_rule_tool(),),
                tool_choice={"type": "tool", "name": STRUCTURE_RULE},
            )
        )
    except Exception as exc:
        return ParseResult(rule=None, model=model, status="error", error_class=type(exc).__name__)
    result = ParseResult(
        rule=None,
        model=response.model,
        cost_usd=response.cost_usd,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        latency_ms=response.latency_ms,
    )
    try:
        result.rule = StructuredRule.model_validate(dict(response.tool_input or {}))
    except ValidationError:
        result.status = "invalid_output"
    return result
