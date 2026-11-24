"""W6h „Katalóg“ window (Erik, 24 Nov 2026; Figma 264:91756): the picker search with up to 100 rows, main cards
followed by their variants, each row with the e-shop flag and stock per warehouse (information only — D18).
All articles and warehouses are fictional."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, ClassVar

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role
from app.money.bridge_client import BridgeUnavailable
from app.money.schemas import Article, ArticleCatalogInfo, WarehouseStockRow
from tests.conftest import Client, FakeMailServer
from tests.test_mail_sync_1c import _signed_in
from tests.test_purchasing_4a import money_on
from tests.test_purchasing_4b import A_NUT, ArticleBridge, _bridge

__all__ = ["_bridge", "money_on"]

WH_A, WH_B = uuid.UUID(int=0xA1), uuid.UUID(int=0xB2)


class CatalogBridge(ArticleBridge):
    info_calls: ClassVar[list[list[uuid.UUID]]] = []
    info_down: ClassVar[bool] = False

    async def catalog_info(self, article_ids: list[uuid.UUID]) -> list[ArticleCatalogInfo]:
        self.info_calls.append(list(article_ids))
        if self.info_down:
            raise BridgeUnavailable()
        return [
            ArticleCatalogInfo(
                article_id=a,
                eshop=a == A_NUT,
                stocks=[
                    WarehouseStockRow(
                        warehouse_id=WH_A,
                        code="20",
                        name="Senica",
                        qty=Decimal("18"),
                        reserved=Decimal("0"),
                        ordered=Decimal("0"),
                        expected=Decimal("18"),
                        available=Decimal("18"),
                        unit_price=Decimal("1.642"),
                    ),
                    WarehouseStockRow(
                        warehouse_id=WH_B,
                        code="30",
                        name="Nitra",
                        qty=Decimal("6"),
                        reserved=Decimal("2"),
                        ordered=Decimal("10"),
                        expected=Decimal("14"),
                        available=Decimal("4"),
                        unit_price=None,
                    ),
                ],
            )
            for a in article_ids
        ]


@pytest.fixture(autouse=True)
def _catalog_bridge(monkeypatch: pytest.MonkeyPatch, _bridge: None) -> None:
    CatalogBridge.info_calls, CatalogBridge.info_down = [], False
    monkeypatch.setattr("app.api.purchasing.BridgeClient", CatalogBridge)


async def test_catalog_rows_have_kinds_eshop_and_stock_per_warehouse(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    await _signed_in(client, db, mail_server, role=Role.warehouse)
    variant = Article(
        id=uuid.uuid4(),
        code="N-A",
        catalog="M934-10-A",
        name="Matica DIN 934 M10 A2 variant",
        ean=None,
        unit="ks",
        parent_id=A_NUT,
        plu="var_a0148",
        last_price=Decimal("0.3271"),
    )
    CatalogBridge.extra = [variant]
    r = await client.get("/api/purchasing/catalog", params={"q": "Matica"})
    assert r.status_code == 200, r.text
    rows = r.json()
    by_id: dict[str, dict[str, Any]] = {row["id"]: row for row in rows}
    main, var = by_id[str(A_NUT)], by_id[str(variant.id)]
    assert main["kind"] == "main" and var["kind"] == "variant"
    assert [row["id"] for row in rows].index(var["id"]) == [row["id"] for row in rows].index(main["id"]) + 1
    assert main["eshop"] is True and var["eshop"] is False
    assert var["plu"] == "var_a0148" and var["last_price"] == "0.3271"  # decimals as strings, never floats
    senica, nitra = var["stocks"]
    assert (senica["code"], senica["qty"], senica["unit_price"]) == ("20", "18", "1.642")
    assert (nitra["reserved"], nitra["ordered"], nitra["expected"], nitra["unit_price"]) == ("2", "10", "14", None)
    assert CatalogBridge.info_calls == [[uuid.UUID(row["id"]) for row in rows]]  # one read for every row
    # the Katalóg asks the bridge for more text hits than the picker (30)
    assert {"code": None, "ean": None, "q": "Matica", "limit": 100} in CatalogBridge.calls


async def test_catalog_unsafe_text_money_down_and_roles(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    await _signed_in(client, db, mail_server, role=Role.warehouse)
    assert (await client.get("/api/purchasing/catalog", params={"q": "M10|x"})).status_code == 422
    assert (await client.get("/api/purchasing/catalog", params={"q": "x"})).status_code == 422  # min 2 characters
    CatalogBridge.info_down = True
    down = await client.get("/api/purchasing/catalog", params={"q": "Matica"})
    assert down.status_code == 503
    CatalogBridge.calls = []
    picker = await client.get("/api/purchasing/articles", params={"q": "Matica"})
    assert picker.status_code == 200 and all("limit" not in c for c in CatalogBridge.calls)  # picker unchanged


async def test_catalog_needs_a_purchasing_role(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    await _signed_in(client, db, mail_server, role=Role.sales)
    r = await client.get("/api/purchasing/catalog", params={"q": "Matica"})
    assert r.status_code == 403
