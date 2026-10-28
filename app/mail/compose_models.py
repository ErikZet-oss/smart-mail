"""Compose identities, canned responses and drafts (Phase 1e, CLAUDE.md §4, SETTINGS 03a/04)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin


class Identity(IdMixin, TimestampMixin, Base):
    __tablename__ = "identities"

    mailbox_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mailboxes.id", ondelete="CASCADE"), index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(254))
    organization: Mapped[str | None] = mapped_column(String(100))
    reply_to: Mapped[str | None] = mapped_column(String(254))
    bcc: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # personal mailbox HTML signatures per language; branch mailboxes leave empty and use Branch.signature_template_html
    signature_html: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict, server_default="{}")
    # uploaded signature images (D22): [{id, cid, storage_key, content_type, size, filename}]
    signature_images: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")


class CannedResponse(IdMixin, TimestampMixin, Base):
    __tablename__ = "responses"

    person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    language: Mapped[str] = mapped_column(String(8), default="sk", server_default="sk")
    body_html: Mapped[str] = mapped_column(Text)
    shared: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    shortcut: Mapped[str | None] = mapped_column(String(20))


class ComposeDraft(IdMixin, TimestampMixin, Base):
    __tablename__ = "compose_drafts"

    mailbox_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mailboxes.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"))
    identity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("identities.id", ondelete="SET NULL"))
    mode: Mapped[str] = mapped_column(String(16), default="new", server_default="new")  # new|reply|reply_all|forward
    in_reply_to_message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    thread_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("threads.id", ondelete="SET NULL"))
    to_addrs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    cc_addrs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    bcc_addrs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    subject: Mapped[str] = mapped_column(Text, default="", server_default="")
    body_html: Mapped[str] = mapped_column(Text, default="", server_default="")
    body_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    include_signature: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    signature_html_override: Mapped[str | None] = mapped_column(Text)  # W4e edit for this message
    signature_person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"))
    priority: Mapped[str] = mapped_column(String(16), default="normal", server_default="normal")  # low|normal|high
    request_mdn: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")  # delivery receipt
    request_dsn: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    save_sent: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    status: Mapped[str] = mapped_column(
        String(16), default="editing", server_default="editing"
    )  # editing|queued|sending|sent|failed|scheduled|cancelled
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    undo_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    send_error: Mapped[str | None] = mapped_column(String(200))
    imap_draft_uid: Mapped[int | None] = mapped_column(Integer)
    final_message_id: Mapped[str | None] = mapped_column(String(998))


class ComposeAttachment(IdMixin, TimestampMixin, Base):
    __tablename__ = "compose_attachments"

    draft_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("compose_drafts.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(200), default="application/octet-stream")
    size: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    storage_key: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))
    is_inline: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    content_id: Mapped[str | None] = mapped_column(String(998))
    av_status: Mapped[str] = mapped_column(String(16), default="skipped", server_default="skipped")
