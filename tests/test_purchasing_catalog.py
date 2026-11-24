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
    body = r.json()
    assert body["cached"] is False and body["total"] == len(body["items"])  # before the first catalog sync: live
    rows = body["items"]
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
    short = await client.get("/api/purchasing/catalog", params={"q": "x"})  # live search needs 2 characters
    assert short.status_code == 200 and short.json()["items"] == []
    CatalogBridge.info_down = True
    down = await client.get("/api/purchasing/catalog", params={"q": "Matica"})
    assert down.status_code == 200 and down.json()["stock_available"] is False  # rows without stock
    CatalogBridge.calls = []
    picker = await client.get("/api/purchasing/articles", params={"q": "Matica"})
    assert picker.status_code == 200 and all("limit" not in c for c in CatalogBridge.calls)  # picker unchanged


async def test_catalog_needs_a_purchasing_role(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    await _signed_in(client, db, mail_server, role=Role.sales)
    r = await client.get("/api/purchasing/catalog", params={"q": "Matica"})
    assert r.status_code == 403


# ----- the read cache `money_articles` (Erik 2026-11-24: the whole catalog like in Money) -----


def _a(n: int, catalog: str, name: str, **kw: Any) -> Article:
    return Article(
        id=uuid.UUID(int=0x1000 + n), code=f"K{n}", catalog=catalog, name=name, ean=kw.pop("ean", None), unit="ks", **kw
    )


MAIN = _a(1, "9990001", "Tyč závitová DIN 976 4.8 ZN 2m", plu="var_a0310")
V8 = _a(2, "999000100008", "tyč záv. M8×2000 4.8 ZN", parent_id=MAIN.id, plu="var_a0310", last_price=Decimal("1.045"))
V10 = _a(3, "999000100010", "tyč záv. M10×2000 4.8 ZN", parent_id=MAIN.id, plu="var_a0310", last_price=Decimal("1.65"))
A4 = _a(4, "309009100010", "tyc zav. M10 A4-70", last_price=Decimal("2.735"), ean="8715492332035")
NUT = _a(5, "311492910010", "Mat. M10 A4 DIN 985", last_price=Decimal("0.073"))
HIDDEN = _a(6, "309000000001", "SMPROBE skrytá karta", inactive=True)


async def _cache(db: AsyncSession, articles: list[Article]) -> None:
    from datetime import UTC, datetime

    from sqlalchemy.dialects.postgresql import insert

    from app.money.models import MoneyArticle
    from app.purchasing.catalog import article_row

    now = datetime.now(UTC)
    await db.execute(insert(MoneyArticle).values([article_row(a, now) for a in articles]))
    await db.commit()


async def _get(client: Client, **params: Any) -> dict[str, Any]:
    r = await client.get("/api/purchasing/catalog", params=params)
    assert r.status_code == 200, r.text
    return dict(r.json())


async def test_cache_lists_the_whole_catalog_sorted_like_money_with_kinds_and_live_stock(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    await _signed_in(client, db, mail_server, role=Role.warehouse)
    await _cache(db, [NUT, A4, V10, MAIN, V8, HIDDEN])
    body = await _get(client)  # empty search = everything (hidden cards stay out, like in Money)
    assert body["cached"] is True and body["total"] == 5 and body["stock_available"] is True
    rows = body["items"]
    assert [r["catalog"] for r in rows] == ["309009100010", "311492910010", "9990001", "999000100008", "999000100010"]
    assert [r["kind"] for r in rows] == ["article", "article", "main", "variant", "variant"]
    assert rows[3]["last_price"] == "1.045000" and rows[3]["plu"] == "var_a0310" and rows[3]["stocks"][0]["qty"] == "18"
    assert CatalogBridge.info_calls == [[uuid.UUID(r["id"]) for r in rows]]  # stock only for the rows of the page
    page2 = await _get(client, offset=3, limit=2)
    assert [r["catalog"] for r in page2["items"]] == ["999000100008", "999000100010"] and page2["total"] == 5
    by_name = await _get(client, sort="name", desc=True)
    assert [r["name"] for r in by_name["items"]][:2] == ["Tyč závitová DIN 976 4.8 ZN 2m", "tyč záv. M8×2000 4.8 ZN"]
    by_price = await _get(client, sort="last_price")
    assert [r["catalog"] for r in by_price["items"]][:2] == ["311492910010", "999000100008"]  # no price → last


async def test_cache_search_text_pattern_ean_supplier_code_and_main_brings_variants(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    from datetime import UTC, datetime

    from app.money.cache_sync import save_supplier_codes
    from app.money.schemas import SupplierCode

    await _signed_in(client, db, mail_server, role=Role.warehouse)
    await _cache(db, [NUT, A4, V10, MAIN, V8, HIDDEN])
    code = SupplierCode(
        id=uuid.uuid4(), article_id=NUT.id, supplier_id=uuid.uuid4(), code="55730.100.001", name=None,
        last_price=None, unit="ks", article_unit="ks", article_unit_qty=Decimal(1),
    )  # fmt: skip
    await save_supplier_codes(db, [code], datetime.now(UTC))
    await db.commit()
    cat = lambda body: [r["catalog"] for r in body["items"]]  # noqa: E731
    assert cat(await _get(client, q="tyc zav")) == ["309009100010", "9990001", "999000100008", "999000100010"]
    assert cat(await _get(client, q="TYČ ZÁVITOVÁ")) == ["9990001", "999000100008", "999000100010"]  # main + variants
    assert cat(await _get(client, q="%tyc%M10%")) == ["309009100010", "999000100010"]  # Money pattern in the name
    assert cat(await _get(client, q="%m10%din%")) == ["311492910010"]  # pieces in their order
    assert cat(await _get(client, q="8715492332035")) == ["309009100010"]  # EAN
    assert cat(await _get(client, q="55730100001")) == ["311492910010"]  # supplier code, normalized
    assert cat(await _get(client, q="50_%")) == []  # `_` is a literal, never a LIKE wildcard
    assert (await _get(client, q="SMPROBE"))["total"] == 0  # hidden
    CatalogBridge.info_down = True
    offline = await _get(client, q="tyc")
    assert offline["stock_available"] is False and offline["total"] == 4 and offline["items"][0]["stocks"] == []


async def test_cache_sync_articles_full_then_delta_and_deactivates_deleted(db: AsyncSession) -> None:
    from sqlalchemy import select

    from app.money.cache_sync import sync_entity
    from app.money.models import MoneyArticle
    from tests.test_money_3b import FakeBridge

    bridge = FakeBridge([])
    bridge.articles_data = [MAIN, V8, V10, A4, NUT]
    first = await sync_entity(db, bridge, "articles")  # type: ignore[arg-type]
    await db.commit()
    assert first.full and first.changed == 5 and bridge.articles_since == [None, None, None]  # pages of 2
    row = await db.get(MoneyArticle, V10.id)
    assert row is not None and row.name_norm == "tyc zav. m10x2000 4.8 zn" and row.parent_id == MAIN.id
    bridge.articles_data = [V10.model_copy(update={"name": "tyč záv. M10×2000 4.8 ZN nová"})]
    delta = await sync_entity(db, bridge, "articles")  # type: ignore[arg-type]
    await db.commit()
    assert not delta.full and bridge.articles_since[-1] is not None
    await db.refresh(row)
    assert row.name.endswith("nová")
    bridge.articles_data = [MAIN, V8, V10, A4]  # NUT deleted in Money
    full = await sync_entity(db, bridge, "articles", full=True)  # type: ignore[arg-type]
    await db.commit()
    assert full.deactivated == 1
    assert (await db.scalar(select(MoneyArticle.active).where(MoneyArticle.id == NUT.id))) is False
