"""Phase 3b Money read cache: companies, persons, codebooks, e-mail ↔ company links, sync state (#150, approved).

Revision ID: 0018
Revises: 0017
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def _base() -> list[sa.Column[Any]]:
    return [
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "money_companies",
        *_base(),
        sa.Column("money_id", UUID, nullable=False, unique=True),
        sa.Column("code", sa.String(40)),
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column("ico", sa.String(20), index=True),
        sa.Column("dic", sa.String(20)),
        sa.Column("icdph", sa.String(20)),
        sa.Column("email", sa.String(320)),
        sa.Column("discount_pct", sa.Numeric(9, 4)),
        sa.Column("due_days", sa.Integer()),
        sa.Column("connections", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("emails", postgresql.ARRAY(sa.String(320)), nullable=False, server_default="{}"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_money_companies_emails", "money_companies", ["emails"], postgresql_using="gin")
    op.create_table(
        "money_persons",
        *_base(),
        sa.Column("money_id", UUID, nullable=False, unique=True),
        sa.Column("company_money_id", UUID, index=True),
        sa.Column("first_name", sa.String(120)),
        sa.Column("last_name", sa.String(120)),
        sa.Column("name", sa.String(255)),
        sa.Column("function", sa.String(120)),
        sa.Column("email", sa.String(320), index=True),
        sa.Column("phone", sa.String(60)),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "money_codebooks",
        *_base(),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("money_id", UUID, nullable=False),
        sa.Column("code", sa.String(60)),
        sa.Column("name", sa.String(255)),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("kind", "money_id"),
    )
    op.create_table(
        "email_company_links",
        *_base(),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("company_money_id", UUID, nullable=False),
        sa.Column("confirmed_by_person_id", UUID, sa.ForeignKey("persons.id", ondelete="SET NULL")),
        sa.Column("confirmed_by_account_id", UUID, sa.ForeignKey("accounts.id", ondelete="SET NULL")),
        sa.Column("note", sa.Text()),
    )
    op.create_table(
        "money_sync_state",
        *_base(),
        sa.Column("entity", sa.String(60), nullable=False, unique=True),
        sa.Column("cursor", sa.DateTime(timezone=True)),
        sa.Column("last_full_at", sa.DateTime(timezone=True)),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_status", sa.String(20)),
        sa.Column("last_error", sa.String(60)),
        sa.Column("history", postgresql.JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_table("money_sync_state")
    op.drop_table("email_company_links")
    op.drop_table("money_codebooks")
    op.drop_table("money_persons")
    op.drop_index("ix_money_companies_emails", table_name="money_companies")
    op.drop_table("money_companies")
