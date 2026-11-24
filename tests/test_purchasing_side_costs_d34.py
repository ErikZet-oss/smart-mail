"""D34 (Erik, 24 Nov 2026): fees (doprava, balné, rozbalné …) become side costs of the received delivery note, evenly
by the number of stock lines — like Money's „Náklady – rovnomerne podľa počtu položiek“. All values fictional."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from app.auth.models import Branch
from app.purchasing.delivery_note import BranchValues, build_payload, side_costs, split_evenly
from app.purchasing.models import DocumentLine, SupplierDocument
from tests.test_purchasing_247 import CENTRE, SERIES, WAREHOUSE, template

D = Decimal


def test_D34_split_evenly_in_cents_that_add_up() -> None:
    assert split_evenly(D("2.50"), 3) == [D("0.83"), D("0.83"), D("0.84")]
    assert split_evenly(D("2.50"), 15) == [D("0.16")] * 5 + [D("0.17")] * 10
    assert split_evenly(D("0"), 3) == [D("0")] * 3 and split_evenly(D("5"), 0) == []


@given(st.decimals(min_value=D("0.01"), max_value=D("10000"), places=2), st.integers(min_value=1, max_value=500))
def test_D34_split_always_adds_up_and_differs_by_one_cent_at_most(total: Decimal, count: int) -> None:
    parts = split_evenly(total, count)
    assert sum(parts, D("0")) == total and len(parts) == count
    assert max(parts) - min(parts) <= D("0.01") and all(p >= 0 for p in parts)


def _line(n: int, qty: str, total: str, *, fee: bool = False, status: str = "matched") -> DocumentLine:
    return DocumentLine(
        line_no=n,
        name="Doprava" if fee else f"Skrutka {n}",
        is_fee=fee,
        qty=D(qty),
        unit_price=D(total) / D(qty),
        line_total=D(total),
        unit_factor=D("1"),
        line_status=status,
        article_id=None if fee or status == "non_stock" else uuid.UUID(int=2),
        warehouse_id=None,
        raw={},
    )


def _payload(lines: list[DocumentLine]) -> dict[str, object]:
    doc = SupplierDocument(
        kind="invoice", doc_number="FA-1", supplier_money_id=uuid.UUID(int=1), idempotency_key="c" * 32, filename="x"
    )
    branch = Branch(
        name="B",
        money_centre_id=CENTRE,
        money_warehouse_id=WAREHOUSE,
        dl_template_values={**template(), "text_line": {"TypObsahu": 0}},
    )
    payload, _ = build_payload(
        doc,
        lines,
        branch,
        BranchValues(CENTRE, WAREHOUSE, SERIES),
        now=datetime(2026, 11, 24, 9, tzinfo=UTC),
        issue_on_approval=False,
        with_address=False,
    )
    return payload


def test_D34_fees_go_to_the_header_and_evenly_into_the_stock_lines() -> None:
    lines = [
        _line(1, "10", "10.00"),
        _line(2, "20", "20.00"),
        _line(3, "1", "1.50", fee=True),  # doprava
        _line(4, "30", "30.00"),
        _line(5, "1", "1.00", fee=True),  # balné
        _line(6, "1", "4.00", status="non_stock"),  # a text line gets no share
    ]
    payload = _payload(lines)
    assert payload["DodatecnePorizovaciNaklady"] == "2.50"
    items = payload["Polozky"]
    assert isinstance(items, list) and len(items) == 4  # fees are not lines
    a, b, c, text = items
    assert [a["CelkoveVedlejsiNaklady"], b["CelkoveVedlejsiNaklady"], c["CelkoveVedlejsiNaklady"]] == [
        "0.83",
        "0.83",
        "0.84",
    ]
    assert a["JednotkoveVedlejsiNaklady"] == "0.0830" and a["JednotkovaPorizovaciCena"] == "1.0830"  # (10 + 0.83) / 10
    assert c["JednotkoveVedlejsiNaklady"] == "0.0280" and c["JednotkovaPorizovaciCena"] == "1.0280"
    assert "CelkoveVedlejsiNaklady" not in text
    assert side_costs(lines) == D("2.50")


def test_D34_no_fees_or_no_stock_line_means_no_side_costs() -> None:
    plain = _payload([_line(1, "10", "10.00")])
    assert "DodatecnePorizovaciNaklady" not in plain and "CelkoveVedlejsiNaklady" not in plain["Polozky"][0]  # type: ignore[index]
    only_text = [_line(1, "1", "4.00", status="non_stock"), _line(2, "1", "2.50", fee=True)]
    assert side_costs(only_text) == D("0") and "DodatecnePorizovaciNaklady" not in _payload(only_text)
