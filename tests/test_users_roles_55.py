"""Issue #55 part 2 (Settings 10 Používatelia a role, Figma W12-10): „Overiť“, „Odhlásiť zo všetkých zariadení“,
„Prístup k schránkam“ and the „Osoby“ count of a branch login."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Account, Role
from app.core.audit import AuditLog
from app.mail.models import Mailbox, MailboxAccess
from tests.conftest import Client, FakeMailServer, make_personal
from tests.test_persons_1b import senica

PASSWORD = "Spravne-Heslo-1"


async def _admin(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> Account:
    acc = await make_personal(db, email="admin@smartsro.sk", role=Role.admin)
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200
    assert (await client.reauth(PASSWORD)).status_code == 200  # ⚠ admin changes need a fresh re-auth (#54)
    return acc


async def _audit(db: AsyncSession, action: str) -> AuditLog:
    return (
        await db.execute(select(AuditLog).where(AuditLog.action == action).execution_options(populate_existing=True))
    ).scalar_one()


async def test_55_overit_tests_the_login_without_storing_the_password(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    eva = await make_personal(db, email="eva@smartsro.sk")
    mail_server.passwords[eva.email] = "Evine-Heslo-9"
    ok = await client.send_json("POST", f"/api/settings/admin/users/{eva.id}/verify", {"password": "Evine-Heslo-9"})
    assert ok.status_code == 200 and ok.json() == {"result": "ok"}
    bad = await client.send_json("POST", f"/api/settings/admin/users/{eva.id}/verify", {"password": "zle"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "verify_failed"
    rows = (
        await db.execute(
            select(AuditLog)
            .where(AuditLog.action == "settings.user_verified")
            .execution_options(populate_existing=True)
        )
    ).scalars()
    details = [r.details for r in rows]
    assert [d["result"] for d in details] == ["ok", "invalid_credentials"]
    assert "Evine-Heslo-9" not in repr(details)
    stored = await db.get(Account, eva.id, populate_existing=True)
    assert stored is not None and stored.mailbox_password_enc is None


async def test_55_logout_everywhere_revokes_the_sessions(
    client: Client, new_client: Callable[[], Client], db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    eva = await make_personal(db, email="eva@smartsro.sk")
    mail_server.passwords[eva.email] = "Evine-Heslo-9"
    async with new_client() as eva_browser:
        assert (await eva_browser.login(eva.email, "Evine-Heslo-9")).status_code == 200
        assert (await eva_browser.get("/api/auth/me")).status_code == 200
        r = await client.send_json("POST", f"/api/settings/admin/users/{eva.id}/logout-all")
        assert r.status_code == 200 and r.json()["revoked_sessions"] >= 1
        assert (await eva_browser.get("/api/auth/me")).status_code == 401
    assert (await _audit(db, "settings.user_logged_out_everywhere")).details["revoked_sessions"] >= 1


async def test_55_mailbox_access_matrix(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    admin = await _admin(client, db, mail_server)
    info = Mailbox(email="info@smartsro.sk", imap_host="imap.example.test", imap_port=993, imap_security="ssl")
    db.add(info)
    await db.commit()
    rows = (await client.get(f"/api/settings/admin/users/{admin.id}/mailbox-access")).json()
    own = next(r for r in rows if r["email"] == "admin@smartsro.sk")
    other = next(r for r in rows if r["email"] == "info@smartsro.sk")
    assert own["own"] and own["read"] and own["send"]
    assert not other["own"] and not other["read"]

    body = [
        {"mailbox_id": own["mailbox_id"], "read": False, "send": False},  # the own mailbox stays
        {"mailbox_id": other["mailbox_id"], "read": True, "send": False},
    ]
    r = await client.send_json("PUT", f"/api/settings/admin/users/{admin.id}/mailbox-access", body)
    assert r.status_code == 200, r.text
    after = {row["email"]: (row["read"], row["send"]) for row in r.json()}
    assert after["admin@smartsro.sk"] == (True, True)
    assert after["info@smartsro.sk"] == (True, False)
    audit_row = await _audit(db, "settings.user_mailbox_access_saved")
    assert {"email": "info@smartsro.sk", "read": True, "send": False} in audit_row.details["after"]

    r = await client.send_json(
        "PUT",
        f"/api/settings/admin/users/{admin.id}/mailbox-access",
        [{"mailbox_id": other["mailbox_id"], "read": False, "send": False}],
    )
    assert r.status_code == 200
    left = (
        await db.execute(
            select(MailboxAccess).where(MailboxAccess.account_id == admin.id, MailboxAccess.mailbox_id == info.id)
        )
    ).scalar_one_or_none()
    assert left is None


async def test_55_branch_login_shows_its_persons_count(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    _, branch_login, _ = await senica(db)
    users = (await client.get("/api/settings/admin/users")).json()
    row = next(u for u in users if u["id"] == str(branch_login.id))
    assert row["persons_count"] == 3
    assert next(u for u in users if u["email"] == "admin@smartsro.sk")["persons_count"] is None


async def test_55_users_endpoints_need_an_admin(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    acc = await make_personal(db, email="jana@smartsro.sk")
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200
    for method, path, body in (
        ("POST", f"/api/settings/admin/users/{acc.id}/verify", {"password": "x"}),
        ("POST", f"/api/settings/admin/users/{acc.id}/logout-all", None),
        ("PUT", f"/api/settings/admin/users/{acc.id}/mailbox-access", []),
    ):
        assert (await client.send_json(method, path, body)).status_code == 403, path
    assert (await client.get(f"/api/settings/admin/users/{acc.id}/mailbox-access")).status_code == 403
