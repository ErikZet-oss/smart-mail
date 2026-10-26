"""Read-only check of the real mail server (mail2.nameserver.sk) with the dedicated TEST mailbox (Phase 1c risk:
the local Dovecot stands in for it until then).

Runs only when REAL_IMAP_TEST_EMAIL and REAL_IMAP_TEST_PASSWORD are set in `.env` (never in git or chat). Never
used with live mailboxes: eshop@, info@ and branch mailboxes are refused even read-only. Nothing is changed on the
server: folders are opened read-only (EXAMINE) and bodies are not fetched.
"""

from __future__ import annotations

import socket

import pytest
from dotenv import dotenv_values

from app.mail.imap import ImapAuthenticator, ImapServer, LoginResult
from app.mail.sync import Credentials, collect, connect, logout_quietly

_env = {**dotenv_values(".env")}
HOST = _env.get("REAL_IMAP_TEST_HOST") or "mail2.nameserver.sk"
PORT = int(_env.get("REAL_IMAP_TEST_PORT") or 993)
EMAIL = (_env.get("REAL_IMAP_TEST_EMAIL") or "").strip().lower()
PASSWORD = _env.get("REAL_IMAP_TEST_PASSWORD") or ""
LIVE_LOCAL_PARTS = frozenset({"eshop", "info", "nitra", "senica", "trencin", "trenčín", "smart", "objednavky"})

pytestmark = [
    pytest.mark.real_mailbox,
    pytest.mark.skipif(
        not (EMAIL and PASSWORD),
        reason="no TEST mailbox for mail2.nameserver.sk in .env (REAL_IMAP_TEST_EMAIL / REAL_IMAP_TEST_PASSWORD) — "
        "the customer provides it before Phase 1f; until then only the local test server is used",
    ),
]


@pytest.fixture(scope="module", autouse=True)
def refuse_live_mailboxes() -> None:
    local = EMAIL.partition("@")[0]
    if local in LIVE_LOCAL_PARTS:
        pytest.fail(f"{EMAIL} is a live mailbox — only the dedicated TEST mailbox may be used")


def server() -> ImapServer:
    return ImapServer(HOST, PORT, "ssl" if PORT == 993 else "starttls", 15)


async def test_real_server_login_like_roundcube() -> None:
    assert await ImapAuthenticator(server()).verify(EMAIL, PASSWORD) is LoginResult.ok


def test_real_server_capabilities_folders_and_quota_read_only() -> None:
    client = connect(server(), Credentials(EMAIL, PASSWORD))
    try:
        snap = collect(client, {}, "inbox", 200)
    finally:
        logout_quietly(client)
    assert "IDLE" in snap.capabilities, "the INBOX watcher needs IDLE (else only the 2-min poll)"
    assert "inbox" in snap.special.values()
    assert snap.folders and snap.folders[0].messages >= 0
    if "QUOTA" in snap.capabilities:
        assert snap.quota_limit_kb is not None


def test_real_server_managesieve_port_answers() -> None:
    """Filtre / Mimo kancelárie (Phase 1f) need ManageSieve on 4190; only the greeting is read, no login."""
    with socket.create_connection((HOST, 4190), timeout=10) as sock:
        greeting = sock.recv(4096).decode("utf-8", errors="replace")
    assert '"IMPLEMENTATION"' in greeting.upper() or "SIEVE" in greeting.upper()
