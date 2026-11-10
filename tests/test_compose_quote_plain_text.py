"""Pilot 2026-11-10: replying to a plain-text mail joined the whole quoted text into one paragraph."""

from __future__ import annotations

import uuid

from app.core.config import Settings
from app.mail.compose import quote_html_for_message
from app.mail.models import Message


def test_plain_text_quote_keeps_line_breaks_and_escapes() -> None:
    source = Message(
        mailbox_id=uuid.uuid4(),
        folder_id=uuid.uuid4(),
        uid=1,
        body_html_sanitized=None,
        body_text="Dobrý deň,\n\n1. Cena modulov\n- verzia 1.17.9\n<script>x</script>\nS pozdravom",
    )
    quote = quote_html_for_message(Settings(), source)
    assert quote is not None
    assert quote.startswith('<pre style="white-space:pre-wrap;font-family:inherit">')
    assert "Dobrý deň,\n\n1. Cena modulov\n- verzia 1.17.9" in quote
    assert "<script>" not in quote and "&lt;script&gt;" in quote
