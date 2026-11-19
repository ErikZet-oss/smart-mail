"""#217 invoice by the customer's order number: numbers with letters, „Popis“ OR „Poznámka“, pick up to 5.
All companies, numbers and addresses are fictional."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AiSuggestion
from app.core.config import Settings
from app.mail.compose import attachment_send_block
from app.mail.compose_models import ComposeAttachment, ComposeDraft
from app.money.invoice_attach import invoice_refs, order_in, order_refs, order_search_terms
from app.money.invoice_suggest import suggest_invoice_attach
from app.money.schemas import InvoiceSearch, IssuedInvoice
from tests.conftest import Client, FakeMailServer
from tests.test_mail_sync_1c import _signed_in
from tests.test_money_3d import OTHER, OURS, FakeBridge, _companies, _fake_bridge, _message, inv, money_on

# ----- order_refs: table + property tests -----


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Prosím faktúru k objednávke č. OR06024026", ["OR06024026"]),
        ("Faktura k PO-45821, ďakujem", ["PO-45821"]),
        ("naša objednávka OBJ/2026/123", ["OBJ/2026/123"]),
        ("vaša objednávka PO-45821", ["PO-45821"]),
        ("PO 4500012345", ["PO 4500012345"]),
        ("zákazka ZK-2026001", ["ZK-2026001"]),
        ("---------- Preposlaná správa ----------\n> Objednávka č. OR06024027 bola prijatá", ["OR06024027"]),
        ("obj. OR06024026 a objednávka OR06024026", ["OR06024026"]),
        ("objednávka 2410006820", ["2410006820"]),
        ("Bestellung NR 09/11/2026", []),  # a date
        ("objednávka 11.11.2026", []),
        ("objednávka zo dňa 11.11.2026, tel. +421 911 855 930", []),
        ("IČO 12345678, DIČ 2020123456, IČ DPH SK2020123456, PSČ 949 01", []),
        ("objednávka IBAN SK31 1200 0000 1987 4263 7541", []),
        ("objednávka 12345", []),  # too short
        ("", []),
    ],
)
def test_217_order_refs_table(text: str, expected: list[str]) -> None:
    assert order_refs(text) == expected


def test_217_invoice_number_wins() -> None:
    text = "Pošlite faktúru FV2600042 k objednávke OR06024026"
    assert invoice_refs(text) == ["FV2600042"]  # the flow never looks at order_refs then


@given(st.text(max_size=300))
def test_217_order_refs_never_raise(text: str) -> None:
    refs = order_refs(text)
    assert len(refs) <= 5 and len(set(refs)) == len(refs)
    for r in refs:
        assert r == r.strip() and sum(c.isdigit() for c in r) >= 4
        assert all(len(t) >= 6 for t in order_search_terms(r))


@given(st.from_regex(r"\+?\d{3} ?\d{3} ?\d{3} ?\d{3}", fullmatch=True))
def test_217_a_phone_is_never_an_order(phone: str) -> None:
    assert order_refs(f"Volajte na {phone}, objednávka zo dňa 11.11.2026.") == []


def test_217_search_terms_and_whole_number_match() -> None:
    assert order_search_terms("PO-45821") == ["PO-45821", "PO45821"]
    assert order_search_terms("OR06024026") == ["OR06024026"]
    assert order_in("Objednávka OR06024026", "OR06024026")
    assert order_in("obj. PO 45821 / dodávka 2", "PO-45821")
    assert order_in("Objednávka: or-06024026", "OR06024026")
    assert not order_in("Objednávka 24100068201", "2410006820")
    assert not order_in("XOR06024026", "OR06024026")
    assert not order_in(None, "OR06024026")


# ----- the card: up to 5 invoices, pre-selection, approve only the picked ones -----

__all__ = ["_fake_bridge", "money_on"]

ORDER = "OR06024026"


@pytest.fixture(autouse=True)
def _order_search(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The 3d fake searches by number / VS; add the bridge's „order“ step over „Popis“ OR „Poznámka“."""
    calls: list[str] = []
    original = FakeBridge.search_invoices

    async def search(self: Any, *, order: str | None = None, **kw: Any) -> InvoiceSearch:
        if order:
            calls.append(order)
            rows = [i for i in FakeBridge.invoices if order in (i.description or "") or order in (i.note or "")]
            return InvoiceSearch(matched_by="order" if rows else "none", items=rows)
        return await original(self, number=kw.get("number"), vs=kw.get("vs"))

    monkeypatch.setattr(FakeBridge, "search_invoices", search)
    return calls


def _inv(
    number: str, company: uuid.UUID, days_ago: int, *, desc: str | None = None, note: str | None = None
) -> IssuedInvoice:
    return inv(number, company).model_copy(
        update={"issued_on": date(2026, 11, 1) - timedelta(days=days_ago), "description": desc, "note": note}
    )


