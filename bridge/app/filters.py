"""GraphQL filter builder for Money S4 (MONEY_API §2, §7): `Field~op~value`, AND = `#`, OR = `|`, parentheses group.

Escaping of `~ # | ( )` inside a value is undocumented on the customer's server [PROBE], so a value that contains any of
them is rejected — never escaped or stripped. Every value passes through `cond`, so no input can add a condition.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

Op = Literal["eq", "ne", "sw", "ct", "ew", "lt", "lte", "gt", "gte"]
OPS: frozenset[str] = frozenset({"eq", "ne", "sw", "ct", "ew", "lt", "lte", "gt", "gte"})
UNSAFE = frozenset("~#|()")
_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

Value = str | int | bool | Decimal | date | uuid.UUID


class UnsafeFilterValue(ValueError):
    def __init__(self, field: str) -> None:
        super().__init__(f"unsafe filter value for {field}")
        self.field = field


def fmt(value: Value) -> str:
    """Dates YYYY-MM-DD [PROBE], bool true/false, decimals with a dot and no exponent, GUID as is."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("decimal must be finite")
        return format(value, "f")
    if isinstance(value, int | uuid.UUID):
        return str(value)
    return value


def cond(field: str, op: Op, value: Value) -> str:
    if not _FIELD.match(field):
        raise ValueError(f"invalid field name {field!r}")
    if op not in OPS:
        raise ValueError(f"invalid operator {op!r}")
    text = fmt(value)
    if any(c in UNSAFE for c in text):
        raise UnsafeFilterValue(field)
    return f"{field}~{op}~{text}"


def all_(*conds: str) -> str:
    """AND of conditions built by `cond` (or nested `any_`)."""
    if not conds:
        raise ValueError("at least one condition")
    return "#".join(conds)


def any_(*conds: str) -> str:
    """OR of conditions; each side is parenthesised."""
    if not conds:
        raise ValueError("at least one condition")
    return "|".join(f"({c})" for c in conds)
