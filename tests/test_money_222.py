"""#222 issued delivery note as Money's own print PDF (`/pdfreport`): branch report (11e), the `delivery_note_attach`
card and the customer panel. Read only, no migration. All companies, numbers and ids are fictional."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, ClassVar

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AiSuggestion
from app.auth.models import Branch, Role
from app.core.audit import AuditLog
from app.core.config import Settings
from app.mail.compose import attachment_send_block
from app.mail.compose_models import ComposeAttachment, ComposeDraft
from app.money.delivery_note_attach import asks_for_correction, delivery_refs, wants_delivery_note
from app.money.delivery_note_suggest import suggest_delivery_note_attach
from app.money.invoice_attach import marked_company
from app.money.invoice_suggest import suggest_invoice_attach
from app.money.schemas import Delivery, DeliverySearch
from tests.conftest import Client, FakeMailServer
from tests.test_mail_sync_1c import _signed_in
from tests.test_money_3d import OTHER, OURS, FakeBridge, _companies, _fake_bridge, _message, money_on

CENTRE_NR = uuid.uuid5(uuid.NAMESPACE_URL, "centre-30-nitra")


async def test_222_settings_11e_delivery_note_report_without_migration(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    from app.money.models import MoneyCodebook
    from tests.test_money_3d import NOW

    await _signed_in(client, db, mail_server, role=Role.admin)
    db.add(MoneyCodebook(kind="centres", money_id=CENTRE_NR, code="30", name="Nitra", active=True, synced_at=NOW))
    branch = Branch(name="Nitra", money_centre_id=str(CENTRE_NR), money_report_ids={"invoice": "77"})
    db.add(branch)
    await db.commit()
    url = f"/api/settings/money/branches/{branch.id}"
    body = {
        "centre_id": str(CENTRE_NR),
        "reports": {"invoice": "77", "delivery_note": "12", "delivery_note_design": "x y"},
    }
    r = await client.send_json("PUT", url, body)
    assert r.status_code == 422 and r.json()["detail"] == {"code": "report_id_invalid", "kind": "delivery_note_design"}
    body["reports"]["delivery_note_design"] = "34"
    r = await client.send_json("PUT", url, body)
    assert r.status_code == 200, r.text
    assert r.json()["reports"]["delivery_note"] == "12" and r.json()["reports"]["delivery_note_design"] == "34"
    await db.refresh(branch)
    assert branch.money_report_ids == {"invoice": "77", "delivery_note": "12", "delivery_note_design": "34"}
    stored = await db.scalar(select(Branch.money_report_ids).where(Branch.id == branch.id))
    assert stored is not None and stored["delivery_note"] == "12"


# ----- delivery_note_attach -----

__all__ = ["_fake_bridge", "money_on"]

PDF = b"%PDF-1.4 fiktivny dodaci list"


def note(
    number: str,
    company: uuid.UUID,
    days_ago: int = 1,
    *,
    desc: str | None = None,
    memo: str | None = None,
    centre: uuid.UUID | None = CENTRE_NR,
) -> Delivery:
    return Delivery(
        id=uuid.uuid5(uuid.NAMESPACE_URL, f"dl-{number}"),
        number=number,
        company_id=company,
        issued_on=date(2026, 11, 18) - timedelta(days=days_ago),
        moved_on=None,
        reference=None,
        state=1,
        transport=None,
        total=Decimal("88.40"),
        centre_id=centre,
        description=desc,
        note=memo,
    )


class Notes:
    rows: ClassVar[list[Delivery]] = []
    pdf_calls: ClassVar[list[tuple[str, str, str | None]]] = []


@pytest.fixture(autouse=True)
def _fake_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    Notes.rows, Notes.pdf_calls = [], []

    async def search_deliveries(
        self: Any, *, number: str | None = None, order: str | None = None, company_id: uuid.UUID | None = None
    ) -> DeliverySearch:
        if number:
            rows = [d for d in Notes.rows if d.number == number]
            return DeliverySearch(matched_by="number" if rows else "none", items=rows)
        if order:
            rows = [d for d in Notes.rows if order in (d.description or "") or order in (d.note or "")]
            return DeliverySearch(matched_by="order" if rows else "none", items=rows)
        rows = [d for d in Notes.rows if d.company_id == company_id]
        return DeliverySearch(matched_by="company" if rows else "none", items=rows)

    async def document_pdf(
        self: Any, kind: str, record_id: uuid.UUID, report_id: str, design_id: str | None = None
    ) -> bytes | None:
        Notes.pdf_calls.append((kind, report_id, design_id))
        return PDF if any(d.id == record_id for d in Notes.rows) else None

    monkeypatch.setattr(FakeBridge, "search_deliveries", search_deliveries, raising=False)
    monkeypatch.setattr(FakeBridge, "document_pdf", document_pdf, raising=False)
    monkeypatch.setattr("app.money.delivery_note_suggest.BridgeClient", FakeBridge)


@pytest.mark.parametrize(
    ("text", "wants", "refs", "corrected"),
    [
        ("Prosím o preposlanie (opraveného) dodacieho listu k objednávke OR06024026", True, [], True),
        ("Pošlite dodací list č. DV260042", True, ["DV260042"], False),
        ("DL 2026/0417 prosím", True, ["2026/0417"], False),
        ("Dodací list DL-2600417 a DV260043", True, ["DL-2600417", "DV260043"], False),
        ("Bitte senden Sie den korrigierten Lieferschein Nr. 4711-2026", True, ["4711-2026"], True),
        ("Please send the corrected delivery note", True, [], True),
        ("Pošlite nový dodací list", True, [], True),
        ("Kópia faktúry FV2600042", False, [], False),
        ("Dajte 1 dl vody a 123456", False, [], False),  # „dl“ = decilitre
    ],
)
def test_222_parsing_table(text: str, wants: bool, refs: list[str], corrected: bool) -> None:
    assert wants_delivery_note(text) is wants
    assert delivery_refs(text) == refs
    assert asks_for_correction(text) is corrected


async def _setup(client: Client, db: AsyncSession, mail_server: FakeMailServer, *, report: bool = True) -> Any:
    from app.money.models import MoneyCodebook
    from tests.test_money_3d import NOW

    mailbox = await _signed_in(client, db, mail_server)
    await _companies(db)
    db.add(MoneyCodebook(kind="centres", money_id=CENTRE_NR, code="30", name="Nitra", active=True, synced_at=NOW))
    ids = {"delivery_note": "12", "delivery_note_design": "34"} if report else {}
    db.add(Branch(name="Pobočka Nitra", money_centre_id=str(CENTRE_NR), money_report_ids=ids))
    await db.commit()
    return mailbox


async def _card(
    client: Client,
    db: AsyncSession,
    mail_server: FakeMailServer,
    settings: Settings,
    body: str,
    *,
    report: bool = True,
    category: str = "document_request",
) -> AiSuggestion | None:
    mailbox = await _setup(client, db, mail_server, report=report)
    msg = await _message(db, mailbox, "faktury@firma1.example", body)
    msg.subject = "Dodací list"
    from app.ai.models import Classification

    cls = await db.scalar(select(Classification).where(Classification.message_id == msg.id))
    assert cls is not None
    cls.category = category
    await db.commit()
    on = settings.model_copy(update={"feature_money": True})
    await suggest_delivery_note_attach(db, mailbox, on, shadow=False)
    await db.commit()
    return await db.scalar(select(AiSuggestion).where(AiSuggestion.suggestion_type == "delivery_note_attach"))


async def test_222_number_in_the_mail_gives_a_preselected_card(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    Notes.rows = [note("DV260042", OURS), note("DV260041", OURS, 3)]
    row = await _card(client, db, mail_server, settings, "Pošlite prosím dodací list č. DV260042.")
    assert row is not None and row.batch_safe is False and row.payload["pick"] is True
    items = row.payload["invoices"]
    assert [i["number"] for i in items] == ["DV260042"]
    assert items[0]["selected"] is True and items[0]["kind"] == "delivery_note" and items[0]["report_ok"] is True
    assert "dodací list DV260042" in row.payload["body"]


async def test_222_order_in_popis_or_poznamka_seven_found_five_shown(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    Notes.rows = [
        note(
            f"DV2601{n:02d}",
            OURS,
            n,
            desc="Objednávka OR06024026" if n % 2 else None,
            memo=None if n % 2 else "Vaša obj. OR06024026",
        )
        for n in range(1, 8)
    ]
    row = await _card(client, db, mail_server, settings, "Dodací list k objednávke č. OR06024026, opravený prosím.")
    assert row is not None
    items = row.payload["invoices"]
    assert [i["number"] for i in items] == [f"DV2601{n:02d}" for n in range(1, 6)]
    assert all(i["selected"] for i in items)  # the whole order number in Popis or Poznámka
    ids = [c["id"] for c in row.checks]
    assert "delivery_note_found_by_order" in ids and "delivery_note_corrected" in ids
    assert row.payload["corrected"] is True


async def test_222_latest_notes_of_the_sender_when_nothing_is_written(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    Notes.rows = [note("DV260050", OURS, 2), note("DV260051", OTHER, 1)]
    row = await _card(client, db, mail_server, settings, "Pošlite nám prosím posledný dodací list.")
    assert row is not None
    assert [i["number"] for i in row.payload["invoices"]] == ["DV260050"]  # never another company's latest
    assert row.payload["invoices"][0]["selected"] is False
    assert any(c["id"] == "delivery_note_latest" for c in row.checks)


async def test_222_another_companys_note_needs_the_ack(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    Notes.rows = [note("DV260099", OTHER)]
    row = await _card(client, db, mail_server, settings, "Dodací list DV260099 prosím.")
    assert row is not None and row.payload["foreign"] is True
    assert row.payload["invoices"][0]["owner_name"] == "Fiktívna 2 s.r.o."
    assert any(c["id"] == "invoice_other_customer" and c["level"] == "requires_ack" for c in row.checks)


async def test_222_no_branch_report_no_card_and_missing_report_blocks(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    Notes.rows = [note("DV260042", OURS)]
    assert await _card(client, db, mail_server, settings, "Dodací list DV260042", report=False) is None


async def test_222_note_of_a_branch_without_report_is_blocking(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    Notes.rows = [note("DV260042", OURS, centre=uuid.uuid4())]  # a centre of no branch
    row = await _card(client, db, mail_server, settings, "Dodací list DV260042")
    assert row is not None and row.payload["invoices"][0]["report_ok"] is False
    assert any(c["id"] == "delivery_note_report_missing" and c["level"] == "blocking" for c in row.checks)


async def test_222_delivery_note_request_gets_no_invoice_card(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    mailbox = await _setup(client, db, mail_server)
    msg = await _message(db, mailbox, "faktury@firma1.example", "Pošlite dodací list k objednávke 2410006820.")
    msg.subject = "Dodací list"
    await db.commit()
    stats = await suggest_invoice_attach(db, mailbox, settings.model_copy(update={"feature_money": True}), shadow=False)
    assert stats["created"] == 0


async def test_222_approve_rechecks_and_attaches_moneys_pdf(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, money_on: None
) -> None:
    Notes.rows = [note("DV260042", OURS), note("DV260041", OURS, 3)]
    row = await _card(client, db, mail_server, settings, "Dodací list DV260042 a DV260041")
    assert row is not None
    r = await client.send_json("POST", f"/api/suggestions/{row.id}/approve", {"selected": ["DV260041"]})
    assert r.status_code == 200, r.text
    draft = await db.get(ComposeDraft, uuid.UUID(r.json()["draft_id"]))
    assert draft is not None and [a["email"] for a in draft.to_addrs] == ["faktury@firma1.example"]
    atts = list(await db.scalars(select(ComposeAttachment).where(ComposeAttachment.draft_id == draft.id)))
    assert [a.filename for a in atts] == ["Dodaci_list_DV260041.pdf"] and marked_company(atts[0].storage_key) == OURS
    assert Notes.pdf_calls == [("issued_delivery_note", "12", "34")]
    await db.refresh(draft)
    assert await attachment_send_block(db, settings, draft) is None


async def test_222_approve_owner_changed_or_deleted_or_no_report(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, money_on: None
) -> None:
    Notes.rows = [note("DV260042", OURS)]
    row = await _card(client, db, mail_server, settings, "Dodací list DV260042")
    assert row is not None
    url = f"/api/suggestions/{row.id}/approve"
    Notes.rows = [note("DV260042", OTHER)]  # Money moved the note to another customer
    r = await client.send_json("POST", url, {})
    assert r.status_code == 409 and r.json()["detail"]["checks"][0]["id"] == "recipient_not_document_owner"
    Notes.rows = []  # deleted in Money
    r = await client.send_json("POST", url, {})
    assert r.status_code == 409 and r.json()["detail"]["checks"][0]["id"] == "delivery_note_not_found"
    Notes.rows = [note("DV260042", OURS, centre=uuid.uuid4())]
    r = await client.send_json("POST", url, {})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "delivery_note_report_missing"
    assert await db.scalar(select(ComposeDraft)) is None


async def test_222_approve_foreign_needs_ack_then_audits(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, money_on: None
) -> None:
    Notes.rows = [note("DV260099", OTHER)]
    row = await _card(client, db, mail_server, settings, "Dodací list DV260099 prosím.")
    assert row is not None
    url = f"/api/suggestions/{row.id}/approve"
    r = await client.send_json("POST", url, {"selected": ["DV260099"]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ack_required"
    r = await client.send_json(
        "POST", url, {"selected": ["DV260099"], "acknowledged_checks": ["invoice_other_customer"]}
    )
    assert r.status_code == 200, r.text
    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "money.delivery_note_other_customer_ack"))
    assert entry is not None and entry.details["owner_money_id"] == str(OTHER)
    draft = await db.get(ComposeDraft, uuid.UUID(r.json()["draft_id"]))
    assert draft is not None
    await db.refresh(draft)
    await db.refresh(row)  # this test session cached the suggestion before approve
    assert await attachment_send_block(db, settings, draft) is None
    draft.cc_addrs = [{"email": "niekto@gmail.example"}]  # a second external address → blocked (#215)
    await db.commit()
    blocked = await attachment_send_block(db, settings, draft)
    assert blocked is not None and blocked.code == "recipient_not_document_owner"


# ----- customer panel / W9a: PDF icon on recent delivery notes -----


async def test_222_card_marks_notes_with_a_branch_report_and_serves_the_pdf(
    client: Client,
    db: AsyncSession,
    mail_server: FakeMailServer,
    settings: Settings,
    money_on: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_money_3c import FakeCardBridge

    await _setup(client, db, mail_server)
    with_branch, without_branch = note("DV260042", OURS), note("DV260043", OURS, centre=uuid.uuid4())
    other = note("DV260099", OTHER)
    Notes.rows = [with_branch, without_branch, other]

    async def deliveries(self: Any, money_id: uuid.UUID, since: date) -> list[Delivery]:
        return [d for d in Notes.rows if d.company_id == money_id]

    async def document_pdf(
        self: Any, kind: str, record_id: uuid.UUID, report_id: str, design_id: str | None = None
    ) -> bytes | None:
        Notes.pdf_calls.append((kind, report_id, design_id))
        return PDF

    monkeypatch.setattr(FakeCardBridge, "deliveries", deliveries)
    monkeypatch.setattr(FakeCardBridge, "document_pdf", document_pdf, raising=False)
    monkeypatch.setattr("app.api.money.BridgeClient", FakeCardBridge)
    card = (await client.get(f"/api/money/companies/{OURS}/card")).json()
    assert card["delivery_pdf"] == [str(with_branch.id)]

    base = f"/api/money/companies/{OURS}/delivery-notes"
    r = await client.get(f"{base}/{with_branch.id}/pdf")
    assert r.status_code == 200 and r.content == PDF and r.headers["content-type"] == "application/pdf"
    assert 'filename="Dodaci_list_DV260042.pdf"' in r.headers["content-disposition"]
    assert Notes.pdf_calls == [("issued_delivery_note", "12", "34")]
    r = await client.get(f"{base}/{without_branch.id}/pdf")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "delivery_note_report_missing"
    r = await client.get(f"{base}/{other.id}/pdf")  # a note of another company is never served under this one
    assert r.status_code == 404
