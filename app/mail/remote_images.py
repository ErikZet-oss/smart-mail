"""Remote image placeholders → signed proxy URLs at render time (pilot #18 B6)."""

from __future__ import annotations

import re
from typing import Literal

from app.core.config import Settings
from app.mail.image_proxy import proxy_path
from app.mail.sanitize import REMOTE_PLACEHOLDER

RemoteMode = Literal["never", "known", "always"]

_DATA_REMOTE = re.compile(
    r'(data-remote-src=)(?P<q>["\'])(?P<url>https?://[^"\']+)(?P=q)',
    re.IGNORECASE,
)


def sender_is_known(*, from_email: str | None, contact_emails: set[str], internal_domains: list[str]) -> bool:
    """Known = address book contact or internal company domain."""
    if not from_email or "@" not in from_email:
        return False
    address = from_email.strip().lower()
    if address in contact_emails:
        return True
    domain = address.rsplit("@", 1)[-1]
    return any(domain == d.strip().lower() for d in internal_domains if d.strip())


def should_offer_remote_images(
    mode: RemoteMode,
    *,
    from_email: str | None,
    contact_emails: set[str],
    internal_domains: list[str],
) -> bool:
    if mode == "never":
        return False
    if mode == "always":
        return True
    return sender_is_known(from_email=from_email, contact_emails=contact_emails, internal_domains=internal_domains)


def sign_remote_image_attrs(html: str, settings: Settings) -> str:
    """Replace data-remote-src https URLs with same-origin signed proxy paths."""

    def repl(match: re.Match[str]) -> str:
        url = match.group("url")
        q = match.group("q")
        return f"{match.group(1)}{q}{proxy_path(settings, url)}{q}"

    return _DATA_REMOTE.sub(repl, html)


def html_has_remote_placeholder(html: str | None) -> bool:
    return bool(html and REMOTE_PLACEHOLDER in html)
