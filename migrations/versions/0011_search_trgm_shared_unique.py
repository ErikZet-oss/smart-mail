"""Phase 1g-a hardening: pg_trgm, search weights, shared-book partial unique.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    # unaccent() is STABLE; wrap for expression indexes (ADR-009).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION immutable_unaccent(text)
        RETURNS text
        LANGUAGE sql
        IMMUTABLE
        PARALLEL SAFE
        STRICT
        AS $$ SELECT public.unaccent('public.unaccent', $1) $$;
        """
    )

    # Weights: subject A, Od/Komu/Kópia B, body D (was from=A, body=C).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION messages_search_vector_update() RETURNS trigger AS $$
        BEGIN
          NEW.search_vector :=
            setweight(to_tsvector('simple', unaccent(coalesce(NEW.subject, ''))), 'A') ||
            setweight(to_tsvector('simple', unaccent(
              coalesce(NEW.from_name, '') || ' ' || coalesce(NEW.from_email, '')
            )), 'B') ||
            setweight(to_tsvector('simple', unaccent(coalesce(NEW.to_addrs::text, ''))), 'B') ||
            setweight(to_tsvector('simple', unaccent(coalesce(NEW.cc_addrs::text, ''))), 'B') ||
            setweight(to_tsvector('simple', unaccent(
              coalesce(NEW.body_text, '') || ' ' || coalesce(NEW.preview, '')
            )), 'D');
          RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        UPDATE messages SET search_vector =
          setweight(to_tsvector('simple', unaccent(coalesce(subject, ''))), 'A') ||
          setweight(to_tsvector('simple', unaccent(
            coalesce(from_name, '') || ' ' || coalesce(from_email, '')
          )), 'B') ||
          setweight(to_tsvector('simple', unaccent(coalesce(to_addrs::text, ''))), 'B') ||
          setweight(to_tsvector('simple', unaccent(coalesce(cc_addrs::text, ''))), 'B') ||
          setweight(to_tsvector('simple', unaccent(
            coalesce(body_text, '') || ' ' || coalesce(preview, '')
          )), 'D');
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_messages_from_email_trgm
          ON messages USING gin (immutable_unaccent(lower(coalesce(from_email, ''))) gin_trgm_ops);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_messages_from_name_trgm
          ON messages USING gin (immutable_unaccent(lower(coalesce(from_name, ''))) gin_trgm_ops);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_messages_to_addrs_trgm
          ON messages USING gin (immutable_unaccent(lower(coalesce(to_addrs::text, ''))) gin_trgm_ops);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_messages_cc_addrs_trgm
          ON messages USING gin (immutable_unaccent(lower(coalesce(cc_addrs::text, ''))) gin_trgm_ops);
        """
    )

    # UNIQUE(kind, owner_person_id) allows many shared rows (NULL ≠ NULL). Enforce one shared + one personal/owner.
    op.execute("ALTER TABLE address_books DROP CONSTRAINT IF EXISTS uq_address_books_personal")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_address_books_personal
          ON address_books (owner_person_id) WHERE kind = 'personal';
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_address_books_one_shared
          ON address_books (kind) WHERE kind = 'shared';
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_address_books_one_shared")
    op.execute("DROP INDEX IF EXISTS uq_address_books_personal")
    op.execute(
        """
        ALTER TABLE address_books
          ADD CONSTRAINT uq_address_books_personal UNIQUE (kind, owner_person_id);
        """
    )
    op.execute("DROP INDEX IF EXISTS ix_messages_cc_addrs_trgm")
    op.execute("DROP INDEX IF EXISTS ix_messages_to_addrs_trgm")
    op.execute("DROP INDEX IF EXISTS ix_messages_from_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_messages_from_email_trgm")
    op.execute("DROP FUNCTION IF EXISTS immutable_unaccent(text)")
    # leave pg_trgm installed; dropping may break other indexes
