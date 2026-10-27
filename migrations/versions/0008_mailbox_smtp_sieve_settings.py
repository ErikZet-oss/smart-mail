"""Phase 1f: mailbox SMTP / ManageSieve / provider URL; person profile extras.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mailboxes", sa.Column("kind", sa.String(16), server_default="personal", nullable=False))
    op.add_column("mailboxes", sa.Column("smtp_host", sa.String(253), nullable=True))
    op.add_column("mailboxes", sa.Column("smtp_port", sa.Integer(), nullable=True))
    op.add_column("mailboxes", sa.Column("smtp_security", sa.String(16), nullable=True))
    op.add_column("mailboxes", sa.Column("sieve_enabled", sa.Boolean(), server_default="true", nullable=False))
    op.add_column("mailboxes", sa.Column("sieve_host", sa.String(253), nullable=True))
    op.add_column("mailboxes", sa.Column("sieve_port", sa.Integer(), server_default="4190", nullable=True))
    op.add_column("mailboxes", sa.Column("provider_admin_url", sa.String(500), nullable=True))
    op.add_column("mailboxes", sa.Column("ai_enabled", sa.Boolean(), server_default="true", nullable=False))
    op.add_column("persons", sa.Column("personal_email", sa.String(254), nullable=True))
    op.add_column(
        "persons",
        sa.Column("languages", postgresql.JSONB(), server_default='["sk"]', nullable=False),
    )
    op.add_column("persons", sa.Column("style_guide", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("persons", "style_guide")
    op.drop_column("persons", "languages")
    op.drop_column("persons", "personal_email")
    op.drop_column("mailboxes", "ai_enabled")
    op.drop_column("mailboxes", "provider_admin_url")
    op.drop_column("mailboxes", "sieve_port")
    op.drop_column("mailboxes", "sieve_host")
    op.drop_column("mailboxes", "sieve_enabled")
    op.drop_column("mailboxes", "smtp_security")
    op.drop_column("mailboxes", "smtp_port")
    op.drop_column("mailboxes", "smtp_host")
    op.drop_column("mailboxes", "kind")
