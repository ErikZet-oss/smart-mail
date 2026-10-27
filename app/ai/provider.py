"""LLMProvider interface — Anthropic Claude API live; Bedrock is a stub (DECISIONS D31, ADR-011)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

import structlog

from app.core.config import Settings

log = structlog.get_logger(__name__)

Purpose = Literal["classify", "draft", "extract", "assistant", "embed"]

# Rough list-price fallbacks (USD / MTok) for cost logging when the SDK omits usage pricing.
# Real spend still comes from token counts × these rates; never use for money/document math.
_DEFAULT_RATES: dict[str, tuple[Decimal, Decimal]] = {
    "haiku": (Decimal("0.10"), Decimal("0.50")),
    "sonnet": (Decimal("2"), Decimal("10")),
    "opus": (Decimal("5"), Decimal("25")),
}


@dataclass(frozen=True, slots=True)
class LLMRequest:
    purpose: Purpose
    system: str
    user: str
    model: str | None = None
    max_tokens: int = 1024
    temperature: float = 0


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    latency_ms: int
    provider: str


class LLMProvider(Protocol):
    async def complete(self, request: LLMRequest) -> LLMResponse: ...


def resolve_model(settings: Settings, purpose: Purpose, explicit: str | None) -> str:
    """Concrete model id from the request or env — never 'latest'."""
    candidates: dict[Purpose, str | None] = {
        "classify": settings.llm_model_classify,
        "draft": settings.llm_model_draft,
        "extract": settings.llm_model_extract,
        "assistant": settings.llm_model_assistant,
        "embed": settings.llm_model_embed,
    }
    model = (explicit or candidates[purpose] or "").strip()
    if not model:
        raise ValueError(f"LLM_MODEL_{purpose.upper()} (or request.model) must be set to a concrete model id")
    if model.lower() == "latest":
        raise ValueError("model id must be concrete; 'latest' is not allowed (DECISIONS D31)")
    return model


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    """Order-of-magnitude USD from published Anthropic list rates (ADR-011)."""
    lower = model.lower()
    in_rate, out_rate = Decimal("1"), Decimal("5")  # Haiku 4.5-ish fallback
    for key, rates in _DEFAULT_RATES.items():
        if key in lower:
            in_rate, out_rate = rates
            break
    cost = (Decimal(input_tokens) / Decimal(1_000_000)) * in_rate + (
        Decimal(output_tokens) / Decimal(1_000_000)
    ) * out_rate
    return cost.quantize(Decimal("0.000001"))


class NullLLMProvider:
    """Used when Anthropic key is missing (dev/test) — never opens a network connection."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def complete(self, request: LLMRequest) -> LLMResponse:
        # Still enforce model id rules so misconfiguration fails in test the same way as prod.
        model = resolve_model(self._settings, request.purpose, request.model)
        raise RuntimeError(f"NullLLMProvider cannot complete (model={model}); set ANTHROPIC_API_KEY")


class AnthropicLLMProvider:
    def __init__(self, api_key: str, settings: Settings) -> None:
        self._api_key = api_key
        self._settings = settings

    async def complete(self, request: LLMRequest) -> LLMResponse:
        import time
        from typing import cast

        from anthropic import AsyncAnthropic
        from anthropic.types import MessageParam

        model = resolve_model(self._settings, request.purpose, request.model)
        client = AsyncAnthropic(api_key=self._api_key)
        started = time.perf_counter()
        # temperature omitted: current Anthropic SDK Messages.create typing has no temperature kwarg
        _ = request.temperature
        user_msg = cast(MessageParam, {"role": "user", "content": request.user})
        message = await client.messages.create(
            model=model,
            max_tokens=request.max_tokens,
            system=request.system,
            messages=[user_msg],
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        text_parts: list[str] = []
        for block in message.content:
            if getattr(block, "type", None) == "text":
                text_parts.append(str(getattr(block, "text", "")))
        usage = message.usage
        in_tok = int(usage.input_tokens)
        out_tok = int(usage.output_tokens)
        cost = estimate_cost_usd(model, in_tok, out_tok)
        log.info(
            "ai.llm_complete",
            purpose=request.purpose,
            model=model,
            provider="anthropic",
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=str(cost),
            latency_ms=latency_ms,
        )
        return LLMResponse(
            text="".join(text_parts),
            model=model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=cost,
            latency_ms=latency_ms,
            provider="anthropic",
        )


class BedrockLLMProvider:
    """Interface stub only (D31). Not a chosen backend."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def complete(self, request: LLMRequest) -> LLMResponse:
        resolve_model(self._settings, request.purpose, request.model)
        raise NotImplementedError(
            "LLM_PROVIDER=bedrock is a stub; DECISIONS D31 selects the Anthropic Claude API "
            "(set LLM_PROVIDER=anthropic)"
        )


def get_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "bedrock":
        return BedrockLLMProvider(settings)
    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
    if not key:
        return NullLLMProvider(settings)
    return AnthropicLLMProvider(key, settings)


def model_for_purpose(settings: Settings, purpose: Purpose) -> str | None:
    mapping: dict[Purpose, str | None] = {
        "classify": settings.llm_model_classify,
        "draft": settings.llm_model_draft,
        "extract": settings.llm_model_extract,
        "assistant": settings.llm_model_assistant,
        "embed": settings.llm_model_embed,
    }
    return mapping[purpose]


# Keep Any import used by Protocol consumers / mypy re-exports.
__all__ = [
    "AnthropicLLMProvider",
    "BedrockLLMProvider",
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "NullLLMProvider",
    "Purpose",
    "estimate_cost_usd",
    "get_llm_provider",
    "model_for_purpose",
    "resolve_model",
]
