"""Phase 2f: per-login settings (07 autonomy, D8) and company settings (17a budget, 17c categories) — #116, answer A.

Two new tables; no existing table changes. Reversible.

Revision ID: 0016
Revises: 0015
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base() -> list[sa.Column[Any]]:
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "account_settings",
        *_base(),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("section", sa.String(64), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("account_id", "section", name="uq_account_settings_account_section"),
    )
    op.create_table(
        "org_settings",
        *_base(),
        sa.Column("section", sa.String(64), nullable=False, unique=True),
        sa.Column("data", postgresql.JSONB(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_table("org_settings")
    op.drop_table("account_settings")
