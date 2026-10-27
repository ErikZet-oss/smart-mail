"""Exact-model list prices (USD / MTok) from Anthropic pricing — never substring match (ADR-011).

Source: https://platform.claude.com/docs/en/about-claude/pricing
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import structlog

log = structlog.get_logger(__name__)

HAIKU_55_CONTEXT_THRESHOLD = 100_000


@dataclass(frozen=True, slots=True)
class ModelRate:
    """Base (and optional high-context) list rates in USD per million tokens."""

    input_per_mtok: Decimal
    output_per_mtok: Decimal
    high_context_threshold: int | None = None
    high_input_per_mtok: Decimal | None = None
    high_output_per_mtok: Decimal | None = None

    def rates_for(self, input_tokens: int) -> tuple[Decimal, Decimal]:
        if (
            self.high_context_threshold is not None
            and self.high_input_per_mtok is not None
            and self.high_output_per_mtok is not None
            and input_tokens > self.high_context_threshold
        ):
            return self.high_input_per_mtok, self.high_output_per_mtok
        return self.input_per_mtok, self.output_per_mtok


# Keyed by exact Claude API model id only (dated aliases listed separately when published).
MODEL_RATES: dict[str, ModelRate] = {
    "claude-haiku-5-5": ModelRate(
        input_per_mtok=Decimal("0.10"),
        output_per_mtok=Decimal("0.50"),
        high_context_threshold=HAIKU_55_CONTEXT_THRESHOLD,
        high_input_per_mtok=Decimal("0.50"),
        high_output_per_mtok=Decimal("2.50"),
    ),
    "claude-sonnet-5-5": ModelRate(
        input_per_mtok=Decimal("2"),
        output_per_mtok=Decimal("10"),
    ),
    "claude-opus-5-5": ModelRate(
        input_per_mtok=Decimal("4"),
        output_per_mtok=Decimal("20"),
    ),
    "claude-haiku-4-5": ModelRate(
        input_per_mtok=Decimal("1"),
        output_per_mtok=Decimal("5"),
    ),
    "claude-haiku-4-5-20251001": ModelRate(
        input_per_mtok=Decimal("1"),
        output_per_mtok=Decimal("5"),
    ),
}


def _highest_rate() -> ModelRate:
    """Conservative fallback: never under-estimate unknown models."""
    best = next(iter(MODEL_RATES.values()))
    best_sum = best.input_per_mtok + best.output_per_mtok
    for rate in MODEL_RATES.values():
        # Prefer the higher of base and high-context rows when present
        candidates = [(rate.input_per_mtok, rate.output_per_mtok)]
        if rate.high_input_per_mtok is not None and rate.high_output_per_mtok is not None:
            candidates.append((rate.high_input_per_mtok, rate.high_output_per_mtok))
        for inn, out in candidates:
            s = inn + out
            if s > best_sum:
                best_sum = s
                best = ModelRate(input_per_mtok=inn, output_per_mtok=out)
    return best


_FALLBACK_RATE = _highest_rate()


def rate_for_model(model_id: str) -> ModelRate:
    """Lookup by exact model id. Unknown → highest table rate + warning."""
    exact = MODEL_RATES.get(model_id)
    if exact is not None:
        return exact
    log.warning(
        "ai.pricing_unknown_model",
        model=model_id,
        fallback_input=str(_FALLBACK_RATE.input_per_mtok),
        fallback_output=str(_FALLBACK_RATE.output_per_mtok),
    )
    return _FALLBACK_RATE


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    """USD for one call from published list rates (exact model id)."""
    rate = rate_for_model(model)
    in_rate, out_rate = rate.rates_for(input_tokens)
    cost = (Decimal(input_tokens) / Decimal(1_000_000)) * in_rate + (
        Decimal(output_tokens) / Decimal(1_000_000)
    ) * out_rate
    return cost.quantize(Decimal("0.000001"))


# Assumed tokens for a classify call before we know real usage (budget pre-check).
CLASSIFY_ESTIMATE_INPUT_TOKENS = 1500
CLASSIFY_ESTIMATE_OUTPUT_TOKENS = 200
DRAFT_ESTIMATE_INPUT_TOKENS = 3000
DRAFT_ESTIMATE_OUTPUT_TOKENS = 500


def estimate_purpose_cost_usd(model: str, purpose: str) -> Decimal:
    if purpose == "draft":
        return estimate_cost_usd(model, DRAFT_ESTIMATE_INPUT_TOKENS, DRAFT_ESTIMATE_OUTPUT_TOKENS)
    return estimate_cost_usd(model, CLASSIFY_ESTIMATE_INPUT_TOKENS, CLASSIFY_ESTIMATE_OUTPUT_TOKENS)
