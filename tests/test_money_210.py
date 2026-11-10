"""#210 „faktúra za objednávku“: no invoice number in the mail, only the e-shop order number → the issued invoice
found through its „Popis“ (`Nazev`). Read-only, the owner check is unchanged. All names and numbers are fictional."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AiSuggestion
from app.core.config import Settings
from app.mail.compose_models import ComposeDraft
from app.money.invoice_attach import draft_body, invoice_refs, order_refs
from app.money.invoice_suggest import suggest_invoice_attach
from app.money.schemas import InvoiceSearch
from tests.conftest import Client, FakeMailServer
from tests.test_mail_sync_1c import _signed_in
from tests.test_money_3d import OTHER, OURS, FakeBridge, _companies, _fake_bridge, _message, inv, money_on

__all__ = ["_fake_bridge", "money_on"]

FORWARD = (
    "Dobrý deň, prosím o preposlanie faktúry za objednávku nižšie.\n\n"
    "---------- Preposlaná správa ----------\n"
    "Od: eshop@smartmail.example\nPredmet: Potvrdenie objednávky\n\n"
    "> Ďakujeme za Vašu objednávku č. 2410006820.\n> Tel.: +421 905 123 456, IČO: 12345678, 949 01 Nitra\n"
)


def _desc(number: str, company: uuid.UUID, order: str | None) -> Any:
    return inv(number, company).model_copy(update={"description": f"Objednávka {order}" if order else None})


@pytest.fixture(autouse=True)
def _order_search(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The 3d fake searches by number / VS; add the bridge's „order“ step (Popis = Nazev contains the number)."""
    calls: list[str] = []
    original = FakeBridge.search_invoices

    async def search(self: Any, *, order: str | None = None, **kw: Any) -> InvoiceSearch:
        if order:
            calls.append(order)
            rows = [i for i in FakeBridge.invoices if order in (i.description or "")]
            return InvoiceSearch(matched_by="order" if rows else "none", items=rows)
        return await original(self, number=kw.get("number"), vs=kw.get("vs"))

    monkeypatch.setattr(FakeBridge, "search_invoices", search)
    return calls


# ----- order_refs (table + property tests) -----


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (FORWARD, ["2410006820"]),
        ("Faktúra k objednávke 2410006820", ["2410006820"]),
        ("obj. 2410006820 a obj.č. 2410006821", ["2410006820", "2410006821"]),
        ("Objednávka č.2410006822", ["2410006822"]),
        ("Prosím fakturu k objednávce č. 2410006823", ["2410006823"]),
        ("Please send the invoice for order #2410006824", ["2410006824"]),
        ("Rechnung zur Bestellung Nr. 2410006825", ["2410006825"]),
        ("objednávka 2410006820, objednávka 2410006820", ["2410006820"]),
        ("tel. 0905123456, IČO 12345678, PSČ 94901, 31.10.2026", []),
        ("objednávka 12345", []),  # fewer than 6 digits
        ("", []),
    ],
)
def test_210_order_refs_table(text: str, expected: list[str]) -> None:
    assert order_refs(text) == expected


@given(st.text(max_size=300))
def test_210_order_refs_never_raises_and_are_digits(text: str) -> None:
    refs = order_refs(text)
    assert len(refs) <= 5 and len(set(refs)) == len(refs)
    assert all(r.isdigit() and 6 <= len(r) <= 14 for r in refs)


@given(st.from_regex(r"\+?\d{3} ?\d{3} ?\d{3} ?\d{3}", fullmatch=True))
def test_210_a_phone_number_alone_is_never_an_order(phone: str) -> None:
    assert order_refs(f"Volajte na {phone}, ďakujeme.") == []


def test_210_invoice_number_wins_over_the_order() -> None:
    text = "Pošlite faktúru FV2600042 k objednávke 2410006820"
    assert invoice_refs(text) == ["FV2600042"]  # the flow then never looks at order_refs


def test_210_draft_names_the_order_in_the_mail_language() -> None:
    assert "faktúry FV2600042 k objednávke č. 2410006820" in draft_body("sk", ["FV2600042"], ["2410006820"])
    assert "for order no. 2410006820" in draft_body("en", ["FV2600042"], ["2410006820"])
    assert "zur Bestellung Nr. 2410006820" in draft_body("de", ["FV2600042"], ["2410006820"])


