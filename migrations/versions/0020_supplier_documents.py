"""Phase 4a: supplier documents and their lines (docs/phase4-plan.md §5, approved by Erik in #191).

Revision ID: 0020
Revises: 0019
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB()


def _stamps() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("message_id", UUID, sa.ForeignKey("messages.id", ondelete="SET NULL")),
        sa.Column("attachment_id", UUID, sa.ForeignKey("attachments.id", ondelete="SET NULL")),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(200), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("branch_id", UUID, sa.ForeignKey("branches.id", ondelete="SET NULL")),
        sa.Column("supplier_money_id", UUID),
        sa.Column("supplier_name", sa.String(255)),
        sa.Column("supplier_ico", sa.String(16)),
        sa.Column("doc_number", sa.String(64)),
        sa.Column("delivery_note_number", sa.String(64)),
        sa.Column("order_reference", sa.String(64)),
        sa.Column("doc_date", sa.Date()),
        sa.Column("currency", sa.String(3)),
        sa.Column("total", sa.Numeric(18, 2)),
        sa.Column("vat_recap", JSONB, nullable=False, server_default="[]"),
        sa.Column("fees", JSONB, nullable=False, server_default="[]"),
        sa.Column("extract_method", sa.String(24)),
        sa.Column("extracted", JSONB, nullable=False, server_default="{}"),
        sa.Column("field_confidence", JSONB, nullable=False, server_default="{}"),
        sa.Column("validation", JSONB, nullable=False, server_default="[]"),
        sa.Column("error", sa.Text()),
        sa.Column("money_doc_id", UUID),
        sa.Column("money_number", sa.String(64)),
        sa.Column("idempotency_key", sa.String(64), nullable=False, unique=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("readback_diff", JSONB),
        sa.Column("template_source", sa.String(64)),
        sa.Column("created_by_person_id", UUID, sa.ForeignKey("persons.id", ondelete="SET NULL")),
        sa.Column("ai_run_id", UUID, sa.ForeignKey("ai_runs.id", ondelete="SET NULL")),
        *_stamps(),
        sa.UniqueConstraint("sha256", "message_id", name="uq_documents_sha_message"),
    )
    for col in ("status", "message_id", "sha256", "supplier_money_id", "doc_number"):
        op.create_index(f"ix_documents_{col}", "documents", [col])
    op.create_table(
        "document_lines",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("document_id", UUID, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("supplier_code", sa.String(64)),
        sa.Column("ean", sa.String(32)),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("qty", sa.Numeric(18, 3)),
        sa.Column("unit", sa.String(16)),
        sa.Column("unit_price", sa.Numeric(18, 4)),
        sa.Column("vat_rate", sa.Numeric(5, 2)),
        sa.Column("line_total", sa.Numeric(18, 2)),
        sa.Column("is_fee", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("raw", JSONB, nullable=False, server_default="{}"),
        sa.Column("article_id", UUID),
        sa.Column("match_method", sa.String(32)),
        sa.Column("candidates", JSONB, nullable=False, server_default="[]"),
        sa.Column("unit_factor", sa.Numeric(18, 6)),
        sa.Column("warehouse_id", UUID),
        sa.Column("line_status", sa.String(16), nullable=False, server_default="unmatched"),
        *_stamps(),
        sa.UniqueConstraint("document_id", "line_no", name="uq_document_lines_no"),
    )
    op.create_index("ix_document_lines_document_id", "document_lines", ["document_id"])


def downgrade() -> None:
    op.drop_table("document_lines")
    op.drop_table("documents")
