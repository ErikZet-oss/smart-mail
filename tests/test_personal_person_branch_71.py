"""Issue #71: the person of a personal login (eshop@) is managed in Pobočky a osoby › „Osobné účty“; the admin sets
its branch for the signature (Karta gets {adresa_pobocky}), without putting it into „Kto ste?“ of that branch."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Person, Role
from app.auth.persons import eligible_persons
from app.core.audit import AuditLog
from app.mail.compose_models import Identity
from app.mail.signature import render_signature
from tests.conftest import Client, FakeMailServer, make_personal
from tests.test_persons_1b import senica

PASSWORD = "Spravne-Heslo-1"
TEMPLATE = {"sk": "<p>{meno} {priezvisko} · {pobocka} · {adresa_pobocky} · {telefon_pobocky}</p>"}
ADDRESS = "Hlavná 1, 905 01 Senica"


async def _admin(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    acc = await make_personal(db, email="admin@smartsro.sk", role=Role.admin)
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200


def _body(person: dict[str, Any], **changes: Any) -> dict[str, Any]:
    body = {k: person[k] for k in ("first_name", "last_name", "function", "phone", "mobile", "role", "is_manager")}
    body.update(active=True, personal_email=None)
    body.update(changes)
    return body


async def test_71_admin_sets_the_branch_of_a_personal_account_person(
    client: Client, new_client: Any, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    eshop = await make_personal(db, email="eshop@smartsro.sk")
    branch, branch_login, people = await senica(
        db, address=ADDRESS, phone="034 000 00 00", signature_template_html=TEMPLATE
    )
    expected_picker = {p.id for p in people.values()}

    listed = (await client.get("/api/settings/admin/personal-people")).json()
    row = next(p for p in listed if p["login_email"] == "eshop@smartsro.sk")
    assert row["branch_id"] is None and row["id"] == str(eshop.person_id)

    r = await client.send_json(
        "PUT",
        f"/api/settings/admin/people/{row['id']}",
        _body(row, first_name="Eshop", last_name="Smart", function="e-shop", branch_id=str(branch.id)),
    )
    assert r.status_code == 200, r.text
    row = next(p for p in (await client.get("/api/settings/admin/personal-people")).json() if p["id"] == row["id"])
    assert (row["branch_id"], row["first_name"], row["function"]) == (str(branch.id), "Eshop", "e-shop")
    audit_row = (
        await db.execute(
            select(AuditLog).where(AuditLog.action == "settings.person_saved").execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert audit_row.details["before"]["branch_id"] is None
    assert audit_row.details["after"]["branch_id"] == str(branch.id)

    # the branch list and the „Kto ste?“ picker of Senica stay without eshop@'s person
    senica_row = next(b for b in (await client.get("/api/settings/admin/branches")).json() if b["id"] == str(branch.id))
    assert row["id"] not in {p["id"] for p in senica_row["people"]}
    picker = await eligible_persons(db, branch_login)
    assert {p.id for p in picker} == expected_picker

    # eshop@ itself: the Karta now carries the branch address and phone
    eshop_client: Client = new_client()
    async with eshop_client:
        mail_server.passwords[eshop.email] = PASSWORD
        assert (await eshop_client.login(eshop.email, PASSWORD)).status_code == 200
        created = await eshop_client.send_json("POST", "/api/mail/mailboxes/default/compose", {"mode": "new"})
        assert created.status_code == 200, created.text
        preview = (await eshop_client.get(f"/api/mail/compose/{created.json()['id']}/signature-preview")).json()
    assert "Eshop Smart" in preview["html"]
    assert ADDRESS in preview["html"] and "034 000 00 00" in preview["html"]

    # „bez pobočky“ clears it again
    r = await client.send_json("PUT", f"/api/settings/admin/people/{row['id']}", _body(row, branch_id=None))
    assert r.status_code == 200, r.text
    person = await db.get(Person, uuid.UUID(row["id"]), populate_existing=True)
    assert person is not None and person.branch_id is None


async def test_71_branch_only_for_a_personal_account_person(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    branch, _, people = await senica(db)
    branch_id = branch.id
    other = await make_personal(db, email="eshop@smartsro.sk")
    jana = people["jana"]
    jana_id = jana.id
    body = {"first_name": "Jana", "last_name": "Nováková", "role": "sales", "branch_id": None}
    r = await client.send_json("PUT", f"/api/settings/admin/people/{jana.id}", body)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "branch_only_for_personal_account"
    r = await client.send_json(
        "PUT",
        f"/api/settings/admin/people/{other.person_id}",
        {"first_name": "Eshop", "last_name": "Smart", "role": "sales", "branch_id": str(uuid.uuid4())},
    )
    assert r.status_code == 404 and r.json()["detail"]["code"] == "branch_not_found"
    # without branch_id the field stays as it is (older clients)
    r = await client.send_json(
        "PUT", f"/api/settings/admin/people/{jana.id}", {"first_name": "Jana", "last_name": "N.", "role": "sales"}
    )
    assert r.status_code == 200
    saved = await db.get(Person, jana_id, populate_existing=True)
    assert saved is not None and saved.branch_id == branch_id


def test_71_identity_signature_wins_outside_the_branch_mailbox() -> None:
    from app.auth.models import Branch

    branch_mailbox, eshop_mailbox = uuid.uuid4(), uuid.uuid4()
    branch = Branch(name="Senica", address=ADDRESS, mailbox_id=branch_mailbox, signature_template_html=TEMPLATE)
    person = Person(first_name="Eshop", last_name="Smart", role=Role.sales)
    own = Identity(mailbox_id=eshop_mailbox, signature_html={"sk": "<p>Vlastný {adresa_pobocky}</p>"})
    assert render_signature(person=person, branch=branch, identity=own, email="eshop@smartsro.sk") == (
        f"<p>Vlastný {ADDRESS}</p>"
    )
    # on the branch mailbox the branch template still rules
    on_branch = Identity(mailbox_id=branch_mailbox, signature_html={"sk": "<p>Starý</p>"})
    assert "Senica" in render_signature(person=person, branch=branch, identity=on_branch, email="x@smartsro.sk")
