"""Phase 2e 17e: rules in natural language — structured, confirmed, executed deterministically (#110)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from pydantic import SecretStr, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AiRule, Classification
from app.ai.provider import LLMResponse
from app.ai.service import process_mailbox_ai
from app.ai.user_rules import MailFacts, StructuredRule, describe, rule_matches
from app.auth.models import Role
from app.core.audit import AuditLog
from app.core.config import Settings
from app.mail.models import FolderMeta, Mailbox, Message
from tests.conftest import Client, FakeMailServer
from tests.test_ai_classify_review_2b import ScriptedAnthropic, _ok_response
from tests.test_knowledge_2e import _admin

ENABLED = datetime(2026, 10, 27, 10, 0, tzinfo=UTC)
SUPPLIER = {
    "match": "all",
    "conditions": [{"field": "from_domain", "op": "equals", "value": "fixtech.example"}],
    "actions": [{"type": "set_category", "value": "supplier_document"}, {"type": "no_reply"}],
}


def _mail(**over: Any) -> MailFacts:
    base: dict[str, Any] = {
        "from_email": "fakturacia@fixtech.example",
        "subject": "Faktura E3/2026/0412",
        "body": "V prílohe faktúra.",
        "attachment_names": ("E3.pdf",),
    }
    base.update(over)
    return MailFacts(**base)


# --- structure + matching ------------------------------------------------------------------------------------------


def test_2e_rule_matching_and_description() -> None:
    rule = StructuredRule.model_validate(SUPPLIER)
    assert rule_matches(rule, _mail())
    assert not rule_matches(rule, _mail(from_email="jan@ina.example"))
    assert describe(rule) == (
        "Ak doména odosielateľa je „fixtech.example“, tak kategória = Doklady dodávateľov, "
        "netreba odpovedať (AI nepripraví odpoveď)."
    )
    any_rule = StructuredRule.model_validate(
        {
            "match": "any",
            "conditions": [
                {"field": "subject", "op": "contains", "value": "URGENT"},
                {"field": "attachment_name", "op": "ends_with", "value": ".isdoc"},
            ],
            "actions": [{"type": "set_priority", "value": "urgent"}],
        }
    )
    assert rule_matches(any_rule, _mail(subject="urgent: stop výroby"))  # case-insensitive
    assert rule_matches(any_rule, _mail(subject="x", attachment_names=("faktura.ISDOC",)))
    assert not rule_matches(any_rule, _mail(subject="x"))


@pytest.mark.parametrize(
    "bad",
    [
        {**SUPPLIER, "actions": [{"type": "set_category", "value": "send_mail"}]},
        {**SUPPLIER, "actions": [{"type": "needs_reply"}, {"type": "no_reply"}]},
        {**SUPPLIER, "actions": []},  # „pošli ďalej …“ — not an allowed action, the model returns none
        {**SUPPLIER, "conditions": [{"field": "subject", "op": "contains", "value": " "}]},
        {**SUPPLIER, "actions": [{"type": "forward", "value": "x@y.example"}]},
    ],
)
def test_2e_rule_validation_refuses(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        StructuredRule.model_validate(bad)


# --- deterministic execution in the pipeline ------------------------------------------------------------------------


async def _mailbox_with_message(db: AsyncSession, **message: Any) -> tuple[Mailbox, Message]:
    mailbox = Mailbox(
        email=f"eshop-{uuid4().hex[:8]}@smartmail.test",
        imap_host="localhost",
        imap_port=1143,
        imap_security="none",
        ai_enabled=True,
        ai_enabled_at=ENABLED,
    )
    db.add(mailbox)
    await db.flush()
    folder = FolderMeta(mailbox_id=mailbox.id, name="INBOX", special_use="inbox", subscribed=True, selectable=True)
    db.add(folder)
    await db.flush()
    fields: dict[str, Any] = {
        "mailbox_id": mailbox.id,
        "folder_id": folder.id,
        "uid": 1,
        "message_id": f"<{uuid4().hex}@fixtech.example>",
        "subject": "Faktura E3/2026/0412",
        "from_email": "fakturacia@fixtech.example",
        "body_text": "Dobrý den, v příloze faktura.",
        "received_at": ENABLED + timedelta(hours=1),
        "flags": [],
    }
    fields.update(message)
    msg = Message(**fields)
    db.add(msg)
    await db.flush()
    return mailbox, msg


def _live(settings: Settings) -> Settings:
    return settings.model_copy(
        update={"anthropic_api_key": SecretStr("sk-test"), "llm_model_classify": "claude-haiku-5-5"}
    )


async def test_2e_category_rule_decides_without_llm(
    db: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.ai.service as service

    rule = AiRule(nl_text="Faktúry od Fixtechu sú doklady dodávateľov", structured=SUPPLIER)
    db.add(rule)
    mailbox, msg = await _mailbox_with_message(db)
    llm = ScriptedAnthropic([])
    monkeypatch.setattr(service, "get_llm_provider", lambda _s: llm)
    stats = await process_mailbox_ai(db, mailbox, _live(settings))
    assert stats["classified"] == 1 and llm.calls == []
    row = await db.scalar(select(Classification).where(Classification.message_id == msg.id))
    assert row is not None and row.category == "supplier_document"
    assert row.payload["source"] == "user_rule" and row.payload["user_rule_id"] == str(rule.id)
    assert row.payload["needs_reply"] is False  # no reply card will be prepared
    await db.refresh(rule)
    assert rule.last_used_at is not None


async def test_2e_priority_rule_overrides_the_classifier(
    db: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.ai.service as service

    db.add(
        AiRule(
            nl_text="Všetko od Kovo Trnava je urgentné",
            structured={
                "match": "all",
                "conditions": [{"field": "from_email", "op": "ends_with", "value": "@kovo.example"}],
                "actions": [{"type": "set_priority", "value": "urgent"}],
            },
        )
    )
    mailbox, msg = await _mailbox_with_message(
        db, from_email="nakup@kovo.example", subject="Dopyt M8", body_text="Cena M8?"
    )
    llm = ScriptedAnthropic([_ok_response()])
    monkeypatch.setattr(service, "get_llm_provider", lambda _s: llm)
    await process_mailbox_ai(db, mailbox, _live(settings))
    assert len(llm.calls) == 1  # no category in the rule → the classifier still runs
    row = await db.scalar(select(Classification).where(Classification.message_id == msg.id))
    assert row is not None and row.category == "inquiry" and row.priority == "urgent"


async def test_2e_disabled_or_broken_rules_do_nothing(
    db: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.ai.service as service

    db.add(AiRule(nl_text="vypnuté", structured=SUPPLIER, enabled=False))
    db.add(AiRule(nl_text="pokazené", structured={"conditions": []}))
    mailbox, _msg = await _mailbox_with_message(db)
    llm = ScriptedAnthropic([_ok_response()])
    monkeypatch.setattr(service, "get_llm_provider", lambda _s: llm)
    await process_mailbox_ai(db, mailbox, _live(settings))
    assert len(llm.calls) == 1


# --- API ----------------------------------------------------------------------------------------------------------


def _rule_response(tool_input: dict[str, Any]) -> LLMResponse:
    return LLMResponse(
        text="",
        model="claude-haiku-5-5",
        input_tokens=200,
        output_tokens=60,
        cost_usd=Decimal("0.000400"),
        latency_ms=300,
        provider="anthropic",
        tool_input=tool_input,
    )


@pytest.fixture
def rule_llm(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> ScriptedAnthropic:
    import app.api.settings_ai as api

    app.state.settings = _live(app.state.settings)
    scripted = ScriptedAnthropic([])
    monkeypatch.setattr(api, "get_llm_provider", lambda _s: scripted)
    return scripted


async def test_2e_preview_confirm_save_toggle_delete(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, rule_llm: ScriptedAnthropic
) -> None:
    await _admin(client, db, mail_server)
    rule_llm._responses = [_rule_response(SUPPLIER)]
    nl = "Faktúry od Fixtechu sú doklady dodávateľov, odpoveď netreba"
    r = await client.send_json("POST", "/api/settings/ai/rules/preview", {"nl_text": nl})
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["description"].startswith("Ak doména odosielateľa je „fixtech.example“")
    assert (await db.scalar(select(AiRule).limit(1))) is None  # preview saves nothing

    r = await client.send_json("POST", "/api/settings/ai/rules", {"nl_text": nl, "structured": preview["structured"]})
    assert r.status_code == 200, r.text
    rule = r.json()
    assert rule["enabled"] is True and rule["description"] == preview["description"]
    r = await client.send_json("PATCH", f"/api/settings/ai/rules/{rule['id']}", {"enabled": False})
    assert r.json()["enabled"] is False
    assert [x["id"] for x in (await client.get("/api/settings/ai/rules")).json()] == [rule["id"]]
    assert (await client.send_json("DELETE", f"/api/settings/ai/rules/{rule['id']}")).status_code == 200
    actions = {e.action for e in (await db.execute(select(AuditLog))).scalars()}
    assert {"ai.rule_created", "ai.rule_updated", "ai.rule_deleted"} <= actions


async def test_2e_preview_refuses_actions_outside_the_list(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, rule_llm: ScriptedAnthropic
) -> None:
    await _admin(client, db, mail_server)
    rule_llm._responses = [_rule_response({**SUPPLIER, "actions": []})]
    r = await client.send_json(
        "POST", "/api/settings/ai/rules/preview", {"nl_text": "Faktúry od Fixtechu pošli účtovníčke"}
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "rule_not_understood"
    bad = {**SUPPLIER, "actions": [{"type": "set_category", "value": "spam_send"}]}
    r = await client.send_json("POST", "/api/settings/ai/rules", {"nl_text": "x y z", "structured": bad})
    assert r.status_code == 422


async def test_2e_try_on_last_messages(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, rule_llm: ScriptedAnthropic
) -> None:
    from tests.test_mail_messages_1d import _seed_inbox
    from tests.test_mail_sync_1c import env

    await _admin(client, db, mail_server)
    mailbox = await db.scalar(select(Mailbox).limit(1))
    assert mailbox is not None
    await _seed_inbox(db, mailbox, env(1, subject="Faktura E3"), env(2, subject="Dopyt"))
    rule = {
        "match": "all",
        "conditions": [{"field": "subject", "op": "contains", "value": "faktura"}],
        "actions": [{"type": "set_category", "value": "supplier_document"}],
    }
    r = await client.send_json("POST", "/api/settings/ai/rules/test", {"structured": rule})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["checked"] == 2 and [m["subject"] for m in out["matches"]] == ["Faktura E3"]


async def test_2e_rules_are_admin_only(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await _admin(client, db, mail_server, role=Role.sales)
    assert (await client.get("/api/settings/ai/rules")).status_code == 403
