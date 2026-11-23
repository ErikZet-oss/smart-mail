"""Phase 4a — supplier documents (W6u upload, W6e list, detail for W6h in 4b). Read-only: nothing is written to Money.

Roles: warehouse, accounting, admin (SCREENS_SPEC W6e/W6h). Only with FEATURE_MONEY.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any, Literal

import structlog
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
from app.mail.mailboxes import accessible_mailbox
from app.mail.models import Message
from app.money.agenda import invalid_branch_ids
from app.money.approval import ApprovalKeyMissing, sign_approval
from app.money.bridge_client import BridgeClient, BridgeRefused, BridgeUnavailable
from app.money.models import MoneyArticleSupplier, MoneyCodebook, MoneyCompany
from app.money.schemas import Article
from app.purchasing import delivery_note, new_article, org_settings
from app.purchasing.item_matching import (
    confirm_article,
    load_lines,
    mark_non_stock,
    match_document,
    needs_matching,
    refresh_checks,
)
from app.purchasing.models import DocumentLine, SupplierDocument
from app.purchasing.numbers import normalize_code
from app.purchasing.service import MAX_BYTES, DocumentRejected, Source, ingest
from app.purchasing.variants import Kind, has_variants, picker_order, variants_of

router = APIRouter(prefix="/api/purchasing", tags=["purchasing"])
log = structlog.get_logger(__name__)
ROLES = frozenset({Role.warehouse, Role.accounting, Role.admin})
ARTICLE_ROLES = ROLES  # D32: who may create a Money article from a line
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
    money_number: str | None = None  # 4c (#247): number of the koncept in Money (W6e „Koncept“ chip)


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
    new_article: dict[str, Any] | None = None  # D32 (#239): partial / failed state of „Založiť artikel v Money“


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
    can_create_article: bool = False  # D32: Settings 14 switch on + role warehouse / accounting / admin
    can_write: bool = False  # D33 (#247): Settings 14 „Zápis dodacích listov“ on + role warehouse / accounting / admin
    write: dict[str, Any] | None = None  # 4c state: creating | created | write_failed | unknown, number, mismatches
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
        "money_number": doc.money_number,
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
        new_article=_new_article_view(ln),
    )


def _new_article_view(ln: DocumentLine) -> dict[str, Any] | None:
    state = new_article.state_of(ln.raw)
    if state.get("status") not in ("partial", "failed", "in_progress"):
        return None
    return {"status": state["status"], "main": state.get("main"), "error": state.get("error")}


async def _detail(db: DB, doc: SupplierDocument, *, money_available: bool = True, person: Any = None) -> DocumentDetail:
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
    conf = await org_settings.load(db)
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
        can_create_article=person is not None and person.role in ARTICLE_ROLES and conf.create_article,
        can_write=person is not None and person.role in ROLES and conf.write_delivery_notes,
        write=_write_view(doc),
        items=[_line(ln, wh_codes) for ln in lines],
    )


MATCHABLE = ("needs_review", "missing_data", "write_failed")  # lines still editable
WRITE_STATES = ("creating", "created", "write_failed", "unknown")


def _write_view(doc: SupplierDocument) -> dict[str, Any] | None:
    if doc.status not in WRITE_STATES and not doc.money_number:
        return None
    meta = doc.readback_diff or {}
    return {
        "state": doc.status if doc.status in WRITE_STATES else "created",
        "number": doc.money_number,
        "money_id": _s(doc.money_doc_id),
        "mismatches": meta.get("mismatches") or [],
        "reconciled": bool(meta.get("reconciled")),
        "error": doc.error if doc.status in ("write_failed", "unknown") else None,
        "written_at": meta.get("written_at"),
    }


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
    elif doc.status in MATCHABLE:  # 4c: branch settings / template may have changed since the last check
        before = (doc.validation, doc.status)
        await refresh_checks(db, doc, await load_lines(db, doc))
        if (doc.validation, doc.status) != before:
            await db.commit()
    return await _detail(db, doc, money_available=available, person=person)


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
    return await _detail(db, doc, money_available=available, person=person)


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
            # DL-B11 (#233): never on a main card that has variants — checked here, never trusting the UI
            main_card = article is not None and await has_variants(bridge, article)
    except BridgeUnavailable as exc:
        raise fail(503, exc.code) from None
    if main_card:
        raise fail(422, "main_card_has_variants")
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
    return await _detail(db, doc, person=person)


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
    return await _detail(db, doc, person=person)


PICKER_LIMIT = 30
MAIN_CARD_LIMIT = 10  # #233: variants are asked for at most 10 result articles (one bridge call)


class PickerArticle(Article):
    """#233 a picker row: `kind` = article | main (a main card that has variants — never receivable) | variant."""

    kind: Kind = "article"


