"""Redis keys of the admin re-auth (#54), per session. No imports from the auth dependencies (sessions uses it)."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from redis.asyncio import Redis

REAUTH_TTL_S = 15 * 60


def reauth_key(session_id: uuid.UUID) -> str:
    return f"smartmail:reauth:{session_id}"


async def mark_reauth(redis: Redis, session_id: uuid.UUID, account_id: uuid.UUID) -> None:
    await redis.set(reauth_key(session_id), str(account_id), ex=REAUTH_TTL_S)


async def has_recent_reauth(redis: Redis, session_id: uuid.UUID, account_id: uuid.UUID) -> bool:
    raw: object = await redis.get(reauth_key(session_id))
    value = raw.decode() if isinstance(raw, bytes) else raw
    return bool(value == str(account_id))


async def forget_reauth(redis: Redis | None, session_ids: Iterable[uuid.UUID]) -> None:
    keys = [reauth_key(s) for s in session_ids]
    if redis is not None and keys:
        await redis.delete(*keys)
