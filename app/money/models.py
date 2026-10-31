"""Money read cache (Phase 3b, migration 0018 approved by Erik in #150). Never written back to Money.

`money_id` is the Money GUID; rows are upserted by it. A nightly full sync marks rows that Money no longer returns as
inactive instead of deleting them (other tables may point at a company).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin


class MoneyCompany(IdMixin, TimestampMixin, Base):
    __tablename__ = "money_companies"

    money_id: Mapped[uuid.UUID] = mapped_column(unique=True)
    code: Mapped[str | None] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(255), default="")
    ico: Mapped[str | None] = mapped_column(String(20), index=True)
    dic: Mapped[str | None] = mapped_column(String(20))
    icdph: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(320))
    discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))
    due_days: Mapped[int | None] = mapped_column(Integer)
    connections: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # lower-cased e-mail addresses from Email + SeznamSpojeni — the sender matching key (3c)
    emails: Mapped[list[str]] = mapped_column(ARRAY(String(320)), default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MoneyPerson(IdMixin, TimestampMixin, Base):
    __tablename__ = "money_persons"

    money_id: Mapped[uuid.UUID] = mapped_column(unique=True)
    company_money_id: Mapped[uuid.UUID | None] = mapped_column(index=True)  # REST parent_ID [PROBE]
    first_name: Mapped[str | None] = mapped_column(String(120))
    last_name: Mapped[str | None] = mapped_column(String(120))
    name: Mapped[str | None] = mapped_column(String(255))
    function: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(320), index=True)  # lower-cased
    phone: Mapped[str | None] = mapped_column(String(60))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MoneyCodebook(IdMixin, TimestampMixin, Base):
    __tablename__ = "money_codebooks"
    __table_args__ = (UniqueConstraint("kind", "money_id"),)

    kind: Mapped[str] = mapped_column(String(40))  # warehouses | centres | numerical-series | currencies
    money_id: Mapped[uuid.UUID]
    code: Mapped[str | None] = mapped_column(String(60))
    name: Mapped[str | None] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EmailCompanyLink(IdMixin, TimestampMixin, Base):
    """A person confirmed that an e-mail address belongs to a Money company (MONEY_API §5.4; used from 3c)."""

    __tablename__ = "email_company_links"

    email: Mapped[str] = mapped_column(String(320), unique=True)  # lower-cased
    company_money_id: Mapped[uuid.UUID]
    confirmed_by_person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"))
    confirmed_by_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(Text)


class MoneySyncState(IdMixin, TimestampMixin, Base):
    """One row per synced entity: the `ChangeFrom` cursor and the last 20 runs (Settings 13e)."""

    __tablename__ = "money_sync_state"

    entity: Mapped[str] = mapped_column(String(60), unique=True)
    cursor: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # start of the last good delta run
    last_full_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(20))  # ok | error
    last_error: Mapped[str | None] = mapped_column(String(60))  # an error code, never a Money payload
    history: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
