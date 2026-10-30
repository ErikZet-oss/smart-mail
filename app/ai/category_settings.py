"""17c Kategórie — company-wide category list in `org_settings` (#116, Erik's answer A).

Built-in categories (AI_ASSISTANT §4) keep their ids; an admin may edit the description used in the classify prompt
and switch them off. Up to 15 custom categories may be added. Switching a category off only removes it from the
prompt and the triage list — classifications already stored keep their category and their view still opens.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.categories import CATEGORIES, CategoryDef
from app.ai.models import OrgSettings

SECTION_CATEGORIES: Final = "ai.categories"
MAX_CUSTOM: Final = 15
FALLBACK_ID: Final = "other"  # the fallback of every failed classification — never switched off
COLOR_TOKENS: Final = ("warning", "success", "danger", "info", "brand", "neutral")
CUSTOM_ID = re.compile(r"^x_[a-z0-9_]{1,40}$")
MAX_LABEL: Final = 40
MAX_DESCRIPTION: Final = 300


def custom_id(label: str) -> str:
    """„Kuriér – DPD“ → x_kurier_dpd (ascii slug; ids of custom categories always start with x_)."""
    table = str.maketrans("áäčďéěíĺľňóôŕřšťúůýžÁÄČĎÉĚÍĹĽŇÓÔŔŘŠŤÚŮÝŽ", "aacdeeillnoorrstuuyzAACDEEILLNOORRSTUUYZ")
    slug = re.sub(r"[^a-z0-9]+", "_", label.translate(table).lower()).strip("_")[:40]
    return f"x_{slug or 'kategoria'}"


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def all_categories(data: dict[str, Any] | None) -> list[tuple[CategoryDef, bool, bool]]:
    """(category, enabled, builtin) for every built-in and stored custom category, in display order."""
    stored = data or {}
    builtin_over = _dict(stored.get("builtin"))
    out: list[tuple[CategoryDef, bool, bool]] = []
    for c in CATEGORIES:
        over = _dict(builtin_over.get(c.id))
        description = _text(over.get("description"))[:MAX_DESCRIPTION]
        enabled = over.get("enabled", True) is not False or c.id == FALLBACK_ID
        category = CategoryDef(c.id, c.label_sk, description or c.description_sk, c.color_token, c.show_in_triage)
        out.append((category, enabled, True))
    raw_custom = stored.get("custom")
    customs: list[Any] = raw_custom if isinstance(raw_custom, list) else []
    seen = {c.id for c in CATEGORIES}
    for item in customs[:MAX_CUSTOM]:
        if not isinstance(item, dict):
            continue
        cid, label = item.get("id"), item.get("label")
        if not isinstance(cid, str) or not CUSTOM_ID.match(cid) or cid in seen or not isinstance(label, str):
            continue
        seen.add(cid)
        description = _text(item.get("description"))
        color = item.get("color") if item.get("color") in COLOR_TOKENS else "neutral"
        out.append(
            (
                CategoryDef(cid, label.strip()[:MAX_LABEL], description.strip()[:MAX_DESCRIPTION], str(color)),
                item.get("enabled", True) is not False,
                False,
            )
        )
    return out


def prompt_categories(data: dict[str, Any] | None) -> tuple[CategoryDef, ...]:
    """The enabled categories — what the classify prompt lists and what the model may answer."""
    return tuple(c for c, enabled, _ in all_categories(data) if enabled)


def triage_categories(data: dict[str, Any] | None) -> tuple[CategoryDef, ...]:
    return tuple(c for c in prompt_categories(data) if c.show_in_triage)


def category_lookup(data: dict[str, Any] | None) -> dict[str, CategoryDef]:
    """Every known category, enabled or not: stored classifications keep opening (#116)."""
    return {c.id: c for c, _, _ in all_categories(data)}


async def load_category_data(db: AsyncSession) -> dict[str, Any] | None:
    row = await db.scalar(select(OrgSettings).where(OrgSettings.section == SECTION_CATEGORIES))
    return row.data if row else None


def category_ids(categories: Sequence[CategoryDef]) -> frozenset[str]:
    return frozenset(c.id for c in categories)
