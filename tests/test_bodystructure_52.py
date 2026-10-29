"""Issue #52: the paperclip from the IMAP BODYSTRUCTURE, before the first open. Fixtures are real Dovecot responses to
fictional messages (tests/fixtures/bodystructure)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from imapclient.response_parser import parse_fetch_response
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.mail.attachment_backfill as backfill_mod
from app.auth.security import encrypt
from app.core.config import Settings
from app.mail.bodystructure import has_file_attachments_structure
from app.mail.models import Message
from app.mail.sync import FETCH_ITEMS, apply_snapshot, parse_envelope
from tests.conftest import TEST_REDIS_URL, make_personal
from tests.test_mail_sync_1c import NOW, delta, env, make_mailbox, snapshot

FIXTURES = Path(__file__).parent / "fixtures" / "bodystructure"


def _fetched(name: str) -> dict[bytes, Any]:
    raw = (FIXTURES / f"{name}.txt").read_bytes().strip()
    return next(iter(parse_fetch_response([raw]).values()))


@pytest.mark.parametrize(
    ("fixture", "paperclip"),
    [
        ("gmail_pdf", True),  # multipart/mixed: alternative + application/pdf attachment
        ("outlook_signature_cid", False),  # multipart/related: signature image with Content-ID, inline
        ("forwarded_eml", True),  # message/rfc822 is a file for the user
        ("isdoc_xml", True),  # text/xml with a name, no Content-Disposition
        ("mixed_signature_and_xlsx", True),  # related signature logo (no) + xlsx attachment (yes)
        ("plain_text", False),
    ],
)
def test_52_bodystructure_paperclip(fixture: str, paperclip: bool) -> None:
    assert has_file_attachments_structure(_fetched(fixture)[b"BODYSTRUCTURE"]) is paperclip


@pytest.mark.parametrize("broken", [None, (), (b"text",), "garbage", (None, None, None)])
def test_52_unknown_or_broken_structure_means_no_paperclip(broken: object) -> None:
    assert has_file_attachments_structure(broken) is False


def test_52_envelope_sync_fetches_bodystructure() -> None:
    assert "BODYSTRUCTURE" in FETCH_ITEMS


async def test_52_unopened_message_gets_the_paperclip_at_insert(db: AsyncSession) -> None:
    mailbox = await make_mailbox(db, await make_personal(db))
    pdf, signature = _fetched("gmail_pdf"), _fetched("outlook_signature_cid")
    new = [parse_envelope(1, pdf), parse_envelope(2, signature)]
    assert [e.has_attachments for e in new] == [True, False]
    await apply_snapshot(db, mailbox, snapshot(delta("INBOX", 1, 3, 2, 2, new=new)), now=NOW)
    await db.commit()
    rows = dict((await db.execute(select(Message.uid, Message.has_attachments))).all())
    assert rows == {1: True, 2: False}


# --- review #67: the backfill holds the sync lock for a bounded time and resumes -------------------------------
class _SlowFetchClient:
    def __init__(self) -> None:
        self.fetched: list[int] = []

    def select_folder(self, name: str, readonly: bool = False) -> None:
        return None

    def fetch(self, uids: list[int], items: list[str]) -> dict[int, dict[bytes, Any]]:
        time.sleep(0.05)
        self.fetched += uids
        pdf = _fetched("gmail_pdf")[b"BODYSTRUCTURE"]
        plain = _fetched("plain_text")[b"BODYSTRUCTURE"]
        return {uid: {b"BODYSTRUCTURE": pdf if uid % 100 == 0 else plain} for uid in uids}


async def test_52_backfill_stops_at_the_time_budget_and_resumes(
    db: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = await make_personal(db, mailbox_password_enc=encrypt(settings, "heslo"))
    mailbox = await make_mailbox(db, account)
    count = 1500  # 3 batches of 500
    await apply_snapshot(
        db,
        mailbox,
        snapshot(delta("INBOX", 1, count + 1, count, 0, new=[env(u) for u in range(1, count + 1)])),
        now=NOW,
    )
    await db.commit()
    client = _SlowFetchClient()
    monkeypatch.setattr(backfill_mod, "connect", lambda *a, **k: client)
    monkeypatch.setattr(backfill_mod, "logout_quietly", lambda c: None)
    live = settings.model_copy(update={"mail_sync_enabled": True})
    redis = Redis.from_url(TEST_REDIS_URL)
    try:
        await redis.delete(backfill_mod.done_key(mailbox.id), backfill_mod.progress_key(mailbox.id))

        first = await backfill_mod.backfill_mailbox(db, redis, mailbox, live, pause_s=0, budget_s=0.07)
        assert first is not None and 0 < first < count // 100  # stopped before the last batch
        assert not await redis.exists(backfill_mod.done_key(mailbox.id))  # not finished: no marker
        assert not await redis.exists(f"smartmail:mail-sync:{mailbox.id}")  # the sync lock is free again
        after_first = list(client.fetched)

        second = await backfill_mod.backfill_mailbox(db, redis, mailbox, live, pause_s=0, budget_s=60)
        assert second is not None and first + second == count // 100
        assert await redis.exists(backfill_mod.done_key(mailbox.id))
        assert not await redis.exists(backfill_mod.progress_key(mailbox.id))
        assert len(client.fetched) == count and len(set(client.fetched)) == count  # nothing fetched twice
        assert set(after_first) < set(client.fetched)
    finally:
        await redis.delete(backfill_mod.done_key(mailbox.id), backfill_mod.progress_key(mailbox.id))
        await redis.aclose()
    flagged = await db.scalar(select(func.count()).select_from(Message).where(Message.has_attachments.is_(True)))
    assert flagged == count // 100
