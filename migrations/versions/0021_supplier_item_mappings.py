"""Phase 4b: learned supplier item mappings (docs/phase4-plan.md §5, approved by Erik in #191).

Revision ID: 0021
Revises: 0020
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "supplier_item_mappings",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("supplier_money_id", UUID, nullable=False),
        sa.Column("code_norm", sa.String(64), nullable=False),
        sa.Column("article_id", UUID, nullable=False),
        sa.Column("unit_factor", sa.Numeric(18, 6), nullable=False, server_default="1"),
        sa.Column("confirmed_by_person_id", UUID, sa.ForeignKey("persons.id", ondelete="SET NULL")),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("uses_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("supplier_money_id", "code_norm", name="uq_supplier_item_mappings"),
    )


def downgrade() -> None:
    op.drop_table("supplier_item_mappings")
