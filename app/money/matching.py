"""Sender → Money company (MONEY_API §5.4), evaluated on the read cache when the Zákazník panel opens.

Order: a person-confirmed link 1.0 → Money person e-mail 0.98 → company `Email` / `SeznamSpojeni` 0.95 → IČO from the
mail body (mod-11 checked) 0.9 → same company domain 0.7 (not free-mail, not ours — a person confirms it once, then
it becomes a link). Two companies on one step → no match, the candidates are offered instead (never a guess).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.mail.models import Message
from app.money.models import EmailCompanyLink, MoneyCompany, MoneyPerson

Method = Literal["confirmed", "person", "company_email", "ico", "domain"]
CONFIDENCE: dict[Method, float] = {"confirmed": 1.0, "person": 0.98, "company_email": 0.95, "ico": 0.9, "domain": 0.7}
FREE_MAIL = frozenset(
    {
        "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "hotmail.com", "outlook.com", "outlook.sk",
        "live.com", "msn.com", "icloud.com", "me.com", "aol.com", "gmx.com", "gmx.net", "gmx.de", "web.de",
        "proton.me", "protonmail.com", "azet.sk", "centrum.sk", "zoznam.sk", "post.sk", "atlas.sk", "pobox.sk",
        "stonline.sk", "seznam.cz", "email.cz", "centrum.cz", "volny.cz", "post.cz", "atlas.cz", "tiscali.cz",
    }
)  # fmt: skip
_ICO = re.compile(r"\bI[ČC]O?\s*[:.]?\s*(\d{2}\s?\d{3}\s?\d{3})\b", re.IGNORECASE)
MAX_CANDIDATES = 5


@dataclass(frozen=True)
class SenderMatch:
    email: str
    company: MoneyCompany | None
    method: Method | None
    confidence: float
    needs_confirmation: bool
    candidates: list[MoneyCompany] = field(default_factory=list)


def ico_valid(ico: str) -> bool:
    """Slovak / Czech IČO mod-11 check digit."""
    if not re.fullmatch(r"\d{8}", ico):
        return False
    total = sum(int(d) * w for d, w in zip(ico[:7], range(8, 1, -1), strict=True))
    return (11 - total % 11) % 10 == int(ico[7])


def icos_in(text: str | None) -> list[str]:
    found = [m.group(1).replace(" ", "") for m in _ICO.finditer(text or "")]
    return list(dict.fromkeys(i for i in found if ico_valid(i)))


def counterparty(message: Message, settings: Settings) -> str | None:
    """The outside address of a message: the sender, or for our own mail the first external recipient."""
    sender = (message.from_email or "").strip().lower()
    if sender and not settings.is_internal_address(sender):
        return sender
    for addr in [*(message.to_addrs or []), *(message.cc_addrs or [])]:
        email = str(addr.get("email") or "").strip().lower()
        if email and not settings.is_internal_address(email):
            return email
    return None


async def _active(db: AsyncSession, money_ids: list[uuid.UUID]) -> list[MoneyCompany]:
    if not money_ids:
        return []
    rows = await db.scalars(
        select(MoneyCompany)
        .where(MoneyCompany.money_id.in_(money_ids), MoneyCompany.active.is_(True))
        .order_by(MoneyCompany.name)
        .limit(MAX_CANDIDATES + 1)
    )
    return list(rows)


def _pick(email: str, method: Method, companies: list[MoneyCompany]) -> SenderMatch | None:
    if not companies:
        return None
    if len(companies) > 1:
        return SenderMatch(email, None, None, 0.0, True, companies[:MAX_CANDIDATES])
    return SenderMatch(email, companies[0], method, CONFIDENCE[method], method == "domain")


async def match_sender(db: AsyncSession, email: str, body_text: str | None, settings: Settings) -> SenderMatch:
    email = email.strip().lower()
    link = await db.scalar(select(EmailCompanyLink).where(EmailCompanyLink.email == email))
    if link is not None:
        found = _pick(email, "confirmed", await _active(db, [link.company_money_id]))
        if found:
            return found

    person_companies = await db.scalars(
        select(MoneyPerson.company_money_id).where(
            MoneyPerson.email == email, MoneyPerson.active.is_(True), MoneyPerson.company_money_id.is_not(None)
        )
    )
    found = _pick(email, "person", await _active(db, [c for c in set(person_companies) if c]))
    if found:
        return found

    by_email = await db.scalars(
        select(MoneyCompany.money_id).where(MoneyCompany.emails.contains([email]), MoneyCompany.active.is_(True))
    )
    found = _pick(email, "company_email", await _active(db, list(by_email)))
    if found:
        return found

    icos = icos_in(body_text)
    if icos:
        by_ico = await db.scalars(
            select(MoneyCompany.money_id).where(MoneyCompany.ico.in_(icos), MoneyCompany.active.is_(True))
        )
        found = _pick(email, "ico", await _active(db, list(by_ico)))
        if found:
            return found

    domain = email.rpartition("@")[2]
    if domain and domain not in FREE_MAIL and domain not in settings.internal_domain_list:
        by_domain = await db.scalars(
            select(MoneyCompany.money_id).where(
                MoneyCompany.active.is_(True),
                func.array_to_string(MoneyCompany.emails, " ").op("~")(f"@{re.escape(domain)}( |$)"),
            )
        )
        found = _pick(email, "domain", await _active(db, list(by_domain)))
        if found:
            return found
    return SenderMatch(email, None, None, 0.0, False)
