"""Folder rules of the folder column (SCREENS_SPEC G3, UX_SPEC W2): SPECIAL-USE mapping like Roundcube, order,
quota level and folder name checks. Pure functions; the IMAP side lives in `app.mail.sync`."""

from __future__ import annotations

import enum
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app.auth.persons import slovak_sort_key

SPECIAL_ORDER = ("inbox", "drafts", "sent", "junk", "trash")
SPECIAL_FLAGS = {"\\drafts": "drafts", "\\sent": "sent", "\\junk": "junk", "\\trash": "trash"}
# used only when the server does not flag a folder (no SPECIAL-USE): Roundcube's default names + common SK/EN ones
FALLBACK_NAMES = {
    "drafts": ("koncepty", "drafts", "draft"),
    "sent": ("odoslané", "odoslane", "sent", "sent items", "sent messages"),
    "junk": ("nevyžiadaná pošta", "spam", "junk", "junk e-mail", "junk email"),
    "trash": ("kôš", "kos", "trash", "deleted items", "deleted messages"),
}
FORBIDDEN_CHARS = frozenset('*%\\"')
MAX_NAME = 100


@dataclass(frozen=True)
class ListedFolder:
    name: str
    delimiter: str | None
    flags: frozenset[str]


def assign_special_use(folders: Iterable[ListedFolder]) -> dict[str, str]:
    """Folder name → special-use key. INBOX by name (RFC 3501), the rest by SPECIAL-USE flags (RFC 6154), with a
    name fallback per type that no folder is flagged for. `\\Archive` stays an own folder (UX_SPEC §5)."""
    listed = list(folders)
    result: dict[str, str] = {}
    for folder in listed:
        if folder.name.upper() == "INBOX":
            result[folder.name] = "inbox"
            continue
        for flag in folder.flags:
            use = SPECIAL_FLAGS.get(flag.lower())
            if use and use not in result.values():
                result[folder.name] = use
    for use, names in FALLBACK_NAMES.items():
        if use in result.values():
            continue
        for folder in listed:
            if folder.name not in result and folder.name.lower() in names:
                result[folder.name] = use
                break
    return result


@dataclass(frozen=True)
class OrderedFolder:
    name: str
    label: str  # last path segment, shown in the column (special folders get SK names in the web app)
    parent: str | None
    depth: int


def order_folders(folders: Iterable[tuple[str, str | None]], special: Mapping[str, str]) -> list[OrderedFolder]:
    """Doručená pošta, Koncepty, Odoslané, Nevyžiadaná pošta, Kôš, then own folders alphabetically (Slovak), each
    subfolder right under its parent (Roundcube folder list)."""
    items = list(folders)
    names = {name for name, _ in items}
    delimiters = dict(items)
    children: dict[str | None, list[str]] = {}
    for name, delimiter in items:
        parent = None
        if delimiter and delimiter in name:
            candidate = name.rsplit(delimiter, 1)[0]
            parent = candidate if candidate in names else None
        children.setdefault(parent, []).append(name)

    def rank(name: str) -> tuple[int, tuple[tuple[int, ...], str]]:
        use = special.get(name)
        position = SPECIAL_ORDER.index(use) if use in SPECIAL_ORDER else len(SPECIAL_ORDER)
        return position, slovak_sort_key(name)

    out: list[OrderedFolder] = []

    def walk(parent: str | None, depth: int) -> None:
        for name in sorted(children.get(parent, []), key=rank):
            delimiter = delimiters[name]
            label = name[len(parent) + len(delimiter or "") :] if parent is not None else name
            out.append(OrderedFolder(name, label, parent, depth))
            walk(name, depth + 1)

    walk(None, 0)
    return out


class QuotaLevel(enum.StrEnum):
    normal = "normal"
    warning = "warning"  # ≥ 75 % → warning/400
    danger = "danger"  # ≥ 90 % → danger/600 (PRODUCT_SPEC §1 "red ≥ 90 %")


@dataclass(frozen=True)
class QuotaView:
    used_kb: int
    limit_kb: int
    percent: int
    level: QuotaLevel


def quota_view(used_kb: int | None, limit_kb: int | None) -> QuotaView | None:
    if used_kb is None or not limit_kb:
        return None
    percent = min(100, used_kb * 100 // limit_kb)
    level = QuotaLevel.danger if percent >= 90 else QuotaLevel.warning if percent >= 75 else QuotaLevel.normal
    return QuotaView(used_kb, limit_kb, percent, level)


class FolderNameError(ValueError):
    pass


def validate_folder_name(name: str, delimiter: str | None) -> str:
    """One path segment typed by the user (Nový podpriečinok, Premenovať)."""
    clean = unicodedata.normalize("NFC", name).strip()
    if not clean or len(clean) > MAX_NAME:
        raise FolderNameError("length")
    if clean.upper() == "INBOX":
        raise FolderNameError("reserved")
    if (delimiter and delimiter in clean) or FORBIDDEN_CHARS & set(clean) or not all(c.isprintable() for c in clean):
        raise FolderNameError("characters")
    return clean


def child_name(parent: str | None, delimiter: str | None, segment: str) -> str:
    return f"{parent}{delimiter or ''}{segment}" if parent else segment


def rename_target(current: str, delimiter: str | None, segment: str) -> str:
    if delimiter and delimiter in current:
        return f"{current.rsplit(delimiter, 1)[0]}{delimiter}{segment}"
    return segment
