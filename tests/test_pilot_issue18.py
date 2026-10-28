"""Pilot VPS issue #18 — B1 ManageSieve non-blocking, B3 AI off, B4 readyz isolation."""

from __future__ import annotations

import asyncio
import time
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.mail.models import Mailbox
from app.mail.sieve import SieveError
from app.mail.sieve_async import (
    SIEVE_CONNECT_TIMEOUT_S,
    SIEVE_UNAVAILABLE_MESSAGE_SK,
    _connect_with_timeout,
    mark_sieve_unavailable,
    sieve_marked_unavailable,
)
from tests.conftest import Client, FakeMailServer, make_personal

BLACKHOLE = "192.0.2.1"  # TEST-NET-1 — packets should never answer
PASSWORD = "secret"


@pytest.mark.asyncio
async def test_b1_blackhole_sieve_connect_times_out_fast() -> None:
    """TCP connect to a black hole must fail within ~5 s, not hang the thread forever."""
    settings = Settings(
        app_env="test",
        app_base_url="http://test",
        app_secret_key="test-secret-key-that-is-long-enough-0123456789",
        database_url="postgresql+asyncpg://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
        mail_sync_allow_real_server=True,
    )
    mailbox = Mailbox(
        email="pilot@smartmail.test",
        imap_host=BLACKHOLE,
        imap_port=993,
        imap_security="ssl",
        sieve_host=BLACKHOLE,
        sieve_port=4190,
        sieve_enabled=True,
    )
    started = time.perf_counter()
    with pytest.raises(SieveError) as excinfo:
        await asyncio.to_thread(
            _connect_with_timeout,
            settings,
            mailbox,
            username="x",
            password="y",
        )
    elapsed = time.perf_counter() - started
    assert excinfo.value.code == "sieve_unavailable"
    assert elapsed < SIEVE_CONNECT_TIMEOUT_S + 2.0


@pytest.mark.asyncio
async def test_b1_sieve_hang_does_not_block_readyz_or_messages(
    client: Client,
    db: AsyncSession,
    mail_server: FakeMailServer,
    app,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """While ManageSieve hangs on a black hole, /readyz and folders stay fast (< 1 s)."""
    monkeypatch.setattr(settings, "mail_sync_allow_real_server", True)
    email = "pilot-sieve@smartmail.test"
    mail_server.passwords[email] = PASSWORD
    await make_personal(db, email=email)
    assert (await client.login(email, PASSWORD)).status_code == 200

    mailbox = (await db.execute(select(Mailbox).where(Mailbox.email == email))).scalar_one()
    mailbox.sieve_host = BLACKHOLE
    mailbox.sieve_port = 4190
    mailbox.sieve_enabled = True
    await db.commit()

    hang = asyncio.create_task(client.get("/api/settings/mailboxes/default/filters"))
    await asyncio.sleep(0.15)

    t0 = time.perf_counter()
    ready = await client.get("/readyz")
    ready_ms = (time.perf_counter() - t0) * 1000
    assert ready.status_code == 200, ready.text
    assert ready_ms < 1000, f"/readyz took {ready_ms:.0f} ms while Sieve hangs"

    t1 = time.perf_counter()
    folders = await client.get("/api/mail/mailboxes/default/folders")
    list_ms = (time.perf_counter() - t1) * 1000
    assert folders.status_code == 200, folders.text
    assert list_ms < 1000, f"folders took {list_ms:.0f} ms while Sieve hangs"

    filters = await hang
    assert filters.status_code == 200, filters.text
    body = filters.json()
    assert body.get("sieve_unavailable") is True
    assert body.get("sieve_message") == SIEVE_UNAVAILABLE_MESSAGE_SK


@pytest.mark.asyncio
async def test_b1_sieve_unavailable_cached_in_redis(app) -> None:
    redis = app.state.redis
    mid = uuid4()
    assert await sieve_marked_unavailable(redis, mid) is False
    await mark_sieve_unavailable(redis, mid)
    assert await sieve_marked_unavailable(redis, mid) is True


@pytest.mark.asyncio
async def test_b3_ai_categories_empty_when_ai_disabled(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    email = "pilot-ai@smartmail.test"
    mail_server.passwords[email] = PASSWORD
    await make_personal(db, email=email)
    assert (await client.login(email, PASSWORD)).status_code == 200

    mailbox = (await db.execute(select(Mailbox).where(Mailbox.email == email))).scalar_one()
    assert mailbox.ai_enabled is False

    cats = await client.get("/api/mail/mailboxes/default/ai/categories")
    assert cats.status_code == 200
    assert cats.json()["categories"] == []

    view = await client.get("/api/mail/mailboxes/default/ai/views/inquiry/messages")
    assert view.status_code == 200
    assert view.json()["total"] == 0
    assert view.json()["messages"] == []

    folders = await client.get("/api/mail/mailboxes/default/folders")
    assert folders.status_code == 200
    mb = folders.json()["mailbox"]
    assert mb["ai_enabled"] is False
    assert mb["ai_available"] is False


@pytest.mark.asyncio
async def test_b4_readyz_fast_when_ok(client: Client) -> None:
    t0 = time.perf_counter()
    r = await client.get("/readyz")
    assert r.status_code == 200
    assert (time.perf_counter() - t0) < 1.0
