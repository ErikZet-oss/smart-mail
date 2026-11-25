"""SETTINGS 11e: a second branch template for foreign suppliers (Erik 2026-11-25 — Slovak suppliers 23 %, EU
suppliers 0 % „Iba základ“). The write takes the template whose stock line has the VAT rate of the document's lines.
Money is a fake bridge; every ID, number and name is fictional."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Branch, Role
from app.core.audit import AuditLog
from app.money.schemas import ReceivedNoteRow
from app.purchasing.delivery_note import pick_template
from app.purchasing.models import DocumentLine, SupplierDocument
from tests.conftest import Client, FakeMailServer
from tests.test_mail_sync_1c import _signed_in
from tests.test_purchasing_4a import money_on
from tests.test_purchasing_4b import _bridge
from tests.test_purchasing_247 import (
    CENTRE,
    TEMPLATE_ID,
    WAREHOUSE,
    KonceptBridge,
    _create,
    _id,
    _koncept_bridge,
    _open,
    switch_on,
    template,
)

__all__ = ["_bridge", "_koncept_bridge", "money_on", "switch_on"]

FOREIGN_ID = _id("template-foreign")


def foreign() -> dict[str, Any]:
    tpl = template(TypCeny=2, DphSazba="0", SazbaDPH_ID=_id("vat-0"), DruhSazbyDPH=0)
    return {**tpl, "id": FOREIGN_ID, "number": "DLP0719/2026", "supplier": "Fiktívny EU dodávateľ"}


def _line(n: int, rate: str | None, *, fee: bool = False, status: str = "matched") -> DocumentLine:
    return DocumentLine(line_no=n, vat_rate=rate, is_fee=fee, line_status=status)


def test_DL_B6_pick_template_by_the_vat_rate_of_the_stock_lines() -> None:
    branch = Branch(name="x", dl_template_money_id=TEMPLATE_ID, dl_template_values=template())
    assert pick_template(branch, [_line(1, "0")])[0] == TEMPLATE_ID  # no second template → the main one (DL-B6)
    branch.dl_template_foreign_money_id, branch.dl_template_foreign_values = FOREIGN_ID, foreign()
    assert pick_template(branch, [_line(1, "23"), _line(2, "23.00")])[0] == TEMPLATE_ID
    assert pick_template(branch, [_line(1, "0"), _line(2, "0.00"), _line(3, "23", fee=True)])[0] == FOREIGN_ID
    assert pick_template(branch, [_line(1, "0"), _line(2, "23", status="non_stock")])[0] == FOREIGN_ID
    assert pick_template(branch, [_line(1, "0"), _line(2, "23")])[0] == TEMPLATE_ID  # mixed rates → main → DL-B6
    assert pick_template(branch, [_line(1, None)])[0] == TEMPLATE_ID  # nothing decides
    assert pick_template(None, [_line(1, "0")]) == (None, {})


async def test_DL_B6_lines_at_0_percent_use_the_foreign_template_in_checks_and_the_write(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, switch_on: None
) -> None:
    detail = await _open(client, db, mail_server, role=Role.accounting)
    doc_id = uuid.UUID(detail["id"])
    await db.execute(update(DocumentLine).where(DocumentLine.document_id == doc_id).values(vat_rate=0))
    await db.commit()
    detail = (await client.get(f"/api/purchasing/documents/{doc_id}")).json()
    b6 = [c for c in detail["checks"] if c["id"] == "DL-B6"]
    assert b6 and b6[0]["params"]["rates"] == ["0"] and b6[0]["params"]["templates"] == ["23"]
    doc = await db.get(SupplierDocument, doc_id)
    assert doc is not None and doc.branch_id is not None
    branch = await db.get(Branch, doc.branch_id)
    assert branch is not None
    branch.dl_template_foreign_money_id, branch.dl_template_foreign_values = FOREIGN_ID, foreign()
    await db.commit()
    detail = (await client.get(f"/api/purchasing/documents/{doc_id}")).json()
    assert not [c for c in detail["checks"] if c["level"] == "blocking"], detail["checks"]
    assert detail["template"]["number"] == "DLP0719/2026"  # W6h shows what the write will copy (Typ ceny …)
    r = await _create(client, detail)
    assert r.status_code == 200, r.text
    ((payload, _tok),) = KonceptBridge.posts
    for it in payload["Polozky"]:
        assert it["SazbaDPH_ID"] == _id("vat-0") and it["TypCeny"] == 2 and it["Stredisko_ID"] == CENTRE
        assert it["ObsahPolozky"]["Sklad_ID"] == WAREHOUSE
    await db.refresh(doc)
    assert doc.template_source == FOREIGN_ID


async def test_settings_11e_foreign_template_pick_by_number_verify_and_remove(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    await _signed_in(client, db, mail_server, role=Role.admin)
    branch = Branch(name="Nitra test", money_centre_id=CENTRE, money_warehouse_id=WAREHOUSE)
    branch.dl_template_money_id, branch.dl_template_values = TEMPLATE_ID, template()
    db.add(branch)
    await db.commit()
    url = f"/api/settings/money/branches/{branch.id}"
    none = (await client.get(f"{url}/dl-template", params={"kind": "foreign"})).json()
    assert none["template"] is None and none["centre_set"] is True  # never picked automatically
    KonceptBridge.rows = [
        ReceivedNoteRow(id=uuid.uuid4(), number="DLP0999/2026", supplier="x", issued_on=None, koncept=False,
                        by_smart_mail=False),
        ReceivedNoteRow(
            id=uuid.UUID(FOREIGN_ID), number="DLP0719/2026", supplier="Fiktívny EU dodávateľ", issued_on=None,
            koncept=False, by_smart_mail=False,
        )
    ]  # fmt: skip
    rows = (await client.get(f"{url}/dl-templates", params={"kind": "foreign", "number": "DLP0719/2026"})).json()
    assert [r["number"] for r in rows] == ["DLP0719/2026"] and rows[0]["selected"] is False
    same = _id("same-rate")
    KonceptBridge.templates[same] = {**template(), "id": same}
    bad = await client.send_json("PUT", f"{url}/dl-template", {"note_id": same, "kind": "foreign"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "template_same_rate"  # would never be used
    KonceptBridge.templates[FOREIGN_ID] = foreign()
    r = await client.send_json("PUT", f"{url}/dl-template", {"note_id": FOREIGN_ID, "kind": "foreign"})
    assert r.status_code == 200, r.text
    assert r.json()["template"]["number"] == "DLP0719/2026" and r.json()["template"]["vat_rate"] == "0"
    main = (await client.get(f"{url}/dl-template")).json()
    assert main["template"]["id"] == TEMPLATE_ID and main["template"]["vat_rate"] == "23"  # the main one untouched
    verify = (await client.send_json("POST", f"{url}/verify")).json()
    by_id = {row["id"]: row for row in verify["rows"]}
    assert by_id["template"]["ok"] is True and by_id["template_foreign"]["ok"] is True
    assert verify["template_foreign"]["number"] == "DLP0719/2026"
    gone = await client.send_json("DELETE", f"{url}/dl-template")
    assert gone.status_code == 200 and gone.json()["template"] is None
    await db.refresh(branch)
    assert branch.dl_template_foreign_money_id is None and branch.dl_template_money_id == TEMPLATE_ID
    kinds = [
        e.details.get("kind")
        for e in await db.scalars(select(AuditLog).where(AuditLog.action == "settings.dl_template"))
    ]
    assert kinds.count("foreign") == 2
