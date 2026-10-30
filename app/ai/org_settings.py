"""17a Poskytovateľ a rozpočet — company-wide AI limits in `org_settings` (#116, Erik's answer A).

`AI_DAILY_BUDGET_USD` from env is the default and the source of truth until an admin explicitly saves a budget in
17a; from then on the saved value wins, always within 1–500 USD. The UI shows where the value comes from.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import OrgSettings
from app.core.config import Settings

SECTION_LIMITS = "ai.limits"
BUDGET_MIN = Decimal("1")
BUDGET_MAX = Decimal("500")
ALERT_DEFAULT = 80
RETENTION_DAYS = (30, 90, 365)
RETENTION_DEFAULT = 90
OnExhausted = Literal["rules_only", "ai_off"]
ON_EXHAUSTED: tuple[OnExhausted, ...] = ("rules_only", "ai_off")
BudgetSource = Literal["env", "app"]


@dataclass(frozen=True, slots=True)
class AiLimits:
    budget_usd: Decimal
    budget_source: BudgetSource
    alert_pct: int
    on_exhausted: OnExhausted
    retention_days: int


def parse_budget(value: object) -> Decimal | None:
    """A stored or submitted budget → Decimal within 1–500, else None (never a float)."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    try:
        amount = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount < BUDGET_MIN or amount > BUDGET_MAX:
        return None
    return amount.quantize(Decimal("0.01"))


def _is_pct(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 100


def limits_from(data: dict[str, Any] | None, settings: Settings) -> AiLimits:
    stored = data or {}
    saved = parse_budget(stored.get("daily_budget_usd"))
    alert = stored.get("alert_pct")
    on_exhausted = stored.get("on_exhausted")
    retention = stored.get("retention_days")
    return AiLimits(
        budget_usd=saved if saved is not None else Decimal(str(settings.ai_daily_budget_usd)),
        budget_source="app" if saved is not None else "env",
        alert_pct=alert
        if isinstance(alert, int) and not isinstance(alert, bool) and 1 <= alert <= 100
        else ALERT_DEFAULT,
        on_exhausted=on_exhausted if on_exhausted in ON_EXHAUSTED else "rules_only",
        retention_days=retention if retention in RETENTION_DAYS else RETENTION_DEFAULT,
    )


async def _row(db: AsyncSession, section: str) -> OrgSettings | None:
    return await db.scalar(select(OrgSettings).where(OrgSettings.section == section))


async def load_ai_limits(db: AsyncSession, settings: Settings) -> AiLimits:
    row = await _row(db, SECTION_LIMITS)
    return limits_from(row.data if row else None, settings)


async def save_org_section(db: AsyncSession, section: str, data: dict[str, Any]) -> None:
    """Replace one company section; the caller audits and commits."""
    row = await _row(db, section)
    if row is None:
        db.add(OrgSettings(section=section, data=data))
    else:
        row.data = data
