"""LLMProvider interface — Anthropic Claude API live; Bedrock is a stub (DECISIONS D31, ADR-011)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol, cast

import structlog

from app.ai.pricing import estimate_cost_usd
from app.core.config import Settings

log = structlog.get_logger(__name__)

Purpose = Literal["classify", "draft", "extract", "assistant", "embed"]

# One Anthropic client per process (timeout ~60 s, limited retries).
_anthropic_client: object | None = None
_anthropic_client_key: str | None = None
_ANTHROPIC_TIMEOUT_S = 60.0
_ANTHROPIC_MAX_RETRIES = 2


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


def _shared_anthropic_client(api_key: str) -> object:
    """Reuse one AsyncAnthropic client for the process lifetime."""
    global _anthropic_client, _anthropic_client_key
    if _anthropic_client is not None and _anthropic_client_key == api_key:
        return _anthropic_client
    from anthropic import AsyncAnthropic

    _anthropic_client = AsyncAnthropic(
        api_key=api_key,
        timeout=_ANTHROPIC_TIMEOUT_S,
        max_retries=_ANTHROPIC_MAX_RETRIES,
    )
    _anthropic_client_key = api_key
    return _anthropic_client


def reset_anthropic_client_for_tests() -> None:
    """Test helper — drop the process-wide client."""
    global _anthropic_client, _anthropic_client_key
    _anthropic_client = None
    _anthropic_client_key = None


class NullLLMProvider:
    """Used when Anthropic key is missing (dev/test) — never opens a network connection."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def complete(self, request: LLMRequest) -> LLMResponse:
        model = resolve_model(self._settings, request.purpose, request.model)
        raise RuntimeError(f"NullLLMProvider cannot complete (model={model}); set ANTHROPIC_API_KEY")


class AnthropicLLMProvider:
    def __init__(self, api_key: str, settings: Settings) -> None:
        self._api_key = api_key
        self._settings = settings
        self._client = _shared_anthropic_client(api_key)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        import time

        from anthropic.types import MessageParam

        model = resolve_model(self._settings, request.purpose, request.model)
        client = self._client
        started = time.perf_counter()
        # temperature omitted: current Anthropic SDK Messages.create typing has no temperature kwarg
        _ = request.temperature
        user_msg = cast(MessageParam, {"role": "user", "content": request.user})
        message = await client.messages.create(  # type: ignore[attr-defined]
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


_provider_singleton: LLMProvider | None = None
_provider_settings_id: int | None = None


def get_llm_provider(settings: Settings) -> LLMProvider:
    """Return a process-scoped provider (one Anthropic client, not per call)."""
    global _provider_singleton, _provider_settings_id
    sid = id(settings)
    if _provider_singleton is not None and _provider_settings_id == sid:
        return _provider_singleton
    if settings.llm_provider == "bedrock":
        provider: LLMProvider = BedrockLLMProvider(settings)
    else:
        key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        if not key:
            provider = NullLLMProvider(settings)
        else:
            provider = AnthropicLLMProvider(key, settings)
    _provider_singleton = provider
    _provider_settings_id = sid
    return provider


def reset_provider_for_tests() -> None:
    global _provider_singleton, _provider_settings_id
    _provider_singleton = None
    _provider_settings_id = None
    reset_anthropic_client_for_tests()


def model_for_purpose(settings: Settings, purpose: Purpose) -> str | None:
    mapping: dict[Purpose, str | None] = {
        "classify": settings.llm_model_classify,
        "draft": settings.llm_model_draft,
        "extract": settings.llm_model_extract,
        "assistant": settings.llm_model_assistant,
        "embed": settings.llm_model_embed,
    }
    return mapping[purpose]


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
    "reset_provider_for_tests",
    "resolve_model",
]
