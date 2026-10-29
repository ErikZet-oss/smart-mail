"""Issue #41 (pilot eshop@, ~25,000 messages): first-sync failures left the mailbox at `new` with no error and 0
messages. Unexpected exceptions must become a visible error state, one bad message must not block the mailbox,
and a large first sync must stay within a time budget."""

from __future__ import annotations

import time
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.mail.sync as sync_mod
import app.mail.threads as threads_mod
from app.auth.security import encrypt
from app.core.config import Settings
from app.mail.models import Mailbox, Message
from app.mail.sync import apply_snapshot, sync_mailbox
from app.mail.threads import link_unthreaded
from tests.conftest import Client, FakeMailServer, make_personal
from tests.test_mail_messages_1d import _seed_inbox, _signed_in
from tests.test_mail_sync_1c import NOW, delta, env, make_mailbox, snapshot

PASSWORD = "Spravne-Heslo-1"


async def _mailbox_with_password(db: AsyncSession, settings: Settings) -> Mailbox:
    account = await make_personal(db, mailbox_password_enc=encrypt(settings, PASSWORD))
    return await make_mailbox(db, account)


def _fake_server(monkeypatch: pytest.MonkeyPatch, snap: sync_mod.MailboxSnapshot) -> None:
    monkeypatch.setattr(sync_mod, "connect", lambda *a, **k: object())
    monkeypatch.setattr(sync_mod, "collect", lambda *a, **k: snap)
    monkeypatch.setattr(sync_mod, "logout_quietly", lambda client: None)


async def _count(db: AsyncSession, mailbox: Mailbox) -> int:
    return int(await db.scalar(select(func.count()).select_from(Message).where(Message.mailbox_id == mailbox.id)) or 0)


