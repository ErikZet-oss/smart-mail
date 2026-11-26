"""SETTINGS_SPEC 11e (#247, D33) — „Vzorový dodací list pobočky“ and „Overiť nastavenie v Money“ (admin only).

The template is a received delivery note of the branch centre made by a person in Money. From it the write copies the
values the API has no codebook for (DOCUMENTS_SPEC §2.6): header IDs incl. `Group_ID` and, from its first stock line,
`TypObsahu`, `TypCeny`, `DruhPolozky_ID`, `SazbaDPH_ID` (+ its %), `DruhSazbyDPH`, `VazbaTypVazby` — never guessed.
Stored in `branches.dl_template_money_id` + `dl_template_values` + `dl_template_cached_at`. Since 2026-11-25 (Erik)
a branch has a second, optional template for foreign suppliers (`dl_template_foreign_*`, `kind=foreign`): the write
takes the one whose stock line has the VAT rate of the document's lines (`delivery_note.pick_template`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.api.mail import fail
from app.api.settings import require_admin
from app.auth.deps import DB, Auth, SettingsDep
from app.auth.models import Branch, Person
from app.core.audit import audit
from app.money.bridge_client import BridgeClient, BridgeUnavailable
from app.money.models import MoneyCodebook
from app.money.schemas import DeliveryNoteTemplate
from app.purchasing.delivery_note import SERIES_KEY, missing_template_values, template_rate

router = APIRouter(prefix="/api/settings/money/branches", tags=["settings-money"])
Admin = Annotated[Person, Depends(require_admin)]
LIST_ROWS = 20
Kind = Literal["main", "foreign"]
KindQ = Annotated[Kind, Query()]


class TemplateOut(BaseModel):
    id: str
    number: str | None
    supplier: str | None
    issued_on: date | None
    cached_at: datetime | None
    missing: list[str]  # values the write needs that the template does not have → DL-B6
    # pilot 2026-11-23: which branch the template note is from — centre and series as Money names them
    centre: str | None = None
    series: str | None = None
    vat_rate: str | None = None  # the VAT % of its stock line — decides which template a document uses
    price_type: int | None = None  # its line `TypCeny` (2 = „Iba základ“) — shown so the admin sees what is copied


class TemplateState(BaseModel):
    centre_set: bool
    template: TemplateOut | None
    money_available: bool = True


class NoteRowOut(BaseModel):
    id: str
    number: str | None
    supplier: str | None
    issued_on: date | None
    koncept: bool
    by_smart_mail: bool
    selected: bool


class TemplateIn(BaseModel):
    note_id: uuid.UUID
    kind: Kind = "main"


class VerifyRow(BaseModel):
    id: str  # centre | warehouse | price_list | series | template | template_foreign
    ok: bool | None  # None = not checked (no Money codebook for it in Smart Mail)
    detail: str | None = None


class VerifyOut(BaseModel):
    rows: list[VerifyRow]
    template: TemplateOut | None
    template_foreign: TemplateOut | None = None


async def _codebook_label(db: DB, kind: str, value: object) -> str | None:
    """`Kód – Názov` of a cached Money codebook value (centres, numerical series), None when unknown."""
    try:
        money_id = uuid.UUID(str(value)) if value else None
    except ValueError:
        return None
    if money_id is None:
        return None
    row = await db.scalar(select(MoneyCodebook).where(MoneyCodebook.kind == kind, MoneyCodebook.money_id == money_id))
    if row is None:
        return None
    return " – ".join(x for x in (row.code, row.name) if x) or None


def _stored(branch: Branch, kind: Kind) -> tuple[str | None, dict[str, Any], datetime | None]:
    if kind == "foreign":
        return (
            branch.dl_template_foreign_money_id,
            branch.dl_template_foreign_values or {},
            branch.dl_template_foreign_cached_at,
        )
    return branch.dl_template_money_id, branch.dl_template_values or {}, branch.dl_template_cached_at


async def _out(db: DB, branch: Branch, kind: Kind = "main") -> TemplateOut | None:
    money_id, values, cached_at = _stored(branch, kind)
    if not money_id or not values:
        return None
    header = values.get("header") or {}
    return TemplateOut(
        id=str(money_id),
        number=values.get("number"),
        supplier=values.get("supplier"),
        issued_on=values.get("issued_on"),
        cached_at=cached_at,
        missing=missing_template_values(values),
        centre=await _codebook_label(db, "centres", values.get("centre_id")),
        series=await _codebook_label(db, "numerical-series", header.get("CiselnaRada_ID")),
        vat_rate=template_rate(values),
        price_type=_int((values.get("line") or {}).get("TypCeny")),
    )


def _int(value: object) -> int | None:
    try:
        return int(str(value)) if value is not None else None
    except ValueError:
        return None


def _centre(branch: Branch) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(branch.money_centre_id)) if branch.money_centre_id else None
    except ValueError:
        return None


async def _branch(db: DB, branch_id: uuid.UUID) -> Branch:
    branch = await db.get(Branch, branch_id)
    if branch is None:
        raise fail(404, "branch_not_found")
    return branch


def _store(branch: Branch, tpl: DeliveryNoteTemplate | None, kind: Kind = "main") -> None:
    """`tpl` None = remove (only the template for foreign suppliers can be removed)."""
    money_id, values = (str(tpl.id), tpl.model_dump(mode="json")) if tpl else (None, None)
    cached_at = datetime.now(UTC) if tpl else None
    if kind == "foreign":
        branch.dl_template_foreign_money_id = money_id
        branch.dl_template_foreign_values = values
        branch.dl_template_foreign_cached_at = cached_at
    else:
        branch.dl_template_money_id = money_id
        branch.dl_template_values = values
        branch.dl_template_cached_at = cached_at


@router.get("/{branch_id}/dl-template")
async def get_template(
    branch_id: uuid.UUID, admin: Admin, ctx: Auth, db: DB, settings: SettingsDep, kind: KindQ = "main"
) -> TemplateState:
    """The stored template. No main template yet → the newest note of the centre not written by Smart Mail is taken
    as the default (SETTINGS 11e) and stored; the admin can pick another one. The template for foreign suppliers is
    never picked automatically."""
    branch = await _branch(db, branch_id)
    centre = _centre(branch)
    if centre is None or kind == "foreign" or branch.dl_template_money_id or not settings.feature_money:
        return TemplateState(centre_set=centre is not None, template=await _out(db, branch, kind))
    try:
        async with BridgeClient(settings) as bridge:
            rows = await bridge.received_notes(centre, LIST_ROWS)
            first = next((r for r in rows if not r.by_smart_mail), None)
            tpl = await bridge.delivery_note_template(first.id) if first else None
    except BridgeUnavailable:
        return TemplateState(centre_set=True, template=None, money_available=False)
    if tpl is not None:
        _store(branch, tpl)
        audit(
            db,
            "settings.dl_template",
            account_id=ctx.account.id,
            person_id=admin.id,
            object_type="branch",
            object_id=str(branch.id),
            details={"note_id": str(tpl.id), "number": tpl.number, "auto": True},
        )
        await db.commit()
    return TemplateState(centre_set=True, template=await _out(db, branch))


@router.get("/{branch_id}/dl-templates")
async def list_templates(
    branch_id: uuid.UUID,
    admin: Admin,
    db: DB,
    settings: SettingsDep,
    kind: KindQ = "main",
    number: Annotated[str, Query(max_length=40)] = "",
) -> list[NoteRowOut]:
    """„Vybrať iný“: the last 20 received delivery notes of the branch centre (Číslo · Dodávateľ · Dátum), or the
    note with the typed number (an older note, e.g. one from a foreign supplier)."""
    branch = await _branch(db, branch_id)
    centre = _centre(branch)
    if centre is None:
        raise fail(422, "centre_missing")
    try:
        async with BridgeClient(settings) as bridge:
            rows = await bridge.received_notes(centre, LIST_ROWS, number=number.strip() or None)
    except BridgeUnavailable as exc:
        raise fail(503, exc.code) from None
    selected = str(_stored(branch, kind)[0] or "").lower()
    return [
        NoteRowOut(
            id=str(r.id),
            number=r.number,
            supplier=r.supplier,
            issued_on=r.issued_on,
            koncept=r.koncept,
            by_smart_mail=r.by_smart_mail,
            selected=str(r.id).lower() == selected,
        )
        for r in rows
    ]


@router.put("/{branch_id}/dl-template")
async def put_template(
    branch_id: uuid.UUID, body: TemplateIn, admin: Admin, ctx: Auth, db: DB, settings: SettingsDep
) -> TemplateState:
    branch = await _branch(db, branch_id)
    centre = _centre(branch)
    if centre is None:
        raise fail(422, "centre_missing")
    try:
        async with BridgeClient(settings) as bridge:
            tpl = await bridge.delivery_note_template(body.note_id)
    except BridgeUnavailable as exc:
        raise fail(503, exc.code) from None
    if tpl is None:
        raise fail(404, "note_not_found")
    if tpl.centre_id != centre:
        raise fail(422, "template_other_centre")  # every value is copied — a note of another branch would be wrong
    values = tpl.model_dump(mode="json")
    missing = missing_template_values(values)
    if missing:
        raise fail(422, "template_incomplete", missing=missing)
    other_id = _stored(branch, "main" if body.kind == "foreign" else "foreign")[0]
    if other_id and str(other_id).lower() == str(tpl.id).lower():
        raise fail(422, "template_same_note")  # the second template must be another note (D35)
    before = _stored(branch, body.kind)[0]
    _store(branch, tpl, body.kind)
    audit(
        db,
        "settings.dl_template",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="branch",
        object_id=str(branch.id),
        details={"before": before, "note_id": str(tpl.id), "number": tpl.number, "kind": body.kind},
    )
    await db.commit()
    return TemplateState(centre_set=True, template=await _out(db, branch, body.kind))


@router.delete("/{branch_id}/dl-template")
async def delete_foreign_template(branch_id: uuid.UUID, admin: Admin, ctx: Auth, db: DB) -> TemplateState:
    """„Odstrániť“ the template for foreign suppliers (the main template can only be replaced, never removed)."""
    branch = await _branch(db, branch_id)
    before = branch.dl_template_foreign_money_id
    _store(branch, None, "foreign")
    audit(
        db,
        "settings.dl_template",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="branch",
        object_id=str(branch.id),
        details={"before": before, "note_id": None, "kind": "foreign"},
    )
    await db.commit()
    return TemplateState(centre_set=_centre(branch) is not None, template=None)


async def _in_codebook(db: DB, kind: str, value: str | None) -> bool | None:
    if not value:
        return False
    known = {str(r).lower() for r in await db.scalars(select(MoneyCodebook.money_id).where(MoneyCodebook.kind == kind))}
    return None if not known else value.strip().lower() in known


@router.post("/{branch_id}/verify")
async def verify_branch(branch_id: uuid.UUID, admin: Admin, db: DB, settings: SettingsDep) -> VerifyOut:
    """„Overiť nastavenie v Money“: centre, warehouse and series exist in the Money codebooks (read cache), the
    template is read again from Money (its cached values refreshed) and has every value the write needs. The price
    list has no codebook in Smart Mail yet — shown as not checked."""
    branch = await _branch(db, branch_id)
    values = branch.dl_template_values or {}
    series = (branch.series_overrides or {}).get(SERIES_KEY) or (values.get("header") or {}).get("CiselnaRada_ID")
    rows = [
        VerifyRow(id="centre", ok=await _in_codebook(db, "centres", branch.money_centre_id)),
        VerifyRow(id="warehouse", ok=await _in_codebook(db, "warehouses", branch.money_warehouse_id)),
        VerifyRow(id="price_list", ok=None if branch.money_price_list_id else False),
        VerifyRow(id="series", ok=await _in_codebook(db, "numerical-series", str(series) if series else None)),
    ]
    rows.append(await _verify_template(db, settings, branch, "main"))
    if branch.dl_template_foreign_money_id:
        rows.append(await _verify_template(db, settings, branch, "foreign"))
    return VerifyOut(rows=rows, template=await _out(db, branch), template_foreign=await _out(db, branch, "foreign"))


async def _verify_template(db: DB, settings: SettingsDep, branch: Branch, kind: Kind) -> VerifyRow:
    """The template read again from Money (its cached values refreshed): it exists and has every value the write
    needs."""
    row_id = "template_foreign" if kind == "foreign" else "template"
    money_id = _stored(branch, kind)[0]
    if not money_id:
        return VerifyRow(id=row_id, ok=False, detail="missing")
    try:
        async with BridgeClient(settings) as bridge:
            tpl = await bridge.delivery_note_template(uuid.UUID(str(money_id)))
    except (BridgeUnavailable, ValueError):
        return VerifyRow(id=row_id, ok=None, detail="money_unavailable")
    if tpl is None:
        return VerifyRow(id=row_id, ok=False, detail="not_found")
    _store(branch, tpl, kind)
    await db.commit()
    missing = missing_template_values(tpl.model_dump(mode="json"))
    return VerifyRow(id=row_id, ok=not missing, detail=",".join(missing) or None)
