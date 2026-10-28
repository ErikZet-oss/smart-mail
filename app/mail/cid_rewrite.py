"""Rewrite cid: image URLs to same-origin inline attachment URLs (pilot #18 B5)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import quote

_CID_SRC = re.compile(
    r"(?P<pre><img\b[^>]*?\bsrc\s*=\s*)(?P<q>[\"'])cid:(?P<cid>[^\"']+)(?P=q)",
    re.IGNORECASE,
)


def normalize_cid(value: str) -> str:
    return value.strip().strip("<>").strip()


def rewrite_cid_images(
    html: str,
    *,
    mailbox_ref: str,
    cid_to_attachment_id: Mapping[str, str],
) -> str:
    """Replace src=\"cid:…\" with /api/mail/mailboxes/{ref}/attachments/{id}/inline."""

    def repl(match: re.Match[str]) -> str:
        cid = normalize_cid(match.group("cid"))
        att_id = cid_to_attachment_id.get(cid)
        if not att_id:
            # Also try case-insensitive match
            lower = {k.lower(): v for k, v in cid_to_attachment_id.items()}
            att_id = lower.get(cid.lower())
        if not att_id:
            return match.group(0)
        ref = quote(mailbox_ref, safe="")
        url = f"/api/mail/mailboxes/{ref}/attachments/{att_id}/inline"
        q = match.group("q")
        return f"{match.group('pre')}{q}{url}{q}"

    return _CID_SRC.sub(repl, html)
