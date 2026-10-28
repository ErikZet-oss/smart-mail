"""GitHub #23 — Sent folder on imap-test: no NAMESPACE prefix, and an INBOX. prefix safety net.

The shared Dovecot uses separator ``/`` and an empty personal prefix (folder ``Sent``).
The prefix case creates ``INBOX.Sent`` and APPENDs there when that name is the folder
sync already knows. A reply also sets ``\\Answered`` and the Sent copy is synced at once.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

import pytest
from imapclient.exceptions import IMAPClientError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role
from app.core.config import Settings
from app.mail.imap import ImapAuthenticator, ImapServer
from app.mail.imap_append import append_to_sent, read_personal_namespace
from app.mail.models import FolderMeta, Mailbox, Message
from app.mail.sync import Credentials, connect, logout_quietly, server_of
from tests.conftest import TEST_REDIS_URL, Client, make_personal

HOST = os.environ.get("TEST_IMAP_HOST", "")
IMAP_PORT = int(os.environ.get("TEST_IMAP_PORT", "1143"))
SMTP_HOST = os.environ.get("TEST_SMTP_HOST", HOST)
SMTP_PORT = int(os.environ.get("TEST_SMTP_PORT", "1587"))
ROOT = Path(__file__).resolve().parents[2]
PILOT_EMAIL = "pilot@smartmail.test"
PILOT_PASSWORD = "pilot-test-heslo"

pytestmark = [
    pytest.mark.imap,
    pytest.mark.skipif(
        not HOST and os.environ.get("REQUIRE_IMAP") != "1",
        reason="local test IMAP/SMTP submission not configured (TEST_IMAP_HOST / TEST_SMTP_PORT)",
    ),
]


@pytest.fixture(scope="module", autouse=True)
def reseed_pilot() -> None:
    if not HOST:
        pytest.fail("REQUIRE_IMAP=1 but TEST_IMAP_HOST is empty")
    cmd = [
        sys.executable,
        "tools/seed_test_imap.py",
        "--host",
        HOST,
        "--port",
        str(IMAP_PORT),
        "--reset",
        "--user",
        PILOT_EMAIL,
    ]
    subprocess.run(cmd, cwd=ROOT, check=True, capture_output=True)


@pytest.fixture
def settings(migrated: str) -> Settings:
    return Settings(
        app_env="test",
        app_base_url="http://test",
        app_secret_key="test-secret-key-that-is-long-enough-0123456789",
        database_url=migrated,
        redis_url=TEST_REDIS_URL,
        imap_login_host=HOST,
        imap_login_port=IMAP_PORT,
        imap_login_security="none",
        smtp_host=SMTP_HOST or HOST,
        smtp_port=SMTP_PORT,
        smtp_security="none",
        mail_send_allow_real_server=True,
        mail_sync_allow_real_server=True,
        undo_send_seconds=0,
        internal_domains="smartmail.test",
        mail_send_test_allowlist="",
    )


def _pilot() -> tuple[ImapServer, Credentials]:
    return ImapServer(HOST, IMAP_PORT, "none", 10), Credentials(PILOT_EMAIL, PILOT_PASSWORD)


def _names(client: object) -> set[str]:
    listed = client.list_folders()  # type: ignore[attr-defined]
    names: set[str] = set()
    for _flags, _delim, name in listed:
        names.add(name if isinstance(name, str) else name.decode("utf-8", "replace"))
    return names


def _subject_uids(client: object, folder: str, subject: str) -> list[int]:
    client.select_folder(folder)  # type: ignore[attr-defined]
    found = client.search(["SUBJECT", subject])  # type: ignore[attr-defined]
    return [int(uid) for uid in found]


def test_23_imap_without_prefix_appends_to_existing_sent() -> None:
    """Live imap-test NAMESPACE is empty + ``/``; APPEND reuses \\Sent and does not create another."""
    server, creds = _pilot()
    client = connect(server, creds)
    subject = f"issue23-plain-{uuid.uuid4().hex[:8]}"
    try:
        prefix, delimiter = read_personal_namespace(client)
        assert prefix == ""
        assert delimiter == "/"
        before = _names(client)
        assert "Sent" in before
        message = EmailMessage()
        message["From"] = f"Pilot <{PILOT_EMAIL}>"
        message["To"] = "sender@smartmail.test"
        message["Subject"] = subject
        message.set_content("Bez prefixu.")
        appended = append_to_sent(server, creds, message, known_folder=None)
        assert appended.folder == "Sent"
        assert _subject_uids(client, "Sent", subject)
        assert "INBOX.Sent" not in (_names(client) - before)
    finally:
        logout_quietly(client)


def test_23_imap_inbox_prefix_known_folder_receives_append() -> None:
    """Safety net: a prefixed Sent folder sync already knows wins over \\Sent.

    This Dovecot uses delimiter ``/`` and rejects ``.`` in mailbox names, so the
    prefixed mailbox is ``INBOX/Sent`` (the ``INBOX.`` + ``.`` layout is covered by
    ``ensure_sent_folder`` against a fake NAMESPACE). APPEND must not land in ``Sent``.
    """
    server, creds = _pilot()
    client = connect(server, creds)
    prefixed = "INBOX/Sent"
    subject = f"issue23-prefix-{uuid.uuid4().hex[:8]}"
    created = False
    try:
        if prefixed not in _names(client):
            client.create_folder(prefixed)
            try:
                client.subscribe_folder(prefixed)
            except (OSError, IMAPClientError):
                pass
            created = True
        message = EmailMessage()
        message["From"] = f"Pilot <{PILOT_EMAIL}>"
        message["To"] = "sender@smartmail.test"
        message["Subject"] = subject
        message.set_content("S prefixom INBOX.")
        appended = append_to_sent(server, creds, message, known_folder=prefixed)
        assert appended.folder == prefixed
        assert _subject_uids(client, prefixed, subject)
        assert _subject_uids(client, "Sent", subject) == []
    finally:
        if created:
            try:
                client.delete_folder(prefixed)
            except (OSError, IMAPClientError):
                pass
        logout_quietly(client)


def _append_inbox(client: object, subject: str, message_id: str) -> int:
    raw = EmailMessage()
    raw["From"] = "Sender <sender@smartmail.test>"
    raw["To"] = PILOT_EMAIL
    raw["Subject"] = subject
    raw["Message-ID"] = message_id
    raw.set_content("Pôvodná správa.")
    response = client.append("INBOX", raw.as_bytes())  # type: ignore[attr-defined]
    if isinstance(response, int):
        return response
    if isinstance(response, tuple) and isinstance(response[-1], int):
        return int(response[-1])
    found = _subject_uids(client, "INBOX", subject)
    assert found, response
    return found[-1]


def _flag_names(client: object, folder: str, uid: int) -> set[str]:
    client.select_folder(folder)  # type: ignore[attr-defined]
    fetched = client.fetch([uid], ["FLAGS"])  # type: ignore[attr-defined]
    raw = fetched[uid][b"FLAGS"]
    names: set[str] = set()
    for flag in raw:
        names.add(flag.decode("ascii", "replace") if isinstance(flag, bytes) else str(flag))
    return names


@pytest.mark.asyncio
async def test_23_reply_sets_answered_and_sent_is_synced_immediately(
    settings: Settings, db: AsyncSession, client: Client, app
) -> None:
    app.state.settings.smtp_host = SMTP_HOST or HOST
    app.state.settings.smtp_port = SMTP_PORT
    app.state.settings.smtp_security = "none"
    app.state.settings.mail_send_allow_real_server = True
    app.state.settings.mail_sync_allow_real_server = True
    app.state.settings.undo_send_seconds = 0
    app.state.settings.imap_login_host = HOST
    app.state.settings.imap_login_port = IMAP_PORT
    app.state.settings.imap_login_security = "none"
    app.state.authenticator = ImapAuthenticator(ImapServer(HOST, IMAP_PORT, "none", settings.imap_login_timeout_s))
    await make_personal(db, email=PILOT_EMAIL, role=Role.sales)
    assert (await client.login(PILOT_EMAIL, PILOT_PASSWORD)).status_code == 200

    mailbox = (await db.execute(select(Mailbox).where(Mailbox.email == PILOT_EMAIL))).scalar_one()
    mailbox.smtp_host = SMTP_HOST or HOST
    mailbox.smtp_port = SMTP_PORT
    mailbox.smtp_security = "none"
    await db.commit()

    subject = f"issue23-reply-{uuid.uuid4().hex[:8]}"
    message_id = make_msgid(domain="smartmail.test")
    server = server_of(mailbox, app.state.settings)
    imap = connect(server, Credentials(PILOT_EMAIL, PILOT_PASSWORD))
    try:
        uid = _append_inbox(imap, subject, message_id)
    finally:
        logout_quietly(imap)

    folder = FolderMeta(mailbox_id=mailbox.id, name="INBOX", special_use="inbox", selectable=True)
    db.add(folder)
    await db.flush()
    source = Message(
        mailbox_id=mailbox.id,
        folder_id=folder.id,
        uid=uid,
        message_id=message_id,
        subject=subject,
        from_name="Sender",
        from_email="sender@smartmail.test",
        flags=[],
        answered=False,
        seen=True,
    )
    db.add(source)
    await db.commit()

    created = await client.send_json(
        "POST",
        "/api/mail/mailboxes/default/compose",
        {"mode": "reply", "message_id": str(source.id)},
    )
    assert created.status_code == 200, created.text
    draft_id = created.json()["id"]
    sent = await client.send_json("POST", f"/api/mail/compose/{draft_id}/send", {"force": False})
    assert sent.status_code == 200, sent.text
    body = sent.json()
    assert body["status"] == "sent", body
    assert body["send_error"] in {None, ""}
    assert body["sent_message_id"]
    assert body["sent_folder_ref"] == "sent"

    imap = connect(server, Credentials(PILOT_EMAIL, PILOT_PASSWORD))
    try:
        flags = _flag_names(imap, "INBOX", uid)
        assert "\\Answered" in flags
        assert _subject_uids(imap, "Sent", f"Re: {subject}")
    finally:
        logout_quietly(imap)

    await db.refresh(source)
    assert source.answered is True
    stored = await db.get(Message, uuid.UUID(body["sent_message_id"]))
    assert stored is not None
    assert stored.mailbox_id == mailbox.id
