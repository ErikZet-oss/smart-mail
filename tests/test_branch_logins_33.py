"""Issue #33: branch logins and persons managed in Settings 10/11 (no CLI or SQL needed), the last-admin guard, and
the CLI converting an auto-provisioned account."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Account, AccountKind, Branch, Person, Role
from app.core.audit import AuditLog
from app.mail.models import Mailbox
from tests.conftest import Client, FakeMailServer, make_branch, make_personal

PASSWORD = "Spravne-Heslo-1"
SIGNATURE = {"sk": "<p>{meno} {priezvisko} – {pobocka}</p>"}


async def _admin(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> Account:
    acc = await make_personal(db, email="admin@smartsro.sk", role=Role.admin)
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200
    return acc


async def _actions(db: AsyncSession) -> list[str]:
    rows = await db.execute(select(AuditLog.action).execution_options(populate_existing=True))
    return list(rows.scalars())


async def _senica(db: AsyncSession) -> Branch:
    branch = Branch(name="Pobočka Senica", signature_template_html=SIGNATURE)
    db.add(branch)
    await db.flush()
    db.add_all(
        [
            Person(branch_id=branch.id, first_name="Jana", last_name="Nováková", role=Role.sales),
            Person(branch_id=branch.id, first_name="Marek", last_name="Kováč", role=Role.warehouse),
        ]
    )
    await db.commit()
    return branch


# --- Settings 10 -------------------------------------------------------------------------------------------------
async def test_33_branch_login_requires_branch_id(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    other = await make_personal(db, email="eva@smartsro.sk")

    r = await client.send_json("POST", "/api/settings/admin/users", {"email": "nitra@smartsro.sk", "kind": "branch"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "branch_required"
    r = await client.send_json("PATCH", f"/api/settings/admin/users/{other.id}", {"kind": "branch"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "branch_required"
    await db.refresh(other)
    assert other.kind == AccountKind.personal


async def test_33_create_branch_and_personal_accounts(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    branch = await _senica(db)
    r = await client.send_json(
        "POST",
        "/api/settings/admin/users",
        {"email": "Senica@smartsro.sk", "kind": "branch", "branch_id": str(branch.id)},
    )
    assert r.status_code == 200, r.text
    assert (r.json()["kind"], r.json()["branch_name"]) == ("branch", "Pobočka Senica")

    r = await client.send_json(
        "POST",
        "/api/settings/admin/users",
        {
            "email": "eva@smartsro.sk",
            "kind": "personal",
            "first_name": "Eva",
            "last_name": "Malá",
            "role": "accounting",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["person"]["role"] == "accounting"

    r = await client.send_json("POST", "/api/settings/admin/users", {"email": "eva@smartsro.sk", "kind": "personal"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "account_exists"
    r = await client.send_json("POST", "/api/settings/admin/users", {"email": "ivo@smartsro.sk", "kind": "personal"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "name_required"
    assert (await _actions(db)).count("settings.user_created") == 2


async def test_33_last_admin_cannot_be_demoted(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    admin = await _admin(client, db, mail_server)
    branch = await _senica(db)  # no admin among its persons

    for patch in ({"kind": "branch", "branch_id": str(branch.id)}, {"role": "sales"}, {"active": False}):
        r = await client.send_json("PATCH", f"/api/settings/admin/users/{admin.id}", patch)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "last_admin", patch

    assert admin.person_id is not None
    r = await client.send_json(
        "PUT",
        f"/api/settings/admin/people/{admin.person_id}",
        {"first_name": "Jana", "last_name": "T", "role": "sales"},
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "last_admin"

    acc = (
        await db.execute(select(Account).where(Account.id == admin.id).execution_options(populate_existing=True))
    ).scalar_one()
    person = await db.get(Person, admin.person_id, populate_existing=True)
    assert acc.kind == AccountKind.personal and acc.active and person is not None and person.role == Role.admin

    # with a second admin login, the change is allowed
    await make_personal(db, email="erik@smartsro.sk", role=Role.admin)
    r = await client.send_json("PATCH", f"/api/settings/admin/users/{admin.id}", {"role": "sales"})
    assert r.status_code == 200, r.text


# --- Settings 11 + "Kto ste?" ------------------------------------------------------------------------------------
async def _login_mailbox(client: Client, mail_server: FakeMailServer, email: str) -> dict[str, object]:
    mail_server.passwords[email] = PASSWORD
    r = await client.login(email, PASSWORD)
    assert r.status_code == 200, r.text
    body: dict[str, object] = r.json()
    return body


async def _pick_and_sign(client: Client, person: Person) -> str:
    r = await client.send_json("POST", "/api/auth/person", {"person_id": str(person.id), "remember_device": False})
    assert r.status_code == 200, r.text
    draft = await client.send_json("POST", "/api/mail/mailboxes/default/compose", {"mode": "new"})
    assert draft.status_code == 200, draft.text
    html: str = (await client.get(f"/api/mail/compose/{draft.json()['id']}/signature-preview")).json()["html"]
    return html


async def test_33_branch_mailbox_link_shows_picker(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    branch = await _senica(db)
    jana = (await db.execute(select(Person).where(Person.last_name == "Nováková"))).scalar_one()
    mailbox = Mailbox(email="senica@smartsro.sk", imap_host="localhost", imap_port=143, imap_security="none")
    db.add(mailbox)
    await db.flush()
    branch.mailbox_id = mailbox.id
    await db.commit()

    # no login for the mailbox yet: Settings 11 offers "Prepojiť prihlásenie s pobočkou", which creates it
    listed = (await client.get("/api/settings/admin/branches")).json()
    assert listed[0]["login_account"] is None
    r = await client.send_json("POST", f"/api/settings/admin/branches/{branch.id}/link-login", {})
    assert r.status_code == 200, r.text
    listed = (await client.get("/api/settings/admin/branches")).json()
    assert listed[0]["login_account"]["linked"] is True
    assert "settings.branch_login_linked" in await _actions(db)

    await client.send_json("POST", "/api/auth/logout", {})
    login = await _login_mailbox(client, mail_server, "senica@smartsro.sk")
    assert login["next"] == "who"
    me = (await client.get("/api/auth/me")).json()
    assert me["needs_person"] is True
    assert "Jana Nováková – Pobočka Senica" in await _pick_and_sign(client, jana)


async def test_33_auto_provisioned_account_converted_to_branch_shows_picker(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    """Pilot: fa@ signed in before it was a branch → personal viewer "Fa"; the admin converts it in Settings 10."""
    branch = await _senica(db)
    first = await _login_mailbox(client, mail_server, "fa@smartsro.sk")
    assert first["next"] != "who"
    fa = (await db.execute(select(Account).where(Account.email == "fa@smartsro.sk"))).scalar_one()
    placeholder_id = fa.person_id
    fa_cookies = dict(client.cookies)

    client.cookies.clear()
    await _admin(client, db, mail_server)
    r = await client.send_json(
        "PATCH", f"/api/settings/admin/users/{fa.id}", {"kind": "branch", "branch_id": str(branch.id)}
    )
    assert r.status_code == 200, r.text

    fa = (
        await db.execute(select(Account).where(Account.id == fa.id).execution_options(populate_existing=True))
    ).scalar_one()
    placeholder = await db.get(Person, placeholder_id, populate_existing=True)
    assert (fa.kind, fa.branch_id, fa.person_id) == (AccountKind.branch, branch.id, None)
    assert placeholder is not None and placeholder.active is False  # deactivated, never deleted

    # the old session of fa@ is revoked
    client.cookies.clear()
    client.cookies.update(fa_cookies)
    assert (await client.get("/api/auth/me")).status_code == 401

    client.cookies.clear()
    login = await _login_mailbox(client, mail_server, "fa@smartsro.sk")
    assert login["next"] == "who"
    jana = (await db.execute(select(Person).where(Person.last_name == "Nováková"))).scalar_one()
    assert "Jana Nováková" in await _pick_and_sign(client, jana)


async def test_33_delete_person_deactivates_with_history_and_keeps_the_last_one(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    branch, _ = await make_branch(db, "Nitra", people=3)
    a, b, c = (await db.execute(select(Person).where(Person.branch_id == branch.id))).scalars().all()
    db.add(AuditLog(action="mail.sent", person_id=a.id))
    await db.commit()

    r = await client.send_json("DELETE", f"/api/settings/admin/people/{a.id}")
    assert r.status_code == 200 and r.json()["result"] == "deactivated"
    r = await client.send_json("DELETE", f"/api/settings/admin/people/{b.id}")
    assert r.status_code == 200 and r.json()["result"] == "deleted"
    r = await client.send_json("DELETE", f"/api/settings/admin/people/{c.id}")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "last_active_person"
    assert await db.get(Person, a.id, populate_existing=True) is not None


async def test_33_add_branch_and_edit_person(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await _admin(client, db, mail_server)
    r = await client.send_json("POST", "/api/settings/admin/branches", {"name": "Pobočka Trenčín"})
    assert r.status_code == 200, r.text
    branch_id = r.json()["id"]
    r = await client.send_json(
        "POST",
        f"/api/settings/admin/branches/{branch_id}/people",
        {"first_name": "Zuzana", "last_name": "Hrušková", "function": "obchod", "mobile": "+421900000030"},
    )
    person_id = r.json()["id"]
    r = await client.send_json(
        "PUT",
        f"/api/settings/admin/people/{person_id}",
        {"first_name": "Zuzana", "last_name": "Hrušková", "function": "vedúca", "role": "sales", "is_manager": True},
    )
    assert r.status_code == 200, r.text
    person = await db.get(Person, person_id, populate_existing=True)
    assert person is not None and person.function == "vedúca" and person.is_manager


# --- CLI ---------------------------------------------------------------------------------------------------------
@pytest.fixture
def cli_env(migrated: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("DATABASE_URL", migrated)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_cli_add_person_creates_branch(
    db: AsyncSession, cli_env: None, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.cli import main

    await main(["add-person", "Pobočka Senica", "--first-name", "Peter", "--last-name", "Hudák", "--manager"])
    assert "created person" in capsys.readouterr().out
    branch = (await db.execute(select(Branch).where(Branch.name == "Pobočka Senica"))).scalar_one()
    peter = (await db.execute(select(Person).where(Person.branch_id == branch.id))).scalar_one()
    assert peter.is_manager


async def test_cli_add_account_convert_existing_personal(
    db: AsyncSession, cli_env: None, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.cli import main

    await make_personal(db, email="admin@smartsro.sk", role=Role.admin)
    fa = await make_personal(db, email="fa@smartsro.sk", role=Role.viewer)
    await main(["add-account", "fa@smartsro.sk", "--branch", "Pobočka Senica"])
    assert "--convert" in capsys.readouterr().out
    await main(["add-account", "fa@smartsro.sk", "--branch", "Pobočka Senica", "--convert"])
    assert "converted" in capsys.readouterr().out
    fa = (
        await db.execute(select(Account).where(Account.id == fa.id).execution_options(populate_existing=True))
    ).scalar_one()
    assert fa.kind == AccountKind.branch and fa.person_id is None


async def test_33_delete_person_with_a_draft_or_session_deactivates_instead_of_500(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    """Review #53: any reference (a session's active person, a compose draft) must not turn the delete into a 500."""
    from datetime import UTC, datetime, timedelta

    from app.auth.models import Session
    from app.mail.compose_models import ComposeDraft

    await _admin(client, db, mail_server)
    branch, branch_acc = await make_branch(db, "Nitra", people=3)
    a, b, _ = (await db.execute(select(Person).where(Person.branch_id == branch.id))).scalars().all()
    now = datetime.now(UTC)
    db.add(
        Session(
            account_id=branch_acc.id,
            token_hash="f" * 64,
            active_person_id=a.id,
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=1),
        )
    )
    mailbox = Mailbox(email=branch_acc.email, imap_host="localhost", imap_port=143, imap_security="none")
    db.add(mailbox)
    await db.flush()
    db.add(ComposeDraft(mailbox_id=mailbox.id, account_id=branch_acc.id, person_id=b.id))
    await db.commit()

    for person in (a, b):
        r = await client.send_json("DELETE", f"/api/settings/admin/people/{person.id}")
        assert r.status_code == 200, r.text
        assert r.json()["result"] == "deactivated"
        kept = await db.get(Person, person.id, populate_existing=True)
        assert kept is not None and kept.active is False


async def test_33_admin_changes_are_audited_with_before_and_after(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    branch = await _senica(db)
    eva = await make_personal(db, email="eva@smartsro.sk", role=Role.viewer)
    r = await client.send_json(
        "PATCH", f"/api/settings/admin/users/{eva.id}", {"kind": "branch", "branch_id": str(branch.id)}
    )
    assert r.status_code == 200, r.text
    row = (
        await db.execute(
            select(AuditLog).where(AuditLog.action == "settings.user_patched").execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert row.details["before"] == {"kind": "personal", "branch_id": None, "role": "viewer", "active": True}
    assert row.details["after"] == {"kind": "branch", "branch_id": str(branch.id), "role": None, "active": True}
