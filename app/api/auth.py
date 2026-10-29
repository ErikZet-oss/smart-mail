"""Mailbox login (SCREENS_SPEC W1, W1a, W1c; PRODUCT_SPEC §2.0; CLAUDE.md §11).

POST /api/auth/login   e-mail + password → IMAP LOGIN → session (or a pending 2FA session)
POST /api/auth/2fa     TOTP or backup code for the pending session
POST /api/auth/logout
GET  /api/auth/me      who is signed in (account, active person, read-only flag)
GET  /api/auth/csrf    issues the CSRF cookie for the current session state
"""

from __future__ import annotations

import re
import secrets
import time
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import select

from app.auth import totp
from app.auth.deps import DB, Auth, AuthContext, SettingsDep, client_ip, now_utc
from app.auth.models import Account, Branch, Person, Session
from app.auth.provisioning import provision_account, remember_mailbox_password
from app.auth.ratelimit import LoginRateLimiter
from app.auth.reauth_store import REAUTH_TTL_S, forget_reauth, mark_reauth
from app.auth.security import csrf_token, decrypt, mfa_trust_cookie, mfa_trust_valid
from app.auth.sessions import (
    Invalid,
    RevokeReason,
    automatic_person,
    create_session,
    forget_revoked_reauth,
    resolve,
    revoke,
    revoke_account_sessions,
)
from app.core.audit import audit
from app.core.config import Settings
from app.core.middleware import CSRF_COOKIE, SESSION_COOKIE
from app.mail.imap import ImapAuthenticator, ImapServer, LoginResult, MailAuthenticator
from app.mail.mailboxes import ensure_own_mailbox

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

DEVICE_COOKIE = "sm_device"
MFA_TRUST_COOKIE = "sm_mfa_trust"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def get_authenticator(request: Request) -> MailAuthenticator:
    authenticator: MailAuthenticator | None = getattr(request.app.state, "authenticator", None)
    if authenticator is None:
        authenticator = ImapAuthenticator(ImapServer.from_settings(request.app.state.settings))
        request.app.state.authenticator = authenticator
    return authenticator


def get_limiter(request: Request) -> LoginRateLimiter:
    redis: Redis = request.app.state.redis
    return LoginRateLimiter(redis, request.app.state.settings)


Authenticator = Annotated[MailAuthenticator, Depends(get_authenticator)]
Limiter = Annotated[LoginRateLimiter, Depends(get_limiter)]


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=1024)
    remember: bool = False

    def __repr__(self) -> str:  # never show the password in tracebacks
        return f"LoginIn(email={self.email!r}, remember={self.remember})"


class MfaIn(BaseModel):
    code: str = Field(min_length=6, max_length=16)
    remember_device: bool = False


class PersonOut(BaseModel):
    id: str
    first_name: str
    last_name: str
    full_name: str
    function: str | None
    is_manager: bool
    role: str


def person_out(person: Person) -> PersonOut:
    return PersonOut(
        id=str(person.id),
        first_name=person.first_name,
        last_name=person.last_name,
        full_name=person.full_name,
        function=person.function,
        is_manager=person.is_manager,
        role=str(person.role),
    )


class MeOut(BaseModel):
    account_id: str
    email: str
    kind: str
    branch: str | None
    person: PersonOut | None
    needs_person: bool
    read_only: bool


class LoginOut(BaseModel):
    next: Literal["2fa", "who", "app"]
    me: MeOut | None = None


def fail(status: int, code: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, **extra})


def _set_cookie(
    response: Response, settings: Settings, name: str, value: str, max_age: int | None, http_only: bool
) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=http_only,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def _issue_session_cookies(response: Response, settings: Settings, session: Session, token: str) -> None:
    max_age = int((session.expires_at - session.created_at).total_seconds()) if session.remember else None
    _set_cookie(response, settings, SESSION_COOKIE, token, max_age, http_only=True)
    _set_cookie(response, settings, CSRF_COOKIE, csrf_token(settings, token), max_age, http_only=False)


async def me_for(db: DB, ctx: AuthContext) -> MeOut:
    branch = await db.get(Branch, ctx.account.branch_id) if ctx.account.branch_id else None
    person = ctx.person
    return MeOut(
        account_id=str(ctx.account.id),
        email=ctx.account.email,
        kind=str(ctx.account.kind),
        branch=branch.name if branch else None,
        person=person_out(person) if person else None,
        needs_person=person is None,
        read_only=ctx.read_only,
    )


@router.get("/csrf")
async def csrf(request: Request, response: Response, settings: SettingsDep) -> dict[str, bool]:
    _set_cookie(
        response,
        settings,
        CSRF_COOKIE,
        csrf_token(settings, request.cookies.get(SESSION_COOKIE)),
        None,
        http_only=False,
    )
    return {"ok": True}


