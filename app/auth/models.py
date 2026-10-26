"""Accounts, sessions, branches and persons (CLAUDE.md §4, PRODUCT_SPEC §2.0, SETTINGS_SPEC 10–11).

An *account* is the login principal: a mailbox address verified against the IMAP server (personal mailbox or a
shared branch mailbox). A *person* is who actually works; roles belong to the person, not to the login (CLAUDE.md §9).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin


class Role(enum.StrEnum):
    admin = "admin"
    sales = "sales"
    warehouse = "warehouse"
    accounting = "accounting"
    viewer = "viewer"


class AccountKind(enum.StrEnum):
    personal = "personal"
    branch = "branch"


class AuthMethod(enum.StrEnum):
    imap = "imap"
    oidc = "oidc"


def _enum(e: type[enum.StrEnum], name: str) -> Enum:
    return Enum(e, name=name, values_callable=lambda members: [m.value for m in members])


class Branch(IdMixin, TimestampMixin, Base):
    __tablename__ = "branches"

    name: Mapped[str] = mapped_column(String(120), unique=True)
    # FK to mailboxes is added together with the mailboxes table (Settings › Schránky)
    mailbox_id: Mapped[uuid.UUID | None]
    address: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(32))
    hours: Mapped[str | None] = mapped_column(String(120))
    logo_key: Mapped[str | None] = mapped_column(String(255))
    idle_ask_minutes: Mapped[int | None] = mapped_column(Integer)
    remember_days: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    signature_template_html: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict, server_default="{}")
    signature_images: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    folder_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    money_centre_id: Mapped[str | None] = mapped_column(String(64))
    money_price_list_id: Mapped[str | None] = mapped_column(String(64))
    money_warehouse_id: Mapped[str | None] = mapped_column(String(64))
    series_overrides: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    dl_template_money_id: Mapped[str | None] = mapped_column(String(64))
    dl_template_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    dl_template_cached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Person(IdMixin, TimestampMixin, Base):
    __tablename__ = "persons"

    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branches.id"))
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    function: Mapped[str | None] = mapped_column(String(60))
    phone: Mapped[str | None] = mapped_column(String(32))
    mobile: Mapped[str | None] = mapped_column(String(32))
    photo_key: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(_enum(Role, "person_role"), default=Role.sales)
    money_staff_id: Mapped[str | None] = mapped_column(String(64))
    is_manager: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class PersonBranch(Base):
    """A person covering more branches appears in the picker of each of them (PRODUCT_SPEC §2.0)."""

    __tablename__ = "person_branches"

    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), primary_key=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"), primary_key=True)


class Account(IdMixin, TimestampMixin, Base):
    __tablename__ = "accounts"

    email: Mapped[str] = mapped_column(String(254), unique=True)  # always stored lower-case
    kind: Mapped[AccountKind] = mapped_column(_enum(AccountKind, "account_kind"), default=AccountKind.personal)
    auth_method: Mapped[AuthMethod] = mapped_column(_enum(AuthMethod, "auth_method"), default=AuthMethod.imap)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branches.id"))
    person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id"))  # personal accounts only
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # scrypt fingerprint of the last mailbox password that logged in; a different password = changed on the mail server
    password_fingerprint: Mapped[str | None] = mapped_column(Text)
    # the mailbox password itself, Fernet-encrypted (APP_ENCRYPTION_KEY), for the background mail sync (DECISIONS D27)
    mailbox_password_enc: Mapped[str | None] = mapped_column(Text)
    mailbox_password_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    totp_secret_enc: Mapped[str | None] = mapped_column(Text)  # Fernet (APP_ENCRYPTION_KEY)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    totp_last_step: Mapped[int | None] = mapped_column(Integer)
    backup_code_hashes: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    require_2fa: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:  # never show secrets in tracebacks or logs
        return f"Account(id={self.id!s}, email={self.email!r}, kind={self.kind!s})"


class DevicePersonMemory(IdMixin, TimestampMixin, Base):
    """Last person picked in "Kto ste?" on one browser (the `sm_device` cookie) for one login (PRODUCT_SPEC §2.0)."""

    __tablename__ = "device_person_memory"
    __table_args__ = (UniqueConstraint("device_id", "account_id"),)

    device_id: Mapped[str] = mapped_column(String(64))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    last_person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"))


class Session(IdMixin, Base):
    """Server-side session. The cookie carries a random token; only its SHA-256 is stored."""

    __tablename__ = "sessions"

    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    active_person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id"))
    device_id: Mapped[str | None] = mapped_column(String(64))
    remember: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_pending: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_failures: Mapped[int] = mapped_column(Integer, default=0)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String(32))
