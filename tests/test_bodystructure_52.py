"""Issue #52: the paperclip from the IMAP BODYSTRUCTURE, before the first open. Fixtures are real Dovecot responses to
fictional messages (tests/fixtures/bodystructure)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from imapclient.response_parser import parse_fetch_response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mail.bodystructure import has_file_attachments_structure
from app.mail.models import Message
from app.mail.sync import FETCH_ITEMS, apply_snapshot, parse_envelope
from tests.conftest import make_personal
from tests.test_mail_sync_1c import NOW, delta, make_mailbox, snapshot

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
