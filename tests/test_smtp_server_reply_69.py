"""Issue #69: a refused send keeps the SMTP server's reply (code + one-line text, ≤ 200 chars) in SmtpError.reason
and in the `smtp.send_failed` log — never anything of the message itself."""

from __future__ import annotations

from email.message import EmailMessage
from typing import Any

import pytest
from aiosmtplib import SMTPDataError, SMTPSenderRefused

from app.core.config import Settings
from app.mail import smtp
from app.mail.smtp import REPLY_MAX, SmtpError, send_message, server_reply_reason


def _message() -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = "nitra@smartsro.sk"
    msg["To"] = "jana@smartmail.test"
    msg["Subject"] = "Tajný predmet"
    msg.set_content("Tajné telo správy")
    return msg


async def _send_failing(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> SmtpError:
    async def boom(*_: Any, **__: Any) -> None:
        raise exc

    monkeypatch.setattr(smtp.aiosmtplib, "send", boom)
    monkeypatch.setattr(smtp, "assert_send_allowed", lambda *_a, **_k: None)
    with pytest.raises(SmtpError) as info:
        await send_message(Settings(), _message(), host="smtp.example.test", port=587)
    return info.value


async def test_69_reason_keeps_code_and_server_text(monkeypatch: pytest.MonkeyPatch) -> None:
    exc = SMTPSenderRefused(550, "Sending mail from your country (de) is not allowed", "nitra@smartsro.sk")
    logs: list[dict[str, Any]] = []

    class _Log:  # structlog caches bound loggers across the suite, so capture_logs() is order-dependent
        def warning(self, event: str, **kw: Any) -> None:
            logs.append({"event": event, **kw})

    monkeypatch.setattr(smtp, "log", _Log())
    err = await _send_failing(monkeypatch, exc)
    assert err.reason == "SMTPSenderRefused:550:Sending mail from your country (de) is not allowed"
    event = next(e for e in logs if e["event"] == "smtp.send_failed")
    assert event["smtp_code"] == 550
    assert event["smtp_message"] == "Sending mail from your country (de) is not allowed"
    assert "Tajn" not in repr(logs)


def test_69_reply_is_one_line_and_truncated() -> None:
    reason, text = server_reply_reason(SMTPDataError(554, "first line\r\nsecond\tline " + "x" * 400))
    assert "\n" not in reason and "\r" not in reason and "\t" not in reason
    assert reason.startswith("SMTPDataError:554:first line second line x")
    assert len(reason) == REPLY_MAX and len(text) == REPLY_MAX


def test_69_empty_server_text_keeps_the_code() -> None:
    assert server_reply_reason(SMTPDataError(451, ""))[0] == "SMTPDataError:451"
