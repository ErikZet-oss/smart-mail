"""Pilot 2026-11-23 (FABORY invoice): `1.000 ks` was read as 1 ks and the lines had no VAT rate, so DL-B7 blocked the
write. Quantities are cross-checked with the printed line total; a single VAT rate of the document fills the lines.
All companies, documents and amounts are fictional."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from app.purchasing.numbers import amount_matches, parse_qty
from app.purchasing.pdf_extract import doc_from_tool
from app.purchasing.validation import Context, validate

D = Decimal


def test_DL_W9_ambiguous_qty_read_as_thousands_when_the_line_total_says_so() -> None:
    assert parse_qty("1.000", D("0.04025"), D("40.25")) == D("1000")
    assert parse_qty("1,200", D("0.03225"), D("38.70")) == D("1200")
    assert parse_qty("2.000", D("0.01175"), D("23.50")) == D("2000")


def test_DL_W9_decimal_reading_stays_when_it_matches_or_nothing_decides() -> None:
    assert parse_qty("1,250", D("4.00"), D("5.00")) == D("1.25")  # 1,25 kg × 4 € = 5 €
    assert parse_qty("1.000", None, D("40.25")) == D("1.000")  # no price → parse_decimal default
    assert parse_qty("1.000", D("7"), D("99")) == D("1.000")  # neither reading matches → DL-W9 warns
    assert parse_qty("600", D("0.03075"), D("18.45")) == D("600")
    assert parse_qty("1 000", D("0.04025"), D("40.25")) == D("1000")


@given(st.text(max_size=12), st.decimals(0, 1000, places=4), st.decimals(0, 100000, places=2))
def test_parse_qty_never_raises(text: str, price: Decimal, total: Decimal) -> None:
    parse_qty(text, price, total)


def test_amount_matches_tolerates_rounded_unit_prices() -> None:
    assert amount_matches(D("600"), D("0.0307"), D("18.45"))  # printed 0,0307 → 18,42
    assert not amount_matches(D("1"), D("0.0402"), D("40.25"))


def _fabory() -> dict[str, object]:
    return {
        "kind": "invoice",
        "supplier_ico": "12345678",
        "number": "431215867",
        "issued_on": "2026-11-18",
        "vat_recap": [{"rate": "23", "base": "45,25"}],
        "lines": [
            {
                "name": "Skr. M8 x12 7380-2 Zn",
                "qty": "1.000",
                "unit": "ks",
                "unit_price": "0,04025",
                "line_total": "40,25",
            },
            {
                "name": "Podl. M6 A2 DIN 125a",
                "qty": "1.000",
                "unit": "ks",
                "unit_price": "0,0025",
                "line_total": "2,50",
            },
            {"name": "Doprava", "qty": "1", "unit": "ks", "line_total": "2,50", "is_fee": True},
        ],
    }


def test_DL_B7_single_vat_rate_fills_lines_and_the_sum_matches() -> None:
    doc = doc_from_tool(_fabory())
    assert [ln.vat_rate for ln in doc.lines] == [D("23")] * 3
    assert [ln.qty for ln in doc.lines[:2]] == [D("1000"), D("1000")]
    checks = validate(
        doc, Context(today=date(2026, 11, 23), supplier_in_money=True, supplier_ico_matches=True, duplicate_of=None)
    )
    assert not [c for c in checks if c["id"] in ("DL-B7", "DL-W9")]


def test_DL_B7_two_rates_without_line_rates_still_block() -> None:
    data = _fabory()
    data["vat_recap"] = [{"rate": "23", "base": "40,25"}, {"rate": "5", "base": "5,00"}]
    doc = doc_from_tool(data)
    assert doc.lines[0].vat_rate is None
    checks = validate(
        doc, Context(today=date(2026, 11, 23), supplier_in_money=True, supplier_ico_matches=True, duplicate_of=None)
    )
    assert any(c["id"] == "DL-B7" and c["level"] == "blocking" for c in checks)


def test_DL_W9_line_total_mismatch_is_a_warning() -> None:
    data = _fabory()
    data["lines"][0]["qty"] = "3"  # type: ignore[index]
    doc = doc_from_tool(data)
    checks = validate(
        doc, Context(today=date(2026, 11, 23), supplier_in_money=True, supplier_ico_matches=True, duplicate_of=None)
    )
    w9 = [c for c in checks if c["id"] == "DL-W9"]
    assert len(w9) == 1 and w9[0]["level"] == "warning" and w9[0]["params"]["line"] == 1
