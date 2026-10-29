"""Who may work under a login (PRODUCT_SPEC §2.0): the people of a branch mailbox, or the own person of a personal
account. Used by the "Kto ste?" picker (W1b/M0), the PersonChip (W2b) and the check on every request."""

from __future__ import annotations

import unicodedata
import uuid

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.auth.models import Account, AccountKind, DevicePersonMemory, Person, PersonBranch

# Slovak alphabet (ICU `sk`): ä, č, ch, ô, š, ž are letters of their own; other accents only break ties
_PRIMARY = ["a", "ä", "b", "c", "č", "d", "e", "f", "g", "h", "ch", "i", "j", "k", "l", "m", "n", "o", "ô", "p", "q"]
_PRIMARY += ["r", "ř", "s", "š", "t", "u", "v", "w", "x", "y", "z", "ž"]
_RANK = {letter: i for i, letter in enumerate(_PRIMARY)}


def _rank(char: str) -> int:
    if char in _RANK:
        return _RANK[char]
    base = unicodedata.normalize("NFD", char)[0]
    if base in _RANK:
        return _RANK[base]
    return -1 if char.isspace() else 1000 + ord(char)


def slovak_sort_key(text: str) -> tuple[tuple[int, ...], str]:
    s = text.casefold()
    ranks: list[int] = []
    i = 0
    while i < len(s):
        if s.startswith("ch", i):
            ranks.append(_RANK["ch"])
            i += 2
            continue
        ranks.append(_rank(s[i]))
        i += 1
    return tuple(ranks), s


def picker_order(person: Person) -> tuple[bool, tuple[tuple[int, ...], str], tuple[tuple[int, ...], str]]:
    """Manager first, then alphabetically (first name, last name)."""
    return (not person.is_manager, slovak_sort_key(person.first_name), slovak_sort_key(person.last_name))


def own_login_person_ids() -> Select[uuid.UUID | None]:
    """Persons that sign in with their own personal account (eshop@, a personal mailbox). Aliased, so it never
    correlates with an outer query on accounts."""
    own = aliased(Account)
    return select(own.person_id).where(own.kind == AccountKind.personal, own.person_id.is_not(None)).correlate(None)


async def eligible_persons(db: AsyncSession, account: Account) -> list[Person]:
    if account.kind == AccountKind.personal:
        if account.person_id is None:
            return []
        person = await db.get(Person, account.person_id)
        return [person] if person is not None and person.active else []
    if account.branch_id is None:
        return []
    covering = select(PersonBranch.person_id).where(PersonBranch.branch_id == account.branch_id)
    rows = await db.execute(
        select(Person)
        .where(Person.active.is_(True))
        .where((Person.branch_id == account.branch_id) | Person.id.in_(covering))
        # a person with an own login only has a branch for the signature, never a place in „Kto ste?“ (#71)
        .where(Person.id.not_in(own_login_person_ids()))
    )
    return sorted(rows.scalars().all(), key=picker_order)


async def is_eligible(db: AsyncSession, account: Account, person_id: uuid.UUID) -> bool:
    return any(p.id == person_id for p in await eligible_persons(db, account))


async def remembered_person(db: AsyncSession, device_id: str | None, account_id: uuid.UUID) -> uuid.UUID | None:
    if not device_id:
        return None
    memory = (
        await db.execute(
            select(DevicePersonMemory).where(
                DevicePersonMemory.device_id == device_id, DevicePersonMemory.account_id == account_id
            )
        )
    ).scalar_one_or_none()
    return memory.last_person_id if memory else None


async def remember_person(
    db: AsyncSession, device_id: str | None, account_id: uuid.UUID, person_id: uuid.UUID | None
) -> None:
    """Store (or with None: forget) the last person of this browser for this login."""
    if not device_id:
        return
    memory = (
        await db.execute(
            select(DevicePersonMemory).where(
                DevicePersonMemory.device_id == device_id, DevicePersonMemory.account_id == account_id
            )
        )
    ).scalar_one_or_none()
    if memory is None:
        if person_id is not None:
            db.add(DevicePersonMemory(device_id=device_id, account_id=account_id, last_person_id=person_id))
        return
    memory.last_person_id = person_id
