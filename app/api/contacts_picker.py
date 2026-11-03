"""W4g / M4b Adresár – výber príjemcov (#203): read-only sources next to the personal / shared books.

- Naposledy použité: recipients of the active person's sent messages (90 days, max 50, newest first) — from
  `compose_drafts` (status sent), no new table.
- Pobočky: the branch mailboxes.
- Money – adresár: the read cache (`money_persons`, `money_companies`) — never a live bridge call, never a write;
  a search of ≥ 2 characters is required and the result is paged.
Same access as `/api/contacts/autocomplete` (signed-in person; viewer may read). Addresses are never logged.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import String, func, or_, select

from app.auth.deps import DB, Auth, SignedInPerson
from app.auth.models import Branch
from app.contacts import service
from app.contacts.models import Contact
from app.mail.compose_models import ComposeDraft
from app.mail.models import Mailbox
from app.money.models import MoneyCompany, MoneyPerson

router = APIRouter(prefix="/api/contacts/picker", tags=["contacts"])

RECENT_DAYS = 90
RECENT_MAX = 50
MONEY_PAGE = 50


class PickEntry(BaseModel):
    key: str  # stable row key (lower-cased e-mail; a contact with 2 e-mails gives 2 rows)
    name: str
    email: str
    organization: str | None = None


class MoneyPage(BaseModel):
    items: list[PickEntry]
    total: int
    page: int


class Summary(BaseModel):
    recent: int
    personal: int
    shared: int
    branches: int
    money: int


def _addr(item: Any) -> tuple[str, str] | None:
    if not isinstance(item, dict):
        return None
    email = str(item.get("email") or item.get("address") or "").strip()
    if "@" not in email:
        return None
    return email, str(item.get("name") or "").strip()


async def _recent(db: DB, person_id: Any) -> list[PickEntry]:
    since = datetime.now(UTC) - timedelta(days=RECENT_DAYS)
    drafts = await db.scalars(
        select(ComposeDraft)
        .where(
            ComposeDraft.person_id == person_id,
            ComposeDraft.status == "sent",
            ComposeDraft.updated_at >= since,
        )
        .order_by(ComposeDraft.updated_at.desc())
        .limit(500)
    )
    seen: dict[str, PickEntry] = {}
    for d in drafts:
        for item in [*(d.to_addrs or []), *(d.cc_addrs or []), *(d.bcc_addrs or [])]:
            got = _addr(item)
            if got is None:
                continue
            email, name = got
            key = email.lower()
            if key not in seen:
                seen[key] = PickEntry(key=key, name=name or email, email=email)
            if len(seen) >= RECENT_MAX:
                return list(seen.values())
    return list(seen.values())


async def _branches(db: DB) -> list[PickEntry]:
    rows = (
        await db.execute(
            select(Branch.name, Mailbox.email).join(Mailbox, Mailbox.id == Branch.mailbox_id).order_by(Branch.name)
        )
    ).all()
    return [PickEntry(key=email.lower(), name=name, email=email, organization=None) for name, email in rows]


def _money_queries(q: str) -> tuple[Any, Any]:
    like = f"%{q.replace('%', '').replace('_', '')}%"
    persons = (
        select(MoneyPerson, MoneyCompany.name)
        .outerjoin(MoneyCompany, MoneyCompany.money_id == MoneyPerson.company_money_id)
        .where(MoneyPerson.active.is_(True), MoneyPerson.email.is_not(None), MoneyPerson.email != "")
    )
    companies = select(MoneyCompany).where(
        MoneyCompany.active.is_(True),
        or_(MoneyCompany.email.is_not(None), func.cardinality(MoneyCompany.emails) > 0),
    )
    if q:
        persons = persons.where(
            or_(
                MoneyPerson.name.ilike(like),
                MoneyPerson.first_name.ilike(like),
                MoneyPerson.last_name.ilike(like),
                MoneyPerson.email.ilike(like),
                MoneyCompany.name.ilike(like),
            )
        )
        companies = companies.where(
            or_(
                MoneyCompany.name.ilike(like),
                MoneyCompany.email.ilike(like),
                func.array_to_string(MoneyCompany.emails, " ").ilike(like),
            )
        )
    return persons, companies


def _person_name(p: MoneyPerson) -> str:
    return p.name or " ".join(x for x in (p.first_name, p.last_name) if x) or (p.email or "")


async def _money_all(db: DB, q: str) -> list[PickEntry]:
    persons_q, companies_q = _money_queries(q)
    out: dict[str, PickEntry] = {}
    for p, company in (await db.execute(persons_q)).all():
        email = (p.email or "").strip()
        out.setdefault(
            email.lower(), PickEntry(key=email.lower(), name=_person_name(p), email=email, organization=company)
        )
    for c in await db.scalars(companies_q):
        for email in dict.fromkeys([e for e in [c.email, *(c.emails or [])] if e and "@" in e]):
            out.setdefault(email.lower(), PickEntry(key=email.lower(), name=c.name, email=email, organization=c.name))
    return sorted(out.values(), key=lambda e: (e.name.lower(), e.email.lower()))


async def _money_count(db: DB) -> int:
    """Rows = distinct e-mail addresses, the same rows the search lists (a company with 2 e-mails = 2 rows)."""
    return len(await _money_all(db, ""))


async def _book_count(db: DB, book_id: Any) -> int:
    """Rows = e-mail addresses (a contact with 2 e-mails is 2 rows, SCREENS_SPEC W4g)."""
    count = await db.scalar(
        select(func.coalesce(func.sum(func.jsonb_array_length(Contact.emails)), 0)).where(
            Contact.address_book_id == book_id, func.cast(Contact.emails, String) != "[]"
        )
    )
    return int(count or 0)


@router.get("/summary")
async def summary(ctx: Auth, person: SignedInPerson, db: DB) -> Summary:
    """Counts for the left column „ADRESÁRE“."""
    personal, shared = await service.ensure_default_books(db, person.id)
    await db.commit()
    return Summary(
        recent=len(await _recent(db, person.id)),
        personal=await _book_count(db, personal.id),
        shared=await _book_count(db, shared.id),
        branches=len(await _branches(db)),
        money=await _money_count(db),
    )


@router.get("/recent")
async def recent(ctx: Auth, person: SignedInPerson, db: DB) -> list[PickEntry]:
    return await _recent(db, person.id)


@router.get("/branches")
async def branches(ctx: Auth, person: SignedInPerson, db: DB) -> list[PickEntry]:
    return await _branches(db)


@router.get("/money")
async def money(
    ctx: Auth,
    person: SignedInPerson,
    db: DB,
    q: Annotated[str, Query(min_length=2, max_length=120)],
    page: Annotated[int, Query(ge=1, le=100)] = 1,
) -> MoneyPage:
    """Money – adresár (read cache only). A search is required — the whole address book (thousands) is never sent."""
    rows = await _money_all(db, q.strip())
    start = (page - 1) * MONEY_PAGE
    return MoneyPage(items=rows[start : start + MONEY_PAGE], total=len(rows), page=page)
