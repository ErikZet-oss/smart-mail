"""#174 print report of an issued invoice per branch (the invoice's centre), SK only. Fictional ids and numbers."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AiSuggestion
from app.auth.models import Branch, Role
from app.core.audit import AuditLog
from app.core.config import Settings
from app.money.invoice_attach import evaluate, load_branch_reports, report_for_invoice
from app.money.invoice_suggest import suggest_invoice_attach
from app.money.models import MoneyCodebook
from app.money.schemas import IssuedInvoice
from tests.conftest import Client, FakeMailServer
from tests.test_mail_sync_1c import _signed_in
from tests.test_money_3d import NOW, OURS, PDF, FakeBridge, _companies, _fake_bridge, _message, inv, money_on

__all__ = ["_fake_bridge", "money_on"]  # the autouse bridge fake of 3d applies here too

CENTRE_NR = uuid.uuid5(uuid.NAMESPACE_URL, "centre-30-nitra")
CENTRE_SE = uuid.uuid5(uuid.NAMESPACE_URL, "centre-20-senica")
COMPANY = {"invoice": {"sk": "12", "en": "", "de": "61"}, "proforma": {"sk": "13", "en": "", "de": ""}}


def _inv(centre: uuid.UUID | None, kind: str = "invoice", number: str = "FV2600042") -> IssuedInvoice:
    return inv(number, OURS, kind).model_copy(update={"centre_id": centre})


@pytest.fixture
def used_reports(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    async def invoice_pdf(self: Any, kind: str, invoice_id: uuid.UUID, report_id: str) -> bytes | None:
        seen.append(report_id)
        return PDF if any(i.id == invoice_id for i in FakeBridge.invoices) else None

    monkeypatch.setattr(FakeBridge, "invoice_pdf", invoice_pdf)
    return seen


async def _branches(db: AsyncSession) -> tuple[Branch, Branch]:
    for money_id, code, name in ((CENTRE_NR, "30", "Nitra"), (CENTRE_SE, "20", "Senica")):
        db.add(MoneyCodebook(kind="centres", money_id=money_id, code=code, name=name, active=True, synced_at=NOW))
    nitra = Branch(name="Nitra", money_centre_id=str(CENTRE_NR), money_report_ids={"invoice": "77"})
    senica = Branch(name="Senica", money_centre_id=str(CENTRE_SE), money_report_ids={})
    db.add_all([nitra, senica])
    await db.commit()
    return nitra, senica


def test_174_report_selection_rules() -> None:
    branches = {str(CENTRE_NR): {"invoice": "77", "proforma": "78"}}
    # SK and an empty language → the branch report
    assert report_for_invoice(COMPANY, branches, _inv(CENTRE_NR), "sk") == "77"
    assert report_for_invoice(COMPANY, branches, _inv(CENTRE_NR), None) == "77"
    assert report_for_invoice(COMPANY, branches, _inv(CENTRE_NR, "proforma"), "sk") == "78"
    # EN/DE → company report of that language, else the branch SK report
    assert report_for_invoice(COMPANY, branches, _inv(CENTRE_NR), "de") == "61"
    assert report_for_invoice(COMPANY, branches, _inv(CENTRE_NR), "en") == "77"
    # centre without a branch, invoice without a centre → 13b as before
    assert report_for_invoice(COMPANY, branches, _inv(CENTRE_SE), "sk") == "12"
    assert report_for_invoice(COMPANY, branches, _inv(None), "en") == "12"
    # nothing configured → None (the blocking check `report_not_configured` stays)
    assert report_for_invoice({}, {}, _inv(CENTRE_NR), "sk") is None


def test_174_branch_without_proforma_falls_back_to_company() -> None:
    branches = {str(CENTRE_NR): {"invoice": "77"}}
    assert report_for_invoice(COMPANY, branches, _inv(CENTRE_NR, "proforma"), "sk") == "13"
    empty_company = {"invoice": {"sk": "", "en": "", "de": ""}}
    assert report_for_invoice(empty_company, branches, _inv(CENTRE_NR), "en") == "77"


async def test_174_branch_reports_loaded_by_centre(db: AsyncSession) -> None:
    await _branches(db)
    db.add(Branch(name="Bez strediska", money_report_ids={"invoice": "90"}))
    await db.commit()
    assert await load_branch_reports(db) == {str(CENTRE_NR): {"invoice": "77"}}


async def test_174_evaluate_blocks_only_when_no_report_at_all(db: AsyncSession, settings: Settings) -> None:
    await _branches(db)
    await _companies(db)
    from app.ai.models import OrgSettings
    from app.money.invoice_attach import SECTION_REPORTS

    row = await db.scalar(select(OrgSettings).where(OrgSettings.section == SECTION_REPORTS))
    assert row is not None
    row.data = {"invoice": {"sk": "", "en": "", "de": ""}, "proforma": {"sk": "", "en": "", "de": ""}}
    await db.commit()
    from app.money.models import EmailCompanyLink

    db.add(EmailCompanyLink(email="faktury@firma1.example", company_money_id=OURS))
    await db.commit()
    FakeBridge.invoices = [_inv(CENTRE_NR), _inv(CENTRE_SE, number="FV2600043")]
    async with FakeBridge() as bridge:
        out = await evaluate(
            db,
            settings,
            bridge,
            email="faktury@firma1.example",
            body_text=None,  # type: ignore[arg-type]
            refs=["FV2600042", "FV2600043"],
            language="sk",
        )
    blocked = [c for c in out.checks if c["id"] == "report_not_configured"]
    assert len(blocked) == 1  # Nitra has its own report, Senica falls back to an empty 13b


async def test_174_approve_selects_the_branch_report_again(
    client: Client,
    db: AsyncSession,
    mail_server: FakeMailServer,
    settings: Settings,
    money_on: None,
    used_reports: list[str],
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    nitra, _ = await _branches(db)
    await _companies(db)
    FakeBridge.invoices = [_inv(CENTRE_NR)]
    await _message(db, mailbox, "faktury@firma1.example", "Prosím kópiu FV2600042.")
    await suggest_invoice_attach(db, mailbox, settings.model_copy(update={"feature_money": True}), shadow=False)
    await db.commit()
    row = await db.scalar(select(AiSuggestion).where(AiSuggestion.suggestion_type == "invoice_attach"))
    assert row is not None
    # the branch report changes between the suggestion and the approval → the approval uses the new one
    nitra.money_report_ids = {"invoice": "88"}
    await db.commit()
    r = await client.send_json("POST", f"/api/suggestions/{row.id}/approve", {})
    assert r.status_code == 200, r.text
    assert used_reports == ["88"]


async def test_174_settings_11e_api(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None, used_reports: list[str]
) -> None:
    await _signed_in(client, db, mail_server, role=Role.admin)
    nitra, senica = await _branches(db)
    await _companies(db)
    listed = (await client.get("/api/settings/money/branches")).json()
    assert [c["code"] for c in listed["centres"]] == ["20", "30"]
    by_name = {b["name"]: b for b in listed["branches"]}
    assert by_name["Nitra"]["reports"] == {"invoice": "77", "proforma": ""}

    url = f"/api/settings/money/branches/{senica.id}"
    r = await client.send_json("PUT", url, {"centre_id": str(uuid.uuid4()), "reports": {}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "centre_unknown"
    r = await client.send_json("PUT", url, {"centre_id": str(CENTRE_SE), "reports": {"invoice": "1 OR 1"}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "report_id_invalid"
    guid = str(uuid.uuid4())
    r = await client.send_json(
        "PUT", url, {"centre_id": str(CENTRE_SE), "reports": {"invoice": "31", "proforma": guid}}
    )
    assert r.status_code == 200 and r.json()["reports"] == {"invoice": "31", "proforma": guid}
    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "settings.branch_money"))
    assert entry is not None and entry.details["after"]["reports"]["invoice"] == "31"

    # „Vyskúšať PDF“: only an invoice of this branch's centre
    FakeBridge.invoices = [_inv(CENTRE_SE), _inv(CENTRE_NR, number="FV2600050")]
    r = await client.get(f"{url}/test?kind=invoice&number=FV2600042")
    assert r.status_code == 200 and r.content == PDF and used_reports == ["31"]
    r = await client.get(f"{url}/test?kind=invoice&number=FV2600050")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "invoice_other_branch"
    r = await client.get(f"/api/settings/money/branches/{nitra.id}/test?kind=proforma&number=FV2600050")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "report_not_configured"


async def test_174_settings_11e_admin_only(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    await _signed_in(client, db, mail_server, role=Role.sales)
    assert (await client.get("/api/settings/money/branches")).status_code == 403
