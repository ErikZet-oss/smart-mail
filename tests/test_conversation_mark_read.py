"""Pilot (Nitra, Konverzácie): opening a conversation marked only its newest message read, so the thread was bold
again after a refresh. With `mark_thread=true` (sent by the web in conversations mode) every unread message of the
thread is marked read, like Roundcube; the list mode keeps marking only the opened message."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.messages as messages_api
from app.mail.models import FolderMeta, Message
from app.mail.sync import Envelope
from tests.conftest import Client, FakeMailServer
from tests.test_mail_messages_1d import _seed_inbox, _signed_in
from tests.test_mail_sync_1c import NOW, env


def _reply(uid: int, minutes: int) -> Envelope:
    return Envelope(
        uid=uid,
        message_id=f"<{uid}@example.test>",
        in_reply_to="<1@example.test>",
        references="<1@example.test>",
        subject="Re: Objednávka",
        from_name="Ján Novák",
        from_email="novak@abcstav.example",
        to=[{"name": None, "email": "pilot@smartmail.test"}],
        cc=[],
        sent_at=NOW + timedelta(minutes=minutes),
        received_at=NOW + timedelta(minutes=minutes),
        size=80,
        flags=[],
        modseq=1,
    )


async def _thread(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, monkeypatch: pytest.MonkeyPatch
) -> tuple[FolderMeta, list[Message], Message, list[tuple[object, ...]]]:
    mailbox = await _signed_in(client, db, mail_server)
    folder = await _seed_inbox(db, mailbox, env(1, subject="Objednávka"), _reply(2, 5), _reply(3, 10))
    rows = list((await db.execute(select(Message).where(Message.folder_id == folder.id))).scalars())
    for m in rows:
        m.body_text = "Telo"
        m.body_fetched_at = NOW
        m.raw_storage_key = "mail/x/raw/ab/cd/fake"
    await db.commit()
    assert len({m.thread_id for m in rows}) == 1 and not any(m.seen for m in rows)
    stored: list[tuple[object, ...]] = []

    async def fake_action(*args: object, **kwargs: object) -> None:
        stored.append(tuple(getattr(args[3], "uids", ())))

    async def fake_creds(*args: object, **kwargs: object) -> object:
        return object()

    async def no_schedule(*args: object, **kwargs: object) -> bool:
        return True

    monkeypatch.setattr(messages_api, "run_msg_action_async", fake_action)
    monkeypatch.setattr(messages_api, "_creds", fake_creds)
    monkeypatch.setattr(messages_api, "schedule_sync", no_schedule)
    newest = max(rows, key=lambda m: m.uid)
    return folder, rows, newest, stored


async def test_conversation_open_marks_the_whole_thread_read(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder, rows, newest, stored = await _thread(client, db, mail_server, monkeypatch)
    r = await client.get(f"/api/mail/mailboxes/default/messages/{newest.id}", params={"mark_thread": "true"})
    assert r.status_code == 200
    for m in rows:
        await db.refresh(m)
    assert all(m.seen for m in rows), "every message of the conversation must be read"
    assert sorted(u for call in stored for u in call) == [1, 2, 3]  # \\Seen stored on the IMAP server for all three
    await db.refresh(folder)
    assert folder.unread == 0


async def test_list_mode_open_marks_only_the_opened_message(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    _folder, rows, newest, _stored = await _thread(client, db, mail_server, monkeypatch)
    r = await client.get(f"/api/mail/mailboxes/default/messages/{newest.id}")
    assert r.status_code == 200
    for m in rows:
        await db.refresh(m)
    assert [m.seen for m in sorted(rows, key=lambda m: m.uid)] == [False, False, True]