SUPPLIER_CODE_LIMIT = 10  # each hit is one bridge read; leave room for the catalog variants


@router.get("/articles")
async def search_articles(
    person: ActivePerson,
    db: DB,
    settings: SettingsDep,
    q: Annotated[str, Query(min_length=2, max_length=80)],
) -> list[PickerArticle]:
    """Article picker of W6h. Results of every kind together, best first (pilot 2026-11-20: a catalog number showed
    only the main card `3090225`, never its variants `30902250010`, …):
    1. exact code / catalog, 2. EAN, 3. supplier code from the read cache (`money_article_suppliers`),
    4. catalog or name containing the text (variants of a main card). At most `PICKER_LIMIT`, no duplicates.
    With `%` (pilot 2026-11-23) it is the Money S4 pattern search in the name only — `%mat%4%934`."""
    _guard(settings, person)
    term = q.strip()
    if set(term) & set("~#|()"):
        raise fail(422, "unsafe_query")
    out: dict[uuid.UUID, Article] = {}

    def add(items: list[Article]) -> None:
        for a in items:
            if len(out) < PICKER_LIMIT:
                out.setdefault(a.id, a)

    try:
        async with BridgeClient(settings) as bridge:
            wildcard = "%" in term  # the pattern search: name only, no exact code / EAN / supplier code steps
            if not wildcard:
                add(await bridge.search_articles(code=term))
            if term.isdigit() and len(term) >= 8:
                add(await bridge.search_articles(ean=term))
            norm = "" if wildcard else normalize_code(term) or ""
            if len(norm) >= 5:
                ids = list(
                    await db.scalars(
                        select(MoneyArticleSupplier.article_id)
                        .where(MoneyArticleSupplier.active.is_(True), MoneyArticleSupplier.code_norm.startswith(norm))
                        .distinct()
                        .limit(SUPPLIER_CODE_LIMIT)
                    )
                )
                for article_id in ids:
                    if article_id not in out and len(out) < PICKER_LIMIT:
                        found = await bridge.article(article_id)
                        if found:
                            out[found.id] = found
            add(sorted(await bridge.search_articles(q=term), key=lambda a: (a.catalog or a.code or "", a.name)))
            # #233: main cards (with variants) are marked and followed by their variants
            results = list(out.values())
            mains = [a.id for a in results if a.parent_id is None]
            variants = await variants_of(bridge, mains, limit=MAIN_CARD_LIMIT)
    except BridgeUnavailable as exc:
        raise fail(503, exc.code) from None
    return [PickerArticle(**a.model_dump(), kind=kind) for a, kind in picker_order(results, variants, PICKER_LIMIT)]


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


# ----- #208 AI card „Príjem tovaru“ in the mail thread (W2c / M3) -----

CHECK_METHODS = ("learned", "ean", "our_code")  # matched, but a person should look (amber in W6h)


