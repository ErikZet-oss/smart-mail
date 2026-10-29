"""Settings 09 Bezpečnosť › Dvojstupňové overenie (#77 PR 1, Figma W12-09 `67:58896`): turn TOTP on with a QR code,
a code from the app and 10 backup codes, and turn it off after a re-auth. Personal accounts only (SETTINGS_SPEC).

The secret and the backup codes never reach logs or the audit log. Until confirmed they live in Redis (secret Fernet-
encrypted, backup codes as hashes) for 15 minutes; `start` replaces an unconfirmed setup."""

from __future__ import annotations

import json
import time
import uuid
from datetime import timedelta
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from app.auth import totp
from app.auth.deps import DB, Auth, AuthContext, SettingsDep, client_ip
from app.auth.models import AccountKind
from app.auth.reauth import ReauthedSession, require_reauthed_session
from app.auth.reauth_store import mfa_setup_key
from app.auth.security import decrypt, encrypt
from app.auth.sessions import remember_days
from app.core.audit import audit

router = APIRouter(prefix="/api/settings/security/2fa", tags=["settings"])

SETUP_TTL_S = 15 * 60
MAX_CONFIRM_FAILURES = 5
ISSUER = "Smart Mail"


def _fail(status: int, code: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code})


def setup_key(account_id: uuid.UUID) -> str:
    return f"smartmail:totp-setup:{account_id}"


def _personal(ctx: AuthContext) -> None:
    if ctx.account.kind != AccountKind.personal:
        raise _fail(403, "personal_only")


@router.get("")
async def status(ctx: Auth) -> dict[str, Any]:
    return {
        "available": ctx.account.kind == AccountKind.personal,
        "enabled": ctx.account.totp_enabled,
        "required": ctx.account.require_2fa,
        "backup_codes_left": len(ctx.account.backup_code_hashes or []),
    }


@router.post("/start")
async def start(request: Request, ctx: Auth, settings: SettingsDep) -> dict[str, Any]:
    """Turning 2FA on is as sensitive as turning it off: an open or stolen session must not bind its own
    authenticator and lock the owner out (#79 review) — so it needs the re-auth of this session too."""
    _personal(ctx)  # a branch login gets 403, not a pointless password prompt
    await require_reauthed_session(request, ctx)
    if ctx.account.totp_enabled:
        raise _fail(409, "totp_already_enabled")
    secret = totp.new_secret()
    codes = totp.new_backup_codes()
    redis: Redis = request.app.state.redis
    pending = {
        "secret_enc": encrypt(settings, secret),
        "backup_hashes": [totp.hash_backup_code(c) for c in codes],
        "failures": 0,
        # bound to the session that started it: another session (device) cannot confirm it
        "session_id": str(ctx.session.id),
    }
    await redis.set(setup_key(ctx.account.id), json.dumps(pending), ex=SETUP_TTL_S)
    label = quote(f"{ISSUER}:{ctx.account.email}")
    uri = f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}&digits={totp.DIGITS}&period={totp.STEP_S}"
    # shown once: the response is the only place the secret and the backup codes appear in clear text
    return {"secret": secret, "otpauth_uri": uri, "backup_codes": codes}


class ConfirmIn(BaseModel):
    code: str = Field(min_length=1, max_length=16)


@router.post("/confirm")
async def confirm(body: ConfirmIn, request: Request, ctx: Auth, db: DB, settings: SettingsDep) -> dict[str, Any]:
    _personal(ctx)
    redis: Redis = request.app.state.redis
    key = setup_key(ctx.account.id)
    raw = await redis.get(key)
    if not raw:
        raise _fail(409, "totp_setup_expired")
    pending = json.loads(raw)
    if pending.get("session_id") != str(ctx.session.id):
        raise _fail(409, "totp_setup_expired")
    secret = decrypt(settings, pending["secret_enc"])
    step = totp.verify(secret, body.code, time.time(), None)  # ±1 time step (clock drift)
    if step is None:
        pending["failures"] = int(pending.get("failures", 0)) + 1
        if pending["failures"] >= MAX_CONFIRM_FAILURES:
            await redis.delete(key)  # start again: no brute force on one pending secret
            raise _fail(409, "totp_setup_expired")
        ttl = await redis.ttl(key)
        await redis.set(key, json.dumps(pending), ex=max(int(ttl), 1))
        raise _fail(422, "totp_invalid")
    account = ctx.account
    account.totp_secret_enc = pending["secret_enc"]
    account.totp_enabled = True
    account.totp_last_step = step  # the confirming code cannot be used again at the next login
    account.backup_code_hashes = list(pending["backup_hashes"])
    audit(
        db,
        "auth.totp_enabled",
        account_id=account.id,
        person_id=ctx.person.id if ctx.person else None,
        object_type="account",
        object_id=str(account.id),
        ip=client_ip(request),
    )
    if ctx.mfa_setup:
        # „Vyžadovať 2FA“ is fulfilled: the limited login session becomes a normal one (#77)
        ctx.session.mfa_pending = False
        lifetime = (
            timedelta(days=await remember_days(db, account, settings))
            if ctx.session.remember
            else timedelta(hours=settings.session_idle_hours)
        )
        ctx.session.expires_at = ctx.session.created_at + lifetime
    await db.commit()
    await redis.delete(key)
    if ctx.mfa_setup:
        await redis.delete(mfa_setup_key(ctx.session.id))
    return {"enabled": True}


@router.post("/disable")
async def disable(request: Request, ctx: ReauthedSession, db: DB) -> dict[str, Any]:
    """„Vypnúť“ needs a fresh re-auth of this session (SETTINGS_SPEC 09). Not while an admin requires 2FA."""
    _personal(ctx)
    account = ctx.account
    if account.require_2fa:
        raise _fail(409, "totp_required")
    account.totp_secret_enc = None
    account.totp_enabled = False
    account.totp_last_step = None
    account.backup_code_hashes = []
    audit(
        db,
        "auth.totp_disabled",
        account_id=account.id,
        person_id=ctx.person.id if ctx.person else None,
        object_type="account",
        object_id=str(account.id),
        ip=client_ip(request),
    )
    await db.commit()
    return {"enabled": False}
