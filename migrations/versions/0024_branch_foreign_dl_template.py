"""SETTINGS 11e: second branch template for foreign suppliers (0 % VAT) — asked for by Erik 2026-11-25.

Revision ID: 0024
Revises: 0023
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("branches", sa.Column("dl_template_foreign_money_id", sa.String(64), nullable=True))
    op.add_column("branches", sa.Column("dl_template_foreign_values", postgresql.JSONB(), nullable=True))
    op.add_column("branches", sa.Column("dl_template_foreign_cached_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("branches", "dl_template_foreign_cached_at")
    op.drop_column("branches", "dl_template_foreign_values")
    op.drop_column("branches", "dl_template_foreign_money_id")
