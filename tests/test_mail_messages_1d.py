"""Phase 1d message list, reading, prefs, flags, bulk, snooze/assign (SCREENS_SPEC W2 / W2c / W2e / W2o / W2i / W2j).

Uses the local DB + apply_snapshot (no live IMAP) unless a test opts into body fetch.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mail.models import FolderMeta, Mailbox, Message, Thread
from app.mail.prefs import ListPrefs, UiPrefs
from app.mail.sync import Envelope, apply_snapshot
from app.mail.threads import link_unthreaded
from tests.conftest import Client, FakeMailServer, make_personal
from tests.test_mail_sync_1c import NOW, PASSWORD, delta, env, snapshot


async def _signed_in(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> Mailbox:
    acc = await make_personal(db)
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200
    return (await db.execute(select(Mailbox).where(Mailbox.email == acc.email))).scalar_one()


async def _seed_inbox(db: AsyncSession, mailbox: Mailbox, *envelopes: Envelope) -> FolderMeta:
    snap = snapshot(
        delta(
            "INBOX",
            1,
            max(e.uid for e in envelopes) + 1,
            len(envelopes),
            1,
            new=list(envelopes),
            present_uids={e.uid for e in envelopes},
        ),
        delta("Trash", 1, 1, 0, 0, present_uids=set()),
        folders=("INBOX", "Trash"),
    )
    await apply_snapshot(db, mailbox, snap, now=NOW)
    await link_unthreaded(db, mailbox.id)
    await db.commit()
    folder = await db.scalar(select(FolderMeta).where(FolderMeta.mailbox_id == mailbox.id, FolderMeta.name == "INBOX"))
    assert folder is not None
    return folder


async def test_1d_list_messages_list_mode(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    folder = await _seed_inbox(db, mailbox, env(1, subject="Prvá"), env(2, "\\Seen", subject="Druhá"))

    r = await client.get(f"/api/mail/mailboxes/default/folders/{folder.id}/messages")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "list"
    assert body["total"] == 2
    assert [m["subject"] for m in body["messages"]] == ["Druhá", "Prvá"]
    assert body["prefs"]["sort"] == "date_received"
    assert body["messages"][1]["seen"] is False


async def test_1d_list_filter_unread_and_conversations(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    e1 = env(1, subject="Objednávka")
    e2 = Envelope(
        uid=2,
        message_id="<2@example.test>",
        in_reply_to="<1@example.test>",
        references="<1@example.test>",
        subject="Re: Objednávka",
        from_name="Pilot",
        from_email="pilot@smartmail.test",
        to=[{"name": None, "email": "hudec@kovotrnava.example"}],
        cc=[],
        sent_at=NOW + timedelta(minutes=5),
        received_at=NOW + timedelta(minutes=5),
        size=80,
        flags=["\\Seen"],
        modseq=1,
    )
    folder = await _seed_inbox(db, mailbox, e1, e2)

    unread = await client.get(f"/api/mail/mailboxes/default/folders/{folder.id}/messages", params={"filter": "unread"})
    assert unread.status_code == 200
    assert unread.json()["total"] == 1
    assert unread.json()["messages"][0]["subject"] == "Objednávka"

    prefs = await client.send_json("PUT", "/api/mail/prefs", {"list": {"mode": "conversations"}})
    assert prefs.status_code == 200
    assert prefs.json()["list"]["mode"] == "conversations"

    conv = await client.get(f"/api/mail/mailboxes/default/folders/{folder.id}/messages")
    assert conv.status_code == 200
    data = conv.json()
    assert data["mode"] == "conversations"
    assert data["total"] == 1
    assert data["threads"][0]["message_count"] == 2
    assert data["threads"][0]["subject"] in ("Objednávka", "Re: Objednávka")


async def test_1d_get_message_detail_without_imap_body(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    folder = await _seed_inbox(db, mailbox, env(1, subject="Detail"))
    msg = await db.scalar(select(Message).where(Message.folder_id == folder.id))
    assert msg is not None
    msg.body_text = "Telo správy"
    msg.body_html_sanitized = "<p>Telo správy</p>"
    msg.body_fetched_at = NOW
    msg.raw_storage_key = "mail/x/raw/ab/cd/fake"
    await db.commit()

    r = await client.get(f"/api/mail/mailboxes/default/messages/{msg.id}", params={"mark_read": "false"})
    assert r.status_code == 200
    detail = r.json()
    assert detail["subject"] == "Detail"
    assert detail["body_text"] == "Telo správy"
    assert detail["body_html_sanitized"] == "<p>Telo správy</p>"


async def test_1d_prefs_ui_classic_and_theme(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await _signed_in(client, db, mail_server)

    r = await client.get("/api/mail/prefs")
    assert r.status_code == 200
    assert r.json()["list"] == ListPrefs().model_dump()
    assert r.json()["ui"] == UiPrefs().model_dump()

    saved = await client.send_json(
        "PUT",
        "/api/mail/prefs",
        {"list": {"density": "comfortable", "mode": "list"}, "ui": {"theme": "dark", "classic": True}},
    )
    assert saved.status_code == 200
    assert saved.json()["list"]["density"] == "comfortable"
    assert saved.json()["ui"] == {"theme": "dark", "classic": True, "remote_images": "known", "prefer_html": True}

    again = await client.get("/api/mail/prefs")
    assert again.json()["ui"]["classic"] is True
    assert again.json()["ui"]["theme"] == "dark"


async def test_1d_snooze_and_assign_thread(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    await _seed_inbox(db, mailbox, env(1, subject="Odlož"))
    thread = await db.scalar(select(Thread).where(Thread.mailbox_id == mailbox.id))
    assert thread is not None
    me = (await client.get("/api/auth/me")).json()
    person_id = me["person"]["id"]

    until = (NOW + timedelta(days=1)).isoformat()
    snooze = await client.send_json("POST", f"/api/mail/mailboxes/default/threads/{thread.id}/snooze", {"until": until})
    assert snooze.status_code == 200
    assert snooze.json()["status"] == "snoozed"

    assign = await client.send_json(
        "POST", f"/api/mail/mailboxes/default/threads/{thread.id}/assign", {"person_id": person_id}
    )
    assert assign.status_code == 200
    assert assign.json()["assignee_id"] == person_id

    await db.refresh(thread)
    assert thread.status == "snoozed"
    assert str(thread.assignee_id) == person_id

    clear = await client.send_json("POST", f"/api/mail/mailboxes/default/threads/{thread.id}/snooze", {"until": None})
    assert clear.json()["status"] == "open"


async def test_1d_bulk_done_marks_threads(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    await _seed_inbox(db, mailbox, env(1), env(2, "\\Seen", subject="Iná"))
    messages = list((await db.execute(select(Message).where(Message.mailbox_id == mailbox.id))).scalars())
    assert len(messages) >= 1

    r = await client.send_json(
        "POST",
        "/api/mail/mailboxes/default/messages/bulk",
        {"message_ids": [str(m.id) for m in messages], "action": "done"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] >= 1
    threads = list((await db.execute(select(Thread).where(Thread.mailbox_id == mailbox.id))).scalars())
    assert all(t.status == "done" for t in threads)


async def test_1d_message_not_found(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await _signed_in(client, db, mail_server)
    r = await client.get(f"/api/mail/mailboxes/default/messages/{uuid.uuid4()}")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "message_not_found"


async def test_1d_long_message_ids_fit_the_thread_key_and_replies_still_join(db: AsyncSession) -> None:
    """Pilot (eshop@): a Message-ID longer than the varchar(80) thread key aborted the whole first sync."""
    from dataclasses import replace

    from tests.test_mail_sync_1c import make_mailbox

    mailbox = await make_mailbox(db, await make_personal(db))
    long_id = "<" + "newsletter-" + "x" * 300 + "@bulk.example>"
    root = replace(env(1, "\\Seen", subject="Akcia"), message_id=long_id)
    reply = replace(
        env(2, subject="Re: Akcia"),
        message_id="<reply-1@example.test>",
        in_reply_to=long_id,
        received_at=NOW + timedelta(hours=1),
    )
    old_reply = replace(
        env(3, subject="Re: Akcia"),
        message_id="<reply-2@example.test>",
        in_reply_to=long_id,
        received_at=NOW + timedelta(days=60),  # outside the 30-day window: new thread with a date suffix
    )
    await _seed_inbox(db, mailbox, root, reply, old_reply)
    threads = list((await db.execute(select(Thread).where(Thread.mailbox_id == mailbox.id))).scalars())
    assert all(len(t.thread_key) <= 80 for t in threads)
    by_uid = {m.uid: m.thread_id for m in (await db.execute(select(Message))).scalars()}
    assert by_uid[1] == by_uid[2]
    assert by_uid[3] != by_uid[1]
    assert len(threads) == 2


async def test_1d_old_fallback_threads_of_the_same_day_share_one_thread(db: AsyncSession) -> None:
    """Pilot (eshop@): two carrier notifications on one day, >30 days after the first, tried to insert the same
    suffixed thread key twice -> UniqueViolation -> opening an unread message returned 500."""
    from dataclasses import replace

    from tests.test_mail_sync_1c import make_mailbox

    mailbox = await make_mailbox(db, await make_personal(db))

    def note(uid: int, offset: timedelta) -> Envelope:
        base = env(uid, subject="Automatische generierte Sendungsinformation")
        return replace(base, message_id=None, in_reply_to=None, references=None, received_at=NOW + offset)

    first = note(1, timedelta(0))
    soon = note(2, timedelta(days=5))  # within the window: same thread as 1
    later_a = note(3, timedelta(days=60))  # window expired: new thread
    later_b = note(4, timedelta(days=60, hours=2))  # same day as 3: must join it, not collide
    much_later = note(5, timedelta(days=200))  # yet another window
    await _seed_inbox(db, mailbox, first, soon, later_a, later_b, much_later)

    by_uid = {m.uid: m.thread_id for m in (await db.execute(select(Message))).scalars()}
    assert None not in by_uid.values()
    assert by_uid[1] == by_uid[2]
    assert by_uid[3] == by_uid[4] != by_uid[1]
    assert by_uid[5] not in {by_uid[1], by_uid[3]}
    threads = list((await db.execute(select(Thread).where(Thread.mailbox_id == mailbox.id))).scalars())
    assert len(threads) == 3
    assert all(len(t.thread_key) <= 80 for t in threads)


async def test_1d_opening_an_unread_message_marks_it_read_without_a_full_sync(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pilot (eshop@, ~30,000 messages): every open of an unread message ran a sync of all folders (5-10 s)."""
    import app.api.messages as messages_api

    mailbox = await _signed_in(client, db, mail_server)
    folder = await _seed_inbox(db, mailbox, env(1, subject="Neprečítaná"))
    msg = await db.scalar(select(Message).where(Message.folder_id == folder.id))
    assert msg is not None and not msg.seen
    msg.body_text = "Telo"
    msg.body_fetched_at = NOW
    msg.raw_storage_key = "mail/x/raw/ab/cd/fake"
    await db.commit()
    unread_before = folder.unread

    stored: list[object] = []

    async def fake_action(*args: object, **kwargs: object) -> None:
        stored.append(args[2])

    async def fake_creds(*args: object, **kwargs: object) -> object:
        return object()

    async def no_full_sync(*args: object, **kwargs: object) -> None:
        raise AssertionError("opening a message must not run a full mailbox sync")

    monkeypatch.setattr(messages_api, "run_msg_action_async", fake_action)
    monkeypatch.setattr(messages_api, "_creds", fake_creds)
    monkeypatch.setattr(messages_api, "_sync", no_full_sync)

    r = await client.get(f"/api/mail/mailboxes/default/messages/{msg.id}")
    assert r.status_code == 200
    assert stored, "\\Seen must still be stored on the IMAP server"
    await db.refresh(msg)
    await db.refresh(folder)
    assert msg.seen
    assert "\\Seen" in (msg.flags or [])
    assert folder.unread == max(0, unread_before - 1)


