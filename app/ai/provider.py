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
# Models that answer 400 "tool_choice: type "tool" and "any" are not supported for this model" (claude-sonnet-5-5 on
# the test server, 2026-10-30). Learned at run time: such a model gets tool_choice "auto" + an instruction to call the
# tool. Callers already treat a missing tool call as invalid output (reply) or parse JSON text (classify).
_NO_FORCED_TOOL_MODELS: set[str] = set()


@dataclass(frozen=True, slots=True)
class LLMRequest:
    purpose: Purpose
    system: str
    user: str
    model: str | None = None
    max_tokens: int = 1024
    temperature: float = 0
    # Anthropic tool use / JSON schema (CLAUDE.md §2). When set, the tool input is preferred over text.
    tools: tuple[dict[str, object], ...] | None = None
    tool_choice: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    latency_ms: int
    provider: str
    # Raw tool-use input when the model called a tool (JSON object as dict).
    tool_input: dict[str, object] | None = None


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
    _NO_FORCED_TOOL_MODELS.clear()
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
        kwargs = _request_kwargs(request, model, user_msg, forced_ok=model not in _NO_FORCED_TOOL_MODELS)
        try:
            message = await client.messages.create(**kwargs)  # type: ignore[attr-defined]
        except Exception as exc:
            detail = _bad_request_detail(exc)
            if detail is not None:
                # the API's own explanation (parameter errors only — never mail text), so the next 400 is diagnosable
                log.warning("ai.llm_bad_request", purpose=request.purpose, model=model, detail=detail[:300])
            if detail is None or not _forced_tool_unsupported(detail) or not _is_forced(request.tool_choice):
                raise
            # read-only LLM call: one retry with tool_choice "auto" is safe; remember the model for later calls
            _NO_FORCED_TOOL_MODELS.add(model)
            kwargs = _request_kwargs(request, model, user_msg, forced_ok=False)
            message = await client.messages.create(**kwargs)  # type: ignore[attr-defined]
        latency_ms = int((time.perf_counter() - started) * 1000)
        text_parts: list[str] = []
        tool_input: dict[str, object] | None = None
        for block in message.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_parts.append(str(getattr(block, "text", "")))
            elif btype == "tool_use" and tool_input is None:
                raw_in = getattr(block, "input", None)
                if isinstance(raw_in, dict):
                    tool_input = cast(dict[str, object], raw_in)
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
            used_tool=tool_input is not None,
        )
        return LLMResponse(
            text="".join(text_parts),
            model=model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=cost,
            latency_ms=latency_ms,
            provider="anthropic",
            tool_input=tool_input,
        )


def _is_forced(tool_choice: dict[str, object] | None) -> bool:
    return tool_choice is not None and tool_choice.get("type") in ("tool", "any")


def _forced_tool_unsupported(detail: str) -> bool:
    text = detail.lower()
    return "tool_choice" in text and "not supported" in text


def _bad_request_detail(exc: Exception) -> str | None:
    """The API error message of a 400, or None for any other failure."""
    try:
        from anthropic import BadRequestError
    except ImportError:  # pragma: no cover - the SDK is a runtime dependency
        return None
    if not isinstance(exc, BadRequestError):
        return None
    body = exc.body
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return str(error["message"])
    return str(exc)


def _request_kwargs(request: LLMRequest, model: str, user_msg: object, *, forced_ok: bool) -> dict[str, object]:
    system = request.system
    kwargs: dict[str, object] = {"model": model, "max_tokens": request.max_tokens, "messages": [user_msg]}
    if request.tools:
        kwargs["tools"] = list(request.tools)
        choice = request.tool_choice
        if choice is not None and _is_forced(choice) and not forced_ok:
            name = choice.get("name")
            target = f"the tool `{name}`" if isinstance(name, str) else "one of the tools"
            system = f"{system}\n\nAnswer only by calling {target}; do not reply with plain text."
            choice = {"type": "auto"}
        if choice is not None:
            kwargs["tool_choice"] = choice
    kwargs["system"] = system
    return kwargs


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
