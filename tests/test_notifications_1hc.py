"""Phase 1h-c notifications: sync failure + assignment (W14 / M16)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.notifications import event_id, prune_dismissed, sync_error_code
from app.auth.models import Person, Role
from app.mail.models import Mailbox, Thread
from tests.conftest import Client, FakeMailServer, make_personal
from tests.test_mail_sync_1c import PASSWORD


def test_1hc_sync_error_code_never_raw() -> None:
    assert sync_error_code("auth_failed") == "auth_failed"
    assert sync_error_code("host_not_allowed") == "host_not_allowed"
    assert sync_error_code("no_credentials") == "no_credentials"
    assert sync_error_code("TimeoutError") == "unavailable"
    assert sync_error_code("Connection refused by imap.example") == "unavailable"
    assert sync_error_code(None) == "unavailable"


def test_1hc_event_id_includes_time() -> None:
    mid = uuid.UUID("11111111-1111-1111-1111-111111111111")
    t1 = datetime(2026, 10, 27, 8, 0, tzinfo=UTC)
    t2 = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
    assert event_id("sync", mid, t1) != event_id("sync", mid, t2)
    assert event_id("sync", mid, t1).startswith(f"sync:{mid}:")


def test_1hc_prune_dismissed_cap_and_age() -> None:
    now = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
    old = event_id("sync", uuid.uuid4(), now - timedelta(days=40))
    fresh = [event_id("sync", uuid.uuid4(), now - timedelta(minutes=i)) for i in range(600)]
    pruned = prune_dismissed({old, *fresh}, now=now)
    assert old not in pruned
    assert len(pruned) == 500


async def test_1hc_notifications_href_and_params(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    acc = await make_personal(db)
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200

    mailbox = (await db.execute(select(Mailbox).where(Mailbox.email == acc.email))).scalar_one()
    failed_at = datetime(2026, 10, 27, 8, 0, tzinfo=UTC)
    mailbox.sync_state = "auth_failed"
    mailbox.sync_error = "auth_failed"
    mailbox.updated_at = failed_at
    await db.commit()

    listed = await client.get("/api/notifications")
    assert listed.status_code == 200
    body = listed.json()
    sync_items = [i for i in body["items"] if i["kind"] == "sync_failed"]
    assert len(sync_items) == 1
    item = sync_items[0]
    assert item["href"] == f"/mail/{mailbox.id}/inbox"
    assert item["id"] == event_id("sync", mailbox.id, failed_at)
    assert "title" not in item and "body" not in item
    assert item["params"] == {"mailbox_email": acc.email, "error_code": "auth_failed"}
    assert "auth_failed" not in item.get("body", "")  # no raw / SK body from API


async def test_1hc_assign_href_and_new_event_unread(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    acc = await make_personal(db)
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200
    mailbox = (await db.execute(select(Mailbox).where(Mailbox.email == acc.email))).scalar_one()
    me = (await client.get("/api/auth/me")).json()
    other = Person(first_name="Peter", last_name="Odovzdávač", role=Role.sales)
    db.add(other)
    await db.flush()
    thread = Thread(
        mailbox_id=mailbox.id,
        thread_key=f"testid:{uuid.uuid4()}",
        subject="Pridelená objednávka",
        status="open",
        assignee_id=uuid.UUID(me["person"]["id"]),
        assigned_by_id=other.id,
        assigned_at=datetime(2026, 10, 26, 18, 0, tzinfo=UTC),
        last_message_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.commit()
    await db.refresh(thread)

    listed = await client.get("/api/notifications")
    assigned = [i for i in listed.json()["items"] if i["kind"] == "assigned"]
    assert len(assigned) == 1
    assert assigned[0]["href"] == f"/mail/{mailbox.id}/inbox/{thread.id}"
    assert assigned[0]["params"]["subject"] == "Pridelená objednávka"
    assert assigned[0]["id"] == event_id("assign", thread.id, thread.assigned_at)  # type: ignore[arg-type]
    assert assigned[0]["unread"] is True

    dismiss = await client.send_json("POST", "/api/notifications/dismiss", {"ids": [assigned[0]["id"]]})
    assert dismiss.status_code == 200
    assert (await client.get("/api/notifications")).json()["unread_count"] == 0

    # Reassignment later → new id → unread again
    thread.assigned_at = datetime(2026, 10, 27, 10, 0, tzinfo=UTC)
    thread.assigned_by_id = other.id
    await db.commit()
    again = await client.get("/api/notifications")
    assigned2 = [i for i in again.json()["items"] if i["kind"] == "assigned"]
    assert len(assigned2) == 1
    assert assigned2[0]["unread"] is True
    assert assigned2[0]["id"] != assigned[0]["id"]


async def test_1hc_self_assign_no_notification(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    acc = await make_personal(db)
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200
    mailbox = (await db.execute(select(Mailbox).where(Mailbox.email == acc.email))).scalar_one()
    me = (await client.get("/api/auth/me")).json()
    person_id = me["person"]["id"]
    thread = Thread(
        mailbox_id=mailbox.id,
        thread_key=f"testid:{uuid.uuid4()}",
        subject="Seba",
        status="open",
        last_message_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.commit()
    await db.refresh(thread)

    assign = await client.send_json(
        "POST",
        f"/api/mail/mailboxes/default/threads/{thread.id}/assign",
        {"person_id": person_id},
    )
    assert assign.status_code == 200

    listed = await client.get("/api/notifications")
    kinds = {i["kind"] for i in listed.json()["items"]}
    assert "assigned" not in kinds


async def test_1hc_dismiss_list_capped(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    acc = await make_personal(db)
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200
    me = (await client.get("/api/auth/me")).json()
    person_id = uuid.UUID(me["person"]["id"])
    now = datetime.now(UTC)
    flood = {event_id("sync", uuid.uuid4(), now - timedelta(seconds=i)) for i in range(520)}
    from app.mail.prefs import save_section

    await save_section(db, person_id, "notifications.dismissed", {"ids": sorted(flood)})
    await db.commit()

    # Trigger prune via dismiss of one more id
    extra = event_id("sync", uuid.uuid4(), now)
    r = await client.send_json("POST", "/api/notifications/dismiss", {"ids": [extra]})
    assert r.status_code == 200
    assert r.json()["dismissed"] <= 500

    from app.mail.models import UserSettings

    row = await db.scalar(
        select(UserSettings).where(
            UserSettings.person_id == person_id, UserSettings.section == "notifications.dismissed"
        )
    )
    assert row is not None
    assert isinstance(row.data["ids"], list)
    assert len(row.data["ids"]) <= 500
    assert extra in row.data["ids"]
