"""RFC 6266/5987 Content-Disposition for non-ASCII attachment names (Phase 1h follow-up)."""

from __future__ import annotations

from app.core.content_disposition import (
    ascii_filename_fallback,
    content_disposition_attachment,
    sanitize_download_filename,
)


def test_disposition_objednavka_diacritics() -> None:
    name = "Objednávka č. 12.pdf"
    header = content_disposition_attachment(name)
    assert header.encode("latin-1")  # must not raise
    assert header.startswith('attachment; filename="')
    assert "filename*=UTF-8''Objedn%C3%A1vka%20%C4%8D.%2012.pdf" in header
    fallback = ascii_filename_fallback(sanitize_download_filename(name))
    assert fallback == "Objedn_vka _. 12.pdf"
    assert fallback.isascii()


def test_disposition_trencin() -> None:
    name = "Ponuka_Trenčín.pdf"
    header = content_disposition_attachment(name)
    assert header.encode("latin-1")
    assert "filename*=UTF-8''Ponuka_Tren%C4%8D%C3%ADn.pdf" in header
    assert ascii_filename_fallback(name) == "Ponuka_Tren__n.pdf"


def test_disposition_strips_quotes_and_newlines() -> None:
    name = 'evil"name\nwith\rbreak.pdf'
    cleaned = sanitize_download_filename(name)
    assert '"' not in cleaned
    assert "\n" not in cleaned
    assert "\r" not in cleaned
    assert cleaned == "evilnamewithbreak.pdf"
    header = content_disposition_attachment(name)
    assert header.encode("latin-1")
    assert "\n" not in header
    assert "\r" not in header
    # legacy filename is a single quoted token — no embedded quote
    legacy = header.split("filename*=", 1)[0]
    assert legacy.count('"') == 2
