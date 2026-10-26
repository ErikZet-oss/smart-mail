"""Phase 1b: "Kto ste?" picker, PersonChip switching, device memory, person + account in the audit log
(SCREENS_SPEC W1b, W2b, M0; PRODUCT_SPEC §2.0 incl. its edge cases; CLAUDE.md §9; DECISIONS D9)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import ActivePerson
from app.auth.models import Account, Branch, Person, PersonBranch, Role
from app.auth.persons import slovak_sort_key
from app.core.audit import AuditLog
from tests.conftest import Client, FakeMailServer, make_branch, make_personal

PASSWORD = "Spravne-Heslo-1"


async def senica(db: AsyncSession, **branch: object) -> tuple[Branch, Account, dict[str, Person]]:
    """Fictional sample people of D23: Peter Hudák (manager), Jana Nováková, Marek Kováč."""
    b, acc = await make_branch(db, "Senica", people=0, **branch)
    people = {
        "jana": Person(branch_id=b.id, first_name="Jana", last_name="Nováková", function="obchod", role=Role.sales),
        "marek": Person(branch_id=b.id, first_name="Marek", last_name="Kováč", function="sklad", role=Role.warehouse),
        "peter": Person(
            branch_id=b.id,
            first_name="Peter",
            last_name="Hudák",
            function="vedúci pobočky",
            role=Role.sales,
            is_manager=True,
        ),
    }
    db.add_all(people.values())
    await db.commit()
    return b, acc, people


async def login_branch(client: Client, mail_server: FakeMailServer, acc: Account) -> None:
    mail_server.passwords[acc.email] = PASSWORD
    r = await client.login(acc.email, PASSWORD)
    assert r.status_code == 200 and r.json()["next"] == "who", r.text


async def choose(client: Client, person: Person, remember: bool = True) -> dict[str, object]:
    r = await client.send_json("POST", "/api/auth/person", {"person_id": str(person.id), "remember_device": remember})
    assert r.status_code == 200, r.text
    body: dict[str, object] = r.json()
    return body


async def audit_rows(db: AsyncSession) -> list[AuditLog]:
    query = select(AuditLog).order_by(AuditLog.created_at, AuditLog.id).execution_options(populate_existing=True)
    return list((await db.execute(query)).scalars())


# --- W1b picker content ----------------------------------------------------------------------------------------------
async def test_w1b_picker_manager_first_then_alphabetical(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    _, acc, _ = await senica(db)
    await login_branch(client, mail_server, acc)
    r = await client.get("/api/auth/persons")
    assert r.status_code == 200
    body = r.json()
    assert body["branch"] == "Senica" and body["email"] == "senica@smartsro.sk"
    assert [p["full_name"] for p in body["persons"]] == ["Peter Hudák", "Jana Nováková", "Marek Kováč"]
    assert body["persons"][0]["is_manager"] is True and body["persons"][0]["function"] == "vedúci pobočky"
    assert body["current_person_id"] is None and body["last_person_id"] is None


def test_w1b_slovak_alphabetical_order() -> None:
    names = [
        "Dana",
        "Čestmír",
        "Cyril",
        "Chrudoš",
        "Hana",
        "Ivan",
        "Šimon",
        "Stano",
        "Žofia",
        "Zuzana",
        "Ádám",
        "Andrej",
    ]
    assert sorted(names, key=slovak_sort_key) == [
        "Ádám",
        "Andrej",
        "Cyril",
        "Čestmír",
        "Dana",
        "Hana",
        "Chrudoš",
        "Ivan",
        "Stano",
        "Šimon",
        "Zuzana",
        "Žofia",
    ]


async def test_w1b_inactive_person_not_listed(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    _, acc, people = await senica(db)
    people["marek"].active = False
    await db.commit()
    await login_branch(client, mail_server, acc)
    names = [p["full_name"] for p in (await client.get("/api/auth/persons")).json()["persons"]]
    assert "Marek Kováč" not in names and len(names) == 2


async def test_w1b_person_covering_two_branches_appears_in_both_pickers(
    client: Client, new_client: Callable[[], Client], db: AsyncSession, mail_server: FakeMailServer
) -> None:
    _, senica_acc, people = await senica(db)
    nitra, nitra_acc = await make_branch(db, "Nitra", people=1)
    db.add(PersonBranch(person_id=people["jana"].id, branch_id=nitra.id))
    await db.commit()
    await login_branch(client, mail_server, nitra_acc)
    names = [p["full_name"] for p in (await client.get("/api/auth/persons")).json()["persons"]]
    assert "Jana Nováková" in names
    await choose(client, people["jana"])
    async with new_client() as other:
        await login_branch(other, mail_server, senica_acc)
        assert "Jana Nováková" in [p["full_name"] for p in (await other.get("/api/auth/persons")).json()["persons"]]


async def test_w1b_personal_account_sees_only_itself(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    acc = await make_personal(db, "jana@smartsro.sk")
    _, _, people = await senica(db)
    mail_server.passwords[acc.email] = PASSWORD
    await client.login(acc.email, PASSWORD)
    body = (await client.get("/api/auth/persons")).json()
    assert [p["id"] for p in body["persons"]] == [str(acc.person_id)]
    assert body["current_person_id"] == str(acc.person_id)
    r = await client.send_json("POST", "/api/auth/person", {"person_id": str(people["peter"].id)})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "person_not_allowed"


async def test_w1b_picker_needs_a_session(client: Client) -> None:
    assert (await client.get("/api/auth/persons")).status_code == 401
    r = await client.send_json("POST", "/api/auth/person", {"person_id": "00000000-0000-0000-0000-000000000000"})
    assert r.status_code == 401


async def test_w1b_idle_ask_minutes_of_the_branch(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    _, acc, _ = await senica(db, idle_ask_minutes=60)
    await login_branch(client, mail_server, acc)
    assert (await client.get("/api/auth/persons")).json()["idle_ask_minutes"] == 60


# --- W1b select ------------------------------------------------------------------------------------------------------
async def test_w1b_one_click_selects_and_is_audited(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    _, acc, people = await senica(db)
    await login_branch(client, mail_server, acc)
    me = await choose(client, people["jana"])
    assert me["read_only"] is False and me["needs_person"] is False
    assert isinstance(me["person"], dict) and me["person"]["full_name"] == "Jana Nováková"
    assert (await client.get("/api/auth/me")).json()["person"]["id"] == str(people["jana"].id)
    [entry] = [a for a in await audit_rows(db) if a.action == "auth.person_selected"]
    assert entry.account_id == acc.id and entry.person_id == people["jana"].id
    assert entry.details == {"remember_device": True}


async def test_w1b_person_of_another_branch_is_refused(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    _, acc, _ = await senica(db)
    nitra, _ = await make_branch(db, "Nitra", people=1)
    stranger = (await db.execute(select(Person).where(Person.branch_id == nitra.id))).scalar_one()
    await login_branch(client, mail_server, acc)
    r = await client.send_json("POST", "/api/auth/person", {"person_id": str(stranger.id)})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "person_not_allowed"
    assert (await client.get("/api/auth/me")).json()["person"] is None


async def test_w1b_inactive_person_cannot_be_selected(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    _, acc, people = await senica(db)
    people["marek"].active = False
    await db.commit()
    await login_branch(client, mail_server, acc)
    r = await client.send_json("POST", "/api/auth/person", {"person_id": str(people["marek"].id)})
    assert r.status_code == 403


async def test_w1b_select_needs_csrf(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    _, acc, people = await senica(db)
    await login_branch(client, mail_server, acc)
    r = await client.post("/api/auth/person", json={"person_id": str(people["jana"].id)})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "csrf"


# --- device memory (PRODUCT_SPEC §2.0, M0 "Zapamätať na tomto telefóne") -------------------------------------------
async def test_w1b_device_remembers_last_person_for_next_login(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    _, acc, people = await senica(db)
    await login_branch(client, mail_server, acc)
    await choose(client, people["jana"])
    await client.send_json("POST", "/api/auth/logout")
    await login_branch(client, mail_server, acc)  # the picker still opens…
    body = (await client.get("/api/auth/persons")).json()
    assert body["last_person_id"] == str(people["jana"].id)  # …with Jana pre-selected
    assert body["current_person_id"] is None


async def test_w1b_memory_is_per_device(
    client: Client, new_client: Callable[[], Client], db: AsyncSession, mail_server: FakeMailServer
) -> None:
    _, acc, people = await senica(db)
    await login_branch(client, mail_server, acc)
    await choose(client, people["jana"])
    async with new_client() as other:
        await login_branch(other, mail_server, acc)
        assert (await other.get("/api/auth/persons")).json()["last_person_id"] is None


async def test_m0_remember_off_forgets_this_device(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    _, acc, people = await senica(db)
    await login_branch(client, mail_server, acc)
    await choose(client, people["jana"])
    await choose(client, people["marek"], remember=False)
    assert (await client.get("/api/auth/persons")).json()["last_person_id"] is None


async def test_w1b_remembered_person_no_longer_active_is_not_preselected(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    _, acc, people = await senica(db)
    await login_branch(client, mail_server, acc)
    await choose(client, people["jana"])
    await client.send_json("POST", "/api/auth/logout")
    people["jana"].active = False
    await db.commit()
    await login_branch(client, mail_server, acc)
    assert (await client.get("/api/auth/persons")).json()["last_person_id"] is None


# --- W2b switching ---------------------------------------------------------------------------------------------------
async def test_w2b_switch_person_without_logout_is_logged(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    _, acc, people = await senica(db)
    await login_branch(client, mail_server, acc)
    await choose(client, people["jana"])
    session_cookie = client.cookies["sm_session"]
    me = await choose(client, people["peter"])
    assert isinstance(me["person"], dict) and me["person"]["first_name"] == "Peter"
    assert client.cookies["sm_session"] == session_cookie  # same session: no logout, no reload
    [entry] = [a for a in await audit_rows(db) if a.action == "auth.person_switched"]
    assert entry.account_id == acc.id and entry.person_id == people["peter"].id
    assert entry.details == {"from_person_id": str(people["jana"].id), "remember_device": True}


async def test_w2b_choosing_the_same_person_again_is_not_a_switch(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    _, acc, people = await senica(db)
    await login_branch(client, mail_server, acc)
    await choose(client, people["jana"])
    await choose(client, people["jana"])
    actions = [a.action for a in await audit_rows(db)]
    assert actions.count("auth.person_selected") == 1 and "auth.person_switched" not in actions


async def test_w1b_two_devices_with_the_same_person_are_allowed(
    client: Client, new_client: Callable[[], Client], db: AsyncSession, mail_server: FakeMailServer
) -> None:
    _, acc, people = await senica(db)
    await login_branch(client, mail_server, acc)
    await choose(client, people["jana"])
    async with new_client() as other:
        await login_branch(other, mail_server, acc)
        await choose(other, people["jana"])
        assert (await other.get("/api/auth/me")).json()["person"]["first_name"] == "Jana"
    assert (await client.get("/api/auth/me")).json()["person"]["first_name"] == "Jana"


# --- edge cases: person deactivated / removed while selected (PRODUCT_SPEC §2.0) ------------------------------------
async def test_w1b_person_deactivated_while_selected_gets_409_then_picker(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    _, acc, people = await senica(db)
    await login_branch(client, mail_server, acc)
    await choose(client, people["jana"])
    people["jana"].active = False
    await db.commit()
    r = await client.get("/api/auth/me")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "person_inactive"
    me = (await client.get("/api/auth/me")).json()  # the session itself stays valid: the picker opens
    assert me["needs_person"] is True and me["read_only"] is True
    assert "auth.person_unavailable" in [a.action for a in await audit_rows(db)]


async def test_w1b_person_removed_from_branch_while_selected_gets_409(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    _, _, people = await senica(db)
    nitra, nitra_acc = await make_branch(db, "Nitra", people=1)
    db.add(PersonBranch(person_id=people["jana"].id, branch_id=nitra.id))
    await db.commit()
    await login_branch(client, mail_server, nitra_acc)
    await choose(client, people["jana"])
    await db.execute(delete(PersonBranch).where(PersonBranch.branch_id == nitra.id))
    await db.commit()
    assert (await client.get("/api/auth/me")).status_code == 409


# --- read-only without a person (CLAUDE.md §9) -----------------------------------------------------------------------
async def test_actions_need_an_active_person(
    client: Client, app: FastAPI, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    @app.post("/api/test/needs-person")
    async def needs_person(person: ActivePerson) -> dict[str, str]:
        return {"person": person.full_name}

    _, acc, people = await senica(db)
    await login_branch(client, mail_server, acc)
    r = await client.send_json("POST", "/api/test/needs-person")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "person_required"
    await choose(client, people["jana"])
    assert (await client.send_json("POST", "/api/test/needs-person")).json() == {"person": "Jana Nováková"}


@pytest.mark.parametrize("role", [Role.viewer])
async def test_viewer_person_is_still_read_only(
    client: Client, app: FastAPI, db: AsyncSession, mail_server: FakeMailServer, role: Role
) -> None:
    @app.post("/api/test/needs-person-2")
    async def needs_person(person: ActivePerson) -> dict[str, str]:
        return {"person": person.full_name}

    await make_personal(db, "eva@smartsro.sk", role=role)
    mail_server.passwords["eva@smartsro.sk"] = PASSWORD
    await client.login("eva@smartsro.sk", PASSWORD)
    r = await client.send_json("POST", "/api/test/needs-person-2")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "read_only"


# --- person_id + account_id in every audit entry (CLAUDE.md §9) -----------------------------------------------------
async def test_every_audit_entry_carries_account_and_known_person(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    _, acc, people = await senica(db)
    mail_server.passwords[acc.email] = PASSWORD
    await client.login(acc.email, "zle")  # failed attempt for a known account
    await login_branch(client, mail_server, acc)
    await choose(client, people["jana"])
    await choose(client, people["marek"])
    await client.send_json("POST", "/api/auth/logout")
    rows = await audit_rows(db)
    assert {a.action for a in rows} >= {
        "auth.login_failed",
        "auth.login",
        "auth.person_selected",
        "auth.person_switched",
        "auth.logout",
    }
    assert all(a.account_id == acc.id for a in rows), [(a.action, a.account_id) for a in rows]
    after_selection = rows[[a.action for a in rows].index("auth.person_selected") :]
    assert all(a.person_id is not None for a in after_selection), [(a.action, a.person_id) for a in after_selection]
    assert rows[-1].action == "auth.logout" and rows[-1].person_id == people["marek"].id


async def test_rate_limited_attempt_on_known_account_is_attributed(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    acc = await make_personal(db, "jana@smartsro.sk")
    mail_server.passwords[acc.email] = PASSWORD
    for _ in range(6):
        await client.login(acc.email, "zle")
    [entry] = [a for a in await audit_rows(db) if a.action == "auth.login_rate_limited"]
    assert entry.account_id == acc.id