class ThreadDocCard(BaseModel):
    id: str
    status: str
    kind: str
    filename: str
    attachment_id: str | None
    supplier_name: str | None
    supplier_ico: str | None
    supplier_in_money: bool | None  # None = Money not reachable / cache empty
    doc_number: str | None
    currency: str | None
    total: str | None
    lines: int
    matched: int
    to_confirm: int
    unmatched: int
    matching_done: bool
    confidence: float | None  # extraction confidence 0–1 for „istota“ (display only, never money)
    checks: list[dict[str, Any]]
    money_number: str | None
    error: str | None
    money_available: bool


def _confidence(values: dict[str, Any]) -> float | None:
    nums = [v for v in (values or {}).values() if isinstance(v, int | float) and not isinstance(v, bool)]
    return round(min(nums), 2) if nums else None


@router.get("/mailboxes/{ref}/messages/{message_id}/documents")
async def message_documents(
    ref: str,
    message_id: uuid.UUID,
    ctx: Auth,
    person: ActivePerson,
    db: DB,
    settings: SettingsDep,
) -> list[ThreadDocCard]:
    """Supplier documents read from this message (#208). Read-only; the mail never breaks on it: Money off, a role
    without W6h or no document → an empty list. Ignored (Zamietnuť) documents are not returned."""
    mailbox = await accessible_mailbox(db, ctx.account, ref)
    msg = await db.get(Message, message_id)
    if mailbox is None or msg is None or msg.mailbox_id != mailbox.id:
        raise fail(404, "message_not_found")
    if not settings.feature_money or person.role not in ROLES:
        return []
    docs = list(
        await db.scalars(
            select(SupplierDocument)
            .where(SupplierDocument.message_id == msg.id, SupplierDocument.status != "ignored")
            .order_by(SupplierDocument.created_at)
        )
    )
    out: list[ThreadDocCard] = []
    for doc in docs:
        lines = await load_lines(db, doc)
        available = True
        if doc.status in MATCHABLE and needs_matching(lines):
            async with BridgeClient(settings) as bridge:
                available = await match_document(db, bridge, doc)
            await db.commit()
            lines = await load_lines(db, doc)
        goods = [ln for ln in lines if not ln.is_fee]
        unmatched = sum(1 for ln in goods if ln.line_status == "unmatched" and ln.match_method is not None)
        to_confirm = sum(1 for ln in goods if ln.line_status == "matched" and ln.match_method in CHECK_METHODS)
        matched = sum(
            1
            for ln in goods
            if ln.line_status == "non_stock" or (ln.line_status == "matched" and ln.match_method not in CHECK_METHODS)
        )
        out.append(
            ThreadDocCard(
                id=str(doc.id),
                status=doc.status,
                kind=doc.kind,
                filename=doc.filename,
                attachment_id=_s(doc.attachment_id),
                supplier_name=doc.supplier_name,
                supplier_ico=doc.supplier_ico,
                supplier_in_money=(doc.supplier_money_id is not None) if available else None,
                doc_number=doc.doc_number,
                currency=doc.currency,
                total=_s(doc.total),
                lines=len(goods),
                matched=matched,
                to_confirm=to_confirm,
                unmatched=unmatched,
                matching_done=bool(goods) and not needs_matching(lines),
                confidence=_confidence(doc.field_confidence),
                checks=doc.validation or [],
                money_number=doc.money_number,
                error=doc.error,
                money_available=available,
            )
        )
    return out


# ----- D32 (#239) „Založiť artikel v Money“ from the W6h / M13b line drawer -----


class NewArticleOut(BaseModel):
    status: Literal["done", "partial"]
    main: dict[str, Any] | None  # the created (or earlier created) main card
    variant: dict[str, Any] | None
    error: str | None  # partial: why the variant was not created
    article_id: str | None  # the card now picked for the line (the variant when both)
    document: DocumentDetail


class CatalogProposal(BaseModel):
    katalog: str | None  # None = no size in the text or 20 numbers taken — the user types it
    size: int | None
    main_catalog: str | None


async def _article_guard(db: DB, settings: Settings, person: Any) -> None:
    if not settings.feature_money:
        raise fail(404, "money_disabled")
    if person.role not in ARTICLE_ROLES:
        raise fail(403, "role_not_allowed")
    if not (await org_settings.load(db)).create_article:
        raise fail(403, "create_article_disabled")


