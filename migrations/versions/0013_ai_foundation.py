"""Phase 2a: ai_enabled_at, AI tables, feature_flags; AI off by default.

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mailboxes", sa.Column("ai_enabled_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column(
        "mailboxes",
        "ai_enabled",
        existing_type=sa.Boolean(),
        server_default="false",
        existing_nullable=False,
    )
    # Test / pilot installs: do not process until an admin enables AI (sets ai_enabled_at).
    op.execute(sa.text("UPDATE mailboxes SET ai_enabled = false WHERE ai_enabled_at IS NULL"))

    op.create_table(
        "ai_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), server_default="0", nullable=False),
        sa.Column("latency_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("mailbox_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mailboxes.id", ondelete="SET NULL")),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("messages.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(16), server_default="ok", nullable=False),
        sa.Column("error_class", sa.String(64), nullable=True),
    )
    op.create_index("ix_ai_runs_mailbox_id", "ai_runs", ["mailbox_id"])
    op.create_index("ix_ai_runs_message_id", "ai_runs", ["message_id"])

    op.create_table(
        "classifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("mailbox_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mailboxes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id_header", sa.String(998), nullable=True),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("priority", sa.String(16), nullable=True),
        sa.Column("payload", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("ai_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_runs.id", ondelete="SET NULL")),
        sa.Column("shadow", sa.Boolean(), server_default="false", nullable=False),
        sa.UniqueConstraint("message_id_header", name="uq_classifications_message_id_header"),
    )
    op.create_index("ix_classifications_mailbox_id", "classifications", ["mailbox_id"])
    op.create_index("ix_classifications_message_id", "classifications", ["message_id"])
    op.create_index("ix_classifications_message_id_header", "classifications", ["message_id_header"])

    op.create_table(
        "ai_suggestions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("mailbox_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mailboxes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("messages.id", ondelete="CASCADE")),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("threads.id", ondelete="CASCADE")),
        sa.Column("suggestion_type", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("checks", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("decided_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("persons.id", ondelete="SET NULL")),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("final_payload", postgresql.JSONB(), nullable=True),
        sa.Column("diff", postgresql.JSONB(), nullable=True),
        sa.Column("batch_safe", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("shadow", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "classification_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("classifications.id", ondelete="SET NULL"),
        ),
    )
    op.create_index("ix_ai_suggestions_mailbox_id", "ai_suggestions", ["mailbox_id"])
    op.create_index("ix_ai_suggestions_message_id", "ai_suggestions", ["message_id"])
    op.create_index("ix_ai_suggestions_thread_id", "ai_suggestions", ["thread_id"])
    op.create_index("ix_ai_suggestions_classification_id", "ai_suggestions", ["classification_id"])

    op.create_table(
        "feature_flags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("persons.id", ondelete="CASCADE")),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("data", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.UniqueConstraint("key", "person_id", name="uq_feature_flags_key_person"),
    )
    op.create_index("ix_feature_flags_key", "feature_flags", ["key"])
    op.create_index("ix_feature_flags_person_id", "feature_flags", ["person_id"])

    # Seed global shadow-mode flag (off): suggestions may be created later but UI stays hidden until 2f.
    op.execute(
        sa.text(
            "INSERT INTO feature_flags (id, key, person_id, enabled, data) "
            "VALUES (gen_random_uuid(), 'ai_shadow_mode', NULL, false, '{}'::jsonb)"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_feature_flags_person_id", table_name="feature_flags")
    op.drop_index("ix_feature_flags_key", table_name="feature_flags")
    op.drop_table("feature_flags")
    op.drop_index("ix_ai_suggestions_classification_id", table_name="ai_suggestions")
    op.drop_index("ix_ai_suggestions_thread_id", table_name="ai_suggestions")
    op.drop_index("ix_ai_suggestions_message_id", table_name="ai_suggestions")
    op.drop_index("ix_ai_suggestions_mailbox_id", table_name="ai_suggestions")
    op.drop_table("ai_suggestions")
    op.drop_index("ix_classifications_message_id_header", table_name="classifications")
    op.drop_index("ix_classifications_message_id", table_name="classifications")
    op.drop_index("ix_classifications_mailbox_id", table_name="classifications")
    op.drop_table("classifications")
    op.drop_index("ix_ai_runs_message_id", table_name="ai_runs")
    op.drop_index("ix_ai_runs_mailbox_id", table_name="ai_runs")
    op.drop_table("ai_runs")
    op.drop_column("mailboxes", "ai_enabled_at")
    op.alter_column(
        "mailboxes",
        "ai_enabled",
        existing_type=sa.Boolean(),
        server_default="true",
        existing_nullable=False,
    )
