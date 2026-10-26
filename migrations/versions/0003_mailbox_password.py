"""Encrypted mailbox password on accounts (DECISIONS D27).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-26
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("mailbox_password_enc", sa.Text(), nullable=True))
    op.add_column("accounts", sa.Column("mailbox_password_set_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("accounts", "mailbox_password_set_at")
    op.drop_column("accounts", "mailbox_password_enc")