async def _locked_doc(db: DB, doc_id: uuid.UUID) -> SupplierDocument:
    """Row lock: two clicks of the same person (or two people) serialise here; the second sees `in_progress` or a new
    version."""
    doc = await db.scalar(select(SupplierDocument).where(SupplierDocument.id == doc_id).with_for_update())
    if doc is None:
        raise fail(404, "document_not_found")
    return doc


async def _the_line(db: DB, doc: SupplierDocument, line_no: int) -> DocumentLine:
    line = await db.scalar(
        select(DocumentLine).where(DocumentLine.document_id == doc.id, DocumentLine.line_no == line_no)
    )
    if line is None or line.is_fee:
        raise fail(404, "line_not_found")
    return line


def _same_request(state: dict[str, Any], body: new_article.NewArticleIn) -> bool:
    req = state.get("request") or {}
    return bool(req.get("mode") == body.mode and req.get("catalogs") == body.catalogs())


async def _out_new(
    db: DB, doc: SupplierDocument, state: dict[str, Any], person: Any, *, status: Literal["done", "partial"]
) -> NewArticleOut:
    picked = state.get("variant") or (state.get("main") if status == "done" else None)
    return NewArticleOut(
        status=status,
        main=state.get("main"),
        variant=state.get("variant"),
        error=state.get("error") if status == "partial" else None,
        article_id=picked["id"] if picked else None,
        document=await _detail(db, doc, person=person),
    )


