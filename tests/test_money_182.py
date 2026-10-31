"""#182 „pošlite poslednú faktúru“ → the newest issued invoice of the sender's company, with a warning.
Deterministic (no model call), read-only. All companies, numbers and dates are fictional."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AiSuggestion
from app.core.config import Settings
from app.mail.compose_models import ComposeDraft
from app.money.invoice_attach import latest_invoice, wants_latest
from app.money.invoice_suggest import suggest_invoice_attach
from app.money.schemas import InvoiceSearch, IssuedInvoice
from tests.conftest import Client, FakeMailServer
from tests.test_mail_sync_1c import _signed_in
from tests.test_money_3d import OTHER, OURS, FakeBridge, _companies, _fake_bridge, _message, inv, money_on

__all__ = ["_fake_bridge", "money_on"]  # the autouse bridge fake of 3d applies here too

TODAY = datetime.now(UTC).date()


def _on(
    number: str, days_ago: int, company: uuid.UUID = OURS, kind: str = "invoice", total: str = "50"
) -> IssuedInvoice:
    return inv(number, company, kind).model_copy(
        update={"issued_on": TODAY - timedelta(days=days_ago), "total": Decimal(total)}
    )


@pytest.fixture(autouse=True)
def _window_search(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """The 3d fake searches only by number / VS; add the company + date window step of the bridge cascade."""
    calls: list[dict[str, Any]] = []
    original = FakeBridge.search_invoices

    async def search(
        self: Any,
        *,
        number: str | None = None,
        vs: str | None = None,
        company_id: uuid.UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> InvoiceSearch:
        if number or vs:
            return await original(self, number=number, vs=vs)
        calls.append({"company_id": company_id, "date_from": date_from, "date_to": date_to})
        rows = [
            i
            for i in FakeBridge.invoices
            if i.company_id == company_id
            and i.issued_on is not None
            and date_from is not None
            and date_to is not None
            and date_from <= i.issued_on <= date_to
        ]
        return InvoiceSearch(matched_by="company_dates" if rows else "none", items=rows)

    monkeypatch.setattr(FakeBridge, "search_invoices", search)
    return calls


@pytest.mark.parametrize(
    "text",
    [
        "Dobrý deň, pošlite mi prosím poslednú faktúru.",
        "Prosím o poslednú FA, ďakujem",
        "Potrebujem kópiu poslednej faktúry",
        "Dobrý den, zašlete prosím poslední fakturu.",
        "Hello, could you send me the last invoice?",
        "Please resend our latest invoice.",
        "Bitte senden Sie uns die letzte Rechnung.",
    ],
)
def test_182_latest_recognised_sk_cz_en_de(text: str) -> None:
    assert wants_latest(text)


@pytest.mark.parametrize("text", ["Posledná objednávka dorazila.", "Faktúra FV2600042 je v poriadku.", "", None])
def test_182_latest_not_recognised_elsewhere(text: str | None) -> None:
    assert not wants_latest(text)


async def test_182_latest_picks_the_newest_issued_invoice_tie_by_number() -> None:
    FakeBridge.invoices = [
        _on("FV2600010", 40),
        _on("FV2600021", 3),
        _on("FV2600022", 3),  # same day → the higher number wins
        _on("FV2600030", 1, company=OTHER),  # another company
    ]
    async with FakeBridge() as bridge:
        found = await latest_invoice(bridge, OURS, TODAY)  # type: ignore[arg-type]
    assert found is not None and found.number == "FV2600022"


async def test_182_latest_skips_proformas_and_credit_notes_and_widens_the_window(
    _window_search: list[dict[str, Any]],
) -> None:
    FakeBridge.invoices = [
        _on("ZF2600050", 2, kind="proforma"),
        _on("FV2600051", 5, total="-50"),  # credit note (negative total)
        _on("FV2600011", 200),  # only in the long window
    ]
    async with FakeBridge() as bridge:
        found = await latest_invoice(bridge, OURS, TODAY)  # type: ignore[arg-type]
    assert found is not None and found.number == "FV2600011"
    assert [(TODAY - c["date_from"]).days for c in _window_search] == [31, 400]


async def test_182_suggestion_has_the_warning_and_is_not_batch_safe(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    await _companies(db)
    FakeBridge.invoices = [_on("FV2600010", 40), _on("FV2600021", 3)]
    await _message(db, mailbox, "faktury@firma1.example", "Dobrý deň, pošlite poslednú faktúru.")
    stats = await suggest_invoice_attach(db, mailbox, settings.model_copy(update={"feature_money": True}), shadow=False)
    await db.commit()
    assert stats["created"] == 1
    row = await db.scalar(select(AiSuggestion).where(AiSuggestion.suggestion_type == "invoice_attach"))
    assert row is not None and row.batch_safe is False
    assert [i["number"] for i in row.payload["invoices"]] == ["FV2600021"] and row.payload["guessed_latest"] is True
    guessed = next(c for c in row.checks if c["id"] == "invoice_guessed_latest")
    assert guessed["level"] == "warning"
    assert guessed["params"]["date"] == (TODAY - timedelta(days=3)).strftime("%d.%m.%Y")
    assert not any(c["level"] == "blocking" for c in row.checks)


async def test_182_written_numbers_win_over_latest(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    await _companies(db)
    FakeBridge.invoices = [_on("FV2600010", 40), _on("FV2600021", 3)]
    await _message(db, mailbox, "faktury@firma1.example", "Pošlite poslednú faktúru, myslím FV2600010.")
    await suggest_invoice_attach(db, mailbox, settings.model_copy(update={"feature_money": True}), shadow=False)
    await db.commit()
    row = await db.scalar(select(AiSuggestion).where(AiSuggestion.suggestion_type == "invoice_attach"))
    assert row is not None and [i["number"] for i in row.payload["invoices"]] == ["FV2600010"]
    assert not any(c["id"] == "invoice_guessed_latest" for c in row.checks)


async def test_182_without_a_strong_sender_match_no_attachment(
    client: Client,
    db: AsyncSession,
    mail_server: FakeMailServer,
    settings: Settings,
    _window_search: list[dict[str, Any]],
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    await _companies(db)
    FakeBridge.invoices = [_on("FV2600021", 3)]
    await _message(db, mailbox, "neznamy@gmail.com", "Pošlite poslednú faktúru.")
    stats = await suggest_invoice_attach(db, mailbox, settings.model_copy(update={"feature_money": True}), shadow=False)
    await db.commit()
    assert stats["created"] == 0 and stats["no_refs"] == 1
    assert _window_search == []  # Money is not even asked for an unknown sender


async def test_182_approve_rechecks_the_owner(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, money_on: None
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    await _companies(db)
    FakeBridge.invoices = [_on("FV2600021", 3)]
    await _message(db, mailbox, "faktury@firma1.example", "Pošlite poslednú faktúru.")
    await suggest_invoice_attach(db, mailbox, settings.model_copy(update={"feature_money": True}), shadow=False)
    await db.commit()
    row = await db.scalar(select(AiSuggestion).where(AiSuggestion.suggestion_type == "invoice_attach"))
    assert row is not None
    FakeBridge.invoices = [_on("FV2600021", 3, company=OTHER)]  # Money changed the customer meanwhile
    r = await client.send_json("POST", f"/api/suggestions/{row.id}/approve", {})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "suggestion_blocked"
    assert (await db.scalar(select(ComposeDraft))) is None
