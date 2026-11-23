"""SETTINGS_SPEC 14 Nákup a sklad — company-wide values in `org_settings` (section `purchasing`, no new table)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import OrgSettings

SECTION = "purchasing"
ConfirmRole = Literal["warehouse", "admin", "accounting", "sales"]
CONFIRM_ROLES = ("warehouse", "admin", "accounting", "sales")


def _default_roles() -> list[ConfirmRole]:
    return ["warehouse", "admin"]


class WarehouseRule(BaseModel):
    """„Sklad podľa dodávateľa“: lines of this supplier go to another Money warehouse (D18, DL-W8 still warns)."""

    supplier_money_id: uuid.UUID
    warehouse_id: uuid.UUID


class PurchasingSettings(BaseModel):
    price_diff_pct: Decimal = Field(default=Decimal("10"), ge=0, le=100, max_digits=5, decimal_places=2)
    qty_diff_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100, max_digits=5, decimal_places=2)
    confirm_roles: list[ConfirmRole] = Field(default_factory=lambda: _default_roles(), min_length=1)
    issue_date: Literal["supplier", "approval"] = "supplier"
    warehouse_rules: list[WarehouseRule] = Field(default_factory=list, max_length=200)
    create_article: bool = False  # D32 (#239) „Zakladanie artiklov v Money“ from the W6h drawer; default off
    write_delivery_notes: bool = False  # D33 (#247) „Zápis dodacích listov do Money (koncept)“; default off

    @field_validator("confirm_roles")
    @classmethod
    def _unique_roles(cls, v: list[ConfirmRole]) -> list[ConfirmRole]:
        return list(dict.fromkeys(v))

    @field_validator("warehouse_rules")
    @classmethod
    def _one_rule_per_supplier(cls, v: list[WarehouseRule]) -> list[WarehouseRule]:
        if len({r.supplier_money_id for r in v}) != len(v):
            raise ValueError("duplicate_supplier_rule")
        return v


async def load(db: AsyncSession) -> PurchasingSettings:
    row = await db.scalar(select(OrgSettings).where(OrgSettings.section == SECTION))
    return PurchasingSettings.model_validate(row.data) if row and row.data else PurchasingSettings()


async def save(db: AsyncSession, value: PurchasingSettings) -> None:
    row = await db.scalar(select(OrgSettings).where(OrgSettings.section == SECTION))
    if row is None:
        row = OrgSettings(section=SECTION, data={})
        db.add(row)
    row.data = value.model_dump(mode="json")


STATE_SECTION = "purchasing_state"  # values the app learns itself — never edited in Settings


class PurchasingState(BaseModel):
    # MONEY_API 5.5.7: a koncept read back without the supplier address → the next writes send Adresa*/IC/DIC/ICDPH
    send_supplier_address: bool = False


async def load_state(db: AsyncSession) -> PurchasingState:
    row = await db.scalar(select(OrgSettings).where(OrgSettings.section == STATE_SECTION))
    return PurchasingState.model_validate(row.data) if row and row.data else PurchasingState()


async def save_state(db: AsyncSession, value: PurchasingState) -> None:
    row = await db.scalar(select(OrgSettings).where(OrgSettings.section == STATE_SECTION))
    if row is None:
        row = OrgSettings(section=STATE_SECTION, data={})
        db.add(row)
    row.data = value.model_dump(mode="json")
