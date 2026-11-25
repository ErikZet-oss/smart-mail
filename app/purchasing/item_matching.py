"""Phase 4b — item matching of supplier document lines to Money articles (MONEY_API §5.5.3, DOCUMENTS_SPEC §2.7).

Read-only: Money is only asked (through the bridge), nothing is written. Cascade per goods line:
1. supplier code in Money (`ArticleSuppliers` of this supplier)            → `supplier_code`
   (#228: from the read cache `money_article_suppliers`; a code the cache does not know is looked up once through the
   bridge and saved — never all codes of a supplier)
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
from app.money.agenda import invalid_branch_ids
from app.money.bridge_client import BridgeClient, BridgeUnavailable
from app.money.cache_sync import save_supplier_codes
from app.money.models import MoneyArticleSupplier
from app.money.schemas import Article, SupplierCode
from app.purchasing import delivery_note, org_settings
from app.purchasing.models import DocumentLine, SupplierDocument, SupplierItemMapping
from app.purchasing.numbers import normalize_code
from app.purchasing.supplier import find_supplier
from app.purchasing.variants import variants_of

log = structlog.get_logger()

PRICE_DIFF_PCT = Decimal("10")  # SETTINGS 14 default (org setting `purchasing.price_diff_pct`)
USER_METHODS = ("user", "non_stock")
MATCH_CHECKS = ("DL-B4", "DL-B11", "DL-W1", "DL-W6", "DL-W8")
MAIN_CARD = "needs_review"  # #233 line status: the cascade hit a main card with variants — a person picks a variant
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


def _candidate(a: Article, kind: str | None = None) -> dict[str, Any]:
    return {
        "article_id": str(a.id),
        "code": a.code,
        "catalog": a.catalog,
        "name": a.name,
        "unit": a.unit,
        "kind": kind or ("variant" if a.parent_id else "article"),
    }


def article_snapshot(a: Article, kind: str | None = None) -> dict[str, Any]:
    """What W6h shows of the Money article (name / catalog / EAN / main unit) — read at matching time. `kind`
    (#233): article | main | variant; a variant's name is shown in italics."""
    return {
        "code": a.code,
        "catalog": a.catalog,
        "name": a.name,
        "ean": a.ean,
        "unit": a.unit,
        "kind": kind or ("variant" if a.parent_id else "article"),
    }


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


def line_checks(
    doc: SupplierDocument,
    lines: list[DocumentLine],
    branch_warehouse: str | None,
    price_pct: Decimal = PRICE_DIFF_PCT,
) -> list[dict[str, Any]]:
    """DL-B4 / DL-W1 / DL-W6 / DL-W8 from the stored matching state (also re-run after every user decision)."""
    out: list[dict[str, Any]] = []
    goods = [ln for ln in lines if not ln.is_fee]
    unmatched = [ln.line_no for ln in goods if ln.line_status == "unmatched"]
    if unmatched:
        out.append(check("DL-B4", "blocking", n=len(unmatched), lines=unmatched))
    for ln in goods:
        if ln.line_status == MAIN_CARD:  # DL-B11 (#233): goods are never received on a main card with variants
            out.append(check("DL-B11", "blocking", n=ln.line_no))
    for ln in goods:
        last = (ln.raw or {}).get("_last_price")
        if ln.match_method == "supplier_code" and last is not None and ln.unit_price is not None:
            pct = price_diff_pct(ln.unit_price, Decimal(str(last)))
            if pct is not None and abs(pct) > price_pct:
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
    if branch is None or "money_warehouse_id" in await invalid_branch_ids(db, branch.id):
        return None  # #212: not in the current Money agenda → behaves as „not set“
    return branch.money_warehouse_id


async def target_warehouse(db: AsyncSession, doc: SupplierDocument) -> str | None:
    """Settings 14 „Sklad podľa dodávateľa“ wins over the branch warehouse (11e); DL-W8 then warns (D18)."""
    conf = await org_settings.load(db)
    if doc.supplier_money_id:
        for rule in conf.warehouse_rules:
            if rule.supplier_money_id == doc.supplier_money_id:
                return str(rule.warehouse_id)
    return await _branch_warehouse(db, doc)


async def refresh_checks(db: AsyncSession, doc: SupplierDocument, lines: list[DocumentLine]) -> None:
    """Replace the matching checks in `doc.validation` and recompute the review status."""
    if doc.supplier_money_id is None and doc.supplier_ico:
        # pilot 2026-11-25: the supplier may have been added to Money (or the cache synced) after the extraction
        company = await find_supplier(db, doc.supplier_ico)
        if company is not None:
            doc.supplier_money_id = company.money_id
            log.info("purchasing.supplier_resolved", document_id=str(doc.id))
    keep = [
        c
        for c in (doc.validation or [])
        if (c["id"] not in MATCH_CHECKS or (c["id"] == "DL-B4" and c["params"].get("reason") == "no_lines"))
        and not c["params"].get("koncept")
        and c["id"] != "DL-B2"  # koncept_checks decides it from `supplier_money_id` (no duplicate row in Kontrola)
    ]
    conf = await org_settings.load(db)
    checks = keep + line_checks(doc, lines, await _branch_warehouse(db, doc), conf.price_diff_pct)
    # 4c (#247): branch values + template (DL-B1 / B5 / B6) — shown before „Vytvoriť v Money“, re-run at approval
    branch = await db.get(Branch, doc.branch_id) if doc.branch_id else None
    invalid = await invalid_branch_ids(db, branch.id) if branch else set()
    checks += delivery_note.mark(
        delivery_note.koncept_checks(doc, lines, branch, delivery_note.branch_values(branch, invalid))
    )
    doc.validation = checks
    if doc.status in ("needs_review", "missing_data"):
        doc.status = "missing_data" if any(c["level"] == "blocking" for c in checks) else "needs_review"


async def load_lines(db: AsyncSession, doc: SupplierDocument) -> list[DocumentLine]:
    return list(
        await db.scalars(select(DocumentLine).where(DocumentLine.document_id == doc.id).order_by(DocumentLine.line_no))
    )


def needs_matching(lines: list[DocumentLine]) -> bool:
    return any(not ln.is_fee and ln.match_method is None for ln in lines)


_UNSAFE = frozenset("~#|()")


async def cached_supplier_codes(db: AsyncSession, supplier_id: uuid.UUID, norms: set[str]) -> dict[str, SupplierCode]:
    """#228: the supplier's codes from the read cache `money_article_suppliers`, only for the codes on the document
    (one SELECT by `supplier_id` + `code_norm`)."""
    if not norms:
        return {}
    rows = await db.scalars(
        select(MoneyArticleSupplier)
        .where(
            MoneyArticleSupplier.supplier_id == supplier_id,
            MoneyArticleSupplier.code_norm.in_(norms),
            MoneyArticleSupplier.active.is_(True),
        )
        .order_by(MoneyArticleSupplier.code_norm, MoneyArticleSupplier.id)
    )
    out: dict[str, SupplierCode] = {}
    for r in rows:
        out.setdefault(
            r.code_norm,
            SupplierCode(
                id=r.id,
                article_id=r.article_id,
                supplier_id=r.supplier_id,
                code=r.code,
                name=r.name,
                last_price=r.last_price,
                unit=r.unit,
                article_unit=r.article_unit,
                article_unit_qty=r.article_unit_qty,
            ),
        )
    return out


async def supplier_codes_for(
    db: AsyncSession, bridge: BridgeClient, supplier_id: uuid.UUID, lines: list[DocumentLine]
) -> dict[str, SupplierCode]:
    """#228: cache first; a code the cache does not know (new in Money, or the first sync has not run yet) is looked
    up once through the bridge exactly as written on the document and saved into the cache. Never „load all codes“."""
    todo = [ln for ln in lines if not ln.is_fee and ln.match_method not in USER_METHODS and ln.supplier_code]
    norms = {n for n in (normalize_code(ln.supplier_code) for ln in todo) if n}
    codes = await cached_supplier_codes(db, supplier_id, norms)
    tried: set[str] = set()
    now = datetime.now(UTC)
    for ln in todo:
        raw = (ln.supplier_code or "").strip()
        norm = normalize_code(raw)
        if not norm or norm in codes or norm in tried or any(c in _UNSAFE for c in raw) or len(raw) > 60:
            continue
        tried.add(norm)
        found = await bridge.lookup_supplier_code(supplier_id, raw)
        if found:
            await save_supplier_codes(db, found, now)
            for sc in found:
                key = normalize_code(sc.code)
                if key:
                    codes.setdefault(key, sc)
    return codes


async def match_document(db: AsyncSession, bridge: BridgeClient, doc: SupplierDocument) -> bool:
    """Run the cascade for every goods line not decided by a person. False = Money unavailable (nothing changed)."""
    lines = await load_lines(db, doc)
    warehouse = await target_warehouse(db, doc)
    learned: dict[str, SupplierItemMapping] = {}
    try:
        codes: dict[str, SupplierCode] = {}
        if doc.supplier_money_id:
            codes = await supplier_codes_for(db, bridge, doc.supplier_money_id, lines)
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
        articles: dict[uuid.UUID, Article | None] = {}
        for r in results.values():
            if r.article_id and r.article_id not in articles:
                articles[r.article_id] = await bridge.article(r.article_id)
        # #233: a hit on a main card with variants never matches — the line waits for a person, its variants offered
        mains = [a.id for a in articles.values() if a is not None and a.parent_id is None]
        variants = await variants_of(bridge, mains)
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
        found = articles.get(res.article_id) if res.article_id else None
        raw["_article"] = article_snapshot(found) if found else None
        if found is not None and variants.get(found.id):
            ln.line_status, ln.warehouse_id = MAIN_CARD, None
            ln.candidates = [_candidate(v, "variant") for v in variants[found.id][:30]]
            raw["_article"] = article_snapshot(found, "main")
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
    warehouse_id: uuid.UUID | None = None,
) -> None:
    """A person picks the article → the line is decided and (optionally) the mapping is learned for this supplier."""
    line.article_id, line.match_method, line.unit_factor, line.line_status = article.id, "user", factor, "matched"
    line.warehouse_id = _uuid(await target_warehouse(db, doc))
    line.candidates = []
    line.raw = {**(line.raw or {}), "_article": article_snapshot(article), "_last_price": None}
    if warehouse_id is not None:
        line.warehouse_id = warehouse_id
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
    line.raw = {**(line.raw or {}), "_article": None, "_last_price": None}
    await refresh_checks(db, doc, await load_lines(db, doc))
    doc.version += 1


