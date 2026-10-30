"""MONEY_API §7 filter builder: every operator, unsafe values, and a property test that no value adds a condition."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.filters import OPS, UNSAFE, UnsafeFilterValue, all_, any_, cond


@pytest.mark.parametrize("op", sorted(OPS))
def test_every_operator(op: str) -> None:
    assert cond("Nazev", op, "Firma") == f"Nazev~{op}~Firma"  # type: ignore[arg-type]


def test_formats() -> None:
    gid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert cond("Firma_ID", "eq", gid) == f"Firma_ID~eq~{gid}"
    assert cond("DatumVystaveni", "gte", date(2026, 1, 2)) == "DatumVystaveni~gte~2026-01-02"
    assert cond("DatumVystaveni", "gte", datetime(2026, 1, 2, 13, 5)) == "DatumVystaveni~gte~2026-01-02"
    assert cond("UhradyZbyva", "gt", Decimal("0")) == "UhradyZbyva~gt~0"
    assert cond("CelkovaCastka", "gt", Decimal("1E+3")) == "CelkovaCastka~gt~1000"
    assert cond("Vyrizeno", "eq", True) == "Vyrizeno~eq~true"
    assert cond("Stav", "eq", 2) == "Stav~eq~2"


def test_and_or_grouping() -> None:
    a, b, c = cond("Misto", "eq", "Nitra"), cond("Nazev", "eq", "X"), cond("ICO", "eq", "123")
    assert any_(all_(a, b), c) == "(Misto~eq~Nitra#Nazev~eq~X)|(ICO~eq~123)"


@pytest.mark.parametrize("bad", ["a~b", "a#b", "a|b", "(a", "a)", "x~eq~y#Firma_ID~ne~0"])
def test_unsafe_values_are_rejected(bad: str) -> None:
    with pytest.raises(UnsafeFilterValue):
        cond("Nazev", "eq", bad)


@pytest.mark.parametrize("field", ["", "1A", "Na zev", "A~B", "A#B"])
def test_invalid_field_names(field: str) -> None:
    with pytest.raises(ValueError, match="field"):
        cond(field, "eq", "x")


def test_invalid_operator_and_non_finite_decimal() -> None:
    with pytest.raises(ValueError, match="operator"):
        cond("Nazev", "like", "x")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="finite"):
        cond("Suma", "gt", Decimal("NaN"))


@given(st.text())
def test_no_value_can_add_a_condition(value: str) -> None:
    try:
        built = cond("Nazev", "eq", value)
    except UnsafeFilterValue:
        assert any(c in UNSAFE for c in value)
        return
    assert built == f"Nazev~eq~{value}"
    assert built.count("~") == 2 and not any(c in built for c in "#|()")


@given(st.lists(st.text(), min_size=1, max_size=4))
def test_combined_filters_keep_their_structure(values: list[str]) -> None:
    safe = [v for v in values if not any(c in UNSAFE for c in v)]
    if not safe:
        return
    built = any_(*(cond("Kod", "eq", v) for v in safe))
    assert built.count("|") == len(safe) - 1
    assert built.count("(") == built.count(")") == len(safe)
    assert "#" not in built