async def test_1d_remote_images_bar_is_offered_for_unknown_senders(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    """Pilot (eshop@): with the default "Od známych odosielateľov" an unknown sender got no bar at all, so remote
    images could never be shown. Like Roundcube, the bar is always offered; the setting only decides auto-loading."""
    mailbox = await _signed_in(client, db, mail_server)
    folder = await _seed_inbox(db, mailbox, env(1, "\\Seen", subject="Newsletter"))
    msg = await db.scalar(select(Message).where(Message.folder_id == folder.id))
    assert msg is not None
    msg.body_text = "Akcia"
    msg.body_html_sanitized = (
        '<p>Akcia</p><img src="about:blank#smartmail-remote" data-remote-src="https://cdn.example/akcia.png" alt="">'
    )
    msg.body_fetched_at = NOW
    msg.raw_storage_key = "mail/x/raw/ab/cd/fake"
    await db.commit()

    r = await client.get(f"/api/mail/mailboxes/default/messages/{msg.id}", params={"mark_read": "false"})
    assert r.status_code == 200
    body = r.json()
    assert body["remote_images_mode"] == "known"
    assert body["remote_images_offered"] is True
    assert body["remote_images_auto"] is False
    assert "/api/mail/image-proxy" in body["body_html_sanitized"]
    assert "cdn.example" not in body["body_html_sanitized"].split("data-remote-src")[0]


async def test_1d_delete_inside_trash_is_permanent_not_a_move_to_trash(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pilot (eshop@): Vymazať in Kôš tried MOVE Kôš -> Kôš, which the server refuses. Roundcube deletes for good."""
    import app.api.messages as messages_api
    from app.mail.actions import MsgAction

    mailbox = await _signed_in(client, db, mail_server)
    await _seed_inbox(db, mailbox, env(1, subject="V doručenej"))
    trash = await db.scalar(select(FolderMeta).where(FolderMeta.mailbox_id == mailbox.id, FolderMeta.name == "Trash"))
    assert trash is not None and trash.special_use == "trash"
    inbox_msg = await db.scalar(select(Message).where(Message.mailbox_id == mailbox.id, Message.uid == 1))
    assert inbox_msg is not None
    trashed = Message(mailbox_id=mailbox.id, folder_id=trash.id, uid=7, subject="V koši", flags=[])
    db.add(trashed)
    await db.commit()

    calls: list[tuple[object, str, tuple[int, ...], object]] = []

    async def fake_action(server: object, creds: object, action: object, target: object, **kw: object) -> None:
        calls.append((action, target.folder, target.uids, kw.get("dest_folder")))  # type: ignore[attr-defined]

    async def fake_creds(*args: object, **kwargs: object) -> object:
        return object()

    async def no_sync(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(messages_api, "run_msg_action_async", fake_action)
    monkeypatch.setattr(messages_api, "_creds", fake_creds)
    monkeypatch.setattr(messages_api, "_sync", no_sync)

    r = await client.send_json(
        "POST",
        "/api/mail/mailboxes/default/messages/bulk",
        {"message_ids": [str(trashed.id), str(inbox_msg.id)], "action": "delete"},
    )
    assert r.status_code == 200, r.text
    by_folder = {folder: (action, uids, dest) for action, folder, uids, dest in calls}
    assert by_folder["Trash"] == (MsgAction.expunge, (7,), None)
    assert by_folder["INBOX"] == (MsgAction.delete, (1,), "Trash")


def test_1d_expunge_action_deletes_only_the_given_uids() -> None:
    from app.mail.actions import MsgAction, MsgTarget, _act

    class FakeClient:
        def __init__(self, caps: tuple[bytes, ...]) -> None:
            self.caps = caps
            self.log: list[tuple[str, object]] = []

        def select_folder(self, name: str) -> None:
            self.log.append(("select", name))

        def add_flags(self, uids: list[int], flags: list[bytes], silent: bool = False) -> None:
            self.log.append(("flags", (tuple(uids), tuple(flags))))

        def capabilities(self) -> tuple[bytes, ...]:
            return self.caps

        def expunge(self, messages: list[int] | None = None) -> None:
            self.log.append(("expunge", tuple(messages) if messages else None))

    uidplus = FakeClient((b"IMAP4REV1", b"UIDPLUS"))
    _act(uidplus, MsgAction.expunge, MsgTarget("Trash", (7, 9)), None)  # type: ignore[arg-type]
    assert uidplus.log == [("select", "Trash"), ("flags", ((7, 9), (b"\\Deleted",))), ("expunge", (7, 9))]
    plain = FakeClient((b"IMAP4REV1",))
    _act(plain, MsgAction.expunge, MsgTarget("Trash", (7,)), None)  # type: ignore[arg-type]
    assert plain.log[-1] == ("expunge", None)
