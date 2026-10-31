"""Phase 3e W8b Upomienky: debtors from Money, reminder drafts (E2) with Money PDFs, strong recipient only,
history, roles. Fictional data only."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, ClassVar

import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import OrgSettings
from app.auth.models import Role
from app.core.config import Settings
from app.mail.compose import attachment_send_block
from app.mail.compose_models import ComposeAttachment, ComposeDraft
from app.money import bridge_client as bc
from app.money.invoice_attach import SECTION_REPORTS, marked_company
from app.money.models import MoneyCompany, MoneyPerson
from app.money.reminders import reminder_html
from app.money.schemas import InvoiceSearch, IssuedInvoice, OverduePage
from tests.conftest import Client, FakeMailServer
from tests.test_mail_sync_1c import _signed_in

NOW = datetime(2026, 10, 31, 8, 0, tzinfo=UTC)
ONE = uuid.uuid5(uuid.NAMESPACE_URL, "debtor-1")
TWO = uuid.uuid5(uuid.NAMESPACE_URL, "debtor-2")
NOCONTACT = uuid.uuid5(uuid.NAMESPACE_URL, "debtor-3")


def inv(number: str, company: uuid.UUID, due: date, remaining: str) -> IssuedInvoice:
    return IssuedInvoice(
        id=uuid.uuid5(uuid.NAMESPACE_URL, number),
        kind="invoice",
        number=number,
        variable_symbol=None,
        company_id=company,
        issued_on=due,
        due_on=due,
        paid_on=None,
        total=Decimal(remaining),
        remaining=Decimal(remaining),
        currency_id=None,
        reference=None,
        doc_type=0,
    )


class FakeBridge:
    rows: ClassVar[list[IssuedInvoice]] = []

    def __init__(self, *_: Any, **__: Any) -> None:
        pass

    async def __aenter__(self) -> FakeBridge:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def overdue(self, before: date, start: int, count: int) -> OverduePage:
        rows = [r for r in self.rows if r.due_on and r.due_on < before]
        return OverduePage(items=rows[start : start + count], next_from=None)

    async def search_invoices(self, **_: Any) -> InvoiceSearch:
        return InvoiceSearch(matched_by="none", items=[])

    async def invoice_pdf(self, kind: str, invoice_id: uuid.UUID, report_id: str) -> bytes | None:
        return b"%PDF-1.4 fictional"


@pytest.fixture(autouse=True)
def _fake(monkeypatch: pytest.MonkeyPatch, app: FastAPI) -> Any:
    bc._circuit.success()
    FakeBridge.rows = [
        inv("FV2600010", ONE, date(2026, 8, 1), "500.00"),
        inv("FV2600011", ONE, date(2026, 9, 20), "20.40"),
        inv("FV2600020", TWO, date(2026, 10, 10), "99.90"),
        inv("FV2600030", NOCONTACT, date(2026, 10, 1), "10.00"),
        inv("FV2699999", ONE, date(2099, 1, 1), "1.00"),  # not overdue
    ]
    monkeypatch.setattr("app.api.money.BridgeClient", FakeBridge)
    app.state.settings.feature_money = True
    yield
    app.state.settings.feature_money = False


async def _seed(db: AsyncSession) -> None:
    for money_id, n, emails in (
        (ONE, 1, ["uctaren@dlznik1.example"]),
        (TWO, 2, ["info@dlznik2.example"]),
        (NOCONTACT, 3, []),
    ):
        db.add(
            MoneyCompany(
                money_id=money_id,
                code=f"D{n}",
                name=f"Fiktívny dlžník {n} s.r.o.",
                email=emails[0] if emails else None,
                emails=emails,
                connections=[],
                active=True,
                synced_at=NOW,
            )
        )
    db.add(OrgSettings(section=SECTION_REPORTS, data={"invoice": {"sk": "12"}, "proforma": {}}))
    await db.commit()


def test_3e_reminder_html_is_escaped_and_totals() -> None:
    rows = [inv("FV<1>", ONE, date(2026, 9, 1), "1234.5"), inv("FV2", ONE, date(2026, 10, 1), "0.5")]
    out = reminder_html("firm", rows, date(2026, 10, 31))
    assert "FV&lt;1&gt;" in out and "<script" not in out
    assert "1 234,50 €" in out and "1 235,00 €" in out and ">60<" in out and ">30<" in out
    assert "bez zbytočného odkladu" in out
    assert "bezpredmetnú" in reminder_html("polite", rows, date(2026, 10, 31))


async def test_3e_debtors_list(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await _signed_in(client, db, mail_server, role=Role.accounting)
    await _seed(db)
    db.add(
        MoneyPerson(
            money_id=uuid.uuid4(),
            company_money_id=ONE,
            name="Eva Účtovná",
            email="uctaren@dlznik1.example",
            active=True,
            synced_at=NOW,
        )
    )
    await db.commit()
    with_time = NOW  # the bridge decides „overdue“ by date; FV2699999 is not
    r = await client.get("/api/money/reminders")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [d["company"]["code"] for d in rows] == ["D1", "D2", "D3"]  # highest sum first
    one = rows[0]
    assert (
        one["overdue_total"] == "520.40" and one["invoice_count"] == 2 and one["contact"] == "uctaren@dlznik1.example"
    )
    assert one["oldest_days"] > 80 and with_time


async def test_3e_prepare_drafts_one_per_customer(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    await _signed_in(client, db, mail_server, role=Role.sales)
    await _seed(db)
    body = {"company_money_ids": [str(ONE), str(NOCONTACT), str(uuid.uuid4())], "tone": "firm"}
    r = await client.send_json("POST", "/api/money/reminders/drafts", body)
    assert r.status_code == 200, r.text
    out = {x["company_money_id"]: x for x in r.json()}
    assert out[str(NOCONTACT)]["error"] == "no_contact"
    assert sum(1 for x in r.json() if x["error"] == "nothing_overdue") == 1
    draft = await db.get(ComposeDraft, uuid.UUID(out[str(ONE)]["draft_id"]))
    assert draft is not None and draft.subject.startswith("Upomienka")
    assert [a["email"] for a in draft.to_addrs] == ["uctaren@dlznik1.example"]
    assert "FV2600010" in draft.body_html and "FV2699999" not in draft.body_html
    atts = (await db.scalars(select(ComposeAttachment).where(ComposeAttachment.draft_id == draft.id))).all()
    assert sorted(a.filename for a in atts) == ["Faktura_FV2600010.pdf", "Faktura_FV2600011.pdf"]
    assert all(marked_company(a.storage_key) == ONE for a in atts)
    # the 3d send check also guards reminders
    assert await attachment_send_block(db, settings, draft) is None
    draft.to_addrs = [{"name": None, "email": "info@dlznik2.example"}]
    assert (await attachment_send_block(db, settings, draft)) is not None

    hist = (await client.get("/api/money/reminders/history")).json()
    assert hist[0]["company_name"] == "Fiktívny dlžník 1 s.r.o." and hist[0]["draft_status"] == "editing"
    again = (await client.get("/api/money/reminders")).json()
    assert again[0]["last_reminder_at"] is not None and again[0]["last_reminder_tone"] == "firm"


async def test_3e_missing_report_blocks_the_draft(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _signed_in(client, db, mail_server, role=Role.admin)
    await _seed(db)
    row = await db.scalar(select(OrgSettings).where(OrgSettings.section == SECTION_REPORTS))
    assert row is not None
    row.data = {"invoice": {}, "proforma": {}}
    await db.commit()
    r = await client.send_json("POST", "/api/money/reminders/drafts", {"company_money_ids": [str(TWO)]})
    assert r.json()[0]["error"] == "report_not_configured" and r.json()[0]["draft_id"] is None
    assert (await db.scalar(select(ComposeDraft))) is None


async def test_3e_roles(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await _signed_in(client, db, mail_server, role=Role.warehouse)
    assert (await client.get("/api/money/reminders")).status_code == 403
    assert (
        await client.send_json("POST", "/api/money/reminders/drafts", {"company_money_ids": [str(ONE)]})
    ).status_code == 403
