"""W12-14 Nastavenia › Nákup a sklad (SETTINGS_SPEC 14, admin, scope G). Read-only towards Money: learned supplier codes
are only exported (CSV) for the purchasing clerk — the Money API has no write for supplier codes."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, or_, select

from app.api.mail import fail
from app.api.settings import require_admin
from app.auth.deps import DB, Auth, SettingsDep
from app.auth.models import Branch, Person
from app.core.audit import audit
from app.core.config import Settings
from app.money.models import MoneyCodebook, MoneyCompany
from app.purchasing import org_settings
from app.purchasing.models import DocumentLine, SupplierItemMapping
from app.purchasing.numbers import normalize_code
from app.purchasing.org_settings import PurchasingSettings

router = APIRouter(prefix="/api/settings/purchasing", tags=["settings-purchasing"])
Admin = Annotated[Person, Depends(require_admin)]
PAGE = 100


def _guard(settings: Settings) -> None:
    if not settings.feature_money:
        raise fail(404, "money_disabled")


class Choice(BaseModel):
    id: str
    label: str


class PurchasingOut(PurchasingSettings):
    branch_warehouses: list[str]  # info row „Predvolený sklad príjmu“ (11e)
    warehouses: list[Choice]  # Money warehouses for the rule table
    suppliers: list[Choice]  # suppliers with learned codes or rules (filter + rule table)


async def _out(db: DB) -> PurchasingOut:
    conf = await org_settings.load(db)
    wh = list(
        await db.scalars(select(MoneyCodebook).where(MoneyCodebook.kind == "warehouses").order_by(MoneyCodebook.code))
    )
    branches = list(await db.scalars(select(Branch).order_by(Branch.name)))
    codes = {str(w.money_id).lower(): w.code for w in wh}
    branch_wh = [
        f"{codes.get((b.money_warehouse_id or '').lower(), '–')} {b.name}" for b in branches if b.money_warehouse_id
    ]
    ids = set(await db.scalars(select(SupplierItemMapping.supplier_money_id).distinct())) | {
        r.supplier_money_id for r in conf.warehouse_rules
    }
    companies = (
        list(await db.scalars(select(MoneyCompany).where(MoneyCompany.money_id.in_(ids)).order_by(MoneyCompany.name)))
        if ids
        else []
    )
    return PurchasingOut(
        **conf.model_dump(),
        branch_warehouses=branch_wh,
        warehouses=[Choice(id=str(w.money_id), label=f"{w.code} – {w.name}") for w in wh],
        suppliers=[Choice(id=str(c.money_id), label=c.name) for c in companies],
    )


@router.get("")
async def get_purchasing(admin: Admin, db: DB, settings: SettingsDep) -> PurchasingOut:
    _guard(settings)
    return await _out(db)


@router.put("")
async def put_purchasing(body: dict[str, Any], admin: Admin, ctx: Auth, db: DB, settings: SettingsDep) -> PurchasingOut:
    _guard(settings)
    try:
        value = PurchasingSettings.model_validate(body)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise fail(422, "invalid_setting", field=".".join(str(p) for p in first["loc"]), msg=first["msg"]) from None
    known = set(await db.scalars(select(MoneyCodebook.money_id).where(MoneyCodebook.kind == "warehouses")))
    if any(r.warehouse_id not in known for r in value.warehouse_rules):
        raise fail(422, "warehouse_not_found")
    before = (await org_settings.load(db)).model_dump(mode="json")
    await org_settings.save(db, value)
    audit(
        db,
        "settings.purchasing",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="org_settings",
        object_id=org_settings.SECTION,
        details={"before": before, "after": value.model_dump(mode="json")},
    )
    await db.commit()
    return await _out(db)


class MappingOut(BaseModel):
    id: str
    supplier_id: str
    supplier_name: str | None
    code: str
    article_id: str
    article_name: str | None
    unit_factor: str
    confirmed_by: str | None
    confirmed_at: datetime | None
    uses_count: int


class MappingPage(BaseModel):
    items: list[MappingOut]
    total: int


async def _mapping_rows(db: DB, q: str, supplier: uuid.UUID | None, limit: int | None) -> tuple[list[MappingOut], int]:
    # the original supplier code and the Money article name come from the newest document line that used them
    line_code = (
        select(DocumentLine.supplier_code)
        .where(DocumentLine.article_id == SupplierItemMapping.article_id, DocumentLine.supplier_code.is_not(None))
        .order_by(DocumentLine.created_at.desc())
        .limit(1)
        .scalar_subquery()
    )
    article_name = (
        select(DocumentLine.raw["_article"]["name"].astext)
        .where(DocumentLine.article_id == SupplierItemMapping.article_id, DocumentLine.raw["_article"].is_not(None))
        .order_by(DocumentLine.created_at.desc())
        .limit(1)
        .scalar_subquery()
    )
    query = (
        select(SupplierItemMapping, MoneyCompany.name, Person.first_name, Person.last_name, line_code, article_name)
        .outerjoin(MoneyCompany, MoneyCompany.money_id == SupplierItemMapping.supplier_money_id)
        .outerjoin(Person, Person.id == SupplierItemMapping.confirmed_by_person_id)
    )
    if supplier:
        query = query.where(SupplierItemMapping.supplier_money_id == supplier)
    term = q.strip()
    if term:
        norm = normalize_code(term) or ""
        like = f"%{term.replace('%', '').replace('_', '')}%"
        query = query.where(
            or_(SupplierItemMapping.code_norm.contains(norm) if norm else False, article_name.ilike(like))
        )
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    query = query.order_by(MoneyCompany.name, SupplierItemMapping.code_norm)
    if limit:
        query = query.limit(limit)
    rows = []
    for m, supplier_name, first, last, code, name in (await db.execute(query)).all():
        rows.append(
            MappingOut(
                id=str(m.id),
                supplier_id=str(m.supplier_money_id),
                supplier_name=supplier_name,
                code=code if code and normalize_code(code) == m.code_norm else m.code_norm,
                article_id=str(m.article_id),
                article_name=name,
                unit_factor=_factor(m.unit_factor),
                confirmed_by=f"{first} {last[:1]}." if first else None,  # „Marek K.“ as in Figma
                confirmed_at=m.confirmed_at,
                uses_count=m.uses_count,
            )
        )
    return rows, int(total or 0)


@router.get("/mappings")
async def list_mappings(
    admin: Admin,
    db: DB,
    settings: SettingsDep,
    q: Annotated[str, Query(max_length=80)] = "",
    supplier: uuid.UUID | None = None,
) -> MappingPage:
    _guard(settings)
    rows, total = await _mapping_rows(db, q, supplier, PAGE)
    return MappingPage(items=rows, total=total)


class MappingPatch(BaseModel):
    unit_factor: str = Field(max_length=24)


@router.patch("/mappings/{mapping_id}")
async def patch_mapping(
    mapping_id: uuid.UUID, body: MappingPatch, admin: Admin, ctx: Auth, db: DB, settings: SettingsDep
) -> MappingOut:
    """Row drawer: only the unit conversion is edited; a wrong article is deleted and confirmed again on W6h."""
    _guard(settings)
    try:
        factor = Decimal(body.unit_factor.strip().replace(",", "."))
    except InvalidOperation:
        raise fail(422, "invalid_factor") from None
    if (
        not factor.is_finite()
        or factor <= 0
        or factor >= Decimal("1e12")
        or factor != factor.quantize(Decimal("0.000001"))
    ):
        raise fail(422, "invalid_factor")
    m = await db.get(SupplierItemMapping, mapping_id)
    if m is None:
        raise fail(404, "mapping_not_found")
    before = str(m.unit_factor)
    m.unit_factor = factor
    audit(
        db,
        "settings.supplier_mapping_changed",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="supplier_item_mapping",
        object_id=str(m.id),
        details={"before": before, "after": str(factor)},
    )
    await db.commit()
    rows, _ = await _mapping_rows(db, "", m.supplier_money_id, None)
    return next(r for r in rows if r.id == str(m.id))


@router.delete("/mappings/{mapping_id}", status_code=204)
async def delete_mapping(mapping_id: uuid.UUID, admin: Admin, ctx: Auth, db: DB, settings: SettingsDep) -> Response:
    _guard(settings)
    m = await db.get(SupplierItemMapping, mapping_id)
    if m is None:
        raise fail(404, "mapping_not_found")
    audit(
        db,
        "settings.supplier_mapping_deleted",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="supplier_item_mapping",
        object_id=str(m.id),
        details={"supplier": str(m.supplier_money_id), "supplier_code": m.code_norm, "article": str(m.article_id)},
    )
    await db.delete(m)
    await db.commit()
    return Response(status_code=204)


@router.get("/mappings.csv")
async def export_mappings(
    admin: Admin, ctx: Auth, db: DB, settings: SettingsDep, supplier: uuid.UUID | None = None
) -> Response:
    """Export CSV (UTF-8 with BOM, `;` — opens in Excel SK) for adding the codes to the Money article cards."""
    _guard(settings)
    rows, _ = await _mapping_rows(db, "", supplier, None)
    buf = io.StringIO()
    out = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    out.writerow(["Dodávateľ", "Kód dodávateľa", "Náš artikel", "ID artikla v Money", "Prepočet", "Potvrdil", "Dátum"])
    for r in rows:
        out.writerow(
            [
                _cell(r.supplier_name or r.supplier_id),
                _cell(r.code),
                _cell(r.article_name or ""),
                r.article_id,
                r.unit_factor.replace(".", ","),
                _cell(r.confirmed_by or ""),
                r.confirmed_at.date().isoformat() if r.confirmed_at else "",
            ]
        )
    audit(
        db,
        "settings.supplier_mappings_exported",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="supplier_item_mapping",
        object_id="csv",
        details={"rows": len(rows)},
    )
    await db.commit()
    return Response(
        content="﻿" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="kody-dodavatelov.csv"', "Cache-Control": "no-store"},
    )


def _cell(value: str) -> str:
    """CSV formula injection guard: a cell never starts with = + - @ (opened in Excel by the clerk)."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def _factor(value: Decimal) -> str:
    """`200.000000` → `200`, `12.500000` → `12.5` (shown as „1 : 200“ in the table)."""
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text
