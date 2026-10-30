"""Pilot 2026-10-30: claude-sonnet-5-5 answers 400 „tool_choice: type "tool" and "any" are not supported for this
model.“ — every reply draft and every „Napíš za mňa“ failed. The provider must retry once with tool_choice "auto",
remember the model, and log the API's explanation of any other 400."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import pytest

from app.ai.provider import AnthropicLLMProvider, LLMRequest, reset_provider_for_tests
from app.core.config import Settings

UNSUPPORTED = 'tool_choice: type "tool" and "any" are not supported for this model.'
TOOL = {"name": "propose_reply", "description": "x", "input_schema": {"type": "object", "properties": {}}}


def _bad_request(message: str) -> anthropic.BadRequestError:
    response = httpx.Response(400, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    body = {"type": "error", "error": {"type": "invalid_request_error", "message": message}}
    return anthropic.BadRequestError(f"Error code: 400 - {body}", response=response, body=body)


def _ok() -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", input={"body": "Dobrý deň"})],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


class FakeMessages:
    def __init__(self, reject_forced: bool, error: str = UNSUPPORTED) -> None:
        self.calls: list[dict[str, Any]] = []
        self.reject_forced = reject_forced
        self.error = error

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        choice = kwargs.get("tool_choice") or {}
        if self.reject_forced and choice.get("type") in ("tool", "any"):
            raise _bad_request(self.error)
        return _ok()


def _provider(messages: FakeMessages) -> AnthropicLLMProvider:
    reset_provider_for_tests()
    provider = AnthropicLLMProvider("sk-ant-test", Settings(llm_model_draft="claude-sonnet-5-5"))
    provider._client = SimpleNamespace(messages=messages)  # type: ignore[assignment]
    return provider


def _request() -> LLMRequest:
    return LLMRequest(
        purpose="draft",
        system="System.",
        user="Ďakujem",
        tools=(TOOL,),
        tool_choice={"type": "tool", "name": "propose_reply"},
    )


async def test_forced_tool_unsupported_retries_with_auto_and_remembers_model() -> None:
    messages = FakeMessages(reject_forced=True)
    provider = _provider(messages)

    first = await provider.complete(_request())
    assert first.tool_input == {"body": "Dobrý deň"}
    assert [c["tool_choice"]["type"] for c in messages.calls] == ["tool", "auto"]
    assert "propose_reply" in messages.calls[1]["system"]

    await provider.complete(_request())  # learned: no second failing call
    assert [c["tool_choice"]["type"] for c in messages.calls] == ["tool", "auto", "auto"]


async def test_model_with_forced_tool_support_is_unchanged() -> None:
    messages = FakeMessages(reject_forced=False)
    await _provider(messages).complete(_request())
    assert len(messages.calls) == 1
    assert messages.calls[0]["tool_choice"] == {"type": "tool", "name": "propose_reply"}
    assert messages.calls[0]["system"] == "System."


async def test_other_bad_request_is_raised_not_retried() -> None:
    messages = FakeMessages(reject_forced=True, error="max_tokens: too large")
    with pytest.raises(anthropic.BadRequestError):
        await _provider(messages).complete(_request())
    assert len(messages.calls) == 1