@router.post("/documents/{doc_id}/lines/{line_no}/new-article")
async def create_line_article(
    doc_id: uuid.UUID,
    line_no: int,
    body: new_article.NewArticleIn,
    ctx: Auth,
    person: ActivePerson,
    db: DB,
    settings: SettingsDep,
) -> NewArticleOut:
    """D32 / MONEY_API 5.5.8b: the user's click is the approval. Catalogs are checked here and again in the bridge right
    before the mutation; nothing is retried automatically. The new card (the variant when both) is picked for the line
    with a learned supplier code."""
    await _article_guard(db, settings, person)
    doc = await _locked_doc(db, doc_id)
    if doc.status not in MATCHABLE:
        raise fail(409, "document_not_reviewable")
    line = await _the_line(db, doc, line_no)
    now = datetime.now(UTC)
    state = new_article.state_of(line.raw)
    if new_article.in_progress(state, now):
        raise fail(409, "in_progress")
    if state.get("status") == "done" and _same_request(state, body):
        return await _out_new(db, doc, state, person, status="done")  # a repeat after success: the stored result
    if doc.version != body.version:
        raise fail(409, "version_conflict")
    main_done = state.get("main") if state.get("status") == "partial" and body.mode == "main_and_variant" else None
    if state.get("status") not in ("partial", "failed"):
        state = {"smids": state.get("smids") or {}}  # a fresh request keeps only the SMIDs of earlier catalogs

    # what to create, in order: (role, card, parent) — parent "main" = the main card created in this request
    plan: list[tuple[str, new_article.CardIn, uuid.UUID | str | None]] = []
    if body.mode == "main" and body.main:
        plan.append(("main", body.main, None))
    elif body.mode == "variant" and body.variant:
        plan.append(("variant", body.variant, body.parent_id))
    elif body.main and body.variant:
        if main_done is None:
            plan.append(("main", body.main, None))
        plan.append(("variant", body.variant, uuid.UUID(main_done["id"]) if main_done else "main"))

    try:
        async with BridgeClient(settings) as bridge:
            for _, c, _parent in plan:  # re-check every catalog (a known SMID = maybe ours: the bridge decides)
                if c.katalog in (state.get("smids") or {}):
                    continue
                free = await bridge.catalog_free(c.katalog)
                if not free.free:
                    raise fail(409, "catalog_exists", katalog=c.katalog)
            if body.mode == "variant" and body.parent_id is not None:
                parent_card = await bridge.article(body.parent_id)
                if parent_card is None or parent_card.inactive:
                    raise fail(422, "parent_not_found")
                if parent_card.parent_id is not None:
                    raise fail(422, "parent_not_main")  # a variant of a variant does not exist in Money
    except BridgeUnavailable as exc:
        raise fail(503, exc.code) from None

    for _, c, _ in plan:
        new_article.smid_for(state, c.katalog)
    state.update(
        status="in_progress",
        started_at=now.isoformat(),
        request={"mode": body.mode, "catalogs": body.catalogs()},
        main=main_done,
        variant=None,
        error=None,
    )
    line.raw = {**(line.raw or {}), new_article.STATE: copy.deepcopy(state)}  # never share `state`: JSON change
    doc.version += 1
    await db.commit()  # the SMIDs are stored before the bridge is called

    async def save(status: str, error: str | None = None) -> None:
        state.update(status=status, error=error)
        line.raw = {**(line.raw or {}), new_article.STATE: copy.deepcopy(state)}

    created_main: dict[str, Any] | None = main_done
    try:
        async with BridgeClient(settings) as bridge:
            for role, c, parent in plan:
                parent_id = (
                    uuid.UUID(created_main["id"])
                    if parent == "main" and created_main
                    else parent
                    if isinstance(parent, uuid.UUID)
                    else None
                )
                p = new_article.payload(c.katalog, c.nazev, state["smids"][c.katalog], parent_id)
                try:
                    token = sign_approval(
                        settings,
                        action="article.create",
                        company_id=doc.supplier_money_id or new_article.NIL,
                        person_id=person.id,
                        body=new_article.body_bytes(p),
                    )
                except ApprovalKeyMissing:
                    raise BridgeUnavailable("approval_key_missing") from None
                got = new_article.card(await bridge.create_article(p, token))
                state[role] = got
                if role == "main":
                    created_main = got
                audit(
                    db,
                    "purchasing.article_created",
                    account_id=ctx.account.id,
                    person_id=person.id,
                    object_type="document",
                    object_id=str(doc.id),
                    details={
                        "line_no": line_no,
                        "card": role,
                        "katalog": got["katalog"],
                        "money_id": got["id"],
                        "payload_sha256": new_article.payload_hash(p),
                    },
                )
                await save("in_progress")
                await db.commit()  # each created card is kept, whatever happens next
    except (BridgeUnavailable, BridgeRefused) as exc:
        code = exc.code
        if body.mode == "main_and_variant" and created_main is not None:
            await save("partial", code)
            doc.version += 1
            await db.commit()
            return await _out_new(db, doc, state, person, status="partial")
        await save("failed", code)
        await db.commit()
        if isinstance(exc, BridgeRefused):
            raise fail(exc.status if exc.status in (403, 409, 422) else 502, code, **_katalog(exc)) from None
        raise fail(503, code) from None

    picked = state.get("variant") or state.get("main")
    assert picked is not None
    await confirm_article(db, doc, line, new_article.as_article(picked), Decimal("1"), person.id, learn=True)
    await save("done")
    await db.commit()
    return await _out_new(db, doc, state, person, status="done")


def _katalog(exc: BridgeRefused) -> dict[str, Any]:
    k = exc.detail.get("katalog")
    return {"katalog": str(k)} if k else {}


@router.get("/articles/catalog-free")
async def article_catalog_free(
    person: ActivePerson,
    db: DB,
    settings: SettingsDep,
    katalog: Annotated[str, Query(min_length=1, max_length=50)],
) -> dict[str, Any]:
    """Live check while typing (debounced in the drawer): taken → „Tento katalóg už v Money existuje – zadajte iný.“"""
    await _article_guard(db, settings, person)
    term = katalog.strip()
    if not term or set(term) & set("~#|()"):
        raise fail(422, "unsafe_query")
    try:
        async with BridgeClient(settings) as bridge:
            free = await bridge.catalog_free(term)
    except BridgeUnavailable as exc:
        raise fail(503, exc.code) from None
    return free.model_dump(mode="json")


