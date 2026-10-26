"""threads, message bodies, attachments, user_settings (Phase 1d).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "threads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "mailbox_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mailboxes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("thread_key", sa.String(80), nullable=False),
        sa.Column("subject", sa.Text),
        sa.Column("status", sa.String(16), server_default="open", nullable=False),
        sa.Column("snoozed_until", sa.DateTime(timezone=True)),
        sa.Column("assignee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("persons.id", ondelete="SET NULL")),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column("message_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unread_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("has_attachments", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("flagged", sa.Boolean(), server_default="false", nullable=False),
        sa.UniqueConstraint("mailbox_id", "thread_key"),
    )
    op.create_index("ix_threads_mailbox_id", "threads", ["mailbox_id"])
    op.create_index("ix_threads_last_message_at", "threads", ["last_message_at"])

    op.add_column(
        "messages",
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("threads.id", ondelete="SET NULL")),
    )
    op.add_column("messages", sa.Column("has_attachments", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("messages", sa.Column("preview", sa.String(240)))
    op.add_column("messages", sa.Column("body_text", sa.Text()))
    op.add_column("messages", sa.Column("body_html_sanitized", sa.Text()))
    op.add_column("messages", sa.Column("body_fetched_at", sa.DateTime(timezone=True)))
    op.add_column("messages", sa.Column("raw_storage_key", sa.String(500)))
    op.add_column("messages", sa.Column("auth_results", postgresql.JSONB()))
    op.create_index("ix_messages_thread_id", "messages", ["thread_id"])

    op.create_table(
        "attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(200), server_default="application/octet-stream", nullable=False),
        sa.Column("size", sa.Integer(), server_default="0", nullable=False),
        sa.Column("content_id", sa.String(998)),
        sa.Column("is_inline", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("av_status", sa.String(16), server_default="skipped", nullable=False),
    )
    op.create_index("ix_attachments_message_id", "attachments", ["message_id"])

    op.create_table(
        "user_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("persons.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("section", sa.String(64), nullable=False),
        sa.Column("data", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.UniqueConstraint("person_id", "section"),
    )
    op.create_index("ix_user_settings_person_id", "user_settings", ["person_id"])


def downgrade() -> None:
    op.drop_table("user_settings")
    op.drop_table("attachments")
    op.drop_index("ix_messages_thread_id", table_name="messages")
    op.drop_column("messages", "auth_results")
    op.drop_column("messages", "raw_storage_key")
    op.drop_column("messages", "body_fetched_at")
    op.drop_column("messages", "body_html_sanitized")
    op.drop_column("messages", "body_text")
    op.drop_column("messages", "preview")
    op.drop_column("messages", "has_attachments")
    op.drop_column("messages", "thread_id")
    op.drop_table("threads")
