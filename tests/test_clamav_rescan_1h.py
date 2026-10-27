"""ClamAV re-scan of skipped/error attachments when the daemon returns (Phase 1h follow-up)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.mail import storage
from app.mail.av_rescan import rescan_pending_attachments
from app.mail.models import Attachment, Message
from tests.conftest import Client, FakeMailServer
from tests.test_mail_messages_1d import _seed_inbox, _signed_in
from tests.test_mail_sync_1c import env


@pytest.mark.asyncio
async def test_rescan_skipped_becomes_clean_when_clamav_back(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    await _seed_inbox(db, mailbox, env(1, subject="S prílohou"))
    message = (await db.execute(select(Message).where(Message.mailbox_id == mailbox.id))).scalar_one()
    key, digest = storage.put_bytes(settings, b"clean-payload", prefix=f"mail/{mailbox.id}/att")
    att = Attachment(
        id=uuid.uuid4(),
        message_id=message.id,
        filename="Objednávka č. 12.pdf",
        content_type="application/pdf",
        size=13,
        storage_key=key,
        sha256=digest,
        av_status="skipped",  # stored while ClamAV was down
    )
    db.add(att)
    await db.commit()

    with patch("app.mail.av_rescan.scan_bytes", new=AsyncMock(return_value="clean")):
        counts = await rescan_pending_attachments(db, settings, limit=200)

    await db.refresh(att)
    assert counts["updated"] == 1
    assert counts["clean"] == 1
    assert att.av_status == "clean"


@pytest.mark.asyncio
async def test_rescan_skipped_becomes_infected_when_clamav_back(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    await _seed_inbox(db, mailbox, env(1, subject="EICAR"))
    message = (await db.execute(select(Message).where(Message.mailbox_id == mailbox.id))).scalar_one()
    key, digest = storage.put_bytes(settings, b"eicar", prefix=f"mail/{mailbox.id}/att")
    att = Attachment(
        id=uuid.uuid4(),
        message_id=message.id,
        filename="virus.bin",
        content_type="application/octet-stream",
        size=5,
        storage_key=key,
        sha256=digest,
        av_status="error",
    )
    db.add(att)
    await db.commit()

    with patch("app.mail.av_rescan.scan_bytes", new=AsyncMock(return_value="infected")):
        counts = await rescan_pending_attachments(db, settings)

    await db.refresh(att)
    assert counts["infected"] == 1
    assert att.av_status == "infected"


@pytest.mark.asyncio
async def test_rescan_leaves_skipped_when_clamav_still_down(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    await _seed_inbox(db, mailbox, env(1, subject="Ešte nie"))
    message = (await db.execute(select(Message).where(Message.mailbox_id == mailbox.id))).scalar_one()
    key, digest = storage.put_bytes(settings, b"pending", prefix=f"mail/{mailbox.id}/att")
    att = Attachment(
        id=uuid.uuid4(),
        message_id=message.id,
        filename="wait.pdf",
        content_type="application/pdf",
        size=7,
        storage_key=key,
        sha256=digest,
        av_status="skipped",
    )
    db.add(att)
    await db.commit()

    with patch("app.mail.av_rescan.scan_bytes", new=AsyncMock(return_value="skipped")):
        counts = await rescan_pending_attachments(db, settings)

    await db.refresh(att)
    assert counts["updated"] == 0
    assert counts["still_pending"] == 1
    assert att.av_status == "skipped"


@pytest.mark.asyncio
async def test_download_non_ascii_filename_header(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    """End-to-end: downloading a Slovak-named attachment must not latin-1-crash."""
    mailbox = await _signed_in(client, db, mail_server)
    await _seed_inbox(db, mailbox, env(1, subject="PDF"))
    message = (await db.execute(select(Message).where(Message.mailbox_id == mailbox.id))).scalar_one()
    key, digest = storage.put_bytes(settings, b"%PDF-1.4", prefix=f"mail/{mailbox.id}/att")
    att = Attachment(
        id=uuid.uuid4(),
        message_id=message.id,
        filename="Ponuka_Trenčín.pdf",
        content_type="application/pdf",
        size=8,
        storage_key=key,
        sha256=digest,
        av_status="clean",
    )
    db.add(att)
    await db.commit()

    r = await client.get(f"/api/mail/mailboxes/default/attachments/{att.id}")
    assert r.status_code == 200
    cd = r.headers["content-disposition"]
    cd.encode("latin-1")
    assert "filename*=UTF-8''" in cd
    assert "Tren" in cd
