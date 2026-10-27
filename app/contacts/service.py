"""Contact books CRUD, vCard import/export, autocomplete (ADR-009)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from sqlalchemy import String, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contacts.models import AddressBook, Contact, RecentRecipient
from app.contacts.vcard import ParsedContact, VCardError, parse_vcards, serialize_vcards

DuplicateMode = Literal["merge", "skip"]


async def ensure_default_books(db: AsyncSession, person_id: uuid.UUID) -> tuple[AddressBook, AddressBook]:
    """Osobné adresy for the person + shared company book (create once)."""
    personal = (
        await db.execute(
            select(AddressBook).where(AddressBook.kind == "personal", AddressBook.owner_person_id == person_id)
        )
    ).scalar_one_or_none()
    if personal is None:
        personal = AddressBook(kind="personal", name="Osobné adresy", owner_person_id=person_id)
        db.add(personal)
        await db.flush()
    shared = (await db.execute(select(AddressBook).where(AddressBook.kind == "shared"))).scalar_one_or_none()
    if shared is None:
        shared = AddressBook(kind="shared", name="Zdieľané", owner_person_id=None)
        db.add(shared)
        await db.flush()
    return personal, shared


async def list_books(db: AsyncSession, person_id: uuid.UUID) -> list[AddressBook]:
    personal, shared = await ensure_default_books(db, person_id)
    return [personal, shared]


async def get_book(db: AsyncSession, book_id: uuid.UUID, person_id: uuid.UUID) -> AddressBook | None:
    book = await db.get(AddressBook, book_id)
    if book is None:
        return None
    if book.kind == "personal" and book.owner_person_id != person_id:
        return None
    if book.kind in ("personal", "shared"):
        return book
    return None


def _emails_lower(emails: list[dict[str, Any]]) -> set[str]:
    return {str(e.get("email") or "").lower() for e in emails if e.get("email")}


async def find_by_emails(db: AsyncSession, book_id: uuid.UUID, emails: set[str]) -> Contact | None:
    if not emails:
        return None
    rows = (await db.execute(select(Contact).where(Contact.address_book_id == book_id))).scalars()
    for c in rows:
        if _emails_lower(c.emails) & emails:
            return c
    return None


def contact_to_parsed(c: Contact) -> ParsedContact:
    return ParsedContact(
        display_name=c.display_name,
        first_name=c.first_name,
        last_name=c.last_name,
        organization=c.organization,
        notes=c.notes,
        emails=list(c.emails or []),
        phones=list(c.phones or []),
    )


def apply_parsed(c: Contact, parsed: ParsedContact, *, merge: bool) -> None:
    if not merge or not c.display_name:
        c.display_name = parsed.display_name or c.display_name
    if parsed.first_name:
        c.first_name = parsed.first_name
    if parsed.last_name:
        c.last_name = parsed.last_name
    if parsed.organization:
        c.organization = parsed.organization
    if parsed.notes:
        c.notes = parsed.notes
    if merge:
        known = _emails_lower(c.emails)
        emails = list(c.emails or [])
        for em in parsed.emails:
            if str(em.get("email") or "").lower() not in known:
                emails.append(em)
        c.emails = emails
        known_ph = {str(p.get("phone") or "") for p in (c.phones or [])}
        phones = list(c.phones or [])
        for ph in parsed.phones:
            if str(ph.get("phone") or "") not in known_ph:
                phones.append(ph)
        c.phones = phones
    else:
        c.emails = list(parsed.emails)
        c.phones = list(parsed.phones)


async def import_vcard(
    db: AsyncSession,
    book: AddressBook,
    text: str,
    *,
    on_duplicate: DuplicateMode = "skip",
) -> dict[str, int]:
    try:
        parsed_list = parse_vcards(text)
    except VCardError as exc:
        raise ValueError(str(exc)) from exc
    created = merged = skipped = 0
    for parsed in parsed_list:
        emails = _emails_lower(parsed.emails)
        existing = await find_by_emails(db, book.id, emails) if emails else None
        if existing is None:
            db.add(
                Contact(
                    address_book_id=book.id,
                    display_name=parsed.display_name or "Kontakt",
                    first_name=parsed.first_name,
                    last_name=parsed.last_name,
                    organization=parsed.organization,
                    notes=parsed.notes,
                    emails=list(parsed.emails),
                    phones=list(parsed.phones),
                )
            )
            created += 1
            continue
        if on_duplicate == "skip":
            skipped += 1
            continue
        apply_parsed(existing, parsed, merge=True)
        merged += 1
    await db.flush()
    return {"created": created, "merged": merged, "skipped": skipped}


async def export_vcard(db: AsyncSession, book_id: uuid.UUID) -> str:
    rows = list(
        (
            await db.execute(select(Contact).where(Contact.address_book_id == book_id).order_by(Contact.display_name))
        ).scalars()
    )
    return serialize_vcards([contact_to_parsed(c) for c in rows])


async def autocomplete(
    db: AsyncSession, person_id: uuid.UUID, q: str, *, limit: int = 20
) -> list[dict[str, str | None]]:
    q = q.strip()
    if len(q) < 1:
        return []
    personal, shared = await ensure_default_books(db, person_id)
    book_ids = [personal.id, shared.id]
    pattern = f"%{q}%"
    ql = q.lower()
    contacts = list(
        (
            await db.execute(
                select(Contact)
                .where(
                    Contact.address_book_id.in_(book_ids),
                    or_(
                        Contact.display_name.ilike(pattern),
                        Contact.first_name.ilike(pattern),
                        Contact.last_name.ilike(pattern),
                        Contact.organization.ilike(pattern),
                        func.cast(Contact.emails, String).ilike(pattern),
                    ),
                )
                .limit(limit * 2)
            )
        ).scalars()
    )
    out: list[dict[str, str | None]] = []
    for c in contacts:
        name_hit = any(ql in (x or "").lower() for x in (c.display_name, c.first_name, c.last_name, c.organization))
        emails = list(c.emails or []) or [{"email": None}]
        for em in emails:
            email = str(em.get("email") or "") or None
            if email and ql not in email.lower() and not name_hit:
                continue
            if not email and not name_hit:
                continue
            out.append({"name": c.display_name, "email": email, "source": "contact"})
            if len(out) >= limit:
                return out
    recent = list(
        (
            await db.execute(
                select(RecentRecipient)
                .where(
                    RecentRecipient.person_id == person_id,
                    or_(RecentRecipient.email.ilike(pattern), RecentRecipient.name.ilike(pattern)),
                )
                .order_by(RecentRecipient.use_count.desc())
                .limit(limit)
            )
        ).scalars()
    )
    seen = {o["email"] for o in out if o.get("email")}
    for r in recent:
        if r.email in seen:
            continue
        out.append({"name": r.name, "email": r.email, "source": "recent"})
        if len(out) >= limit:
            break
    return out
