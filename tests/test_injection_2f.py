"""Injection suite (AI_ASSISTANT §12, ≥ 20 fictional fixtures in fixtures/ai/injection/cases.json).

A real model cannot run in CI, so every fixture plays the worst case: the scripted model *obeys* the malicious text,
and the test proves the code still holds — wrappers stay closed, the recipient never comes from the model, invented
facts block, unknown categories and rule actions are refused, approve never sends."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.classify import classify_message
from app.ai.compose_assist import assist
from app.ai.models import AiSuggestion, KnowledgeCard
from app.ai.provider import LLMResponse
from app.ai.reply import suggest_replies
from app.ai.retrieval import knowledge_block
from app.ai.style_profile import generate as generate_profile
from app.ai.user_rules import StructuredRule
from app.core.config import Settings
from app.mail.compose_models import ComposeDraft
from tests.conftest import Client, FakeMailServer
from tests.test_ai_classify_review_2b import ScriptedAnthropic, ScriptedLLM, _ok_response
from tests.test_ai_reply_2c import _draft_response, _seed, _settings

CASES: list[dict[str, Any]] = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "ai" / "injection" / "cases.json").read_text(encoding="utf-8")
)["cases"]


def _by(vector: str) -> list[dict[str, Any]]:
    return [c for c in CASES if c["vector"] == vector]


def test_inj_suite_has_at_least_20_fictional_cases() -> None:
    assert len(CASES) >= 20 and all(c["fictional"] for c in CASES)
    assert len({c["id"] for c in CASES}) == len(CASES)


@pytest.mark.parametrize("case", _by("classify"), ids=lambda c: c["id"])
async def test_inj_classify(case: dict[str, Any]) -> None:
    llm = ScriptedLLM([_ok_response(tool_input=case["model"])])
    outcome = await classify_message(
        provider=llm,  # type: ignore[arg-type]
        model="claude-haiku-5-5",
        from_email="utocnik@evil.example",
        from_name="Útočník",
        subject="Test",
        body_text=case["body"],
        headers_text=None,
        attachment_names=[],
        auth_results=None,
        internal_domains=["smartmail.test"],
    )
    expect = case["expect"]
    request = llm.calls[0]
    assert request.user.count("</untrusted_email>") == 1, "the mail can never close its wrapper"
    assert outcome.result is not None
    if "category_not" in expect:
        assert outcome.result.category != expect["category_not"]
        assert outcome.result.priority in {"urgent", "normal", "low"}
    if "summary_max" in expect:
        assert len(outcome.result.summary_sk) <= expect["summary_max"]
    if "note" in expect:
        assert expect["note"] in outcome.note_codes


@pytest.mark.parametrize("case", _by("reply"), ids=lambda c: c["id"])
async def test_inj_reply(case: dict[str, Any], db: AsyncSession, settings: Settings) -> None:
    mailbox, message = await _seed(db, body=case["body"], notes=case.get("notes") or [])
    sender = message.from_email
    llm = ScriptedAnthropic([_draft_response(**case["model"])])
    await suggest_replies(db, mailbox, _settings(settings), spent_usd=Decimal("0"), shadow=True, provider=llm)
    row = await db.scalar(select(AiSuggestion).where(AiSuggestion.message_id == message.id))
    assert row is not None
    expect = case["expect"]
    levels = {c["id"]: c["level"] for c in row.checks}
    request = llm.calls[0]
    assert request.user.count("</untrusted_email>") == 1
    assert row.payload["to"] == [sender], "the recipient always comes from the message, never from the model"
    assert row.shadow is True
    if "blocking" in expect:
        assert levels.get(expect["blocking"]) == "blocking", levels
    if "warning" in expect:
        assert levels.get(expect["warning"]) == "warning", levels
    if "literal_in_prompt" in expect:
        assert expect["literal_in_prompt"] in request.user


@pytest.mark.parametrize("case", _by("compose"), ids=lambda c: c["id"])
async def test_inj_compose(case: dict[str, Any]) -> None:
    llm = ScriptedLLM(
        [
            LLMResponse(
                text="",
                model="claude-sonnet-5-5",
                input_tokens=1,
                output_tokens=1,
                cost_usd=Decimal("0"),
                latency_ms=1,
                provider="anthropic",
                tool_input=case["model"],
            )
        ]
    )
    await assist(
        llm,  # type: ignore[arg-type]
        "claude-sonnet-5-5",
        action="write" if case.get("instruction") else "shorter",
        text=case.get("text", ""),
        instruction=case.get("instruction"),
        language=None,
        source_thread=[],
    )
    user = llm.calls[0].user
    assert user.count("</draft>") == 1
    assert "</untrusted_email>" not in user.replace("(no quoted e-mail)", "")


@pytest.mark.parametrize("case", _by("rule"), ids=lambda c: c["id"])
def test_inj_rule_cannot_express_external_effects(case: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        StructuredRule.model_validate(case["model"])


@pytest.mark.parametrize("case", _by("knowledge"), ids=lambda c: c["id"])
def test_inj_knowledge_card(case: dict[str, Any]) -> None:
    block = knowledge_block([KnowledgeCard(title="Karta", body=case["body"])])
    assert block.count("</company_knowledge>") == 1 and "<untrusted_email>" not in block


@pytest.mark.parametrize("case", _by("style"), ids=lambda c: c["id"])
async def test_inj_style_sample(case: dict[str, Any]) -> None:
    llm = ScriptedLLM(
        [
            LLMResponse(
                text="",
                model="m",
                input_tokens=1,
                output_tokens=1,
                cost_usd=Decimal("0"),
                latency_ms=1,
                provider="anthropic",
                tool_input={"profile_sk": "- Vyká."},
            )
        ]
    )
    await generate_profile(llm, "m", [case["sample"]])  # type: ignore[arg-type]
    assert llm.calls[0].user.count("</sample>") == 1


@pytest.mark.parametrize("case", _by("approve"), ids=lambda c: c["id"])
async def test_inj_approve_never_sends(
    case: dict[str, Any], client: Client, db: AsyncSession, mail_server: FakeMailServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.suggestions as api
    from tests.test_ai_approve_2c import _seed as seed_suggestion
    from tests.test_mail_messages_1d import _signed_in

    async def no_imap(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(api, "sync_draft_to_imap", no_imap)
    mailbox = await _signed_in(client, db, mail_server)
    _message, suggestion = await seed_suggestion(db, mailbox)
    r = await client.send_json("POST", f"/api/suggestions/{suggestion.id}/approve", {})
    assert r.status_code == 200, r.text
    await db.close()
    draft = await db.get(ComposeDraft, r.json()["draft_id"])
    assert draft is not None and draft.status == case["expect"]["draft_status"]
