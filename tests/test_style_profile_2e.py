"""Phase 2e Settings 07: personal style profile — opt-in, from the person's own sent text only, used in drafts."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.provider import LLMResponse
from app.auth.models import Account, Person
from app.core.audit import AuditLog
from app.mail.compose_models import ComposeDraft
from app.mail.models import Mailbox
from tests.conftest import Client, FakeMailServer
from tests.test_ai_classify_review_2b import ScriptedLLM
from tests.test_mail_messages_1d import _signed_in

QUOTE = '<blockquote data-sm-quote="1"><p>Zákazník Novák píše o cene 1234 €.</p></blockquote>'
SIGNATURE = '<div data-sm-signature="1"><p>Jana Testová · 0900 000 000</p></div>'


def _profile_response(**tool: Any) -> LLMResponse:
    return LLMResponse(
        text="",
        model="claude-sonnet-5-5",
        input_tokens=3000,
        output_tokens=200,
        cost_usd=Decimal("0.010000"),
        latency_ms=900,
        provider="anthropic",
        tool_input={"profile_sk": "- Vyká.\n- Začína „Dobrý deň,“.\n- Krátke odseky.", **tool},
    )


@pytest.fixture
def llm(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> ScriptedLLM:
    import app.api.compose_ai as compose_ai
    import app.api.settings_ai as api

    app.state.settings = app.state.settings.model_copy(
        update={"anthropic_api_key": SecretStr("sk-test"), "llm_model_draft": "claude-sonnet-5-5"}
    )
    scripted = ScriptedLLM([])
    monkeypatch.setattr(api, "get_llm_provider", lambda _s: scripted)
    monkeypatch.setattr(compose_ai, "get_llm_provider", lambda _s: scripted)
    return scripted


async def _sent(db: AsyncSession, mailbox: Mailbox, n: int) -> Person:
    account = await db.scalar(select(Account).where(Account.email == mailbox.email))
    assert account is not None and account.person_id is not None
    person = await db.get(Person, account.person_id)
    assert person is not None
    for i in range(n):
        db.add(
            ComposeDraft(
                mailbox_id=mailbox.id,
                account_id=account.id,
                person_id=person.id,
                status="sent",
                subject=f"Re: dopyt {i}",
                body_html=f"<p>Dobrý deň, ďakujeme za dopyt číslo {i}, posielame ponuku.</p>{QUOTE}{SIGNATURE}",
            )
        )
    await db.commit()
    return person


async def test_2e_profile_needs_opt_in_and_enough_mail(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, llm: ScriptedLLM
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    await _sent(db, mailbox, 3)
    r = await client.send_json("POST", "/api/settings/ai/style-profile/generate", {})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "opt_in_required"
    await client.send_json("PUT", "/api/settings/ai/style-profile", {"opt_in": True, "text": ""})
    r = await client.send_json("POST", "/api/settings/ai/style-profile/generate", {})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "not_enough_mail"
    assert llm.calls == []


async def test_2e_profile_from_own_text_only_and_switch_off_deletes_it(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, llm: ScriptedLLM
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    await _sent(db, mailbox, 6)
    await client.send_json("PUT", "/api/settings/ai/style-profile", {"opt_in": True, "text": ""})
    llm._responses = [_profile_response()]
    r = await client.send_json("POST", "/api/settings/ai/style-profile/generate", {})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["opt_in"] is True and out["source_count"] == 6 and out["text"].startswith("- Vyká.")
    [request] = llm.calls
    assert request.user.count("<sample>") == 6 and "posielame ponuku" in request.user
    assert "Novák" not in request.user and "0900" not in request.user  # no quote, no signature
    entries = list((await db.execute(select(AuditLog).where(AuditLog.action.like("ai.style_profile%")))).scalars())
    assert {e.action for e in entries} == {"ai.style_profile_updated", "ai.style_profile_generated"}
    assert all("Vyká" not in str(e.details) for e in entries)

    r = await client.send_json("PUT", "/api/settings/ai/style-profile", {"opt_in": True, "text": "Píšem stručne."})
    assert r.json()["text"] == "Píšem stručne."
    r = await client.send_json("PUT", "/api/settings/ai/style-profile", {"opt_in": False, "text": "Píšem stručne."})
    assert r.json() == {"opt_in": False, "text": "", "generated_at": None, "source_count": 0}


async def test_2e_compose_panel_uses_the_writers_profile(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, llm: ScriptedLLM
) -> None:
    from datetime import UTC, datetime

    mailbox = await _signed_in(client, db, mail_server)
    mailbox.ai_enabled, mailbox.ai_enabled_at = True, datetime(2026, 10, 1, tzinfo=UTC)
    await db.commit()
    await client.send_json("PUT", "/api/settings/ai/style-profile", {"opt_in": True, "text": "Píšem stručne."})
    created = await client.send_json("POST", "/api/mail/mailboxes/default/compose", {"mode": "new"})
    draft_id = created.json()["id"]
    llm._responses = [
        LLMResponse(
            text="",
            model="claude-sonnet-5-5",
            input_tokens=10,
            output_tokens=10,
            cost_usd=Decimal("0"),
            latency_ms=1,
            provider="anthropic",
            tool_input={"text": "Dobrý deň.", "language": "sk", "unanswered": []},
        )
    ]
    r = await client.send_json("POST", f"/api/mail/compose/{draft_id}/ai", {"action": "shorter", "text": "Ahoj"})
    assert r.status_code == 200, r.text
    assert "Personal style of the person writing this e-mail:\nPíšem stručne." in llm.calls[0].system