@router.get("/catalog-proposal")
async def catalog_proposal(
    person: ActivePerson,
    db: DB,
    settings: SettingsDep,
    parent_id: Annotated[uuid.UUID | None, Query()] = None,
    main_catalog: Annotated[str | None, Query(max_length=50)] = None,
    size: Annotated[str | None, Query(max_length=200)] = None,
) -> CatalogProposal:
    """D32: variant catalog = main catalog + 5-digit size (M10 → `00010`); taken → the next free number, at most 20
    tries. Only a proposal — the user can edit it. The main catalog comes from `parent_id` (an existing card) or
    `main_catalog` (a new main card typed in the drawer)."""
    await _article_guard(db, settings, person)
    n = new_article.size_of(size)
    base = (main_catalog or "").strip() or None
    try:
        async with BridgeClient(settings) as bridge:
            if parent_id is not None:
                parent = await bridge.article(parent_id)
                if parent is None:
                    raise fail(422, "parent_not_found")
                base = parent.catalog
            if base and set(base) & set("~#|()"):
                raise fail(422, "unsafe_query")
            if not base or n is None:
                return CatalogProposal(katalog=None, size=n, main_catalog=base)
            for candidate in new_article.proposals(base, n):
                if len(candidate) <= 50 and (await bridge.catalog_free(candidate)).free:
                    return CatalogProposal(katalog=candidate, size=n, main_catalog=base)
    except BridgeUnavailable as exc:
        raise fail(503, exc.code) from None
    return CatalogProposal(katalog=None, size=n, main_catalog=base)


# ----- Phase 4c (#247, D33) „Vytvoriť v Money“ — the received delivery note as a KONCEPT -----

CREATING_TTL = timedelta(minutes=2)  # bridge timeout × 2 — an older `creating` is a crashed attempt → reconcile


class CreateIn(BaseModel):
    version: int


async def _write_guard(db: DB, settings: Settings, person: Any) -> None:
    _guard(settings, person)  # roles warehouse / accounting / admin
    if not (await org_settings.load(db)).write_delivery_notes:
        raise fail(403, "write_disabled")


def _creating_fresh(doc: SupplierDocument, now: datetime) -> bool:
    started = (doc.readback_diff or {}).get("started_at")
    try:
        return doc.status == "creating" and now - datetime.fromisoformat(str(started)) < CREATING_TTL
    except ValueError:
        return False


