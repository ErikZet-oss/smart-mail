"""Folder / mailbox backup to a ZIP of raw .eml files (#127, Erik 2026-10-30).

The ARQ job reads each message with `BODY.PEEK[]` on a read-only SELECT (never changes \\Seen), writes it straight
into a ZIP on local disk (one message at a time, never the whole archive in memory) and uploads the finished file
to object storage in parts. The job state lives in Redis with a TTL (no table — #127): progress, the storage key,
the archive sha256 and the UIDs it contains per folder (the safe-delete step may delete only those). Download links
are valid 24 h; an hourly cron deletes expired archives. One running export per mailbox.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import re
import shutil
import tempfile
import time
import unicodedata
import uuid
import zipfile
from collections.abc import Awaitable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from email.parser import BytesHeaderParser
from email.policy import default as default_policy
from pathlib import Path
from typing import Any, Literal, cast

import structlog
from redis.asyncio import Redis
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.mail import storage
from app.mail.models import FolderMeta, Mailbox, Message
from app.mail.sync import connect, credentials_for, logout_quietly, server_of

log = structlog.get_logger(__name__)

LINK_TTL_S = 24 * 3600  # the download link (and the archive) live 24 h
STATE_TTL_S = LINK_TTL_S + 3600
LOCK_TTL_S = 6 * 3600  # a crashed job frees the mailbox after 6 h at the latest
FETCH_CHUNK = 20  # messages per IMAP FETCH — bounds memory to ~20 raw messages
PROGRESS_EVERY_S = 1.0
BOM = "\ufeff"  # manifest.csv opens in SK Excel like the eval file
_PEEK = ["BODY.PEEK[]", "INTERNALDATE", "RFC822.SIZE"]  # never RFC822 / BODY[]: those set \Seen

RangeKind = Literal["all", "older", "between"]
Status = Literal["queued", "running", "ready", "failed"]


class ExportError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ExportRange:
    kind: RangeKind = "all"
    months: int | None = None  # older: older than N months
    date_from: date | None = None  # between: inclusive
    date_to: date | None = None  # between: inclusive

    def bounds(self, today: date) -> tuple[date | None, date | None]:
        """(since inclusive, before exclusive) in message dates."""
        if self.kind == "older":
            return None, _months_ago(today, self.months or 0)
        if self.kind == "between":
            return self.date_from, (self.date_to + timedelta(days=1)) if self.date_to else None
        return None, None

    def imap_criteria(self, today: date) -> list[Any]:
        since, before = self.bounds(today)
        criteria: list[Any] = []
        if since:
            criteria += ["SINCE", since]
        if before:
            criteria += ["BEFORE", before]
        return criteria or ["ALL"]


def _months_ago(today: date, months: int) -> date:
    year, month = divmod(today.year * 12 + today.month - 1 - months, 12)
    month += 1
    day = min(
        today.day,
        [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][
            month - 1
        ],
    )
    return date(year, month, day)


# --- folders and estimate -------------------------------------------------------------------------------------


def visible_to(folder: FolderMeta, person_id: uuid.UUID | None) -> bool:
    """Private folders only for their owner (same rule as search)."""
    return not folder.private or (folder.owner_person_id is not None and folder.owner_person_id == person_id)


async def select_folders(
    db: AsyncSession,
    mailbox: Mailbox,
    person_id: uuid.UUID | None,
    folder_ids: Sequence[uuid.UUID] | None,
    include_children: bool,
) -> list[FolderMeta]:
    """The folders of an export. A named private folder of somebody else → `folder_private` (403); for a whole
    mailbox (folder_ids None) private folders of others are simply left out."""
    all_folders = list((await db.scalars(select(FolderMeta).where(FolderMeta.mailbox_id == mailbox.id))).all())
    if folder_ids is None:
        return sorted((f for f in all_folders if visible_to(f, person_id)), key=lambda f: f.name)
    by_id = {f.id: f for f in all_folders}
    chosen: dict[uuid.UUID, FolderMeta] = {}
    for fid in folder_ids:
        folder = by_id.get(fid)
        if folder is None:
            raise ExportError("folder_not_found")
        if not visible_to(folder, person_id):
            raise ExportError("folder_private")
        chosen[folder.id] = folder
        if include_children:
            prefix = folder.name + (folder.delimiter or "/")
            for child in all_folders:
                if child.name.startswith(prefix) and visible_to(child, person_id):
                    chosen[child.id] = child
    return sorted(chosen.values(), key=lambda f: f.name)


async def estimate(db: AsyncSession, folders: Sequence[FolderMeta], rng: ExportRange, today: date) -> tuple[int, int]:
    """(messages, bytes) from the synced copy — an estimate; the job reads the server itself."""
    if not folders:
        return 0, 0
    since, before = rng.bounds(today)
    q = select(func.count(Message.id), func.coalesce(func.sum(Message.size), 0)).where(
        Message.folder_id.in_([f.id for f in folders])
    )
    if since:
        q = q.where(Message.received_at >= datetime.combine(since, datetime.min.time(), UTC))
    if before:
        q = q.where(
            or_(Message.received_at.is_(None), Message.received_at < datetime.combine(before, datetime.min.time(), UTC))
        )
    count, size = (await db.execute(q)).one()
    return int(count), int(size)


# --- state in Redis ---------------------------------------------------------------------------------------------


def state_key(export_id: str) -> str:
    return f"smartmail:export:{export_id}"


def lock_key(mailbox_id: uuid.UUID | str) -> str:
    return f"smartmail:export:lock:{mailbox_id}"


EXPIRY_SET = "smartmail:export:expiry"  # zset storage_key → unix time when the archive must be deleted


@dataclass(slots=True)
class ExportState:
    id: str
    mailbox_id: str
    account_id: str
    person_id: str | None
    folder_ids: list[str]
    folder_names: list[str]
    range: dict[str, Any]
    scope: Literal["folders", "mailbox"]
    status: Status = "queued"
    done: int = 0
    total: int = 0
    bytes: int = 0
    storage_key: str | None = None
    sha256: str | None = None
    archive_size: int = 0
    filename: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    finished_at: str | None = None
    expires_at: str | None = None
    downloaded_at: str | None = None
    purged_at: str | None = None
    purged: int = 0
    error: str | None = None
    # what the archive contains — the safe-delete step may delete exactly these UIDs (#127)
    manifest: dict[str, dict[str, Any]] = field(default_factory=dict)  # folder_id → {uidvalidity, uids}

    def public(self) -> dict[str, Any]:
        out = asdict(self)
        out.pop("manifest")
        out.pop("storage_key")
        return out


async def save_state(redis: Redis, state: ExportState) -> None:
    await redis.set(state_key(state.id), json.dumps(asdict(state)), ex=STATE_TTL_S)


async def load_state(redis: Redis, export_id: str) -> ExportState | None:
    raw = await redis.get(state_key(export_id))
    if raw is None:
        return None
    return ExportState(**json.loads(raw))


async def person_exports(redis: Redis, person_id: str) -> list[ExportState]:
    members = await cast("Awaitable[set[Any]]", redis.smembers(f"smartmail:export:p:{person_id}"))
    ids = [i.decode() if isinstance(i, bytes) else str(i) for i in members]
    states = [await load_state(redis, i) for i in ids]
    return sorted((s for s in states if s is not None), key=lambda s: s.created_at, reverse=True)


async def start(redis: Redis, state: ExportState) -> bool:
    """Take the per-mailbox lock and store the state; False when another export of this mailbox is running."""
    if not await redis.set(lock_key(state.mailbox_id), state.id, nx=True, ex=LOCK_TTL_S):
        return False
    await save_state(redis, state)
    if state.person_id:
        key = f"smartmail:export:p:{state.person_id}"
        await cast("Awaitable[int]", redis.sadd(key, state.id))
        await redis.expire(key, STATE_TTL_S)
    return True


# --- the archive ------------------------------------------------------------------------------------------------

_SLUG = re.compile(r"[^a-z0-9]+")
_HEADERS = BytesHeaderParser(policy=default_policy)


def slug(text: str, limit: int = 40) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    return _SLUG.sub("-", plain).strip("-")[:limit].strip("-") or "bez-predmetu"


def folder_dir(folder: FolderMeta) -> str:
    """IMAP path → safe ZIP directory („Dodávatelia/Fixtech“ → „Dodavatelia/Fixtech“)."""
    parts = folder.name.split(folder.delimiter or "/") if folder.delimiter else [folder.name]
    return "/".join(slug(p, 60) or "priecinok" for p in parts)


def _header(raw: bytes) -> tuple[str, str, str]:
    """(Message-ID, From, Subject) from the header part only."""
    head = raw.split(b"\r\n\r\n", 1)[0].split(b"\n\n", 1)[0]
    try:
        msg = _HEADERS.parsebytes(head)
        return (str(msg.get("Message-ID", "") or ""), str(msg.get("From", "") or ""), str(msg.get("Subject", "") or ""))
    except Exception:  # a broken header must not stop a backup
        return "", "", ""


def _internal_date(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return None


MANIFEST_FIELDS = ("folder", "uid", "message_id", "date", "from", "subject", "size", "sha256", "file")


def _run_folder(
    client: Any,
    folder: FolderMeta,
    criteria: list[Any],
    archive: zipfile.ZipFile,
    manifest: csv.DictWriter[str],
    used_names: set[str],
    progress: Any,
) -> tuple[int, list[int], int]:
    """Export one folder (blocking IMAP, runs in a worker thread). Returns (uidvalidity, uids, bytes)."""
    selected = client.select_folder(folder.name, readonly=True)
    uidvalidity = int(selected.get(b"UIDVALIDITY", 0) or 0) if isinstance(selected, dict) else 0
    uids = sorted(int(u) for u in client.search(criteria))
    progress(add_total=len(uids))
    done_uids: list[int] = []
    size_total = 0
    base = folder_dir(folder)
    for i in range(0, len(uids), FETCH_CHUNK):
        chunk = uids[i : i + FETCH_CHUNK]
        data = client.fetch(chunk, _PEEK)
        for uid in chunk:
            item = data.get(uid) or {}
            raw = item.get(b"BODY[]") or item.get(b"BODY.PEEK[]")
            if raw is None:
                continue  # deleted meanwhile — not in the archive, so never purged either
            raw = bytes(raw)
            when = _internal_date(item.get(b"INTERNALDATE"))
            message_id, sender, subject = _header(raw)
            stamp = when.strftime("%Y-%m-%d_%H%M") if when else "0000-00-00_0000"
            name = f"{base}/{stamp}_{slug(subject)}_{uid}.eml"
            while name in used_names:  # same folder slug twice (e.g. „Faktúry“ / „Faktury“)
                name = name.removesuffix(".eml") + "_1.eml"
            used_names.add(name)
            archive.writestr(name, raw)
            sha = hashlib.sha256(raw).hexdigest()
            manifest.writerow(
                {
                    "folder": folder.name,
                    "uid": uid,
                    "message_id": message_id,
                    "date": when.isoformat() if when else "",
                    "from": sender,
                    "subject": subject,
                    "size": len(raw),
                    "sha256": sha,
                    "file": name,
                }
            )
            done_uids.append(uid)
            size_total += len(raw)
            progress(add_done=1, add_bytes=len(raw))
    return uidvalidity, done_uids, size_total


async def run_export(
    redis: Redis, db: AsyncSession, settings: Settings, export_id: str, *, today: date | None = None
) -> ExportState | None:
    """The ARQ job body. Never raises for IMAP/storage problems — the state becomes `failed` with a code."""
    state = await load_state(redis, export_id)
    if state is None:
        return None
    try:
        mailbox = await db.get(Mailbox, uuid.UUID(state.mailbox_id))
        if mailbox is None:
            raise ExportError("mailbox_not_found")
        folders = [f for f in [await db.get(FolderMeta, uuid.UUID(fid)) for fid in state.folder_ids] if f is not None]
        creds = await credentials_for(db, mailbox, settings)
        if creds is None:
            raise ExportError("no_credentials")
        rng = ExportRange(
            kind=state.range.get("kind", "all"),
            months=state.range.get("months"),
            date_from=date.fromisoformat(state.range["date_from"]) if state.range.get("date_from") else None,
            date_to=date.fromisoformat(state.range["date_to"]) if state.range.get("date_to") else None,
        )
        criteria = rng.imap_criteria(today or datetime.now(UTC).date())
        _, estimated = await estimate(db, folders, rng, today or datetime.now(UTC).date())
        if not enough_space(estimated):
            raise ExportError("export_no_space")
        state.status = "running"
        await save_state(redis, state)

        loop = asyncio.get_running_loop()
        last = [0.0]

        def progress(add_total: int = 0, add_done: int = 0, add_bytes: int = 0) -> None:
            state.total += add_total
            state.done += add_done
            state.bytes += add_bytes
            now = time.monotonic()
            if now - last[0] >= PROGRESS_EVERY_S or add_total:
                last[0] = now
                asyncio.run_coroutine_threadsafe(save_state(redis, state), loop)

        with tempfile.TemporaryDirectory(prefix="smartmail-export-") as tmp:
            path = Path(tmp) / "archive.zip"

            def build() -> dict[str, dict[str, Any]]:
                manifest_io = io.StringIO()
                writer = csv.DictWriter(manifest_io, fieldnames=MANIFEST_FIELDS, delimiter=";", lineterminator="\r\n")
                writer.writeheader()
                result: dict[str, dict[str, Any]] = {}
                used: set[str] = set()
                client = connect(server_of(mailbox, settings), creds)
                try:
                    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                        for folder in folders:
                            uidvalidity, uids, _ = _run_folder(
                                client, folder, criteria, archive, writer, used, progress
                            )
                            result[str(folder.id)] = {"uidvalidity": uidvalidity, "uids": uids}
                        archive.writestr("manifest.csv", BOM + manifest_io.getvalue())
                finally:
                    logout_quietly(client)
                return result

            state.manifest = await asyncio.to_thread(build)
            key, sha = await asyncio.to_thread(storage.put_file, settings, path, prefix=f"exports/{state.mailbox_id}")
            state.archive_size = path.stat().st_size
        finished = datetime.now(UTC)
        state.storage_key, state.sha256 = key, sha
        state.status = "ready"
        state.finished_at = finished.isoformat()
        state.expires_at = (finished + timedelta(seconds=LINK_TTL_S)).isoformat()
        await redis.zadd(EXPIRY_SET, {key: finished.timestamp() + LINK_TTL_S})
    except ExportError as exc:
        state.status, state.error = "failed", exc.code
    except Exception as exc:  # IMAP down, auth failed, storage full — the person sees „zlyhalo“
        log.warning("mail.export_failed", export_id=export_id, error=type(exc).__name__)
        state.status, state.error = "failed", type(exc).__name__
    finally:
        await redis.delete(lock_key(state.mailbox_id))
    await save_state(redis, state)
    log.info("mail.export_done", export_id=export_id, status=state.status, messages=state.done)
    return state


async def delete_expired(redis: Redis, settings: Settings, now: float | None = None) -> int:
    """Hourly: delete archives whose 24 h link expired. Returns how many were removed."""
    due = await redis.zrangebyscore(EXPIRY_SET, 0, now if now is not None else time.time())
    for raw in due:
        key = raw.decode() if isinstance(raw, bytes) else str(raw)
        await asyncio.to_thread(storage.delete_key, settings, key)
        await redis.zrem(EXPIRY_SET, raw)
    return len(due)


def is_expired(state: ExportState, now: datetime | None = None) -> bool:
    if state.expires_at is None:
        return False
    return (now or datetime.now(UTC)) >= datetime.fromisoformat(state.expires_at)


# --- part 2: safe delete after the backup (#127) -------------------------------------------------------------------

PURGE_CHUNK = 500
SPACE_FACTOR = 1.1  # the ZIP on disk plus headroom, against the estimate (reviewer note on #130)


def temp_free_bytes() -> int:
    return shutil.disk_usage(tempfile.gettempdir()).free


def enough_space(estimated_bytes: int, free: int | None = None) -> bool:
    return (free if free is not None else temp_free_bytes()) >= int(estimated_bytes * SPACE_FACTOR)


@dataclass(slots=True)
class PurgeResult:
    deleted: int = 0
    folders: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)  # folder name → reason code


def _purge_folder(client: Any, name: str, uidvalidity: int, uids: list[int]) -> tuple[int, str | None]:
    """\\Deleted + EXPUNGE of exactly these UIDs (blocking). Returns (deleted, skip reason)."""
    selected = client.select_folder(name)
    current = int(selected.get(b"UIDVALIDITY", 0) or 0) if isinstance(selected, dict) else 0
    if uidvalidity and current and current != uidvalidity:
        return 0, "uidvalidity_changed"  # the folder was re-created: these UIDs mean other messages now
    present = sorted({int(u) for u in client.search("ALL")} & set(uids))  # gone meanwhile → nothing to do
    if not present:
        return 0, None
    uidplus = b"UIDPLUS" in client.capabilities()
    if not uidplus:
        # without UID EXPUNGE a plain EXPUNGE removes every \Deleted message — only safe when there is no other one
        others = set(int(u) for u in client.search(["DELETED"])) - set(present)
        if others:
            return 0, "other_deleted_present"
    for i in range(0, len(present), PURGE_CHUNK):
        chunk = present[i : i + PURGE_CHUNK]
        client.add_flags(chunk, [b"\\Deleted"], silent=True)
        if uidplus:
            client.expunge(chunk)  # UID EXPUNGE: nothing that arrived meanwhile, no other \Deleted message
    if not uidplus:
        client.expunge()
    return len(present), None


async def purge_exported(db: AsyncSession, settings: Settings, state: ExportState, mailbox: Mailbox) -> PurgeResult:
    """Delete from the server exactly the messages the archive contains (UIDs of the manifest), per folder."""
    creds = await credentials_for(db, mailbox, settings)
    if creds is None:
        raise ExportError("no_credentials")
    folders = {str(f.id): f for f in (await db.scalars(select(FolderMeta).where(FolderMeta.mailbox_id == mailbox.id)))}

    def work() -> PurgeResult:
        result = PurgeResult()
        client = connect(server_of(mailbox, settings), creds)
        try:
            for folder_id, entry in state.manifest.items():
                folder = folders.get(folder_id)
                uids = [int(u) for u in entry.get("uids", [])]
                if folder is None:
                    result.skipped[folder_id] = "folder_gone"
                    continue
                if not uids:
                    continue
                deleted, reason = _purge_folder(client, folder.name, int(entry.get("uidvalidity") or 0), uids)
                if reason:
                    result.skipped[folder.name] = reason
                if deleted:
                    result.deleted += deleted
                    result.folders.append(folder.name)
        finally:
            logout_quietly(client)
        return result

    return await asyncio.to_thread(work)


async def archive_intact(settings: Settings, state: ExportState) -> bool:
    """The stored archive still hashes to the sha256 recorded when it was built (before anything is deleted)."""
    if not state.storage_key or not state.sha256:
        return False

    def digest() -> str | None:
        chunks = storage.iter_key(settings, state.storage_key or "")
        if chunks is None:
            return None
        h = hashlib.sha256()
        for block in chunks:
            h.update(block)
        return h.hexdigest()

    return await asyncio.to_thread(digest) == state.sha256
