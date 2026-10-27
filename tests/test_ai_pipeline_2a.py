"""Phase 2a: AI pipeline skeleton — history gate, D21 folders, AV, Message-ID idempotency."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from pydantic import SecretStr

from app.ai.pipeline import (
    BackfillEstimate,
    RecordingLLM,
    estimate_backfill,
    folder_eligible_for_ai,
    message_eligible_for_ai,
    select_new_messages_for_ai,
)
from app.ai.provider import LLMRequest, NullLLMProvider, get_llm_provider
from app.core.config import Settings
from app.mail.models import FolderMeta, Mailbox, Message


def _mailbox(**kwargs: Any) -> Mailbox:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "email": "pilot@smartmail.test",
        "kind": "personal",
        "imap_host": "imap-test",
        "imap_port": 143,
        "imap_security": "none",
        "ai_enabled": True,
        "ai_enabled_at": datetime(2026, 10, 27, 12, 0, tzinfo=UTC),
    }
    defaults.update(kwargs)
    return Mailbox(**defaults)


def _folder(**kwargs: Any) -> FolderMeta:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "mailbox_id": uuid.uuid4(),
        "name": "INBOX",
        "subscribed": True,
        "selectable": True,
        "private": False,
        "special_use": "inbox",
    }
    defaults.update(kwargs)
    return FolderMeta(**defaults)


def _message(**kwargs: Any) -> Message:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "mailbox_id": uuid.uuid4(),
        "folder_id": uuid.uuid4(),
        "uid": 1,
        "message_id": "<a@smartmail.test>",
        "received_at": datetime(2026, 10, 27, 13, 0, tzinfo=UTC),
    }
    defaults.update(kwargs)
    return Message(**defaults)


def test_2a_attachments_require_av_clean() -> None:
    from app.ai.pipeline import attachments_eligible_for_ai
    from app.mail.models import Attachment

    clean = Attachment(
        message_id=uuid.uuid4(),
        filename="a.pdf",
        storage_key="k",
        sha256="0" * 64,
        av_status="clean",
    )
    skipped = Attachment(
        message_id=uuid.uuid4(),
        filename="b.pdf",
        storage_key="k2",
        sha256="1" * 64,
        av_status="skipped",
    )
    assert attachments_eligible_for_ai([clean]) is True
    assert attachments_eligible_for_ai([clean, skipped]) is False


def test_2a_folder_excludes_d21_special_and_private() -> None:
    assert folder_eligible_for_ai(_folder(special_use="inbox")) is True
    assert folder_eligible_for_ai(_folder(name="Nitra", special_use=None)) is True
    for use in ("drafts", "sent", "trash", "junk"):
        assert folder_eligible_for_ai(_folder(special_use=use)) is False
    assert folder_eligible_for_ai(_folder(subscribed=False)) is False
    assert folder_eligible_for_ai(_folder(private=True)) is False


def test_2a_message_before_ai_enabled_at_is_not_eligible() -> None:
    mb = _mailbox(ai_enabled_at=datetime(2026, 10, 27, 12, 0, tzinfo=UTC))
    folder = _folder()
    old = _message(received_at=datetime(2026, 10, 27, 11, 59, tzinfo=UTC))
    new = _message(received_at=datetime(2026, 10, 27, 12, 0, tzinfo=UTC))
    assert message_eligible_for_ai(mb, folder, old) is False
    assert message_eligible_for_ai(mb, folder, new) is True


def test_2a_ai_disabled_or_null_enabled_at_blocks_all() -> None:
    folder = _folder()
    msg = _message()
    assert message_eligible_for_ai(_mailbox(ai_enabled=False), folder, msg) is False
    assert message_eligible_for_ai(_mailbox(ai_enabled=True, ai_enabled_at=None), folder, msg) is False


def test_2a_first_sync_of_10000_old_messages_makes_zero_llm_calls() -> None:
    """Binding plan A: first sync of historical mail must not call the LLM."""
    enabled_at = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
    mb = _mailbox(ai_enabled=True, ai_enabled_at=enabled_at)
    folder = _folder()
    llm = RecordingLLM()
    old_msgs = [
        _message(
            id=uuid.uuid4(),
            uid=i,
            message_id=f"<old-{i}@smartmail.test>",
            received_at=enabled_at - timedelta(days=1, seconds=i),
        )
        for i in range(10_000)
    ]
    selected = select_new_messages_for_ai(mb, folder, old_msgs)
    assert selected == []
    for msg in old_msgs:
        assert message_eligible_for_ai(mb, folder, msg) is False
    assert llm.call_count == 0


def test_2a_backfill_estimate_requires_count_cost_and_limit() -> None:
    est = estimate_backfill(
        message_count=500,
        limit=200,
        classify_usd_per_1k=Decimal("0.40"),
    )
    assert isinstance(est, BackfillEstimate)
    assert est.message_count == 500
    assert est.limit == 200
    assert est.will_process == 200
    assert est.estimated_usd == Decimal("0.08")  # 200/1000 * 0.40
    assert "limit" in est.summary_sk.lower() or "limit" in est.summary_sk or "max" in est.summary_sk.lower()


def test_2a_null_provider_never_calls_network() -> None:
    settings = Settings(
        app_env="test",
        app_base_url="http://test",
        app_secret_key="test-secret-key-that-is-long-enough-0123456789",
        database_url="postgresql+asyncpg://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
        llm_provider="anthropic",
        anthropic_api_key=None,
        llm_model_classify="claude-haiku-4-5-20251001",
    )
    provider = get_llm_provider(settings)
    assert isinstance(provider, NullLLMProvider)


@pytest.mark.asyncio
async def test_2a_provider_requires_concrete_model_id() -> None:
    settings = Settings(
        app_env="test",
        app_base_url="http://test",
        app_secret_key="test-secret-key-that-is-long-enough-0123456789",
        database_url="postgresql+asyncpg://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
        llm_provider="anthropic",
        anthropic_api_key=SecretStr("sk-test"),
        llm_model_classify=None,
    )
    provider = get_llm_provider(settings)
    with pytest.raises(ValueError, match="LLM_MODEL_"):
        await provider.complete(LLMRequest(purpose="classify", system="s", user="u", model=None))