@router.post("/documents/{doc_id}/create")
async def create_in_money(
    doc_id: uuid.UUID,
    body: CreateIn,
    ctx: Auth,
    person: ActivePerson,
    db: DB,
    settings: SettingsDep,
) -> DocumentDetail:
    """D33 / MONEY_API 5.5.7: the person's click in the confirm dialog is the approval. Every check runs again here
    (DL-B1–B11), the SMID is stored before the bridge is called, nothing is retried automatically; a timeout leaves
    `unknown` and the next click reconciles by the SMID. Money keeps the note as a koncept — a person finishes it."""
    await _write_guard(db, settings, person)
    doc = await db.scalar(select(SupplierDocument).where(SupplierDocument.id == doc_id).with_for_update())
    if doc is None:
        raise fail(404, "document_not_found")
    blog = log.bind(document_id=str(doc.id))
    now = datetime.now(UTC)
    if doc.status == "created":
        return await _detail(db, doc, person=person)  # a repeat after success: the stored result, nothing in Money
    if _creating_fresh(doc, now):
        raise fail(409, "in_progress")
    if doc.status not in (*MATCHABLE, "creating", "unknown"):
        raise fail(409, "document_not_reviewable")
    if doc.version != body.version:
        raise fail(409, "version_conflict")
    lines = await load_lines(db, doc)
    reviewable = doc.status in MATCHABLE
    if reviewable:
        await refresh_checks(db, doc, lines)
    blocking = [c for c in (doc.validation or []) if c.get("level") == "blocking"]
    if blocking:
        await db.commit()
        raise fail(409, "checks_failed", checks=blocking)  # DL-B1–B11 at approval, never trusting the UI
    branch = await db.get(Branch, doc.branch_id) if doc.branch_id else None
    if branch is None:  # pragma: no cover — DL-B1 blocks above
        raise fail(409, "checks_failed")
    conf = await org_settings.load(db)
    state = await org_settings.load_state(db)
    values = delivery_note.branch_values(branch, await invalid_branch_ids(db, branch.id))
    payload, expected = delivery_note.build_payload(
        doc,
        lines,
        branch,
        values,
        now=now,
        issue_on_approval=conf.issue_date == "approval",
        with_address=state.send_supplier_address,
    )
    digest = delivery_note.payload_hash(payload)
    doc.status = "creating"
    doc.error = None
    doc.readback_diff = {"started_at": now.isoformat(), "payload_sha256": digest}
    doc.version += 1
    await db.commit()  # the SMID (`idempotency_key`) and the attempt are stored before the bridge is called
    blog.info("purchasing.koncept_write_started", lines=len(expected))

    try:
        token = sign_approval(
            settings,
            action="delivery_note.create",
            company_id=doc.supplier_money_id or new_article.NIL,
            person_id=person.id,
            body=delivery_note.body_bytes(payload),
        )
    except ApprovalKeyMissing:
        doc.status, doc.error = "write_failed", "approval_key_missing"
        await db.commit()
        raise fail(503, "approval_key_missing") from None
    try:
        async with BridgeClient(settings) as bridge:
            back = await bridge.create_delivery_note(payload, token)
    except BridgeRefused as exc:
        if exc.code == "duplicate":  # DL-B3 in Money: a person must look — nothing was created
            number = exc.detail.get("number")
            doc.status = "missing_data"
            doc.validation = [
                *(doc.validation or []),
                {"id": "DL-B3", "level": "blocking", "params": {"number": number, "money": True}},
            ]
            await db.commit()
            blog.info("purchasing.koncept_write_duplicate")
            raise fail(409, "duplicate", number=number) from None
        doc.status, doc.error = "write_failed", exc.code
        await db.commit()
        blog.warning("purchasing.koncept_write_refused", code=exc.code)
        raise fail(exc.status if exc.status in (403, 409, 422) else 502, exc.code) from None
    except BridgeUnavailable as exc:
        doc.status, doc.error = "unknown", exc.code  # maybe written — the next click reconciles by SMID
        await db.commit()
        blog.warning("purchasing.koncept_write_unknown", code=exc.code)
        raise fail(503, exc.code) from None

    mismatches = delivery_note.compare(expected, back)
    doc.status = "created"
    doc.money_doc_id, doc.money_number = back.id, back.number
    doc.readback_diff = {
        "started_at": now.isoformat(),
        "written_at": datetime.now(UTC).isoformat(),
        "payload_sha256": digest,
        "mismatches": mismatches,
        "reconciled": back.reconciled,
    }
    doc.template_source = branch.dl_template_money_id
    if back.address_empty and not state.send_supplier_address:  # MONEY_API 5.5.7: next writes send the address
        await org_settings.save_state(db, state.model_copy(update={"send_supplier_address": True}))
    audit(
        db,
        "purchasing.delivery_note_created",
        account_id=ctx.account.id,
        person_id=person.id,
        object_type="document",
        object_id=str(doc.id),
        details={
            "money_id": str(back.id),
            "number": back.number,
            "payload_sha256": digest,
            "reconciled": back.reconciled,
            "mismatches": len(mismatches),
            "koncept": True,
        },
    )
    await db.commit()
    blog.info("purchasing.koncept_written", reconciled=back.reconciled, mismatches=len(mismatches))
    return await _detail(db, doc, person=person)
