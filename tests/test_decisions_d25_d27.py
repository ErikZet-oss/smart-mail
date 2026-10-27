"""Customer decisions of 26 October 2026 on the Phase 1a login (DECISIONS.md D25–D27, ADR-003)."""

from __future__ import annotations

from collections.abc import Callable

import structlog
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Account, AccountKind, Person, Role
from app.auth.security import decrypt
from app.core.audit import AuditLog
from app.core.config import Settings
from tests.conftest import Client, FakeMailServer, make_personal

PASSWORD = "Spravne-Heslo-1"


async def account_by_email(db: AsyncSession, email: str) -> Account | None:
    db.expire_all()
    return (await db.execute(select(Account).where(Account.email == email))).scalar_one_or_none()


# --- D25: auto-created accounts for INTERNAL_DOMAINS, viewer until an admin assigns a role ------------------------
async def test_d25_first_login_of_internal_address_creates_viewer_account(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    mail_server.passwords["peter.hudak@smartsro.sk"] = PASSWORD
    r = await client.login("Peter.Hudak@smartsro.sk", PASSWORD)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["next"] == "app"
    assert body["me"]["person"]["role"] == "viewer" and body["me"]["read_only"] is True
    assert body["me"]["person"]["full_name"] == "Peter Hudak"

    acc = await account_by_email(db, "peter.hudak@smartsro.sk")
    assert acc is not None and acc.kind == AccountKind.personal and acc.person_id is not None
    entry = (await db.execute(select(AuditLog).where(AuditLog.action == "auth.account_created"))).scalar_one()
    assert entry.account_id == acc.id and entry.details == {"role": "viewer", "source": "first_login"}


async def test_d25_second_login_reuses_the_account(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    mail_server.passwords["eva@smartsro.sk"] = PASSWORD
    assert (await client.login("eva@smartsro.sk", PASSWORD)).status_code == 200
    assert (await client.login("eva@smartsro.sk", PASSWORD)).status_code == 200
    rows = (await db.execute(select(Account).where(Account.email == "eva@smartsro.sk"))).scalars().all()
    assert len(rows) == 1


async def test_d25_address_outside_internal_domains_is_never_created(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    mail_server.passwords["cudzi@gmail.com"] = PASSWORD
    r = await client.login("cudzi@gmail.com", PASSWORD)
    assert r.status_code == 401 and r.json()["detail"]["code"] == "invalid_credentials"
    assert await account_by_email(db, "cudzi@gmail.com") is None


async def test_d25_subdomain_lookalike_is_not_internal(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    mail_server.passwords["x@evil-smartsro.sk"] = PASSWORD
    assert (await client.login("x@evil-smartsro.sk", PASSWORD)).status_code == 401
    assert await account_by_email(db, "x@evil-smartsro.sk") is None


async def test_d25_wrong_password_does_not_create_account(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    mail_server.passwords["novy@smartsro.sk"] = PASSWORD
    assert (await client.login("novy@smartsro.sk", "zle")).status_code == 401
    assert await account_by_email(db, "novy@smartsro.sk") is None


async def test_d25_admin_emails_become_admin_on_first_login(
    client: Client, app: FastAPI, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    app.state.settings.admin_emails = "Admin@SmartSro.sk, druhy@smartsro.sk"
    mail_server.passwords["admin@smartsro.sk"] = PASSWORD
    body = (await client.login("admin@smartsro.sk", PASSWORD)).json()
    assert body["me"]["person"]["role"] == "admin" and body["me"]["read_only"] is False
    entry = (await db.execute(select(AuditLog).where(AuditLog.action == "auth.account_created"))).scalar_one()
    assert entry.details == {"role": "admin", "source": "first_login"}


async def test_d25_admin_emails_do_not_change_existing_roles(
    client: Client, app: FastAPI, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    acc = await make_personal(db, "jana@smartsro.sk", role=Role.viewer)
    person_id = acc.person_id
    app.state.settings.admin_emails = "jana@smartsro.sk"
    mail_server.passwords["jana@smartsro.sk"] = PASSWORD
    assert (await client.login("jana@smartsro.sk", PASSWORD)).json()["me"]["person"]["role"] == "viewer"
    db.expire_all()
    person = await db.get(Person, person_id)
    assert person is not None and person.role == Role.viewer


async def test_d25_disabled_auto_account_stays_disabled(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    mail_server.passwords["eva@smartsro.sk"] = PASSWORD
    assert (await client.login("eva@smartsro.sk", PASSWORD)).status_code == 200
    acc = await account_by_email(db, "eva@smartsro.sk")
    assert acc is not None
    acc.active = False
    await db.commit()
    assert (await client.login("eva@smartsro.sk", PASSWORD)).status_code == 401


def test_d25_admin_email_list_is_normalised() -> None:
    s = Settings(admin_emails=" A@SmartSro.sk ,,b@smartsro.sk ")
    assert s.admin_email_list == {"a@smartsro.sk", "b@smartsro.sk"}


# --- D26: per-account 5 / 5 min, per-IP 30 / 5 min, company IPs exempt from the IP limit ---------------------------
def test_d26_default_limits() -> None:
    s = Settings()
    assert (s.login_max_failures, s.login_ip_max_failures, s.login_lock_minutes) == (5, 30, 5)


def test_d26_ip_allowlist_accepts_addresses_and_networks() -> None:
    s = Settings(login_ip_allowlist="203.0.113.10, 198.51.100.0/24")
    assert s.ip_exempt_from_limit("203.0.113.10")
    assert s.ip_exempt_from_limit("198.51.100.77")
    assert not s.ip_exempt_from_limit("198.51.101.1")
    assert not s.ip_exempt_from_limit(None)
    assert not s.ip_exempt_from_limit("not-an-ip")


def test_d26_ip_allowlist_rejects_garbage() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(login_ip_allowlist="203.0.113.10, nonsense")


async def test_d26_ip_limit_is_30_per_window(client: Client, mail_server: FakeMailServer) -> None:
    for i in range(30):
        assert (await client.login(f"u{i}@smartsro.sk", "zle")).status_code == 401
    assert (await client.login("iny@smartsro.sk", "zle")).status_code == 429


async def test_d26_company_ip_is_exempt_from_ip_limit(
    client: Client, app: FastAPI, mail_server: FakeMailServer
) -> None:
    app.state.settings.login_ip_max_failures = 3
    app.state.settings.login_ip_allowlist = "127.0.0.0/8"  # the ASGI test client connects from 127.0.0.1
    for i in range(10):
        assert (await client.login(f"u{i}@smartsro.sk", "zle")).status_code == 401


async def test_d26_company_ip_still_has_the_per_account_limit(
    client: Client, app: FastAPI, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    app.state.settings.login_ip_allowlist = "127.0.0.1"
    await make_personal(db, "jana@smartsro.sk")
    mail_server.passwords["jana@smartsro.sk"] = PASSWORD
    for _ in range(5):
        assert (await client.login("jana@smartsro.sk", "zle")).status_code == 401
    assert (await client.login("jana@smartsro.sk", PASSWORD)).status_code == 429


# --- D27: mailbox password stored encrypted (Fernet), overwritten on change, never logged -------------------------
async def test_d27_mailbox_password_stored_encrypted(
    client: Client, app: FastAPI, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await make_personal(db, "jana@smartsro.sk")
    mail_server.passwords["jana@smartsro.sk"] = PASSWORD
    assert (await client.login("jana@smartsro.sk", PASSWORD)).status_code == 200
    acc = await account_by_email(db, "jana@smartsro.sk")
    assert acc is not None and acc.mailbox_password_enc is not None
    assert PASSWORD not in acc.mailbox_password_enc
    assert decrypt(app.state.settings, acc.mailbox_password_enc) == PASSWORD
    assert acc.mailbox_password_set_at is not None


async def test_d27_password_change_overwrites_stored_password_immediately(
    client: Client, new_client: Callable[[], Client], app: FastAPI, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await make_personal(db, "jana@smartsro.sk")
    mail_server.passwords["jana@smartsro.sk"] = PASSWORD
    assert (await client.login("jana@smartsro.sk", PASSWORD)).status_code == 200
    first = await account_by_email(db, "jana@smartsro.sk")
    assert first is not None
    old_cipher, old_set_at = first.mailbox_password_enc, first.mailbox_password_set_at

    mail_server.passwords["jana@smartsro.sk"] = "Nove-Heslo-2"
    async with new_client() as other:
        assert (await other.login("jana@smartsro.sk", "Nove-Heslo-2")).status_code == 200
    acc = await account_by_email(db, "jana@smartsro.sk")
    assert acc is not None and acc.mailbox_password_enc is not None
    assert acc.mailbox_password_enc != old_cipher
    assert decrypt(app.state.settings, acc.mailbox_password_enc) == "Nove-Heslo-2"
    assert old_set_at is not None and acc.mailbox_password_set_at is not None
    assert acc.mailbox_password_set_at >= old_set_at


async def test_d27_same_password_is_not_rewritten(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await make_personal(db, "jana@smartsro.sk")
    mail_server.passwords["jana@smartsro.sk"] = PASSWORD
    await client.login("jana@smartsro.sk", PASSWORD)
    first = await account_by_email(db, "jana@smartsro.sk")
    assert first is not None
    cipher = first.mailbox_password_enc
    await client.login("jana@smartsro.sk", PASSWORD)
    acc = await account_by_email(db, "jana@smartsro.sk")
    assert acc is not None and acc.mailbox_password_enc == cipher


async def test_d27_wrong_password_is_never_stored(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await make_personal(db, "jana@smartsro.sk")
    mail_server.passwords["jana@smartsro.sk"] = PASSWORD
    await client.login("jana@smartsro.sk", "zle-heslo")
    acc = await account_by_email(db, "jana@smartsro.sk")
    assert acc is not None and acc.mailbox_password_enc is None


async def test_d27_password_and_key_never_in_logs_or_audit(
    client: Client, app: FastAPI, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    mail_server.passwords["eva@smartsro.sk"] = PASSWORD
    with structlog.testing.capture_logs() as logs:
        await client.login("eva@smartsro.sk", "zle-heslo")
        await client.login("eva@smartsro.sk", PASSWORD)
    acc = await account_by_email(db, "eva@smartsro.sk")
    assert acc is not None and acc.mailbox_password_enc is not None
    key = app.state.settings.app_secret_key.get_secret_value()
    dumped = repr(logs) + repr([a.details for a in (await db.execute(select(AuditLog))).scalars()])
    for secret in (PASSWORD, "zle-heslo", acc.mailbox_password_enc, key):
        assert secret not in dumped


def test_d27_account_repr_hides_the_cipher() -> None:
    acc = Account(email="a@smartsro.sk", mailbox_password_enc="gAAAA-cipher")
    assert "gAAAA-cipher" not in repr(acc)


# --- decision 7: W16a "Požiadať správcu" = mailto to the admin address from config ------------------------------
async def test_w16a_admin_contact_comes_from_config(client: Client, app: FastAPI) -> None:
    app.state.settings.admin_contact_email = "it@smartsro.sk"
    app.state.settings.feature_money = False
    r = await client.get("/api/system/info")
    assert r.status_code == 200
    assert r.json() == {"admin_contact_email": "it@smartsro.sk", "features": {"money": False}}


async def test_w16a_admin_contact_empty_when_unset(client: Client, app: FastAPI) -> None:
    app.state.settings.admin_contact_email = None
    app.state.settings.feature_money = False
    assert (await client.get("/api/system/info")).json() == {
        "admin_contact_email": None,
        "features": {"money": False},
    }
