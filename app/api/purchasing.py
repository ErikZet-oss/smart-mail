"""Phase 4a — supplier documents (W6u upload, W6e list, detail for W6h in 4b). Read-only: nothing is written to Money.

Roles: warehouse, accounting, admin (SCREENS_SPEC W6e/W6h). Only with FEATURE_MONEY.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Query, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.ai.provider import get_llm_provider
from app.api.mail import fail
from app.auth.deps import DB, ActivePerson, Auth, SettingsDep
from app.auth.models import Branch, Role
from app.core.audit import audit
from app.core.config import Settings
from app.core.content_disposition import content_disposition_attachment
from app.mail import storage
from app.mail.clamav import scan_bytes
from app.money.bridge_client import BridgeClient, BridgeUnavailable
from app.money.models import MoneyCodebook, MoneyCompany
from app.money.schemas import Article
from app.purchasing import org_settings
from app.purchasing.item_matching import confirm_article, load_lines, mark_non_stock, match_document, needs_matching
from app.purchasing.models import DocumentLine, SupplierDocument
from app.purchasing.service import MAX_BYTES, DocumentRejected, Source, ingest

router = APIRouter(prefix="/api/purchasing", tags=["purchasing"])
ROLES = frozenset({Role.warehouse, Role.accounting, Role.admin})
PAGE = 50


def _guard(settings: Settings, person: Any) -> None:
    if not settings.feature_money:
        raise fail(404, "money_disabled")
    if person.role not in ROLES:
        raise fail(403, "role_not_allowed")


class DocumentOut(BaseModel):
    id: str
    source: str
    kind: str
    status: str
    filename: str
    branch_id: str | None
    branch_name: str | None
    centre_code: str | None  # Money centre of the branch (W6e column „Stredisko“)
    warehouse_code: str | None  # branch warehouse (W6e column „Kód skladu“)
    supplier_name: str | None
    supplier_ico: str | None
    supplier_money_id: str | None
    doc_number: str | None
    doc_date: date | None
    currency: str | None
    total: str | None
    lines: int
    blocking: int
    warnings: int
    error: str | None
    created_at: datetime


class LineOut(BaseModel):
    line_no: int
    supplier_code: str | None
    ean: str | None
    name: str
    qty: str | None
    unit: str | None
    unit_price: str | None
    vat_rate: str | None
    line_total: str | None
    is_fee: bool
    line_status: str
    article_id: str | None = None
    match_method: str | None = None
    unit_factor: str | None = None
    warehouse_id: str | None = None
    candidates: list[dict[str, Any]] = []
    article: dict[str, Any] | None = None  # Money article snapshot: name, catalog, ean, unit, code
    qty_our: str | None = None  # quantity in the article unit = qty × unit factor (never rounded to packaging)
    price_our: str | None = None  # net unit price per article unit = unit price / factor, 4 dp
    warehouse_code: str | None = None


class DocumentDetail(DocumentOut):
    delivery_note_number: str | None
    order_reference: str | None
    vat_recap: list[dict[str, Any]]
    fees: list[dict[str, Any]]
    extract_method: str | None
    field_confidence: dict[str, Any]
    checks: list[dict[str, Any]]
    message_id: str | None
    version: int
    money_available: bool = True
    supplier: dict[str, Any] | None  # from the Money cache (read-only): name, ico, dic, icdph
    series: str | None  # branch series for received delivery notes (SETTINGS 11e)
    template: dict[str, Any]  # cached values of the branch template document (4c fills them)
    warehouses: list[dict[str, str]]  # Money warehouses for the line select (D18)
    items: list[LineOut]


class DocumentPage(BaseModel):
    items: list[DocumentOut]
    total: int


def _s(v: Any) -> str | None:
    return None if v is None else str(v)


@dataclass(frozen=True, slots=True)
class BranchInfo:
    name: str
    centre: str | None
    warehouse: str | None


async def _branches(db: DB) -> dict[uuid.UUID, BranchInfo]:
    codes = {
        (row.kind, str(row.money_id)): row.code
        for row in await db.scalars(select(MoneyCodebook).where(MoneyCodebook.kind.in_(("centres", "warehouses"))))
    }
    return {
        b.id: BranchInfo(
            name=b.name,
            centre=codes.get(("centres", (b.money_centre_id or "").lower())),
            warehouse=codes.get(("warehouses", (b.money_warehouse_id or "").lower())),
        )
        for b in await db.scalars(select(Branch))
    }


def _out(doc: SupplierDocument, lines: int, branches: dict[uuid.UUID, BranchInfo] | None = None) -> dict[str, Any]:
    checks = doc.validation or []
    info = (branches or {}).get(doc.branch_id) if doc.branch_id else None
    return {
        "id": str(doc.id),
        "source": doc.source,
        "kind": doc.kind,
        "status": doc.status,
        "filename": doc.filename,
        "branch_id": _s(doc.branch_id),
        "branch_name": info.name if info else None,
        "centre_code": info.centre if info else None,
        "warehouse_code": info.warehouse if info else None,
        "supplier_name": doc.supplier_name,
        "supplier_ico": doc.supplier_ico,
        "supplier_money_id": _s(doc.supplier_money_id),
        "doc_number": doc.doc_number,
        "doc_date": doc.doc_date,
        "currency": doc.currency,
        "total": _s(doc.total),
        "lines": lines,
        "blocking": sum(1 for c in checks if c.get("level") == "blocking"),
        "warnings": sum(1 for c in checks if c.get("level") == "warning"),
        "error": doc.error,
        "created_at": doc.created_at,
    }


@router.post("/documents")
async def upload_document(
    ctx: Auth,
    person: ActivePerson,
    db: DB,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
) -> DocumentOut:
    """W6u „Nahrať doklad“: a supplier invoice or delivery note (PDF / ISDOC / UBL) → extracted for review."""
    _guard(settings, person)
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise fail(413, "document_too_large")
    if await scan_bytes(settings, data) == "infected":
        raise fail(422, "document_infected")
    try:
        doc = await ingest(
            db,
            settings,
            get_llm_provider(settings),
            Source(
                data=data,
                filename=file.filename or "doklad",
                content_type=file.content_type or "application/octet-stream",
                source="upload",
                person_id=person.id,
                person_branch_id=person.branch_id,
            ),
        )
    except DocumentRejected as exc:
        raise fail(422, str(exc)) from None
    audit(
        db,
        "purchasing.document_uploaded",
        account_id=ctx.account.id,
        person_id=person.id,
        object_type="document",
        object_id=str(doc.id),
    )
    await db.commit()
    count = await db.scalar(select(func.count()).select_from(DocumentLine).where(DocumentLine.document_id == doc.id))
    return DocumentOut(**_out(doc, int(count or 0)))


@router.get("/documents")
async def list_documents(
    person: ActivePerson,
    db: DB,
    settings: SettingsDep,
    status: Annotated[Literal["open", "all", "duplicate", "ignored"], Query()] = "open",
    page: Annotated[int, Query(ge=1)] = 1,
    q_text: Annotated[str, Query(alias="q", max_length=80)] = "",
) -> DocumentPage:
    """W6e: newest first. „open“ = still to review (not ignored, not duplicate)."""
    _guard(settings, person)
    q = select(SupplierDocument)
    if status == "open":
        q = q.where(SupplierDocument.status.notin_(("ignored", "duplicate")))
    elif status in ("duplicate", "ignored"):
        q = q.where(SupplierDocument.status == status)
    term = q_text.strip()
    if term:
        like = f"%{term.replace('%', '').replace('_', '')}%"
        q = q.where(
            or_(
                SupplierDocument.doc_number.ilike(like),
                SupplierDocument.supplier_name.ilike(like),
                SupplierDocument.supplier_ico.ilike(like),
                SupplierDocument.filename.ilike(like),
            )
        )
    total = await db.scalar(select(func.count()).select_from(q.subquery()))
    docs = list(await db.scalars(q.order_by(SupplierDocument.created_at.desc()).limit(PAGE).offset((page - 1) * PAGE)))
    counts = (
        dict(
            (
                await db.execute(
                    select(DocumentLine.document_id, func.count())
                    .where(DocumentLine.document_id.in_([d.id for d in docs]))
                    .group_by(DocumentLine.document_id)
                )
            ).all()
        )
        if docs
        else {}
    )
    branches = await _branches(db)
    return DocumentPage(
        items=[DocumentOut(**_out(d, int(counts.get(d.id, 0)), branches)) for d in docs], total=int(total or 0)
    )


async def _get(db: DB, doc_id: uuid.UUID) -> SupplierDocument:
    doc = await db.get(SupplierDocument, doc_id)
    if doc is None:
        raise fail(404, "document_not_found")
    return doc


Q4 = Decimal("0.0001")


def _line(ln: DocumentLine, wh_codes: dict[str, str]) -> LineOut:
    factor = ln.unit_factor
    qty_our = ln.qty * factor if ln.qty is not None and factor else None
    price_our = (ln.unit_price / factor).quantize(Q4, ROUND_HALF_UP) if ln.unit_price is not None and factor else None
    return LineOut(
        line_no=ln.line_no,
        supplier_code=ln.supplier_code,
        ean=ln.ean,
        name=ln.name,
        qty=_s(ln.qty),
        unit=ln.unit,
        unit_price=_s(ln.unit_price),
        vat_rate=_s(ln.vat_rate),
        line_total=_s(ln.line_total),
        is_fee=ln.is_fee,
        line_status=ln.line_status,
        article_id=_s(ln.article_id),
        match_method=ln.match_method,
        unit_factor=_s(ln.unit_factor),
        warehouse_id=_s(ln.warehouse_id),
        candidates=ln.candidates or [],
        article=(ln.raw or {}).get("_article"),
        qty_our=_s(qty_our.quantize(Q4) if qty_our is not None else None),
        price_our=_s(price_our),
        warehouse_code=wh_codes.get(str(ln.warehouse_id).lower()) if ln.warehouse_id else None,
    )


async def _detail(db: DB, doc: SupplierDocument, *, money_available: bool = True) -> DocumentDetail:
    lines = await load_lines(db, doc)
    warehouses = [
        {"id": str(w.money_id), "code": w.code or "", "name": w.name or ""}
        for w in await db.scalars(
            select(MoneyCodebook).where(MoneyCodebook.kind == "warehouses").order_by(MoneyCodebook.code)
        )
    ]
    wh_codes = {w["id"].lower(): w["code"] for w in warehouses}
    company = (
        await db.scalar(select(MoneyCompany).where(MoneyCompany.money_id == doc.supplier_money_id))
        if doc.supplier_money_id
        else None
    )
    branch = await db.get(Branch, doc.branch_id) if doc.branch_id else None
    series = (branch.series_overrides or {}).get("received_delivery_note") if branch else None
    return DocumentDetail(
        **_out(doc, len(lines), await _branches(db)),
        delivery_note_number=doc.delivery_note_number,
        order_reference=doc.order_reference,
        vat_recap=doc.vat_recap or [],
        fees=doc.fees or [],
        extract_method=doc.extract_method,
        field_confidence=doc.field_confidence or {},
        checks=doc.validation or [],
        message_id=_s(doc.message_id),
        version=doc.version,
        money_available=money_available,
        supplier=(
            {"name": company.name, "ico": company.ico, "dic": company.dic, "icdph": company.icdph} if company else None
        ),
        series=str(series) if series else None,
        template=(branch.dl_template_values or {}) if branch else {},
        warehouses=warehouses,
        items=[_line(ln, wh_codes) for ln in lines],
    )


MATCHABLE = ("needs_review", "missing_data")


@router.get("/documents/{doc_id}")
async def get_document(doc_id: uuid.UUID, person: ActivePerson, db: DB, settings: SettingsDep) -> DocumentDetail:
    """W6h. The first open runs the item matching (read-only bridge calls); Money down → lines stay as they are."""
    _guard(settings, person)
    doc = await _get(db, doc_id)
    available = True
    if doc.status in MATCHABLE and needs_matching(await load_lines(db, doc)):
        async with BridgeClient(settings) as bridge:
            available = await match_document(db, bridge, doc)
        await db.commit()
    return await _detail(db, doc, money_available=available)


@router.post("/documents/{doc_id}/match")
async def rematch_document(doc_id: uuid.UUID, person: ActivePerson, db: DB, settings: SettingsDep) -> DocumentDetail:
    """„Znova spárovať“: re-runs the cascade for lines not decided by a person."""
    _guard(settings, person)
    doc = await _get(db, doc_id)
    if doc.status not in MATCHABLE:
        raise fail(409, "document_not_reviewable")
    async with BridgeClient(settings) as bridge:
        available = await match_document(db, bridge, doc)
    await db.commit()
    return await _detail(db, doc, money_available=available)


class ConfirmArticleIn(BaseModel):
    article_id: uuid.UUID
    unit_factor: Decimal = Field(default=Decimal("1"), gt=0, max_digits=18, decimal_places=6)
    learn: bool = True  # remember supplier code → article for this supplier
    warehouse_id: uuid.UUID | None = None  # another Money warehouse than the branch one (DL-W8, D18)
    version: int


class NonStockIn(BaseModel):
    version: int


async def _line_for(db: DB, doc: SupplierDocument, line_no: int, version: int, person: Any) -> DocumentLine:
    if str(person.role) not in (await org_settings.load(db)).confirm_roles:
        raise fail(403, "confirm_role_not_allowed")  # Settings 14 „Kto potvrdzuje párovanie položiek“
    if doc.status not in MATCHABLE:
        raise fail(409, "document_not_reviewable")
    if doc.version != version:
        raise fail(409, "version_conflict")
    line = await db.scalar(
        select(DocumentLine).where(DocumentLine.document_id == doc.id, DocumentLine.line_no == line_no)
    )
    if line is None or line.is_fee:
        raise fail(404, "line_not_found")
    return line


@router.post("/documents/{doc_id}/lines/{line_no}/article")
async def confirm_line_article(
    doc_id: uuid.UUID,
    line_no: int,
    body: ConfirmArticleIn,
    ctx: Auth,
    person: ActivePerson,
    db: DB,
    settings: SettingsDep,
) -> DocumentDetail:
    """The person picks the Money article of a line; with `learn` the supplier code is remembered (DL-W6 until it is
    in the Money article card)."""
    _guard(settings, person)
    doc = await _get(db, doc_id)
    line = await _line_for(db, doc, line_no, body.version, person)
    try:
        async with BridgeClient(settings) as bridge:
            article = await bridge.article(body.article_id)
    except BridgeUnavailable as exc:
        raise fail(503, exc.code) from None
    if article is None or article.inactive:
        raise fail(422, "article_not_found")
    if body.warehouse_id is not None and not await db.scalar(
        select(MoneyCodebook.id).where(MoneyCodebook.kind == "warehouses", MoneyCodebook.money_id == body.warehouse_id)
    ):
        raise fail(422, "warehouse_not_found")
    await confirm_article(
        db, doc, line, article, body.unit_factor, person.id, learn=body.learn, warehouse_id=body.warehouse_id
    )
    audit(
        db,
        "purchasing.line_article_confirmed",
        account_id=ctx.account.id,
        person_id=person.id,
        object_type="document",
        object_id=str(doc.id),
        details={"line_no": line_no, "article_id": str(article.id), "learn": body.learn},
    )
    await db.commit()
    return await _detail(db, doc)


@router.post("/documents/{doc_id}/lines/{line_no}/non-stock")
async def line_non_stock(
    doc_id: uuid.UUID,
    line_no: int,
    body: NonStockIn,
    ctx: Auth,
    person: ActivePerson,
    db: DB,
    settings: SettingsDep,
) -> DocumentDetail:
    """„Neskladová položka“ (DL-B4): the line is written without an article in 4c."""
    _guard(settings, person)
    doc = await _get(db, doc_id)
    line = await _line_for(db, doc, line_no, body.version, person)
    await mark_non_stock(db, doc, line)
    audit(
        db,
        "purchasing.line_non_stock",
        account_id=ctx.account.id,
        person_id=person.id,
        object_type="document",
        object_id=str(doc.id),
        details={"line_no": line_no},
    )
    await db.commit()
    return await _detail(db, doc)


@router.get("/articles")
async def search_articles(
    person: ActivePerson,
    settings: SettingsDep,
    q: Annotated[str, Query(min_length=2, max_length=80)],
) -> list[Article]:
    """Article picker of W6h: by EAN (digits only), else by code / catalog, else by name."""
    _guard(settings, person)
    term = q.strip()
    if set(term) & set("~#|()"):
        raise fail(422, "unsafe_query")
    try:
        async with BridgeClient(settings) as bridge:
            if term.isdigit() and len(term) >= 8:
                found = await bridge.search_articles(ean=term)
                if found:
                    return found
            found = await bridge.search_articles(code=term)
            return found or await bridge.search_articles(q=term)
    except BridgeUnavailable as exc:
        raise fail(503, exc.code) from None


@router.get("/documents/{doc_id}/file")
async def document_file(doc_id: uuid.UUID, person: ActivePerson, db: DB, settings: SettingsDep) -> Response:
    """The original supplier file (W6h right panel „Originál“)."""
    _guard(settings, person)
    doc = await _get(db, doc_id)
    data = storage.get_bytes(settings, doc.storage_key)
    if data is None:
        raise fail(404, "file_missing")
    media = "application/pdf" if data[:5] == b"%PDF-" else "application/xml"
    return Response(
        content=data,
        media_type=media,
        headers={"Cache-Control": "no-store", "Content-Disposition": content_disposition_attachment(doc.filename)},
    )


@router.post("/documents/{doc_id}/ignore")
async def ignore_document(
    doc_id: uuid.UUID, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> DocumentOut:
    """„Nie je to doklad na príjem“ — hides it from the W6e list (stays in the audit)."""
    _guard(settings, person)
    doc = await _get(db, doc_id)
    doc.status = "ignored"
    audit(
        db,
        "purchasing.document_ignored",
        account_id=ctx.account.id,
        person_id=person.id,
        object_type="document",
        object_id=str(doc.id),
    )
    await db.commit()
    count = await db.scalar(select(func.count()).select_from(DocumentLine).where(DocumentLine.document_id == doc.id))
    return DocumentOut(**_out(doc, int(count or 0)))
