"""Phase 1a: branches, persons, person_branches, accounts, sessions, audit_log (append-only).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-26
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

ROLE = pg.ENUM("admin", "sales", "warehouse", "accounting", "viewer", name="person_role", create_type=False)
KIND = pg.ENUM("personal", "branch", name="account_kind", create_type=False)
METHOD = pg.ENUM("imap", "oidc", name="auth_method", create_type=False)


def _ts() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    for enum in (ROLE, KIND, METHOD):
        enum.create(bind, checkfirst=True)

    op.create_table(
        "branches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("mailbox_id", sa.Uuid(), nullable=True),
        sa.Column("address", sa.String(200)),
        sa.Column("phone", sa.String(32)),
        sa.Column("hours", sa.String(120)),
        sa.Column("logo_key", sa.String(255)),
        sa.Column("idle_ask_minutes", sa.Integer()),
        sa.Column("remember_days", sa.Integer(), server_default="30", nullable=False),
        sa.Column("signature_template_html", pg.JSONB(), server_default="{}", nullable=False),
        sa.Column("signature_images", pg.JSONB(), server_default="[]", nullable=False),
        sa.Column("folder_ids", pg.JSONB(), server_default="[]", nullable=False),
        sa.Column("money_centre_id", sa.String(64)),
        sa.Column("money_price_list_id", sa.String(64)),
        sa.Column("money_warehouse_id", sa.String(64)),
        sa.Column("series_overrides", pg.JSONB(), server_default="{}", nullable=False),
        sa.Column("dl_template_money_id", sa.String(64)),
        sa.Column("dl_template_values", pg.JSONB()),
        sa.Column("dl_template_cached_at", sa.DateTime(timezone=True)),
        *_ts(),
        sa.UniqueConstraint("name", name="uq_branches_name"),
        sa.CheckConstraint("remember_days IN (1, 7, 30)", name="ck_branches_remember_days"),
        sa.CheckConstraint(
            "idle_ask_minutes IS NULL OR idle_ask_minutes IN (30, 60, 120)", name="ck_branches_idle_ask_minutes"
        ),
    )
    op.create_table(
        "persons",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("branch_id", sa.Uuid(), sa.ForeignKey("branches.id", name="fk_persons_branch_id_branches")),
        sa.Column("first_name", sa.String(80), nullable=False),
        sa.Column("last_name", sa.String(80), nullable=False),
        sa.Column("function", sa.String(60)),
        sa.Column("phone", sa.String(32)),
        sa.Column("mobile", sa.String(32)),
        sa.Column("photo_key", sa.String(255)),
        sa.Column("role", ROLE, nullable=False, server_default="sales"),
        sa.Column("money_staff_id", sa.String(64)),
        sa.Column("is_manager", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        *_ts(),
    )
    op.create_table(
        "person_branches",
        sa.Column(
            "person_id",
            sa.Uuid(),
            sa.ForeignKey("persons.id", ondelete="CASCADE", name="fk_person_branches_person_id_persons"),
            primary_key=True,
        ),
        sa.Column(
            "branch_id",
            sa.Uuid(),
            sa.ForeignKey("branches.id", ondelete="CASCADE", name="fk_person_branches_branch_id_branches"),
            primary_key=True,
        ),
    )
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("kind", KIND, nullable=False, server_default="personal"),
        sa.Column("auth_method", METHOD, nullable=False, server_default="imap"),
        sa.Column("branch_id", sa.Uuid(), sa.ForeignKey("branches.id", name="fk_accounts_branch_id_branches")),
        sa.Column("person_id", sa.Uuid(), sa.ForeignKey("persons.id", name="fk_accounts_person_id_persons")),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("password_fingerprint", sa.Text()),
        sa.Column("totp_secret_enc", sa.Text()),
        sa.Column("totp_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("totp_last_step", sa.Integer()),
        sa.Column("backup_code_hashes", pg.JSONB(), server_default="[]", nullable=False),
        sa.Column("require_2fa", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        *_ts(),
        sa.UniqueConstraint("email", name="uq_accounts_email"),
        sa.CheckConstraint("email = lower(email)", name="ck_accounts_email_lower"),
        sa.CheckConstraint("kind <> 'branch' OR branch_id IS NOT NULL", name="ck_accounts_branch_needs_branch"),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE", name="fk_sessions_account_id_accounts"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column(
            "active_person_id", sa.Uuid(), sa.ForeignKey("persons.id", name="fk_sessions_active_person_id_persons")
        ),
        sa.Column("device_id", sa.String(64)),
        sa.Column("remember", sa.Boolean(), nullable=False),
        sa.Column("mfa_pending", sa.Boolean(), nullable=False),
        sa.Column("mfa_failures", sa.Integer(), nullable=False),
        sa.Column("ip", sa.String(64)),
        sa.Column("user_agent", sa.String(400)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_reason", sa.String(32)),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
    )
    op.create_index("ix_sessions_account_id", "sessions", ["account_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("account_id", sa.Uuid()),
        sa.Column("person_id", sa.Uuid()),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("object_type", sa.String(40)),
        sa.Column("object_id", sa.String(64)),
        sa.Column("ip", sa.String(64)),
        sa.Column("details", pg.JSONB(), server_default="{}", nullable=False),
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])
    op.create_index("ix_audit_log_account_id", "audit_log", ["account_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    # append-only for every database role, including the owner (CLAUDE.md §4, §11)
    op.execute(
        """
        CREATE FUNCTION audit_log_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'audit_log is append-only (% blocked)', TG_OP USING ERRCODE = 'insufficient_privilege';
        END $$;
        """
    )
    op.execute(
        "CREATE TRIGGER audit_log_no_update_delete BEFORE UPDATE OR DELETE ON audit_log "
        "FOR EACH ROW EXECUTE FUNCTION audit_log_append_only()"
    )
    op.execute(
        "CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_log_append_only()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_truncate ON audit_log")
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_update_delete ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_append_only()")
    for table in ("audit_log", "sessions", "accounts", "person_branches", "persons", "branches"):
        op.drop_table(table)
    bind = op.get_bind()
    for enum in (METHOD, KIND, ROLE):
        enum.drop(bind, checkfirst=True)
