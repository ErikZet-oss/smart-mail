"""W6h article picker (pilot 2026-11-20): an exact catalog hit must not hide the variants of that card, and the
supplier code from the read cache finds the article too. All articles, codes and companies are fictional."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role
from app.money import bridge_client as bc
from app.money.models import MoneyArticleSupplier
from app.money.schemas import Article
from app.purchasing.numbers import normalize_code
from tests.conftest import Client, FakeMailServer
from tests.test_mail_sync_1c import _signed_in
from tests.test_purchasing_4a import SUPPLIER, money_on

__all__ = ["money_on"]


def _a(key: str, code: str, catalog: str, name: str, parent: uuid.UUID | None = None) -> Article:
    return Article(
        id=uuid.uuid5(uuid.NAMESPACE_URL, key),
        code=code,
        catalog=catalog,
        name=name,
        ean=None,
        unit="ks",
        parent_id=parent,
    )


MAIN = _a("main", "TZ-MAIN", "9990001", "Tyč závitová DIN 976 4.8 ZN 2m")
VAR_M12 = _a("m12", "TZ-M12", "99900010012", "tyč záv. M12x2000 4.8 ZN", MAIN.id)  # #233: variants of MAIN
VAR_M10 = _a("m10", "TZ-M10", "99900010010", "tyč záv. M10x2000 4.8 ZN", MAIN.id)
OTHER = _a("other", "X-1", "1234567", "Matica M10")
ARTICLES = [MAIN, VAR_M12, VAR_M10, OTHER]


class PickerBridge:
    """Mirrors the real bridge: `code` = Kod or Katalog equal, `q` = Nazev or Katalog contains."""

    def __init__(self, *_: Any, **__: Any) -> None:
        pass

    async def __aenter__(self) -> PickerBridge:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def search_articles(
        self, *, code: str | None = None, ean: str | None = None, q: str | None = None
    ) -> list[Article]:
        if ean:
            return []
        if code:
            return [a for a in ARTICLES if code in (a.code, a.catalog)]
        t = (q or "").lower()
        return [a for a in ARTICLES if t in a.name.lower() or t in (a.catalog or "")]

    async def article(self, article_id: uuid.UUID) -> Article | None:
        return next((a for a in ARTICLES if a.id == article_id), None)

    async def article_variants(self, parent_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Article]]:
        return {p: [a for a in ARTICLES if a.parent_id == p] for p in parent_ids}


@pytest.fixture(autouse=True)
def _bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    bc._circuit.success()
    monkeypatch.setattr("app.api.purchasing.BridgeClient", PickerBridge)


async def test_picker_exact_catalog_hit_still_lists_variants_exact_first(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    await _signed_in(client, db, mail_server, role=Role.warehouse)
    found = (await client.get("/api/purchasing/articles", params={"q": "9990001"})).json()
    assert [a["id"] for a in found] == [str(MAIN.id), str(VAR_M10.id), str(VAR_M12.id)]
    assert [a["kind"] for a in found] == ["main", "variant", "variant"]  # #233


async def test_picker_finds_article_by_cached_supplier_code(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    await _signed_in(client, db, mail_server, role=Role.warehouse)
    db.add(
        MoneyArticleSupplier(
            id=uuid.uuid4(),
            article_id=VAR_M10.id,
            supplier_id=SUPPLIER,
            code="09999.11.00.100.000",
            code_norm=normalize_code("09999.11.00.100.000") or "",
            name=None,
            last_price=None,
            unit="ks",
            article_unit="ks",
            article_unit_qty=None,
            active=True,
            synced_at=datetime.now(UTC),
        )
    )
    await db.commit()
    found = (await client.get("/api/purchasing/articles", params={"q": "09999.11.00"})).json()
    assert [a["id"] for a in found] == [str(VAR_M10.id)]
    assert found[0]["kind"] == "variant"  # #233: a variant without its main card stays a variant
