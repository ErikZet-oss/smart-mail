"""Issue #52 against the local test IMAP server (Dovecot, fictional mail): the paperclip shows before the first open,
an Outlook-style signature logo gets none, and the one-off backfill flags messages synced before #52.

Runs when TEST_IMAP_HOST is set (see tests/integration/test_imap_messages_1d.py).
"""

from __future__ import annotations

from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from imapclient import IMAPClient
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.mail.attachment_backfill import backfill_mailbox, done_key
from app.mail.models import Mailbox, Message
from tests.conftest import TEST_REDIS_URL, Client, make_personal
from tests.integration.test_imap_messages_1d import (  # noqa: F401  (fixtures)
    addr,
    imap,
    login,
    mail_server,
    pytestmark,
    refresh,
    reseed_senica,
    settings,
    thread_pair_with_attachment,
)

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def _outlook_signature_only() -> bytes:
    rel = MIMEMultipart("related")
    rel["From"] = "Eva Testovacia <eva@dodavatel.example>"
    rel["To"] = addr("senica")
    rel["Subject"] = "Podpis s logom 52"
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText("Dobrý deň", "plain", "utf-8"))
    alt.attach(MIMEText('<p>Dobrý deň</p><img src="cid:logo52@x">', "html", "utf-8"))
    rel.attach(alt)
    logo = MIMEImage(PNG, "png")
    logo.add_header("Content-ID", "<logo52@x>")
    rel.attach(logo)
    return rel.as_bytes()


async def test_52_paperclip_before_first_open_and_backfill(
    client: Client,
    db: AsyncSession,
    imap: IMAPClient,  # noqa: F811  (fixture imported from the 1d module)
    settings: Settings,  # noqa: F811
) -> None:
    await make_personal(db, email=addr("senica"))
    await login(client, "senica")
    parent, _ = thread_pair_with_attachment()  # fictional PDF attachment
    imap.append("INBOX", parent)
    imap.append("INBOX", _outlook_signature_only())
    await refresh(client)

    flags = dict((await db.execute(select(Message.subject, Message.has_attachments))).all())
    assert flags["Dodací list DL-1d-77"] is True  # never opened, paperclip from BODYSTRUCTURE
    assert flags["Podpis s logom 52"] is False  # signature logo is not an attachment

    # a mailbox synced before #52: the flag is missing; the backfill sets it once
    await db.execute(update(Message).values(has_attachments=False))
    await db.commit()
    mailbox = (await db.execute(select(Mailbox).where(Mailbox.email == addr("senica")))).scalar_one()
    redis = Redis.from_url(TEST_REDIS_URL)
    try:
        await redis.delete(done_key(mailbox.id))
        flagged = await backfill_mailbox(db, redis, mailbox, settings, pause_s=0)
        assert flagged is not None and flagged >= 1  # the seeded fictional mailbox has more attachments
        assert await backfill_mailbox(db, redis, mailbox, settings, pause_s=0) is None  # once per mailbox
    finally:
        await redis.delete(done_key(mailbox.id))
        await redis.aclose()
    flags = dict(
        (
            await db.execute(select(Message.subject, Message.has_attachments).execution_options(populate_existing=True))
        ).all()
    )
    assert flags["Dodací list DL-1d-77"] is True and flags["Podpis s logom 52"] is False
