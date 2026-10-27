"""Vacation Sieve on local imap-test (Dovecot ManageSieve + LMTP): compiled script + real auto-reply.

Runs when TEST_IMAP_HOST is set (CI: ``docker compose up -d --build imap-test``). REQUIRE_IMAP=1 fails the skip.
"""

from __future__ import annotations

import os
import smtplib
import time
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import EmailMessage
from types import SimpleNamespace

import pytest
from imapclient import IMAPClient

from app.core.config import Settings
from app.mail.sieve import (
    VacationSettings,
    apply_vacation_to_script,
    connect_sieve,
    get_script,
    put_script,
    sieve_supports_variables,
)

HOST = os.environ.get("TEST_IMAP_HOST", "")
IMAP_PORT = int(os.environ.get("TEST_IMAP_PORT", "1143"))
SIEVE_PORT = int(os.environ.get("TEST_SIEVE_PORT", "4190"))
LMTP_PORT = int(os.environ.get("TEST_LMTP_PORT", "1024"))

PILOT = "pilot@smartmail.test"
PILOT_PW = "pilot-test-heslo"
SENDER = "sender@smartmail.test"
SENDER_PW = "sender-test-heslo"

pytestmark = [
    pytest.mark.imap,
    pytest.mark.skipif(
        not HOST and os.environ.get("REQUIRE_IMAP") != "1",
        reason="local test IMAP server not configured (set TEST_IMAP_HOST)",
    ),
]


def _settings() -> Settings:
    return Settings(
        app_env="test",
        app_base_url="http://test",
        app_secret_key="test-secret-key-that-is-long-enough-0123456789",
        database_url="postgresql+asyncpg://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
        mail_sync_allow_real_server=True,
    )


def _mailbox() -> SimpleNamespace:
    return SimpleNamespace(
        email=PILOT,
        imap_host=HOST,
        imap_port=IMAP_PORT,
        imap_security="none",
        sieve_host=HOST,
        sieve_port=SIEVE_PORT,
        sieve_enabled=True,
    )


def test_1h_vacation_script_accepted_and_reply_on_imap_test() -> None:
    if not HOST:
        pytest.fail("REQUIRE_IMAP=1 but TEST_IMAP_HOST is empty")

    settings = _settings()
    mailbox = _mailbox()
    client = connect_sieve(settings, mailbox, username=PILOT, password=PILOT_PW)  # type: ignore[arg-type]
    assert sieve_supports_variables(client) is True

    vac = VacationSettings(
        enabled=True,
        subject="Mimo kancelárie: {predmet}",
        body_sk="Som mimo kancelárie (SK test).",
        body_en="I am out of office (EN test).",
        body_de="Ich bin außer Haus (DE test).",
        days=0,  # imap-test allows 0 (sieve_vacation_min_period)
    )
    current = get_script(client, "roundcube") or 'require ["fileinto","vacation"];\n'
    script = apply_vacation_to_script(current, vac, script_name="roundcube", supports_variables=True)
    # Unique :handle so Dovecot's duplicate DB does not suppress re-runs the same day.
    handle = f"sm-test-{time.time_ns()}"
    script = script.replace(
        f"vacation :days {int(vac.days)}",
        f'vacation :days {int(vac.days)} :handle "{handle}"',
        1,
    )
    assert 'set "orig" "${1}"' in script
    assert ':subject "Mimo kancelárie: ${orig}"' in script
    assert "Accept-Language" not in script
    assert script.count("vacation :days") == 1

    assert client.checkscript(script) is True
    put_script(client, "roundcube", script, activate=True)
    client.logout()

    with IMAPClient(HOST, port=IMAP_PORT, ssl=False) as imap:
        imap.login(SENDER, SENDER_PW)
        imap.select_folder("INBOX")
        existing = imap.search(["ALL"])
        if existing:
            imap.delete_messages(existing)
            imap.expunge()

    orig_subject = "Objednávka skrutiek M8"
    msg = EmailMessage()
    msg["From"] = SENDER
    msg["To"] = PILOT
    msg["Subject"] = orig_subject
    msg["Message-ID"] = f"<vacation-test-{time.time_ns()}@smartmail.test>"
    msg.set_content("Prosím o potvrdenie objednávky.")

    with smtplib.LMTP(HOST, LMTP_PORT) as lmtp:
        lmtp.send_message(msg, from_addr=SENDER, to_addrs=[PILOT])

    found_subj = None
    found_body = None
    deadline = time.time() + 15
    while time.time() < deadline:
        with IMAPClient(HOST, port=IMAP_PORT, ssl=False) as imap:
            imap.login(SENDER, SENDER_PW)
            imap.select_folder("INBOX")
            uids = imap.search(["ALL"])
            for uid in uids:
                fetched = imap.fetch([uid], ["RFC822"])
                raw = fetched[uid][b"RFC822"]
                parsed = message_from_bytes(raw)
                found_subj = parsed.get("Subject", "")
                payload = parsed.get_payload(decode=True)
                found_body = (
                    payload.decode("utf-8", errors="replace")
                    if isinstance(payload, bytes)
                    else str(parsed.get_payload())
                )
                if "Som mimo kancelárie (SK test)." in found_body:
                    break
            else:
                time.sleep(0.4)
                continue
            break

    assert found_body is not None and "Som mimo kancelárie (SK test)." in found_body
    assert "I am out of office (EN test)." in found_body
    assert "Ich bin außer Haus (DE test)." in found_body
    assert found_subj is not None
    decoded_subj = str(make_header(decode_header(found_subj)))
    assert orig_subject in decoded_subj
    assert "Mimo kancelárie" in decoded_subj
