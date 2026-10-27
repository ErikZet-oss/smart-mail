"""Mailboxes, access, folders, threads and synced messages (CLAUDE.md §4, §5; Phase 1d bodies/attachments).

The IMAP server stays the source of truth; these tables are the local copy the UI reads (SCREENS_SPEC W2).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin


class Mailbox(IdMixin, TimestampMixin, Base):
    __tablename__ = "mailboxes"

    email: Mapped[str] = mapped_column(String(254), unique=True)  # lower-case
    # personal | shared | branch
    kind: Mapped[str] = mapped_column(String(16), default="personal", server_default="personal")
    imap_host: Mapped[str] = mapped_column(String(253))
    imap_port: Mapped[int] = mapped_column(Integer)
    imap_security: Mapped[str] = mapped_column(String(16))  # ssl | starttls | none
    smtp_host: Mapped[str | None] = mapped_column(String(253))
    smtp_port: Mapped[int | None] = mapped_column(Integer)
    smtp_security: Mapped[str | None] = mapped_column(String(16))
    sieve_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sieve_host: Mapped[str | None] = mapped_column(String(253))
    sieve_port: Mapped[int | None] = mapped_column(Integer, default=4190, server_default="4190")
    provider_admin_url: Mapped[str | None] = mapped_column(String(500))
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
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
    # When private=true, only this person may search/list the folder (ADR-009). Null + private → hidden from all.
    owner_person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"), index=True)
    uidvalidity: Mapped[int | None] = mapped_column(BigInteger)
    uidnext: Mapped[int | None] = mapped_column(BigInteger)
    highestmodseq: Mapped[int | None] = mapped_column(BigInteger)
    total: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    unread: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Thread(IdMixin, TimestampMixin, Base):
    __tablename__ = "threads"
    __table_args__ = (UniqueConstraint("mailbox_id", "thread_key"),)

    mailbox_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mailboxes.id", ondelete="CASCADE"), index=True)
    thread_key: Mapped[str] = mapped_column(String(80))  # "msgid:<id>" | "fallback:<hash>"
    subject: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open")  # open|waiting|done|snoozed
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"))
    assigned_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"), index=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    unread_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    has_attachments: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    flagged: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Message(IdMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("folder_id", "uid"),)

    mailbox_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mailboxes.id", ondelete="CASCADE"), index=True)
    folder_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("folders_meta.id", ondelete="CASCADE"))
    thread_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("threads.id", ondelete="SET NULL"), index=True)
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
    has_attachments: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    preview: Mapped[str | None] = mapped_column(String(240))
    body_text: Mapped[str | None] = mapped_column(Text)
    body_html_sanitized: Mapped[str | None] = mapped_column(Text)
    body_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_storage_key: Mapped[str | None] = mapped_column(String(500))
    auth_results: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Maintained by DB trigger (simple + unaccent); used by GET /api/search (ADR-009).
    search_vector: Mapped[Any | None] = mapped_column(TSVECTOR)


class Attachment(IdMixin, TimestampMixin, Base):
    __tablename__ = "attachments"

    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(200), default="application/octet-stream")
    size: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    content_id: Mapped[str | None] = mapped_column(String(998))
    is_inline: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    storage_key: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))
    av_status: Mapped[str] = mapped_column(
        String(16), default="skipped", server_default="skipped"
    )  # clean|infected|skipped


class UserSettings(IdMixin, TimestampMixin, Base):
    """JSON prefs per person and section (SETTINGS_SPEC; 01a/01b used in Phase 1d)."""

    __tablename__ = "user_settings"
    __table_args__ = (UniqueConstraint("person_id", "section"),)

    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), index=True)
    section: Mapped[str] = mapped_column(String(64))  # e.g. prefs.list, prefs.ui
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")


class SieveScriptBackup(IdMixin, TimestampMixin, Base):
    """Previous ManageSieve script content before each write (Filtre / Mimo kancelárie)."""

    __tablename__ = "sieve_script_backups"

    mailbox_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mailboxes.id", ondelete="CASCADE"), index=True)
    script_name: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(String(64))  # filters_save | vacation_save | restore
    person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"))
