"""IMAP access (CLAUDE.md §5). Phase 1a: verifying a mailbox login exactly like Roundcube does (LOGIN over TLS)."""

from __future__ import annotations

import asyncio
import enum
import ssl
from dataclasses import dataclass
from typing import Protocol

import structlog
from imapclient import IMAPClient
from imapclient.exceptions import IMAPClientError, LoginError

from app.core.config import Settings

log = structlog.get_logger(__name__)


class LoginResult(enum.Enum):
    ok = "ok"
    invalid_credentials = "invalid_credentials"
    server_unavailable = "server_unavailable"


@dataclass(frozen=True)
class ImapServer:
    host: str
    port: int
    security: str  # ssl | starttls | none
    timeout_s: int

    @classmethod
    def from_settings(cls, settings: Settings) -> ImapServer:
        return cls(
            settings.imap_login_host,
            settings.imap_login_port,
            settings.imap_login_security,
            settings.imap_login_timeout_s,
        )


class MailAuthenticator(Protocol):
    async def verify(self, email: str, password: str) -> LoginResult: ...


class ImapAuthenticator:
    """Checks the credentials against the mail server. The password is never logged or stored by this class."""

    def __init__(self, server: ImapServer, ssl_context: ssl.SSLContext | None = None) -> None:
        self.server = server
        self.ssl_context = ssl_context or ssl.create_default_context()

    def _verify_sync(self, email: str, password: str) -> LoginResult:
        s = self.server
        try:
            client = IMAPClient(
                s.host,
                port=s.port,
                ssl=s.security == "ssl",
                ssl_context=self.ssl_context,
                timeout=s.timeout_s,
            )
        except (OSError, IMAPClientError) as exc:
            log.warning("imap.connect_failed", host=s.host, error=type(exc).__name__)
            return LoginResult.server_unavailable
        try:
            if s.security == "starttls":
                client.starttls(self.ssl_context)
            client.login(email, password)
            return LoginResult.ok
        except LoginError:
            return LoginResult.invalid_credentials
        except (OSError, IMAPClientError) as exc:
            log.warning("imap.login_failed", host=s.host, error=type(exc).__name__)
            return LoginResult.server_unavailable
        finally:
            try:
                client.logout()
            except (OSError, IMAPClientError):
                pass

    async def verify(self, email: str, password: str) -> LoginResult:
        try:
            async with asyncio.timeout(self.server.timeout_s + 2):
                return await asyncio.to_thread(self._verify_sync, email, password)
        except TimeoutError:
            log.warning("imap.timeout", host=self.server.host)
            return LoginResult.server_unavailable
