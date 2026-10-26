"""API dependencies: who is calling (account + active person), enforced server-side (CLAUDE.md §9)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Account, Person, Role, Session
from app.auth.persons import is_eligible
from app.auth.sessions import Invalid, InvalidReason, resolve, touch
from app.core.audit import audit, set_actor
from app.core.config import Settings
from app.core.db import get_db
from app.core.middleware import SESSION_COOKIE

DB = Annotated[AsyncSession, Depends(get_db)]


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


def now_utc() -> datetime:
    return datetime.now(UTC)


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@dataclass
class AuthContext:
    session: Session
    account: Account
    person: Person | None

    @property
    def read_only(self) -> bool:
        """No active person → read-only: cannot send, assign or approve (CLAUDE.md §9)."""
        return self.person is None or self.person.role == Role.viewer


def unauthenticated(reason: InvalidReason) -> HTTPException:
    return HTTPException(status_code=401, detail={"code": "unauthenticated", "reason": str(reason)})


async def get_auth(request: Request, db: DB, settings: SettingsDep) -> AuthContext:
    now = now_utc()
    found = await resolve(db, request.cookies.get(SESSION_COOKIE), now=now)
    if isinstance(found, Invalid):
        raise unauthenticated(found.reason)
    if found.mfa_pending:
        raise unauthenticated(InvalidReason.missing)
    account = await db.get(Account, found.account_id)
    if account is None or not account.active:
        raise unauthenticated(InvalidReason.account_disabled)
    person = await db.get(Person, found.active_person_id) if found.active_person_id else None
    if found.active_person_id is not None and (person is None or not await is_eligible(db, account, person.id)):
        # deactivated or removed from the branch while selected: drop the person, the picker opens (PRODUCT_SPEC §2.0)
        audit(
            db,
            "auth.person_unavailable",
            account_id=account.id,
            person_id=found.active_person_id,
            object_type="session",
            object_id=str(found.id),
            ip=client_ip(request),
        )
        found.active_person_id = None
        await db.commit()
        raise HTTPException(status_code=409, detail={"code": "person_inactive"})
    touch(found, settings, now=now)
    await db.commit()
    set_actor(account.id, person.id if person else None)
    return AuthContext(found, account, person)


Auth = Annotated[AuthContext, Depends(get_auth)]


async def get_active_person(ctx: Auth) -> Person:
    """For every action that sends, assigns, approves or writes: needs a chosen person with a role that may act."""
    if ctx.person is None:
        raise HTTPException(status_code=403, detail={"code": "person_required"})
    if ctx.person.role == Role.viewer:
        raise HTTPException(status_code=403, detail={"code": "read_only"})
    return ctx.person


ActivePerson = Annotated[Person, Depends(get_active_person)]