# ----- suggestion flow -----


async def test_210_forwarded_order_confirmation_gives_an_invoice_card(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, _order_search: list[str]
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    await _companies(db)
    FakeBridge.invoices = [
        _desc("FV2600042", OURS, "2410006820"),
        _desc("FV2600043", OURS, "2410006820"),  # partial invoice of the same order → both
        _desc("FV2600099", OTHER, None),
    ]
    await _message(db, mailbox, "faktury@firma1.example", FORWARD)
    stats = await suggest_invoice_attach(db, mailbox, settings.model_copy(update={"feature_money": True}), shadow=False)
    await db.commit()
    assert stats["created"] == 1 and _order_search == ["2410006820"]
    row = await db.scalar(select(AiSuggestion).where(AiSuggestion.suggestion_type == "invoice_attach"))
    assert row is not None and row.batch_safe is False
    assert sorted(i["number"] for i in row.payload["invoices"]) == ["FV2600042", "FV2600043"]
    assert row.payload["orders"] == ["2410006820"]
    assert "k objednávke č. 2410006820" in row.payload["body"]
    found = next(c for c in row.checks if c["id"] == "invoice_found_by_order")
    assert found["level"] == "warning" and found["params"]["order"] == "2410006820"


async def test_210_invoice_of_another_company_needs_an_ack(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    """Changed by #215 (ADR-019): the card is offered, but only with the `requires_ack` check (see test_money_215)."""
    mailbox = await _signed_in(client, db, mail_server)
    await _companies(db)
    FakeBridge.invoices = [_desc("FV2600099", OTHER, "2410006820")]
    await _message(db, mailbox, "faktury@firma1.example", FORWARD)
    stats = await suggest_invoice_attach(db, mailbox, settings.model_copy(update={"feature_money": True}), shadow=False)
    await db.commit()
    assert stats["created"] == 1
    row = await db.scalar(select(AiSuggestion))
    assert row is not None and row.payload["foreign"] is True and row.batch_safe is False
    assert any(c["id"] == "invoice_other_customer" and c["level"] == "requires_ack" for c in row.checks)


async def test_210_order_without_invoice_gives_no_card(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    await _companies(db)
    FakeBridge.invoices = [_desc("FV2600042", OURS, "2410000001")]
    await _message(db, mailbox, "faktury@firma1.example", FORWARD)
    stats = await suggest_invoice_attach(db, mailbox, settings.model_copy(update={"feature_money": True}), shadow=False)
    await db.commit()
    assert stats["created"] == 0 and stats["order_no_invoice"] == 1


async def test_210_written_invoice_number_skips_the_order_search(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, _order_search: list[str]
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    await _companies(db)
    FakeBridge.invoices = [_desc("FV2600042", OURS, "2410006820")]
    await _message(db, mailbox, "faktury@firma1.example", "Pošlite FV2600042 k objednávke 2410006820.")
    await suggest_invoice_attach(db, mailbox, settings.model_copy(update={"feature_money": True}), shadow=False)
    await db.commit()
    assert _order_search == []
    row = await db.scalar(select(AiSuggestion))
    assert row is not None and not any(c["id"] == "invoice_found_by_order" for c in row.checks)


async def test_210_approve_rechecks_the_owner_on_the_order_path(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, money_on: None
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    await _companies(db)
    FakeBridge.invoices = [_desc("FV2600042", OURS, "2410006820")]
    await _message(db, mailbox, "faktury@firma1.example", FORWARD)
    await suggest_invoice_attach(db, mailbox, settings.model_copy(update={"feature_money": True}), shadow=False)
    await db.commit()
    row = await db.scalar(select(AiSuggestion))
    assert row is not None
    FakeBridge.invoices = [_desc("FV2600042", OTHER, "2410006820")]  # Money changed the customer meanwhile
    r = await client.send_json("POST", f"/api/suggestions/{row.id}/approve", {})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "suggestion_blocked"
    assert (await db.scalar(select(ComposeDraft))) is None
