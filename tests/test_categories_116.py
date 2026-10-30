"""#116 17c: company categories — descriptions feed the classify prompt, max 15 custom, switching off never breaks
stored classifications."""

from __future__ import annotations

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.categories import CATEGORIES
from app.ai.category_settings import (
    SECTION_CATEGORIES,
    all_categories,
    category_lookup,
    custom_id,
    prompt_categories,
    triage_categories,
)
from app.ai.classify import classify_message, classify_system
from app.ai.models import OrgSettings
from app.ai.service import process_mailbox_ai
from app.auth.models import Role
from app.core.audit import AuditLog
from app.core.config import Settings
from tests.conftest import Client, FakeMailServer
from tests.test_ai_classify_review_2b import ScriptedAnthropic, _ok_response, _seed_ai_mailbox
from tests.test_knowledge_2e import PASSWORD, _admin

CUSTOM = {"id": "x_kurier", "label": "Kuriér", "description": "zásielky DPD a GLS", "color": "info"}


def test_116_defaults_are_the_builtins() -> None:
    assert [c.id for c in prompt_categories(None)] == [c.id for c in CATEGORIES]


def test_116_switched_off_category_leaves_prompt_but_stays_known() -> None:
    data = {"builtin": {"order": {"enabled": False}, "other": {"enabled": False}}}
    ids = {c.id for c in prompt_categories(data)}
    assert "order" not in ids and "other" in ids  # „Iné“ is the fallback and stays on
    assert "order" not in {c.id for c in triage_categories(data)}
    assert "order" in category_lookup(data)  # stored classifications keep their view


def test_116_admin_description_and_custom_category_feed_the_prompt() -> None:
    data = {"builtin": {"inquiry": {"description": "dopyty na skrutky a matice"}}, "custom": [CUSTOM]}
    system = classify_system(prompt_categories(data))
    assert "inquiry — Dopyty: dopyty na skrutky a matice" in system
    assert "x_kurier — Kuriér: zásielky DPD a GLS" in system


def test_116_bad_custom_rows_are_ignored_and_max_15() -> None:
    customs = [{"id": f"x_c{i}", "label": f"K{i}"} for i in range(20)]
    customs += [{"id": "inquiry", "label": "clash"}, {"id": "nope", "label": "bad id"}]
    rows = all_categories({"custom": customs})
    assert len([r for r in rows if not r[2]]) == 15


def test_116_custom_id_slug() -> None:
    assert custom_id("Kuriér – DPD") == "x_kurier_dpd" and custom_id("!!!") == "x_kategoria"


async def _classify(answer: str, categories: object) -> tuple[str | None, str | None]:
    llm = ScriptedAnthropic([_ok_response(tool_input={**_ok_response().tool_input, "category": answer})])  # type: ignore[dict-item]
    outcome = await classify_message(
        provider=llm,
        model="claude-haiku-4-5-20251001",
        from_email="a@customer.test",
        from_name="A",
        subject="Zásielka",
        body_text="Kde je moja zásielka?",
        headers_text=None,
        attachment_names=[],
        auth_results=None,
        internal_domains=["smartsro.sk"],
        categories=categories,  # type: ignore[arg-type]
    )
    return (outcome.result.category if outcome.result else None), outcome.run_status


async def test_116_model_may_answer_a_custom_but_not_a_switched_off_category() -> None:
    data = {"builtin": {"shipping": {"enabled": False}}, "custom": [CUSTOM]}
    assert await _classify("x_kurier", prompt_categories(data)) == ("x_kurier", "ok")
    category, status = await _classify("shipping", prompt_categories(data))
    assert status == "invalid_output" and category != "shipping"


