"""Outbound send guard (Phase 1f) — mirrors the IMAP sync host guard.

Outside APP_ENV=prod, Smart Mail never talks to a live SMTP server or real customer
addresses unless explicitly opted in. Recipients stay limited to @smartmail.test and
MAIL_SEND_TEST_ALLOWLIST even when MAIL_SEND_ALLOW_REAL_SERVER is true.
"""

from __future__ import annotations

from email.message import EmailMessage
from email.utils import getaddresses

from app.core.config import Settings

# Docker Compose Mailpit + loopback. "imap-test" is accepted as a compose-network alias
# only when someone mis-points SMTP at the IMAP service hostname by mistake in docs —
# the real test SMTP service is mailpit.
TEST_SMTP_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "mailpit", "imap-test"})


class SendGuardError(Exception):
    def __init__(self, code: str, *, detail: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


def _parse_allowlist(raw: str) -> set[str]:
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def smtp_host_allowed(settings: Settings, host: str) -> bool:
    """Same shape as Settings.sync_host_allowed: prod, opt-in, or local test SMTP."""
    if settings.app_env == "prod":
        return True
    if settings.mail_send_allow_real_server:
        return True
    return host.strip().lower() in TEST_SMTP_HOSTS


def recipient_allowed(settings: Settings, email: str) -> bool:
    """Outside prod only @smartmail.test and MAIL_SEND_TEST_ALLOWLIST may receive mail."""
    if settings.app_env == "prod":
        return True
    address = email.strip().lower()
    if not address or "@" not in address:
        return False
    if address.endswith("@smartmail.test"):
        return True
    return address in _parse_allowlist(settings.mail_send_test_allowlist)


def test_allowlist_addresses(settings: Settings) -> list[str]:
    """Sorted addresses from MAIL_SEND_TEST_ALLOWLIST (for API/UI copy when APP_ENV=test)."""
    return sorted(_parse_allowlist(settings.mail_send_test_allowlist))


def blocked_recipients(settings: Settings, emails: list[str]) -> list[str]:
    """Addresses that would be rejected by the outbound send guard (pilot #18 B7)."""
    return sorted({addr.strip().lower() for addr in emails if addr and not recipient_allowed(settings, addr)})


def collect_recipients(message: EmailMessage) -> list[str]:
    headers = []
    for key in ("To", "Cc", "Bcc"):
        value = message.get_all(key, failobj=[])
        headers.extend(value)
    return [addr for _, addr in getaddresses(headers) if addr]


def assert_send_allowed(settings: Settings, message: EmailMessage, *, host: str) -> None:
    """Raise SendGuardError before any SMTP connection when the send would leave the sandbox."""
    if not smtp_host_allowed(settings, host):
        raise SendGuardError("smtp_host_not_allowed", detail=host.lower())
    blocked = blocked_recipients(settings, collect_recipients(message))
    if blocked:
        raise SendGuardError("recipient_not_allowed", detail=",".join(blocked))
