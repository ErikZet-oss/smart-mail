"""Phase 1h-c notifications: sync failure + assignment (W14 / M16)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mail.models import Mailbox, Thread
from tests.conftest import Client, FakeMailServer, make_personal
from tests.test_mail_sync_1c import PASSWORD


async def test_1hc_notifications_sync_and_assign(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    acc = await make_personal(db)
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200

    mailbox = (await db.execute(select(Mailbox).where(Mailbox.email == acc.email))).scalar_one()
    mailbox.sync_state = "auth_failed"
    mailbox.sync_error = "auth_failed"
    mailbox.last_synced_at = datetime.now(UTC)

    me = (await client.get("/api/auth/me")).json()
    person_id = me["person"]["id"]
    db.add(
        Thread(
            mailbox_id=mailbox.id,
            thread_key=f"testid:{uuid.uuid4()}",
            subject="Pridelená objednávka",
            status="open",
            assignee_id=uuid.UUID(person_id),
            last_message_at=datetime.now(UTC),
        )
    )
    await db.commit()

    listed = await client.get("/api/notifications")
    assert listed.status_code == 200
    body = listed.json()
    kinds = {i["kind"] for i in body["items"]}
    assert "sync_failed" in kinds
    assert "assigned" in kinds
    assert body["unread_count"] >= 2

    dismiss = await client.send_json("POST", "/api/notifications/dismiss", {"all": True})
    assert dismiss.status_code == 200
    again = await client.get("/api/notifications")
    assert again.json()["unread_count"] == 0
