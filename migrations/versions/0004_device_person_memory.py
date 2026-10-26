"""Phase 1b: the device remembers the last person of the "Kto ste?" picker (CLAUDE.md §4 device_person_memory).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-26
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_person_memory",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("last_person_id", sa.Uuid(), sa.ForeignKey("persons.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("device_id", "account_id"),
    )


def downgrade() -> None:
    op.drop_table("device_person_memory")
