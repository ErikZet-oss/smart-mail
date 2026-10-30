"""Autonomy levels per action (AI_ASSISTANT §1), set by each login itself — no admin maximum (DECISIONS D8, #116).

The hard rule lives here, in code, and no stored value can change it: external sends and Money writes never go
above level 2 (Pripraviť na schválenie). Values are clamped when they are saved *and* when they are read, so a
row written by hand (or by an older version) cannot raise a level either.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AccountSettings

SECTION = "ai.autonomy"
LEVELS = (0, 1, 2, 3, 4)
HUMAN_APPROVAL_MAX = 2  # external send and Money writes: a person always approves


@dataclass(frozen=True, slots=True)
class AutonomyAction:
    id: str
    default: int
    max: int
    hard: bool = False  # external send / Money write — locked at max 2 for everybody


# AI_ASSISTANT §1, in the order of the table there.
ACTIONS: tuple[AutonomyAction, ...] = (
    AutonomyAction("classify", 4, 4),
    AutonomyAction("link_company", 4, 4),
    AutonomyAction("newsletter_feed", 3, 4),
    AutonomyAction("spam_move", 3, 3),
    AutonomyAction("assign", 2, 3),
    AutonomyAction("reply", 2, 2, hard=True),
    AutonomyAction("invoice_attach", 2, 2, hard=True),
    AutonomyAction("reminder", 1, 2, hard=True),
    AutonomyAction("delivery_note", 2, 2, hard=True),
    AutonomyAction("complaint", 1, 2, hard=True),
    AutonomyAction("order_create", 2, 2, hard=True),
    AutonomyAction("order_confirmation", 2, 2, hard=True),
    AutonomyAction("order_clarification", 1, 2, hard=True),
    AutonomyAction("order_change", 2, 2, hard=True),
    AutonomyAction("goods_shipped", 1, 2, hard=True),
    AutonomyAction("offer", 1, 2, hard=True),
    AutonomyAction("money_company", 1, 2, hard=True),
    AutonomyAction("money_activity", 4, 4),
    AutonomyAction("followup", 3, 3),
)
BY_ID = {a.id: a for a in ACTIONS}


def clamp(action: AutonomyAction, value: object) -> int:
    """A stored or submitted value → a level allowed for this action (unknown → the default)."""
    if isinstance(value, bool) or not isinstance(value, int) or value not in LEVELS:
        return action.default
    limit = min(action.max, HUMAN_APPROVAL_MAX) if action.hard else action.max
    return min(value, limit)


def effective_levels(data: dict[str, Any] | None) -> dict[str, int]:
    stored = data or {}
    return {a.id: clamp(a, stored.get(a.id, a.default)) for a in ACTIONS}


async def load_levels(db: AsyncSession, account_id: uuid.UUID) -> dict[str, int]:
    row = await db.scalar(
        select(AccountSettings).where(AccountSettings.account_id == account_id, AccountSettings.section == SECTION)
    )
    return effective_levels(row.data if row else None)


async def autonomy_level(db: AsyncSession, account_id: uuid.UUID, action_id: str) -> int:
    return (await load_levels(db, account_id))[action_id]


async def save_levels(db: AsyncSession, account_id: uuid.UUID, submitted: dict[str, int]) -> dict[str, int]:
    """Store only known actions, clamped; returns the effective levels. The caller commits."""
    row = await db.scalar(
        select(AccountSettings).where(AccountSettings.account_id == account_id, AccountSettings.section == SECTION)
    )
    current = effective_levels(row.data if row else None)
    merged = {**current, **{k: clamp(BY_ID[k], v) for k, v in submitted.items() if k in BY_ID}}
    if row is None:
        db.add(AccountSettings(account_id=account_id, section=SECTION, data=merged))
    else:
        row.data = merged
    return merged
