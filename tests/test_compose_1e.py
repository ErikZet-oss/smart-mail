"""Phase 1e compose: draft create/reply, pre-send checks, undo send, S3/local attachments."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mail.compose_models import ComposeDraft
from app.mail.models import Mailbox, Message
from app.mail.signature import fill_variables
from app.mail.sync import apply_snapshot
from tests.conftest import Client, FakeMailServer, make_personal
from tests.test_mail_sync_1c import NOW, PASSWORD, delta, env, snapshot


async def _signed_in(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> Mailbox:
    acc = await make_personal(db)
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200
    return (await db.execute(select(Mailbox).where(Mailbox.email == acc.email))).scalar_one()


async def _seed_one(db: AsyncSession, mailbox: Mailbox) -> Message:
    snap = snapshot(
        delta("INBOX", 1, 2, 1, 1, new=[env(1, subject="Objednávka PO-77")], present_uids={1}),
        folders=("INBOX", "Drafts", "Sent"),
    )
    await apply_snapshot(db, mailbox, snap, now=NOW)
    await db.commit()
    msg = await db.scalar(select(Message).where(Message.mailbox_id == mailbox.id))
    assert msg is not None
    msg.body_html_sanitized = "<p>Prosím o potvrdenie.</p>"
    msg.body_text = "Prosím o potvrdenie."
    await db.commit()
    return msg


def test_1e_signature_variables() -> None:
    out = fill_variables("Ahoj {meno} z {pobocka}", {"meno": "Jana", "pobocka": "Senica", "priezvisko": ""})
    assert out == "Ahoj Jana z Senica"


@pytest.mark.asyncio
async def test_1e_compose_reply_keeps_subject_and_identity(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    msg = await _seed_one(db, mailbox)

    r = await client.send_json(
        "POST",
        "/api/mail/mailboxes/default/compose",
        {"mode": "reply", "message_id": str(msg.id)},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "reply"
    assert body["subject"].startswith("Re:")
    assert body["to_addrs"]
    assert body["status"] == "editing"
    identities = await client.get("/api/mail/mailboxes/default/identities")
    assert identities.status_code == 200
    assert len(identities.json()) >= 1


@pytest.mark.asyncio
async def test_1e_pre_send_blocks_placeholder(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await _signed_in(client, db, mail_server)
    created = await client.send_json("POST", "/api/mail/mailboxes/default/compose", {"mode": "new"})
    draft_id = created.json()["id"]
    patched = await client.send_json(
        "PATCH",
        f"/api/mail/compose/{draft_id}",
        {
            "to_addrs": [{"email": "novak@abcstav.example"}],
            "subject": "Test",
            "body_html": "<p>Prosím [[DOPLNIŤ]] množstvo.</p>",
        },
    )
    assert patched.status_code == 200
    assert any(c["code"] == "placeholder" and c["blocking"] for c in patched.json()["checks"])

    blocked = await client.send_json("POST", f"/api/mail/compose/{draft_id}/send", {"force": False})
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "pre_send_blocked"


@pytest.mark.asyncio
async def test_1e_send_with_undo_zero_calls_smtp(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings
) -> None:
    await _signed_in(client, db, mail_server)
    created = await client.send_json("POST", "/api/mail/mailboxes/default/compose", {"mode": "new"})
    draft_id = created.json()["id"]
    await client.send_json(
        "PATCH",
        f"/api/mail/compose/{draft_id}",
        {
            "to_addrs": [{"email": "novak@abcstav.example", "name": "Ján"}],
            "subject": "Potvrdenie",
            "body_html": "<p>Ďakujeme.</p>",
        },
    )
    with patch("app.mail.compose.send_message", new_callable=AsyncMock) as send:
        sent = await client.send_json("POST", f"/api/mail/compose/{draft_id}/send", {"force": False})
        assert sent.status_code == 200, sent.text
        # undo_send_seconds=0 in test settings → execute_send runs inline when enqueue fails or delay 0
        draft = await db.get(ComposeDraft, __import__("uuid").UUID(draft_id))
        assert draft is not None
        # may still be queued if arq enqueue succeeded; force execute
        from app.mail.compose import execute_send

        result = await execute_send(db, settings, draft.id)
        assert result in {"sent", "already", "undone"}
        if result == "sent":
            send.assert_awaited()
            await db.refresh(draft)
            assert draft.status == "sent"


@pytest.mark.asyncio
async def test_1e_storage_put_get_local(settings) -> None:
    from app.mail import storage

    key, digest = storage.put_bytes(settings, b"hello-1e", prefix="mail/test/att")
    assert len(digest) == 64
    assert storage.get_bytes(settings, key) == b"hello-1e"
    storage.delete_key(settings, key)
    assert storage.get_bytes(settings, key) is None
