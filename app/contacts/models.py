"""Address books, contacts and groups (PRODUCT_SPEC §2.6, SCREENS_SPEC W9; ADR-009)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin


class AddressBook(IdMixin, TimestampMixin, Base):
    """Osobné adresy (person) or Zdieľané (company-wide). Money book is Phase 3 (not stored here)."""

    __tablename__ = "address_books"
    __table_args__ = (
        # UNIQUE(kind, owner_person_id) is a no-op for shared (NULL owner); use partial indexes (0011).
        Index(
            "uq_address_books_personal",
            "owner_person_id",
            unique=True,
            postgresql_where=text("kind = 'personal'"),
        ),
        Index(
            "uq_address_books_one_shared",
            "kind",
            unique=True,
            postgresql_where=text("kind = 'shared'"),
        ),
    )

    kind: Mapped[str] = mapped_column(String(16))  # personal | shared
    name: Mapped[str] = mapped_column(String(120))
    owner_person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), index=True)


class ContactGroup(IdMixin, TimestampMixin, Base):
    __tablename__ = "contact_groups"
    __table_args__ = (UniqueConstraint("address_book_id", "name"),)

    address_book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("address_books.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))


class Contact(IdMixin, TimestampMixin, Base):
    __tablename__ = "contacts"

    address_book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("address_books.id", ondelete="CASCADE"), index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    first_name: Mapped[str | None] = mapped_column(String(80))
    last_name: Mapped[str | None] = mapped_column(String(80))
    organization: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    emails: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    phones: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")


class ContactGroupMember(Base):
    __tablename__ = "contact_group_members"

    contact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), primary_key=True)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contact_groups.id", ondelete="CASCADE"), primary_key=True)


class RecentRecipient(IdMixin, TimestampMixin, Base):
    """Local compose/send history for autocomplete (never Money)."""

    __tablename__ = "recent_recipients"
    __table_args__ = (UniqueConstraint("person_id", "email"),)

    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(254))
    name: Mapped[str | None] = mapped_column(String(200))
    use_count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
