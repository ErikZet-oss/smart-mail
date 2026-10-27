"""vCard 2.1/3.0 parse/serialize for Roundcube-compatible import/export (PRODUCT_SPEC §2.6).

Supports ENCODING=QUOTED-PRINTABLE and CHARSET= (utf-8, windows-1250). Fixtures: @smartmail.test only.
"""

from __future__ import annotations

import quopri
from dataclasses import dataclass, field
from typing import Any


class VCardError(ValueError):
    """Invalid or empty vCard payload."""


class VCardTooLarge(VCardError):
    """Import exceeds size or contact count limit."""


MAX_VCARD_BYTES = 5 * 1024 * 1024
MAX_VCARD_CONTACTS = 5_000

_CHARSETS = {
    "utf-8": "utf-8",
    "utf8": "utf-8",
    "windows-1250": "cp1250",
    "windows1250": "cp1250",
    "cp1250": "cp1250",
}


@dataclass
class ParsedContact:
    display_name: str = ""
    first_name: str | None = None
    last_name: str | None = None
    organization: str | None = None
    notes: str | None = None
    emails: list[dict[str, Any]] = field(default_factory=list)
    phones: list[dict[str, Any]] = field(default_factory=list)


def _unfold(text: str) -> list[str]:
    """RFC 6350 / vCard 2.1 line unfolding (CRLF + space/tab, and QP soft breaks)."""
    raw = text.replace("\r\n", "\n").replace("\r", "\n")
    # Quoted-printable soft line breaks (= at EOL) before structural unfold
    while "=\n" in raw:
        raw = raw.replace("=\n", "")
    lines: list[str] = []
    for line in raw.split("\n"):
        if line.startswith((" ", "\t")) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def _unescape(value: str) -> str:
    return value.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _param_map(params: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in params:
        if "=" in p:
            k, v = p.split("=", 1)
            out[k.upper()] = v
        else:
            out[p.upper()] = ""
    return out


def _decode_value(raw_value: str, params: list[str]) -> str:
    pmap = _param_map(params)
    encoding = (pmap.get("ENCODING") or "").upper()
    charset_key = (pmap.get("CHARSET") or "utf-8").lower()
    charset = _CHARSETS.get(charset_key, "utf-8")
    if encoding in {"QUOTED-PRINTABLE", "QP"}:
        # Soft breaks already removed in _unfold; decode QP then charset.
        try:
            raw_bytes = quopri.decodestring(raw_value.encode("ascii", errors="replace"))
        except Exception as exc:
            raise VCardError("quoted_printable") from exc
        return raw_bytes.decode(charset, errors="replace")
    if charset != "utf-8":
        # Plain value labeled with a non-UTF charset (rare); interpret latin-1 bytes as charset.
        return raw_value.encode("latin-1", errors="replace").decode(charset, errors="replace")
    return _unescape(raw_value.strip())


def _parse_line(line: str) -> tuple[str, list[str], str] | None:
    if not line or line.startswith(" ") or ":" not in line:
        return None
    left, value = line.split(":", 1)
    parts = left.split(";")
    name = parts[0].upper()
    if name.startswith("ITEM") and "." in name:
        name = name.split(".", 1)[1]
    fixed: list[str] = []
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            fixed.append(f"{k.upper()}={v}")
        else:
            fixed.append(p.upper())
    return name, fixed, value


def parse_vcards(text: str, *, max_contacts: int = MAX_VCARD_CONTACTS) -> list[ParsedContact]:
    """Parse one or more BEGIN:VCARD … END:VCARD blocks. Raises VCardError if none are valid."""
    if not text or not text.strip():
        raise VCardError("empty")
    lines = _unfold(text)
    contacts: list[ParsedContact] = []
    current: ParsedContact | None = None
    for line in lines:
        upper = line.strip().upper()
        if upper == "BEGIN:VCARD":
            current = ParsedContact()
            continue
        if upper == "END:VCARD":
            if current is not None:
                if not current.display_name and (current.first_name or current.last_name):
                    current.display_name = " ".join(p for p in (current.first_name, current.last_name) if p).strip()
                if not current.display_name and current.emails:
                    current.display_name = str(current.emails[0].get("email") or "")
                if current.display_name or current.emails:
                    contacts.append(current)
                    if len(contacts) > max_contacts:
                        raise VCardTooLarge("too_many_contacts")
            current = None
            continue
        if current is None:
            continue
        parsed = _parse_line(line)
        if parsed is None:
            continue
        name, params, raw_value = parsed
        try:
            value = _decode_value(raw_value, params)
        except VCardError:
            value = _unescape(raw_value.strip())
        if name == "FN":
            current.display_name = value
        elif name == "N":
            bits = value.split(";")
            current.last_name = bits[0] or None if bits else None
            current.first_name = bits[1] or None if len(bits) > 1 else None
        elif name == "ORG":
            current.organization = value.split(";", 1)[0] or None
        elif name == "NOTE":
            current.notes = value
        elif name == "EMAIL" and value:
            label = "work" if any("WORK" in p for p in params) else "home" if any("HOME" in p for p in params) else None
            primary = any("PREF" in p or p.endswith("=PREF") for p in params) or not current.emails
            current.emails.append({"email": value.lower().strip(), "label": label, "primary": primary})
        elif name == "TEL" and value:
            label = (
                "work"
                if any("WORK" in p for p in params)
                else "cell"
                if any("CELL" in p or "MOBILE" in p for p in params)
                else "home"
                if any("HOME" in p for p in params)
                else None
            )
            current.phones.append({"phone": value, "label": label})
    if not contacts:
        raise VCardError("no_vcards")
    return contacts


def serialize_vcards(contacts: list[ParsedContact]) -> str:
    """Emit vCard 3.0 text suitable for Roundcube import."""
    blocks: list[str] = []
    for c in contacts:
        lines = ["BEGIN:VCARD", "VERSION:3.0"]
        fn = c.display_name or " ".join(p for p in (c.first_name, c.last_name) if p).strip() or "Kontakt"
        lines.append(f"FN:{_escape(fn)}")
        n_last = c.last_name or ""
        n_first = c.first_name or ""
        lines.append(f"N:{_escape(n_last)};{_escape(n_first)};;;")
        if c.organization:
            lines.append(f"ORG:{_escape(c.organization)}")
        if c.notes:
            lines.append(f"NOTE:{_escape(c.notes)}")
        for i, em in enumerate(c.emails):
            email = str(em.get("email") or "").strip()
            if not email:
                continue
            params = ["TYPE=INTERNET"]
            if em.get("label"):
                params.append(f"TYPE={str(em['label']).upper()}")
            if em.get("primary") or i == 0:
                params.append("TYPE=PREF")
            lines.append(f"EMAIL;{';'.join(params)}:{email}")
        for ph in c.phones:
            phone = str(ph.get("phone") or "").strip()
            if not phone:
                continue
            pparams = []
            if ph.get("label"):
                pparams.append(f"TYPE={str(ph['label']).upper()}")
            prefix = f"TEL;{';'.join(pparams)}" if pparams else "TEL"
            lines.append(f"{prefix}:{phone}")
        lines.append("END:VCARD")
        blocks.append("\r\n".join(lines))
    return "\r\n".join(blocks) + ("\r\n" if blocks else "")
