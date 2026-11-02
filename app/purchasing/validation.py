"""Rules of DOCUMENTS_SPEC §2.7 that need no item matching (Phase 4a). Every rule has a test named after its id.

DL-B4/B5/B6/B9/B10 and DL-W1/W2/W3/W6/W7/W8 come with 4b–4c (they need articles, warehouses or the branch template).
DL-B3 here covers duplicates inside Smart Mail; the Money side (`Odkaz` of received delivery notes) is added in 4c.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.ai.guards import check
from app.purchasing.schemas import ExtractedDoc, ExtractedLine

CENT = Decimal("0.01")
TOLERANCE = Decimal("0.01")
DATE_WINDOW_DAYS = 30


@dataclass(frozen=True, slots=True)
class Context:
    today: date
    supplier_in_money: bool | None  # None = Money cache unknown (empty) → not checked
    supplier_ico_matches: bool
    duplicate_of: str | None  # number of the earlier document with the same supplier + number (Smart Mail)


def line_amount(line: ExtractedLine) -> Decimal | None:
    if line.line_total is not None:
        return line.line_total
    if line.qty is not None and line.unit_price is not None:
        return (line.qty * line.unit_price).quantize(CENT, ROUND_HALF_UP)
    return None


def validate(doc: ExtractedDoc, ctx: Context) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    # DL-B2 supplier exists in Money and the IČO matches the document
    if not doc.supplier_ico:
        out.append(check("DL-B2", "blocking", reason="no_ico"))
    elif ctx.supplier_in_money is False or not ctx.supplier_ico_matches:
        out.append(check("DL-B2", "blocking", reason="not_in_money", ico=doc.supplier_ico))
    # DL-B3 the same supplier document already exists (Smart Mail side)
    if ctx.duplicate_of:
        out.append(check("DL-B3", "blocking", number=ctx.duplicate_of))
    # DL-B7 Σ lines (+ listed fees) = document total per VAT rate (± 0,01)
    if doc.vat_recap:
        sums: dict[Decimal, Decimal] = defaultdict(lambda: Decimal("0"))
        unknown = False
        for line in doc.lines:
            amount = line_amount(line)
            if amount is None or line.vat_rate is None:
                unknown = True
                continue
            sums[line.vat_rate.normalize()] += amount
        for row in doc.vat_recap:
            got = sums.get(row.rate.normalize(), Decimal("0"))
            if unknown or abs(got - row.base) > TOLERANCE:
                out.append(check("DL-B7", "blocking", rate=str(row.rate), lines=str(got), document=str(row.base)))
                break
    else:
        out.append(check("DL-B7", "warning", reason="no_vat_recap"))
    # DL-B8 all quantities > 0 (returns only in Money, D15)
    if any(line.qty is not None and line.qty <= 0 for line in doc.lines):
        out.append(check("DL-B8", "blocking"))
    if any(line.qty is None for line in doc.lines if not line.is_fee):
        out.append(check("DL-B8", "blocking", reason="qty_missing"))
    # DL-W4 issue date in the future or older than 30 days
    if doc.issued_on is None or doc.issued_on > ctx.today or doc.issued_on < ctx.today - timedelta(DATE_WINDOW_DAYS):
        out.append(check("DL-W4", "warning", issued_on=doc.issued_on.isoformat() if doc.issued_on else None))
    # DL-W5 fees are not written (D14)
    fees = [line for line in doc.lines if line.is_fee]
    if fees:
        total = sum((line_amount(f) or Decimal("0") for f in fees), Decimal("0"))
        out.append(check("DL-W5", "warning", sum=str(total)))
    if not [line for line in doc.lines if not line.is_fee]:
        out.append(check("DL-B4", "blocking", reason="no_lines"))
    return out