async def _card(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, body: str
) -> AiSuggestion:
    mailbox = await _signed_in(client, db, mail_server)
    await _companies(db)
    await _message(db, mailbox, "faktury@firma1.example", body)
    stats = await suggest_invoice_attach(db, mailbox, settings.model_copy(update={"feature_money": True}), shadow=False)
    await db.commit()
    assert stats["created"] == 1, stats
    row = await db.scalar(select(AiSuggestion).where(AiSuggestion.suggestion_type == "invoice_attach"))
    assert row is not None
    return row


async def test_217_seven_found_five_newest_and_preselection(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, _order_search: list[str]
) -> None:
    FakeBridge.invoices = [
        _inv(f"FV26001{n:02d}", OURS, n, desc=f"Objednávka {ORDER}" if n in (3, 5) else None, note=f"obj. {ORDER}-x")
        for n in range(1, 8)
    ]
    FakeBridge.invoices[0] = _inv("FV2600101", OURS, 1, note=f"Vaša objednávka {ORDER}")  # only in „Poznámka“
    row = await _card(client, db, mail_server, settings, f"Pošlite faktúry k objednávke č. {ORDER}, ďakujem.")
    assert _order_search == [ORDER]
    items = row.payload["invoices"]
    assert row.payload["pick"] is True and row.batch_safe is False
    assert [i["number"] for i in items] == ["FV2600101", "FV2600102", "FV2600103", "FV2600104", "FV2600105"]
    # pre-selected: own + the whole number in Popis / Poznámka („OR06024026-x“ also holds the whole number)
    assert all(i["own"] for i in items) and all(i["selected"] for i in items)
    assert items[0]["issued_on"] == "2026-10-31"
    assert any(c["id"] == "invoice_found_by_order" for c in row.checks)


async def test_217_partial_number_is_listed_but_not_preselected(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    FakeBridge.invoices = [
        _inv("FV2600201", OURS, 1, desc=f"Objednávka {ORDER}"),
        _inv("FV2600202", OURS, 2, desc=f"Objednávka {ORDER}1"),  # a longer number — not the same order
    ]
    row = await _card(client, db, mail_server, settings, f"Faktúra k objednávke {ORDER}?")
    picked = {i["number"]: i["selected"] for i in row.payload["invoices"]}
    assert picked == {"FV2600201": True, "FV2600202": False}
    assert "FV2600201" in row.payload["body"] and "FV2600202" not in row.payload["body"]


async def _approve(client: Client, row: AiSuggestion, **body: Any) -> Any:
    return await client.send_json("POST", f"/api/suggestions/{row.id}/approve", body)


async def test_217_approve_only_the_picked_invoices(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, money_on: None
) -> None:
    FakeBridge.invoices = [
        _inv("FV2600301", OURS, 1, desc=f"Objednávka {ORDER}"),
        _inv("FV2600302", OURS, 2, note=f"Objednávka {ORDER}"),
    ]
    row = await _card(client, db, mail_server, settings, f"objednávka {ORDER}")
    r = await _approve(client, row, selected=[])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "selection_invalid"
    r = await _approve(client, row, selected=["FV9999999"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "selection_invalid"
    r = await _approve(client, row, selected=["FV2600302"])
    assert r.status_code == 200, r.text
    draft = await db.get(ComposeDraft, uuid.UUID(r.json()["draft_id"]))
    assert draft is not None
    atts = list(await db.scalars(select(ComposeAttachment).where(ComposeAttachment.draft_id == draft.id)))
    assert [a.filename for a in atts] == ["Faktura_FV2600302.pdf"]
    await db.refresh(row)
    assert row.final_payload["selected"] == ["FV2600302"]
    assert "FV2600302" in row.final_payload["body"] and "FV2600301" not in row.final_payload["body"]


async def test_217_picked_foreign_invoice_needs_the_ack_and_never_mixes(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, money_on: None
) -> None:
    FakeBridge.invoices = [
        _inv("FV2600401", OURS, 1, desc=f"Objednávka {ORDER}"),
        _inv("FV2600402", OTHER, 2, desc=f"Objednávka {ORDER}"),
    ]
    row = await _card(client, db, mail_server, settings, f"objednávka {ORDER}")
    items = {i["number"]: i for i in row.payload["invoices"]}
    assert items["FV2600402"]["own"] is False and items["FV2600402"]["selected"] is False
    assert items["FV2600402"]["owner_name"] == "Fiktívna 2 s.r.o."
    r = await _approve(client, row, selected=["FV2600401", "FV2600402"])
    assert r.status_code == 409 and r.json()["detail"]["checks"][0]["id"] == "one_customer_per_draft"
    r = await _approve(client, row, selected=["FV2600402"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ack_required"
    r = await _approve(client, row, selected=["FV2600402"], acknowledged_checks=["invoice_other_customer"])
    assert r.status_code == 200, r.text
    await db.refresh(row)
    assert row.final_payload["ack"]["owner_money_id"] == str(OTHER)
    draft = await db.get(ComposeDraft, uuid.UUID(r.json()["draft_id"]))
    assert draft is not None
    await db.refresh(draft)
    assert await attachment_send_block(db, settings, draft) is None  # the acknowledged owner, the one address
