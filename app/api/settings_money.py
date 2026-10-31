"""Settings 13a Prepojenie (status card) and 13e Synchronizácia (interval, sync now, history) — Phase 3b, admin only.

13b Tlačové zostavy (report ids per kind and language) comes with 3d. 13c and 13f (write features) stay hidden in
Phase 3 (Erik, #150). The writes switch of 13a and the probe upload come with the milestones that need them.
"""

from __future__ import annotations

import time
import uuid
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
from app.auth.models import Branch, Person
from app.auth.reauth import RecentReauth
from app.core.audit import audit
from app.core.config import Settings
from app.money.activities import (
    SECTION_ACTIVITIES,
    SECTION_WRITES,
    ActivitySettings,
    failed_activities,
    load_activity_settings,
)
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


# ----- 11e Money (pobočka): centre + own print reports, SK only (#174) -----


class CentreOption(BaseModel):
    id: str
    code: str | None
    name: str | None


class BranchMoneyOut(BaseModel):
    id: str
    name: str
    centre_id: str | None
    centre_missing: bool  # the saved centre is no longer in Money's codebook
    reports: dict[str, str]  # {"invoice": "", "proforma": ""}


class BranchMoneyList(BaseModel):
    centres: list[CentreOption]
    branches: list[BranchMoneyOut]


class BranchMoneyIn(BaseModel):
    centre_id: str | None = None
    reports: dict[str, str]


async def _centres(db: DB) -> list[MoneyCodebook]:
    rows = await db.scalars(
        select(MoneyCodebook)
        .where(MoneyCodebook.kind == "centres", MoneyCodebook.active.is_(True))
        .order_by(MoneyCodebook.code)
    )
    return list(rows)


def _branch_money(branch: Branch, known: set[str]) -> BranchMoneyOut:
    centre = (branch.money_centre_id or "").strip().lower() or None
    ids = branch.money_report_ids or {}
    return BranchMoneyOut(
        id=str(branch.id),
        name=branch.name,
        centre_id=centre,
        centre_missing=bool(centre and centre not in known),
        reports={kind: str(ids.get(kind) or "") for kind in REPORT_KINDS},
    )


@router.get("/branches")
async def get_branch_money(admin: Admin, db: DB) -> BranchMoneyList:
    centres = await _centres(db)
    known = {str(c.money_id) for c in centres}
    branches = await db.scalars(select(Branch).order_by(Branch.name))
    return BranchMoneyList(
        centres=[CentreOption(id=str(c.money_id), code=c.code, name=c.name) for c in centres],
        branches=[_branch_money(b, known) for b in branches],
    )


@router.put("/branches/{branch_id}")
async def put_branch_money(
    branch_id: uuid.UUID, body: BranchMoneyIn, admin: Admin, ctx: Auth, db: DB
) -> BranchMoneyOut:
    branch = await db.get(Branch, branch_id)
    if branch is None:
        raise fail(404, "branch_not_found")
    known = {str(c.money_id) for c in await _centres(db)}
    centre = (body.centre_id or "").strip().lower() or None
    if centre is not None and centre not in known:
        raise fail(422, "centre_unknown")  # only centres from Money's own codebook, never a typed GUID
    reports: dict[str, str] = {}
    for kind in REPORT_KINDS:
        value = str(body.reports.get(kind) or "").strip()
        if value and not report_id_valid(value):
            raise fail(422, "report_id_invalid", kind=kind)
        if value:
            reports[kind] = value
    before = {"centre_id": branch.money_centre_id, "reports": dict(branch.money_report_ids or {})}
    branch.money_centre_id = centre
    branch.money_report_ids = reports
    audit(
        db,
        "settings.branch_money",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="branch",
        object_id=str(branch.id),
        details={"before": before, "after": {"centre_id": centre, "reports": reports}},
    )
    await db.commit()
    return _branch_money(branch, known)


@router.get("/branches/{branch_id}/test")
async def test_branch_report(
    branch_id: uuid.UUID,
    admin: Admin,
    db: DB,
    settings: SettingsDep,
    kind: Literal["invoice", "proforma"],
    number: str = Query(min_length=3, max_length=40),
) -> Response:
    """„Vyskúšať PDF“ (11e): the branch report with one invoice of this branch's centre that the admin names."""
    if not settings.feature_money:
        raise fail(409, "money_disabled")
    branch = await db.get(Branch, branch_id)
    if branch is None:
        raise fail(404, "branch_not_found")
    report = str((branch.money_report_ids or {}).get(kind) or "")
    if not report:
        raise fail(409, "report_not_configured")
    async with BridgeClient(settings) as bridge:
        try:
            found = await bridge.search_invoices(number=number.strip())
            invoice = next((i for i in found.items if i.kind == kind), None)
            if invoice is None:
                raise fail(404, "invoice_not_found")
            centre = (branch.money_centre_id or "").strip().lower()
            if not centre or str(invoice.centre_id or "").lower() != centre:
                raise fail(409, "invoice_other_branch")
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


# ----- 13a Zápisy do Money povolené ⚠ + 13d Aktivity (Phase 3f) -----


class WritesOut(BaseModel):
    enabled: bool
    key_configured: bool  # APPROVAL_JWT_PRIVATE_KEY on the VPS


class WritesIn(BaseModel):
    enabled: bool


