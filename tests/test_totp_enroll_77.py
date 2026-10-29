"""Issue #77 PR 1: Settings 09 „Dvojstupňové overenie“ — start (QR secret + 10 backup codes shown once), confirm with a
code from the app, disable after a re-auth. Personal accounts only; secrets never in logs or audit."""

from __future__ import annotations

import json
import time
from collections.abc import Callable

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.security_2fa import setup_key
from app.auth import totp
from app.auth.models import Account
from app.core.audit import AuditLog
from tests.conftest import Client, FakeMailServer, make_personal
from tests.test_persons_1b import login_branch, senica

PASSWORD = "Spravne-Heslo-1"
EMAIL = "jana@smartsro.sk"
URL = "/api/settings/security/2fa"


async def _signed_in(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> Account:
    acc = await make_personal(db, email=EMAIL)
    mail_server.passwords[EMAIL] = PASSWORD
    assert (await client.login(EMAIL, PASSWORD)).status_code == 200
    assert (await client.reauth(PASSWORD)).status_code == 200  # `start` needs a fresh re-auth (#79 review)
    return acc


def _now_code(secret: str) -> str:
    return totp.code_at(secret, int(time.time() // totp.STEP_S))


async def _account(db: AsyncSession, acc: Account) -> Account:
    found = await db.get(Account, acc.id, populate_existing=True)
    assert found is not None
    return found


async def test_77_enable_2fa_with_a_code_and_backup_codes(
    client: Client, new_client: Callable[[], Client], db: AsyncSession, mail_server: FakeMailServer, app: FastAPI
) -> None:
    acc = await _signed_in(client, db, mail_server)
    assert (await client.get(URL)).json() == {
        "available": True,
        "enabled": False,
        "required": False,
        "backup_codes_left": 0,
    }
    started = (await client.send_json("POST", f"{URL}/start")).json()
    secret, codes = started["secret"], started["backup_codes"]
    assert len(codes) == 10 and started["otpauth_uri"].startswith("otpauth://totp/Smart%20Mail%3Ajana%40smartsro.sk")
    raw = await app.state.redis.get(setup_key(acc.id))
    assert secret not in raw.decode() and not any(c in raw.decode() for c in codes)  # encrypted + hashed
    assert not (await _account(db, acc)).totp_enabled  # nothing changes before confirm

    wrong = await client.send_json("POST", f"{URL}/confirm", {"code": "000000"})
    assert wrong.status_code == 422 and wrong.json()["detail"]["code"] == "totp_invalid"
    code = _now_code(secret)
    ok = await client.send_json("POST", f"{URL}/confirm", {"code": code})
    assert ok.status_code == 200, ok.text
    saved = await _account(db, acc)
    assert saved.totp_enabled and saved.totp_secret_enc and secret not in saved.totp_secret_enc
    assert len(saved.backup_code_hashes) == 10 and codes[0] not in saved.backup_code_hashes
    assert not await app.state.redis.exists(setup_key(acc.id))

    rows = (await db.execute(select(AuditLog).execution_options(populate_existing=True))).scalars().all()
    assert "auth.totp_enabled" in [r.action for r in rows]
    dump = repr([r.details for r in rows])
    assert secret not in dump and codes[0] not in dump

    # the next login asks for the code; the confirming code is not accepted again (replay)
    async with new_client() as browser:
        assert (await browser.login(EMAIL, PASSWORD)).json()["next"] == "2fa"
        replay = await browser.send_json("POST", "/api/auth/2fa", {"code": code})
        assert replay.status_code == 401
    async with new_client() as browser:
        assert (await browser.login(EMAIL, PASSWORD)).json()["next"] == "2fa"
        backup = await browser.send_json("POST", "/api/auth/2fa", {"code": codes[0]})
        assert backup.status_code == 200, backup.text


async def test_77_start_replaces_an_unconfirmed_setup_and_limits_wrong_codes(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, app: FastAPI
) -> None:
    acc = await _signed_in(client, db, mail_server)
    first = (await client.send_json("POST", f"{URL}/start")).json()["secret"]
    second = (await client.send_json("POST", f"{URL}/start")).json()["secret"]
    assert first != second
    old = await client.send_json("POST", f"{URL}/confirm", {"code": _now_code(first)})
    assert old.status_code == 422  # the replaced secret no longer works

    for _ in range(3):
        assert (await client.send_json("POST", f"{URL}/confirm", {"code": "000000"})).status_code == 422
    gone = await client.send_json("POST", f"{URL}/confirm", {"code": "000000"})
    assert gone.status_code == 409 and gone.json()["detail"]["code"] == "totp_setup_expired"
    assert not await app.state.redis.exists(setup_key(acc.id))
    late = await client.send_json("POST", f"{URL}/confirm", {"code": _now_code(second)})
    assert late.status_code == 409


async def test_77_pending_setup_is_not_json_with_a_clear_secret(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, app: FastAPI
) -> None:
    acc = await _signed_in(client, db, mail_server)
    started = (await client.send_json("POST", f"{URL}/start")).json()
    pending = json.loads(await app.state.redis.get(setup_key(acc.id)))
    assert set(pending) == {"secret_enc", "backup_hashes", "failures", "session_id"}
    assert pending["secret_enc"] != started["secret"]
    assert 0 < await app.state.redis.ttl(setup_key(acc.id)) <= 15 * 60


async def test_77_disable_needs_a_reauth_and_is_refused_when_required(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, app: FastAPI
) -> None:
    acc = await _signed_in(client, db, mail_server)
    secret = (await client.send_json("POST", f"{URL}/start")).json()["secret"]
    assert (await client.send_json("POST", f"{URL}/confirm", {"code": _now_code(secret)})).status_code == 200
    await app.state.redis.flushdb()  # the re-auth of `start` is over
    r = await client.send_json("POST", f"{URL}/disable")
    assert r.status_code == 401 and r.json()["detail"]["code"] == "reauth_required"
    assert (await client.reauth(PASSWORD)).status_code == 200

    saved = await _account(db, acc)
    saved.require_2fa = True
    await db.commit()
    r = await client.send_json("POST", f"{URL}/disable")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "totp_required"

    saved.require_2fa = False
    await db.commit()
    assert (await client.send_json("POST", f"{URL}/disable")).status_code == 200
    off = await _account(db, acc)
    assert not off.totp_enabled and off.totp_secret_enc is None and off.backup_code_hashes == []
    assert "auth.totp_disabled" in [
        r.action for r in (await db.execute(select(AuditLog).execution_options(populate_existing=True))).scalars()
    ]


async def test_77_branch_login_cannot_enable_2fa(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    _, branch_login, _ = await senica(db)
    await login_branch(client, mail_server, branch_login)
    assert (await client.get(URL)).json()["available"] is False
    r = await client.send_json("POST", f"{URL}/start")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "personal_only"


async def test_77_start_needs_a_reauth(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await make_personal(db, email=EMAIL)
    mail_server.passwords[EMAIL] = PASSWORD
    assert (await client.login(EMAIL, PASSWORD)).status_code == 200
    r = await client.send_json("POST", f"{URL}/start")
    assert r.status_code == 401 and r.json()["detail"]["code"] == "reauth_required"
    assert (await client.reauth(PASSWORD)).status_code == 200
    assert (await client.send_json("POST", f"{URL}/start")).status_code == 200


async def test_77_setup_is_bound_to_the_session_that_started_it(
    client: Client, new_client: Callable[[], Client], db: AsyncSession, mail_server: FakeMailServer
) -> None:
    acc = await _signed_in(client, db, mail_server)
    secret = (await client.send_json("POST", f"{URL}/start")).json()["secret"]
    async with new_client() as other_device:
        assert (await other_device.login(EMAIL, PASSWORD)).status_code == 200
        r = await other_device.send_json("POST", f"{URL}/confirm", {"code": _now_code(secret)})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "totp_setup_expired"
    assert not (await _account(db, acc)).totp_enabled