REMATCH_STATUSES = ("needs_review", "missing_data")
REMATCH_LIMIT = 200


async def rematch_after_first_supplier_sync(db: AsyncSession, bridge: BridgeClient) -> int:
    """#228 one-off after the first full sync of the supplier code cache: draft documents with unmatched lines are
    matched again. Lines a person decided (`USER_METHODS`) are never touched (`match_document` skips them).
    The caller commits. Returns the number of documents matched again."""
    with_unmatched = (
        select(DocumentLine.document_id)
        .where(DocumentLine.line_status == "unmatched", DocumentLine.is_fee.is_(False))
        .distinct()
    )
    docs = list(
        await db.scalars(
            select(SupplierDocument)
            .where(
                SupplierDocument.status.in_(REMATCH_STATUSES),
                SupplierDocument.supplier_money_id.is_not(None),
                SupplierDocument.id.in_(with_unmatched),
            )
            .order_by(SupplierDocument.created_at.desc())
            .limit(REMATCH_LIMIT)
        )
    )
    done = 0
    for doc in docs:
        if not await match_document(db, bridge, doc):
            break  # Money down: the rest waits for „Znova spárovať“ on W6h
        done += 1
    log.info("purchasing.rematched_after_supplier_sync", documents=done, candidates=len(docs))
    return done
