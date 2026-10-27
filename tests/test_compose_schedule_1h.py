"""W4c schedule send: PATCH scheduled_at → status scheduled; clear cancels (Phase 1h)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.mail.compose_models import ComposeDraft
from tests.conftest import Client, FakeMailServer, make_personal

EMAIL, PASSWORD = "jana@smartsro.sk", "Spravne-Heslo-1"


@pytest.mark.asyncio
async def test_1h_schedule_and_cancel(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await make_personal(db, EMAIL)
    mail_server.passwords[EMAIL] = PASSWORD
    assert (await client.login(EMAIL, PASSWORD)).status_code == 200

    created = await client.send_json("POST", "/api/mail/mailboxes/default/compose", {"mode": "new"})
    assert created.status_code == 200, created.text
    draft_id = created.json()["id"]
    when = (datetime.now(UTC) + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)

    patched = await client.send_json(
        "PATCH",
        f"/api/mail/compose/{draft_id}",
        {
            "to_addrs": [{"email": "peter@smartsro.sk"}],
            "subject": "Naplánované",
            "body_html": "<p>ahoj</p>",
            "scheduled_at": when.isoformat(),
        },
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["status"] == "scheduled"
    assert body["scheduled_at"] is not None

    row = await db.get(ComposeDraft, draft_id)
    assert row is not None and row.status == "scheduled"

    cleared = await client.send_json("PATCH", f"/api/mail/compose/{draft_id}", {"scheduled_at": None})
    assert cleared.status_code == 200
    assert cleared.json()["status"] == "editing"
    assert cleared.json()["scheduled_at"] is None
