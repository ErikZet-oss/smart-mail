"""Category eval (Phase 2 plan B): scores predictions against labels made on the server.

Pure functions only — no mail text ever enters a report: rows carry ids and category/language codes, the report
carries counts. Gate: ≥ 90 % category accuracy on the server-side labeled set (CLAUDE.md §12 Phase 2).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

ACCURACY_GATE = Decimal("0.90")
SECTION_EVAL = "ai.eval_last"  # org_settings: summary of the last saved run, shown in 17f
MIN_LABELED = 200  # the plan's size of the server-side set; smaller sets are reported, flagged as too small


@dataclass(frozen=True, slots=True)
class EvalRow:
    label: str
    predicted: str | None  # None = not classified (counted as wrong)
    language_label: str | None = None
    language_predicted: str | None = None


@dataclass(slots=True)
class CategoryScore:
    support: int = 0  # labeled as this category
    predicted: int = 0  # predicted as this category
    correct: int = 0

    @property
    def precision(self) -> Decimal | None:
        return _ratio(self.correct, self.predicted)

    @property
    def recall(self) -> Decimal | None:
        return _ratio(self.correct, self.support)


@dataclass(slots=True)
class EvalReport:
    total: int = 0
    correct: int = 0
    unclassified: int = 0
    language_total: int = 0
    language_correct: int = 0
    per_category: dict[str, CategoryScore] = field(default_factory=dict)
    confusion: Counter[tuple[str, str]] = field(default_factory=Counter)  # (label, predicted) → count

    @property
    def accuracy(self) -> Decimal | None:
        return _ratio(self.correct, self.total)

    @property
    def language_accuracy(self) -> Decimal | None:
        return _ratio(self.language_correct, self.language_total)

    def passes(self, gate: Decimal = ACCURACY_GATE) -> bool:
        accuracy = self.accuracy
        return accuracy is not None and accuracy >= gate

    def to_summary(self) -> dict[str, Any]:
        """Aggregates only (safe to store in org_settings and show in 17f): no ids, no mail text."""
        return {
            "total": self.total,
            "correct": self.correct,
            "unclassified": self.unclassified,
            "accuracy": _pct(self.accuracy),
            "language_accuracy": _pct(self.language_accuracy),
            "too_small": self.total < MIN_LABELED,
            "per_category": {
                cid: {
                    "support": s.support,
                    "predicted": s.predicted,
                    "correct": s.correct,
                    "precision": _pct(s.precision),
                    "recall": _pct(s.recall),
                }
                for cid, s in sorted(self.per_category.items())
            },
            "confusion": [
                {"label": label, "predicted": predicted, "count": count}
                for (label, predicted), count in sorted(self.confusion.items(), key=lambda kv: (-kv[1], kv[0]))
            ],
        }


def _ratio(numerator: int, denominator: int) -> Decimal | None:
    return None if denominator == 0 else Decimal(numerator) / Decimal(denominator)


def _pct(value: Decimal | None) -> str | None:
    return None if value is None else str((value * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def evaluate(rows: Iterable[EvalRow]) -> EvalReport:
    report = EvalReport()
    for row in rows:
        predicted = row.predicted or "(none)"
        report.total += 1
        if row.predicted is None:
            report.unclassified += 1
        label_score = report.per_category.setdefault(row.label, CategoryScore())
        label_score.support += 1
        report.per_category.setdefault(predicted, CategoryScore()).predicted += 1
        if predicted == row.label:
            report.correct += 1
            label_score.correct += 1
        else:
            report.confusion[(row.label, predicted)] += 1
        if row.language_label:
            report.language_total += 1
            if row.language_predicted == row.language_label:
                report.language_correct += 1
    report.per_category.pop("(none)", None)
    return report


def format_report(report: EvalReport, *, mode: str, gate: Decimal = ACCURACY_GATE) -> str:
    """Plain-text report for the server console — codes and counts only."""
    summary = report.to_summary()
    lines = [
        f"mode={mode} labeled={report.total} correct={report.correct} unclassified={report.unclassified}",
        f"category accuracy: {summary['accuracy'] or '-'} %  (gate {gate * 100:.0f} %) → "
        + ("PASS" if report.passes(gate) else "FAIL"),
        f"language accuracy: {summary['language_accuracy'] or '-'} %",
    ]
    if summary["too_small"]:
        lines.append(f"WARNING: fewer than {MIN_LABELED} labeled messages — not enough for the acceptance gate")
    lines.append("")
    lines.append(f"{'category':<20} {'support':>7} {'predicted':>9} {'precision':>9} {'recall':>7}")
    for cid, s in summary["per_category"].items():
        lines.append(
            f"{cid:<20} {s['support']:>7} {s['predicted']:>9} {s['precision'] or '-':>9} {s['recall'] or '-':>7}"
        )
    if summary["confusion"]:
        lines.append("")
        lines.append("confusions (label → predicted: count)")
        for c in summary["confusion"]:
            lines.append(f"  {c['label']} → {c['predicted']}: {c['count']}")
    return "\n".join(lines)
