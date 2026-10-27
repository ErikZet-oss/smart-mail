"""Phase 1g: local contacts + message FTS (unaccent) + private folder owner.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "folders_meta",
        sa.Column("owner_person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("persons.id", ondelete="SET NULL")),
    )
    op.create_index("ix_folders_meta_owner_person_id", "folders_meta", ["owner_person_id"])

    op.add_column("messages", sa.Column("search_vector", postgresql.TSVECTOR()))
    op.create_index("ix_messages_search_vector", "messages", ["search_vector"], postgresql_using="gin")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION messages_search_vector_update() RETURNS trigger AS $$
        BEGIN
          NEW.search_vector :=
            setweight(to_tsvector('simple', unaccent(coalesce(NEW.subject, ''))), 'A') ||
            setweight(to_tsvector('simple', unaccent(
              coalesce(NEW.from_name, '') || ' ' || coalesce(NEW.from_email, '')
            )), 'A') ||
            setweight(to_tsvector('simple', unaccent(coalesce(NEW.to_addrs::text, ''))), 'B') ||
            setweight(to_tsvector('simple', unaccent(coalesce(NEW.cc_addrs::text, ''))), 'B') ||
            setweight(to_tsvector('simple', unaccent(
              coalesce(NEW.body_text, '') || ' ' || coalesce(NEW.preview, '')
            )), 'C');
          RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER messages_search_vector_trigger
        BEFORE INSERT OR UPDATE OF subject, from_name, from_email, to_addrs, cc_addrs, body_text, preview
        ON messages
        FOR EACH ROW EXECUTE FUNCTION messages_search_vector_update();
        """
    )
    op.execute(
        """
        UPDATE messages SET search_vector =
          setweight(to_tsvector('simple', unaccent(coalesce(subject, ''))), 'A') ||
          setweight(to_tsvector('simple', unaccent(
            coalesce(from_name, '') || ' ' || coalesce(from_email, '')
          )), 'A') ||
          setweight(to_tsvector('simple', unaccent(coalesce(to_addrs::text, ''))), 'B') ||
          setweight(to_tsvector('simple', unaccent(coalesce(cc_addrs::text, ''))), 'B') ||
          setweight(to_tsvector('simple', unaccent(
            coalesce(body_text, '') || ' ' || coalesce(preview, '')
          )), 'C');
        """
    )

    op.create_table(
        "address_books",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "owner_person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("persons.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("kind", "owner_person_id", name="uq_address_books_personal"),
    )
    op.create_index("ix_address_books_owner_person_id", "address_books", ["owner_person_id"])

    op.create_table(
        "contact_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "address_book_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("address_books.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("address_book_id", "name"),
    )
    op.create_index("ix_contact_groups_address_book_id", "contact_groups", ["address_book_id"])

    op.create_table(
        "contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "address_book_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("address_books.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("first_name", sa.String(80)),
        sa.Column("last_name", sa.String(80)),
        sa.Column("organization", sa.String(200)),
        sa.Column("notes", sa.Text()),
        sa.Column("emails", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("phones", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_contacts_address_book_id", "contacts", ["address_book_id"])

    op.create_table(
        "contact_group_members",
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contacts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contact_groups.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "recent_recipients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("persons.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("name", sa.String(200)),
        sa.Column("use_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("person_id", "email"),
    )
    op.create_index("ix_recent_recipients_person_id", "recent_recipients", ["person_id"])


def downgrade() -> None:
    op.drop_index("ix_recent_recipients_person_id", table_name="recent_recipients")
    op.drop_table("recent_recipients")
    op.drop_table("contact_group_members")
    op.drop_index("ix_contacts_address_book_id", table_name="contacts")
    op.drop_table("contacts")
    op.drop_index("ix_contact_groups_address_book_id", table_name="contact_groups")
    op.drop_table("contact_groups")
    op.drop_index("ix_address_books_owner_person_id", table_name="address_books")
    op.drop_table("address_books")
    op.execute("DROP TRIGGER IF EXISTS messages_search_vector_trigger ON messages")
    op.execute("DROP FUNCTION IF EXISTS messages_search_vector_update()")
    op.drop_index("ix_messages_search_vector", table_name="messages")
    op.drop_column("messages", "search_vector")
    op.drop_index("ix_folders_meta_owner_person_id", table_name="folders_meta")
    op.drop_column("folders_meta", "owner_person_id")
