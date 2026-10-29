"""Re-auth for ⚠ admin changes (SETTINGS_SPEC §39, CLAUDE.md §11, #54): the mailbox password again when the last
re-auth of *this session* is older than 15 minutes. Kept in Redis per session (no schema change, Erik's answer on #54);
the key is removed on logout and when the session is revoked."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from redis.asyncio import Redis

from app.auth.deps import Auth, AuthContext
from app.auth.models import Role
from app.auth.reauth_store import REAUTH_TTL_S, forget_reauth, has_recent_reauth, mark_reauth, reauth_key

__all__ = ["REAUTH_TTL_S", "RecentReauth", "forget_reauth", "has_recent_reauth", "mark_reauth", "reauth_key"]


async def require_recent_reauth(request: Request, ctx: Auth) -> AuthContext:
    """401 `reauth_required` unless this very session re-authenticated within REAUTH_TTL_S. The key is per session,
    so another device of the same login cannot reuse it."""
    if ctx.person is None or ctx.person.role != Role.admin:
        # every ⚠ change is an admin change: a non-admin gets the usual 403, not a password prompt
        raise HTTPException(status_code=403, detail={"code": "admin_required"})
    redis: Redis = request.app.state.redis
    if not await has_recent_reauth(redis, ctx.session.id, ctx.account.id):
        raise HTTPException(status_code=401, detail={"code": "reauth_required"})
    return ctx


RecentReauth = Annotated[AuthContext, Depends(require_recent_reauth)]
