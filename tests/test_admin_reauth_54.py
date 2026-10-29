"""Issue #54: ⚠ admin changes need a re-auth with the mailbox password of *this* session within 15 minutes
(SETTINGS_SPEC §39, CLAUDE.md §11). Kept in Redis per session; a wrong password never logs out."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Account, Branch, Role, Session
from app.auth.reauth_store import REAUTH_TTL_S, reauth_key
from app.core.audit import AuditLog
from tests.conftest import Client, FakeMailServer, make_personal

PASSWORD = "Spravne-Heslo-1"
ADMIN = "admin@smartsro.sk"


async def _admin(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> Account:
    acc = await make_personal(db, email=ADMIN, role=Role.admin)
    mail_server.passwords[ADMIN] = PASSWORD
    assert (await client.login(ADMIN, PASSWORD)).status_code == 200
    return acc


async def _session_ids(db: AsyncSession, account: Account) -> list[Any]:
    rows = await db.execute(
        select(Session.id)
        .where(Session.account_id == account.id, Session.revoked_at.is_(None))
        .execution_options(populate_existing=True)
    )
    return list(rows.scalars())


async def _patch(client: Client, account: Account, **body: Any) -> Any:
    return await client.send_json("PATCH", f"/api/settings/admin/users/{account.id}", body)


async def test_54_admin_change_requires_a_recent_reauth(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, app: FastAPI
) -> None:
    admin = await _admin(client, db, mail_server)
    eva = await make_personal(db, email="eva@smartsro.sk")
    r = await _patch(client, eva, role="accounting")
    assert r.status_code == 401 and r.json()["detail"]["code"] == "reauth_required"
    assert (await client.get("/api/auth/me")).status_code == 200  # still signed in

    ok = await client.reauth(PASSWORD)
    assert ok.status_code == 200 and ok.json()["valid_s"] == REAUTH_TTL_S
    assert (await _patch(client, eva, role="accounting")).status_code == 200

    (session_id,) = await _session_ids(db, admin)
    ttl = await app.state.redis.ttl(reauth_key(session_id))
    assert REAUTH_TTL_S - 5 <= ttl <= REAUTH_TTL_S
    await app.state.redis.delete(reauth_key(session_id))  # what the 15 min TTL does
    assert (await _patch(client, eva, role="sales")).json()["detail"]["code"] == "reauth_required"

    rows = (
        await db.execute(
            select(AuditLog).where(AuditLog.action == "auth.reauth").execution_options(populate_existing=True)
        )
    ).scalars()
    details = [row.details for row in rows]
    assert details == [{"result": "ok"}] and PASSWORD not in repr(details)


async def test_54_wrong_password_does_not_log_out_and_counts_towards_the_limit(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    for _ in range(5):
        r = await client.reauth("zle")
        assert r.status_code == 422 and r.json()["detail"]["code"] == "reauth_failed"
        assert (await client.get("/api/auth/me")).status_code == 200
    locked = await client.reauth(PASSWORD)
    assert locked.status_code == 429 and locked.json()["detail"]["code"] == "rate_limited"
    failed = (
        await db.execute(
            select(AuditLog).where(AuditLog.action == "auth.reauth").execution_options(populate_existing=True)
        )
    ).scalars()
    assert [row.details["result"] for row in failed] == ["failed"] * 5


async def test_54_reauth_belongs_to_the_session_not_the_login(
    client: Client, new_client: Callable[[], Client], db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    eva = await make_personal(db, email="eva@smartsro.sk")
    assert (await client.reauth(PASSWORD)).status_code == 200
    async with new_client() as other_device:
        assert (await other_device.login(ADMIN, PASSWORD)).status_code == 200
        r = await other_device.send_json("PATCH", f"/api/settings/admin/users/{eva.id}", {"role": "accounting"})
        assert r.status_code == 401 and r.json()["detail"]["code"] == "reauth_required"
    assert (await _patch(client, eva, role="accounting")).status_code == 200


async def test_54_logout_and_revoked_sessions_drop_the_reauth(
    client: Client, new_client: Callable[[], Client], db: AsyncSession, mail_server: FakeMailServer, app: FastAPI
) -> None:
    admin = await _admin(client, db, mail_server)
    assert (await client.reauth(PASSWORD)).status_code == 200
    (first,) = await _session_ids(db, admin)
    assert await app.state.redis.exists(reauth_key(first))
    assert (await client.send_json("POST", "/api/auth/logout")).status_code == 200
    assert not await app.state.redis.exists(reauth_key(first))

    # revoke_account_sessions (Odhlásiť zo všetkých zariadení) drops the re-auth of every revoked session
    eva = await make_personal(db, email="eva@smartsro.sk")
    mail_server.passwords[eva.email] = "Evine-Heslo-9"
    async with new_client() as eva_browser:
        assert (await eva_browser.login(eva.email, "Evine-Heslo-9")).status_code == 200
        (eva_session,) = await _session_ids(db, eva)
        await app.state.redis.set(reauth_key(eva_session), str(eva.id))
        assert (await client.login(ADMIN, PASSWORD)).status_code == 200
        assert (await client.reauth(PASSWORD)).status_code == 200
        r = await client.send_json("POST", f"/api/settings/admin/users/{eva.id}/logout-all")
        assert r.status_code == 200 and r.json()["revoked_sessions"] == 1
    assert not await app.state.redis.exists(reauth_key(eva_session))


async def test_54_a_refused_change_keeps_the_reauth(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    """409 `last_admin` rolls the revocation back, so the session keeps its re-auth (no second password prompt)."""
    admin = await _admin(client, db, mail_server)
    branch = Branch(name="Pobočka Senica")
    db.add(branch)
    await db.commit()
    assert (await client.reauth(PASSWORD)).status_code == 200
    # converting the only admin's login revokes its sessions inside the transaction, then 409 rolls it back
    for body in ({"kind": "branch", "branch_id": str(branch.id)}, {"role": "sales"}, {"active": False}):
        r = await _patch(client, admin, **body)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "last_admin", body


async def test_54_person_role_and_active_need_reauth_names_do_not(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    admin = await _admin(client, db, mail_server)
    body = {"first_name": "Jana", "last_name": "Testová", "function": "obchod", "role": "admin", "active": True}
    r = await client.send_json("PUT", f"/api/settings/admin/people/{admin.person_id}", body)
    assert r.status_code == 200, r.text
    r = await client.send_json("PUT", f"/api/settings/admin/people/{admin.person_id}", {**body, "role": "sales"})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "reauth_required"


async def test_54_non_admin_gets_403_not_a_password_prompt(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    jana = await make_personal(db, email="jana@smartsro.sk")
    mail_server.passwords[jana.email] = PASSWORD
    assert (await client.login(jana.email, PASSWORD)).status_code == 200
    r = await _patch(client, jana, role="admin")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "admin_required"
