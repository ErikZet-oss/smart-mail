"""GitHub #20 — SMTP AUTH with mailbox credentials + APPEND to \\Sent.

Requires the local Dovecot `imap-test` with submission on TEST_SMTP_PORT (CI: 1587 → 587).
Without AUTH the send must fail; with the mailbox password it must succeed and the message
must appear in the IMAP Sent folder (SPECIAL-USE \\Sent).
"""

from __future__ import annotations

import os
import subprocess
import sys
from email.message import EmailMessage
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role
from app.auth.security import encrypt
from app.core.config import Settings
from app.mail.compose import execute_send
from app.mail.compose_models import ComposeDraft, Identity
from app.mail.imap import ImapAuthenticator, ImapServer
from app.mail.imap_append import append_to_sent, resolve_special_folder
from app.mail.models import Mailbox
from app.mail.smtp import SmtpError, send_message, smtp_endpoint
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


def _mime(*, subject: str = "Issue 20 SMTP") -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = f"Pilot <{PILOT_EMAIL}>"
    msg["To"] = "sender@smartmail.test"
    msg["Subject"] = subject
    msg.set_content("Ahoj z CI testu issue 20.")
    return msg


@pytest.mark.asyncio
async def test_20_smtp_without_auth_fails(settings: Settings) -> None:
    """Submission must refuse unauthenticated send — catches the VPS bug (no username/password)."""
    with pytest.raises(SmtpError):
        await send_message(
            settings,
            _mime(subject="no-auth"),
            host=SMTP_HOST or HOST,
            port=SMTP_PORT,
            security="none",
            username=None,
            password=None,
            mail_from=PILOT_EMAIL,
        )


@pytest.mark.asyncio
async def test_20_smtp_with_mailbox_auth_succeeds_and_sent_has_message(
    settings: Settings, db: AsyncSession, client: Client, app
) -> None:
    """AUTH with mailbox password works; execute_send APPENDs to \\Sent (visible over IMAP)."""
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

    host, port, sec = smtp_endpoint(mailbox, app.state.settings)
    assert (host, port, sec) == (SMTP_HOST or HOST, SMTP_PORT, "none")

    created = await client.send_json("POST", "/api/mail/mailboxes/default/compose", {"mode": "new"})
    assert created.status_code == 200, created.text
    draft_id = created.json()["id"]
    subject = "Issue20 auth-ok"
    patched = await client.send_json(
        "PATCH",
        f"/api/mail/compose/{draft_id}",
        {
            "to_addrs": [{"email": "sender@smartmail.test"}],
            "subject": subject,
            "body_html": "<p>Ahoj</p>",
        },
    )
    assert patched.status_code == 200, patched.text

    sent = await client.send_json("POST", f"/api/mail/compose/{draft_id}/send", {"force": False})
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "sent", sent.text

    creds = Credentials(PILOT_EMAIL, PILOT_PASSWORD)
    server = server_of(mailbox, app.state.settings)
    imap = connect(server, creds)
    try:
        folder = resolve_special_folder(imap, special=b"\\Sent", fallbacks=("Sent", "Odoslané"))
        imap.select_folder(folder)
        uids = imap.search(["SUBJECT", subject])
        assert uids, f"sent message not found in {folder!r}"
    finally:
        logout_quietly(imap)


@pytest.mark.asyncio
async def test_20_execute_send_auth_failed_marks_mailbox(settings: Settings, db: AsyncSession) -> None:
    acc = await make_personal(db, email="pilot-bad@smartmail.test", role=Role.sales)
    acc.mailbox_password_enc = encrypt(settings, "wrong-password")
    await db.flush()
    mailbox = Mailbox(
        email=PILOT_EMAIL,
        imap_host=HOST,
        imap_port=IMAP_PORT,
        imap_security="none",
        smtp_host=SMTP_HOST or HOST,
        smtp_port=SMTP_PORT,
        smtp_security="none",
        credential_account_id=acc.id,
        sync_state="ok",
    )
    db.add(mailbox)
    await db.flush()
    identity = Identity(mailbox_id=mailbox.id, display_name="Pilot", email=PILOT_EMAIL, is_default=True)
    db.add(identity)
    await db.flush()
    draft = ComposeDraft(
        mailbox_id=mailbox.id,
        account_id=acc.id,
        identity_id=identity.id,
        to_addrs=[{"email": "sender@smartmail.test"}],
        subject="auth-fail",
        body_html="<p>x</p>",
        body_text="x",
        status="queued",
    )
    db.add(draft)
    await db.commit()

    result = await execute_send(db, settings, draft.id)
    assert result == "failed"
    await db.refresh(draft)
    await db.refresh(mailbox)
    assert draft.send_error == "auth_failed"
    assert mailbox.sync_state == "auth_failed"


def test_20_append_to_sent_unit_against_imap(settings: Settings) -> None:
    creds = Credentials(PILOT_EMAIL, PILOT_PASSWORD)
    server = ImapServer(HOST, IMAP_PORT, "none", 10)
    append_to_sent(server, creds, _mime(subject="append-only-20"))
    client = connect(server, creds)
    try:
        folder = resolve_special_folder(client, special=b"\\Sent", fallbacks=("Sent",))
        client.select_folder(folder)
        assert client.search(["SUBJECT", "append-only-20"])
    finally:
        logout_quietly(client)
