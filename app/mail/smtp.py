"""Outbound SMTP via aiosmtplib (Phase 1e/1f / GitHub #20).

Pilot / production: authenticate with the mailbox password (same Fernet secret as IMAP, D27).
Dev/CI against Mailpit may omit credentials; against imap-test submission AUTH is mandatory.
Never logs bodies or credentials.
"""

from __future__ import annotations

from email.message import EmailMessage
from typing import Literal

import aiosmtplib
import structlog
from aiosmtplib import SMTPAuthenticationError, SMTPResponseException

from app.core.config import Settings
from app.mail.models import Mailbox
from app.mail.send_guard import SendGuardError, assert_send_allowed

log = structlog.get_logger(__name__)

Security = Literal["ssl", "starttls", "none"]


class SmtpError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def smtp_endpoint(mailbox: Mailbox, settings: Settings) -> tuple[str, int, Security]:
    """Host/port/security from the mailbox row, else app env (SMTP_*)."""
    host = (mailbox.smtp_host or settings.smtp_host).strip()
    port = int(mailbox.smtp_port if mailbox.smtp_port is not None else settings.smtp_port)
    raw = (mailbox.smtp_security or settings.smtp_security or "none").strip().lower()
    security: Security = raw if raw in {"ssl", "starttls", "none"} else "none"  # type: ignore[assignment]
    return host, port, security


async def send_message(
    settings: Settings,
    message: EmailMessage,
    *,
    host: str | None = None,
    port: int | None = None,
    security: Security | None = None,
    username: str | None = None,
    password: str | None = None,
    mail_from: str | None = None,
) -> None:
    host = host or settings.smtp_host
    port = port if port is not None else settings.smtp_port
    security = security or settings.smtp_security
    try:
        assert_send_allowed(settings, message, host=host)
    except SendGuardError as exc:
        log.warning("smtp.guard_blocked", code=exc.code)
        # Keep blocked addresses in the reason so the compose UI can show them (pilot #18 B7).
        reason = f"{exc.code}:{exc.detail}" if exc.detail else exc.code
        raise SmtpError(reason) from exc
    use_tls = security == "ssl"
    start_tls = security == "starttls"
    sender = mail_from or message.get("From")
    try:
        await aiosmtplib.send(
            message,
            sender=sender,
            hostname=host,
            port=port,
            username=username,
            password=password,
            use_tls=use_tls,
            start_tls=start_tls,
            timeout=30,
        )
    except SMTPAuthenticationError as exc:
        log.warning("smtp.auth_failed", error_type=type(exc).__name__)
        raise SmtpError("auth_failed") from exc
    except SMTPResponseException as exc:
        # 535 is auth; other permanent failures stay typed for the UI
        if exc.code == 535:
            log.warning("smtp.auth_failed", smtp_code=exc.code)
            raise SmtpError("auth_failed") from exc
        log.warning("smtp.send_failed", error_type=type(exc).__name__, smtp_code=exc.code)
        raise SmtpError(type(exc).__name__) from exc
    except aiosmtplib.SMTPException as exc:
        log.warning("smtp.send_failed", error_type=type(exc).__name__)
        raise SmtpError(type(exc).__name__) from exc
    except (TimeoutError, OSError) as exc:
        log.warning("smtp.unavailable", error_type=type(exc).__name__)
        raise SmtpError("server_unavailable") from exc
