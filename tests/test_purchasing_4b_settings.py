"""Phase 4b-3 — SETTINGS_SPEC 14 Nákup a sklad: thresholds, confirm roles, warehouse per supplier, learned supplier
codes (list / edit / delete / CSV export). Nothing is written to Money. All data is fictional."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role
from app.money.models import MoneyCodebook
from app.purchasing.models import SupplierItemMapping
from tests.conftest import Client, FakeMailServer
from tests.test_mail_sync_1c import _signed_in
from tests.test_purchasing_4a import SUPPLIER, _supplier, money_on
from tests.test_purchasing_4b import A_NUT, ArticleBridge, _bridge, _doc, _sc

__all__ = ["_bridge", "money_on"]

WH99 = uuid.uuid5(uuid.NAMESPACE_URL, "wh-99")
URL = "/api/settings/purchasing"


async def _wh(db: AsyncSession) -> None:
    db.add(
        MoneyCodebook(kind="warehouses", money_id=WH99, code="99", name="Externý sklad", synced_at=datetime.now(UTC))
    )
    await db.commit()


async def test_14_defaults_validation_and_admin_only(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    await _signed_in(client, db, mail_server, role=Role.admin)
    await _wh(db)
    got = (await client.get(URL)).json()
    assert got["price_diff_pct"] == "10" and got["qty_diff_pct"] == "0"
    assert got["confirm_roles"] == ["warehouse", "admin"] and got["issue_date"] == "supplier"
    assert got["warehouse_rules"] == [] and got["warehouses"] == [{"id": str(WH99), "label": "99 – Externý sklad"}]
    for bad in (
        {"price_diff_pct": "101"},
        {"qty_diff_pct": "-1"},
        {"confirm_roles": []},
        {"confirm_roles": ["viewer"]},
        {"issue_date": "tomorrow"},
    ):
        r = await client.send_json("PUT", URL, bad)
        assert r.status_code == 422, bad
    r = await client.send_json(
        "PUT", URL, {"warehouse_rules": [{"supplier_money_id": str(SUPPLIER), "warehouse_id": str(uuid.uuid4())}]}
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "warehouse_not_found"
    ok = await client.send_json("PUT", URL, {"price_diff_pct": "20", "issue_date": "approval"})
    assert ok.status_code == 200 and ok.json()["price_diff_pct"] == "20" and ok.json()["issue_date"] == "approval"


async def test_14_warehouse_person_cannot_change_settings(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    await _signed_in(client, db, mail_server, role=Role.warehouse)
    assert (await client.get(URL)).status_code == 403
    assert (await client.send_json("PUT", URL, {"price_diff_pct": "50"})).status_code == 403


async def test_14_price_threshold_drives_DL_W1_and_warehouse_rule_drives_DL_W8(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    await _signed_in(client, db, mail_server, role=Role.admin)
    await _supplier(db)
    await _wh(db)
    put = await client.send_json(
        "PUT",
        URL,
        {
            "price_diff_pct": "20",
            "warehouse_rules": [{"supplier_money_id": str(SUPPLIER), "warehouse_id": str(WH99)}],
        },
    )
    assert put.status_code == 200, put.text
    ArticleBridge.codes = [_sc("934-10-A2", A_NUT, last="7.00", unit="bal", qty="200")]  # +15 % < 20 %
    doc_id = await _doc(client)
    detail = (await client.get(f"/api/purchasing/documents/{doc_id}")).json()
    assert not any(c["id"] == "DL-W1" for c in detail["checks"])
    nut = detail["items"][1]
    assert nut["warehouse_code"] == "99"  # supplier rule wins over the branch warehouse (D18)


async def test_14_confirm_roles_limit_who_confirms_a_line(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    from app.purchasing import org_settings
    from app.purchasing.org_settings import PurchasingSettings

    await org_settings.save(db, PurchasingSettings(confirm_roles=["admin"]))
    await db.commit()
    await _signed_in(client, db, mail_server, role=Role.warehouse)
    await _supplier(db)
    doc_id = await _doc(client)
    detail = (await client.get(f"/api/purchasing/documents/{doc_id}")).json()
    r = await client.send_json(
        "POST",
        f"/api/purchasing/documents/{doc_id}/lines/2/non-stock",
        {"version": detail["version"]},
    )
    assert r.status_code == 403 and r.json()["detail"]["code"] == "confirm_role_not_allowed"


async def test_14_learned_codes_list_edit_delete_and_csv_export(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    await _signed_in(client, db, mail_server, role=Role.admin)
    await _supplier(db)
    doc_id = await _doc(client)
    detail = (await client.get(f"/api/purchasing/documents/{doc_id}")).json()
    r = await client.send_json(
        "POST",
        f"/api/purchasing/documents/{doc_id}/lines/2/article",
        {"article_id": str(A_NUT), "unit_factor": "200", "version": detail["version"]},
    )
    assert r.status_code == 200, r.text
    db.add(
        SupplierItemMapping(supplier_money_id=SUPPLIER, code_norm="=CMD", article_id=A_NUT, unit_factor=Decimal("1"))
    )
    await db.commit()

    page = (await client.get(f"{URL}/mappings", params={"q": "10-A2"})).json()
    assert page["total"] == 1
    row = page["items"][0]
    assert row["supplier_name"] == "Fiktívny dodávateľ s.r.o." and row["code"] == "934-10-A2"
    assert row["article_name"] == "Matica DIN 934 M10 A2" and row["unit_factor"] == "200"
    assert row["confirmed_by"] and row["uses_count"] == 0
    assert (await client.get(f"{URL}/mappings", params={"q": "Matica"})).json()["total"] == 2

    bad = await client.send_json("PATCH", f"{URL}/mappings/{row['id']}", {"unit_factor": "0"})
    assert bad.status_code == 422
    edited = await client.send_json("PATCH", f"{URL}/mappings/{row['id']}", {"unit_factor": "12,5"})
    assert edited.status_code == 200 and edited.json()["unit_factor"] == "12.5"

    csv = await client.get(f"{URL}/mappings.csv")
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    text = csv.text.lstrip("﻿")
    assert text.splitlines()[0].startswith("Dodávateľ;Kód dodávateľa;Náš artikel")
    assert "934-10-A2;Matica DIN 934 M10 A2" in text and ";12,5;" in text
    assert "'=CMD" in text and ";=CMD" not in text  # formula injection guard

    assert (await client.send_json("DELETE", f"{URL}/mappings/{row['id']}", None)).status_code == 204
    left = list(await db.scalars(select(SupplierItemMapping.code_norm)))
    assert left == ["=CMD"]
