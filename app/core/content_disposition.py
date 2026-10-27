"""RFC 6266 / RFC 5987 Content-Disposition for file downloads.

Starlette encodes response headers as latin-1; non-ASCII filenames (č, š, ž, ľ, …)
must use `filename*` (UTF-8 percent-encoded) with an ASCII `filename` fallback.
"""

from __future__ import annotations

from urllib.parse import quote


def content_disposition_attachment(filename: str) -> str:
    """Build `attachment; filename="<ascii>"; filename*=UTF-8''<pct>` (RFC 6266 §4.3)."""
    cleaned = sanitize_download_filename(filename)
    ascii_name = ascii_filename_fallback(cleaned)
    encoded = quote(cleaned, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"


def sanitize_download_filename(filename: str) -> str:
    """Strip quotes and newlines that would break or inject into the header."""
    cleaned = filename.replace('"', "").replace("\r", "").replace("\n", "").strip()
    return cleaned or "download"


def ascii_filename_fallback(filename: str) -> str:
    """ASCII-only name for the legacy `filename` parameter (latin-1 safe)."""
    out: list[str] = []
    for ch in filename:
        code = ord(ch)
        if 0x20 <= code <= 0x7E and ch not in {"\\", '"', ";", "%"}:
            out.append(ch)
        else:
            out.append("_")
    result = "".join(out).strip("._ ") or "download"
    return result
