"""Thread keys for listing in Konverzácie mode (CLAUDE.md §5).

Prefer Message-ID graph (In-Reply-To / first References id); else normalized subject + sorted participants,
bucketed by 30-day windows so unrelated mail with the same subject does not merge forever.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime

_PREFIX = re.compile(
    r"^\s*((re|fw|fwd|aw|sv|odp|odpoved|antwort)\s*(\[\d+\])?\s*:\s*)+",
    re.IGNORECASE,
)
_WS = re.compile(r"\s+")


def normalize_subject(subject: str | None) -> str:
    text = (subject or "").strip()
    while True:
        next_text = _PREFIX.sub("", text, count=1)
        if next_text == text:
            break
        text = next_text.strip()
    return _WS.sub(" ", text).casefold()


def _clean_msgid(value: str | None) -> str | None:
    if not value:
        return None
    # take the first angle-addr if several are present
    match = re.search(r"<[^>]+>", value)
    token = match.group(0) if match else value.strip()
    return token.casefold() or None


@dataclass(frozen=True)
class ThreadKey:
    kind: str  # msgid | fallback
    value: str


def thread_key_for(
    *,
    message_id: str | None,
    in_reply_to: str | None,
    references: str | None,
    subject: str | None,
    from_email: str | None,
    to_emails: list[str],
    sent_at: datetime | None,
) -> ThreadKey:
    # Prefer the Message-ID graph: replies key on the root id (In-Reply-To / first References);
    # a root message keys on its own Message-ID so later replies join the same thread.
    root = _clean_msgid(in_reply_to)
    if root is None and references:
        first = next((p for p in references.split() if p), None)
        root = _clean_msgid(first)
    if root is None:
        root = _clean_msgid(message_id)
    if root is not None:
        return ThreadKey("msgid", root)

    # Time window (30 days) is applied when linking to an existing thread (`last_message_at`), not in the key —
    # absolute day-buckets would split a conversation that spans a bucket boundary.
    del sent_at  # kept in the signature for call sites / future windowing helpers
    people = sorted({(from_email or "").casefold(), *(e.casefold() for e in to_emails if e)})
    raw = f"{normalize_subject(subject)}|{','.join(people)}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:32]
    return ThreadKey("fallback", digest)
