"""Phase 4b — item matching (read-only): cascade, unit conversion, learned mappings, DL-B4/W1/W6/W8 and the line APIs.
Money is a fake bridge; all companies, articles, codes and prices are fictional."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, ClassVar

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role
from app.money import bridge_client as bc
from app.money.bridge_client import BridgeUnavailable
from app.money.schemas import Article, SupplierCode
from app.purchasing.item_matching import line_checks, price_diff_pct, unit_factor
from app.purchasing.models import DocumentLine, SupplierDocument, SupplierItemMapping
from tests.conftest import Client, FakeMailServer
from tests.test_mail_sync_1c import _signed_in
from tests.test_purchasing_4a import ISDOC, SUPPLIER, _supplier, _upload, money_on

__all__ = ["money_on"]

A_BOLT = uuid.uuid5(uuid.NAMESPACE_URL, "art-933-10-30")
A_NUT = uuid.uuid5(uuid.NAMESPACE_URL, "art-934-10")
A_OTHER = uuid.uuid5(uuid.NAMESPACE_URL, "art-other")


def _art(aid: uuid.UUID, code: str, name: str, ean: str | None = None) -> Article:
    return Article(id=aid, code=code, catalog=None, name=name, ean=ean, unit="ks")


ARTICLES = [
    _art(A_BOLT, "S933-1030", "Skrutka DIN 933 M10x30 A2", "8590000000017"),
    _art(A_NUT, "M934-10", "Matica DIN 934 M10 A2"),
    _art(A_OTHER, "X-1", "Iný artikel"),
]


def _sc(
    code: str, article: uuid.UUID, last: str | None = None, unit: str = "ks", qty: str | None = None
) -> SupplierCode:
    return SupplierCode(
        article_id=article,
        supplier_id=SUPPLIER,
        code=code,
        name=None,
        last_price=None if last is None else Decimal(last),
        unit=unit,
        article_unit="ks",
        article_unit_qty=None if qty is None else Decimal(qty),
    )


class ArticleBridge:
    codes: ClassVar[list[SupplierCode]] = []
    down: ClassVar[bool] = False
    calls: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, *_: Any, **__: Any) -> None:
        pass

    async def __aenter__(self) -> ArticleBridge:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def supplier_codes(self, supplier_id: uuid.UUID) -> list[SupplierCode]:
        if self.down:
            raise BridgeUnavailable()
        return [c for c in self.codes if c.supplier_id == supplier_id]

    async def search_articles(
        self, *, code: str | None = None, ean: str | None = None, q: str | None = None
    ) -> list[Article]:
        self.calls.append({"code": code, "ean": ean, "q": q})
        if ean:
            return [a for a in ARTICLES if a.ean == ean]
        if code:
            return [a for a in ARTICLES if a.code == code]
        return [a for a in ARTICLES if q and q.split()[0].lower() in a.name.lower()]

    async def article(self, article_id: uuid.UUID) -> Article | None:
        return next((a for a in ARTICLES if a.id == article_id), None)


@pytest.fixture(autouse=True)
def _bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    bc._circuit.success()
    ArticleBridge.codes, ArticleBridge.down, ArticleBridge.calls = [], False, []
    monkeypatch.setattr("app.api.purchasing.BridgeClient", ArticleBridge)


# ----- pure functions -----


def test_4b_unit_factor_supplier_package_to_article_units_no_rounding() -> None:
    sc = _sc("934-10-A2", A_NUT, unit="bal", qty="200")
    assert unit_factor("bal", sc) == Decimal("200")
    assert unit_factor(None, sc) == Decimal("200")
    assert unit_factor("ks", sc) == Decimal("1")
    assert unit_factor("kg", sc) == Decimal("1")  # unknown unit → never guessed
    assert unit_factor("bal", _sc("x", A_NUT, unit="bal", qty="12.5")) == Decimal("12.5")  # D17: no rounding


def test_4b_price_diff_pct() -> None:
    assert price_diff_pct(Decimal("1.10"), Decimal("1.00")) == Decimal("10.0")
    assert price_diff_pct(Decimal("0.80"), Decimal("1.00")) == Decimal("-20.0")
    assert price_diff_pct(Decimal("1"), None) is None and price_diff_pct(Decimal("1"), Decimal("0")) is None


def _ln(no: int, status: str = "matched", method: str | None = "supplier_code", **kw: Any) -> DocumentLine:
    base: dict[str, Any] = {"line_no": no, "name": "x", "is_fee": False, "raw": {}, "unit_price": Decimal("1")}
    base.update(kw)
    return DocumentLine(line_status=status, match_method=method, **base)


def _ids(checks: list[dict[str, Any]]) -> list[str]:
    return [c["id"] for c in checks]


WH = "11111111-1111-1111-1111-111111111111"


def test_DL_B4_unmatched_goods_lines_block_fees_and_non_stock_do_not() -> None:
    lines = [
        _ln(1, "unmatched", "none"),
        _ln(2, "non_stock", "non_stock"),
        _ln(3, "unmatched", None, is_fee=True),
    ]
    checks = line_checks(SupplierDocument(), lines, None)
    assert checks == [{"id": "DL-B4", "level": "blocking", "params": {"n": 1, "lines": [1]}}]


def test_DL_W1_price_differs_from_last_supplier_price_over_10_pct() -> None:
    ok = _ln(1, unit_price=Decimal("1.09"), raw={"_last_price": "1.00"})
    high = _ln(2, unit_price=Decimal("1.25"), raw={"_last_price": "1.00"})
    checks = line_checks(SupplierDocument(), [ok, high], None)
    assert checks == [{"id": "DL-W1", "level": "warning", "params": {"line": 2, "x": "25.0", "last": "1.00"}}]


def test_DL_W6_learned_mapping_not_in_money_card() -> None:
    assert _ids(line_checks(SupplierDocument(), [_ln(1, method="learned", supplier_code="AB-1")], None)) == ["DL-W6"]


def test_DL_W8_line_warehouse_is_not_the_branch_warehouse() -> None:
    other = uuid.UUID("22222222-2222-2222-2222-222222222222")
    same = _ln(1, warehouse_id=uuid.UUID(WH))
    diff = _ln(2, warehouse_id=other)
    assert _ids(line_checks(SupplierDocument(), [same, diff], WH)) == ["DL-W8"]


# ----- API -----


async def _doc(client: Client) -> str:
    r = await _upload(client, "FA-2026-00456.isdoc", ISDOC, "application/xml")
    assert r.status_code == 200, r.text
    return str(r.json()["id"])


async def test_4b_cascade_supplier_code_with_package_factor_ean_and_price_check(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    await _signed_in(client, db, mail_server, role=Role.warehouse)
    await _supplier(db)
    # line 2 (12 bal á 8,05) is in the supplier codes; line 1 only has an EAN
    ArticleBridge.codes = [_sc("934 10 A2", A_NUT, last="7.00", unit="bal", qty="200")]
    doc_id = await _doc(client)
    detail = (await client.get(f"/api/purchasing/documents/{doc_id}")).json()
    assert detail["money_available"] is True
    one, two, fee = detail["items"]
    assert (one["match_method"], one["article_id"], one["unit_factor"]) == ("ean", str(A_BOLT), "1.000000")
    assert (two["match_method"], two["article_id"], two["unit_factor"]) == ("supplier_code", str(A_NUT), "200.000000")
    assert fee["is_fee"] and fee["match_method"] is None
    assert two["qty"] == "12.000"  # the document quantity is never changed; the factor is shown next to it
    w1 = [c for c in detail["checks"] if c["id"] == "DL-W1"]
    assert w1 == [{"id": "DL-W1", "level": "warning", "params": {"line": 2, "x": "15.0", "last": "7.00"}}]
    assert not any(c["id"] == "DL-B4" for c in detail["checks"])
    # the second open does not ask Money again
    calls = len(ArticleBridge.calls)
    await client.get(f"/api/purchasing/documents/{doc_id}")
    assert len(ArticleBridge.calls) == calls


async def test_4b_unmatched_line_confirmed_by_a_person_is_learned_for_the_next_document(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    await _signed_in(client, db, mail_server, role=Role.warehouse)
    await _supplier(db)
    doc_id = await _doc(client)
    detail = (await client.get(f"/api/purchasing/documents/{doc_id}")).json()
    two = detail["items"][1]
    assert two["line_status"] == "unmatched" and two["match_method"] == "none"
    assert str(A_NUT) in [c["article_id"] for c in two["candidates"]]  # found by text for the picker
    assert detail["status"] == "missing_data"
    assert next(c for c in detail["checks"] if c["id"] == "DL-B4")["params"]["lines"] == [2]

    stale = await client.send_json(
        "POST",
        f"/api/purchasing/documents/{doc_id}/lines/2/article",
        {"article_id": str(A_NUT), "unit_factor": "200", "version": detail["version"] - 1},
    )
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "version_conflict"
    r = await client.send_json(
        "POST",
        f"/api/purchasing/documents/{doc_id}/lines/2/article",
        {"article_id": str(A_NUT), "unit_factor": "200", "version": detail["version"]},
    )
    assert r.status_code == 200, r.text
    after = r.json()
    assert after["items"][1]["match_method"] == "user" and after["status"] == "needs_review"
    assert not any(c["id"] == "DL-B4" for c in after["checks"])
    mapping = await db.scalar(select(SupplierItemMapping))
    assert mapping is not None and mapping.code_norm == "93410A2" and mapping.article_id == A_NUT
    assert mapping.unit_factor == Decimal("200") and mapping.confirmed_by_person_id is not None

    # „Znova spárovať“ keeps the person's decision
    again = (await client.send_json("POST", f"/api/purchasing/documents/{doc_id}/match", {})).json()
    assert again["items"][1]["match_method"] == "user"

    # next invoice of the same supplier → learned mapping + DL-W6 (not yet in the Money card)
    doc2 = await _upload(
        client, "FA-2026-00457.isdoc", ISDOC.replace(b"FA-2026-00456", b"FA-2026-00457"), "application/xml"
    )
    d2 = (await client.get(f"/api/purchasing/documents/{doc2.json()['id']}")).json()
    assert d2["items"][1]["match_method"] == "learned" and d2["items"][1]["unit_factor"] == "200.000000"
    assert any(c["id"] == "DL-W6" for c in d2["checks"])
    await db.refresh(mapping)
    assert mapping.uses_count == 1


async def test_4b_non_stock_line_and_unknown_article(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    await _signed_in(client, db, mail_server, role=Role.warehouse)
    await _supplier(db)
    doc_id = await _doc(client)
    detail = (await client.get(f"/api/purchasing/documents/{doc_id}")).json()
    bad = await client.send_json(
        "POST",
        f"/api/purchasing/documents/{doc_id}/lines/2/article",
        {"article_id": str(uuid.uuid4()), "version": detail["version"]},
    )
    assert bad.status_code == 422
    fee = await client.send_json(
        "POST", f"/api/purchasing/documents/{doc_id}/lines/3/non-stock", {"version": detail["version"]}
    )
    assert fee.status_code == 404  # fees are never items
    r = await client.send_json(
        "POST", f"/api/purchasing/documents/{doc_id}/lines/2/non-stock", {"version": detail["version"]}
    )
    assert r.status_code == 200 and r.json()["items"][1]["line_status"] == "non_stock"
    assert not any(c["id"] == "DL-B4" for c in r.json()["checks"])


async def test_4b_money_down_leaves_lines_and_mail_untouched(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    await _signed_in(client, db, mail_server, role=Role.warehouse)
    await _supplier(db)
    ArticleBridge.down = True
    doc_id = await _doc(client)
    r = await client.get(f"/api/purchasing/documents/{doc_id}")
    assert r.status_code == 200 and r.json()["money_available"] is False
    assert all(i["match_method"] is None for i in r.json()["items"])
    ArticleBridge.down = False
    assert (await client.get(f"/api/purchasing/documents/{doc_id}")).json()["items"][1]["match_method"] == "none"


async def test_4b_article_search_rejects_filter_characters_and_roles(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    await _signed_in(client, db, mail_server, role=Role.warehouse)
    assert (await client.get("/api/purchasing/articles", params={"q": "M10|x"})).status_code == 422
    found = (await client.get("/api/purchasing/articles", params={"q": "8590000000017"})).json()
    assert [a["id"] for a in found] == [str(A_BOLT)]
    found = (await client.get("/api/purchasing/articles", params={"q": "Matica"})).json()
    assert [a["id"] for a in found] == [str(A_NUT)]
