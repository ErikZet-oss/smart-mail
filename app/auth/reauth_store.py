"""Redis keys of the admin re-auth (#54), per session. No imports from the auth dependencies (sessions uses it)."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from redis.asyncio import Redis

REAUTH_TTL_S = 15 * 60


def reauth_key(session_id: uuid.UUID) -> str:
    return f"smartmail:reauth:{session_id}"


def _owner(account_id: uuid.UUID, person_id: uuid.UUID | None) -> str:
    # the re-auth belongs to the person who typed the password: a branch login shares one session (PersonChip, D9)
    return f"{account_id}:{person_id or '-'}"


async def mark_reauth(redis: Redis, session_id: uuid.UUID, account_id: uuid.UUID, person_id: uuid.UUID | None) -> None:
    await redis.set(reauth_key(session_id), _owner(account_id, person_id), ex=REAUTH_TTL_S)


async def has_recent_reauth(
    redis: Redis, session_id: uuid.UUID, account_id: uuid.UUID, person_id: uuid.UUID | None
) -> bool:
    raw: object = await redis.get(reauth_key(session_id))
    value = raw.decode() if isinstance(raw, bytes) else raw
    return bool(value == _owner(account_id, person_id))


async def forget_reauth(redis: Redis | None, session_ids: Iterable[uuid.UUID]) -> None:
    keys = [reauth_key(s) for s in session_ids]
    if redis is not None and keys:
        await redis.delete(*keys)


# --- „Vyžadovať 2FA“ (#77 PR 2): a session that must first set up TOTP --------------------------------------------
MFA_SETUP_TTL_S = 10 * 60  # as long as an mfa_pending session lives


def mfa_setup_key(session_id: uuid.UUID) -> str:
    return f"smartmail:mfa-setup:{session_id}"


async def mark_mfa_setup(redis: Redis, session_id: uuid.UUID) -> None:
    await redis.set(mfa_setup_key(session_id), "1", ex=MFA_SETUP_TTL_S)


async def needs_mfa_setup(redis: Redis, session_id: uuid.UUID) -> bool:
    return bool(await redis.exists(mfa_setup_key(session_id)))


async def forget_session_keys(redis: Redis | None, session_ids: Iterable[uuid.UUID]) -> None:
    """Logout / revoke: the re-auth and the 2FA-setup flag of these sessions go away."""
    ids = list(session_ids)
    keys = [reauth_key(s) for s in ids] + [mfa_setup_key(s) for s in ids]
    if redis is not None and keys:
        await redis.delete(*keys)
