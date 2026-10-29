"""#89: toolbar actions return without a full mailbox sync; the local copy changes in the same request."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mail.models import FolderMeta, Message
from app.mail.sync import SyncUnavailable
from app.mail.sync_schedule import schedule_sync
from tests.conftest import Client, FakeMailServer
from tests.test_mail_messages_1d import _seed_inbox, _signed_in
from tests.test_mail_sync_1c import env


def _patch(monkeypatch: pytest.MonkeyPatch, *, fail: bool = False) -> list[uuid.UUID]:
    import app.api.mail as mail_api
    import app.api.messages as messages_api

    scheduled: list[uuid.UUID] = []

    async def action(*args: object, **kwargs: object) -> None:
        if fail:
            raise SyncUnavailable("OSError")

    async def creds(*args: object, **kwargs: object) -> object:
        return object()

    async def no_full_sync(*args: object, **kwargs: object) -> str:
        raise AssertionError("#89: an action must not run a mailbox sync inside the request")

    async def schedule(redis: object, mailbox_id: uuid.UUID) -> bool:
        scheduled.append(mailbox_id)
        return True

    monkeypatch.setattr(messages_api, "run_msg_action_async", action)
    monkeypatch.setattr(messages_api, "_creds", creds)
    monkeypatch.setattr(mail_api, "sync_mailbox", no_full_sync)
    monkeypatch.setattr(messages_api, "schedule_sync", schedule)
    return scheduled


async def _folder(db: AsyncSession, mailbox_id: uuid.UUID, name: str) -> FolderMeta:
    folder = await db.scalar(select(FolderMeta).where(FolderMeta.mailbox_id == mailbox_id, FolderMeta.name == name))
    assert folder is not None
    await db.refresh(folder)
    return folder


async def test_89_delete_removes_locally_and_schedules_sync(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    inbox = await _seed_inbox(db, mailbox, env(1, subject="A"), env(2, "\\Seen", subject="B"))
    trash_before = await _folder(db, mailbox.id, "Trash")
    trash_total = trash_before.total or 0
    total, unread = inbox.total or 0, inbox.unread or 0
    msgs = list((await db.execute(select(Message).where(Message.folder_id == inbox.id))).scalars())
    scheduled = _patch(monkeypatch)

    r = await client.send_json(
        "POST",
        "/api/mail/mailboxes/default/messages/bulk",
        {"message_ids": [str(m.id) for m in msgs], "action": "delete"},
    )
    assert r.status_code == 200, r.text
    assert scheduled == [mailbox.id]
    await db.close()  # drop the identity map; read what the request committed
    left = (await db.execute(select(Message).where(Message.folder_id == inbox.id))).scalars().all()
    assert left == []
    inbox = await _folder(db, mailbox.id, "INBOX")
    assert inbox.total == max(0, total - 2)
    assert inbox.unread == max(0, unread - 1)
    assert (await _folder(db, mailbox.id, "Trash")).total == trash_total + 2


async def test_89_flag_updates_locally_without_any_sync(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    inbox = await _seed_inbox(db, mailbox, env(1, subject="A"))
    msg = await db.scalar(select(Message).where(Message.folder_id == inbox.id))
    assert msg is not None and not msg.seen
    unread = inbox.unread or 0
    scheduled = _patch(monkeypatch)

    for action in ("mark_seen", "flag"):
        r = await client.send_json(
            "POST", "/api/mail/mailboxes/default/messages/bulk", {"message_ids": [str(msg.id)], "action": action}
        )
        assert r.status_code == 200, r.text
    assert scheduled == []  # flags are exact locally; nothing to fetch
    await db.close()  # drop the identity map; read what the request committed
    msg = await db.get(Message, msg.id)
    assert msg is not None and msg.seen and msg.flagged
    assert {"\\Seen", "\\Flagged"} <= set(msg.flags or [])
    assert (await _folder(db, mailbox.id, "INBOX")).unread == max(0, unread - 1)


async def test_89_imap_error_changes_nothing_locally(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    inbox = await _seed_inbox(db, mailbox, env(1, subject="A"))
    msg = await db.scalar(select(Message).where(Message.folder_id == inbox.id))
    assert msg is not None
    scheduled = _patch(monkeypatch, fail=True)

    r = await client.send_json(
        "POST", "/api/mail/mailboxes/default/messages/bulk", {"message_ids": [str(msg.id)], "action": "delete"}
    )
    assert r.status_code == 503
    assert scheduled == []
    await db.close()  # drop the identity map; read what the request committed
    assert await db.get(Message, msg.id) is not None


async def test_89_quick_actions_in_a_row_queue_one_sync(app: FastAPI) -> None:
    redis = app.state.redis
    mailbox_id = uuid.uuid4()
    assert await schedule_sync(redis, mailbox_id) is True
    assert await schedule_sync(redis, mailbox_id) is False  # same job id while queued → one sync
    assert await redis.zcard("arq:queue") == 1
