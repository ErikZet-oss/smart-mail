"""Phase 1d message list, reading, prefs, flags, bulk, snooze/assign (SCREENS_SPEC W2 / W2c / W2e / W2o / W2i / W2j).

Uses the local DB + apply_snapshot (no live IMAP) unless a test opts into body fetch.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

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
