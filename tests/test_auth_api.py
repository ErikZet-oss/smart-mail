"""Mailbox login end-to-end over the API (SCREENS_SPEC W1, W1a, W1c; PRODUCT_SPEC §2.0; CLAUDE.md §9, §11)."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import totp
from app.auth.models import Account, Branch, Role, Session
from app.auth.security import encrypt
from app.core import maintenance
from app.core.audit import AuditLog, audit
from app.core.config import Settings
from tests.conftest import Client, FakeMailServer, make_branch, make_personal

EMAIL, PASSWORD = "jana@smartsro.sk", "Spravne-Heslo-1"


async def actions(db: AsyncSession) -> list[str]:
    rows = await db.execute(select(AuditLog.action).order_by(AuditLog.created_at, AuditLog.id))
    return list(rows.scalars())


async def sessions_of(db: AsyncSession, account: Account) -> list[Session]:
    account_id = account.id
    db.expire_all()
    rows = await db.execute(select(Session).where(Session.account_id == account_id).order_by(Session.created_at))
    return list(rows.scalars())


# --- W1 login ------------------------------------------------------------------------------------------------------
async def test_w1_login_personal_account_goes_to_app(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    acc = await make_personal(db, EMAIL)
    mail_server.passwords[EMAIL] = PASSWORD
    r = await client.login(" Jana@SmartSro.sk ", PASSWORD)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["next"] == "app"
    assert body["me"]["email"] == EMAIL and body["me"]["person"]["full_name"] == "Jana Testová"
    assert body["me"]["read_only"] is False
    session_cookie = r.cookies["sm_session"]
    assert session_cookie and "sm_csrf" in client.cookies
    assert "httponly" in r.headers["set-cookie"].lower()

    me = await client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["account_id"] == str(acc.id)
    assert "auth.login" in await actions(db)
    [s] = await sessions_of(db, acc)
    assert s.token_hash != session_cookie  # only the hash is stored
    assert not s.remember and s.expires_at - s.created_at == timedelta(hours=12)


async def test_w1_wrong_password_generic_error_and_audit_without_password(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await make_personal(db, EMAIL)
    mail_server.passwords[EMAIL] = PASSWORD
    r = await client.login(EMAIL, "zle-heslo")
    assert r.status_code == 401 and r.json()["detail"]["code"] == "invalid_credentials"
    entry = (await db.execute(select(AuditLog).where(AuditLog.action == "auth.login_failed"))).scalar_one()
    assert entry.details == {"email": EMAIL, "reason": "bad_password"}
    assert "zle-heslo" not in str(entry.details)


async def test_w1_d25_valid_imap_login_of_external_address_is_rejected(
    client: Client, mail_server: FakeMailServer
) -> None:
    mail_server.passwords["cudzi@example.com"] = PASSWORD
    r = await client.login("cudzi@example.com", PASSWORD)
    assert r.status_code == 401 and r.json()["detail"]["code"] == "invalid_credentials"


async def test_w1_disabled_account_rejected(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await make_personal(db, EMAIL, active=False)
    mail_server.passwords[EMAIL] = PASSWORD
    r = await client.login(EMAIL, PASSWORD)
    assert r.status_code == 401 and r.json()["detail"]["code"] == "invalid_credentials"


async def test_w1_mail_server_down_is_503_and_not_counted(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await make_personal(db, EMAIL)
    mail_server.passwords[EMAIL] = PASSWORD
    mail_server.down = True
    for _ in range(7):
        r = await client.login(EMAIL, PASSWORD)
        assert r.status_code == 503 and r.json()["detail"]["code"] == "mail_server_unavailable"
    mail_server.down = False
    assert (await client.login(EMAIL, PASSWORD)).status_code == 200


async def test_w1_rate_limit_after_5_failures_locks_for_5_minutes(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await make_personal(db, EMAIL)
    mail_server.passwords[EMAIL] = PASSWORD
    for _ in range(5):
        assert (await client.login(EMAIL, "zle")).status_code == 401
    calls = mail_server.calls
    r = await client.login(EMAIL, PASSWORD)  # even the right password is refused while locked
    assert r.status_code == 429
    detail = r.json()["detail"]
    assert detail["code"] == "rate_limited" and 0 < detail["retry_after"] <= 300
    assert mail_server.calls == calls  # IMAP is not even asked while locked
    assert "auth.login_rate_limited" in await actions(db)


async def test_w1_rate_limit_per_ip_across_accounts(client: Client, app: FastAPI, mail_server: FakeMailServer) -> None:
    app.state.settings.login_ip_max_failures = 3
    for i in range(3):
        assert (await client.login(f"u{i}@smartsro.sk", "zle")).status_code == 401
    assert (await client.login("iny@smartsro.sk", "zle")).status_code == 429


async def test_w1_success_clears_account_counter(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await make_personal(db, EMAIL)
    mail_server.passwords[EMAIL] = PASSWORD
    for _ in range(4):
        await client.login(EMAIL, "zle")
    assert (await client.login(EMAIL, PASSWORD)).status_code == 200
    for _ in range(4):
        assert (await client.login(EMAIL, "zle")).status_code == 401


async def test_w1_remember_me_30_days_capped_by_branch(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    _, acc = await make_branch(db, "Senica", people=1, remember_days=7)
    mail_server.passwords[acc.email] = PASSWORD
    r = await client.login(acc.email, PASSWORD, remember=True)
    assert r.status_code == 200
    [s] = await sessions_of(db, acc)
    assert s.remember and s.expires_at - s.created_at == timedelta(days=7)
    assert "max-age=604800" in r.headers["set-cookie"].lower()


async def test_w1_branch_mailbox_with_several_people_needs_picker_and_is_read_only(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    _, acc = await make_branch(db, "Nitra", people=2)
    mail_server.passwords[acc.email] = PASSWORD
    body = (await client.login(acc.email, PASSWORD)).json()
    assert body["next"] == "who"
    assert body["me"]["needs_person"] is True and body["me"]["read_only"] is True
    assert body["me"]["branch"] == "Nitra"


async def test_w1_branch_mailbox_with_one_person_selects_it(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    _, acc = await make_branch(db, "Trenčín", people=1)
    mail_server.passwords[acc.email] = PASSWORD
    body = (await client.login(acc.email, PASSWORD)).json()
    assert body["next"] == "app" and body["me"]["person"]["first_name"] == "Osoba0"


async def test_viewer_role_is_read_only(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await make_personal(db, EMAIL, role=Role.viewer)
    mail_server.passwords[EMAIL] = PASSWORD
    assert (await client.login(EMAIL, PASSWORD)).json()["me"]["read_only"] is True


# --- W1c: password changed / expired ------------------------------------------------------------------------------
async def test_w1c_new_password_logs_out_other_sessions(
    client: Client,
    new_client: Callable[[], Client],
    db: AsyncSession,
    mail_server: FakeMailServer,
) -> None:
    acc = await make_personal(db, EMAIL)
    mail_server.passwords[EMAIL] = PASSWORD
    assert (await client.login(EMAIL, PASSWORD)).status_code == 200

    mail_server.passwords[EMAIL] = "Nove-Heslo-2"  # changed in Roundcube / on the server
    async with new_client() as other:
        assert (await other.login(EMAIL, "Nove-Heslo-2")).status_code == 200
        assert (await other.get("/api/auth/me")).status_code == 200

    r = await client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["detail"] == {"code": "unauthenticated", "reason": "password_changed"}
    assert "auth.password_changed" in await actions(db)
    old, new = await sessions_of(db, acc)
    assert old.revoked_reason == "password_changed" and new.revoked_at is None


async def test_w1c_same_password_keeps_other_sessions(
    client: Client, new_client: Callable[[], Client], db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await make_personal(db, EMAIL)
    mail_server.passwords[EMAIL] = PASSWORD
    await client.login(EMAIL, PASSWORD)
    async with new_client() as other:
        await other.login(EMAIL, PASSWORD)
    assert (await client.get("/api/auth/me")).status_code == 200


async def test_w1c_idle_session_expires(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    acc = await make_personal(db, EMAIL)
    mail_server.passwords[EMAIL] = PASSWORD
    await client.login(EMAIL, PASSWORD)
    past = datetime.now(UTC) - timedelta(seconds=1)
    await db.execute(update(Session).where(Session.account_id == acc.id).values(expires_at=past))
    await db.commit()
    r = await client.get("/api/auth/me")
    assert r.status_code == 401 and r.json()["detail"]["reason"] == "expired"


async def test_activity_slides_the_idle_timeout(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    acc = await make_personal(db, EMAIL)
    mail_server.passwords[EMAIL] = PASSWORD
    await client.login(EMAIL, PASSWORD)
    earlier = datetime.now(UTC) - timedelta(hours=11)
    await db.execute(
        update(Session)
        .where(Session.account_id == acc.id)
        .values(last_seen_at=earlier, expires_at=earlier + timedelta(hours=12))
    )
    await db.commit()
    assert (await client.get("/api/auth/me")).status_code == 200
    [s] = await sessions_of(db, acc)
    assert s.expires_at > datetime.now(UTC) + timedelta(hours=11, minutes=59)


async def test_no_cookie_is_401_missing(client: Client) -> None:
    r = await client.get("/api/auth/me")
    assert r.status_code == 401 and r.json()["detail"]["reason"] == "missing"


async def test_logout_revokes_session(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    acc = await make_personal(db, EMAIL)
    mail_server.passwords[EMAIL] = PASSWORD
    await client.login(EMAIL, PASSWORD)
    token = client.cookies["sm_session"]
    assert (await client.send_json("POST", "/api/auth/logout")).status_code == 200
    client.cookies.set("sm_session", token)  # a copied cookie must not work any more
    r = await client.get("/api/auth/me")
    assert r.status_code == 401 and r.json()["detail"]["reason"] == "revoked"
    [s] = await sessions_of(db, acc)
    assert s.revoked_reason == "logout"
    assert "auth.logout" in await actions(db)


async def test_disabling_account_ends_access(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    acc = await make_personal(db, EMAIL)
    mail_server.passwords[EMAIL] = PASSWORD
    await client.login(EMAIL, PASSWORD)
    await db.execute(update(Account).where(Account.id == acc.id).values(active=False))
    await db.commit()
    r = await client.get("/api/auth/me")
    assert r.status_code == 401 and r.json()["detail"]["reason"] == "account_disabled"


# --- CSRF ----------------------------------------------------------------------------------------------------------
async def test_csrf_required_for_unsafe_methods(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await make_personal(db, EMAIL)
    mail_server.passwords[EMAIL] = PASSWORD
    r = await client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "csrf"
    await client.csrf()
    forged = await client.post(
        "/api/auth/login", json={"email": EMAIL, "password": PASSWORD}, headers={"X-CSRF-Token": "a.b"}
    )
    assert forged.status_code == 403
    non_ascii = await client.post("/api/auth/logout", headers={"X-CSRF-Token": "ľ.ť".encode()})
    assert non_ascii.status_code == 403  # regression: compare_digest on non-ASCII str raised → 500


async def test_csrf_token_rotates_with_session(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await make_personal(db, EMAIL)
    mail_server.passwords[EMAIL] = PASSWORD
    await client.csrf()
    pre_login = client.cookies["sm_csrf"]
    await client.login(EMAIL, PASSWORD)
    assert client.cookies["sm_csrf"] != pre_login
    client.cookies.set("sm_csrf", pre_login)
    r = await client.post("/api/auth/logout", headers={"X-CSRF-Token": pre_login})
    assert r.status_code == 403  # the anonymous token is not valid for the signed-in session


# --- W1a two-factor ------------------------------------------------------------------------------------------------
async def _with_totp(db: AsyncSession, settings: Settings) -> tuple[Account, str, list[str]]:
    secret = totp.new_secret()
    codes = totp.new_backup_codes()
    acc = await make_personal(
        db,
        EMAIL,
        totp_enabled=True,
        totp_secret_enc=encrypt(settings, secret),
        backup_code_hashes=[totp.hash_backup_code(c) for c in codes],
    )
    return acc, secret, codes


async def test_w1a_totp_required_then_session_rotated(
    client: Client, db: AsyncSession, settings: Settings, mail_server: FakeMailServer
) -> None:
    acc, secret, _ = await _with_totp(db, settings)
    mail_server.passwords[EMAIL] = PASSWORD
    r = await client.login(EMAIL, PASSWORD)
    assert r.json() == {"next": "2fa", "me": None}
    pending = client.cookies["sm_session"]
    assert (await client.get("/api/auth/me")).status_code == 401  # pending session is not signed in

    code = totp.code_at(secret, int(time.time() // 30))
    r = await client.send_json("POST", "/api/auth/2fa", {"code": code})
    assert r.status_code == 200 and r.json()["next"] == "app"
    assert client.cookies["sm_session"] != pending
    assert (await client.get("/api/auth/me")).status_code == 200
    old, new = await sessions_of(db, acc)
    assert old.revoked_reason == "rotated" and not new.mfa_pending

    # replay of the same code on a fresh login is refused
    async with Client(transport=client._transport, base_url="http://test") as other:
        await other.login(EMAIL, PASSWORD)
        replay = await other.send_json("POST", "/api/auth/2fa", {"code": code})
        assert replay.status_code == 401 and replay.json()["detail"]["code"] == "invalid_code"


async def test_w1a_wrong_code_counts_down_then_locks(
    client: Client, db: AsyncSession, settings: Settings, mail_server: FakeMailServer
) -> None:
    await _with_totp(db, settings)
    mail_server.passwords[EMAIL] = PASSWORD
    await client.login(EMAIL, PASSWORD)
    lefts = []
    for _ in range(4):
        r = await client.send_json("POST", "/api/auth/2fa", {"code": "000000"})
        assert r.status_code == 401 and r.json()["detail"]["code"] == "invalid_code"
        lefts.append(r.json()["detail"]["attempts_left"])
    assert lefts == [4, 3, 2, 1]
    r = await client.send_json("POST", "/api/auth/2fa", {"code": "000000"})
    assert r.json()["detail"]["code"] == "mfa_locked"
    r = await client.send_json("POST", "/api/auth/2fa", {"code": "000000"})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "unauthenticated"
    # the 2FA failures count towards the login lock as well
    assert (await client.login(EMAIL, PASSWORD)).status_code == 429


async def test_w1a_backup_code_single_use(
    client: Client, db: AsyncSession, settings: Settings, mail_server: FakeMailServer
) -> None:
    acc, _, codes = await _with_totp(db, settings)
    mail_server.passwords[EMAIL] = PASSWORD
    await client.login(EMAIL, PASSWORD)
    assert (await client.send_json("POST", "/api/auth/2fa", {"code": codes[0]})).status_code == 200
    acc_id = acc.id
    db.expire_all()
    refreshed = await db.get(Account, acc_id)
    assert refreshed is not None and len(refreshed.backup_code_hashes) == 9
    await client.send_json("POST", "/api/auth/logout")
    await client.login(EMAIL, PASSWORD)
    assert (await client.send_json("POST", "/api/auth/2fa", {"code": codes[0]})).status_code == 401


async def test_w1a_remember_device_skips_totp_next_time(
    client: Client, db: AsyncSession, settings: Settings, mail_server: FakeMailServer
) -> None:
    _, secret, _ = await _with_totp(db, settings)
    mail_server.passwords[EMAIL] = PASSWORD
    await client.login(EMAIL, PASSWORD)
    code = totp.code_at(secret, int(time.time() // 30))
    r = await client.send_json("POST", "/api/auth/2fa", {"code": code, "remember_device": True})
    assert "sm_mfa_trust" in r.cookies
    await client.send_json("POST", "/api/auth/logout")
    assert (await client.login(EMAIL, PASSWORD)).json()["next"] == "app"


# --- W17 maintenance, W16c unexpected error, security headers -----------------------------------------------------
async def test_w17_maintenance_blocks_api_but_not_status(client: Client, app: FastAPI) -> None:
    until = datetime(2026, 10, 27, 8, 0, tzinfo=UTC)
    await maintenance.start(app.state.redis, until)
    r = await client.get("/api/auth/me")
    assert r.status_code == 503 and r.json()["detail"] == {"code": "maintenance", "until": until.isoformat()}
    status = await client.get("/api/system/maintenance")
    assert status.status_code == 200 and status.json() == {"active": True, "until": until.isoformat()}
    assert (await client.get("/healthz")).status_code == 200
    await maintenance.stop(app.state.redis)
    assert (await client.get("/api/system/maintenance")).json() == {"active": False, "until": None}


async def test_w16c_unexpected_error_returns_reference(client: Client, app: FastAPI) -> None:
    @app.get("/api/test-boom")
    async def boom() -> None:
        raise RuntimeError("secret detail")

    r = await client.get("/api/test-boom")
    assert r.status_code == 500
    detail = r.json()["detail"]
    assert detail["code"] == "server_error" and len(detail["ref"]) == 8
    assert "secret detail" not in r.text


async def test_security_headers_on_api(client: Client) -> None:
    r = await client.get("/api/auth/me")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"
    assert "default-src 'none'" in r.headers["content-security-policy"]


# --- audit log is append-only -------------------------------------------------------------------------------------
@pytest.mark.parametrize("sql", ["UPDATE audit_log SET action = 'x'", "DELETE FROM audit_log", "TRUNCATE audit_log"])
async def test_audit_log_append_only(db: AsyncSession, sql: str) -> None:
    audit(db, "test.entry")
    await db.commit()
    with pytest.raises(DBAPIError, match="append-only"):
        await db.execute(text(sql))
    await db.rollback()
    assert await actions(db) == ["test.entry"]


@pytest.mark.parametrize("key", ["password", "Code", "token", "secret", "body"])
async def test_audit_rejects_secret_detail_keys(db: AsyncSession, key: str) -> None:
    with pytest.raises(ValueError):
        audit(db, "test.entry", details={key: "x"})


async def test_branch_remember_days_constraint(db: AsyncSession) -> None:
    db.add(Branch(name="Zlá", remember_days=14))
    with pytest.raises(DBAPIError):
        await db.commit()
