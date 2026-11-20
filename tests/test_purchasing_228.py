"""#228 supplier codes from the read cache `money_article_suppliers` instead of loading every code of a supplier
through the bridge (a 5 000 row limit lost most codes of a big supplier). All codes and ids are fictional."""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.money import agenda
from app.money.bridge_client import BridgeUnavailable
from app.money.cache_sync import save_supplier_codes, sync_entity
from app.money.jobs import run_money_sync
from app.money.models import MoneyArticleSupplier
from app.money.schemas import Article, SupplierCode, SupplierCodePage
from app.purchasing.item_matching import match_document
from app.purchasing.models import DocumentLine, SupplierDocument
from app.purchasing.numbers import normalize_code
from tests.test_money_3b import FakeBridge, _company

SUPPLIER = uuid.uuid5(uuid.NAMESPACE_URL, "supplier-mekrs-fiktivny")
WANTED = "09150.14.01.120.000"
A_WANTED = uuid.uuid5(uuid.NAMESPACE_URL, "article-wanted")


def code(n: int, value: str | None = None, article: uuid.UUID | None = None) -> SupplierCode:
    return SupplierCode(
        id=uuid.uuid5(uuid.NAMESPACE_URL, f"as-{n}"),
        article_id=article or uuid.uuid5(uuid.NAMESPACE_URL, f"art-{n}"),
        supplier_id=SUPPLIER,
        code=value or f"{n:05d}.10.20.{n % 997:03d}",
        name=None,
        last_price=Decimal("0.0840"),
        unit="ks",
        article_unit="ks",
        article_unit_qty=Decimal("1"),
    )


class MatchBridge:
    """The bridge as seen by `match_document`: no „all codes“ method exists any more — only the fallback lookup."""

    def __init__(self, lookup: dict[str, list[SupplierCode]] | None = None) -> None:
        self.lookup = lookup or {}
        self.lookups: list[str] = []

    async def lookup_supplier_code(self, supplier_id: uuid.UUID, value: str) -> list[SupplierCode]:
        self.lookups.append(value)
        return self.lookup.get(value, [])

    async def search_articles(self, **_: Any) -> list[Article]:
        return []

    async def article(self, article_id: uuid.UUID) -> Article | None:
        return Article(id=article_id, code="X", catalog=None, name="Fiktívny artikel", ean=None, unit="ks")


async def _doc(db: AsyncSession, codes: list[str], *, decided: dict[int, str] | None = None) -> SupplierDocument:
    doc = SupplierDocument(
        source="upload",
        kind="delivery_note",
        status="missing_data",
        storage_key="k",
        filename="DL.pdf",
        content_type="application/pdf",
        sha256=uuid.uuid4().hex,
        supplier_money_id=SUPPLIER,
    )
    db.add(doc)
    await db.flush()
    for n, value in enumerate(codes, 1):
        method = (decided or {}).get(n)
        db.add(
            DocumentLine(
                document_id=doc.id,
                line_no=n,
                supplier_code=value,
                name=f"Riadok {n}",
                qty=Decimal("1"),
                unit="ks",
                unit_price=Decimal("0.08"),
                line_status="matched" if method else "unmatched",
                match_method=method,
                article_id=uuid.uuid5(uuid.NAMESPACE_URL, "chosen-by-person") if method == "user" else None,
            )
        )
    await db.commit()
    await db.refresh(doc)
    return doc


async def _lines(db: AsyncSession, doc: SupplierDocument) -> list[DocumentLine]:
    await db.refresh(doc)
    doc_id = doc.id
    db.expire_all()
    rows = await db.scalars(
        select(DocumentLine).where(DocumentLine.document_id == doc_id).order_by(DocumentLine.line_no)
    )
    return list(rows)


def test_228_code_norm_ignores_dots_spaces_dashes_and_case() -> None:
    assert normalize_code("09150.14.01.120.000") == normalize_code("09150 14 01 120 000")
    # (the issue's third example „0915014011200 0“ has one digit less — it is a different code)
    assert normalize_code("09150.14.01.120.000") == normalize_code("09150-14-01-120-000") == "091501401120000"
    assert normalize_code("0915014011200 0") != normalize_code("09150.14.01.120.000")
    assert normalize_code("din-933 m8x30") == normalize_code("DIN 933 M8X30")


async def test_228_regression_6000_codes_in_random_order_are_all_found_from_the_cache(db: AsyncSession) -> None:
    rows = [code(n) for n in range(1, 6201)] + [code(9999, WANTED, A_WANTED)]
    random.Random(228).shuffle(rows)
    await save_supplier_codes(db, rows, datetime.now(UTC))
    await db.commit()
    doc = await _doc(db, ["09150 14 01 120 000", rows[17].code, "NEZNAMY-1"])
    bridge = MatchBridge()
    assert await match_document(db, bridge, doc)  # type: ignore[arg-type]
    await db.commit()
    one, two, three = await _lines(db, doc)
    assert (one.match_method, one.article_id) == ("supplier_code", A_WANTED)  # before: lost after 5 000 rows
    assert two.match_method == "supplier_code" and two.article_id == rows[17].article_id
    assert three.line_status == "unmatched"
    assert bridge.lookups == ["NEZNAMY-1"]  # ≤ the number of lines the cache does not know


