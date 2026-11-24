"""Money read cache sync (MONEY_API §4): companies by `ChangeFrom` delta, nightly full; persons and codebooks full.

- The cursor moves only after a run without errors, to the moment that run *started* minus a safety margin, so a
  record changed during the run is fetched again next time (upserts are idempotent).
- A full run marks rows that Money no longer returns as inactive (never deletes — other rows may point at them).
- Logs carry counts and error codes only, never Money payloads (CLAUDE.md §0.1).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import structlog
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.money.bridge_client import BridgeClient, BridgeUnavailable
from app.money.models import (
    MoneyArticle,
    MoneyArticleSupplier,
    MoneyCodebook,
    MoneyCompany,
    MoneyPerson,
    MoneySyncState,
)
from app.money.schemas import CODEBOOKS, Company, Person, SupplierCode
from app.purchasing.numbers import normalize_code

log = structlog.get_logger(__name__)

Entity = Literal["companies", "persons", "codebooks", "article_suppliers", "articles"]
ENTITIES: tuple[Entity, ...] = ("companies", "persons", "codebooks", "article_suppliers", "articles")
# `ChangeFrom` delta + nightly full; `articles` = the W6h Katalóg cache (Erik 2026-11-24)
DELTA_ENTITIES: frozenset[str] = frozenset({"companies", "article_suppliers", "articles"})
PAGE = 200
MAX_PAGES = 500  # 100 000 rows — a runaway paging loop stops here
CURSOR_MARGIN = timedelta(minutes=2)
UPSERT_BATCH = 1000
HISTORY_KEEP = 20
INTERVALS = (5, 15, 30, 60)
DEFAULT_INTERVAL = 15


@dataclass
class SyncResult:
    entity: Entity
    full: bool
    changed: int = 0
    deactivated: int = 0
    status: str = "ok"
    error: str | None = None
    duration_ms: int = 0


def company_emails(company: Company) -> list[str]:
    found = {company.email.strip().lower()} if company.email and "@" in company.email else set()
    found |= {c.value.strip().lower() for c in company.connections if "@" in c.value}
    return sorted(e for e in found if e)


def _company_row(c: Company, now: datetime) -> dict[str, Any]:
    return {
        "id": uuid.uuid4(),
        "money_id": c.id,
        "code": c.code,
        "name": c.name[:255],
        "ico": (c.ico or "").replace(" ", "")[:20] or None,
        "dic": c.dic,
        "icdph": c.icdph,
        "email": c.email,
        "discount_pct": c.discount_pct,
        "due_days": c.due_days,
        "connections": [conn.model_dump() for conn in c.connections],
        "emails": company_emails(c),
        "active": True,
        "synced_at": now,
    }


def _person_row(p: Person, now: datetime) -> dict[str, Any]:
    return {
        "id": uuid.uuid4(),
        "money_id": p.id,
        "company_money_id": p.company_id,
        "first_name": p.first_name,
        "last_name": p.last_name,
        "name": p.name,
        "function": p.function,
        "email": p.email.strip().lower() if p.email else None,
        "phone": p.phone,
        "active": True,
        "synced_at": now,
    }


def supplier_code_row(c: SupplierCode, now: datetime) -> dict[str, Any] | None:
    norm = normalize_code(c.code)
    if c.id is None or not norm:
        return None
    return {
        "id": c.id,
        "article_id": c.article_id,
        "supplier_id": c.supplier_id,
        "code": c.code[:120],
        "code_norm": norm[:120],
        "name": (c.name or None) and c.name[:255],
        "last_price": c.last_price,
        "unit": c.unit,
        "article_unit": c.article_unit,
        "article_unit_qty": c.article_unit_qty,
        "active": True,
        "synced_at": now,
    }


async def save_supplier_codes(db: AsyncSession, codes: list[SupplierCode], now: datetime) -> int:
    """Upsert `ArticleSuppliers` rows into the read cache (also used by the matching fallback, #228)."""
    rows = [r for r in (supplier_code_row(c, now) for c in codes) if r is not None]
    unique = list({r["id"]: r for r in rows}.values())  # one row per id in one statement
    for i in range(0, len(unique), UPSERT_BATCH):  # PostgreSQL allows at most 32 767 parameters per statement
        await _upsert(db, MoneyArticleSupplier.__table__, unique[i : i + UPSERT_BATCH], ["id"])
    return len(unique)


async def _sync_article_suppliers(
    db: AsyncSession, client: BridgeClient, since: datetime | None, now: datetime
) -> tuple[int, set[uuid.UUID]]:
    """Tens of thousands of rows on the first full run: page by page, one upsert per page, counts only in logs."""
    seen: set[uuid.UUID] = set()
    start, changed = 0, 0
    for _ in range(MAX_PAGES):
        page = await client.all_supplier_codes(since, start, PAGE)
        changed += await save_supplier_codes(db, page.items, now)
        seen |= {c.id for c in page.items if c.id is not None}
        if page.next_from is None:
            break
        start = page.next_from
    return changed, seen


async def _sync_articles(
    db: AsyncSession, client: BridgeClient, since: datetime | None, now: datetime
) -> tuple[int, set[uuid.UUID]]:
    """W6h Katalóg: the whole catalog on the first full run (tens of thousands of rows), page by page."""
    from app.purchasing.catalog import article_row

    seen: set[uuid.UUID] = set()
    start, changed = 0, 0
    for _ in range(MAX_PAGES):
        page = await client.all_articles(since, start, PAGE)
        rows = list({r["id"]: r for r in (article_row(a, now) for a in page.items)}.values())
        for i in range(0, len(rows), UPSERT_BATCH):
            await _upsert(db, MoneyArticle.__table__, rows[i : i + UPSERT_BATCH], ["id"])
        changed += len(rows)
        seen |= {a.id for a in page.items}
        if page.next_from is None:
            break
        start = page.next_from
    return changed, seen


async def _upsert(db: AsyncSession, table: Any, rows: list[dict[str, Any]], key: list[str]) -> None:
    if not rows:
        return
    stmt = insert(table).values(rows)
    updates: dict[str, Any] = {c: stmt.excluded[c] for c in rows[0] if c not in ("id", *key)}
    updates["updated_at"] = datetime.now(UTC)
    await db.execute(stmt.on_conflict_do_update(index_elements=key, set_=updates))


async def _state(db: AsyncSession, entity: str) -> MoneySyncState:
    row = await db.scalar(select(MoneySyncState).where(MoneySyncState.entity == entity).with_for_update())
    if row is None:
        row = MoneySyncState(entity=entity, history=[])
        db.add(row)
        await db.flush()
    return row


async def _sync_companies(
    db: AsyncSession, client: BridgeClient, since: datetime | None, now: datetime
) -> tuple[int, set[uuid.UUID]]:
    seen: set[uuid.UUID] = set()
    start, changed = 0, 0
    for _ in range(MAX_PAGES):
        page = await client.companies(since, start, PAGE)
        await _upsert(db, MoneyCompany.__table__, [_company_row(c, now) for c in page.items], ["money_id"])
        seen |= {c.id for c in page.items}
        changed += len(page.items)
        if page.next_from is None:
            break
        start = page.next_from
    return changed, seen


async def _sync_persons(db: AsyncSession, client: BridgeClient, now: datetime) -> tuple[int, set[uuid.UUID]]:
    seen: set[uuid.UUID] = set()
    start, changed = 0, 0
    for _ in range(MAX_PAGES):
        page = await client.persons(None, start, PAGE)
        await _upsert(db, MoneyPerson.__table__, [_person_row(p, now) for p in page.items], ["money_id"])
        seen |= {p.id for p in page.items}
        changed += len(page.items)
        if page.next_from is None:
            break
        start = page.next_from
    return changed, seen


async def _sync_codebooks(db: AsyncSession, client: BridgeClient, now: datetime) -> tuple[int, int]:
    changed, deactivated = 0, 0
    for kind in CODEBOOKS:
        seen: set[uuid.UUID] = set()
        start = 0
        for _ in range(MAX_PAGES):
            page = await client.codebook(kind, start, PAGE)
            rows = [
                {
                    "id": uuid.uuid4(),
                    "kind": kind,
                    "money_id": i.id,
                    "code": i.code,
                    "name": i.name,
                    "active": True,
                    "synced_at": now,
                }
                for i in page.items
            ]
            await _upsert(db, MoneyCodebook.__table__, rows, ["kind", "money_id"])
            seen |= {i.id for i in page.items}
            changed += len(rows)
            if page.next_from is None:
                break
            start = page.next_from
        result = await db.execute(
            update(MoneyCodebook)
            .where(
                MoneyCodebook.kind == kind,
                MoneyCodebook.active.is_(True),
                MoneyCodebook.money_id.not_in(seen or {uuid.UUID(int=0)}),
            )
            .values(active=False)
        )
        deactivated += int(getattr(result, "rowcount", 0) or 0)
    return changed, deactivated


async def _deactivate(db: AsyncSession, model: type[MoneyCompany] | type[MoneyPerson], seen: set[uuid.UUID]) -> int:
    result = await db.execute(
        update(model)
        .where(model.active.is_(True), model.money_id.not_in(seen or {uuid.UUID(int=0)}))
        .values(active=False)
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def _deactivate_supplier_codes(
    db: AsyncSession, seen: set[uuid.UUID], table: str = "money_article_suppliers"
) -> int:
    """Rows a full run did not see (deleted in Money). The set can be large: a temporary table, not a long IN list."""
    from sqlalchemy import text

    await db.execute(text("CREATE TEMP TABLE IF NOT EXISTS _seen_as (id uuid PRIMARY KEY) ON COMMIT DROP"))
    await db.execute(text("TRUNCATE _seen_as"))
    ids = list(seen)
    for i in range(0, len(ids), 5000):
        await db.execute(
            text("INSERT INTO _seen_as (id) SELECT unnest(CAST(:ids AS uuid[])) ON CONFLICT DO NOTHING"),
            {"ids": ids[i : i + 5000]},
        )
    result = await db.execute(
        text(
            f"UPDATE {table} SET active = false, updated_at = now() "  # noqa: S608 — a fixed table name
            "WHERE active AND id NOT IN (SELECT id FROM _seen_as)"
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def sync_entity(db: AsyncSession, client: BridgeClient, entity: Entity, *, full: bool = False) -> SyncResult:
    """One entity, one transaction (the caller commits). Persons and codebooks are always full ([PROBE] delta)."""
    started = time.monotonic()
    now = datetime.now(UTC)
    state = await _state(db, entity)
    full = full or entity not in DELTA_ENTITIES or state.cursor is None
    result = SyncResult(entity=entity, full=full)
    try:
        async with db.begin_nested():
            if entity == "companies":
                changed, seen = await _sync_companies(db, client, None if full else state.cursor, now)
                result.changed = changed
                if full:
                    result.deactivated = await _deactivate(db, MoneyCompany, seen)
            elif entity == "article_suppliers":
                changed, seen = await _sync_article_suppliers(db, client, None if full else state.cursor, now)
                result.changed = changed
                if full:
                    result.deactivated = await _deactivate_supplier_codes(db, seen)
            elif entity == "articles":
                changed, seen = await _sync_articles(db, client, None if full else state.cursor, now)
                result.changed = changed
                if full:
                    result.deactivated = await _deactivate_supplier_codes(db, seen, "money_articles")
            elif entity == "persons":
                changed, seen = await _sync_persons(db, client, now)
                result.changed = changed
                result.deactivated = await _deactivate(db, MoneyPerson, seen)
            else:
                result.changed, result.deactivated = await _sync_codebooks(db, client, now)
    except BridgeUnavailable as exc:
        result.status, result.error = "error", exc.code[:60]
    result.duration_ms = int((time.monotonic() - started) * 1000)

    state.last_run_at = now
    state.last_status = result.status
    state.last_error = result.error
    if result.status == "ok":
        state.cursor = now - CURSOR_MARGIN
        if full:
            state.last_full_at = now
    run = {
        "at": now.isoformat(),
        "full": full,
        "status": result.status,
        "changed": result.changed,
        "deactivated": result.deactivated,
        "error": result.error,
        "duration_ms": result.duration_ms,
    }
    state.history = [run, *(state.history or [])][:HISTORY_KEEP]
    log.info("money_sync", entity=entity, full=full, status=result.status, changed=result.changed, error=result.error)
    return result


def due(state: MoneySyncState | None, interval_min: int, now: datetime) -> bool:
    if state is None or state.last_run_at is None:
        return True
    return now - state.last_run_at >= timedelta(minutes=interval_min) - timedelta(seconds=30)


def needs_nightly_full(state: MoneySyncState | None, now: datetime) -> bool:
    if state is None or state.last_full_at is None:
        return True
    return now - state.last_full_at >= timedelta(hours=23)
