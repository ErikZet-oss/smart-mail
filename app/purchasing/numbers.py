"""Numbers and codes from supplier documents — Decimal only, no binary floating point (CLAUDE.md §0.1)."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_SPACES = re.compile(r"[\s  ']")
_CODE_JUNK = re.compile(r"[^0-9A-Z]")


def parse_decimal(text: str | None) -> Decimal | None:
    """`1 234,50` · `1.234,50` · `1,234.50` · `1234.5` · `-12,3` → Decimal; unknown shapes → None.

    A single separator is always the decimal mark (`0,084` and `1,234` are prices per piece, not thousands — SK
    documents print decimals with a comma). Several identical separators are thousands groups of exactly 3 digits."""
    if text is None:
        return None
    s = _SPACES.sub("", str(text)).replace("€", "").replace("EUR", "").strip()
    if not s:
        return None
    neg = s.startswith("-") or s.endswith("-")
    s = s.strip("-+")
    if not s or not re.fullmatch(r"[0-9.,]+", s):
        return None
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        grp = "." if dec == "," else ","
        s = s.replace(grp, "").replace(dec, ".")
    elif "," in s:
        parts = s.split(",")
        if len(parts) > 2:
            if not all(len(p) == 3 for p in parts[1:]):
                return None
            s = "".join(parts)
        else:
            s = s.replace(",", ".")
    elif s.count(".") > 1:
        parts = s.split(".")
        if not all(len(p) == 3 for p in parts[1:]):
            return None
        s = "".join(parts)
    try:
        value = Decimal(s)
    except InvalidOperation:
        return None
    if not value.is_finite():
        return None
    return -value if neg else value


_AMBIGUOUS_QTY = re.compile(r"\d{1,3}[.,]\d{3}")


def parse_qty(text: str | None, unit_price: Decimal | None, line_total: Decimal | None) -> Decimal | None:
    """Quantity of a PDF line. `1.000` / `1,200` alone is ambiguous: the decimal reading (1 / 1,2) is the default of
    `parse_decimal`, but FABORY and others print thousands with a dot. The printed line total decides: when only the
    thousands reading gives qty × unit price = line total, it wins (pilot 2026-11-23: 1000 ks arrived as 1 ks)."""
    value = parse_decimal(text)
    if value is None or text is None or unit_price is None or line_total is None:
        return value
    s = _SPACES.sub("", str(text)).strip()
    if not _AMBIGUOUS_QTY.fullmatch(s):
        return value
    thousands = Decimal(s.replace(".", "").replace(",", ""))
    if amount_matches(value, unit_price, line_total):
        return value
    return thousands if amount_matches(thousands, unit_price, line_total) else value


def amount_matches(qty: Decimal, unit_price: Decimal, line_total: Decimal) -> bool:
    """qty × unit price = line total within 1 % (min. 0,02) — printed unit prices are rounded."""
    tolerance = max(Decimal("0.02"), abs(line_total) / 100)
    return abs(qty * unit_price - line_total) <= tolerance


def normalize_code(code: str | None) -> str | None:
    """Supplier/catalog codes compared without spaces, dashes, dots and case: `DIN 933 M8x30` → `DIN933M8X30`."""
    if code is None:
        return None
    out = _CODE_JUNK.sub("", str(code).upper())
    return out or None
