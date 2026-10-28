"""RFC822 parsing for the reading pane (Phase 1d / SCREENS_SPEC W2c)."""

from __future__ import annotations

import re
from email.message import EmailMessage

from app.mail.parse import parse_rfc822
from app.mail.sanitize import REMOTE_PLACEHOLDER


def _raw(msg: EmailMessage) -> bytes:
    return msg.as_bytes()


def test_parse_1d_plain_text_body_and_preview() -> None:
    msg = EmailMessage()
    msg["Subject"] = "Objednávka"
    msg["From"] = "Peter <peter@example.test>"
    msg.set_content("Dobrý deň,\nprosím o potvrdenie.\n")
    parsed = parse_rfc822(_raw(msg))
    assert parsed.body_text is not None and "potvrdenie" in parsed.body_text
    assert parsed.body_html_sanitized is None
    assert parsed.preview is not None and "potvrdenie" in parsed.preview
    assert parsed.attachments == []


def test_parse_1d_keep_src_on_received_mail_is_blocked() -> None:
    msg = EmailMessage()
    msg["Subject"] = "Sledovanie"
    msg.set_content("plain")
    msg.add_alternative(
        '<img src="https://evil.example/x.png" data-sm-keep-src="1" data-cid="x">',
        subtype="html",
    )
    parsed = parse_rfc822(_raw(msg))
    assert parsed.body_html_sanitized is not None
    assert REMOTE_PLACEHOLDER in parsed.body_html_sanitized
    assert "data-sm-keep-src" not in parsed.body_html_sanitized
    assert "data-cid" not in parsed.body_html_sanitized
    assert re.search(r'(?<![\w-])src="https://', parsed.body_html_sanitized) is None


def test_parse_1d_html_is_sanitized_and_remote_images_blocked() -> None:
    msg = EmailMessage()
    msg["Subject"] = "HTML"
    msg.set_content("plain fallback")
    msg.add_alternative(
        '<p>Ahoj</p><script>x()</script><img src="https://tracker.example/p.gif">',
        subtype="html",
    )
    parsed = parse_rfc822(_raw(msg))
    assert parsed.body_html_sanitized is not None
    assert "script" not in parsed.body_html_sanitized.lower()
    assert REMOTE_PLACEHOLDER in parsed.body_html_sanitized
    assert "Ahoj" in parsed.body_html_sanitized
    assert parsed.preview == "plain fallback"


def test_parse_1d_attachment_parts() -> None:
    msg = EmailMessage()
    msg["Subject"] = "S prílohou"
    msg.set_content("text")
    msg.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="faktura.pdf")
    parsed = parse_rfc822(_raw(msg))
    assert len(parsed.attachments) == 1
    att = parsed.attachments[0]
    assert att.filename == "faktura.pdf"
    assert att.content_type == "application/pdf"
    assert att.payload.startswith(b"%PDF")
    assert att.is_inline is False


def test_parse_1d_auth_results_spf_dkim_dmarc() -> None:
    msg = EmailMessage()
    msg["Subject"] = "Auth"
    msg["Authentication-Results"] = "mx; spf=pass smtp.mailfrom=a; dkim=fail; dmarc=pass"
    msg.set_content("ok")
    parsed = parse_rfc822(_raw(msg))
    assert parsed.auth_results == {"spf": "pass", "dkim": "fail", "dmarc": "pass"}
