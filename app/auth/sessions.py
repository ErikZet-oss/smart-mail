"""Server-side sessions (CLAUDE.md §11): 12 h of inactivity, or "Zostať prihlásený" up to 30 days.

States: mfa_pending → active → revoked (logout, password_changed, mfa_failed, admin) or expired.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Account, AccountKind, Branch, Session
from app.auth.persons import eligible_persons
from app.auth.reauth_store import forget_reauth
from app.auth.security import new_token, sha256_hex
from app.core.config import Settings

TOUCH_EVERY = timedelta(minutes=1)


class RevokeReason(enum.StrEnum):
    logout = "logout"
    password_changed = "password_changed"  # noqa: S105 - revoke reason, not a secret
    mfa_failed = "mfa_failed"
    rotated = "rotated"
    account_changed = "account_changed"  # admin converted the login (e.g. to a branch login, #33)
    admin_logout = "admin_logout"  # „Odhlásiť zo všetkých zariadení“ in Settings 10 (#55)


class InvalidReason(enum.StrEnum):
    missing = "missing"
    expired = "expired"
    password_changed = "password_changed"  # noqa: S105 - revoke reason, not a secret
    revoked = "revoked"
    account_disabled = "account_disabled"


@dataclass(frozen=True)
class Invalid:
    reason: InvalidReason


async def remember_days(db: AsyncSession, account: Account, settings: Settings) -> int:
    days = settings.session_remember_days
    if account.kind == AccountKind.branch and account.branch_id is not None:
        branch = await db.get(Branch, account.branch_id)
        if branch is not None:
            days = min(days, branch.remember_days)
    return days


async def create_session(
    db: AsyncSession,
    account: Account,
    settings: Settings,
    *,
    now: datetime,
    remember: bool,
    mfa_pending: bool,
    device_id: str | None,
    ip: str | None,
    user_agent: str | None,
    active_person_id: uuid.UUID | None = None,
) -> tuple[Session, str]:
    token = new_token()
    if remember:
        expires = now + timedelta(days=await remember_days(db, account, settings))
    else:
        expires = now + timedelta(hours=settings.session_idle_hours)
    if mfa_pending:
        expires = min(expires, now + timedelta(minutes=10))
    session = Session(
        account_id=account.id,
        token_hash=sha256_hex(token),
        active_person_id=active_person_id,
        device_id=device_id,
        remember=remember,
        mfa_pending=mfa_pending,
        mfa_failures=0,
        ip=ip,
        user_agent=(user_agent or "")[:400] or None,
        created_at=now,
        last_seen_at=now,
        expires_at=expires,
    )
    db.add(session)
    await db.flush()
    return session, token


async def resolve(db: AsyncSession, token: str | None, *, now: datetime) -> Session | Invalid:
    if not token:
        return Invalid(InvalidReason.missing)
    session = (await db.execute(select(Session).where(Session.token_hash == sha256_hex(token)))).scalar_one_or_none()
    if session is None:
        return Invalid(InvalidReason.missing)
    if session.revoked_at is not None:
        if session.revoked_reason == RevokeReason.password_changed:
            return Invalid(InvalidReason.password_changed)
        return Invalid(InvalidReason.revoked)
    if session.expires_at <= now:
        return Invalid(InvalidReason.expired)
    return session


def touch(session: Session, settings: Settings, *, now: datetime) -> None:
    """Sliding idle timeout for normal sessions; remembered sessions keep their fixed end."""
    if now - session.last_seen_at < TOUCH_EVERY:
        return
    session.last_seen_at = now
    if not session.remember and not session.mfa_pending:
        session.expires_at = now + timedelta(hours=settings.session_idle_hours)


def revoke(session: Session, reason: RevokeReason, *, now: datetime) -> None:
    session.revoked_at = now
    session.revoked_reason = reason


async def revoke_account_sessions(
    db: AsyncSession,
    account_id: uuid.UUID,
    reason: RevokeReason,
    *,
    now: datetime,
    except_session_id: uuid.UUID | None = None,
) -> int:
    """Log the account out everywhere. Called on a detected password change (login with a new password, and the
    background IMAP login of the mailbox sync failing with an authentication error)."""
    stmt = (
        update(Session)
        .where(Session.account_id == account_id, Session.revoked_at.is_(None), Session.expires_at > now)
        .values(revoked_at=now, revoked_reason=str(reason))
    )
    if except_session_id is not None:
        stmt = stmt.where(Session.id != except_session_id)
    result = await db.execute(stmt)
    return int(getattr(result, "rowcount", 0) or 0)


async def forget_revoked_reauth(db: AsyncSession, redis: Redis, account_id: uuid.UUID) -> None:
    """Drop the admin re-auth (#54) of every revoked session of the login. Call it after the commit that revoked
    them, so a rolled-back change (e.g. 409 `last_admin`) never leaves a live session without its re-auth."""
    ids = (
        await db.execute(select(Session.id).where(Session.account_id == account_id, Session.revoked_at.is_not(None)))
    ).scalars()
    await forget_reauth(redis, list(ids))


async def automatic_person(db: AsyncSession, account: Account) -> uuid.UUID | None:
    """Personal account → its person. Branch mailbox with exactly one active person → that person.
    Two or more → None: the person picker "Kto ste?" decides (PRODUCT_SPEC §2.0)."""
    people = await eligible_persons(db, account)
    if account.kind == AccountKind.personal:
        return people[0].id if people else None
    return people[0].id if len(people) == 1 else None
