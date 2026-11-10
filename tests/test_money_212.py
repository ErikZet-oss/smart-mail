"""#212 PRODUCTION agenda read-only + the safe switch TEST → PROD. No Money write anywhere; nothing is deleted.
All companies, ids and numbers are fictional."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AiSuggestion, OrgSettings
from app.auth.models import Branch, Role
from app.core.audit import AuditLog
from app.core.config import Settings
from app.money import agenda
from app.money.activities import SECTION_WRITES, load_activity_settings
from app.money.jobs import run_money_sync
from app.money.models import EmailCompanyLink, MoneyCodebook, MoneyCompany
from app.purchasing.models import SupplierItemMapping
from tests.conftest import Client, FakeMailServer
from tests.test_mail_sync_1c import PASSWORD, _signed_in
from tests.test_money_3b import CID, FakeBridge, _company

NOW = datetime.now(UTC)
GONE = uuid.uuid5(uuid.NAMESPACE_URL, "company-only-in-test")


async def _set(db: AsyncSession, section: str, data: dict[str, Any]) -> None:
    row = await db.scalar(select(OrgSettings).where(OrgSettings.section == section))
    if row is None:
        db.add(OrgSettings(section=section, data=data))
    else:
        row.data = data
    await db.commit()


async def test_212_prod_settings_lock_the_writes_switch(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _signed_in(client, db, mail_server, role=Role.admin)
    await _set(db, agenda.SECTION, {"agenda": "PROD"})
    writes = (await client.get("/api/settings/money/writes")).json()
    assert writes["read_only"] is True and writes["enabled"] is False
    status = (await client.get("/api/settings/money/status")).json()
    assert status["read_only"] is True and status["cache_agenda"] == "PROD"
    assert (await client.reauth(PASSWORD)).status_code == 200
    r = await client.send_json("PUT", "/api/settings/money/writes", {"enabled": True})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "prod_read_only"


async def test_212_prod_turns_activity_writes_off_even_when_switched_on(db: AsyncSession) -> None:
    await _set(db, SECTION_WRITES, {"enabled": True})
    assert (await load_activity_settings(db)).writes_enabled is True
    await _set(db, agenda.SECTION, {"agenda": "PROD"})
    assert (await load_activity_settings(db)).writes_enabled is False  # no activity is even attempted


async def _seed_test_agenda(db: AsyncSession) -> uuid.UUID:
    """A cache filled from TEST: a company that PROD does not have, links and mappings to it, a branch whose
    centre is unknown in PROD, and a pending invoice suggestion with TEST data."""
    db.add(
        MoneyCompany(
            money_id=GONE,
            name="Len v TEST s.r.o.",
            ico="99999999",
            emails=[],
            connections=[],
            active=True,
            synced_at=NOW,
        )
    )
    db.add(EmailCompanyLink(email="nakup@lentest.example", company_money_id=GONE))
    db.add(SupplierItemMapping(supplier_money_id=GONE, code_norm="ABC1", article_id=uuid.uuid4()))
    branch = Branch(name="Pobočka Fiktívna", money_centre_id=str(uuid.uuid4()), money_warehouse_id=None)
    db.add(branch)
    await db.commit()
    return branch.id


async def test_212_switch_test_to_prod_full_resync_checks_and_never_deletes(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, app: FastAPI
) -> None:
    mailbox = await _signed_in(client, db, mail_server, role=Role.admin)
    on = settings.model_copy(update={"feature_money": True})
    redis = app.state.redis
    bridge = FakeBridge([_company(0), _company(1)])
    await run_money_sync(app.state.sessionmaker, on, redis, client=bridge)  # type: ignore[arg-type]
    assert (await agenda.load(db))["agenda"] == "TEST" and not (await agenda.load(db)).get("changed_at")

    branch_id = await _seed_test_agenda(db)
    db.add(
        AiSuggestion(
            mailbox_id=mailbox.id,
            suggestion_type="invoice_attach",
            payload={},
            checks=[],
            status="pending",
            shadow=False,
        )
    )
    await db.commit()
    links_before = await db.scalar(select(func.count()).select_from(EmailCompanyLink))
    mappings_before = await db.scalar(select(func.count()).select_from(SupplierItemMapping))

    bridge.agenda = "PROD"
    bridge.companies_data = [_company(0)]  # company 1 and the TEST-only one do not exist in PROD
    results = await run_money_sync(app.state.sessionmaker, on, redis, client=bridge)  # type: ignore[arg-type]
    assert [r.entity for r in results] == ["companies", "persons", "codebooks"] and all(r.full for r in results)
    db.expire_all()

    # deactivated, never deleted
    active = set(await db.scalars(select(MoneyCompany.money_id).where(MoneyCompany.active.is_(True))))
    assert active == {CID[0]}
    assert await db.scalar(select(func.count()).select_from(MoneyCompany)) == 3
    assert await db.scalar(select(func.count()).select_from(EmailCompanyLink)) == links_before
    assert await db.scalar(select(func.count()).select_from(SupplierItemMapping)) == mappings_before
    branch = await db.get(Branch, branch_id)
    assert branch is not None and branch.money_centre_id  # the setting is kept, only flagged

    state = await agenda.load(db)
    assert state["agenda"] == "PROD" and state["previous"] == "TEST" and state["resync_pending"] is False
    kinds = {(p["kind"], p.get("field")) for p in state["problems"]}
    assert ("branch", "money_centre_id") in kinds
    assert ("email_links", None) in kinds and ("supplier_mappings", None) in kinds
    assert await agenda.invalid_branch_ids(db, branch_id) == {"money_centre_id"}

    stale = await db.scalar(select(AiSuggestion).where(AiSuggestion.suggestion_type == "invoice_attach"))
    assert stale is not None and stale.status == "superseded"  # cannot be approved; made again from PROD
    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "money.agenda_changed"))
    assert entry is not None and entry.details["from"] == "TEST" and entry.details["to"] == "PROD"
    assert entry.details["superseded"] == 1 and entry.details["deactivated"] >= 2

    notes = (await client.get("/api/notifications")).json()["items"]
    note = next(n for n in notes if n["kind"] == "money_agenda_changed")
    assert note["params"] == {"agenda": "PROD", "previous": "TEST"}
    status = (await client.get("/api/settings/money/status")).json()
    assert status["read_only"] is True and status["problems"]


async def test_212_interrupted_switch_continues_with_a_full_run(app: FastAPI, settings: Settings) -> None:
    on = settings.model_copy(update={"feature_money": True})
    redis = app.state.redis
    bridge = FakeBridge([_company(0)])
    await run_money_sync(app.state.sessionmaker, on, redis, client=bridge)  # type: ignore[arg-type]
    bridge.agenda = "PROD"
    bridge.fail = True  # Money goes down right after the switch is noticed? health fails → nothing changes
    await run_money_sync(app.state.sessionmaker, on, redis, client=bridge)  # type: ignore[arg-type]
    async with app.state.sessionmaker() as db:
        assert (await agenda.load(db))["agenda"] == "TEST"
    bridge.fail = False
    await run_money_sync(app.state.sessionmaker, on, redis, client=bridge)  # type: ignore[arg-type]
    async with app.state.sessionmaker() as db:
        state = await agenda.load(db)
        assert state["agenda"] == "PROD" and state["resync_pending"] is False


async def test_212_codebook_check_ignores_an_empty_cache(db: AsyncSession) -> None:
    db.add(Branch(name="Bez číselníkov", money_centre_id=str(uuid.uuid4())))
    await db.commit()
    assert await db.scalar(select(func.count()).select_from(MoneyCodebook)) == 0
    assert [p for p in await agenda.check_references(db) if p["kind"] == "branch"] == []
