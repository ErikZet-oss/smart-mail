"""Contacts API — local address books, groups, vCard, autocomplete (SCREENS_SPEC W9; ADR-009)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import String, func, or_, select

from app.auth.deps import DB, ActivePerson, Auth
from app.contacts import service
from app.contacts.models import Contact, ContactGroup, ContactGroupMember

router = APIRouter(prefix="/api/contacts", tags=["contacts"])


class BookOut(BaseModel):
    id: str
    kind: str
    name: str


class ContactIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    first_name: str | None = Field(default=None, max_length=80)
    last_name: str | None = Field(default=None, max_length=80)
    organization: str | None = Field(default=None, max_length=200)
    notes: str | None = None
    emails: list[dict[str, Any]] = Field(default_factory=list)
    phones: list[dict[str, Any]] = Field(default_factory=list)
    group_ids: list[uuid.UUID] = Field(default_factory=list)


class ContactOut(BaseModel):
    id: str
    address_book_id: str
    display_name: str
    first_name: str | None
    last_name: str | None
    organization: str | None
    notes: str | None
    emails: list[dict[str, Any]]
    phones: list[dict[str, Any]]
    group_ids: list[str] = []


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class GroupOut(BaseModel):
    id: str
    address_book_id: str
    name: str


class ImportOut(BaseModel):
    created: int
    merged: int
    skipped: int


def _fail(status: int, code: str, **extra: object) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, **extra})


def _contact_out(c: Contact, group_ids: list[str] | None = None) -> ContactOut:
    return ContactOut(
        id=str(c.id),
        address_book_id=str(c.address_book_id),
        display_name=c.display_name,
        first_name=c.first_name,
        last_name=c.last_name,
        organization=c.organization,
        notes=c.notes,
        emails=list(c.emails or []),
        phones=list(c.phones or []),
        group_ids=group_ids or [],
    )


async def _group_ids(db: DB, contact_id: uuid.UUID) -> list[str]:
    rows = await db.execute(select(ContactGroupMember.group_id).where(ContactGroupMember.contact_id == contact_id))
    return [str(g) for g in rows.scalars()]


@router.get("/books")
async def list_books(ctx: Auth, person: ActivePerson, db: DB) -> list[BookOut]:
    books = await service.list_books(db, person.id)
    await db.commit()
    return [BookOut(id=str(b.id), kind=b.kind, name=b.name) for b in books]


@router.get("/books/{book_id}/contacts")
async def list_contacts(
    book_id: uuid.UUID,
    ctx: Auth,
    person: ActivePerson,
    db: DB,
    q: str | None = None,
) -> list[ContactOut]:
    book = await service.get_book(db, book_id, person.id)
    if book is None:
        raise _fail(404, "book_not_found")
    stmt = select(Contact).where(Contact.address_book_id == book.id).order_by(Contact.display_name)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Contact.display_name.ilike(pattern),
                Contact.first_name.ilike(pattern),
                Contact.last_name.ilike(pattern),
                Contact.organization.ilike(pattern),
                func.cast(Contact.emails, String).ilike(pattern),
            )
        )
    contacts = list((await db.execute(stmt)).scalars())
    out: list[ContactOut] = []
    for c in contacts:
        out.append(_contact_out(c, await _group_ids(db, c.id)))
    return out


@router.post("/books/{book_id}/contacts", status_code=201)
async def create_contact(book_id: uuid.UUID, body: ContactIn, ctx: Auth, person: ActivePerson, db: DB) -> ContactOut:
    book = await service.get_book(db, book_id, person.id)
    if book is None:
        raise _fail(404, "book_not_found")
    c = Contact(
        address_book_id=book.id,
        display_name=body.display_name.strip(),
        first_name=body.first_name,
        last_name=body.last_name,
        organization=body.organization,
        notes=body.notes,
        emails=body.emails,
        phones=body.phones,
    )
    db.add(c)
    await db.flush()
    for gid in body.group_ids:
        g = await db.get(ContactGroup, gid)
        if g is None or g.address_book_id != book.id:
            raise _fail(400, "group_not_found", group_id=str(gid))
        db.add(ContactGroupMember(contact_id=c.id, group_id=gid))
    await db.commit()
    await db.refresh(c)
    return _contact_out(c, [str(g) for g in body.group_ids])


@router.get("/contacts/{contact_id}")
async def get_contact(contact_id: uuid.UUID, ctx: Auth, person: ActivePerson, db: DB) -> ContactOut:
    c = await db.get(Contact, contact_id)
    if c is None:
        raise _fail(404, "contact_not_found")
    book = await service.get_book(db, c.address_book_id, person.id)
    if book is None:
        raise _fail(404, "contact_not_found")
    return _contact_out(c, await _group_ids(db, c.id))


@router.patch("/contacts/{contact_id}")
async def patch_contact(contact_id: uuid.UUID, body: ContactIn, ctx: Auth, person: ActivePerson, db: DB) -> ContactOut:
    c = await db.get(Contact, contact_id)
    if c is None:
        raise _fail(404, "contact_not_found")
    book = await service.get_book(db, c.address_book_id, person.id)
    if book is None:
        raise _fail(404, "contact_not_found")
    c.display_name = body.display_name.strip()
    c.first_name = body.first_name
    c.last_name = body.last_name
    c.organization = body.organization
    c.notes = body.notes
    c.emails = body.emails
    c.phones = body.phones
    existing = list(
        (await db.execute(select(ContactGroupMember).where(ContactGroupMember.contact_id == c.id))).scalars()
    )
    for m in existing:
        await db.delete(m)
    for gid in body.group_ids:
        g = await db.get(ContactGroup, gid)
        if g is None or g.address_book_id != book.id:
            raise _fail(400, "group_not_found", group_id=str(gid))
        db.add(ContactGroupMember(contact_id=c.id, group_id=gid))
    await db.commit()
    await db.refresh(c)
    return _contact_out(c, [str(g) for g in body.group_ids])


@router.delete("/contacts/{contact_id}", status_code=204)
async def delete_contact(contact_id: uuid.UUID, ctx: Auth, person: ActivePerson, db: DB) -> None:
    c = await db.get(Contact, contact_id)
    if c is None:
        raise _fail(404, "contact_not_found")
    book = await service.get_book(db, c.address_book_id, person.id)
    if book is None:
        raise _fail(404, "contact_not_found")
    await db.delete(c)
    await db.commit()


@router.get("/books/{book_id}/groups")
async def list_groups(book_id: uuid.UUID, ctx: Auth, person: ActivePerson, db: DB) -> list[GroupOut]:
    book = await service.get_book(db, book_id, person.id)
    if book is None:
        raise _fail(404, "book_not_found")
    groups = list(
        (
            await db.execute(
                select(ContactGroup).where(ContactGroup.address_book_id == book.id).order_by(ContactGroup.name)
            )
        ).scalars()
    )
    return [GroupOut(id=str(g.id), address_book_id=str(g.address_book_id), name=g.name) for g in groups]


@router.post("/books/{book_id}/groups", status_code=201)
async def create_group(book_id: uuid.UUID, body: GroupIn, ctx: Auth, person: ActivePerson, db: DB) -> GroupOut:
    book = await service.get_book(db, book_id, person.id)
    if book is None:
        raise _fail(404, "book_not_found")
    g = ContactGroup(address_book_id=book.id, name=body.name.strip())
    db.add(g)
    await db.commit()
    await db.refresh(g)
    return GroupOut(id=str(g.id), address_book_id=str(g.address_book_id), name=g.name)


@router.delete("/groups/{group_id}", status_code=204)
async def delete_group(group_id: uuid.UUID, ctx: Auth, person: ActivePerson, db: DB) -> None:
    g = await db.get(ContactGroup, group_id)
    if g is None:
        raise _fail(404, "group_not_found")
    book = await service.get_book(db, g.address_book_id, person.id)
    if book is None:
        raise _fail(404, "group_not_found")
    await db.delete(g)
    await db.commit()


@router.post("/books/{book_id}/import")
async def import_vcard(
    book_id: uuid.UUID,
    ctx: Auth,
    person: ActivePerson,
    db: DB,
    file: Annotated[UploadFile, File()],
    on_duplicate: Annotated[Literal["merge", "skip"], Form()] = "skip",
) -> ImportOut:
    book = await service.get_book(db, book_id, person.id)
    if book is None:
        raise _fail(404, "book_not_found")
    raw = (await file.read()).decode("utf-8", errors="replace")
    try:
        stats = await service.import_vcard(db, book, raw, on_duplicate=on_duplicate)
    except ValueError as exc:
        raise _fail(422, "invalid_vcard", reason=str(exc)) from exc
    await db.commit()
    return ImportOut(**stats)


@router.get("/books/{book_id}/export")
async def export_vcard(book_id: uuid.UUID, ctx: Auth, person: ActivePerson, db: DB) -> PlainTextResponse:
    book = await service.get_book(db, book_id, person.id)
    if book is None:
        raise _fail(404, "book_not_found")
    text = await service.export_vcard(db, book.id)
    return PlainTextResponse(
        text,
        media_type="text/vcard; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="contacts.vcf"'},
    )


@router.get("/autocomplete")
async def autocomplete(
    ctx: Auth,
    person: ActivePerson,
    db: DB,
    q: Annotated[str, Query(min_length=1, max_length=120)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[dict[str, str | None]]:
    await service.ensure_default_books(db, person.id)
    rows = await service.autocomplete(db, person.id, q, limit=limit)
    await db.commit()
    return rows
