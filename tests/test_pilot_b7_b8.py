"""Pilot #18 B7 (send allowlist on Send) + B8 (sqlalchemy.case on AI views) against Postgres."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import Classification
from app.mail.models import FolderMeta, Mailbox, Message
from tests.conftest import Client, FakeMailServer, make_personal

PASSWORD = "secret"


async def _signed_in(client: Client, db: AsyncSession, mail_server: FakeMailServer, email: str) -> Mailbox:
    mail_server.passwords[email] = PASSWORD
    await make_personal(db, email=email)
    assert (await client.login(email, PASSWORD)).status_code == 200
    return (await db.execute(select(Mailbox).where(Mailbox.email == email))).scalar_one()


@pytest.mark.asyncio
async def test_b7_send_rejects_disallowed_recipient_422(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, app
) -> None:
    """Allowlist check on Send click — 422 before the draft is queued (pilot #18 B7)."""
    app.state.settings.mail_send_test_allowlist = "qa@example.test"
    await _signed_in(client, db, mail_server, "pilot-b7@smartmail.test")

    created = await client.send_json("POST", "/api/mail/mailboxes/default/compose", {"mode": "new"})
    assert created.status_code == 200, created.text
    draft_id = created.json()["id"]

    patched = await client.send_json(
        "PATCH",
        f"/api/mail/compose/{draft_id}",
        {
            "to_addrs": [{"email": "zakaznik@firma.sk"}],
            "subject": "Test B7",
            "body_html": "<p>Ahoj</p>",
        },
    )
    assert patched.status_code == 200, patched.text

    sent = await client.send_json("POST", f"/api/mail/compose/{draft_id}/send", {"force": False})
    assert sent.status_code == 422, sent.text
    detail = sent.json()["detail"]
    assert detail["code"] == "recipient_not_allowed"
    assert "zakaznik@firma.sk" in detail["blocked"]
    assert detail["show_allowlist"] is True
    assert "qa@example.test" in detail["allowlist"]

    again = await client.get(f"/api/mail/compose/{draft_id}")
    assert again.status_code == 200
    assert again.json()["status"] == "editing"


@pytest.mark.asyncio
async def test_b7_send_allows_smartmail_test_domain(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, app
) -> None:
    app.state.settings.mail_send_test_allowlist = ""
    await _signed_in(client, db, mail_server, "pilot-b7-ok@smartmail.test")
    created = await client.send_json("POST", "/api/mail/mailboxes/default/compose", {"mode": "new"})
    draft_id = created.json()["id"]
    await client.send_json(
        "PATCH",
        f"/api/mail/compose/{draft_id}",
        {
            "to_addrs": [{"email": "colleague@smartmail.test"}],
            "subject": "OK",
            "body_html": "<p>ok</p>",
        },
    )
    from unittest.mock import AsyncMock, patch

    with patch("app.mail.compose.send_message", new_callable=AsyncMock):
        sent = await client.send_json("POST", f"/api/mail/compose/{draft_id}/send", {"force": False})
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] in {"sent", "queued", "sending"}


@pytest.mark.asyncio
async def test_b7_empty_allowlist_does_not_block_external_on_send(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, app
) -> None:
    """Empty MAIL_SEND_TEST_ALLOWLIST must not 422 every recipient (Phase 1e send path)."""
    app.state.settings.mail_send_test_allowlist = ""
    await _signed_in(client, db, mail_server, "pilot-b7-empty@smartmail.test")
    created = await client.send_json("POST", "/api/mail/mailboxes/default/compose", {"mode": "new"})
    draft_id = created.json()["id"]
    await client.send_json(
        "PATCH",
        f"/api/mail/compose/{draft_id}",
        {
            "to_addrs": [{"email": "novak@abcstav.example"}],
            "subject": "Test",
            "body_html": "<p>Ďakujeme.</p>",
        },
    )
    from unittest.mock import AsyncMock, patch

    with patch("app.mail.compose.send_message", new_callable=AsyncMock):
        sent = await client.send_json("POST", f"/api/mail/compose/{draft_id}/send", {"force": False})
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] in {"sent", "queued", "sending"}


@pytest.mark.asyncio
async def test_b8_ai_views_messages_uses_sqlalchemy_case(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, app
) -> None:
    """GET /ai/views/*/messages must run the priority case() against Postgres (pilot #18 B8)."""
    from pydantic import SecretStr

    app.state.settings.anthropic_api_key = SecretStr("sk-test-b8")
    mailbox = await _signed_in(client, db, mail_server, "pilot-b8@smartmail.test")
    mailbox.ai_enabled = True
    mailbox.ai_enabled_at = datetime(2026, 10, 27, 10, 0, tzinfo=UTC)
    await db.flush()

    folder = FolderMeta(
        mailbox_id=mailbox.id,
        name="INBOX",
        special_use="inbox",
        subscribed=True,
        selectable=True,
        private=False,
    )
    db.add(folder)
    await db.flush()

    enabled = mailbox.ai_enabled_at
    assert enabled is not None
    rows: list[tuple[str, str, int]] = [
        ("urgent", "Urgentný dopyt", 1),
        ("low", "Nízky dopyt", 2),
        ("normal", "Bežný dopyt", 3),
    ]
    for priority, subject, uid in rows:
        msg = Message(
            mailbox_id=mailbox.id,
            folder_id=folder.id,
            uid=uid,
            message_id=f"<b8-{uuid4().hex}@customer.test>",
            subject=subject,
            from_name="Anna",
            from_email="anna@customer.test",
            body_text="Prosím o cenu",
            received_at=enabled + timedelta(minutes=uid),
            size=20,
        )
        db.add(msg)
        await db.flush()
        db.add(
            Classification(
                mailbox_id=mailbox.id,
                message_id=msg.id,
                message_id_header=f"b8-{uuid4().hex}@customer.test",
                category="inquiry",
                language="sk",
                priority=priority,
                payload={"summary_sk": subject, "confidence": 0.9, "note_codes": [], "source": "test"},
                status="done",
            )
        )
    await db.commit()

    view = await client.get("/api/mail/mailboxes/default/ai/views/inquiry/messages")
    assert view.status_code == 200, view.text
    body = view.json()
    assert body["total"] == 3
    subjects = [m["subject"] for m in body["messages"]]
    # urgent first, then normal, then low (sqlalchemy.case priority_order)
    assert subjects[0] == "Urgentný dopyt"
    assert subjects[1] == "Bežný dopyt"
    assert subjects[2] == "Nízky dopyt"
