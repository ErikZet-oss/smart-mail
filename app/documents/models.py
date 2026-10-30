"""Prehlásenie o zhode / atest 2.1 (#139, data model approved by Erik)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin


class ConformityDeclaration(IdMixin, TimestampMixin, Base):
    """One issued declaration — never edited after issue (a correction gets a new number)."""

    __tablename__ = "conformity_declarations"

    number: Mapped[str] = mapped_column(String(20), unique=True)  # PZ-RRRR-NNNN, one series for the company
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), index=True)
    prepared_by_person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id"))  # who really issued it
    signer_person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id"))  # the branch manager who signs
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    customer_text: Mapped[str] = mapped_column(Text, default="")
    document_ref: Mapped[str] = mapped_column(String(120), default="")
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)  # {nazov, kod, norma, poznamka}
    place: Mapped[str] = mapped_column(String(80), default="")
    issued_on: Mapped[date] = mapped_column(Date)
    pdf_storage_key: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    thread_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("threads.id", ondelete="SET NULL"))
