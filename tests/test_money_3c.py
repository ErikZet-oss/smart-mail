"""Phase 3c: sender → Money company (MONEY_API §5.4), Zákazník card, „Priradiť k firme“. Fictional data only."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.money import receivables_summary
from app.auth.models import Role
from app.core.audit import AuditLog
from app.core.config import Settings
from app.mail.models import FolderMeta, Mailbox, Message
from app.money import bridge_client as bc
from app.money.bridge_client import BridgeClient, BridgeUnavailable
from app.money.matching import counterparty, ico_valid, icos_in, match_sender
from app.money.models import EmailCompanyLink, MoneyCompany, MoneyPerson
from app.money.schemas import Activity, Delivery, IssuedInvoice, Order
from tests.conftest import Client, FakeMailServer
from tests.test_mail_sync_1c import _signed_in

CONTRACT = Path(__file__).resolve().parents[1] / "fixtures" / "money" / "bridge_contract.json"
NOW = datetime(2026, 10, 31, 8, 0, tzinfo=UTC)


def make_ico(prefix: str) -> str:
    total = sum(int(d) * w for d, w in zip(prefix, range(8, 1, -1), strict=True))
    return prefix + str((11 - total % 11) % 10)


ICO_A = make_ico("3612345")
ICO_B = make_ico("4498765")


@pytest.fixture(autouse=True)
def _reset_circuit() -> None:
    bc._circuit.success()


async def _company(
    db: AsyncSession, n: int, emails: list[str], ico: str | None = None, active: bool = True
) -> MoneyCompany:
    row = MoneyCompany(
        money_id=uuid.uuid5(uuid.NAMESPACE_URL, f"company-{n}"),
        code=f"F{n}",
        name=f"Fiktívna {n} s.r.o.",
        ico=ico,
        emails=emails,
        email=emails[0] if emails else None,
        connections=[],
        active=active,
        synced_at=NOW,
    )
    db.add(row)
    await db.flush()
    return row


def test_3c_ico_checksum_and_extraction() -> None:
    assert ico_valid(ICO_A) and not ico_valid(ICO_A[:7] + str((int(ICO_A[7]) + 1) % 10))
    body = f"S pozdravom\nFiktívna 1 s.r.o.\nIČO: {ICO_A[:2]} {ICO_A[2:5]} {ICO_A[5:]}\nIČ DPH SK2020\nICO 12345678"
    assert icos_in(body) == [ICO_A]  # 12345678 fails the check digit
    assert icos_in(None) == []


def test_3c_counterparty_of_our_own_mail_is_the_external_recipient(settings: Settings) -> None:
    incoming = Message(from_email="Nakup@Firma1.example", to_addrs=[{"email": "jana@smartsro.sk"}])
    outgoing = Message(
        from_email="jana@smartsro.sk",
        to_addrs=[{"email": "kolega@smartsro.sk"}],
        cc_addrs=[{"email": "nakup@firma2.example"}],
    )
    internal = Message(from_email="jana@smartsro.sk", to_addrs=[{"email": "peter@smartsro.sk"}])
    assert counterparty(incoming, settings) == "nakup@firma1.example"
    assert counterparty(outgoing, settings) == "nakup@firma2.example"
    assert counterparty(internal, settings) is None


async def test_3c_match_order_link_person_email_ico_domain(db: AsyncSession, settings: Settings) -> None:
    one = await _company(db, 1, ["info@firma1.example"], ico=ICO_A)
    two = await _company(db, 2, ["faktury@firma2.example"], ico=ICO_B)
    db.add(
        MoneyPerson(
            money_id=uuid.uuid4(),
            company_money_id=two.money_id,
            email="peter@firma1.example",
            active=True,
            synced_at=NOW,
        )
    )
    await db.commit()

    # person e-mail (0.98) beats the company domain of firma1
    m = await match_sender(db, "Peter@Firma1.example", None, settings)
    assert m.company is not None and m.company.money_id == two.money_id and m.method == "person"
    m = await match_sender(db, "info@firma1.example", None, settings)
    assert m.method == "company_email" and m.confidence == 0.95 and not m.needs_confirmation
    m = await match_sender(db, "someone@gmail.com", f"IČO: {ICO_A}", settings)
    assert m.company is not None and m.company.money_id == one.money_id and m.method == "ico"
    m = await match_sender(db, "novy@firma2.example", None, settings)
    assert m.method == "domain" and m.confidence == 0.7 and m.needs_confirmation
    # free-mail and our own domains never match by domain
    await _company(db, 3, ["firma3@gmail.com"])
    await db.commit()
    assert (await match_sender(db, "iny@gmail.com", None, settings)).company is None
    # a confirmed link wins over everything
    db.add(EmailCompanyLink(email="info@firma1.example", company_money_id=two.money_id))
    await db.commit()
    m = await match_sender(db, "info@firma1.example", None, settings)
    assert m.method == "confirmed" and m.company is not None and m.company.money_id == two.money_id


async def test_3c_two_companies_on_one_step_are_candidates_not_a_match(db: AsyncSession, settings: Settings) -> None:
    await _company(db, 1, ["spolocna@holding.example"])
    await _company(db, 2, ["spolocna@holding.example"])
    await _company(db, 3, ["stara@zrusena.example"], active=False)
    await db.commit()
    m = await match_sender(db, "spolocna@holding.example", None, settings)
    assert m.company is None and len(m.candidates) == 2 and m.needs_confirmation
    assert (await match_sender(db, "stara@zrusena.example", None, settings)).company is None  # inactive
    # a domain that only looks similar does not match
    assert (await match_sender(db, "x@olding.example", None, settings)).company is None
    assert (await match_sender(db, "x@holding.example.evil", None, settings)).company is None


def test_3c_receivables_summary() -> None:
    today = date(2026, 10, 31)

    def inv(n: int, due: date, remaining: str) -> IssuedInvoice:
        return IssuedInvoice(
            id=uuid.uuid4(),
            kind="invoice",
            number=f"FV{n}",
            variable_symbol=None,
            company_id=None,
            issued_on=due - timedelta(days=14),
            due_on=due,
            paid_on=None,
            total=Decimal(remaining),
            remaining=Decimal(remaining),
            currency_id=None,
            reference=None,
            doc_type=0,
        )

    out = receivables_summary(
        [inv(1, today - timedelta(days=40), "100.10"), inv(2, today + timedelta(days=5), "0.20")], today
    )
    assert out.open_count == 2 and out.open_total == Decimal("100.30")
    assert out.overdue_count == 1 and out.overdue_total == Decimal("100.10") and out.oldest_overdue_days == 40
    assert out.items[0].number == "FV1"


def test_3c_contract_fixture_has_the_card_parts() -> None:
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    for row in data["orders"]:
        Order.model_validate(row)
    for row in data["deliveries"]:
        Delivery.model_validate(row)
    for row in data["activities"]:
        Activity.model_validate(row)


async def test_3c_client_501_is_not_an_outage_and_404_is_none(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/activities"):
            return httpx.Response(501, json={"detail": {"code": "waiting_for_probe"}})
        return httpx.Response(404, json={"detail": {"code": "not_found"}})

    client = BridgeClient(settings, http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    for _ in range(bc.FAILS_TO_OPEN + 1):
        with pytest.raises(BridgeUnavailable) as err:
            await client.activities(uuid.uuid4())
        assert err.value.code == "waiting_for_probe"
    assert await client.company(uuid.uuid4()) is None  # circuit still closed


# ----- API -----


async def _mail_from(db: AsyncSession, mailbox: Mailbox, sender: str, body: str = "Dobrý deň") -> Message:
    inbox = await db.scalar(select(FolderMeta).where(FolderMeta.mailbox_id == mailbox.id, FolderMeta.name == "INBOX"))
    assert inbox is not None
    message = Message(
        mailbox_id=mailbox.id,
        folder_id=inbox.id,
        uid=77,
        subject="Faktúra",
        from_email=sender,
        to_addrs=[{"email": mailbox.email}],
        body_text=body,
        received_at=NOW,
    )
    db.add(message)
    await db.commit()
    return message


class FakeCardBridge:
    def __init__(self, *_: Any, **__: Any) -> None:
        pass

    async def __aenter__(self) -> FakeCardBridge:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def receivables(self, money_id: uuid.UUID) -> list[IssuedInvoice]:
        data = json.loads(CONTRACT.read_text(encoding="utf-8"))
        return [IssuedInvoice.model_validate(r) for r in data["receivables"]]

    async def orders(self, money_id: uuid.UUID, since: date) -> list[Order]:
        raise BridgeUnavailable("money_unavailable")

    async def deliveries(self, money_id: uuid.UUID, since: date) -> list[Delivery]:
        return []

    async def activities(self, money_id: uuid.UUID) -> list[Activity]:
        raise BridgeUnavailable("waiting_for_probe")


@pytest.fixture
def money_on(app: FastAPI) -> Any:
    app.state.settings.feature_money = True
    yield
    app.state.settings.feature_money = False


async def test_3c_disabled_without_feature_money(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    message = await _mail_from(db, mailbox, "info@firma1.example")
    r = await client.get(f"/api/money/messages/{message.id}/customer")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "money_disabled"


async def test_3c_customer_and_card(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.money.BridgeClient", FakeCardBridge)
    mailbox = await _signed_in(client, db, mail_server)
    company = await _company(db, 1, ["info@firma1.example"], ico=ICO_A)
    db.add(
        MoneyPerson(
            money_id=uuid.uuid4(), company_money_id=company.money_id, name="Ján Fiktívny", active=True, synced_at=NOW
        )
    )
    await db.commit()
    message = await _mail_from(db, mailbox, "info@firma1.example")
    r = await client.get(f"/api/money/messages/{message.id}/customer")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["method"] == "company_email" and body["company"]["ico"] == ICO_A

    card = (await client.get(f"/api/money/companies/{company.money_id}/card")).json()
    assert card["company"]["name"] == "Fiktívna 1 s.r.o."
    assert card["receivables"]["error"] is None and isinstance(card["receivables"]["open_total"], str)
    assert card["orders"] == {"error": "money_unavailable", "items": []}  # one part down, the rest stays
    assert card["deliveries"] == {"error": None, "items": []}
    assert card["activities"]["error"] == "waiting_for_probe"
    assert [p["name"] for p in card["persons"]] == ["Ján Fiktívny"]


async def test_3c_message_of_another_mailbox_is_404(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    await _signed_in(client, db, mail_server)
    assert (await client.get(f"/api/money/messages/{uuid.uuid4()}/customer")).status_code == 404


async def test_3c_search_link_and_unlink(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    company = await _company(db, 1, ["info@firma1.example"], ico=ICO_A)
    await _company(db, 2, ["x@firma2.example"])
    await db.commit()
    found = (await client.get("/api/money/companies/search?q=fiktívna 1")).json()
    assert [c["code"] for c in found] == ["F1"]
    assert [c["code"] for c in (await client.get(f"/api/money/companies/search?q={ICO_A}")).json()] == ["F1"]
    assert (await client.get("/api/money/companies/search?q=%25")).status_code == 422  # too short
    assert (await client.get("/api/money/companies/search?q=%25%25")).json() == []  # % is literal

    message = await _mail_from(db, mailbox, "objednavky@gmail.com")
    assert (await client.get(f"/api/money/messages/{message.id}/customer")).json()["company"] is None
    r = await client.send_json(
        "POST", "/api/money/links", {"email": "Objednavky@Gmail.com", "company_money_id": str(company.money_id)}
    )
    assert r.status_code == 200 and r.json()["method"] == "confirmed"
    after = (await client.get(f"/api/money/messages/{message.id}/customer")).json()
    assert after["method"] == "confirmed" and after["company"]["code"] == "F1"
    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "money.email_linked"))
    assert entry is not None and entry.object_id == "objednavky@gmail.com"

    bad = await client.send_json(
        "POST", "/api/money/links", {"email": "jana@smartsro.sk", "company_money_id": str(company.money_id)}
    )
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "internal_address"
    r = await client.send_json("DELETE", "/api/money/links?email=objednavky@gmail.com")
    assert r.status_code == 200
    assert (await client.get(f"/api/money/messages/{message.id}/customer")).json()["company"] is None


async def test_3c_viewer_cannot_link(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    await _signed_in(client, db, mail_server, role=Role.viewer)
    company = await _company(db, 1, ["info@firma1.example"])
    await db.commit()
    r = await client.send_json(
        "POST", "/api/money/links", {"email": "a@b.example", "company_money_id": str(company.money_id)}
    )
    assert r.status_code == 403
