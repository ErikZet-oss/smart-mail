"""Phase 4b — item matching of supplier document lines to Money articles (MONEY_API §5.5.3, DOCUMENTS_SPEC §2.7).

Read-only: Money is only asked (through the bridge), nothing is written. Cascade per goods line:
1. supplier code in Money (`ArticleSuppliers` of this supplier)            → `supplier_code`
2. learned mapping confirmed by a person (`supplier_item_mappings`)        → `learned` (+ DL-W6)
3. EAN (`CarovyKod`), exactly one article                                  → `ean`
4. our code / catalog (`Kod` / `Katalog`), exactly one article             → `our_code`
5. nothing → up to 5 text candidates for the user, line stays unmatched    → `none`
Open purchase order and fastener attributes (plan 4b steps 5–6) are not built yet — follow-up.

Units: the supplier unit is converted with `article_unit_qty` of the supplier code (e.g. 1 bal = 200 ks). Quantities are
never rounded to packaging (D6/D17). Lines a person decided (`user`, `non_stock`) are never overwritten.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.guards import check
from app.auth.models import Branch
from app.money.bridge_client import BridgeClient, BridgeUnavailable
from app.money.schemas import Article, SupplierCode
from app.purchasing.models import DocumentLine, SupplierDocument, SupplierItemMapping
from app.purchasing.numbers import normalize_code

log = structlog.get_logger()

PRICE_DIFF_PCT = Decimal("10")  # SETTINGS 14 default; the setting itself comes with 4b-3
USER_METHODS = ("user", "non_stock")
MATCH_CHECKS = ("DL-B4", "DL-W1", "DL-W6", "DL-W8")
UNSAFE = set("~#|()")
ONE = Decimal("1")


def _safe(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    return None if not value or UNSAFE & set(value) else value


def _text(name: str | None) -> str | None:
    """Text search term: filter characters become spaces (names like „Matica M10 (bal. 200 ks)“ are common)."""
    cleaned = " ".join("".join(" " if ch in UNSAFE else ch for ch in (name or "")).split())[:40].strip()
    return cleaned if len(cleaned) >= 3 else None


def _same_unit(a: str | None, b: str | None) -> bool:
    return bool(a and b and a.strip().lower().rstrip(".") == b.strip().lower().rstrip("."))


def unit_factor(line_unit: str | None, sc: SupplierCode) -> Decimal:
    """How many article units one line unit is. Unknown → 1 (shown to the user, never guessed further)."""
    if _same_unit(line_unit, sc.article_unit):
        return ONE
    if sc.article_unit_qty and sc.article_unit_qty > 0 and (line_unit is None or _same_unit(line_unit, sc.unit)):
        return sc.article_unit_qty
    return ONE


def price_diff_pct(price: Decimal | None, last: Decimal | None) -> Decimal | None:
    if price is None or last is None or last <= 0:
        return None
    return ((price - last) / last * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)


def _candidate(a: Article) -> dict[str, Any]:
    return {"article_id": str(a.id), "code": a.code, "catalog": a.catalog, "name": a.name, "unit": a.unit}


@dataclass(slots=True)
class Result:
    article_id: uuid.UUID | None
    method: str
    factor: Decimal | None
    candidates: list[dict[str, Any]]
    last_price: Decimal | None = None


async def _match_line(
    line: DocumentLine,
    bridge: BridgeClient,
    codes: dict[str, SupplierCode],
    learned: dict[str, SupplierItemMapping],
) -> Result:
    norm = normalize_code(line.supplier_code)
    if norm and norm in codes:
        sc = codes[norm]
        return Result(sc.article_id, "supplier_code", unit_factor(line.unit, sc), [], sc.last_price)
    if norm and norm in learned:
        m = learned[norm]
        return Result(m.article_id, "learned", m.unit_factor, [])
    ean = _safe(line.ean)
    if ean:
        found = await bridge.search_articles(ean=ean)
        if len(found) == 1:
            return Result(found[0].id, "ean", ONE, [])
    code = _safe(line.supplier_code)
    if code:
        found = await bridge.search_articles(code=code)
        if len(found) == 1:
            return Result(found[0].id, "our_code", ONE, [])
    text = _text(line.name)
    found = await bridge.search_articles(q=text) if text else []
    return Result(None, "none", None, [_candidate(a) for a in found[:5]])


def line_checks(doc: SupplierDocument, lines: list[DocumentLine], branch_warehouse: str | None) -> list[dict[str, Any]]:
    """DL-B4 / DL-W1 / DL-W6 / DL-W8 from the stored matching state (also re-run after every user decision)."""
    out: list[dict[str, Any]] = []
    goods = [ln for ln in lines if not ln.is_fee]
    unmatched = [ln.line_no for ln in goods if ln.line_status == "unmatched"]
    if unmatched:
        out.append(check("DL-B4", "blocking", n=len(unmatched), lines=unmatched))
    for ln in goods:
        last = (ln.raw or {}).get("_last_price")
        if ln.match_method == "supplier_code" and last is not None and ln.unit_price is not None:
            pct = price_diff_pct(ln.unit_price, Decimal(str(last)))
            if pct is not None and abs(pct) > PRICE_DIFF_PCT:
                out.append(check("DL-W1", "warning", line=ln.line_no, x=str(pct), last=str(last)))
        if ln.match_method == "learned":
            out.append(check("DL-W6", "warning", line=ln.line_no, code=ln.supplier_code))
        if (
            ln.line_status == "matched"
            and ln.warehouse_id is not None
            and branch_warehouse
            and str(ln.warehouse_id).lower() != branch_warehouse.lower()
        ):
            out.append(check("DL-W8", "warning", n=ln.line_no, warehouse=str(ln.warehouse_id)))
    return out


async def _branch_warehouse(db: AsyncSession, doc: SupplierDocument) -> str | None:
    if doc.branch_id is None:
        return None
    branch = await db.get(Branch, doc.branch_id)
    return branch.money_warehouse_id if branch else None


async def refresh_checks(db: AsyncSession, doc: SupplierDocument, lines: list[DocumentLine]) -> None:
    """Replace the matching checks in `doc.validation` and recompute the review status."""
    keep = [
        c
        for c in (doc.validation or [])
        if c["id"] not in MATCH_CHECKS or (c["id"] == "DL-B4" and c["params"].get("reason") == "no_lines")
    ]
    checks = keep + line_checks(doc, lines, await _branch_warehouse(db, doc))
    doc.validation = checks
    if doc.status in ("needs_review", "missing_data"):
        doc.status = "missing_data" if any(c["level"] == "blocking" for c in checks) else "needs_review"


async def load_lines(db: AsyncSession, doc: SupplierDocument) -> list[DocumentLine]:
    return list(
        await db.scalars(select(DocumentLine).where(DocumentLine.document_id == doc.id).order_by(DocumentLine.line_no))
    )


def needs_matching(lines: list[DocumentLine]) -> bool:
    return any(not ln.is_fee and ln.match_method is None for ln in lines)


async def match_document(db: AsyncSession, bridge: BridgeClient, doc: SupplierDocument) -> bool:
    """Run the cascade for every goods line not decided by a person. False = Money unavailable (nothing changed)."""
    lines = await load_lines(db, doc)
    warehouse = await _branch_warehouse(db, doc)
    learned: dict[str, SupplierItemMapping] = {}
    try:
        codes: dict[str, SupplierCode] = {}
        if doc.supplier_money_id:
            for sc in await bridge.supplier_codes(doc.supplier_money_id):
                key = normalize_code(sc.code)
                if key:
                    codes.setdefault(key, sc)
            learned = {
                m.code_norm: m
                for m in await db.scalars(
                    select(SupplierItemMapping).where(SupplierItemMapping.supplier_money_id == doc.supplier_money_id)
                )
            }
        results = {
            ln.id: await _match_line(ln, bridge, codes, learned)
            for ln in lines
            if not ln.is_fee and ln.match_method not in USER_METHODS
        }
    except BridgeUnavailable as exc:
        log.warning("purchasing.matching_unavailable", document_id=str(doc.id), code=exc.code)
        return False
    now = datetime.now(UTC)
    for ln in lines:
        res = results.get(ln.id)
        if res is None:
            continue
        ln.article_id, ln.match_method, ln.unit_factor, ln.candidates = (
            res.article_id,
            res.method,
            res.factor,
            res.candidates,
        )
        ln.line_status = "matched" if res.article_id else "unmatched"
        ln.warehouse_id = _uuid(warehouse) if res.article_id else None
        raw = dict(ln.raw or {})
        raw["_last_price"] = None if res.last_price is None else str(res.last_price)
        ln.raw = raw
        if res.method == "learned":
            m = learned[normalize_code(ln.supplier_code) or ""]
            m.uses_count += 1
            m.last_used_at = now
    await refresh_checks(db, doc, lines)
    doc.version += 1
    log.info(
        "purchasing.matched",
        document_id=str(doc.id),
        matched=sum(1 for r in results.values() if r.article_id),
        total=len(results),
    )
    return True


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


async def confirm_article(
    db: AsyncSession,
    doc: SupplierDocument,
    line: DocumentLine,
    article: Article,
    factor: Decimal,
    person_id: uuid.UUID,
    *,
    learn: bool,
) -> None:
    """A person picks the article → the line is decided and (optionally) the mapping is learned for this supplier."""
    line.article_id, line.match_method, line.unit_factor, line.line_status = article.id, "user", factor, "matched"
    line.warehouse_id = _uuid(await _branch_warehouse(db, doc))
    line.candidates = []
    norm = normalize_code(line.supplier_code)
    if learn and norm and doc.supplier_money_id:
        now = datetime.now(UTC)
        mapping = await db.scalar(
            select(SupplierItemMapping).where(
                SupplierItemMapping.supplier_money_id == doc.supplier_money_id, SupplierItemMapping.code_norm == norm
            )
        )
        if mapping is None:
            mapping = SupplierItemMapping(supplier_money_id=doc.supplier_money_id, code_norm=norm, uses_count=0)
            db.add(mapping)
        mapping.article_id, mapping.unit_factor = article.id, factor
        mapping.confirmed_by_person_id, mapping.confirmed_at = person_id, now
    await refresh_checks(db, doc, await load_lines(db, doc))
    doc.version += 1


async def mark_non_stock(db: AsyncSession, doc: SupplierDocument, line: DocumentLine) -> None:
    line.article_id, line.match_method, line.unit_factor, line.line_status = None, "non_stock", None, "non_stock"
    line.warehouse_id, line.candidates = None, []
    await refresh_checks(db, doc, await load_lines(db, doc))
    doc.version += 1
