"""The supplier of a document in the read cache `money_companies` (DL-B2).

Pilot 2026-11-25 (Valenta ZT, IČ 26512149): a Czech supplier was in Money, but its card was not found. The match is
now tolerant of how the number is written on either side — spaces, dots, a country prefix (`CZ26512149`) — and also
looks at DIČ / IČ DPH, where a foreign supplier's card often carries the number (Money has no IČO for some of them).
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.money.models import MoneyCompany

_PREFIX = re.compile(r"^[A-Z]{2}(?=\d)")


def ico_key(value: str | None) -> str:
    """`CZ 265 12 149` / `26512149` / `cz26512149` → `26512149` (letters and digits only, without a country prefix)."""
    plain = re.sub(r"[^0-9A-Z]", "", (value or "").upper())
    return _PREFIX.sub("", plain)


def _norm(col: Any) -> Any:
    return func.regexp_replace(func.upper(func.coalesce(col, "")), "[^0-9A-Z]", "", "g")


async def find_supplier(db: AsyncSession, ico: str | None) -> MoneyCompany | None:
    """Active company whose IČO (preferred), DIČ or IČ DPH is the document's number — with or without a country
    prefix. Several cards → the IČO match first, then the oldest card (stable)."""
    key = ico_key(ico)
    if len(key) < 6:  # a real IČO has 8 digits (SK, CZ); shorter text would match too much
        return None
    variants = [key, *(f"{cc}{key}" for cc in ("SK", "CZ", "AT", "DE", "HU", "PL"))]
    ico_n, dic_n, icdph_n = _norm(MoneyCompany.ico), _norm(MoneyCompany.dic), _norm(MoneyCompany.icdph)
    rows = (
        await db.scalars(
            select(MoneyCompany)
            .where(
                MoneyCompany.active.is_(True),
                or_(ico_n.in_(variants), dic_n.in_(variants), icdph_n.in_(variants)),
            )
            .order_by(MoneyCompany.created_at, MoneyCompany.id)
        )
    ).all()
    by_ico = [c for c in rows if ico_key(c.ico) == key]
    best = by_ico or list(rows)
    return best[0] if best else None