async def _org_row(db: DB, section: str) -> OrgSettings:
    row = await db.scalar(select(OrgSettings).where(OrgSettings.section == section))
    if row is None:
        row = OrgSettings(section=section, data={})
        db.add(row)
    return row


def _writes_out(conf: ActivitySettings, settings: Settings) -> WritesOut:
    key = settings.approval_jwt_private_key
    return WritesOut(enabled=conf.writes_enabled, key_configured=bool(key and key.get_secret_value().strip()))


@router.get("/writes")
async def get_writes(admin: Admin, db: DB, settings: SettingsDep) -> WritesOut:
    return _writes_out(await load_activity_settings(db), settings)


@router.put("/writes")
async def put_writes(body: WritesIn, ctx: RecentReauth, db: DB, settings: SettingsDep) -> WritesOut:
    """⚠ main switch of all Money writes — re-auth (#54) and audit. Phase 3 runs on the TEST agenda only (the bridge
    refuses `MONEY_BACKEND=api` elsewhere), so the „type OSTRÁ“ confirmation of SETTINGS_SPEC 13a is not needed yet."""
    admin = ctx.person
    assert admin is not None
    if body.enabled and not _writes_out(await load_activity_settings(db), settings).key_configured:
        raise fail(409, "approval_key_missing")
    row = await _org_row(db, SECTION_WRITES)
    before = (row.data or {}).get("enabled") is True
    row.data = {**(row.data or {}), "enabled": body.enabled}
    audit(
        db,
        "settings.money_writes",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="org_settings",
        object_id=SECTION_WRITES,
        details={"before": before, "after": body.enabled},
    )
    await db.commit()
    return _writes_out(await load_activity_settings(db), settings)


class ActivityTypeOut(BaseModel):
    id: str
    code: str | None
    name: str | None


class FailedActivityOut(BaseModel):
    draft_id: str
    at: datetime
    error: str | None
    kind: str | None
    invoices: list[str]


class ActivitiesOut(BaseModel):
    enabled: bool
    type_email: str | None
    type_reminder: str | None
    writes_enabled: bool
    types: list[ActivityTypeOut]
    failed: list[FailedActivityOut]


class ActivitiesIn(BaseModel):
    enabled: bool
    type_email: str | None = None
    type_reminder: str | None = None


async def _activities_out(db: DB) -> ActivitiesOut:
    conf = await load_activity_settings(db)
    types = (
        await db.scalars(
            select(MoneyCodebook)
            .where(MoneyCodebook.kind == "activity-types", MoneyCodebook.active.is_(True))
            .order_by(MoneyCodebook.name)
        )
    ).all()
    failed = await failed_activities(db)
    return ActivitiesOut(
        enabled=conf.enabled,
        type_email=conf.type_email,
        type_reminder=conf.type_reminder,
        writes_enabled=conf.writes_enabled,
        types=[ActivityTypeOut(id=str(t.money_id), code=t.code, name=t.name) for t in types],
        failed=[
            FailedActivityOut(
                draft_id=str(f.object_id),
                at=f.created_at,
                error=(f.details or {}).get("error"),
                kind=(f.details or {}).get("kind"),
                invoices=[str(n) for n in (f.details or {}).get("invoices") or []],
            )
            for f in failed
        ],
    )


@router.get("/activities")
async def get_activities(admin: Admin, db: DB) -> ActivitiesOut:
    return await _activities_out(db)


@router.put("/activities")
async def put_activities(body: ActivitiesIn, admin: Admin, ctx: Auth, db: DB) -> ActivitiesOut:
    known = {
        str(t)
        for t in await db.scalars(
            select(MoneyCodebook.money_id).where(MoneyCodebook.kind == "activity-types", MoneyCodebook.active.is_(True))
        )
    }
    for value in (body.type_email, body.type_reminder):
        if value and value not in known:
            raise fail(422, "activity_type_unknown")  # only types from Money's own codebook, never a guessed GUID
    if body.enabled and not (body.type_email and body.type_reminder):
        raise fail(422, "activity_type_required")
    row = await _org_row(db, SECTION_ACTIVITIES)
    before = dict(row.data or {})
    row.data = {"enabled": body.enabled, "type_email": body.type_email, "type_reminder": body.type_reminder}
    audit(
        db,
        "settings.money_activities",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="org_settings",
        object_id=SECTION_ACTIVITIES,
        details={"before": before, "after": row.data},
    )
    await db.commit()
    return await _activities_out(db)


@router.post("/activities/{draft_id}/retry", status_code=202)
async def retry_activity(
    draft_id: uuid.UUID, admin: Admin, ctx: Auth, db: DB, request: Request, settings: SettingsDep
) -> dict[str, bool]:
    """13d: the admin repeats a failed write by hand (never automatic). The SMID keeps it idempotent."""
    if not settings.feature_money:
        raise fail(409, "money_disabled")
    conf = await load_activity_settings(db)
    if not conf.writes_enabled or not conf.enabled:
        raise fail(409, "writes_disabled")
    redis = request.app.state.redis
    await ArqRedis(connection_pool=redis.connection_pool).enqueue_job(
        "money_activity_job", str(draft_id), _job_id=f"money-activity:{draft_id}:retry:{uuid.uuid4().hex[:8]}"
    )
    audit(
        db,
        "money.activity_retry",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="compose_draft",
        object_id=str(draft_id),
        details={},
    )
    await db.commit()
    return {"queued": True}
