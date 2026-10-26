"""API dependencies: who is calling (account + active person), enforced server-side (CLAUDE.md §9)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Account, Person, Role, Session
from app.auth.sessions import Invalid, InvalidReason, resolve, touch
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
    touch(found, settings, now=now)
    await db.commit()
    return AuthContext(found, account, person)


Auth = Annotated[AuthContext, Depends(get_auth)]
