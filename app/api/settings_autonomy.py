"""07 Samostatnosť per login (DECISIONS D8) and the read-only 17b overview for admins (#116).

Every login sets its own levels; changing them is a ⚠ change (re-auth + audit before/after). The hard rule — external
send and Money writes at most level 2 — is applied in `app.ai.autonomy`, whatever is submitted or stored.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.ai.autonomy import ACTIONS, HUMAN_APPROVAL_MAX, SECTION, effective_levels, load_levels, save_levels
from app.ai.models import AccountSettings
from app.api.settings import require_admin
from app.auth.deps import DB, Auth
from app.auth.models import Account, Person
from app.auth.reauth import ReauthedSession
from app.core.audit import audit

router = APIRouter(prefix="/api/settings/ai/autonomy", tags=["settings-ai"])
Admin = Annotated[Person, Depends(require_admin)]


class ActionLevel(BaseModel):
    id: str
    level: int
    default: int
    max: int  # the highest level this login may pick (hard actions: 2)
    hard: bool


class AutonomyOut(BaseModel):
    actions: list[ActionLevel]


class AutonomyIn(BaseModel):
    levels: dict[str, int] = Field(max_length=len(ACTIONS))


def _out(levels: dict[str, int]) -> AutonomyOut:
    return AutonomyOut(
        actions=[
            ActionLevel(
                id=a.id,
                level=levels[a.id],
                default=a.default,
                max=min(a.max, HUMAN_APPROVAL_MAX) if a.hard else a.max,
                hard=a.hard,
            )
            for a in ACTIONS
        ]
    )


@router.get("")
async def get_autonomy(ctx: Auth, db: DB) -> AutonomyOut:
    return _out(await load_levels(db, ctx.account.id))


@router.put("")
async def put_autonomy(body: AutonomyIn, ctx: ReauthedSession, db: DB) -> AutonomyOut:
    if ctx.read_only:
        raise HTTPException(status_code=403, detail={"code": "read_only"})
    before = await load_levels(db, ctx.account.id)
    after = await save_levels(db, ctx.account.id, body.levels)
    changed = {k: {"before": before[k], "after": after[k]} for k in after if before[k] != after[k]}
    if changed:
        audit(
            db,
            "ai.autonomy_changed",
            account_id=ctx.account.id,
            person_id=ctx.person.id if ctx.person else None,
            object_type="account",
            object_id=str(ctx.account.id),
            details={"changed": changed},
        )
    await db.commit()
    return _out(after)


class AccountAutonomy(BaseModel):
    account_id: str
    email: str
    kind: str
    levels: dict[str, int]
    customized: bool


@router.get("/overview")
async def autonomy_overview(admin: Admin, db: DB) -> list[AccountAutonomy]:
    """17b: read-only — admins see each login's levels but cannot change them (D8)."""
    accounts = (await db.scalars(select(Account).where(Account.active.is_(True)).order_by(Account.email))).all()
    rows = (await db.scalars(select(AccountSettings).where(AccountSettings.section == SECTION))).all()
    stored = {r.account_id: r.data for r in rows}
    return [
        AccountAutonomy(
            account_id=str(a.id),
            email=a.email,
            kind=a.kind.value,
            levels=effective_levels(stored.get(a.id)),
            customized=a.id in stored,
        )
        for a in accounts
    ]
