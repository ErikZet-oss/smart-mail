"""Phase 4a intake: supplier invoice / delivery note → `documents` + `document_lines` (read-only, no Money write).

Order: XML (ISDOC / UBL, deterministic) → PDF text layer + one LLM call (D3) → scan = `unreadable` (OCR later).
Logs carry `document_id` only — never document text or values (CLAUDE.md §0.1 Observability).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.budget import budget_allows_call
from app.ai.models import AiRun
from app.ai.org_settings import load_ai_limits
from app.ai.pricing import estimate_cost_usd
from app.ai.provider import LLMProvider, NullLLMProvider
from app.ai.service import daily_spend_usd
from app.auth.models import Branch
from app.core.audit import audit
from app.core.config import Settings
from app.mail import storage
from app.mail.models import Message
from app.money.models import MoneyCompany
from app.purchasing.models import DocumentLine, SupplierDocument
from app.purchasing.pdf_extract import extract_pdf, pdf_text
from app.purchasing.schemas import ExtractedDoc
from app.purchasing.validation import Context, validate
from app.purchasing.xmlparse import NotSupplierXml, parse_xml

log = structlog.get_logger(__name__)
MAX_BYTES = 15 * 1024 * 1024
EXTRACT_ESTIMATE_IN, EXTRACT_ESTIMATE_OUT = 20_000, 6_000
XML_TYPES = ("application/xml", "text/xml", "application/isdoc+xml")


class DocumentRejected(ValueError):
    """Not a PDF / XML supplier document, or too large."""


@dataclass(frozen=True, slots=True)
class Source:
    data: bytes
    filename: str
    content_type: str
    source: str  # mail | upload
    message: Message | None = None
    attachment_id: uuid.UUID | None = None
    person_id: uuid.UUID | None = None
    person_branch_id: uuid.UUID | None = None


def file_kind(data: bytes, filename: str, content_type: str) -> str:
    name = filename.lower()
    if data[:5] == b"%PDF-":
        return "pdf"
    head = data[:200].lstrip()
    if name.endswith((".xml", ".isdoc", ".isdocx")) or content_type in XML_TYPES or head.startswith(b"<?xml"):
        return "xml"
    raise DocumentRejected("unsupported_type")


async def _branch_for(db: AsyncSession, src: Source) -> uuid.UUID | None:
    """Folder mapped to a branch (Settings 11a, D21) → branch mailbox → the uploader's branch."""
    msg = src.message
    if msg is not None:
        for branch in await db.scalars(select(Branch)):
            if str(msg.folder_id) in (branch.folder_ids or []):
                return branch.id
        by_mailbox = await db.scalar(select(Branch.id).where(Branch.mailbox_id == msg.mailbox_id))
        if by_mailbox:
            return by_mailbox
    return src.person_branch_id


async def _run_llm(
    db: AsyncSession, settings: Settings, provider: LLMProvider, doc: SupplierDocument, text: str
) -> ExtractedDoc | None:
    model = (settings.llm_model_extract or "").strip()
    if isinstance(provider, NullLLMProvider) or not model:
        doc.status, doc.error = "failed", "llm_unavailable"
        return None
    budget = (await load_ai_limits(db, settings)).budget_usd
    if not budget_allows_call(
        spent_usd=await daily_spend_usd(db),
        estimate_usd=estimate_cost_usd(model, EXTRACT_ESTIMATE_IN, EXTRACT_ESTIMATE_OUT),
        budget_usd=budget,
    ):
        doc.status, doc.error = "failed", "budget"
        return None
    try:
        extracted, response = await extract_pdf(provider, model, text)
    except Exception as exc:  # never crash the intake; the document stays visible with the error
        db.add(
            AiRun(purpose="extract", provider="anthropic", model=model, status="error", error_class=type(exc).__name__)
        )
        doc.status, doc.error = "failed", "llm_error"
        return None
    run = AiRun(
        purpose="extract",
        provider=response.provider,
        model=response.model,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cost_usd=response.cost_usd,
        latency_ms=response.latency_ms,
        message_id=doc.message_id,
        status="ok" if extracted else "invalid",
    )
    db.add(run)
    await db.flush()
    doc.ai_run_id = run.id
    if extracted is None:
        doc.status, doc.error = "failed", "llm_no_output"
    return extracted


