"""W2p Hlavičky správy: header block only, folding kept, encoded words decoded, other mailbox → 404.
All addresses and hosts are fictional."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.mail import storage
from app.mail.models import Message
from app.mail.raw_headers import parse_headers
from tests.conftest import Client, FakeMailServer
from tests.test_mail_messages_1d import _seed_inbox, _signed_in
from tests.test_mail_sync_1c import env

RAW = (
    b"Return-Path: <objednavky@fiktivna-firma.example>\r\n"
    b"Received: from mx004.example.net (mx004.example.net [192.0.2.10])\r\n"
    b"\tby mail.example.net with esmtps (TLS1.3); Tue, 17 Nov 2026 07:41:26 +0100\r\n"
    b"From: =?utf-8?q?Jana_Fikt=C3=ADvna?= <objednavky@fiktivna-firma.example>\r\n"
    b"To: eshop@smartmail.test\r\n"
    b"Subject: Rozvoz\r\n"
    b"Authentication-Results: mail.example.net; spf=pass; dkim=pass; dmarc=pass\r\n"
    b"\r\n"
    b"Tajne telo: X-Not-A-Header: no\r\n"
)


def test_w2p_parse_keeps_order_folding_and_decodes() -> None:
    headers = parse_headers(RAW)
    assert [h["name"] for h in headers] == [
        "Return-Path",
        "Received",
        "From",
        "To",
        "Subject",
        "Authentication-Results",
    ]
    assert headers[1]["value"].split("\n")[1].startswith("  by mail.example.net")
    assert headers[2]["value"] == "Jana Fiktívna <objednavky@fiktivna-firma.example>"
    assert "Tajne" not in str(headers)  # never the body


def test_w2p_parse_lf_only_and_mbox_from_line() -> None:
    raw = b"From someone Tue Nov 17 2026\nSubject: A\nX-Y: b\n\nbody"
    assert parse_headers(raw) == [{"name": "Subject", "value": "A"}, {"name": "X-Y", "value": "b"}]


@given(st.binary(max_size=2000))
def test_w2p_parse_never_raises(raw: bytes) -> None:
    for h in parse_headers(raw):
        assert h["name"] and ":" not in h["name"]


async def test_w2p_headers_endpoint(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    folder = await _seed_inbox(db, mailbox, env(1, subject="Rozvoz"))
    msg = await db.scalar(select(Message).where(Message.folder_id == folder.id))
    assert msg is not None
    msg.raw_storage_key = storage.put_bytes(settings, RAW, prefix=f"mail/{mailbox.id}/raw")[0]
    msg.auth_results = {"spf": "pass", "dkim": "pass", "dmarc": "pass"}
    await db.commit()

    r = await client.get(f"/api/mail/mailboxes/default/messages/{msg.id}/headers")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["headers"][0] == {"name": "Return-Path", "value": "<objednavky@fiktivna-firma.example>"}
    assert out["auth_results"] == {"spf": "pass", "dkim": "pass", "dmarc": "pass"}

    r = await client.get("/api/mail/mailboxes/default/messages/00000000-0000-0000-0000-000000000000/headers")
    assert r.status_code == 404
