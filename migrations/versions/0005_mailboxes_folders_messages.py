"""Phase 1c: mailboxes, mailbox_access, folders_meta, message envelopes; branches.mailbox_id gets its FK.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-26
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _ts() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "mailboxes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("imap_host", sa.String(253), nullable=False),
        sa.Column("imap_port", sa.Integer(), nullable=False),
        sa.Column("imap_security", sa.String(16), nullable=False),
        sa.Column(
            "credential_account_id",
            sa.Uuid(),
            sa.ForeignKey("accounts.id", ondelete="SET NULL", name="fk_mailboxes_credential_account_id_accounts"),
        ),
        sa.Column("capabilities", pg.JSONB(), server_default="[]", nullable=False),
        sa.Column("quota_used_kb", sa.BigInteger()),
        sa.Column("quota_limit_kb", sa.BigInteger()),
        sa.Column("quota_checked_at", sa.DateTime(timezone=True)),
        sa.Column("sync_state", sa.String(16), server_default="new", nullable=False),
        sa.Column("sync_error", sa.String(64)),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        *_ts(),
        sa.UniqueConstraint("email", name="uq_mailboxes_email"),
        sa.CheckConstraint("imap_security IN ('ssl', 'starttls', 'none')", name="ck_mailboxes_imap_security"),
        sa.CheckConstraint("sync_state IN ('new', 'ok', 'error', 'auth_failed')", name="ck_mailboxes_sync_state"),
    )
    op.create_table(
        "mailbox_access",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mailbox_id", sa.Uuid(), sa.ForeignKey("mailboxes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("can_send", sa.Boolean(), server_default="true", nullable=False),
        *_ts(),
        sa.UniqueConstraint("account_id", "mailbox_id", name="uq_mailbox_access_account_id"),
    )
    op.create_index("ix_mailbox_access_account_id", "mailbox_access", ["account_id"])
    op.create_table(
        "folders_meta",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("mailbox_id", sa.Uuid(), sa.ForeignKey("mailboxes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("delimiter", sa.String(1)),
        sa.Column("special_use", sa.String(16)),
        sa.Column("subscribed", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("selectable", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("private", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("uidvalidity", sa.BigInteger()),
        sa.Column("uidnext", sa.BigInteger()),
        sa.Column("highestmodseq", sa.BigInteger()),
        sa.Column("total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unread", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        *_ts(),
        sa.UniqueConstraint("mailbox_id", "name", name="uq_folders_meta_mailbox_id"),
        sa.CheckConstraint(
            "special_use IS NULL OR special_use IN ('inbox', 'drafts', 'sent', 'junk', 'trash')",
            name="ck_folders_meta_special_use",
        ),
    )
    op.create_index("ix_folders_meta_mailbox_id", "folders_meta", ["mailbox_id"])
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("mailbox_id", sa.Uuid(), sa.ForeignKey("mailboxes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("folder_id", sa.Uuid(), sa.ForeignKey("folders_meta.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uid", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.String(998)),
        sa.Column("in_reply_to", sa.String(998)),
        sa.Column("references", sa.Text()),
        sa.Column("subject", sa.Text()),
        sa.Column("from_name", sa.String(400)),
        sa.Column("from_email", sa.String(254)),
        sa.Column("to_addrs", pg.JSONB(), server_default="[]", nullable=False),
        sa.Column("cc_addrs", pg.JSONB(), server_default="[]", nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("size", sa.Integer(), server_default="0", nullable=False),
        sa.Column("flags", pg.JSONB(), server_default="[]", nullable=False),
        sa.Column("seen", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("flagged", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("answered", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("modseq", sa.BigInteger()),
        *_ts(),
        sa.UniqueConstraint("folder_id", "uid", name="uq_messages_folder_id"),
    )
    op.create_index("ix_messages_mailbox_id", "messages", ["mailbox_id"])
    op.create_index("ix_messages_message_id", "messages", ["message_id"])
    op.create_index("ix_messages_received_at", "messages", ["received_at"])
    op.create_foreign_key(
        "fk_branches_mailbox_id_mailboxes", "branches", "mailboxes", ["mailbox_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint("fk_branches_mailbox_id_mailboxes", "branches", type_="foreignkey")
    op.drop_table("messages")
    op.drop_table("folders_meta")
    op.drop_table("mailbox_access")
    op.drop_table("mailboxes")