async def test_41_sync_unexpected_error_sets_error_state(
    db: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    mailbox = await _mailbox_with_password(db, settings)
    snap = snapshot(delta("INBOX", 1, 3, 2, 2, new=[env(1), env(2)]))
    _fake_server(monkeypatch, snap)

    async def broken(*args: Any, **kwargs: Any) -> None:
        raise ValueError("server text with data@example.test must never be stored")

    monkeypatch.setattr(sync_mod, "apply_snapshot", broken)
    assert await sync_mailbox(db, mailbox, settings, now=NOW) == "error"
    await db.refresh(mailbox)
    assert mailbox.sync_state == "error"
    assert mailbox.sync_error == "unexpected:ValueError"

    # the next successful sync clears it
    monkeypatch.setattr(sync_mod, "apply_snapshot", apply_snapshot)
    assert await sync_mailbox(db, mailbox, settings, now=NOW) == "ok"
    await db.refresh(mailbox)
    assert (mailbox.sync_state, mailbox.sync_error) == ("ok", None)
    assert await _count(db, mailbox) == 2


async def test_41_sync_error_class_name_is_capped_at_64_chars(
    db: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    mailbox = await _mailbox_with_password(db, settings)
    _fake_server(monkeypatch, snapshot(delta("INBOX", 1, 1, 0, 0)))
    long_error = type("E" * 100, (Exception,), {})

    async def broken(*args: Any, **kwargs: Any) -> None:
        raise long_error()

    monkeypatch.setattr(sync_mod, "apply_snapshot", broken)
    assert await sync_mailbox(db, mailbox, settings, now=NOW) == "error"
    await db.refresh(mailbox)
    assert mailbox.sync_error == "unexpected:" + "E" * 53
    assert len(mailbox.sync_error) == 64


async def test_41_threading_failure_keeps_the_envelopes_of_the_sync(
    db: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Envelopes are committed before threading: a threading crash must not lose the folder."""
    mailbox = await _mailbox_with_password(db, settings)
    _fake_server(monkeypatch, snapshot(delta("INBOX", 1, 4, 3, 3, new=[env(1), env(2), env(3)])))

    async def broken(*args: Any, **kwargs: Any) -> int:
        raise RuntimeError("threading crashed")

    monkeypatch.setattr(threads_mod, "link_unthreaded", broken)
    assert await sync_mailbox(db, mailbox, settings, now=NOW) == "error"
    assert await _count(db, mailbox) == 3


async def test_41_threading_failure_of_one_message_does_not_roll_back_the_folder(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    mailbox = await make_mailbox(db, await make_personal(db))
    await apply_snapshot(db, mailbox, snapshot(delta("INBOX", 1, 4, 3, 3, new=[env(1), env(2), env(3)])), now=NOW)
    await db.commit()

    real = threads_mod.stored_key

    def flaky(message: Message) -> str:
        if message.uid == 2:
            raise RuntimeError("bad message")
        return real(message)

    monkeypatch.setattr(threads_mod, "stored_key", flaky)
    assert await link_unthreaded(db, mailbox.id) == 2
    await db.commit()

    rows = {
        m.uid: m.thread_id
        for m in (await db.execute(select(Message).where(Message.mailbox_id == mailbox.id))).scalars()
    }
    assert set(rows) == {1, 2, 3}
    assert rows[2] is None  # stays unthreaded, still listed in Zoznam mode
    assert rows[1] is not None and rows[3] is not None


async def test_41_load_first_sync_of_20000_envelopes_in_one_folder(db: AsyncSession) -> None:
    """CI-sized load test: ~20,000 envelopes through apply_snapshot + link_unthreaded within a time budget."""
    mailbox = await make_mailbox(db, await make_personal(db))
    count = 20_000
    new = [env(uid, subject=f"Objednávka {uid % 2000}") for uid in range(1, count + 1)]
    started = time.monotonic()
    await apply_snapshot(db, mailbox, snapshot(delta("INBOX", 7, count + 1, count, count, new=new)), now=NOW)
    await db.commit()
    applied = time.monotonic() - started
    linked = 0
    while True:
        batch = await link_unthreaded(db, mailbox.id)
        await db.commit()
        linked += batch
        if batch == 0:
            break
    total = time.monotonic() - started
    assert await _count(db, mailbox) == count
    assert linked == count
    assert applied < 30, f"apply_snapshot took {applied:.1f} s"
    assert total < 90, f"first sync took {total:.1f} s"


async def test_41_opening_a_message_survives_a_threading_failure(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #41 comment: a failure in threading must not fail the open — mark it read and return the message."""
    import app.api.messages as messages_api

    mailbox = await _signed_in(client, db, mail_server)
    folder = await _seed_inbox(db, mailbox, env(1, subject="Neprečítaná"))
    msg = await db.scalar(select(Message).where(Message.folder_id == folder.id))
    assert msg is not None
    msg.body_text = "Telo"
    msg.body_fetched_at = NOW
    msg.raw_storage_key = "mail/x/raw/ab/cd/fake"
    msg.thread_id = None
    await db.commit()

    async def fake_action(*args: object, **kwargs: object) -> None:
        return None

    async def fake_creds(*args: object, **kwargs: object) -> object:
        return object()

    async def broken(*args: object, **kwargs: object) -> int:
        raise RuntimeError("threading crashed")

    monkeypatch.setattr(messages_api, "run_msg_action_async", fake_action)
    monkeypatch.setattr(messages_api, "_creds", fake_creds)
    monkeypatch.setattr(threads_mod, "link_unthreaded", broken)

    r = await client.get(f"/api/mail/mailboxes/default/messages/{msg.id}")
    assert r.status_code == 200
    await db.refresh(msg)
    assert msg.seen


async def test_41_folders_report_first_sync_progress(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    """ "Načítava sa schránka… 12 400 / 25 000": envelopes stored locally vs. what the server reports."""
    mailbox = await _signed_in(client, db, mail_server)
    await apply_snapshot(
        db, mailbox, snapshot(delta("INBOX", 1, 3, 25_000, 0, new=[env(1), env(2)]), folders=("INBOX",)), now=NOW
    )
    await db.commit()
    r = await client.get(f"/api/mail/mailboxes/{mailbox.id}/folders")
    assert r.status_code == 200
    sync = r.json()["sync"]
    assert (sync["loaded"], sync["total"]) == (2, 25_000)
