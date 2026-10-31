"""Pilot 2026-10-31: new mail has no body until someone opens it. The classifier therefore saw only the subject
(„Faktura“): heuristic → pl, LLM → pl, reply drafted in Polish; attachments and DMARC were unknown too.
The pipeline now fetches the body (BODY.PEEK) before classifying; a failed fetch falls back to the subject."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import Classification
from app.ai.service import process_mailbox_ai
from app.core.config import Settings
from app.mail.models import FolderMeta, Mailbox, Message
from tests.test_ai_classify_review_2b import ScriptedAnthropic, _ok_response

BODY = "Dobrý deň, potreboval by som poslať našu poslednú faktúru do mailu.\nĎakujem\nPROXTON Engineering s.r.o."


async def _seed(db: AsyncSession) -> tuple[Mailbox, Message]:
    enabled_at = datetime(2026, 10, 27, 10, 0, tzinfo=UTC)
    mailbox = Mailbox(
        email=f"ai-body-{uuid4().hex[:8]}@smartmail.test",
        imap_host="localhost",
        imap_port=1143,
        imap_security="none",
        ai_enabled=True,
        ai_enabled_at=enabled_at,
    )
    db.add(mailbox)
    await db.flush()
    folder = FolderMeta(mailbox_id=mailbox.id, name="INBOX", special_use="inbox", subscribed=True, selectable=True)
    db.add(folder)
    await db.flush()
    message = Message(
        mailbox_id=mailbox.id,
        folder_id=folder.id,
        uid=7,
        message_id=f"<body-{uuid4().hex}@customer.test>",
        subject="Faktura",
        from_email="erik@customer.test",
        body_text=None,
        received_at=enabled_at + timedelta(minutes=1),
        size=300,
    )
    db.add(message)
    await db.flush()
    return mailbox, message


def _live(settings: Settings) -> Settings:
    return settings.model_copy(
        update={"anthropic_api_key": SecretStr("sk-test"), "llm_model_classify": "claude-haiku-4-5-20251001"}
    )


@pytest.mark.asyncio
async def test_body_is_fetched_before_classify(
    db: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    mailbox, message = await _seed(db)
    fetched: list[Any] = []

    async def fake_creds(*_: Any) -> object:
        return object()

    async def fake_ensure(_db: Any, _s: Any, _mb: Any, msg: Message, _c: Any) -> Message:
        fetched.append(msg.id)
        msg.body_text = BODY
        msg.body_fetched_at = datetime.now(UTC)
        return msg

    monkeypatch.setattr("app.mail.sync.credentials_for", fake_creds)
    monkeypatch.setattr("app.mail.body.ensure_body", fake_ensure)
    llm = ScriptedAnthropic(
        [_ok_response(tool_input={**_ok_response().tool_input, "category": "invoice_request", "language": "pl"})]
    )  # type: ignore[dict-item]
    monkeypatch.setattr("app.ai.service.get_llm_provider", lambda _s: llm)

    await process_mailbox_ai(db, mailbox, _live(settings))

    assert fetched == [message.id]
    assert "potreboval by som" in llm.calls[0].user  # the classifier saw the body, not only the subject
    row = await db.scalar(select(Classification).where(Classification.message_id == message.id))
    assert row is not None and row.language == "sk"


@pytest.mark.asyncio
async def test_failed_body_fetch_falls_back_to_subject(
    db: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    mailbox, _ = await _seed(db)

    async def fake_creds(*_: Any) -> object:
        return object()

    async def broken(*_: Any) -> Message:
        raise RuntimeError("imap down")

    monkeypatch.setattr("app.mail.sync.credentials_for", fake_creds)
    monkeypatch.setattr("app.mail.body.ensure_body", broken)
    llm = ScriptedAnthropic([_ok_response()])
    monkeypatch.setattr("app.ai.service.get_llm_provider", lambda _s: llm)

    stats = await process_mailbox_ai(db, mailbox, _live(settings))
    assert stats["classified"] == 1  # mail processing never stops because of a body fetch
