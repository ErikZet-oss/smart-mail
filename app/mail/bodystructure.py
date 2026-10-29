"""Paperclip from the IMAP BODYSTRUCTURE, before a message was ever opened (issue #52, Roundcube parity).

`ensure_body` stays authoritative: the first open overwrites the flag with `has_file_attachments(parsed)`. Until then
the list uses this structural guess. The rule is the one of #51 / B9: images shown inside the body (`multipart/
related` parts with a Content-ID, inline images) are not attachments, and when unsure the answer is *no* paperclip.
"""

from __future__ import annotations

from typing import Any

# Position of the disposition in a single-part BODYSTRUCTURE (RFC 3501 §7.4.2, extension data):
# basic: type subtype params id description encoding size | md5 disposition …
# text:  … size lines | md5 disposition …
# message/rfc822: … size envelope body lines | md5 disposition …
_DISPOSITION_AT = {"text": 9, "message/rfc822": 11}
_BASIC_DISPOSITION_AT = 8


def _s(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("ascii", errors="replace").lower()
    return str(value).lower() if value is not None else ""


def _param(params: object, name: str) -> str | None:
    """Value of `name` in a flat (key, value, key, value, …) parameter list."""
    if not isinstance(params, (tuple, list)):
        return None
    items = list(params)
    for key, value in zip(items[::2], items[1::2], strict=False):
        if _s(key) == name:
            return _s(value) or None
    return None


def _leaf_is_file(part: Any, *, in_related: bool) -> bool:
    mtype, subtype = _s(part[0]), _s(part[1])
    if f"{mtype}/{subtype}" == "message/rfc822":
        return True  # a forwarded .eml is a file for the user
    at = _DISPOSITION_AT.get(f"{mtype}/{subtype}", _DISPOSITION_AT.get(mtype, _BASIC_DISPOSITION_AT))
    disposition = part[at] if len(part) > at else None
    kind, disp_params = (None, None)
    if isinstance(disposition, (tuple, list)) and disposition:
        kind, disp_params = _s(disposition[0]), (disposition[1] if len(disposition) > 1 else None)
    content_id = part[3] if len(part) > 3 else None
    filename = _param(disp_params, "filename") or _param(part[2], "name")
    if in_related and content_id:
        return False  # shown inside the HTML body (signature logo, banner)
    if kind == "attachment":
        return True
    if kind == "inline" and mtype == "image":
        return False
    if mtype == "text" and subtype in {"plain", "html"} and not filename:
        return False  # the body itself
    return bool(filename)


def _walk(node: Any, *, in_related: bool) -> bool:
    if getattr(node, "is_multipart", False):
        parts, subtype = node[0], _s(node[1])
        related = in_related or subtype == "related"
        return any(_walk(part, in_related=related) for part in parts)
    return _leaf_is_file(node, in_related=in_related)


def has_file_attachments_structure(bodystructure: Any) -> bool:
    """True when a part is a file the user would see as an attachment. Unknown or malformed structures → False."""
    if bodystructure is None:
        return False
    try:
        return _walk(bodystructure, in_related=False)
    except (IndexError, TypeError, ValueError):
        return False
