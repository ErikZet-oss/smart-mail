"""Phase 2a follow-up: exact-model pricing, Bratislava budget, Haiku 4.5 ≠ 5.5."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.ai.budget import budget_day_start, run_budgeted_batch
from app.ai.pricing import estimate_cost_usd, estimate_purpose_cost_usd, rate_for_model
from app.ai.provider import estimate_cost_usd as provider_estimate


def test_2a_haiku_45_not_priced_as_haiku_55() -> None:
    """Exact model id lookup — substring 'haiku' must not conflate 4.5 and 5.5."""
    tokens_in, tokens_out = 1500, 200
    cost_55 = estimate_cost_usd("claude-haiku-5-5", tokens_in, tokens_out)
    cost_45 = estimate_cost_usd("claude-haiku-4-5", tokens_in, tokens_out)
    cost_45_dated = estimate_cost_usd("claude-haiku-4-5-20251001", tokens_in, tokens_out)
    assert cost_55 == Decimal("0.000250")  # 0.10/0.50
    assert cost_45 == Decimal("0.002500")  # 1/5
    assert cost_45_dated == cost_45
    assert cost_45 != cost_55


def test_2a_sonnet_and_opus_55_list_rates() -> None:
    assert estimate_cost_usd("claude-sonnet-5-5", 1_000_000, 1_000_000) == Decimal("12.000000")
    assert estimate_cost_usd("claude-opus-5-5", 1_000_000, 1_000_000) == Decimal("24.000000")


def test_2a_haiku_55_high_context_tier() -> None:
    low = estimate_cost_usd("claude-haiku-5-5", 50_000, 1000)
    high = estimate_cost_usd("claude-haiku-5-5", 100_001, 1000)
    assert high > low
    # >100K: 0.50 in / 2.50 out
    assert high == (
        Decimal("100001") / Decimal(1_000_000) * Decimal("0.50")
        + Decimal("1000") / Decimal(1_000_000) * Decimal("2.50")
    ).quantize(Decimal("0.000001"))


def test_2a_unknown_model_uses_highest_rate() -> None:
    # Highest published row in our table is Opus 5.5 at 4/20 (or Haiku 5.5 high-context 0.50/2.50 — Opus wins).
    fallback = rate_for_model("claude-totally-unknown-model-xyz")
    assert fallback.input_per_mtok == Decimal("4")
    assert fallback.output_per_mtok == Decimal("20")
    cost = estimate_cost_usd("claude-totally-unknown-model-xyz", 1_000_000, 0)
    assert cost == Decimal("4.000000")


def test_2a_provider_reexports_pricing() -> None:
    assert provider_estimate("claude-haiku-4-5", 1500, 200) == estimate_cost_usd("claude-haiku-4-5", 1500, 200)


def test_2a_budget_day_is_europe_bratislava() -> None:
    # 2026-10-27 22:30 UTC = 2026-10-27 23:30 in Bratislava (UTC+1) → same local day
    late_utc = datetime(2026, 10, 27, 22, 30, tzinfo=UTC)
    start = budget_day_start(late_utc)
    local = start.astimezone(ZoneInfo("Europe/Bratislava"))
    assert local.hour == 0 and local.minute == 0
    assert local.date().isoformat() == "2026-10-27"
    # Just after midnight Bratislava on the 28th (2026-10-27 23:00 UTC in winter = 00:00+1)
    after = datetime(2026, 10, 27, 23, 0, tzinfo=UTC)
    start2 = budget_day_start(after)
    assert start2.astimezone(ZoneInfo("Europe/Bratislava")).date().isoformat() == "2026-10-28"


def test_2a_batch_of_100_stops_at_budget_limit() -> None:
    """Budget is checked before every call — a 100-message batch stops at the cap."""
    estimate = estimate_purpose_cost_usd("claude-haiku-5-5", "classify")
    # Allow exactly 10 classify estimates
    budget = estimate * 10
    result = run_budgeted_batch(
        message_count=100,
        estimate_usd_per_call=estimate,
        budget_usd=budget,
    )
    assert result.attempted == 100
    assert result.processed == 10
    assert result.stopped_at_budget is True
    assert result.spent_usd == estimate * 10
