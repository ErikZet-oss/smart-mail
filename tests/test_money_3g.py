"""Phase 3g: W9a e-mails of a company (visible mailboxes, private folders hidden), card rows, Money in global
search (companies from the cache, invoices live for the sending roles). Fictional data only."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role
from app.mail.models import FolderMeta, Mailbox, Message
from app.money import bridge_client as bc
from app.money.bridge_client import BridgeUnavailable
from app.money.models import EmailCompanyLink, MoneyCompany, MoneyPerson
from app.money.schemas import InvoiceSearch, IssuedInvoice
from tests.conftest import Client, FakeMailServer
from tests.test_mail_sync_1c import _signed_in

NOW = datetime(2026, 10, 31, 8, 0, tzinfo=UTC)
CO = uuid.uuid5(uuid.NAMESPACE_URL, "company-360")
INV = IssuedInvoice(
    id=uuid.uuid4(),
    kind="invoice",
    number="FV2600042",
    variable_symbol=None,
    company_id=CO,
    issued_on=date(2026, 9, 1),
    due_on=date(2026, 9, 15),
    paid_on=None,
    total=Decimal("10"),
    remaining=Decimal("10"),
    currency_id=None,
    reference=None,
    doc_type=0,
)


class FakeBridge:
    down = False

    def __init__(self, *_: Any, **__: Any) -> None:
        pass

    async def __aenter__(self) -> FakeBridge:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def search_invoices(self, *, number: str | None = None, **_: Any) -> InvoiceSearch:
        if FakeBridge.down:
            raise BridgeUnavailable()
        return InvoiceSearch(matched_by="number", items=[INV] if number == INV.number else [])


@pytest.fixture(autouse=True)
def _money(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> Any:
    bc._circuit.success()
    FakeBridge.down = False
    monkeypatch.setattr("app.api.money.BridgeClient", FakeBridge)
    app.state.settings.feature_money = True
    yield
    app.state.settings.feature_money = False


async def _seed(db: AsyncSession, mailbox: Mailbox) -> tuple[FolderMeta, FolderMeta]:
    db.add(
        MoneyCompany(
            money_id=CO,
            code="F360",
            name="Fiktívna 360 s.r.o.",
            ico="36123459",
            emails=["info@firma360.example"],
            connections=[],
            active=True,
            synced_at=NOW,
        )
    )
    db.add(
        MoneyPerson(
            money_id=uuid.uuid4(), company_money_id=CO, email="jan@firma360.example", active=True, synced_at=NOW
        )
    )
    db.add(EmailCompanyLink(email="objednavky@gmail.com", company_money_id=CO))
    inbox = await db.scalar(select(FolderMeta).where(FolderMeta.mailbox_id == mailbox.id, FolderMeta.name == "INBOX"))
    other = await db.scalar(select(FolderMeta).where(FolderMeta.mailbox_id == mailbox.id, FolderMeta.name == "Nitra"))
    assert inbox is not None and other is not None
    rows = [
        (inbox, "info@firma360.example", [{"email": mailbox.email}], "Objednávka"),
        (inbox, "Jan@Firma360.example", [{"email": mailbox.email}], "Kópia faktúry"),
        (inbox, "objednavky@gmail.com", [{"email": mailbox.email}], "Z gmailu"),
        (inbox, mailbox.email, [{"email": "info@firma360.example"}], "Naša odpoveď"),
        (inbox, "iny@cudzia.example", [{"email": mailbox.email}], "Cudzí"),
        (other, "info@firma360.example", [{"email": mailbox.email}], "V súkromnom priečinku"),
    ]
    for n, (folder, sender, to, subject) in enumerate(rows):
        db.add(
            Message(
                mailbox_id=mailbox.id,
                folder_id=folder.id,
                uid=500 + n,
                subject=subject,
                from_email=sender,
                to_addrs=to,
                received_at=datetime(2026, 10, 1 + n, tzinfo=UTC),
            )
        )
    await db.commit()
    return inbox, other


async def test_3g_company_emails(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    _, other = await _seed(db, mailbox)
    other.private = True  # someone else's private folder
    await db.commit()
    r = await client.get(f"/api/money/companies/{CO}/emails")
    assert r.status_code == 200, r.text
    subjects = [m["subject"] for m in r.json()]
    assert subjects == ["Naša odpoveď", "Z gmailu", "Kópia faktúry", "Objednávka"]  # newest first
    assert next(m for m in r.json() if m["subject"] == "Naša odpoveď")["direction"] == "out"
    assert (await client.get(f"/api/money/companies/{uuid.uuid4()}/emails")).status_code == 404


async def test_3g_search_companies_and_invoices(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    mailbox = await _signed_in(client, db, mail_server, role=Role.sales)
    await _seed(db, mailbox)
    body = (await client.get("/api/money/search?q=fiktívna 360")).json()
    assert [c["code"] for c in body["companies"]] == ["F360"] and body["invoices"] == []
    body = (await client.get("/api/money/search?q=FV2600042")).json()
    assert [i["number"] for i in body["invoices"]] == ["FV2600042"]
    FakeBridge.down = True
    body = (await client.get("/api/money/search?q=FV2600042")).json()
    assert body["invoices"] == [] and body["invoices_error"] == "money_unavailable"  # the rest still answers
    assert (await client.get("/api/money/search?q=FV%23x")).json()["invoices"] == []  # never sent to Money


async def test_3g_viewer_sees_companies_but_no_invoices(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    mailbox = await _signed_in(client, db, mail_server, role=Role.viewer)
    await _seed(db, mailbox)
    body = (await client.get("/api/money/search?q=FV2600042")).json()
    assert body["invoices"] == []
    assert [c["code"] for c in (await client.get("/api/money/search?q=36123459")).json()["companies"]] == ["F360"]
