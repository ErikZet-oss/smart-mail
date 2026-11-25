"""DL-B2 supplier lookup (pilot 2026-11-25, an EU supplier in Money was not found). Fictional companies only."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.money.models import MoneyCompany
from app.purchasing.item_matching import refresh_checks
from app.purchasing.models import SupplierDocument
from app.purchasing.supplier import find_supplier, ico_key

NOW = datetime(2026, 11, 25, 9, 0, tzinfo=UTC)


def _company(name: str, **kw: object) -> MoneyCompany:
    return MoneyCompany(
        money_id=uuid.uuid4(), name=name, emails=[], connections=[], active=kw.pop("active", True), synced_at=NOW, **kw
    )


def test_DL_B2_ico_key_ignores_spaces_dots_and_country_prefix() -> None:
    assert ico_key("CZ 123 45 678") == ico_key("12345678") == ico_key("cz12345678") == ico_key("123.45.678")
    assert ico_key("SK2020000000") == "2020000000"
    assert ico_key(None) == ""


async def test_DL_B2_find_supplier_by_ico_dic_or_icdph_in_any_spelling(db: AsyncSession) -> None:
    by_ico = _company("Fiktívna CZ s.r.o.", ico="123 45 678")
    by_dic = _company("Fiktívna bez IČO s.r.o.", ico=None, dic="CZ87654321")
    gone = _company("Zrušená s.r.o.", ico="11122233", active=False)
    db.add_all([by_ico, by_dic, gone])
    await db.commit()
    for spelled in ("12345678", "CZ12345678", "CZ 123 45 678"):
        found = await find_supplier(db, spelled)
        assert found is not None and found.money_id == by_ico.money_id, spelled
    found = await find_supplier(db, "87654321")  # the card has only DIČ CZ87654321
    assert found is not None and found.money_id == by_dic.money_id
    assert await find_supplier(db, "11122233") is None  # inactive card
    assert await find_supplier(db, "123") is None  # too short to be a company number
    assert await find_supplier(db, None) is None


async def test_DL_B2_supplier_added_to_money_later_is_found_on_refresh(db: AsyncSession) -> None:
    doc = SupplierDocument(
        source="upload", kind="invoice", filename="fa.pdf", content_type="application/pdf", sha256="0" * 64,
        storage_key="k", status="missing_data", supplier_ico="CZ12345678",
        validation=[{"id": "DL-B2", "level": "blocking", "params": {"reason": "not_in_money", "ico": "CZ12345678"}}],
    )  # fmt: skip
    db.add(doc)
    await db.commit()
    await refresh_checks(db, doc, [])
    assert [c["params"]["reason"] for c in doc.validation if c["id"] == "DL-B2"] == ["not_in_money"]  # one row only
    company = _company("Fiktívna CZ s.r.o.", ico="12345678")
    db.add(company)
    await db.commit()
    await refresh_checks(db, doc, [])  # „Znova spárovať“ after the cache sync
    assert doc.supplier_money_id == company.money_id
    assert not [c for c in doc.validation if c["id"] == "DL-B2"]
