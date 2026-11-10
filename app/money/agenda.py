"""#212 Which Money agenda the read cache comes from (TEST / PROD) and the safe switch between them.

- PROD is read-only, decided by the customer (Erik, 2026-11-10): every write is off in the app as well as in the
  bridge (the bridge answers 403 `prod_read_only` on its write router).
- The agenda of the cache lives in `org_settings` (section `money.agenda`), no new table.
- When the bridge reports another agenda than the cache: full resync of companies, persons and codebooks, rows
  missing in the new agenda are deactivated (never deleted), pending Money suggestions are superseded, the branch
  settings and the learned mappings are checked, an audit entry is written and admins get one notification.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AiSuggestion, OrgSettings
from app.auth.models import Branch
from app.core.audit import audit
from app.money.models import EmailCompanyLink, MoneyCodebook, MoneyCompany

log = structlog.get_logger()

SECTION = "money.agenda"
MONEY_SUGGESTIONS = ("invoice_attach",)  # payloads hold Money ids / amounts of the agenda they were made from
BRANCH_FIELDS: tuple[tuple[str, str], ...] = (("money_centre_id", "centres"), ("money_warehouse_id", "warehouses"))


async def _row(db: AsyncSession) -> OrgSettings:
    row = await db.scalar(select(OrgSettings).where(OrgSettings.section == SECTION))
    if row is None:
        row = OrgSettings(section=SECTION, data={})
        db.add(row)
    return row


async def load(db: AsyncSession) -> dict[str, Any]:
    row = await db.scalar(select(OrgSettings).where(OrgSettings.section == SECTION))
    return dict(row.data or {}) if row else {}


async def is_prod(db: AsyncSession) -> bool:
    """The cache (and the bridge it came from) is the PRODUCTION agenda → read-only."""
    return (await load(db)).get("agenda") == "PROD"


async def note_agenda(db: AsyncSession, agenda: str) -> bool:
    """Called with the agenda the bridge reports, before a sync run. True = the agenda changed → the caller runs a
    full resync and then `finish_switch`. The first time ever only records it."""
    row = await _row(db)
    data = dict(row.data or {})
    stored = data.get("agenda")
    if stored == agenda:
        return bool(data.get("resync_pending"))  # an interrupted switch continues with a full run
    now = datetime.now(UTC).isoformat()
    if stored is None:
        row.data = {**data, "agenda": agenda, "since": now}
        return False
    superseded = await db.execute(
        update(AiSuggestion)
        .where(AiSuggestion.status == "pending", AiSuggestion.suggestion_type.in_(MONEY_SUGGESTIONS))
        .values(status="superseded")
    )
    row.data = {
        **data,
        "agenda": agenda,
        "previous": stored,
        "changed_at": now,
        "since": now,
        "resync_pending": True,
        "superseded": int(getattr(superseded, "rowcount", 0) or 0),
        "problems": [],
    }
    log.warning("money.agenda_changed", previous=stored, agenda=agenda)
    return True


async def _codebook_ids(db: AsyncSession, kind: str) -> set[str]:
    rows = await db.execute(
        select(MoneyCodebook.money_id, MoneyCodebook.code).where(
            MoneyCodebook.kind == kind, MoneyCodebook.active.is_(True)
        )
    )
    out: set[str] = set()
    for money_id, code in rows.all():
        out.add(str(money_id).lower())
        if code:
            out.add(str(code).strip().lower())
    return out


async def check_references(db: AsyncSession) -> list[dict[str, Any]]:
    """Money ids saved in Smart Mail that the current cache does not know. Price lists and print-report ids are not in
    the cache — they are not checked here (the next use fails safely: no PDF / no price → existing handling)."""
    problems: list[dict[str, Any]] = []
    codebooks = {kind: await _codebook_ids(db, kind) for _, kind in BRANCH_FIELDS}
    series = await _codebook_ids(db, "numerical-series")
    for branch in await db.scalars(select(Branch).order_by(Branch.name)):
        for field, kind in BRANCH_FIELDS:
            value = (getattr(branch, field) or "").strip().lower()
            if value and codebooks[kind] and value not in codebooks[kind]:
                problems.append({"kind": "branch", "branch_id": str(branch.id), "branch": branch.name, "field": field})
        for key, value in (branch.series_overrides or {}).items():
            text = str(value or "").strip().lower()
            if text and series and text not in series:
                problems.append(
                    {"kind": "branch", "branch_id": str(branch.id), "branch": branch.name, "field": f"series:{key}"}
                )
    active = select(MoneyCompany.money_id).where(MoneyCompany.active.is_(True))
    links = await db.scalar(
        select(func.count()).select_from(EmailCompanyLink).where(EmailCompanyLink.company_money_id.not_in(active))
    )
    if links:
        problems.append({"kind": "email_links", "count": int(links)})
    from app.purchasing.models import SupplierItemMapping

    mappings = await db.scalar(
        select(func.count())
        .select_from(SupplierItemMapping)
        .where(SupplierItemMapping.supplier_money_id.not_in(active))
    )
    if mappings:
        problems.append({"kind": "supplier_mappings", "count": int(mappings)})
    return problems


async def finish_switch(db: AsyncSession, *, deactivated: int) -> None:
    """After a successful full resync: checks, audit and the admin notification (derived from `changed_at`)."""
    row = await _row(db)
    data = dict(row.data or {})
    problems = await check_references(db)
    row.data = {**data, "resync_pending": False, "problems": problems, "resynced_at": datetime.now(UTC).isoformat()}
    audit(
        db,
        "money.agenda_changed",
        object_type="org_settings",
        object_id=SECTION,
        details={
            "from": data.get("previous"),
            "to": data.get("agenda"),
            "deactivated": deactivated,
            "superseded": data.get("superseded", 0),
            "problems": len(problems),
        },
    )


async def invalid_branch_ids(db: AsyncSession, branch_id: uuid.UUID) -> set[str]:
    """Fields of this branch that point to a Money item the current agenda does not have (behave as „not set“)."""
    return {
        str(p.get("field"))
        for p in (await load(db)).get("problems") or []
        if p.get("kind") == "branch" and p.get("branch_id") == str(branch_id)
    }
