"""Issue #55 (Settings 11 Pobočky a osoby, Figma W12-11a/b/d): person photo, branch logo, „Pôsobí aj na pobočkách“,
the last active person rule on the Aktívna switch, „Vymazať pobočku“ (only an empty branch) and branch folders."""

from __future__ import annotations

import io
import uuid
from typing import Any

import httpx
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Account, AccountKind, Branch, Person, PersonBranch, Role
from app.auth.persons import eligible_persons
from app.core.audit import AuditLog
from app.mail.models import FolderMeta, Mailbox
from app.mail.signature import LOGO_CID, PHOTO_CID, preview_signature_html
from tests.conftest import Client, FakeMailServer, make_branch, make_personal
from tests.test_persons_1b import senica

PASSWORD = "Spravne-Heslo-1"


def _png(width: int, height: int, color: str = "red") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), color).save(out, format="PNG")
    return out.getvalue()


async def _admin(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    acc = await make_personal(db, email="admin@smartsro.sk", role=Role.admin)
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200


async def _upload(client: Client, url: str, name: str, data: bytes, ctype: str = "image/png") -> httpx.Response:
    await client.csrf()
    return await client.post(
        url, files={"file": (name, data, ctype)}, headers={"X-CSRF-Token": client.cookies["sm_csrf"]}
    )


async def _actions(db: AsyncSession) -> list[str]:
    return list((await db.execute(select(AuditLog.action).execution_options(populate_existing=True))).scalars())


def _person_body(p: Person, **changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "first_name": p.first_name,
        "last_name": p.last_name,
        "function": p.function,
        "role": p.role.value,
        "is_manager": p.is_manager,
        "active": True,
    }
    body.update(changes)
    return body


async def test_55_person_photo_is_cropped_square_and_served(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    _, _, people = await senica(db)
    jana_id = people["jana"].id
    r = await _upload(client, f"/api/settings/admin/people/{jana_id}/photo", "jana.png", _png(400, 200))
    assert r.status_code == 200, r.text
    served = await client.get(r.json()["photo_url"])
    assert served.status_code == 200 and served.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(served.content)) as image:
        assert image.size == (256, 256)
    branch_rows = (await client.get("/api/settings/admin/branches")).json()
    row = next(p for b in branch_rows for p in b["people"] if p["id"] == str(jana_id))
    assert row["photo_url"].startswith(f"/api/settings/people/{jana_id}/photo")
    assert "settings.person_photo_saved" in await _actions(db)

    bad = await _upload(client, f"/api/settings/admin/people/{jana_id}/photo", "x.txt", b"not an image", "text/plain")
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "image_type"
    gone = await client.send_json("DELETE", f"/api/settings/admin/people/{jana_id}/photo")
    assert gone.status_code == 200
    assert (await client.get(f"/api/settings/people/{jana_id}/photo")).status_code == 404


async def test_55_photo_and_logo_need_an_admin(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    acc = await make_personal(db, email="jana@smartsro.sk", role=Role.sales)
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200
    branch, _ = await make_branch(db, "Trnava")
    r = await _upload(client, f"/api/settings/admin/people/{acc.person_id}/photo", "a.png", _png(10, 10))
    assert r.status_code == 403
    r = await _upload(client, f"/api/settings/admin/branches/{branch.id}/logo", "a.png", _png(10, 10))
    assert r.status_code == 403


async def test_55_branch_logo_fills_the_logo_variable(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    branch, _ = await make_branch(db, "Nitra")
    branch_id = branch.id
    r = await _upload(client, f"/api/settings/admin/branches/{branch_id}/logo", "logo.png", _png(96, 33, "blue"))
    assert r.status_code == 200, r.text
    served = await client.get(r.json()["logo_url"])
    assert served.status_code == 200 and served.headers["content-type"] == "image/png"
    too_big = await _upload(
        client, f"/api/settings/admin/branches/{branch_id}/logo", "big.png", b"\x89PNG" + b"0" * 300_000
    )
    assert too_big.status_code == 422 and too_big.json()["detail"]["code"] == "image_too_large"

    saved = await db.get(Branch, branch_id, populate_existing=True)
    assert saved is not None and saved.logo_key
    saved.signature_template_html = {"sk": "<p>{logo} {fotka}</p>"}
    person = Person(first_name="Jana", last_name="Nováková", role=Role.sales, photo_key="person-photos/x")
    person.id = uuid.uuid4()
    html = preview_signature_html(person=person, branch=saved, identity=None, email="nitra@smartsro.sk")
    assert f"/api/settings/branches/{branch_id}/logo" in html and f"cid:{LOGO_CID}" not in html
    assert f"/api/settings/people/{person.id}/photo" in html and f"cid:{PHOTO_CID}" not in html


async def test_55_person_covers_other_branches(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await _admin(client, db, mail_server)
    _, _, people = await senica(db)
    trnava, trnava_login = await make_branch(db, "Trnava", people=1)
    trnava_id = trnava.id
    jana = people["jana"]
    jana_id = jana.id
    r = await client.send_json(
        "PUT", f"/api/settings/admin/people/{jana_id}", _person_body(jana, cover_branch_ids=[str(trnava_id)])
    )
    assert r.status_code == 200, r.text
    assert jana_id in {p.id for p in await eligible_persons(db, trnava_login)}
    row = next(
        p
        for b in (await client.get("/api/settings/admin/branches")).json()
        for p in b["people"]
        if p["id"] == str(jana_id)
    )
    assert row["cover_branch_ids"] == [str(trnava_id)]
    audit_row = (
        await db.execute(
            select(AuditLog).where(AuditLog.action == "settings.person_saved").execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert audit_row.details["before"]["cover_branch_ids"] == []
    assert audit_row.details["after"]["cover_branch_ids"] == [str(trnava_id)]

    # omitted = unchanged; unknown branch = 404; [] removes
    r = await client.send_json("PUT", f"/api/settings/admin/people/{jana_id}", _person_body(jana, function="obchod"))
    assert r.status_code == 200
    covers = (await db.execute(select(PersonBranch.branch_id).where(PersonBranch.person_id == jana_id))).scalars()
    assert list(covers) == [trnava_id]
    r = await client.send_json(
        "PUT", f"/api/settings/admin/people/{jana_id}", _person_body(jana, cover_branch_ids=[str(uuid.uuid4())])
    )
    assert r.status_code == 404
    r = await client.send_json("PUT", f"/api/settings/admin/people/{jana_id}", _person_body(jana, cover_branch_ids=[]))
    assert r.status_code == 200
    assert jana_id not in {p.id for p in await eligible_persons(db, trnava_login)}


async def test_55_aktivna_switch_keeps_one_active_person(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    branch, _ = await make_branch(db, "Trnava", people=1)
    only = (await db.execute(select(Person).where(Person.branch_id == branch.id))).scalar_one()
    r = await client.send_json("PUT", f"/api/settings/admin/people/{only.id}", _person_body(only, active=False))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "last_active_person"


async def test_55_only_an_empty_branch_can_be_deleted(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    busy, _ = await make_branch(db, "Senica", people=1)
    r = await client.send_json("DELETE", f"/api/settings/admin/branches/{busy.id}")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "branch_has_people"

    with_login = Branch(name="Trenčín")
    db.add(with_login)
    await db.flush()
    db.add(Account(email="trencin@smartsro.sk", kind=AccountKind.branch, branch_id=with_login.id))
    await db.commit()
    r = await client.send_json("DELETE", f"/api/settings/admin/branches/{with_login.id}")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "branch_has_login"

    empty = Branch(name="Pobočka Prázdna")
    db.add(empty)
    await db.flush()
    former = Person(branch_id=empty.id, first_name="Bývalý", last_name="Kolega", role=Role.sales, active=False)
    db.add(former)
    await db.commit()
    empty_id, former_id = empty.id, former.id
    r = await client.send_json("DELETE", f"/api/settings/admin/branches/{empty_id}")
    assert r.status_code == 200, r.text
    assert await db.get(Branch, empty_id, populate_existing=True) is None
    kept = await db.get(Person, former_id, populate_existing=True)
    assert kept is not None and kept.branch_id is None  # history keeps the name
    assert "settings.branch_deleted" in await _actions(db)


async def test_55_branch_folders_lists_own_folders(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    mailbox = (await db.execute(select(Mailbox).where(Mailbox.email == "admin@smartsro.sk"))).scalar_one()
    db.add_all(
        [
            FolderMeta(mailbox_id=mailbox.id, name="Senica"),
            FolderMeta(mailbox_id=mailbox.id, name="Odoslané", special_use="sent"),
        ]
    )
    await db.commit()
    rows = (await client.get("/api/settings/admin/branch-folders")).json()
    names = {r["name"] for r in rows}
    assert "Senica" in names and "Odoslané" not in names
    assert all(r["mailbox_email"] == "admin@smartsro.sk" for r in rows)
