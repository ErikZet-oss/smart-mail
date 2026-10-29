"""Person picker "Kto ste?" and PersonChip switching (SCREENS_SPEC W1b, W2b, M0; PRODUCT_SPEC §2.0; DECISIONS D9).

GET  /api/auth/persons   people who may work under this login + the person remembered on this device
POST /api/auth/person    one click selects / switches the active person of the session (no PIN, no logout)
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.api.auth import DEVICE_COOKIE, MeOut, PersonOut, me_for, person_out
from app.auth.deps import DB, Auth, AuthContext, client_ip
from app.auth.models import Branch
from app.auth.persons import eligible_persons, remember_person, remembered_person
from app.auth.reauth_store import forget_reauth
from app.core.audit import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])


class PickerOut(BaseModel):
    branch: str | None
    email: str
    persons: list[PersonOut]
    current_person_id: str | None
    last_person_id: str | None
    idle_ask_minutes: int | None


class ChooseIn(BaseModel):
    person_id: uuid.UUID
    remember_device: bool = True


@router.get("/persons")
async def persons(request: Request, ctx: Auth, db: DB) -> PickerOut:
    people = await eligible_persons(db, ctx.account)
    branch = await db.get(Branch, ctx.account.branch_id) if ctx.account.branch_id else None
    last = await remembered_person(db, request.cookies.get(DEVICE_COOKIE), ctx.account.id)
    return PickerOut(
        branch=branch.name if branch else None,
        email=ctx.account.email,
        persons=[person_out(p) for p in people],
        current_person_id=str(ctx.person.id) if ctx.person else None,
        last_person_id=str(last) if last and any(p.id == last for p in people) else None,
        idle_ask_minutes=branch.idle_ask_minutes if branch else None,
    )


@router.post("/person")
async def choose_person(body: ChooseIn, request: Request, ctx: Auth, db: DB) -> MeOut:
    people = await eligible_persons(db, ctx.account)
    person = next((p for p in people if p.id == body.person_id), None)
    if person is None:
        raise HTTPException(status_code=403, detail={"code": "person_not_allowed"})
    previous = ctx.session.active_person_id
    ctx.session.active_person_id = person.id
    device_id = request.cookies.get(DEVICE_COOKIE)
    await remember_person(db, device_id, ctx.account.id, person.id if body.remember_device else None)
    if previous != person.id:
        details: dict[str, object] = {"remember_device": body.remember_device}
        if previous is not None:
            details = {"from_person_id": str(previous), **details}
        audit(
            db,
            "auth.person_switched" if previous is not None else "auth.person_selected",
            account_id=ctx.account.id,
            person_id=person.id,
            object_type="session",
            object_id=str(ctx.session.id),
            ip=client_ip(request),
            details=details,
        )
    await db.commit()
    if previous != person.id:
        # the admin re-auth belongs to the person who typed the password (#54 review)
        await forget_reauth(request.app.state.redis, [ctx.session.id])
    return await me_for(db, AuthContext(ctx.session, ctx.account, person))
