"""#116 17a: company budget in org_settings — env is the default until an admin saves a value (1–500)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AiRun, OrgSettings
from app.ai.org_settings import SECTION_LIMITS, limits_from, load_ai_limits, parse_budget
from app.ai.service import process_mailbox_ai
from app.auth.models import Role
from app.core.audit import AuditLog
from app.core.config import Settings
from tests.conftest import Client, FakeMailServer
from tests.test_ai_classify_review_2b import ScriptedAnthropic, _ok_response, _seed_ai_mailbox
from tests.test_knowledge_2e import PASSWORD, _admin


def test_116_env_budget_until_admin_saves(settings: Settings) -> None:
    env = settings.model_copy(update={"ai_daily_budget_usd": 5.0})
    default = limits_from(None, env)
    assert default.budget_usd == Decimal("5") and default.budget_source == "env"
    assert default.alert_pct == 80 and default.on_exhausted == "rules_only" and default.retention_days == 90
    saved = limits_from({"daily_budget_usd": "12.50"}, env)
    assert saved.budget_usd == Decimal("12.50") and saved.budget_source == "app"
    # a broken or out-of-range stored value never wins over env
    for bad in ("0", "500.01", "abc", 7.5, True, "NaN", None):
        assert limits_from({"daily_budget_usd": bad}, env).budget_source == "env"


def test_116_parse_budget_range() -> None:
    assert parse_budget("1") == Decimal("1.00") and parse_budget("500") == Decimal("500.00")
    assert parse_budget("0.99") is None and parse_budget("501") is None and parse_budget("Infinity") is None


async def test_116_limits_api_reauth_audit_and_source(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    r = await client.get("/api/settings/ai/limits")
    assert r.status_code == 200 and r.json()["budget_source"] == "env"
    assert [m["purpose"] for m in r.json()["models"]] == ["classify", "draft", "extract", "assistant", "embed"]

    body = {"daily_budget_usd": "20,5", "alert_pct": 70, "on_exhausted": "ai_off", "retention_days": 30}
    r = await client.send_json("PUT", "/api/settings/ai/limits", body)
    assert r.status_code == 401 and r.json()["detail"]["code"] == "reauth_required"
    assert (await client.reauth(PASSWORD)).status_code == 200
    r = await client.send_json("PUT", "/api/settings/ai/limits", body)
    out = r.json()
    assert out["daily_budget_usd"] == "20.50" and out["budget_source"] == "app" and out["on_exhausted"] == "ai_off"
    row = await db.scalar(select(OrgSettings).where(OrgSettings.section == SECTION_LIMITS))
    assert row is not None and row.data["daily_budget_usd"] == "20.50"  # a string, never a float
    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "ai.limits_changed"))
    assert entry is not None and entry.details is not None
    assert entry.details["before"]["budget_source"] == "env" and entry.details["after"]["daily_budget_usd"] == "20.50"

    for bad in ("0", "501", "abc"):
        r = await client.send_json("PUT", "/api/settings/ai/limits", {**body, "daily_budget_usd": bad})
        assert r.status_code == 422
    # empty budget → back to the server value
    r = await client.send_json("PUT", "/api/settings/ai/limits", {**body, "daily_budget_usd": None})
    assert r.json()["budget_source"] == "env"


async def test_116_limits_admin_only(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await _admin(client, db, mail_server, role=Role.sales)
    assert (await client.get("/api/settings/ai/limits")).status_code == 403
    assert (await client.send_json("PUT", "/api/settings/ai/limits", {})).status_code == 403


async def _spent_one_dollar(db: AsyncSession) -> None:
    db.add(AiRun(purpose="classify", provider="anthropic", model="m", cost_usd=Decimal("1.0000"), status="ok"))
    db.add(OrgSettings(section=SECTION_LIMITS, data={"daily_budget_usd": "1"}))
    await db.flush()


@pytest.mark.parametrize(("mode", "skipped"), [("rules_only", 2), ("ai_off", 1)])
async def test_116_pipeline_uses_saved_budget_and_on_exhausted(
    db: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch, mode: str, skipped: int
) -> None:
    llm = ScriptedAnthropic([_ok_response(), _ok_response()])
    monkeypatch.setattr("app.ai.service.get_llm_provider", lambda _s: llm)
    env = settings.model_copy(
        update={
            "anthropic_api_key": SecretStr("sk-test"),
            "llm_model_classify": "claude-haiku-4-5-20251001",
            "ai_daily_budget_usd": 50.0,  # env would allow it; the saved 1 USD is already spent
        }
    )
    await _spent_one_dollar(db)
    row = await db.scalar(select(OrgSettings).where(OrgSettings.section == SECTION_LIMITS))
    assert row is not None
    row.data = {**row.data, "on_exhausted": mode}
    mailbox = await _seed_ai_mailbox(db, n_messages=2)
    assert (await load_ai_limits(db, env)).budget_usd == Decimal("1.00")
    stats = await process_mailbox_ai(db, mailbox, env)
    assert llm.calls == [] and stats["skipped_budget"] == skipped
