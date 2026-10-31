"""Phase 3b: bridge client (HMAC, contract, circuit), read cache sync, schedule, Settings 13a/13e API."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role
from app.core.audit import AuditLog
from app.core.config import Settings
from app.money import bridge_client as bc
from app.money.bridge_client import BridgeClient, BridgeUnavailable, sign
from app.money.cache_sync import HISTORY_KEEP, company_emails, due, needs_nightly_full, sync_entity
from app.money.jobs import LOCK_KEY, run_money_sync
from app.money.models import MoneyCodebook, MoneyCompany, MoneyPerson, MoneySyncState
from app.money.schemas import (
    CodebookItem,
    CodebookName,
    CodebookPage,
    Company,
    CompanyPage,
    Connection,
    Health,
    IssuedInvoice,
    Person,
    PersonPage,
)
from tests.conftest import Client, FakeMailServer
from tests.test_mail_sync_1c import _signed_in

CONTRACT = Path(__file__).resolve().parents[1] / "fixtures" / "money" / "bridge_contract.json"


def test_3b_signature_matches_the_bridge_test_vector() -> None:
    """Same vector as bridge/tests/test_auth.py — both sides must sign byte-identically."""
    assert sign("k", "get", "/healthz", "1700000000") == sign("k", "GET", "/healthz", "1700000000")
    from hashlib import sha256
    from hmac import new

    canonical = b"GET\n/companies/x?a=1\n1700000000\ne3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert sign("k", "GET", "/companies/x?a=1", "1700000000") == new(b"k", canonical, sha256).hexdigest()


def test_3b_contract_fixture_parses_with_the_app_models() -> None:
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert "FICTIONAL" in data["_comment"]
    Health.model_validate(data["healthz"])
    companies = CompanyPage.model_validate(data["sync_companies"])
    assert companies.items and all(c.email and c.email.endswith(".example") for c in companies.items)
    PersonPage.model_validate(data["sync_persons"])
    CodebookPage.model_validate(data["sync_codebook_currencies"])
    for row in data["receivables"]:
        IssuedInvoice.model_validate(row)


# ----- bridge client -----


def _client(settings: Settings, handler: Any) -> BridgeClient:
    return BridgeClient(settings, http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.fixture(autouse=True)
def _reset_circuit() -> None:
    bc._circuit.success()


async def test_3b_client_signs_and_parses(settings: Settings) -> None:
    seen: list[httpx.Request] = []
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=data["sync_companies"])

    page = await _client(settings, handler).companies(datetime(2026, 10, 1, tzinfo=UTC), 0, 2)
    req = seen[0]
    path_qs = req.url.raw_path.decode()
    assert path_qs.startswith("/sync/companies?since=2026-10-01T00%3A00%3A00%2B00%3A00&from=0&count=2")
    assert req.headers["x-bridge-key-id"] == settings.bridge_hmac_key_id
    expected = sign(settings.bridge_hmac_secret.get_secret_value(), "GET", path_qs, req.headers["x-bridge-timestamp"])
    assert req.headers["x-bridge-signature"] == expected
    assert page.items[0].name.startswith("Fiktívna")


async def test_3b_client_failures_open_the_circuit(settings: Settings) -> None:
    calls = [0]

    def down(_: httpx.Request) -> httpx.Response:
        calls[0] += 1
        return httpx.Response(503, json={"detail": {"code": "money_unavailable"}})

    client = _client(settings, down)
    for _ in range(bc.FAILS_TO_OPEN):
        with pytest.raises(BridgeUnavailable) as err:
            await client.codebook("currencies", 0, 10)
        assert err.value.code == "money_unavailable"
    with pytest.raises(BridgeUnavailable) as err:
        await client.codebook("currencies", 0, 10)
    assert err.value.code == "money_circuit_open" and calls[0] == bc.FAILS_TO_OPEN


async def test_3b_client_contract_violation_is_unavailable(settings: Settings) -> None:
    client = _client(settings, lambda _: httpx.Response(200, json={"items": [{"id": "x"}], "next_from": None}))
    with pytest.raises(BridgeUnavailable) as err:
        await client.codebook("currencies", 0, 10)
    assert err.value.code == "bridge_contract"


# ----- cache sync -----

CID = [uuid.uuid5(uuid.NAMESPACE_URL, f"c{i}") for i in range(5)]


def _company(i: int, name: str = "Fiktívna") -> Company:
    return Company(
        id=CID[i],
        code=f"F{i}",
        name=f"{name} {i} s.r.o.",
        ico=f"1234 567{i}",
        dic=None,
        icdph=None,
        email=f"Info@Firma{i}.example",
        discount_pct=None,
        own_discount=None,
        due_days=14,
        connections=[
            Connection(kind="E-mail", value=f"faktury@firma{i}.example"),
            Connection(kind="Tel", value="+421"),
        ],
    )


class FakeBridge:
    """Stands in for `BridgeClient` in sync tests (pages of 2)."""

    def __init__(self, companies: list[Company], persons: list[Person] | None = None, fail: bool = False) -> None:
        self.companies_data, self.persons_data, self.fail = companies, persons or [], fail
        self.since: list[datetime | None] = []

    async def companies(self, since: datetime | None, start: int, count: int) -> CompanyPage:
        if self.fail:
            raise BridgeUnavailable("money_unavailable")
        self.since.append(since)
        rows = self.companies_data[start : start + 2]
        return CompanyPage(items=rows, next_from=start + 2 if start + 2 < len(self.companies_data) else None)

    async def persons(self, since: datetime | None, start: int, count: int) -> PersonPage:
        return PersonPage(items=self.persons_data, next_from=None)

    async def codebook(self, name: CodebookName, start: int, count: int) -> CodebookPage:
        item = CodebookItem(id=uuid.uuid5(uuid.NAMESPACE_URL, name), code=name[:3].upper(), name=name)
        return CodebookPage(items=[item], next_from=None)

    async def aclose(self) -> None:
        return None


def test_3b_company_emails_are_lowercased_and_deduplicated() -> None:
    assert company_emails(_company(1)) == ["faktury@firma1.example", "info@firma1.example"]


async def test_3b_first_sync_is_full_then_delta_with_cursor(db: AsyncSession) -> None:
    bridge = FakeBridge([_company(i) for i in range(5)])
    result = await sync_entity(db, bridge, "companies")  # type: ignore[arg-type]
    await db.commit()
    assert result.full and result.changed == 5 and result.status == "ok"
    rows = (await db.scalars(select(MoneyCompany).order_by(MoneyCompany.code))).all()
    assert len(rows) == 5 and rows[0].ico == "12345670" and "info@firma0.example" in rows[0].emails
    state = await db.scalar(select(MoneySyncState).where(MoneySyncState.entity == "companies"))
    assert state is not None and state.cursor is not None and state.last_full_at is not None
    cursor = state.cursor

    bridge.companies_data = [_company(0, name="Premenovaná")]
    result = await sync_entity(db, bridge, "companies")  # type: ignore[arg-type]
    await db.commit()
    assert not result.full and bridge.since[-1] == cursor
    db.expire_all()  # the upsert runs in Core; reload the ORM rows
    renamed = await db.scalar(select(MoneyCompany).where(MoneyCompany.money_id == CID[0]))
    assert renamed is not None and renamed.name == "Premenovaná 0 s.r.o."
    assert len((await db.scalars(select(MoneyCompany))).all()) == 5  # upsert, no duplicates


async def test_3b_full_sync_deactivates_missing_rows(db: AsyncSession) -> None:
    await sync_entity(db, FakeBridge([_company(i) for i in range(3)]), "companies")  # type: ignore[arg-type]
    await db.commit()
    result = await sync_entity(db, FakeBridge([_company(0), _company(1)]), "companies", full=True)  # type: ignore[arg-type]
    await db.commit()
    assert result.deactivated == 1
    db.expire_all()
    gone = await db.scalar(select(MoneyCompany).where(MoneyCompany.money_id == CID[2]))
    assert gone is not None and gone.active is False


async def test_3b_failed_sync_keeps_the_cursor_and_records_the_error(db: AsyncSession) -> None:
    await sync_entity(db, FakeBridge([_company(0)]), "companies")  # type: ignore[arg-type]
    await db.commit()
    state = await db.scalar(select(MoneySyncState).where(MoneySyncState.entity == "companies"))
    assert state is not None
    cursor = state.cursor
    result = await sync_entity(db, FakeBridge([], fail=True), "companies")  # type: ignore[arg-type]
    await db.commit()
    await db.refresh(state)
    assert result.status == "error" and result.error == "money_unavailable"
    assert state.cursor == cursor and state.last_status == "error" and state.history[0]["status"] == "error"
    assert "Fiktívna" not in json.dumps(state.history)  # counts and codes only, never Money data


async def test_3b_history_keeps_the_last_20_runs(db: AsyncSession) -> None:
    for _ in range(HISTORY_KEEP + 3):
        await sync_entity(db, FakeBridge([]), "codebooks")  # type: ignore[arg-type]
        await db.commit()
    state = await db.scalar(select(MoneySyncState).where(MoneySyncState.entity == "codebooks"))
    assert state is not None and len(state.history) == HISTORY_KEEP
    assert len((await db.scalars(select(MoneyCodebook))).all()) == 4


async def test_3b_persons_sync_lowercases_email(db: AsyncSession) -> None:
    person = Person(
        id=uuid.uuid4(),
        company_id=CID[0],
        first_name="Ján",
        last_name="Fiktívny",
        name="Ján Fiktívny",
        function=None,
        email="J.Fiktivny@Firma0.example",
        phone=None,
    )
    await sync_entity(db, FakeBridge([], [person]), "persons")  # type: ignore[arg-type]
    await db.commit()
    row = await db.scalar(select(MoneyPerson))
    assert row is not None and row.email == "j.fiktivny@firma0.example" and row.company_money_id == CID[0]


def test_3b_schedule_rules() -> None:
    now = datetime(2026, 10, 31, 2, 0, tzinfo=UTC)
    state = MoneySyncState(
        entity="companies", last_run_at=now - timedelta(minutes=10), last_full_at=now - timedelta(hours=2)
    )
    assert not due(state, 15, now) and due(state, 5, now) and due(None, 15, now)
    assert not needs_nightly_full(state, now)
    state.last_full_at = now - timedelta(hours=24)
    assert needs_nightly_full(state, now)


async def test_3b_job_runs_only_with_feature_money_and_one_at_a_time(app: FastAPI, settings: Settings) -> None:
    redis = app.state.redis
    bridge = FakeBridge([_company(0)])
    off = await run_money_sync(app.state.sessionmaker, settings, redis, client=bridge)  # type: ignore[arg-type]
    assert off == []
    on = settings.model_copy(update={"feature_money": True})
    await redis.set(LOCK_KEY, "1")
    assert await run_money_sync(app.state.sessionmaker, on, redis, client=bridge) == []  # type: ignore[arg-type]
    await redis.delete(LOCK_KEY)
    results = await run_money_sync(app.state.sessionmaker, on, redis, client=bridge)  # type: ignore[arg-type]
    assert [r.entity for r in results] == ["companies", "persons", "codebooks"]
    assert not await redis.exists(LOCK_KEY)
    # right after a run nothing is due; a manual run forces all
    assert await run_money_sync(app.state.sessionmaker, on, redis, client=bridge) == []  # type: ignore[arg-type]
    forced = await run_money_sync(app.state.sessionmaker, on, redis, client=bridge, force=True)  # type: ignore[arg-type]
    assert len(forced) == 3


async def test_3b_job_stops_after_money_fails(app: FastAPI, settings: Settings) -> None:
    on = settings.model_copy(update={"feature_money": True})
    results = await run_money_sync(app.state.sessionmaker, on, app.state.redis, client=FakeBridge([], fail=True))  # type: ignore[arg-type]
    assert [r.status for r in results] == ["error"]


# ----- Settings 13a / 13e -----


async def test_3b_status_when_the_bridge_is_down(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, app: FastAPI
) -> None:
    app.state.settings.bridge_url = "http://127.0.0.1:9"  # nothing listens
    await _signed_in(client, db, mail_server, role=Role.admin)
    r = await client.get("/api/settings/money/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reachable"] is False and body["error"] == "money_unavailable"
    assert [e["entity"] for e in body["entities"]] == ["companies", "persons", "codebooks"]


async def test_3b_money_settings_are_admin_only(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await _signed_in(client, db, mail_server, role=Role.sales)
    assert (await client.get("/api/settings/money/status")).status_code == 403
    assert (await client.get("/api/settings/money/sync")).status_code == 403


async def test_3b_interval_is_saved_and_audited(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await _signed_in(client, db, mail_server, role=Role.admin)
    assert (await client.get("/api/settings/money/sync")).json() == {
        "interval_min": 15,
        "running": False,
        "history": [],
    }
    r = await client.send_json("PUT", "/api/settings/money/sync", {"interval_min": 30})
    assert r.status_code == 200 and r.json()["interval_min"] == 30
    assert (await client.send_json("PUT", "/api/settings/money/sync", {"interval_min": 7})).status_code == 422
    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "settings.money_sync_interval"))
    assert entry is not None and entry.details == {"before": None, "after": 30}


async def test_3b_sync_now(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs: list[tuple[Any, ...]] = []

    async def enqueue(self: Any, name: str, *args: Any, **kwargs: Any) -> None:
        jobs.append((name, *args, kwargs.get("_job_id")))

    monkeypatch.setattr("arq.connections.ArqRedis.enqueue_job", enqueue)
    await _signed_in(client, db, mail_server, role=Role.admin)
    r = await client.send_json("POST", "/api/settings/money/sync-now")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "money_disabled"
    app.state.settings.feature_money = True
    try:
        assert (await client.send_json("POST", "/api/settings/money/sync-now")).status_code == 202
        assert jobs == [("money_sync", True, "money-sync-now")]
        await app.state.redis.set(LOCK_KEY, "1")
        r = await client.send_json("POST", "/api/settings/money/sync-now")
        assert r.status_code == 409 and r.json()["detail"]["code"] == "money_sync_running"
    finally:
        app.state.settings.feature_money = False


async def test_3b_nav_shows_money_only_with_the_feature(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, app: FastAPI
) -> None:
    await _signed_in(client, db, mail_server, role=Role.admin)
    paths = [s["path"] for s in (await client.get("/api/settings/nav")).json()["sections"]]
    assert "money" not in paths
    app.state.settings.feature_money = True
    try:
        sections = (await client.get("/api/settings/nav")).json()["sections"]
        money = next(s for s in sections if s["path"] == "money")
        assert [s["id"] for s in money["subs"]] == ["13a", "13b", "13e"]  # 13c / 13f hidden in Phase 3 (#150)
    finally:
        app.state.settings.feature_money = False


async def test_3h_cloudflare_access_headers_only_when_configured(settings: Settings) -> None:
    """ADR-016: the app sends the Access service token to the tunnel hostname; nothing in dev."""
    from pydantic import SecretStr

    from app.money.bridge_client import access_headers

    assert access_headers(settings) == {}
    tunnel = settings.model_copy(
        update={"bridge_cf_access_client_id": "id.access", "bridge_cf_access_client_secret": SecretStr("s3cret")}
    )
    assert access_headers(tunnel) == {"CF-Access-Client-Id": "id.access", "CF-Access-Client-Secret": "s3cret"}
    client = BridgeClient(tunnel)
    try:
        assert client._http.headers["CF-Access-Client-Id"] == "id.access"
    finally:
        await client.aclose()