async def ingest(
    db: AsyncSession, settings: Settings, provider: LLMProvider, src: Source, *, today: datetime | None = None
) -> SupplierDocument:
    """Create (or return the existing) document for these bytes. The caller commits."""
    if len(src.data) > MAX_BYTES:
        raise DocumentRejected("too_large")
    kind = file_kind(src.data, src.filename, src.content_type)
    sha = hashlib.sha256(src.data).hexdigest()
    same_source = (
        SupplierDocument.message_id == src.message.id if src.message else SupplierDocument.message_id.is_(None)
    )
    existing = await db.scalar(select(SupplierDocument).where(SupplierDocument.sha256 == sha, same_source))
    if existing is not None:
        return existing
    key, _ = storage.put_bytes(settings, src.data, prefix="purchasing")
    doc = SupplierDocument(
        source=src.source,
        message_id=src.message.id if src.message else None,
        attachment_id=src.attachment_id,
        storage_key=key,
        filename=src.filename[:255],
        content_type=src.content_type[:200],
        sha256=sha,
        branch_id=await _branch_for(db, src),
        created_by_person_id=src.person_id,
        status="extracting",
    )
    db.add(doc)
    await db.flush()

    extracted: ExtractedDoc | None = None
    if kind == "xml":
        try:
            extracted = parse_xml(src.data)
        except NotSupplierXml:
            doc.status, doc.error = "unreadable", "xml_not_supplier_document"
    else:
        text = pdf_text(src.data)
        if text is None:
            doc.status, doc.error = "unreadable", "no_text_layer"  # scan → OCR comes later
        else:
            extracted = await _run_llm(db, settings, provider, doc, text)
    if extracted is not None:
        await apply_extraction(db, doc, extracted, today=(today or datetime.now(UTC)).date())
    audit(
        db,
        "purchasing.document_extracted",
        person_id=src.person_id,
        object_type="document",
        object_id=str(doc.id),
        details={
            "source": src.source,
            "status": doc.status,
            "method": doc.extract_method,
            "lines": len(extracted.lines) if extracted else 0,
        },
    )
    log.info("purchasing.document_extracted", document_id=str(doc.id), status=doc.status, method=doc.extract_method)
    return doc


async def apply_extraction(db: AsyncSession, doc: SupplierDocument, ex: ExtractedDoc, *, today: date) -> None:
    doc.kind = ex.kind
    doc.extract_method = ex.method
    doc.extracted = ex.model_dump(mode="json")
    doc.field_confidence = ex.confidence
    doc.supplier_name, doc.supplier_ico = ex.supplier_name, ex.supplier_ico
    doc.doc_number, doc.delivery_note_number, doc.order_reference = (
        ex.number,
        ex.delivery_note_number,
        ex.order_reference,
    )
    doc.doc_date, doc.currency, doc.total = ex.issued_on, ex.currency, ex.total
    doc.vat_recap = [
        {"rate": str(r.rate), "base": str(r.base), "vat": None if r.vat is None else str(r.vat)} for r in ex.vat_recap
    ]
    doc.fees = [
        {"name": line.name, "amount": None if line.line_total is None else str(line.line_total)}
        for line in ex.lines
        if line.is_fee
    ]
    for no, line in enumerate(ex.lines, start=1):
        db.add(
            DocumentLine(
                document_id=doc.id,
                line_no=no,
                supplier_code=line.supplier_code,
                ean=line.ean,
                name=line.name,
                qty=line.qty,
                unit=line.unit,
                unit_price=line.unit_price,
                vat_rate=line.vat_rate,
                line_total=line.line_total,
                is_fee=line.is_fee,
                raw=line.model_dump(mode="json"),
            )
        )
    company = (
        await db.scalar(select(MoneyCompany).where(MoneyCompany.ico == ex.supplier_ico, MoneyCompany.active.is_(True)))
        if ex.supplier_ico
        else None
    )
    cache_empty = (await db.scalar(select(MoneyCompany.id).limit(1))) is None
    doc.supplier_money_id = company.money_id if company else None
    duplicate = None
    if ex.number and (ex.supplier_ico or company):
        duplicate = await db.scalar(
            select(SupplierDocument.doc_number).where(
                SupplierDocument.id != doc.id,
                SupplierDocument.doc_number == ex.number,
                or_(
                    SupplierDocument.supplier_ico == ex.supplier_ico,
                    SupplierDocument.supplier_money_id == (company.money_id if company else None),
                ),
                SupplierDocument.status.notin_(("ignored", "duplicate")),
            )
        )
    checks = validate(
        ex,
        Context(
            today=today,
            supplier_in_money=None if cache_empty else company is not None,
            supplier_ico_matches=company is not None or cache_empty,
            duplicate_of=duplicate,
        ),
    )
    doc.validation = checks
    if duplicate:
        doc.status = "duplicate"
    elif any(c["level"] == "blocking" for c in checks):
        doc.status = "missing_data"
    else:
        doc.status = "needs_review"
