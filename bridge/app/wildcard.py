"""Pilot 2026-11-23: the `%` search of Money S4 in the article picker — `%mat%4%934` = a name with „mat“, then „4“,
then „934“ (in this order, anything in between). Money gets an AND of `Nazev~ct~<part>` (never a `%` in a filter
value); the order is checked here on the returned rows, case- and accent-insensitive."""

from __future__ import annotations

import unicodedata

WILDCARD = "%"


def is_wildcard(text: str | None) -> bool:
    return bool(text) and WILDCARD in (text or "")


def parts(text: str) -> list[str]:
    """Non-empty pieces between `%`, trimmed, in order (duplicates kept — the order check needs them)."""
    return [p.strip() for p in text.split(WILDCARD) if p.strip()]


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def in_order(name: str, pieces: list[str]) -> bool:
    """True when every piece occurs in `name` after the previous one."""
    hay, pos = fold(name), 0
    for piece in pieces:
        found = hay.find(fold(piece), pos)
        if found < 0:
            return False
        pos = found + len(fold(piece))
    return True
