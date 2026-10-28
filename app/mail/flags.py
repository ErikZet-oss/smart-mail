"""Local flag bits that the message list renders without waiting for the next poll."""

from __future__ import annotations

from collections.abc import Sequence

from app.mail.models import Message

ANSWERED_FLAG = "\\Answered"
FORWARDED_FLAG = "$Forwarded"


def is_forwarded(flags: Sequence[str] | None) -> bool:
    return any(str(flag).casefold() == FORWARDED_FLAG.casefold() for flag in flags or [])


def apply_local_flag(message: Message, flag: str) -> None:
    """Record an IMAP flag we just stored, so the list icon updates on the next fetch."""
    current = [str(item) for item in (message.flags or [])]
    if not any(item.casefold() == flag.casefold() for item in current):
        current.append(flag)
    message.flags = current
    if flag.casefold() == ANSWERED_FLAG.casefold():
        message.answered = True
