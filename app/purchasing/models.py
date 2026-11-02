"""Supplier documents in (Phase 4a, plan §5 — approved by Erik in #191). Read-only: nothing is written to Money here."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin

# statuses of a supplier document before any Money write (4c adds approved / writing / created / undone …)
DOC_STATUSES = ("extracting", "needs_review", "missing_data", "duplicate", "unreadable", "failed", "ignored")


class SupplierDocument(IdMixin, TimestampMixin, Base):
    """A supplier invoice or delivery note that is the source of a received delivery note (D7: the invoice itself is
    never written to Money)."""

    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("sha256", "message_id", name="uq_documents_sha_message"),)

    source: Mapped[str] = mapped_column(String(16))  # mail | upload
    kind: Mapped[str] = mapped_column(String(24), default="unknown")  # invoice | delivery_note | unknown
    status: Mapped[str] = mapped_column(String(24), default="extracting", index=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"), index=True)
    attachment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("attachments.id", ondelete="SET NULL"))
    storage_key: Mapped[str] = mapped_column(String(500))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(200))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branches.id", ondelete="SET NULL"))
    supplier_money_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(255))
    supplier_ico: Mapped[str | None] = mapped_column(String(16))
    doc_number: Mapped[str | None] = mapped_column(String(64), index=True)  # supplier's number → Money `Odkaz`
    delivery_note_number: Mapped[str | None] = mapped_column(String(64))
    order_reference: Mapped[str | None] = mapped_column(String(64))
    doc_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str | None] = mapped_column(String(3))
    total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    vat_recap: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)  # [{rate, base, vat}] as strings
    fees: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)  # D14: shown, never written
    extract_method: Mapped[str | None] = mapped_column(String(24))  # isdoc | ubl | pdf_llm
    extracted: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # raw parser / LLM output (audit)
    field_confidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    validation: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)  # DL-B / DL-W checks
    error: Mapped[str | None] = mapped_column(Text)
    money_doc_id: Mapped[uuid.UUID | None] = mapped_column()  # 4c
    money_number: Mapped[str | None] = mapped_column(String(64))  # 4c
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: uuid.uuid4().hex)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")  # optimistic lock (4b/4c)
    readback_diff: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # 4c
    template_source: Mapped[str | None] = mapped_column(String(64))  # 4c: branch template document
    created_by_person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"))
    ai_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ai_runs.id", ondelete="SET NULL"))


class DocumentLine(IdMixin, TimestampMixin, Base):
    """One line of a supplier document — ALL lines are extracted (CLAUDE.md §12 Phase 4). Matching fields fill in 4b."""

    __tablename__ = "document_lines"
    __table_args__ = (UniqueConstraint("document_id", "line_no", name="uq_document_lines_no"),)

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    supplier_code: Mapped[str | None] = mapped_column(String(64))
    ean: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(Text, default="")
    qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    unit: Mapped[str | None] = mapped_column(String(16))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))  # excl. VAT, per one unit
    vat_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    line_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))  # excl. VAT
    is_fee: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    article_id: Mapped[uuid.UUID | None] = mapped_column()  # 4b
    match_method: Mapped[str | None] = mapped_column(String(32))  # 4b
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)  # 4b
    unit_factor: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))  # 4b
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column()  # 4b
    line_status: Mapped[str] = mapped_column(String(16), default="unmatched")  # 4b
