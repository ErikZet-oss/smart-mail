"""#228 read cache of Money `ArticleSuppliers` (supplier codes) — approved by Erik 2026-11-20.

Revision ID: 0022
Revises: 0021
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "money_article_suppliers",
        sa.Column("id", UUID, primary_key=True),  # ArticleSuppliers.ID
        sa.Column("article_id", UUID, nullable=False),
        sa.Column("supplier_id", UUID, nullable=False),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("code_norm", sa.String(120), nullable=False),
        sa.Column("name", sa.String(255)),
        sa.Column("last_price", sa.Numeric(18, 6)),
        sa.Column("unit", sa.String(40)),
        sa.Column("article_unit", sa.String(40)),
        sa.Column("article_unit_qty", sa.Numeric(18, 6)),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_money_article_suppliers_supplier_code", "money_article_suppliers", ["supplier_id", "code_norm"]
    )
    op.create_index("ix_money_article_suppliers_article_id", "money_article_suppliers", ["article_id"])


def downgrade() -> None:
    op.drop_index("ix_money_article_suppliers_article_id", table_name="money_article_suppliers")
    op.drop_index("ix_money_article_suppliers_supplier_code", table_name="money_article_suppliers")
    op.drop_table("money_article_suppliers")
