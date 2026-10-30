"""Phase 2e: knowledge cards (incl. the company style guide) and AI rules (#110, Erik's answer A).

Revision ID: 0015
Revises: 0014
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VECTOR = (
    "setweight(to_tsvector('simple', unaccent(coalesce({p}title, ''))), 'A') || "
    "setweight(to_tsvector('simple', unaccent(array_to_string(coalesce({p}tags, '{{}}'), ' '))), 'A') || "
    "setweight(to_tsvector('simple', unaccent(coalesce({p}body, ''))), 'B')"
)


def upgrade() -> None:
    op.create_table(
        "knowledge_cards",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="knowledge"),  # knowledge | style_guide
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("valid_until", sa.Date()),
        sa.Column("tags", postgresql.ARRAY(sa.String(64)), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_by_person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("persons.id", ondelete="SET NULL"),
        ),
        sa.Column("search_vector", postgresql.TSVECTOR()),
        sa.CheckConstraint("kind IN ('knowledge', 'style_guide')", name="ck_knowledge_cards_kind"),
    )
    # The company style guide is the single row of kind style_guide.
    op.create_index(
        "uq_knowledge_cards_style_guide",
        "knowledge_cards",
        ["kind"],
        unique=True,
        postgresql_where=sa.text("kind = 'style_guide'"),
    )
    op.create_index("ix_knowledge_cards_search_vector", "knowledge_cards", ["search_vector"], postgresql_using="gin")
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION knowledge_cards_search_vector_update() RETURNS trigger AS $$
        BEGIN
          NEW.search_vector := {_VECTOR.format(p="NEW.")};
          RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER knowledge_cards_search_vector_trigger
        BEFORE INSERT OR UPDATE OF title, tags, body ON knowledge_cards
        FOR EACH ROW EXECUTE FUNCTION knowledge_cards_search_vector_update();
        """
    )

    op.create_table(
        "ai_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("nl_text", sa.Text(), nullable=False),
        sa.Column("structured", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_by_person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("persons.id", ondelete="SET NULL"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("ai_rules")
    op.execute("DROP TRIGGER IF EXISTS knowledge_cards_search_vector_trigger ON knowledge_cards")
    op.execute("DROP FUNCTION IF EXISTS knowledge_cards_search_vector_update()")
    op.drop_table("knowledge_cards")
