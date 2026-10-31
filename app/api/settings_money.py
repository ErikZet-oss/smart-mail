"""Settings 13a Prepojenie (status card) and 13e Synchronizácia (interval, sync now, history) — Phase 3b, admin only.

13b Tlačové zostavy (report ids per kind and language) comes with 3d. 13c and 13f (write features) stay hidden in
Phase 3 (Erik, #150). The writes switch of 13a and the probe upload come with the milestones that need them.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Annotated, Any, Literal

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select

from app.ai.models import OrgSettings
from app.api.mail import fail
from app.api.settings import require_admin
from app.auth.deps import DB, Auth, SettingsDep
from app.auth.models import Person
from app.core.audit import audit
from app.money.bridge_client import BridgeClient, BridgeUnavailable
from app.money.cache_sync import ENTITIES
from app.money.invoice_attach import (
    REPORT_KINDS,
    REPORT_LANGS,
    SECTION_REPORTS,
    load_reports,
    pick_report,
    report_id_valid,
)
from app.money.jobs import LOCK_KEY, SECTION_SYNC, sync_interval
from app.money.models import MoneyCodebook, MoneyCompany, MoneyPerson, MoneySyncState

router = APIRouter(prefix="/api/settings/money", tags=["settings-money"])
Admin = Annotated[Person, Depends(require_admin)]
HISTORY_ROWS = 20


class EntityState(BaseModel):
    entity: str
    last_run_at: datetime | None
    last_full_at: datetime | None
    status: str | None
    error: str | None
    rows: int


class StatusOut(BaseModel):
    enabled: bool  # FEATURE_MONEY
    reachable: bool
    error: str | None
    backend: str | None
    agenda: str | None
    bridge_version: str | None
    money_version: str | None
    latency_ms: int | None
    writes_enabled: bool
    entities: list[EntityState]


class SyncRun(BaseModel):
    entity: str
    at: str
    full: bool
    status: str
    changed: int
    deactivated: int
    error: str | None
    duration_ms: int


class SyncOut(BaseModel):
    interval_min: int
    running: bool
    history: list[SyncRun]


class SyncIn(BaseModel):
    interval_min: Literal[5, 15, 30, 60]


async def _entities(db: DB) -> list[EntityState]:
    states = {s.entity: s for s in (await db.scalars(select(MoneySyncState))).all()}
    counts = {
        "companies": await db.scalar(select(func.count()).select_from(MoneyCompany).where(MoneyCompany.active)),
        "persons": await db.scalar(select(func.count()).select_from(MoneyPerson).where(MoneyPerson.active)),
        "codebooks": await db.scalar(select(func.count()).select_from(MoneyCodebook).where(MoneyCodebook.active)),
    }
    out = []
    for entity in ENTITIES:
        s = states.get(entity)
        out.append(
            EntityState(
                entity=entity,
                last_run_at=s.last_run_at if s else None,
                last_full_at=s.last_full_at if s else None,
                status=s.last_status if s else None,
                error=s.last_error if s else None,
                rows=int(counts[entity] or 0),
            )
        )
    return out


@router.get("/status")
async def money_status(admin: Admin, db: DB, settings: SettingsDep) -> StatusOut:
    """13a status card; „Otestovať“ calls it again. Never raises when Money or the bridge is down."""
    out: dict[str, Any] = {
        "enabled": settings.feature_money,
        "reachable": False,
        "error": None,
        "backend": None,
        "agenda": None,
        "bridge_version": None,
        "money_version": None,
        "latency_ms": None,
        "writes_enabled": False,
        "entities": await _entities(db),
    }
    async with BridgeClient(settings) as bridge:
        try:
            health = await bridge.health()
            out.update(
                backend=health.backend,
                agenda=health.agenda,
                bridge_version=health.version,
                writes_enabled=health.writes_enabled,
            )
            started = time.monotonic()
            ready = await bridge.ready()
            out.update(
                reachable=True,
                money_version=ready.get("money_version"),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        except BridgeUnavailable as exc:
            out["error"] = exc.code
    return StatusOut(**out)


async def _sync_out(db: DB, request: Request) -> SyncOut:
    runs: list[SyncRun] = []
    for s in (await db.scalars(select(MoneySyncState))).all():
        runs += [SyncRun(entity=s.entity, **r) for r in (s.history or []) if isinstance(r, dict)]
    runs.sort(key=lambda r: r.at, reverse=True)
    running = bool(await request.app.state.redis.exists(LOCK_KEY))
    return SyncOut(interval_min=await sync_interval(db), running=running, history=runs[:HISTORY_ROWS])


@router.get("/sync")
async def get_sync(admin: Admin, db: DB, request: Request) -> SyncOut:
    return await _sync_out(db, request)


@router.put("/sync")
async def put_sync(body: SyncIn, admin: Admin, ctx: Auth, db: DB, request: Request) -> SyncOut:
    row = await db.scalar(select(OrgSettings).where(OrgSettings.section == SECTION_SYNC))
    before = (row.data if row else {}).get("interval_min")
    if row is None:
        row = OrgSettings(section=SECTION_SYNC, data={})
        db.add(row)
    row.data = {**(row.data or {}), "interval_min": body.interval_min}
    audit(
        db,
        "settings.money_sync_interval",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="org_settings",
        object_id=SECTION_SYNC,
        details={"before": before, "after": body.interval_min},
    )
    await db.commit()
    return await _sync_out(db, request)


@router.post("/sync-now", status_code=202)
async def sync_now(admin: Admin, ctx: Auth, db: DB, request: Request, settings: SettingsDep) -> dict[str, bool]:
    if not settings.feature_money:
        raise fail(409, "money_disabled")
    redis = request.app.state.redis
    if await redis.exists(LOCK_KEY):
        raise fail(409, "money_sync_running")
    await ArqRedis(connection_pool=redis.connection_pool).enqueue_job("money_sync", True, _job_id="money-sync-now")
    audit(
        db, "money.sync_requested", account_id=ctx.account.id, person_id=admin.id, object_type="money", object_id="sync"
    )
    await db.commit()
    return {"queued": True}


# ----- 13b Tlačové zostavy (Phase 3d) -----


class ReportsIO(BaseModel):
    invoice: dict[str, str]
    proforma: dict[str, str]


@router.get("/reports")
async def get_reports(admin: Admin, db: DB) -> ReportsIO:
    return ReportsIO(**await load_reports(db))


@router.put("/reports")
async def put_reports(body: ReportsIO, admin: Admin, ctx: Auth, db: DB) -> ReportsIO:
    clean: dict[str, dict[str, str]] = {}
    for kind in REPORT_KINDS:
        values = getattr(body, kind)
        clean[kind] = {}
        for lang in REPORT_LANGS:
            value = str(values.get(lang) or "").strip()
            if value and not report_id_valid(value):
                raise fail(422, "report_id_invalid", kind=kind, lang=lang)
            clean[kind][lang] = value
    row = await db.scalar(select(OrgSettings).where(OrgSettings.section == SECTION_REPORTS))
    if row is None:
        row = OrgSettings(section=SECTION_REPORTS, data={})
        db.add(row)
    before = dict(row.data or {})
    row.data = clean
    audit(
        db,
        "settings.money_reports",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="org_settings",
        object_id=SECTION_REPORTS,
        details={"before": before, "after": clean},
    )
    await db.commit()
    return ReportsIO(**clean)


@router.get("/reports/test")
async def test_report(
    admin: Admin,
    db: DB,
    settings: SettingsDep,
    kind: Literal["invoice", "proforma"],
    lang: Literal["sk", "en", "de"],
    number: str = Query(min_length=3, max_length=40),
) -> Response:
    """„Vyskúšať PDF“: the saved report for this kind and language with one invoice the admin names."""
    if not settings.feature_money:
        raise fail(409, "money_disabled")
    report = pick_report(await load_reports(db), kind, lang)
    if report is None:
        raise fail(409, "report_not_configured")
    async with BridgeClient(settings) as bridge:
        try:
            found = await bridge.search_invoices(number=number.strip())
            invoice = next((i for i in found.items if i.kind == kind), None)
            if invoice is None:
                raise fail(404, "invoice_not_found")
            pdf = await bridge.invoice_pdf(kind, invoice.id, report)
        except BridgeUnavailable as exc:
            raise fail(503, "money_unavailable", reason=exc.code) from None
    if not pdf:
        raise fail(404, "pdf_missing")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Cache-Control": "no-store", "Content-Disposition": "inline; filename=test.pdf"},
    )
