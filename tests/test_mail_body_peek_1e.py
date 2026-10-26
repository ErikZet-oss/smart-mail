"""Phase 1e: message bodies are fetched with BODY.PEEK[] only — never RFC822 (marks \\Seen)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.mail.body import ensure_body
from app.mail.models import FolderMeta, Mailbox, Message
from app.mail.sync import Credentials


class _FakeClient:
    def __init__(self) -> None:
        self.fetch_items: list[str] | None = None

    def select_folder(self, name: str, readonly: bool = False) -> None:
        assert readonly is True

    def fetch(self, uids: list[int], items: list[str]) -> dict[int, dict[bytes, bytes]]:
        self.fetch_items = list(items)
        assert "RFC822" not in items
        assert items == ["BODY.PEEK[]"]
        return {uids[0]: {b"BODY[]": b"From: a@example.test\r\nSubject: Peek\r\n\r\nTelo\r\n"}}

    def logout(self) -> None:
        return None


@pytest.mark.asyncio
async def test_1e_ensure_body_uses_body_peek_only(
    db: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeClient()
    monkeypatch.setattr("app.mail.body.connect", lambda *_a, **_k: fake)
    monkeypatch.setattr("app.mail.body.logout_quietly", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "app.mail.body.server_of",
        lambda *_a, **_k: SimpleNamespace(host="localhost", port=1143, security="none"),
    )

    mailbox = Mailbox(
        email="peek@smartmail.test",
        imap_host="localhost",
        imap_port=1143,
        imap_security="none",
    )
    db.add(mailbox)
    await db.flush()
    folder = FolderMeta(mailbox_id=mailbox.id, name="INBOX", special_use="inbox")
    db.add(folder)
    await db.flush()
    message = Message(mailbox_id=mailbox.id, folder_id=folder.id, uid=7, subject="Peek", size=10)
    db.add(message)
    await db.flush()

    out = await ensure_body(db, settings, mailbox, message, Credentials("peek@smartmail.test", "x"))
    assert fake.fetch_items == ["BODY.PEEK[]"]
    assert out.body_text and "Telo" in (out.body_text or "")
    assert out.raw_storage_key
