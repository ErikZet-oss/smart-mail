"""SETTINGS_SPEC 11e (#247, D33) — „Vzorový dodací list pobočky“ and „Overiť nastavenie v Money“ (admin only).

The template is a received delivery note of the branch centre made by a person in Money. From it the write copies the
values the API has no codebook for (DOCUMENTS_SPEC §2.6): header IDs incl. `Group_ID` and, from its first stock line,
`TypObsahu`, `TypCeny`, `DruhPolozky_ID`, `SazbaDPH_ID` (+ its %), `DruhSazbyDPH`, `VazbaTypVazby` — never guessed.
Stored in `branches.dl_template_money_id` + `dl_template_values` + `dl_template_cached_at` (no migration).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
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
from app.purchasing.delivery_note import SERIES_KEY, missing_template_values

router = APIRouter(prefix="/api/settings/money/branches", tags=["settings-money"])
Admin = Annotated[Person, Depends(require_admin)]
LIST_ROWS = 20


class TemplateOut(BaseModel):
    id: str
    number: str | None
    supplier: str | None
    issued_on: date | None
    cached_at: datetime | None
    missing: list[str]  # values the write needs that the template does not have → DL-B6


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


class VerifyRow(BaseModel):
    id: str  # centre | warehouse | price_list | series | template
    ok: bool | None  # None = not checked (no Money codebook for it in Smart Mail)
    detail: str | None = None


class VerifyOut(BaseModel):
    rows: list[VerifyRow]
    template: TemplateOut | None


def _out(branch: Branch) -> TemplateOut | None:
    values = branch.dl_template_values or {}
    if not branch.dl_template_money_id or not values:
        return None
    return TemplateOut(
        id=str(branch.dl_template_money_id),
        number=values.get("number"),
        supplier=values.get("supplier"),
        issued_on=values.get("issued_on"),
        cached_at=branch.dl_template_cached_at,
        missing=missing_template_values(values),
    )


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


def _store(branch: Branch, tpl: DeliveryNoteTemplate) -> None:
    branch.dl_template_money_id = str(tpl.id)
    branch.dl_template_values = tpl.model_dump(mode="json")
    branch.dl_template_cached_at = datetime.now(UTC)


@router.get("/{branch_id}/dl-template")
async def get_template(branch_id: uuid.UUID, admin: Admin, ctx: Auth, db: DB, settings: SettingsDep) -> TemplateState:
    """The stored template. None stored yet → the newest note of the centre not written by Smart Mail is taken as the
    default (SETTINGS 11e) and stored; the admin can pick another one."""
    branch = await _branch(db, branch_id)
    centre = _centre(branch)
    if centre is None or branch.dl_template_money_id or not settings.feature_money:
        return TemplateState(centre_set=centre is not None, template=_out(branch))
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
    return TemplateState(centre_set=True, template=_out(branch))


@router.get("/{branch_id}/dl-templates")
async def list_templates(branch_id: uuid.UUID, admin: Admin, db: DB, settings: SettingsDep) -> list[NoteRowOut]:
    """„Vybrať iný“: the last 20 received delivery notes of the branch centre (Číslo · Dodávateľ · Dátum)."""
    branch = await _branch(db, branch_id)
    centre = _centre(branch)
    if centre is None:
        raise fail(422, "centre_missing")
    try:
        async with BridgeClient(settings) as bridge:
            rows = await bridge.received_notes(centre, LIST_ROWS)
    except BridgeUnavailable as exc:
        raise fail(503, exc.code) from None
    selected = str(branch.dl_template_money_id or "").lower()
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
    missing = missing_template_values(tpl.model_dump(mode="json"))
    if missing:
        raise fail(422, "template_incomplete", missing=missing)
    before = branch.dl_template_money_id
    _store(branch, tpl)
    audit(
        db,
        "settings.dl_template",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="branch",
        object_id=str(branch.id),
        details={"before": before, "note_id": str(tpl.id), "number": tpl.number},
    )
    await db.commit()
    return TemplateState(centre_set=True, template=_out(branch))


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
    template_row = VerifyRow(id="template", ok=False, detail="missing")
    if branch.dl_template_money_id:
        try:
            async with BridgeClient(settings) as bridge:
                tpl = await bridge.delivery_note_template(uuid.UUID(str(branch.dl_template_money_id)))
        except (BridgeUnavailable, ValueError):
            template_row = VerifyRow(id="template", ok=None, detail="money_unavailable")
        else:
            if tpl is None:
                template_row = VerifyRow(id="template", ok=False, detail="not_found")
            else:
                _store(branch, tpl)
                missing = missing_template_values(tpl.model_dump(mode="json"))
                template_row = VerifyRow(id="template", ok=not missing, detail=",".join(missing) or None)
                await db.commit()
    rows.append(template_row)
    return VerifyOut(rows=rows, template=_out(branch))
