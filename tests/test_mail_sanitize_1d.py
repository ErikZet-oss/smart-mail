"""HTML sanitizer for message bodies (CLAUDE.md §5, SCREENS_SPEC W2c, DECISIONS D22 for signature rules reused).

Keeps safe tags/tables/inline styles/img; strips script/iframe/form/on* handlers/javascript: URLs; remote images
are rewritten to a placeholder so the UI can offer "Zobraziť obrázky".
"""

from __future__ import annotations

import pytest

from app.mail.sanitize import REMOTE_PLACEHOLDER, sanitize_html


def test_sanitize_1d_strips_script_and_iframe() -> None:
    html = '<p>Ahoj</p><script>alert(1)</script><iframe src="https://evil.example"></iframe>'
    out = sanitize_html(html)
    assert "script" not in out.lower()
    assert "iframe" not in out.lower()
    assert "Ahoj" in out


def test_sanitize_1d_strips_on_handlers_and_javascript_urls() -> None:
    html = '<a href="javascript:alert(1)" onclick="evil()">klik</a><p onmouseover="x()">x</p>'
    out = sanitize_html(html)
    assert "javascript:" not in out.lower()
    assert "onclick" not in out.lower()
    assert "onmouseover" not in out.lower()


def test_sanitize_1d_keeps_tables_and_inline_styles() -> None:
    html = (
        '<table style="border-collapse:collapse"><tr><td style="color:#333">riadok</td></tr></table>'
        '<p style="font-family:Arial">text</p>'
    )
    out = sanitize_html(html)
    assert "<table" in out
    assert "riadok" in out
    assert "font-family" in out or "Arial" in out


def test_sanitize_1d_remote_images_become_placeholders() -> None:
    html = '<p>Hi</p><img src="https://tracker.example/pixel.gif" alt="x"><img src="cid:logo@local">'
    out = sanitize_html(html)
    assert f'src="{REMOTE_PLACEHOLDER}"' in out
    assert 'data-remote-src="https://tracker.example/pixel.gif"' in out
    assert "cid:logo@local" in out
    assert out.count("https://tracker.example") == 1  # only in data-remote-src, not in src


def test_sanitize_1d_cid_and_data_images_kept() -> None:
    html = '<img src="data:image/png;base64,aaa" alt="d"><img src="cid:part1">'
    out = sanitize_html(html)
    assert "data:image/png" in out
    assert "cid:part1" in out


def test_sanitize_1d_empty_and_plain() -> None:
    assert sanitize_html("") == ""
    assert sanitize_html("len text") == "len text"


def test_sanitize_1d_size_limit_truncates() -> None:
    huge = "<p>" + ("x" * 200_000) + "</p>"
    out = sanitize_html(huge, max_bytes=64_000)
    assert len(out.encode()) <= 64_000 + 200  # small headroom for truncation marker


@pytest.mark.parametrize(
    "bad",
    [
        '<form action="/"><input name="p"></form>',
        "<object data='x'></object>",
        "<embed src='x'>",
        '<base href="https://evil.example/">',
        '<meta http-equiv="refresh" content="0;url=https://evil.example">',
    ],
)
def test_sanitize_1d_strips_dangerous_tags(bad: str) -> None:
    out = sanitize_html(f"<p>ok</p>{bad}")
    assert "ok" in out
    for tag in ("form", "input", "object", "embed", "base", "meta"):
        assert f"<{tag}" not in out.lower()
