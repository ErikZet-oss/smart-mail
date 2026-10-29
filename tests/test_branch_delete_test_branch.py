"""Pilot: a test branch could never be removed. „Vymazať pobočku“ needs no active person, but the last active person
could not be deactivated or deleted (409 last_active_person) even when no branch login uses the branch."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Account, Branch, Person
from tests.conftest import Client, FakeMailServer, make_branch
from tests.test_branches_people_55 import _admin, _person_body


async def test_branch_without_login_last_person_can_go_and_branch_is_deleted(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    branch, login = await make_branch(db, "Testovacia", people=2)
    # the branch login was converted / removed first: nobody picks a person on this branch any more
    await db.execute(delete(Account).where(Account.id == login.id))
    await db.commit()
    first, last = (await db.execute(select(Person).where(Person.branch_id == branch.id))).scalars().all()

    r = await client.send_json("PUT", f"/api/settings/admin/people/{first.id}", _person_body(first, active=False))
    assert r.status_code == 200, r.text
    r = await client.send_json("DELETE", f"/api/settings/admin/people/{last.id}")
    assert r.status_code == 200, r.text

    r = await client.send_json("DELETE", f"/api/settings/admin/branches/{branch.id}")
    assert r.status_code == 200, r.text
    assert await db.get(Branch, branch.id, populate_existing=True) is None


async def test_branch_with_login_still_keeps_one_active_person(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    branch, _login = await make_branch(db, "Nitra2", people=1)
    only = (await db.execute(select(Person).where(Person.branch_id == branch.id))).scalar_one()
    r = await client.send_json("PUT", f"/api/settings/admin/people/{only.id}", _person_body(only, active=False))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "last_active_person"
    r = await client.send_json("DELETE", f"/api/settings/admin/people/{only.id}")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "last_active_person"
