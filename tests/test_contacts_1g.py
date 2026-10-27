"""Phase 1g contacts API: books, CRUD, groups, vCard import/export, autocomplete."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Account, AccountKind, Person, Role
from app.contacts.models import Contact
from app.mail.models import Mailbox
from tests.conftest import Client, FakeMailServer, make_personal
from tests.test_mail_sync_1c import PASSWORD

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contacts"


async def _signed_in(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> Account:
    acc = await make_personal(db)
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200
    return acc


@pytest.mark.asyncio
async def test_1g_books_personal_and_shared(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await _signed_in(client, db, mail_server)
    r = await client.get("/api/contacts/books")
    assert r.status_code == 200, r.text
    kinds = {b["kind"] for b in r.json()}
    assert kinds == {"personal", "shared"}


@pytest.mark.asyncio
async def test_1g_contact_crud_and_group(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await _signed_in(client, db, mail_server)
    books = (await client.get("/api/contacts/books")).json()
    personal = next(b for b in books if b["kind"] == "personal")
    g = await client.send_json("POST", f"/api/contacts/books/{personal['id']}/groups", {"name": "Dodávatelia"})
    assert g.status_code == 201
    created = await client.send_json(
        "POST",
        f"/api/contacts/books/{personal['id']}/contacts",
        {
            "display_name": "Ján Test",
            "emails": [{"email": "jan.test@smartmail.test", "primary": True}],
            "phones": [{"phone": "+421900000001", "label": "cell"}],
            "group_ids": [g.json()["id"]],
        },
    )
    assert created.status_code == 201, created.text
    cid = created.json()["id"]
    assert created.json()["group_ids"] == [g.json()["id"]]
    listed = await client.get(f"/api/contacts/books/{personal['id']}/contacts")
    assert any(c["id"] == cid for c in listed.json())
    deleted = await client.send_json("DELETE", f"/api/contacts/contacts/{cid}")
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_1g_vcard_import_skip_and_merge(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await _signed_in(client, db, mail_server)
    books = (await client.get("/api/contacts/books")).json()
    personal = next(b for b in books if b["kind"] == "personal")
    book_id = personal["id"]
    await client.csrf()
    data = (FIXTURES / "roundcube_export.vcf").read_bytes()
    imp = await client.post(
        f"/api/contacts/books/{book_id}/import",
        files={"file": ("roundcube_export.vcf", data, "text/vcard")},
        data={"on_duplicate": "skip"},
        headers={"X-CSRF-Token": client.cookies["sm_csrf"]},
    )
    assert imp.status_code == 200, imp.text
    assert imp.json()["created"] == 3
    # skip duplicate
    dup = (FIXTURES / "duplicate_jan.vcf").read_bytes()
    skip = await client.post(
        f"/api/contacts/books/{book_id}/import",
        files={"file": ("duplicate_jan.vcf", dup, "text/vcard")},
        data={"on_duplicate": "skip"},
        headers={"X-CSRF-Token": client.cookies["sm_csrf"]},
    )
    assert skip.json()["skipped"] == 1
    merge = await client.post(
        f"/api/contacts/books/{book_id}/import",
        files={"file": ("duplicate_jan.vcf", dup, "text/vcard")},
        data={"on_duplicate": "merge"},
        headers={"X-CSRF-Token": client.cookies["sm_csrf"]},
    )
    assert merge.json()["merged"] == 1
    contacts = (await client.get(f"/api/contacts/books/{book_id}/contacts")).json()
    jan = next(c for c in contacts if any(e.get("email") == "jan.novak@smartmail.test" for e in c["emails"]))
    emails = {e["email"] for e in jan["emails"]}
    assert "jan.extra@smartmail.test" in emails
    export = await client.get(f"/api/contacts/books/{book_id}/export")
    assert export.status_code == 200
    assert "BEGIN:VCARD" in export.text
    assert "@smartmail.test" in export.text


@pytest.mark.asyncio
async def test_1g_vcard_bad_file_422(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await _signed_in(client, db, mail_server)
    books = (await client.get("/api/contacts/books")).json()
    book_id = books[0]["id"]
    await client.csrf()
    bad = (FIXTURES / "bad_file.vcf").read_bytes()
    r = await client.post(
        f"/api/contacts/books/{book_id}/import",
        files={"file": ("bad.vcf", bad, "text/plain")},
        data={"on_duplicate": "skip"},
        headers={"X-CSRF-Token": client.cookies["sm_csrf"]},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "invalid_vcard"


@pytest.mark.asyncio
async def test_1g_autocomplete_from_contacts(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await _signed_in(client, db, mail_server)
    books = (await client.get("/api/contacts/books")).json()
    personal = next(b for b in books if b["kind"] == "personal")
    await client.send_json(
        "POST",
        f"/api/contacts/books/{personal['id']}/contacts",
        {
            "display_name": "Mária Čéna",
            "emails": [{"email": "maria.cena@smartmail.test", "primary": True}],
        },
    )
    r = await client.get("/api/contacts/autocomplete", params={"q": "maria"})
    assert r.status_code == 200
    assert any(row["email"] == "maria.cena@smartmail.test" for row in r.json())


@pytest.mark.asyncio
async def test_1g_cannot_read_other_persons_personal_book(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, new_client
) -> None:
    await _signed_in(client, db, mail_server)
    books = (await client.get("/api/contacts/books")).json()
    personal = next(b for b in books if b["kind"] == "personal")
    await client.send_json(
        "POST",
        f"/api/contacts/books/{personal['id']}/contacts",
        {"display_name": "Tajný", "emails": [{"email": "tajny@smartmail.test"}]},
    )
    other = Person(first_name="Iný", last_name="Človek", role=Role.sales)
    db.add(other)
    await db.flush()
    acc2 = Account(email="iny@smartmail.test", kind=AccountKind.personal, person_id=other.id)
    db.add(acc2)
    await db.commit()
    mail_server.passwords[acc2.email] = PASSWORD
    c2 = new_client()
    async with c2:
        assert (await c2.login(acc2.email, PASSWORD)).status_code == 200
        denied = await c2.get(f"/api/contacts/books/{personal['id']}/contacts")
        assert denied.status_code == 404


@pytest.mark.asyncio
async def test_1g_contacts_never_touch_imap_tables_only(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    """Sanity: creating a contact does not create IMAP-related rows beyond the login mailbox."""
    await _signed_in(client, db, mail_server)
    before = (await db.execute(select(Mailbox))).scalars().all()
    books = (await client.get("/api/contacts/books")).json()
    personal = next(b for b in books if b["kind"] == "personal")
    await client.send_json(
        "POST",
        f"/api/contacts/books/{personal['id']}/contacts",
        {"display_name": "Len DB", "emails": [{"email": "len.db@smartmail.test"}]},
    )
    after = (await db.execute(select(Mailbox))).scalars().all()
    assert len(after) == len(before)
    assert await db.scalar(select(Contact).where(Contact.display_name == "Len DB")) is not None
