"""#139 Prehlásenie o zhode: branch stamp, person signature, issued declarations (approved by Erik).

Revision ID: 0017
Revises: 0016
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("branches", sa.Column("stamp_key", sa.String(255)))
    op.add_column("persons", sa.Column("signature_key", sa.String(255)))
    op.create_table(
        "conformity_declarations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("number", sa.String(20), nullable=False, unique=True),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("branches.id"), nullable=False, index=True),
        sa.Column("prepared_by_person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("persons.id"), nullable=False),
        sa.Column("signer_person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("persons.id"), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("customer_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("document_ref", sa.String(120), nullable=False, server_default=""),
        sa.Column("items", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("place", sa.String(80), nullable=False, server_default=""),
        sa.Column("issued_on", sa.Date(), nullable=False),
        sa.Column("pdf_storage_key", sa.String(255), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("messages.id", ondelete="SET NULL")),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("threads.id", ondelete="SET NULL")),
    )


def downgrade() -> None:
    op.drop_table("conformity_declarations")
    op.drop_column("persons", "signature_key")
    op.drop_column("branches", "stamp_key")
