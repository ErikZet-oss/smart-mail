"""Phase 4a — supplier documents (W6u upload, W6e list, detail for W6h in 4b). Read-only: nothing is written to Money.

Roles: warehouse, accounting, admin (SCREENS_SPEC W6e/W6h). Only with FEATURE_MONEY.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Query, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select

from app.ai.provider import get_llm_provider
from app.api.mail import fail
from app.auth.deps import DB, ActivePerson, Auth, SettingsDep
from app.auth.models import Role
from app.core.audit import audit
from app.core.config import Settings
from app.core.content_disposition import content_disposition_attachment
from app.mail import storage
from app.mail.clamav import scan_bytes
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


class DocumentDetail(DocumentOut):
    delivery_note_number: str | None
    order_reference: str | None
    vat_recap: list[dict[str, Any]]
    fees: list[dict[str, Any]]
    extract_method: str | None
    field_confidence: dict[str, Any]
    checks: list[dict[str, Any]]
    message_id: str | None
    items: list[LineOut]


class DocumentPage(BaseModel):
    items: list[DocumentOut]
    total: int


def _s(v: Any) -> str | None:
    return None if v is None else str(v)


def _out(doc: SupplierDocument, lines: int) -> dict[str, Any]:
    checks = doc.validation or []
    return {
        "id": str(doc.id),
        "source": doc.source,
        "kind": doc.kind,
        "status": doc.status,
        "filename": doc.filename,
        "branch_id": _s(doc.branch_id),
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
) -> DocumentPage:
    """W6e: newest first. „open“ = still to review (not ignored, not duplicate)."""
    _guard(settings, person)
    q = select(SupplierDocument)
    if status == "open":
        q = q.where(SupplierDocument.status.notin_(("ignored", "duplicate")))
    elif status in ("duplicate", "ignored"):
        q = q.where(SupplierDocument.status == status)
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
    return DocumentPage(items=[DocumentOut(**_out(d, int(counts.get(d.id, 0)))) for d in docs], total=int(total or 0))


async def _get(db: DB, doc_id: uuid.UUID) -> SupplierDocument:
    doc = await db.get(SupplierDocument, doc_id)
    if doc is None:
        raise fail(404, "document_not_found")
    return doc


@router.get("/documents/{doc_id}")
async def get_document(doc_id: uuid.UUID, person: ActivePerson, db: DB, settings: SettingsDep) -> DocumentDetail:
    _guard(settings, person)
    doc = await _get(db, doc_id)
    lines = list(
        await db.scalars(select(DocumentLine).where(DocumentLine.document_id == doc.id).order_by(DocumentLine.line_no))
    )
    return DocumentDetail(
        **_out(doc, len(lines)),
        delivery_note_number=doc.delivery_note_number,
        order_reference=doc.order_reference,
        vat_recap=doc.vat_recap or [],
        fees=doc.fees or [],
        extract_method=doc.extract_method,
        field_confidence=doc.field_confidence or {},
        checks=doc.validation or [],
        message_id=_s(doc.message_id),
        items=[
            LineOut(
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
            )
            for ln in lines
        ],
    )


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
