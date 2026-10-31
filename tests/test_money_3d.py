"""Phase 3d invoice_attach: references, owner check, approve → draft with the Money PDF, send-time recipient check,
„Poslať“ from the card, Settings 13b. All companies, numbers and PDFs are fictional."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, ClassVar

import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AiSuggestion, Classification, OrgSettings
from app.auth.models import Role
from app.core.audit import AuditLog
from app.core.config import Settings
from app.mail.compose import attachment_send_block
from app.mail.compose_models import ComposeAttachment, ComposeDraft
from app.mail.models import FolderMeta, Mailbox, Message
from app.money import bridge_client as bc
from app.money.bridge_client import BridgeUnavailable
from app.money.invoice_attach import (
    SECTION_REPORTS,
    draft_body,
    evaluate,
    invoice_refs,
    marked_company,
    pick_report,
    report_id_valid,
    storage_prefix,
)
from app.money.invoice_suggest import suggest_invoice_attach
from app.money.models import EmailCompanyLink, MoneyCompany
from app.money.schemas import InvoiceSearch, IssuedInvoice
from tests.conftest import Client, FakeMailServer
from tests.test_mail_sync_1c import _signed_in

NOW = datetime(2026, 10, 31, 8, 0, tzinfo=UTC)
OURS = uuid.uuid5(uuid.NAMESPACE_URL, "company-ours")
OTHER = uuid.uuid5(uuid.NAMESPACE_URL, "company-other")
PDF = b"%PDF-1.4 fictional invoice"


def inv(number: str, company: uuid.UUID, kind: str = "invoice") -> IssuedInvoice:
    return IssuedInvoice(
        id=uuid.uuid5(uuid.NAMESPACE_URL, number),
        kind=kind,  # type: ignore[arg-type]
        number=number,
        variable_symbol=number[-7:],
        company_id=company,
        issued_on=date(2026, 9, 1),
        due_on=date(2026, 9, 15),
        paid_on=None,
        total=Decimal("120.50"),
        remaining=Decimal("120.50"),
        currency_id=None,
        reference=None,
        doc_type=0,
    )


class FakeBridge:
    """Stands in for BridgeClient: a tiny invoice register and PDFs."""

    invoices: ClassVar[list[IssuedInvoice]] = []
    down: ClassVar[bool] = False

    def __init__(self, *_: Any, **__: Any) -> None:
        pass

    async def __aenter__(self) -> FakeBridge:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def search_invoices(
        self, *, number: str | None = None, vs: str | None = None, company_id: uuid.UUID | None = None
    ) -> InvoiceSearch:
        if self.down:
            raise BridgeUnavailable()
        rows = [i for i in self.invoices if (number and i.number == number) or (vs and i.variable_symbol == vs)]
        return InvoiceSearch(matched_by="number" if rows else "none", items=rows)

    async def invoice_pdf(self, kind: str, invoice_id: uuid.UUID, report_id: str) -> bytes | None:
        return PDF if any(i.id == invoice_id for i in self.invoices) else None


@pytest.fixture(autouse=True)
def _fake_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    bc._circuit.success()
    FakeBridge.invoices = [inv("FV2600042", OURS), inv("FV2600099", OTHER), inv("ZF2600007", OURS, "proforma")]
    FakeBridge.down = False
    monkeypatch.setattr("app.money.bridge_client.BridgeClient", FakeBridge)
    monkeypatch.setattr("app.api.money.BridgeClient", FakeBridge)
    monkeypatch.setattr("app.api.settings_money.BridgeClient", FakeBridge)
    monkeypatch.setattr("app.money.invoice_suggest.BridgeClient", FakeBridge)


async def _companies(db: AsyncSession) -> None:
    for money_id, n in ((OURS, 1), (OTHER, 2)):
        db.add(
            MoneyCompany(
                money_id=money_id,
                code=f"F{n}",
                name=f"Fiktívna {n} s.r.o.",
                emails=[f"faktury@firma{n}.example"],
                connections=[],
                active=True,
                synced_at=NOW,
            )
        )
    db.add(
        OrgSettings(
            section=SECTION_REPORTS,
            data={"invoice": {"sk": "12", "en": "", "de": ""}, "proforma": {"sk": "13", "en": "", "de": ""}},
        )
    )
    await db.commit()


def test_3d_invoice_references_in_the_mail() -> None:
    text = "Dobrý deň, prosím o kópiu faktúry č. 2026/0815 a FV2600042, VS: 2600099. Objednávka 12 ks M8."
    assert invoice_refs(text) == ["FV2600042", "2026/0815", "2600099"]
    assert invoice_refs("Pošlite faktúru") == [] and invoice_refs(None) == []
    assert invoice_refs("zf 26-0007 prosím") == ["ZF26-0007"]


def test_3d_reports_language_fallback_and_validation() -> None:
    reports = {"invoice": {"sk": "12", "en": "", "de": "14"}, "proforma": {"sk": "", "en": "", "de": ""}}
    assert pick_report(reports, "invoice", "de") == "14"
    assert pick_report(reports, "invoice", "en") == "12"  # empty language → SK
    assert pick_report(reports, "invoice", "cs") == "12"
    assert pick_report(reports, "proforma", "sk") is None
    assert report_id_valid("12") and report_id_valid(str(uuid.uuid4()))
    assert not report_id_valid("12;DROP") and not report_id_valid("../x")


def test_3d_marker_round_trip_and_body() -> None:
    draft = uuid.uuid4()
    key = storage_prefix(draft, OURS) + "/ab/cd/file"
    assert marked_company(key) == OURS and marked_company(f"compose/{draft}/ab/cd/x") is None
    assert "kópiu faktúry FV1" in draft_body("sk", ["FV1"]) and "copies of invoices" in draft_body("en", ["A", "B"])


async def test_3d_evaluate_owner_recipient_and_report(db: AsyncSession, settings: Settings) -> None:
    await _companies(db)
    bridge = FakeBridge()
    ok = await evaluate(
        db, settings, bridge, email="faktury@firma1.example", body_text=None, refs=["FV2600042"], language="sk"
    )  # type: ignore[arg-type]
    assert not ok.blocked and [i.number for i in ok.invoices] == ["FV2600042"]
    foreign = await evaluate(
        db, settings, bridge, email="faktury@firma1.example", body_text=None, refs=["FV2600099"], language="sk"
    )  # type: ignore[arg-type]
    assert foreign.blocked and not foreign.invoices
    assert {c["id"] for c in foreign.checks} >= {"recipient_not_document_owner", "no_invoice"}
    assert "Fiktívna 2" not in str(foreign.checks)  # the other company is never named
    weak = await evaluate(
        db, settings, bridge, email="novy@firma1.example", body_text=None, refs=["FV2600042"], language="sk"
    )  # type: ignore[arg-type]
    assert weak.blocked and any(c["id"] == "recipient_unconfirmed" for c in weak.checks)  # domain only
    missing = await evaluate(
        db, settings, bridge, email="faktury@firma1.example", body_text=None, refs=["FV9999999"], language="sk"
    )  # type: ignore[arg-type]
    assert any(c["id"] == "invoice_not_found" and c["level"] == "warning" for c in missing.checks)


async def _message(db: AsyncSession, mailbox: Mailbox, sender: str, body: str) -> Message:
    inbox = await db.scalar(select(FolderMeta).where(FolderMeta.mailbox_id == mailbox.id, FolderMeta.name == "INBOX"))
    assert inbox is not None
    mailbox.ai_enabled = True
    mailbox.ai_enabled_at = datetime(2026, 1, 1, tzinfo=UTC)
    message = Message(
        mailbox_id=mailbox.id,
        folder_id=inbox.id,
        uid=91,
        message_id="<inv-91@firma.example>",
        subject="Kópia faktúry",
        from_email=sender,
        to_addrs=[{"email": mailbox.email}],
        body_text=body,
        received_at=NOW,
    )
    db.add(message)
    await db.flush()
    db.add(
        Classification(
            mailbox_id=mailbox.id,
            message_id=message.id,
            message_id_header="inv-91@firma.example",
            category="invoice_request",
            language="sk",
            status="done",
            payload={},
        )
    )
    await db.commit()
    return message


@pytest.fixture
def money_on(app: FastAPI, settings: Settings) -> Any:
    app.state.settings.feature_money = True
    yield
    app.state.settings.feature_money = False


async def test_3d_suggestion_created_only_for_the_owners_invoice(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    await _companies(db)
    await _message(db, mailbox, "faktury@firma1.example", "Prosím kópiu FV2600042 a FV2600099.")
    on = settings.model_copy(update={"feature_money": True})
    off = await suggest_invoice_attach(db, mailbox, settings, shadow=False)
    assert off["created"] == 0  # FEATURE_MONEY off
    stats = await suggest_invoice_attach(db, mailbox, on, shadow=False)
    await db.commit()
    assert stats["created"] == 1
    row = await db.scalar(select(AiSuggestion).where(AiSuggestion.suggestion_type == "invoice_attach"))
    assert row is not None
    assert [i["number"] for i in row.payload["invoices"]] == ["FV2600042"]  # never the other company's invoice
    assert row.payload["to"] == ["faktury@firma1.example"]
    other = next(c for c in row.checks if c["id"] == "invoice_other_customer")
    assert other["level"] == "warning" and not any(c["level"] == "blocking" for c in row.checks)
    again = await suggest_invoice_attach(db, mailbox, on, shadow=False)
    assert again["created"] == 0  # idempotent


async def test_3d_money_down_creates_nothing(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    await _companies(db)
    await _message(db, mailbox, "faktury@firma1.example", "Prosím kópiu FV2600042.")
    FakeBridge.down = True
    stats = await suggest_invoice_attach(db, mailbox, settings.model_copy(update={"feature_money": True}), shadow=False)
    assert stats["created"] == 0 and stats["money_down"] == 1


async def test_3d_approve_creates_a_draft_with_the_money_pdf_and_send_checks_recipients(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, money_on: None
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    await _companies(db)
    await _message(db, mailbox, "faktury@firma1.example", "Prosím kópiu FV2600042.")
    await suggest_invoice_attach(db, mailbox, settings.model_copy(update={"feature_money": True}), shadow=False)
    await db.commit()
    row = await db.scalar(select(AiSuggestion).where(AiSuggestion.suggestion_type == "invoice_attach"))
    assert row is not None and not any(c["level"] == "blocking" for c in row.checks)

    r = await client.send_json("POST", f"/api/suggestions/{row.id}/approve", {})
    assert r.status_code == 200, r.text
    draft = await db.get(ComposeDraft, uuid.UUID(r.json()["draft_id"]))
    assert draft is not None and [a["email"] for a in draft.to_addrs] == ["faktury@firma1.example"]
    atts = (await db.scalars(select(ComposeAttachment).where(ComposeAttachment.draft_id == draft.id))).all()
    assert [a.filename for a in atts] == ["Faktura_FV2600042.pdf"] and marked_company(atts[0].storage_key) == OURS
    assert "FV2600042" in draft.body_html
    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "ai.suggestion_approved"))
    assert entry is not None and entry.details["invoices"] == ["FV2600042"]

    # at send: the right recipient passes, a changed recipient is blocked (no wrong-recipient send)
    assert await attachment_send_block(db, settings, draft) is None
    draft.to_addrs = [{"name": None, "email": "faktury@firma2.example"}]
    blocked = await attachment_send_block(db, settings, draft)
    assert blocked is not None and blocked.code == "recipient_not_document_owner"
    draft.to_addrs = [{"name": None, "email": "faktury@firma1.example"}]
    draft.cc_addrs = [{"name": None, "email": "spy@gmail.com"}]
    assert (await attachment_send_block(db, settings, draft)) is not None
    draft.cc_addrs = [{"name": None, "email": "kolega@smartsro.sk"}]  # our own people are fine
    assert await attachment_send_block(db, settings, draft) is None


async def test_3d_approve_rechecks_owner_live(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, money_on: None
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    await _companies(db)
    await _message(db, mailbox, "faktury@firma1.example", "Prosím kópiu FV2600042.")
    await suggest_invoice_attach(db, mailbox, settings.model_copy(update={"feature_money": True}), shadow=False)
    await db.commit()
    row = await db.scalar(select(AiSuggestion).where(AiSuggestion.suggestion_type == "invoice_attach"))
    assert row is not None
    FakeBridge.invoices = [inv("FV2600042", OTHER)]  # Money changed the customer of the invoice meanwhile
    r = await client.send_json("POST", f"/api/suggestions/{row.id}/approve", {})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "suggestion_blocked"
    FakeBridge.down = True
    r = await client.send_json("POST", f"/api/suggestions/{row.id}/approve", {})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "money_unavailable"
    assert (await db.scalar(select(ComposeDraft))) is None


async def test_3d_send_from_the_card(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    await _companies(db)
    message = await _message(db, mailbox, "info@firma1.example", "Ďakujeme.")
    db.add(EmailCompanyLink(email="info@firma1.example", company_money_id=OURS))
    await db.commit()
    url = f"/api/money/messages/{message.id}/invoice-draft"
    r = await client.send_json("POST", url, {"number": "ZF2600007"})
    assert r.status_code == 200, r.text
    att = await db.scalar(select(ComposeAttachment))
    assert att is not None and att.filename == "Zalohova_faktura_ZF2600007.pdf"
    r = await client.send_json("POST", url, {"number": "FV2600099"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "suggestion_blocked"


async def test_3d_warehouse_cannot_send_invoices(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    mailbox = await _signed_in(client, db, mail_server, role=Role.warehouse)
    await _companies(db)
    message = await _message(db, mailbox, "faktury@firma1.example", "x")
    r = await client.send_json("POST", f"/api/money/messages/{message.id}/invoice-draft", {"number": "FV2600042"})
    assert r.status_code == 403


async def test_3d_settings_13b(client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None) -> None:
    await _signed_in(client, db, mail_server, role=Role.admin)
    await _companies(db)
    body = {"invoice": {"sk": "21", "en": "", "de": str(uuid.uuid4())}, "proforma": {"sk": "13", "en": "", "de": ""}}
    assert (await client.send_json("PUT", "/api/settings/money/reports", body)).status_code == 200
    assert (await client.get("/api/settings/money/reports")).json()["invoice"]["sk"] == "21"
    bad = {**body, "invoice": {"sk": "1 OR 1", "en": "", "de": ""}}
    r = await client.send_json("PUT", "/api/settings/money/reports", bad)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "report_id_invalid"
    r = await client.get("/api/settings/money/reports/test?kind=invoice&lang=en&number=FV2600042")
    assert r.status_code == 200 and r.content == PDF
    assert (
        await client.get("/api/settings/money/reports/test?kind=invoice&lang=sk&number=FV0000000")
    ).status_code == 404
