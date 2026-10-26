"""Mailboxes, access, folders and synced message envelopes (CLAUDE.md §4, §5).

The IMAP server stays the source of truth; these tables are the local copy the UI reads (SCREENS_SPEC W2 "list data
from local DB synced via IMAP"). Bodies, attachments and threads come with Phase 1d.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin


class Mailbox(IdMixin, TimestampMixin, Base):
    __tablename__ = "mailboxes"

    email: Mapped[str] = mapped_column(String(254), unique=True)  # lower-case
    imap_host: Mapped[str] = mapped_column(String(253))
    imap_port: Mapped[int] = mapped_column(Integer)
    imap_security: Mapped[str] = mapped_column(String(16))  # ssl | starttls | none
    # the login whose stored mailbox password (DECISIONS D27) the background sync uses
    credential_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))
    capabilities: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    quota_used_kb: Mapped[int | None] = mapped_column(BigInteger)
    quota_limit_kb: Mapped[int | None] = mapped_column(BigInteger)
    quota_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_state: Mapped[str] = mapped_column(String(16), default="new", server_default="new")  # new|ok|error|auth_failed
    sync_error: Mapped[str | None] = mapped_column(String(64))  # error class only, never server text with data
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MailboxAccess(IdMixin, TimestampMixin, Base):
    __tablename__ = "mailbox_access"
    __table_args__ = (UniqueConstraint("account_id", "mailbox_id"),)

    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    mailbox_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mailboxes.id", ondelete="CASCADE"))
    can_send: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class FolderMeta(IdMixin, TimestampMixin, Base):
    __tablename__ = "folders_meta"
    __table_args__ = (UniqueConstraint("mailbox_id", "name"),)

    mailbox_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mailboxes.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(500))  # full IMAP path, decoded from modified UTF-7
    delimiter: Mapped[str | None] = mapped_column(String(1))
    special_use: Mapped[str | None] = mapped_column(String(16))  # inbox | drafts | sent | junk | trash
    subscribed: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    selectable: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    private: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")  # SETTINGS 02, D21
    uidvalidity: Mapped[int | None] = mapped_column(BigInteger)
    uidnext: Mapped[int | None] = mapped_column(BigInteger)
    highestmodseq: Mapped[int | None] = mapped_column(BigInteger)
    total: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    unread: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(IdMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("folder_id", "uid"),)

    mailbox_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mailboxes.id", ondelete="CASCADE"), index=True)
    folder_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("folders_meta.id", ondelete="CASCADE"))
    uid: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[str | None] = mapped_column(String(998), index=True)
    in_reply_to: Mapped[str | None] = mapped_column(String(998))
    references: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(Text)
    from_name: Mapped[str | None] = mapped_column(String(400))
    from_email: Mapped[str | None] = mapped_column(String(254))
    to_addrs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    cc_addrs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    size: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    flags: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    seen: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    flagged: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    answered: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    modseq: Mapped[int | None] = mapped_column(BigInteger)
