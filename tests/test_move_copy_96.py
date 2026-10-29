"""#96: Kopírovať do… (bulk `copy`) and Presunúť do… into the same folder."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditLog
from app.mail.actions import MsgAction
from app.mail.models import Message
from tests.conftest import Client, FakeMailServer
from tests.test_fast_actions_89 import _folder
from tests.test_mail_messages_1d import _seed_inbox, _signed_in
from tests.test_mail_sync_1c import env


def _patch(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[tuple[object, str, tuple[int, ...], object]], list[uuid.UUID]]:
    import app.api.messages as messages_api

    calls: list[tuple[object, str, tuple[int, ...], object]] = []
    scheduled: list[uuid.UUID] = []

    async def action(server: object, creds: object, act: object, target: object, **kw: object) -> None:
        calls.append((act, target.folder, target.uids, kw.get("dest_folder")))  # type: ignore[attr-defined]

    async def creds(*args: object, **kwargs: object) -> object:
        return object()

    async def schedule(redis: object, mailbox_id: uuid.UUID) -> bool:
        scheduled.append(mailbox_id)
        return True

    monkeypatch.setattr(messages_api, "run_msg_action_async", action)
    monkeypatch.setattr(messages_api, "_creds", creds)
    monkeypatch.setattr(messages_api, "schedule_sync", schedule)
    return calls, scheduled


async def test_96_copy_keeps_the_source_and_schedules_sync(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    inbox = await _seed_inbox(db, mailbox, env(1, subject="A"))
    msg = await db.scalar(select(Message).where(Message.folder_id == inbox.id))
    assert msg is not None
    trash = await _folder(db, mailbox.id, "Trash")
    total = trash.total or 0
    calls, scheduled = _patch(monkeypatch)

    r = await client.send_json(
        "POST",
        "/api/mail/mailboxes/default/messages/bulk",
        {"message_ids": [str(msg.id)], "action": "copy", "dest_folder_id": str(trash.id)},
    )
    assert r.status_code == 200, r.text
    assert calls == [(MsgAction.copy, "INBOX", (1,), "Trash")]
    assert scheduled == [mailbox.id]
    await db.close()
    assert await db.get(Message, msg.id) is not None  # source untouched
    assert (await _folder(db, mailbox.id, "Trash")).total == total + 1
    assert await db.scalar(select(AuditLog).where(AuditLog.action == "mail.bulk_copy")) is not None


async def test_96_copy_and_move_need_a_destination_and_skip_the_same_folder(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    inbox = await _seed_inbox(db, mailbox, env(1, subject="A"))
    msg = await db.scalar(select(Message).where(Message.folder_id == inbox.id))
    assert msg is not None
    calls, scheduled = _patch(monkeypatch)
    url = "/api/mail/mailboxes/default/messages/bulk"

    r = await client.send_json("POST", url, {"message_ids": [str(msg.id)], "action": "copy"})
    assert r.status_code == 422
    for action in ("move", "copy"):
        r = await client.send_json(
            "POST", url, {"message_ids": [str(msg.id)], "action": action, "dest_folder_id": str(inbox.id)}
        )
        assert r.status_code == 200, r.text
    assert calls == [] and scheduled == []
    await db.close()
    assert await db.get(Message, msg.id) is not None
