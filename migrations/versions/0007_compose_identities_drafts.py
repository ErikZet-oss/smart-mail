"""Phase 1e: identities, canned responses, compose drafts and attachments.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "mailbox_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mailboxes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("organization", sa.String(100)),
        sa.Column("reply_to", sa.String(254)),
        sa.Column("bcc", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("signature_html", postgresql.JSONB(), server_default="{}", nullable=False),
    )
    op.create_index("ix_identities_mailbox_id", "identities", ["mailbox_id"])

    op.create_table(
        "responses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("persons.id", ondelete="CASCADE")),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("language", sa.String(8), server_default="sk", nullable=False),
        sa.Column("body_html", sa.Text(), nullable=False),
        sa.Column("shared", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("shortcut", sa.String(20)),
    )
    op.create_index("ix_responses_person_id", "responses", ["person_id"])

    op.create_table(
        "compose_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "mailbox_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mailboxes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("persons.id", ondelete="SET NULL")),
        sa.Column("identity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("identities.id", ondelete="SET NULL")),
        sa.Column("mode", sa.String(16), server_default="new", nullable=False),
        sa.Column(
            "in_reply_to_message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
        ),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("threads.id", ondelete="SET NULL")),
        sa.Column("to_addrs", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("cc_addrs", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("bcc_addrs", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("subject", sa.Text(), server_default="", nullable=False),
        sa.Column("body_html", sa.Text(), server_default="", nullable=False),
        sa.Column("body_text", sa.Text(), server_default="", nullable=False),
        sa.Column("include_signature", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("signature_html_override", sa.Text()),
        sa.Column(
            "signature_person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("persons.id", ondelete="SET NULL")
        ),
        sa.Column("priority", sa.String(16), server_default="normal", nullable=False),
        sa.Column("request_mdn", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("request_dsn", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("save_sent", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("status", sa.String(16), server_default="editing", nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("undo_until", sa.DateTime(timezone=True)),
        sa.Column("send_error", sa.String(200)),
        sa.Column("imap_draft_uid", sa.Integer()),
        sa.Column("final_message_id", sa.String(998)),
    )
    op.create_index("ix_compose_drafts_mailbox_id", "compose_drafts", ["mailbox_id"])

    op.create_table(
        "compose_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "draft_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("compose_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(200), server_default="application/octet-stream", nullable=False),
        sa.Column("size", sa.Integer(), server_default="0", nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("is_inline", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("content_id", sa.String(998)),
        sa.Column("av_status", sa.String(16), server_default="skipped", nullable=False),
    )
    op.create_index("ix_compose_attachments_draft_id", "compose_attachments", ["draft_id"])


def downgrade() -> None:
    op.drop_table("compose_attachments")
    op.drop_table("compose_drafts")
    op.drop_table("responses")
    op.drop_table("identities")
