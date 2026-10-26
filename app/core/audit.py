"""Append-only audit log (CLAUDE.md §4, §9, §11). A database trigger rejects UPDATE, DELETE and TRUNCATE.

Every entry stores `account_id` and `person_id` when known. Never put passwords, codes, mail bodies or Money payloads
into `details`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin

FORBIDDEN_DETAIL_KEYS = frozenset({"password", "code", "token", "secret", "body"})


class AuditLog(IdMixin, Base):
    __tablename__ = "audit_log"

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    # no foreign keys on purpose: history survives deleted accounts/persons and the row is never updated
    account_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    person_id: Mapped[uuid.UUID | None]
    action: Mapped[str] = mapped_column(String(64), index=True)
    object_type: Mapped[str | None] = mapped_column(String(40))
    object_id: Mapped[str | None] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")


def audit(
    db: AsyncSession,
    action: str,
    *,
    account_id: uuid.UUID | None = None,
    person_id: uuid.UUID | None = None,
    object_type: str | None = None,
    object_id: str | None = None,
    ip: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    details = details or {}
    leaked = FORBIDDEN_DETAIL_KEYS & {k.lower() for k in details}
    if leaked:
        raise ValueError(f"audit details must not contain {sorted(leaked)}")
    entry = AuditLog(
        account_id=account_id,
        person_id=person_id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        ip=ip,
        details=details,
    )
    db.add(entry)
    return entry
