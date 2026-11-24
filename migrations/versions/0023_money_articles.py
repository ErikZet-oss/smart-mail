"""W6h Katalóg: read cache of Money `Articles` (the whole catalog) — approved by Erik 2026-11-24.

Revision ID: 0023
Revises: 0022
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "money_articles",
        sa.Column("id", UUID, primary_key=True),  # Articles.ID
        sa.Column("code", sa.String(100)),
        sa.Column("catalog", sa.String(100)),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("ean", sa.String(64)),
        sa.Column("unit", sa.String(40)),
        sa.Column("parent_id", UUID),
        sa.Column("plu", sa.String(64)),
        sa.Column("last_price", sa.Numeric(18, 6)),
        sa.Column("search_norm", sa.Text(), nullable=False),
        sa.Column("name_norm", sa.Text(), nullable=False),
        sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_money_articles_catalog", "money_articles", ["catalog"])
    op.create_index("ix_money_articles_ean", "money_articles", ["ean"])
    op.create_index("ix_money_articles_parent_id", "money_articles", ["parent_id"])


def downgrade() -> None:
    op.drop_index("ix_money_articles_parent_id", table_name="money_articles")
    op.drop_index("ix_money_articles_ean", table_name="money_articles")
    op.drop_index("ix_money_articles_catalog", table_name="money_articles")
    op.drop_table("money_articles")
