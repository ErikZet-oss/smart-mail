"""W2p Hlavičky správy: the header block of the raw message as name/value pairs, in the order of the source.

Folding is kept (continuation lines joined with a newline, leading whitespace collapsed to two spaces) so long
`Received:` lines read like in Roundcube. Only the header block is returned — never the body."""

from __future__ import annotations

from email.header import decode_header, make_header

MAX_HEADER_BYTES = 64 * 1024
MAX_HEADERS = 300


def _decode(value: str) -> str:
    if "=?" not in value:
        return value
    try:
        return str(make_header(decode_header(value)))
    except (UnicodeDecodeError, LookupError, ValueError):
        return value


def header_block(raw: bytes) -> bytes:
    head = raw[:MAX_HEADER_BYTES]
    for sep in (b"\r\n\r\n", b"\n\n"):
        idx = head.find(sep)
        if idx != -1:
            return head[:idx]
    return head


def parse_headers(raw: bytes) -> list[dict[str, str]]:
    text = header_block(raw).decode("utf-8", errors="replace")
    out: list[dict[str, str]] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if not line:
            continue
        if line[0] in " \t":
            if out:
                out[-1]["value"] += "\n  " + line.strip()
            continue
        name, sep, value = line.partition(":")
        if not sep or not name.strip() or " " in name.strip():
            continue  # mbox "From " line or garbage
        if len(out) >= MAX_HEADERS:
            break
        out.append({"name": name.strip(), "value": value.strip()})
    for item in out:
        item["value"] = "\n".join(_decode(part) for part in item["value"].split("\n"))
    return out
