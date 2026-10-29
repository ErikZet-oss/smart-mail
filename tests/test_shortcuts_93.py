"""#93: Shift+Delete = permanent delete (bulk `purge`), Settings 01e on/off reaches the mail prefs."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mail.actions import MsgAction
from app.mail.models import Message
from tests.conftest import Client, FakeMailServer
from tests.test_fast_actions_89 import _folder
from tests.test_mail_messages_1d import _seed_inbox, _signed_in
from tests.test_mail_sync_1c import env


async def test_93_purge_expunges_in_place_without_a_trash_copy(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.messages as messages_api

    mailbox = await _signed_in(client, db, mail_server)
    inbox = await _seed_inbox(db, mailbox, env(1, subject="A"))
    msg = await db.scalar(select(Message).where(Message.folder_id == inbox.id))
    assert msg is not None
    trash_total = (await _folder(db, mailbox.id, "Trash")).total or 0
    calls: list[tuple[object, str, tuple[int, ...], object]] = []

    async def action(server: object, creds: object, act: object, target: object, **kw: object) -> None:
        calls.append((act, target.folder, target.uids, kw.get("dest_folder")))  # type: ignore[attr-defined]

    async def creds(*args: object, **kwargs: object) -> object:
        return object()

    async def schedule(*args: object, **kwargs: object) -> bool:
        return True

    monkeypatch.setattr(messages_api, "run_msg_action_async", action)
    monkeypatch.setattr(messages_api, "_creds", creds)
    monkeypatch.setattr(messages_api, "schedule_sync", schedule)

    r = await client.send_json(
        "POST", "/api/mail/mailboxes/default/messages/bulk", {"message_ids": [str(msg.id)], "action": "purge"}
    )
    assert r.status_code == 200, r.text
    assert calls == [(MsgAction.expunge, "INBOX", (1,), None)]
    await db.close()
    assert await db.get(Message, msg.id) is None
    assert (await _folder(db, mailbox.id, "Trash")).total == trash_total


async def test_93_settings_01e_switch_reaches_mail_prefs(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _signed_in(client, db, mail_server)
    r = await client.get("/api/mail/prefs")
    assert r.status_code == 200
    assert r.json()["shortcuts"] == {"enabled": True}

    prefs = (await client.get("/api/settings/preferences")).json()
    r = await client.send_json("PUT", "/api/settings/preferences", {**prefs, "shortcuts": {"shortcuts_enabled": False}})
    assert r.status_code == 200, r.text
    assert (await client.get("/api/mail/prefs")).json()["shortcuts"] == {"enabled": False}