async def test_116_pipeline_sends_the_company_list(
    db: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    db.add(OrgSettings(section=SECTION_CATEGORIES, data={"custom": [CUSTOM], "builtin": {"spam": {"enabled": False}}}))
    llm = ScriptedAnthropic([_ok_response()])
    monkeypatch.setattr("app.ai.service.get_llm_provider", lambda _s: llm)
    env = settings.model_copy(
        update={"anthropic_api_key": SecretStr("sk-test"), "llm_model_classify": "claude-haiku-4-5-20251001"}
    )
    mailbox = await _seed_ai_mailbox(db, n_messages=1)
    await process_mailbox_ai(db, mailbox, env)
    assert len(llm.calls) == 1
    assert "x_kurier — Kuriér" in llm.calls[0].system and "- spam —" not in llm.calls[0].system


async def test_116_categories_api_reauth_limit_audit_and_views(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    rows = (await client.get("/api/settings/ai/categories")).json()
    assert len(rows) == len(CATEGORIES) and next(r for r in rows if r["id"] == "other")["locked"] is True

    body = {
        "categories": [
            {"id": "order", "description": "", "enabled": False},
            {"label": "Kuriér – DPD", "description": "DPD", "color": "info"},
        ]
    }
    r = await client.send_json("PUT", "/api/settings/ai/categories", body)
    assert r.status_code == 401 and r.json()["detail"]["code"] == "reauth_required"
    assert (await client.reauth(PASSWORD)).status_code == 200
    r = await client.send_json("PUT", "/api/settings/ai/categories", body)
    assert r.status_code == 200, r.text
    out = {row["id"]: row for row in r.json()}
    assert out["order"]["enabled"] is False and out["x_kurier_dpd"]["label"] == "Kuriér – DPD"
    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "ai.categories_changed"))
    assert entry is not None and entry.details is not None
    assert entry.details["changed"]["order"]["after"]["enabled"] is False

    # a switched-off and a custom category still open (stored classifications are not broken)
    for cid in ("order", "x_kurier_dpd"):
        assert (await client.get(f"/api/mail/mailboxes/default/ai/views/{cid}/messages")).status_code == 200
    assert (await client.get("/api/mail/mailboxes/default/ai/views/x_unknown/messages")).status_code == 404

    too_many = {"categories": [{"label": f"K{i}"} for i in range(16)]}
    r = await client.send_json("PUT", "/api/settings/ai/categories", too_many)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "too_many_categories"
    r = await client.send_json("PUT", "/api/settings/ai/categories", {"categories": [{"id": "x_a", "label": " "}]})
    assert r.status_code == 422
    r = await client.send_json("PUT", "/api/settings/ai/categories", {"categories": [{"id": "bogus", "label": "B"}]})
    assert r.json()["detail"]["code"] == "category_unknown"


async def test_116_categories_admin_only(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await _admin(client, db, mail_server, role=Role.sales)
    assert (await client.get("/api/settings/ai/categories")).status_code == 403


async def test_126_rule_naming_a_switched_off_category_goes_to_other(
    db: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ai import service
    from app.ai.models import AiRule, Classification
    from tests.test_rules_2e import SUPPLIER, _live, _mailbox_with_message

    db.add(OrgSettings(section=SECTION_CATEGORIES, data={"builtin": {"supplier_document": {"enabled": False}}}))
    db.add(AiRule(nl_text="Faktúry od Fixtechu sú doklady dodávateľov", structured=SUPPLIER))
    mailbox, msg = await _mailbox_with_message(db)
    llm = ScriptedAnthropic([])
    monkeypatch.setattr(service, "get_llm_provider", lambda _s: llm)
    await process_mailbox_ai(db, mailbox, _live(settings))
    row = await db.scalar(select(Classification).where(Classification.message_id == msg.id))
    assert row is not None and row.category == "other"


async def test_126_removed_custom_category_keeps_its_view(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    assert (await client.reauth(PASSWORD)).status_code == 200
    add = {"categories": [{"label": "Kuriér", "description": "DPD", "color": "info"}]}
    assert (await client.send_json("PUT", "/api/settings/ai/categories", add)).status_code == 200
    r = await client.send_json("PUT", "/api/settings/ai/categories", {"categories": []})
    assert all(row["id"] != "x_kurier" for row in r.json())  # gone from 17c and the prompt
    view = await client.get("/api/mail/mailboxes/default/ai/views/x_kurier/messages")
    assert view.status_code == 200 and view.json()["category"]["label_sk"] == "Kuriér"
    # re-adding the same name brings the same id back
    r = await client.send_json("PUT", "/api/settings/ai/categories", add)
    assert any(row["id"] == "x_kurier" for row in r.json())
