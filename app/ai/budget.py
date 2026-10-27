"""Daily AI budget — Europe/Bratislava calendar day; check before every LLM call."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

BUDGET_TZ = ZoneInfo("Europe/Bratislava")


def budget_day_start(now: datetime | None = None) -> datetime:
    """Start of the current calendar day in Europe/Bratislava, as UTC timestamptz."""
    local = (now or datetime.now(UTC)).astimezone(BUDGET_TZ)
    start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_local.astimezone(UTC)


def budget_allows_call(*, spent_usd: Decimal, estimate_usd: Decimal, budget_usd: Decimal) -> bool:
    """True if this call's estimate still fits under the daily cap."""
    if budget_usd <= 0:
        return False
    return spent_usd + estimate_usd <= budget_usd


@dataclass(frozen=True, slots=True)
class BudgetedBatchResult:
    attempted: int
    processed: int
    stopped_at_budget: bool
    spent_usd: Decimal


def run_budgeted_batch(
    *,
    message_count: int,
    estimate_usd_per_call: Decimal,
    budget_usd: Decimal,
    already_spent_usd: Decimal = Decimal("0"),
) -> BudgetedBatchResult:
    """Process up to message_count calls, checking the budget before each one.

    Pure helper used by the pipeline and by the 100-message stop-at-limit test.
    """
    spent = already_spent_usd
    processed = 0
    stopped = False
    for _ in range(message_count):
        if not budget_allows_call(spent_usd=spent, estimate_usd=estimate_usd_per_call, budget_usd=budget_usd):
            stopped = True
            break
        spent += estimate_usd_per_call
        processed += 1
    return BudgetedBatchResult(
        attempted=message_count,
        processed=processed,
        stopped_at_budget=stopped,
        spent_usd=spent,
    )
