"""Issue #77 PR 2: „Vyžadovať 2FA“ — a personal login with the flag and no TOTP gets a session limited to the 2FA
setup (403 `mfa_setup_required` elsewhere, except `me` and logout); the admin can reset 2FA of another account."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import totp
from app.auth.models import Account, Role, Session
from app.auth.reauth_store import mfa_setup_key
from app.core.audit import AuditLog
from tests.conftest import Client, FakeMailServer, make_personal
from tests.test_persons_1b import senica

PASSWORD = "Spravne-Heslo-1"
EVA = "eva@smartsro.sk"
EVA_PASSWORD = "Evine-Heslo-9"


async def _admin(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> Account:
    acc = await make_personal(db, email="admin@smartsro.sk", role=Role.admin)
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200
    assert (await client.reauth(PASSWORD)).status_code == 200
    return acc


async def _eva(db: AsyncSession, mail_server: FakeMailServer, **account: Any) -> Account:
    eva = await make_personal(db, email=EVA, **account)
    mail_server.passwords[EVA] = EVA_PASSWORD
    return eva


def _code(secret: str) -> str:
    return totp.code_at(secret, int(time.time() // totp.STEP_S))


async def _actions(db: AsyncSession) -> list[AuditLog]:
    return list((await db.execute(select(AuditLog).execution_options(populate_existing=True))).scalars())


async def test_77_admin_sets_require_2fa_for_personal_accounts_only(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    eva = await _eva(db, mail_server)
    _, branch_login, _ = await senica(db)
    r = await client.send_json("PATCH", f"/api/settings/admin/users/{eva.id}", {"require_2fa": True})
    assert r.status_code == 200 and r.json()["require_2fa"] is True and r.json()["totp_enabled"] is False
    row = next(a for a in await _actions(db) if a.action == "settings.user_patched")
    assert (row.details["before"]["require_2fa"], row.details["after"]["require_2fa"]) == (False, True)
    r = await client.send_json("PATCH", f"/api/settings/admin/users/{branch_login.id}", {"require_2fa": True})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "personal_only"


async def test_77_login_without_totp_reaches_only_the_setup(
    new_client: Callable[[], Client], db: AsyncSession, mail_server: FakeMailServer, app: FastAPI
) -> None:
    await _eva(db, mail_server, require_2fa=True)
    async with new_client() as browser:
        login = await browser.login(EVA, EVA_PASSWORD)
        assert login.status_code == 200 and login.json()["next"] == "2fa-setup"
        me = await browser.get("/api/auth/me")
        assert me.status_code == 200 and me.json()["mfa_setup_required"] is True
        for path in ("/api/mail/mailboxes/default/folders", "/api/settings/security/sessions", "/api/auth/persons"):
            r = await browser.get(path)
            assert r.status_code == 403 and r.json()["detail"]["code"] == "mfa_setup_required", path
        assert (await browser.get("/api/settings/security/2fa")).json()["required"] is True

        secret = (await browser.send_json("POST", "/api/settings/security/2fa/start")).json()["secret"]
        assert (
            await browser.send_json("POST", "/api/settings/security/2fa/confirm", {"code": _code(secret)})
        ).status_code == 200
        assert (await browser.get("/api/mail/mailboxes/default/folders")).status_code == 200
        assert (await browser.get("/api/auth/me")).json()["mfa_setup_required"] is False
    session = (await db.execute(select(Session).execution_options(populate_existing=True))).scalars().one()
    assert session.mfa_pending is False and not await app.state.redis.exists(mfa_setup_key(session.id))
    assert "auth.login_mfa_setup_required" in [a.action for a in await _actions(db)]


async def test_77_logout_during_setup_drops_the_flag(
    new_client: Callable[[], Client], db: AsyncSession, mail_server: FakeMailServer, app: FastAPI
) -> None:
    await _eva(db, mail_server, require_2fa=True)
    async with new_client() as browser:
        assert (await browser.login(EVA, EVA_PASSWORD)).json()["next"] == "2fa-setup"
        (session_id,) = (await db.execute(select(Session.id))).scalars()
        assert await app.state.redis.exists(mfa_setup_key(session_id))
        assert (await browser.send_json("POST", "/api/auth/logout")).status_code == 200
    assert not await app.state.redis.exists(mfa_setup_key(session_id))


async def test_77_a_normal_2fa_login_cannot_use_the_setup(
    new_client: Callable[[], Client], db: AsyncSession, mail_server: FakeMailServer
) -> None:
    """A login waiting for its TOTP code is not a setup session: it reaches nothing (401) until the code."""
    eva = await _eva(db, mail_server, require_2fa=True)
    eva.totp_enabled = True
    eva.totp_secret_enc = None
    await db.commit()
    async with new_client() as browser:
        assert (await browser.login(EVA, EVA_PASSWORD)).json()["next"] == "2fa"
        assert (await browser.send_json("POST", "/api/settings/security/2fa/start")).status_code == 401


async def test_77_admin_resets_2fa_and_the_next_login_sets_it_up_again(
    client: Client, new_client: Callable[[], Client], db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    eva = await _eva(db, mail_server, require_2fa=True)
    eva.totp_enabled = True
    eva.backup_code_hashes = ["x" * 64]
    await db.commit()
    async with new_client() as old_browser:
        assert (await old_browser.login(EVA, EVA_PASSWORD)).json()["next"] == "2fa"
        r = await client.send_json("POST", f"/api/settings/admin/users/{eva.id}/reset-2fa")
        assert r.status_code == 200 and r.json()["totp_enabled"] is False, r.text
        assert (await old_browser.get("/api/auth/me")).status_code == 401
    saved = await db.get(Account, eva.id, populate_existing=True)
    assert saved is not None and saved.totp_secret_enc is None and saved.backup_code_hashes == []
    row = next(a for a in await _actions(db) if a.action == "settings.user_2fa_reset")
    assert row.details["before"]["totp_enabled"] is True and row.details["after"]["totp_enabled"] is False
    async with new_client() as browser:
        assert (await browser.login(EVA, EVA_PASSWORD)).json()["next"] == "2fa-setup"


async def test_77_reset_2fa_needs_admin_and_reauth(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    eva = await _eva(db, mail_server)
    assert (await client.login(EVA, EVA_PASSWORD)).status_code == 200
    r = await client.send_json("POST", f"/api/settings/admin/users/{eva.id}/reset-2fa")
    assert r.status_code == 403