@router.post("/login")
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: DB,
    settings: SettingsDep,
    authenticator: Authenticator,
    limiter: Limiter,
) -> LoginOut:
    email = body.email.strip().lower()
    ip = client_ip(request)
    if not EMAIL_RE.match(email):
        raise fail(401, "invalid_credentials")
    if not settings.login_allowed(email):
        # Same opaque error as a wrong password — do not reveal allowlist membership.
        audit(db, "auth.login_failed", ip=ip, details={"email": email, "reason": "not_allowlisted"})
        await db.commit()
        raise fail(401, "invalid_credentials")
    lock = await limiter.check(email, ip)
    if lock.locked:
        known = (await db.execute(select(Account.id).where(Account.email == email))).scalar_one_or_none()
        audit(db, "auth.login_rate_limited", account_id=known, ip=ip, details={"email": email})
        await db.commit()
        raise fail(429, "rate_limited", retry_after=lock.retry_after_s)

    result = await authenticator.verify(email, body.password)
    if result is LoginResult.server_unavailable:
        raise fail(503, "mail_server_unavailable")

    account = (await db.execute(select(Account).where(Account.email == email))).scalar_one_or_none()
    if result is LoginResult.ok and account is None and settings.is_internal_address(email):
        account = await provision_account(db, email, settings)
        person = await db.get(Person, account.person_id)
        audit(
            db,
            "auth.account_created",
            account_id=account.id,
            person_id=account.person_id,
            ip=ip,
            details={"role": str(person.role) if person else None, "source": "first_login"},
        )
    if result is LoginResult.invalid_credentials or account is None or not account.active:
        await limiter.fail(email, ip)
        reason = (
            "bad_password"
            if result is LoginResult.invalid_credentials
            else ("no_account" if account is None else "account_disabled")
        )
        audit(
            db,
            "auth.login_failed",
            account_id=account.id if account else None,
            ip=ip,
            details={"email": email, "reason": reason},
        )
        await db.commit()
        raise fail(401, "invalid_credentials")

    await limiter.success(email)
    now = now_utc()
    password_changed = remember_mailbox_password(account, body.password, settings, now=now)
    if password_changed:
        revoked = await revoke_account_sessions(db, account.id, RevokeReason.password_changed, now=now)
        audit(db, "auth.password_changed", account_id=account.id, ip=ip, details={"sessions_revoked": revoked})
    await ensure_own_mailbox(db, account, settings)

    device_id = request.cookies.get(DEVICE_COOKIE) or secrets.token_urlsafe(16)
    _set_cookie(response, settings, DEVICE_COOKIE, device_id, 400 * 86400, http_only=True)

    needs_mfa = account.totp_enabled and not mfa_trust_valid(
        settings, request.cookies.get(MFA_TRUST_COOKIE), str(account.id)
    )
    person_id = None if needs_mfa else await automatic_person(db, account)
    session, token = await create_session(
        db,
        account,
        settings,
        now=now,
        remember=body.remember,
        mfa_pending=needs_mfa,
        device_id=device_id,
        ip=ip,
        user_agent=request.headers.get("user-agent"),
        active_person_id=person_id,
    )
    _issue_session_cookies(response, settings, session, token)
    if needs_mfa:
        audit(db, "auth.login_mfa_required", account_id=account.id, ip=ip)
        await db.commit()
        if password_changed:
            await forget_revoked_reauth(db, request.app.state.redis, account.id)
        return LoginOut(next="2fa")

    account.last_login_at = now
    audit(
        db,
        "auth.login",
        account_id=account.id,
        person_id=person_id,
        object_type="session",
        object_id=str(session.id),
        ip=ip,
        details={"remember": body.remember},
    )
    await db.commit()
    if password_changed:
        await forget_revoked_reauth(db, request.app.state.redis, account.id)
    person = await db.get(Person, person_id) if person_id else None
    me = await me_for(db, AuthContext(session, account, person))
    return LoginOut(next="app" if person else "who", me=me)


