"""AI tables: runs, classifications, suggestions, feature flags (CLAUDE.md §4; Phase 2a)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin


class AiRun(IdMixin, TimestampMixin, Base):
    """One LLM call — tokens and cost only; never mail bodies or prompts."""

    __tablename__ = "ai_runs"

    purpose: Mapped[str] = mapped_column(String(32))  # classify|draft|extract|assistant|embed
    provider: Mapped[str] = mapped_column(String(32))  # anthropic|bedrock|null
    model: Mapped[str] = mapped_column(String(128))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"), server_default="0")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    mailbox_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("mailboxes.id", ondelete="SET NULL"), index=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(
        String(16), default="ok", server_default="ok"
    )  # ok|invalid_output|error|skipped
    error_class: Mapped[str | None] = mapped_column(String(64))  # type name only, never payload


class Classification(IdMixin, TimestampMixin, Base):
    """Idempotency key = Message-ID header across mailboxes (AI_ASSISTANT §2)."""

    __tablename__ = "classifications"
    __table_args__ = (UniqueConstraint("message_id_header", name="uq_classifications_message_id_header"),)

    mailbox_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mailboxes.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    # RFC Message-ID without angle brackets when present; null when the message has none
    message_id_header: Mapped[str | None] = mapped_column(String(998), index=True)
    category: Mapped[str | None] = mapped_column(String(64))
    language: Mapped[str | None] = mapped_column(String(16))
    priority: Mapped[str | None] = mapped_column(String(16))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")  # pending|done|skipped
    ai_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ai_runs.id", ondelete="SET NULL"))
    shadow: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class AiSuggestion(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_suggestions"

    mailbox_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mailboxes.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    thread_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("threads.id", ondelete="CASCADE"), index=True)
    suggestion_type: Mapped[str] = mapped_column(String(64))  # reply|… (Phase 2c+)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    rationale: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    checks: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")
    status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending"
    )  # pending|approved|rejected|superseded
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    final_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    diff: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    batch_safe: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # ai_shadow_mode: create rows but UI hides them (Phase 2c+)
    shadow: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    classification_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("classifications.id", ondelete="SET NULL"), index=True
    )


class FeatureFlag(IdMixin, TimestampMixin, Base):
    """Per-person or global flags (e.g. ai_shadow_mode). person_id null = global default."""

    __tablename__ = "feature_flags"
    __table_args__ = (UniqueConstraint("key", "person_id", name="uq_feature_flags_key_person"),)

    key: Mapped[str] = mapped_column(String(64), index=True)
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")


class KnowledgeCard(IdMixin, TimestampMixin, Base):
    """17d Znalosti (company data for drafts) and the single company style guide (kind ``style_guide``) — #110."""

    __tablename__ = "knowledge_cards"

    kind: Mapped[str] = mapped_column(String(16), default="knowledge", server_default="knowledge")
    title: Mapped[str] = mapped_column(String(200), default="", server_default="")
    body: Mapped[str] = mapped_column(Text, default="", server_default="")
    valid_until: Mapped[date | None] = mapped_column(Date)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list, server_default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_by_person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"))
    # filled by a trigger (title, tags weight A; body B) — read-only here
    search_vector: Mapped[Any] = mapped_column(TSVECTOR, nullable=True, deferred=True)


class AiRule(IdMixin, TimestampMixin, Base):
    """17e Pravidlá: the rule in Slovak and its confirmed structured form (executed deterministically) — #110."""

    __tablename__ = "ai_rules"

    nl_text: Mapped[str] = mapped_column(Text)
    structured: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_by_person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AccountSettings(IdMixin, TimestampMixin, Base):
    """JSON settings per login (scope A) — 07 autonomy (DECISIONS D8, #116)."""

    __tablename__ = "account_settings"
    __table_args__ = (UniqueConstraint("account_id", "section", name="uq_account_settings_account_section"),)

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    section: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")


class OrgSettings(IdMixin, TimestampMixin, Base):
    """Company-wide JSON settings (scope G) — 17a provider/budget, 17c categories (#116)."""

    __tablename__ = "org_settings"

    section: Mapped[str] = mapped_column(String(64), unique=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
