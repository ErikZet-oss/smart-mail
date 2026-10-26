"""Outbound SMTP via aiosmtplib (Phase 1e). Dev/CI → Mailpit; never logs bodies or credentials."""

from __future__ import annotations

from email.message import EmailMessage
from typing import Literal

import aiosmtplib
import structlog

from app.core.config import Settings

log = structlog.get_logger(__name__)

Security = Literal["ssl", "starttls", "none"]


class SmtpError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def send_message(
    settings: Settings,
    message: EmailMessage,
    *,
    host: str | None = None,
    port: int | None = None,
    security: Security | None = None,
    username: str | None = None,
    password: str | None = None,
) -> None:
    host = host or settings.smtp_host
    port = port if port is not None else settings.smtp_port
    security = security or settings.smtp_security
    use_tls = security == "ssl"
    start_tls = security == "starttls"
    try:
        await aiosmtplib.send(
            message,
            hostname=host,
            port=port,
            username=username,
            password=password,
            use_tls=use_tls,
            start_tls=start_tls,
            timeout=30,
        )
    except aiosmtplib.SMTPException as exc:
        log.warning("smtp.send_failed", error_type=type(exc).__name__)
        raise SmtpError(type(exc).__name__) from exc
    except (TimeoutError, OSError) as exc:
        log.warning("smtp.unavailable", error_type=type(exc).__name__)
        raise SmtpError("server_unavailable") from exc