@router.post("/2fa")
async def verify_mfa(
    body: MfaIn,
    request: Request,
    response: Response,
    db: DB,
    settings: SettingsDep,
    limiter: Limiter,
) -> LoginOut:
    now = now_utc()
    ip = client_ip(request)
    found = await resolve(db, request.cookies.get(SESSION_COOKIE), now=now)
    if isinstance(found, Invalid) or not found.mfa_pending:
        raise fail(401, "unauthenticated", reason="missing")
    account = await db.get(Account, found.account_id)
    if account is None or not account.active or not account.totp_secret_enc:
        raise fail(401, "unauthenticated", reason="missing")

    ok = False
    code = body.code.strip()
    if code.replace(" ", "").isdigit():
        step = totp.verify(decrypt(settings, account.totp_secret_enc), code, time.time(), account.totp_last_step)
        if step is not None:
            account.totp_last_step = step
            ok = True
    else:
        remaining = totp.use_backup_code(code, list(account.backup_code_hashes))
        if remaining is not None:
            account.backup_code_hashes = remaining
            ok = True
            audit(db, "auth.backup_code_used", account_id=account.id, ip=ip, details={"left": len(remaining)})

    if not ok:
        found.mfa_failures += 1
        await limiter.fail(account.email, ip)
        left = settings.mfa_max_failures - found.mfa_failures
        audit(db, "auth.mfa_failed", account_id=account.id, ip=ip, details={"attempts_left": max(left, 0)})
        if left <= 0:
            revoke(found, RevokeReason.mfa_failed, now=now)
            await db.commit()
            response.delete_cookie(SESSION_COOKIE, path="/")
            raise fail(401, "mfa_locked")
        await db.commit()
        raise fail(401, "invalid_code", attempts_left=left)

    # rotate the session token after the second factor (no fixation of the pre-2FA cookie)
    revoke(found, RevokeReason.rotated, now=now)
    person_id = await automatic_person(db, account)
    session, token = await create_session(
        db,
        account,
        settings,
        now=now,
        remember=found.remember,
        mfa_pending=False,
        device_id=found.device_id,
        ip=ip,
        user_agent=request.headers.get("user-agent"),
        active_person_id=person_id,
    )
    _issue_session_cookies(response, settings, session, token)
    if body.remember_device:
        _set_cookie(
            response,
            settings,
            MFA_TRUST_COOKIE,
            mfa_trust_cookie(settings, str(account.id)),
            settings.mfa_trust_days * 86400,
            http_only=True,
        )
    await limiter.success(account.email)
    account.last_login_at = now
    audit(
        db,
        "auth.login",
        account_id=account.id,
        person_id=person_id,
        object_type="session",
        object_id=str(session.id),
        ip=ip,
        details={"remember": found.remember, "mfa": True, "remember_device": body.remember_device},
    )
    await db.commit()
    person = await db.get(Person, person_id) if person_id else None
    me = await me_for(db, AuthContext(session, account, person))
    return LoginOut(next="app" if person else "who", me=me)


@router.post("/logout")
async def logout(request: Request, response: Response, db: DB, settings: SettingsDep) -> dict[str, bool]:
    now = now_utc()
    found = await resolve(db, request.cookies.get(SESSION_COOKIE), now=now)
    if not isinstance(found, Invalid):
        revoke(found, RevokeReason.logout, now=now)
        await forget_reauth(request.app.state.redis, [found.id])
        audit(
            db,
            "auth.logout",
            account_id=found.account_id,
            person_id=found.active_person_id,
            object_type="session",
            object_id=str(found.id),
            ip=client_ip(request),
        )
        await db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    _set_cookie(response, settings, CSRF_COOKIE, csrf_token(settings, None), None, http_only=False)
    return {"ok": True}


class ReauthIn(BaseModel):
    password: str = Field(min_length=1, max_length=512)


@router.post("/reauth")
async def reauth(
    body: ReauthIn,
    request: Request,
    ctx: Auth,
    db: DB,
    authenticator: Authenticator,
    limiter: Limiter,
) -> dict[str, int]:
    """Re-auth for ⚠ admin changes (#54): the mailbox password of the signed-in login, checked on the mail server
    like the login. Success only sets the Redis key of this session (nothing in the session is rotated); a wrong
    password never logs out — it counts towards the login rate limit and answers 422 `reauth_failed`."""
    ip = client_ip(request)
    email = ctx.account.email
    lock = await limiter.check(email, ip)
    if lock.locked:
        raise fail(429, "rate_limited", retry_after=lock.retry_after_s)
    result = await authenticator.verify(email, body.password)
    if result is LoginResult.server_unavailable:
        raise fail(503, "mail_server_unavailable")
    ok = result is LoginResult.ok
    if ok:
        await limiter.success(email)
        await mark_reauth(request.app.state.redis, ctx.session.id, ctx.account.id)
    else:
        await limiter.fail(email, ip)
    audit(
        db,
        "auth.reauth",
        account_id=ctx.account.id,
        person_id=ctx.person.id if ctx.person else None,
        object_type="session",
        object_id=str(ctx.session.id),
        ip=ip,
        details={"result": "ok" if ok else "failed"},
    )
    await db.commit()
    if not ok:
        raise fail(422, "reauth_failed")
    return {"valid_s": REAUTH_TTL_S}


@router.get("/me")
async def me(ctx: Auth, db: DB) -> MeOut:
    return await me_for(db, ctx)
