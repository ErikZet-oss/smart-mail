"""Phase 2a: provider selection, model id rules, Bedrock stub (D31)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import SecretStr

from app.ai.provider import (
    AnthropicLLMProvider,
    BedrockLLMProvider,
    LLMRequest,
    NullLLMProvider,
    estimate_cost_usd,
    get_llm_provider,
    resolve_model,
)
from app.core.config import Settings


def _settings(**kwargs: object) -> Settings:
    base: dict[str, object] = {
        "app_env": "test",
        "app_base_url": "http://test",
        "app_secret_key": "test-secret-key-that-is-long-enough-0123456789",
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
        "llm_provider": "anthropic",
        "anthropic_api_key": None,
        "llm_model_classify": "claude-haiku-4-5-20251001",
        "llm_model_draft": "claude-sonnet-4-5-20250929",
    }
    base.update(kwargs)
    return Settings(**base)  # type: ignore[arg-type]


def test_2a_resolve_model_rejects_latest() -> None:
    settings = _settings(llm_model_classify="latest")
    with pytest.raises(ValueError, match="latest"):
        resolve_model(settings, "classify", None)


def test_2a_resolve_model_requires_env() -> None:
    settings = _settings(llm_model_classify=None)
    with pytest.raises(ValueError, match="LLM_MODEL_"):
        resolve_model(settings, "classify", None)


def test_2a_bedrock_is_stub_only() -> None:
    settings = _settings(llm_provider="bedrock")
    provider = get_llm_provider(settings)
    assert isinstance(provider, BedrockLLMProvider)


@pytest.mark.asyncio
async def test_2a_bedrock_complete_raises() -> None:
    settings = _settings(llm_provider="bedrock", llm_model_classify="claude-haiku-4-5-20251001")
    provider = get_llm_provider(settings)
    with pytest.raises(NotImplementedError, match=r"D31|stub|anthropic"):
        await provider.complete(LLMRequest(purpose="classify", system="s", user="u"))


def test_2a_missing_key_uses_null_provider() -> None:
    provider = get_llm_provider(_settings(anthropic_api_key=None))
    assert isinstance(provider, NullLLMProvider)


def test_2a_estimate_cost_haiku_classify_ballpark() -> None:
    # ADR-011: ~1500 in + 200 out at Haiku 5.5 list → ~$0.00025
    cost = estimate_cost_usd("claude-haiku-5-5", 1500, 200)
    assert cost == Decimal("0.000250")


def test_2a_anthropic_key_selects_live_provider_class() -> None:
    settings = _settings(anthropic_api_key=SecretStr("sk-test"))
    provider = get_llm_provider(settings)
    assert isinstance(provider, AnthropicLLMProvider)
