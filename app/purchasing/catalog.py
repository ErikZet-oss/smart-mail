"""W6h Katalóg on the read cache `money_articles` (Erik 2026-11-24): list, sort and search the whole Money catalog.

Search like the picker: exact catalog / code, EAN, supplier code (`money_article_suppliers`), catalog / code / name
containing the text, or — with `%` — the Money S4 pattern in the name (`%mat%4%934` = „mat“, then „4“, then „934“).
Case and diacritics are ignored (`norm`). A main card that matches brings its variants along. Sorted by catalog (Money
default) — a variant's catalog starts with its main card's, so it follows it — or by name, PLU, last price.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.money.models import MoneyArticle, MoneyArticleSupplier
from app.money.schemas import Article
from app.purchasing.numbers import normalize_code

Sort = Literal["catalog", "name", "plu", "last_price"]
Kind = Literal["article", "main", "variant"]
SUPPLIER_CODE_HITS = 50
_SPACES = re.compile(r"\s+")


def norm(text: str | None) -> str:
    """Lower-case without diacritics and with single spaces: „Tyč závitová“ → „tyc zavitova“."""
    plain = unicodedata.normalize("NFKD", (text or "").replace("×", "x")).encode("ascii", "ignore").decode("ascii")
    return _SPACES.sub(" ", plain.lower()).strip()


def _like(text: str) -> str:
    """A LIKE fragment: `%`, `_` and `\\` of the user text are literals (`%` is handled before, as the pattern)."""
    return text.replace("\\", "\\\\").replace("_", "\\_")


def article_row(a: Article, now: datetime) -> dict[str, Any]:
    return {
        "id": a.id,
        "code": (a.code or None) and a.code[:100],
        "catalog": (a.catalog or None) and a.catalog[:100],
        "name": (a.name or "")[:255],
        "ean": (a.ean or None) and a.ean[:64],
        "unit": a.unit,
        "parent_id": a.parent_id,
        "plu": (a.plu or None) and a.plu[:64],
        "last_price": a.last_price,
        "search_norm": norm(" ".join(x for x in (a.catalog, a.code, a.name) if x)),
        "name_norm": norm(a.name),
        "hidden": a.inactive,
        "active": True,
        "synced_at": now,
    }


@dataclass
class CatalogPage:
    total: int
    rows: list[tuple[MoneyArticle, Kind]]


def _filters(term: str) -> tuple[Any, list[str]]:
    """The WHERE of a search + the normalized supplier-code prefix to look up (empty = no supplier-code step)."""
    t = term.strip()
    if not t:
        return None, []
    if "%" in t:
        pieces = [norm(p) for p in t.split("%") if norm(p)]
        if not pieces:
            return None, []
        pattern = "%" + "%".join(_like(p) for p in pieces) + "%"
        return MoneyArticle.name_norm.like(pattern, escape="\\"), []
    n = norm(t)
    conds = [
        MoneyArticle.catalog == t,
        MoneyArticle.code == t,
        MoneyArticle.search_norm.like(f"%{_like(n)}%", escape="\\"),
    ]
    if t.isdigit() and len(t) >= 8:
        conds.append(MoneyArticle.ean == t)
    code = normalize_code(t) or ""
    return or_(*conds), [code] if len(code) >= 5 else []


async def search(
    db: AsyncSession,
    q: str,
    *,
    sort: Sort = "catalog",
    desc: bool = False,
    offset: int = 0,
    limit: int = 100,
) -> CatalogPage:
    """One page of the catalog (active, not hidden). Empty `q` = the whole catalog."""
    where, codes = _filters(q)
    visible = and_(MoneyArticle.active.is_(True), MoneyArticle.hidden.is_(False))
    if where is not None:
        matched: Any = where
        if codes:
            by_code = (
                select(MoneyArticleSupplier.article_id)
                .where(MoneyArticleSupplier.active.is_(True), MoneyArticleSupplier.code_norm.startswith(codes[0]))
                .limit(SUPPLIER_CODE_HITS)
            )
            matched = or_(matched, MoneyArticle.id.in_(by_code))
        hits = select(MoneyArticle.id).where(visible, matched)
        # a main card that matches brings its variants along (like the picker, #233)
        cond = and_(visible, or_(MoneyArticle.id.in_(hits), MoneyArticle.parent_id.in_(hits)))
    else:
        cond = visible
    child = aliased(MoneyArticle)
    is_main = exists().where(child.parent_id == MoneyArticle.id, child.active.is_(True), child.hidden.is_(False))
    # byte order (COLLATE "C"): the same on every server, digits before letters like in Money
    key: Any = {
        "catalog": func.coalesce(MoneyArticle.catalog, MoneyArticle.code, "").collate("C"),
        "name": MoneyArticle.name_norm.collate("C"),
        "plu": func.coalesce(MoneyArticle.plu, "").collate("C"),
        "last_price": MoneyArticle.last_price,
    }[sort]
    order = [
        key.desc().nulls_last() if desc else key.asc().nulls_last(),
        MoneyArticle.name_norm.collate("C"),
        MoneyArticle.id,
    ]
    total = int(await db.scalar(select(func.count()).select_from(MoneyArticle).where(cond)) or 0)
    query = select(MoneyArticle, is_main.label("is_main")).where(cond).order_by(*order).offset(offset).limit(limit)
    rows = (await db.execute(query)).all()
    out: list[tuple[MoneyArticle, Kind]] = []
    for art, main in rows:
        kind: Kind = "variant" if art.parent_id else ("main" if main else "article")
        out.append((art, kind))
    return CatalogPage(total=total, rows=out)


async def cached(db: AsyncSession) -> bool:
    """The cache has had its first sync (until then the Katalóg searches Money live)."""
    return (await db.scalar(select(MoneyArticle.id).limit(1))) is not None


def as_article(a: MoneyArticle) -> Article:
    return Article(
        id=a.id,
        code=a.code,
        catalog=a.catalog,
        name=a.name,
        ean=a.ean,
        unit=a.unit,
        inactive=a.hidden,
        parent_id=a.parent_id,
        plu=a.plu,
        last_price=Decimal(a.last_price) if a.last_price is not None else None,
    )
