"""Phase 1h-c: assignment actor + time for W14 notifications.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "threads",
        sa.Column("assigned_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("persons.id", ondelete="SET NULL")),
    )
    op.add_column("threads", sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_threads_assigned_by_id", "threads", ["assigned_by_id"])


def downgrade() -> None:
    op.drop_index("ix_threads_assigned_by_id", table_name="threads")
    op.drop_column("threads", "assigned_at")
    op.drop_column("threads", "assigned_by_id")