async def test_228_fallback_finds_a_new_code_and_stores_it_in_the_cache(db: AsyncSession) -> None:
    new = code(1, "NEW-2026/01")
    doc = await _doc(db, ["NEW-2026/01", "NEW-2026/01", "zly(kod)|x", None or "AB~1"])
    bridge = MatchBridge({"NEW-2026/01": [new]})
    assert await match_document(db, bridge, doc)  # type: ignore[arg-type]
    await db.commit()
    lines = await _lines(db, doc)
    assert lines[0].match_method == "supplier_code" and lines[1].match_method == "supplier_code"
    assert bridge.lookups == ["NEW-2026/01"]  # once per code; values with ~ # | ( ) never reach the bridge
    cached = await db.scalar(select(MoneyArticleSupplier).where(MoneyArticleSupplier.id == new.id))
    assert cached is not None and cached.code_norm == "NEW202601" and cached.supplier_id == SUPPLIER


async def test_228_empty_cache_uses_only_the_per_line_fallback(db: AsyncSession) -> None:
    doc = await _doc(db, [WANTED, "OTHER-1"])
    bridge = MatchBridge({WANTED: [code(9999, WANTED, A_WANTED)]})
    assert await match_document(db, bridge, doc)  # type: ignore[arg-type]
    assert bridge.lookups == [WANTED, "OTHER-1"]
    assert not hasattr(bridge, "supplier_codes")  # there is no „load all codes“ path any more


async def test_228_money_down_during_fallback_changes_nothing(db: AsyncSession) -> None:
    class Down(MatchBridge):
        async def lookup_supplier_code(self, supplier_id: uuid.UUID, value: str) -> list[SupplierCode]:
            raise BridgeUnavailable()

    doc = await _doc(db, [WANTED])
    assert await match_document(db, Down(), doc) is False  # type: ignore[arg-type]


# ----- sync -----


async def test_228_sync_first_full_then_delta_with_changefrom_and_full_deactivates(db: AsyncSession) -> None:
    bridge = FakeBridge([_company(0)])
    bridge.supplier_codes_data = [code(1), code(2), code(3)]
    first = await sync_entity(db, bridge, "article_suppliers")  # type: ignore[arg-type]
    await db.commit()
    assert first.full and first.changed == 3 and bridge.supplier_since == [None, None]
    bridge.supplier_codes_data = [code(1, "CHANGED-1")]
    delta = await sync_entity(db, bridge, "article_suppliers")  # type: ignore[arg-type]
    await db.commit()
    assert not delta.full and bridge.supplier_since[-1] is not None  # ChangeFrom = the cursor
    row = await db.get(MoneyArticleSupplier, code(1).id)
    assert row is not None and row.code == "CHANGED-1" and row.code_norm == "CHANGED1"
    bridge.supplier_codes_data = [code(1, "CHANGED-1"), code(3)]  # 2 was deleted in Money
    full = await sync_entity(db, bridge, "article_suppliers", full=True)  # type: ignore[arg-type]
    await db.commit()
    assert full.deactivated == 1
    active = set(await db.scalars(select(MoneyArticleSupplier.id).where(MoneyArticleSupplier.active)))
    assert active == {code(1).id, code(3).id}
    assert await db.scalar(select(func.count()).select_from(MoneyArticleSupplier)) == 3  # never deleted


async def test_228_agenda_switch_resyncs_the_codes_in_full(app: FastAPI, settings: Settings) -> None:
    on = settings.model_copy(update={"feature_money": True})
    bridge = FakeBridge([_company(0)])
    bridge.supplier_codes_data = [code(1)]
    await run_money_sync(app.state.sessionmaker, on, app.state.redis, client=bridge)  # type: ignore[arg-type]
    bridge.agenda = "PROD"
    results = await run_money_sync(app.state.sessionmaker, on, app.state.redis, client=bridge)  # type: ignore[arg-type]
    by_entity = {r.entity: r for r in results}
    assert by_entity["article_suppliers"].full is True
    async with app.state.sessionmaker() as db:
        assert (await agenda.load(db))["resync_pending"] is False


async def test_228_first_full_sync_rematches_drafts_but_never_a_persons_choice(
    app: FastAPI, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with app.state.sessionmaker() as db:
        doc = await _doc(db, [WANTED, "OTHER-1"], decided={2: "user"})
        doc_id = doc.id
    on = settings.model_copy(update={"feature_money": True})
    bridge = FakeBridge([_company(0)])
    bridge.supplier_codes_data = [code(9999, WANTED, A_WANTED), code(2, "OTHER-1")]

    async def lookup(self: Any, supplier_id: uuid.UUID, value: str) -> list[SupplierCode]:
        raise AssertionError("everything is in the cache now")

    async def article(self: Any, article_id: uuid.UUID) -> Article | None:
        return Article(id=article_id, code="X", catalog=None, name="Fiktívny", ean=None, unit="ks")

    async def search_articles(self: Any, **_: Any) -> list[Article]:
        return []

    monkeypatch.setattr(FakeBridge, "lookup_supplier_code", lookup, raising=False)
    monkeypatch.setattr(FakeBridge, "article", article, raising=False)
    monkeypatch.setattr(FakeBridge, "search_articles", search_articles, raising=False)
    await run_money_sync(app.state.sessionmaker, on, app.state.redis, client=bridge)  # type: ignore[arg-type]
    async with app.state.sessionmaker() as db:
        lines = list(
            await db.scalars(
                select(DocumentLine).where(DocumentLine.document_id == doc_id).order_by(DocumentLine.line_no)
            )
        )
        assert (lines[0].match_method, lines[0].article_id) == ("supplier_code", A_WANTED)
        assert lines[1].match_method == "user"  # a person's decision stays
        assert lines[1].article_id == uuid.uuid5(uuid.NAMESPACE_URL, "chosen-by-person")


def test_228_page_model_carries_the_money_id() -> None:
    page = SupplierCodePage(items=[code(1)], next_from=None)
    assert page.items[0].id == code(1).id
