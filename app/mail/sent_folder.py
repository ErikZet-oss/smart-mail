"""Pick the Sent folder sync already knows, else SPECIAL-USE / a Roundcube name, else create one.

Creation uses the IMAP NAMESPACE prefix and delimiter (``INBOX.`` + ``.`` → ``INBOX.Sent``,
empty prefix → ``Sent``). A folder is created only when none of those matches exist.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.mail.folders import FALLBACK_NAMES, ListedFolder

SENT_LEAVES = frozenset(name.casefold() for name in FALLBACK_NAMES["sent"])


def sent_create_name(prefix: str, delimiter: str) -> str:
    """Mailbox name to CREATE when the server has no Sent folder."""
    base = "Sent"
    if not prefix:
        return base
    if delimiter and prefix.endswith(delimiter):
        return f"{prefix}{base}"
    if delimiter:
        return f"{prefix}{delimiter}{base}"
    return f"{prefix}{base}"


def _leaf(name: str, delimiter: str | None) -> str:
    if delimiter and delimiter in name:
        return name.rsplit(delimiter, 1)[-1]
    return name


def _is_sent_flag(flags: frozenset[str]) -> bool:
    return any(flag.casefold() == "\\sent" for flag in flags)


def choose_sent_folder(
    listed: Sequence[ListedFolder],
    *,
    known: str | None,
    prefix: str,
    delimiter: str,
) -> tuple[str, bool]:
    """Return ``(folder name, should_create)``.

    ``known`` is ``folders_meta.name`` where ``special_use='sent'`` — the folder the
    folder list already shows. It wins when it is still on the server, including a
    prefixed name such as ``INBOX.Sent`` while another mailbox carries ``\\Sent``.
    """
    by_name = {folder.name: folder for folder in listed}
    if known and known in by_name:
        return known, False
    for folder in listed:
        if _is_sent_flag(folder.flags):
            return folder.name, False
    for folder in listed:
        leaf = _leaf(folder.name, folder.delimiter).casefold()
        if leaf in SENT_LEAVES or folder.name.casefold() in SENT_LEAVES:
            return folder.name, False
    return sent_create_name(prefix, delimiter), True
