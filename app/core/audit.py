"""Append-only audit log (CLAUDE.md §4, §9, §11). A database trigger rejects UPDATE, DELETE and TRUNCATE.

Every entry stores `account_id` and `person_id` when known. Never put passwords, codes, mail bodies or Money payloads
into `details`.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Actor:
    account_id: uuid.UUID
    person_id: uuid.UUID | None


# set by the auth dependency for the current request; entries written during it inherit account + person
_actor: ContextVar[Actor | None] = ContextVar("audit_actor", default=None)


def set_actor(account_id: uuid.UUID, person_id: uuid.UUID | None) -> None:
    _actor.set(Actor(account_id, person_id))


def clear_actor() -> None:
    _actor.set(None)


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
    actor = _actor.get()
    if actor is not None and account_id in (None, actor.account_id):
        account_id = actor.account_id
        person_id = person_id or actor.person_id
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
