"""Incremental IMAP sync (CLAUDE.md §5): folders (LIST + LSUB + SPECIAL-USE), STATUS counts, QUOTA, and message
envelopes per folder by UIDVALIDITY + UID, flag changes by CONDSTORE (MODSEQ) and expunges by UID comparison.

The blocking IMAP part (`collect`) runs in a thread and returns plain data; `apply_snapshot` writes it to the local
copy. Passwords, subjects and addresses never go to the logs.
"""

from __future__ import annotations

import asyncio
import ssl
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.header import decode_header, make_header
from typing import Any, Literal

import structlog
from imapclient import IMAPClient
from imapclient.exceptions import IMAPClientError, LoginError
from redis.asyncio import Redis
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Account
from app.auth.security import decrypt
from app.auth.sessions import RevokeReason, revoke_account_sessions
from app.core.audit import audit
from app.core.config import Settings
from app.mail.folders import ListedFolder, assign_special_use
from app.mail.imap import ImapServer
from app.mail.models import FolderMeta, Mailbox, Message

log = structlog.get_logger(__name__)

STATUS_ITEMS = [b"MESSAGES", b"UNSEEN", b"UIDNEXT", b"UIDVALIDITY", b"HIGHESTMODSEQ"]
REFS_FIELD = b"BODY[HEADER.FIELDS (REFERENCES)]"
FETCH_ITEMS = ["UID", "FLAGS", "ENVELOPE", "INTERNALDATE", "RFC822.SIZE", "BODY.PEEK[HEADER.FIELDS (REFERENCES)]"]
LOCK_TIMEOUT_S = 300

Scope = Literal["all", "inbox", "others"]


class SyncAuthError(Exception):
    """The mail server rejected the stored mailbox password."""


class SyncUnavailable(Exception):
    """Connection or protocol failure; the next poll retries."""


@dataclass(frozen=True)
class Credentials:
    email: str
    password: str

    def __repr__(self) -> str:
        return f"Credentials(email={self.email!r})"


@dataclass(frozen=True)
class KnownFolder:
    uidvalidity: int | None
    uidnext: int | None
    highestmodseq: int | None
    unread: int
    local_count: int


@dataclass(frozen=True)
class Envelope:
    uid: int
    message_id: str | None
    in_reply_to: str | None
    references: str | None
    subject: str | None
    from_name: str | None
    from_email: str | None
    to: list[dict[str, str | None]]
    cc: list[dict[str, str | None]]
    sent_at: datetime | None
    received_at: datetime | None
    size: int
    flags: list[str]
    modseq: int | None


@dataclass
class FolderDelta:
    name: str
    messages: int
    unseen: int
    uidvalidity: int | None
    uidnext: int | None
    highestmodseq: int | None
    reset: bool = False
    new: list[Envelope] = field(default_factory=list)
    flags: dict[int, tuple[list[str], int | None]] = field(default_factory=dict)
    present_uids: set[int] | None = None  # None = not checked (folder unchanged)


@dataclass
class MailboxSnapshot:
    capabilities: list[str]
    listed: list[ListedFolder]
    subscribed: set[str]
    special: dict[str, str]
    quota_used_kb: int | None
    quota_limit_kb: int | None
    folders: list[FolderDelta]


# --- blocking IMAP part ---------------------------------------------------------------------------------------


def connect(server: ImapServer, creds: Credentials, ssl_context: ssl.SSLContext | None = None) -> IMAPClient:
    context = ssl_context or ssl.create_default_context()
    try:
        client = IMAPClient(
            server.host, port=server.port, ssl=server.security == "ssl", ssl_context=context, timeout=server.timeout_s
        )
        if server.security == "starttls":
            client.starttls(context)
    except (OSError, IMAPClientError) as exc:
        raise SyncUnavailable(type(exc).__name__) from exc
    client.normalise_times = False
    try:
        client.login(creds.email, creds.password)
    except LoginError as exc:
        logout_quietly(client)
        raise SyncAuthError from exc
    except (OSError, IMAPClientError) as exc:
        logout_quietly(client)
        raise SyncUnavailable(type(exc).__name__) from exc
    return client


def logout_quietly(client: IMAPClient) -> None:
    try:
        client.logout()
    except (OSError, IMAPClientError):
        pass


def _text(raw: bytes | str | None) -> str | None:
    if raw is None:
        return None
    value = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    try:
        return str(make_header(decode_header(value))).strip() or None
    except (UnicodeError, LookupError, ValueError):
        return value.strip() or None


def _addresses(raw: Sequence[Any] | None) -> list[dict[str, str | None]]:
    out: list[dict[str, str | None]] = []
    for address in raw or ():
        mailbox, host = _text(address.mailbox), _text(address.host)
        if mailbox is None:  # group syntax markers
            continue
        email = f"{mailbox}@{host}".lower() if host else mailbox.lower()
        out.append({"name": _text(address.name), "email": email})
    return out


def _aware(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _first_reference(raw: bytes | None) -> str | None:
    if not raw:
        return None
    _, _, value = raw.decode("utf-8", errors="replace").partition(":")
    return " ".join(value.split()) or None


def parse_envelope(uid: int, data: dict[bytes, Any]) -> Envelope:
    env = data.get(b"ENVELOPE")
    sender = _addresses(env.from_ if env else None)
    modseq = data.get(b"MODSEQ")
    return Envelope(
        uid=uid,
        message_id=_text(env.message_id) if env else None,
        in_reply_to=_text(env.in_reply_to) if env else None,
        references=_first_reference(data.get(REFS_FIELD)),
        subject=_text(env.subject) if env else None,
        from_name=sender[0]["name"] if sender else None,
        from_email=sender[0]["email"] if sender else None,
        to=_addresses(env.to if env else None),
        cc=_addresses(env.cc if env else None),
        sent_at=_aware(env.date) if env else None,
        received_at=_aware(data.get(b"INTERNALDATE")),
        size=int(data.get(b"RFC822.SIZE", 0)),
        flags=[_flag(f) for f in data.get(b"FLAGS", ())],
        modseq=int(modseq[0]) if modseq else None,
    )


def _flag(raw: bytes | str) -> str:
    return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw


def _batches(items: Sequence[int], size: int) -> Iterable[Sequence[int]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _quota(client: IMAPClient) -> tuple[int | None, int | None]:
    if not client.has_capability("QUOTA"):
        return None, None
    try:
        _, quotas = client.get_quota_root("INBOX")
    except IMAPClientError:
        return None, None
    for quota in quotas:
        if str(quota.resource).upper() == "STORAGE":
            return int(quota.usage), int(quota.limit)
    return None, None


def folder_selected(
    *,
    name: str,
    is_inbox: bool,
    subscribed: set[str],
    scope: Scope,
    only_names: frozenset[str] | None,
) -> bool:
    """Whether this LIST entry is fetched. An explicit name skips the subscription filter (GitHub #23)."""
    if only_names is not None:
        return name in only_names
    if not is_inbox and name not in subscribed:
        return False
    if (scope == "inbox" and not is_inbox) or (scope == "others" and is_inbox):
        return False
    return True


def collect(
    client: IMAPClient,
    known: dict[str, KnownFolder],
    scope: Scope,
    batch: int,
    *,
    only_names: frozenset[str] | None = None,
) -> MailboxSnapshot:
    capabilities = [_flag(c).upper() for c in client.capabilities()]
    condstore = "CONDSTORE" in capabilities
    listed = [
        ListedFolder(
            name=name,
            delimiter=_flag(delim) if delim else None,
            flags=frozenset(_flag(f) for f in flags),
        )
        for flags, delim, name in client.list_folders()
    ]
    subscribed = {name for _, _, name in client.list_sub_folders()}
    special = assign_special_use(listed)
    used, limit = _quota(client)
    deltas: list[FolderDelta] = []
    for folder in listed:
        if "\\noselect" in {f.lower() for f in folder.flags} or "\\nonexistent" in {f.lower() for f in folder.flags}:
            continue
        is_inbox = special.get(folder.name) == "inbox"
        if not folder_selected(
            name=folder.name,
            is_inbox=is_inbox,
            subscribed=subscribed,
            scope=scope,
            only_names=only_names,
        ):
            continue
        deltas.append(_collect_folder(client, folder.name, known.get(folder.name), condstore, batch))
    return MailboxSnapshot(capabilities, listed, subscribed, special, used, limit, deltas)


def _collect_folder(
    client: IMAPClient, name: str, known: KnownFolder | None, condstore: bool, batch: int
) -> FolderDelta:
    items = STATUS_ITEMS if condstore else STATUS_ITEMS[:4]
    status = client.folder_status(name, items)
    delta = FolderDelta(
        name=name,
        messages=int(status.get(b"MESSAGES", 0)),
        unseen=int(status.get(b"UNSEEN", 0)),
        uidvalidity=int(status[b"UIDVALIDITY"]) if b"UIDVALIDITY" in status else None,
        uidnext=int(status[b"UIDNEXT"]) if b"UIDNEXT" in status else None,
        highestmodseq=int(status[b"HIGHESTMODSEQ"]) if b"HIGHESTMODSEQ" in status else None,
    )
    if known is not None and (
        known.uidvalidity == delta.uidvalidity
        and known.uidnext == delta.uidnext
        and known.local_count == delta.messages
        and (known.highestmodseq == delta.highestmodseq if condstore else known.unread == delta.unseen)
    ):
        return delta  # nothing changed since the last run

    delta.reset = known is None or known.uidvalidity != delta.uidvalidity
    client.select_folder(name, readonly=True)
    try:
        present = sorted(int(u) for u in client.search("ALL"))
        delta.present_uids = set(present)
        start = 1 if delta.reset or known is None else (known.uidnext or 1)
        new_uids = [u for u in present if u >= start]
        fetch_items = [*FETCH_ITEMS, "MODSEQ"] if condstore else FETCH_ITEMS
        for chunk in _batches(new_uids, batch):
            for uid, data in client.fetch(chunk, fetch_items).items():
                delta.new.append(parse_envelope(int(uid), data))
        if not delta.reset and known is not None:
            if condstore and known.highestmodseq:
                changed = [int(u) for u in client.search(["MODSEQ", str(known.highestmodseq + 1)]) if int(u) < start]
            else:
                changed = [u for u in present if u < start]
            for chunk in _batches(changed, batch):
                for uid, data in client.fetch(chunk, ["FLAGS", "MODSEQ"] if condstore else ["FLAGS"]).items():
                    modseq = data.get(b"MODSEQ")
                    delta.flags[int(uid)] = (
                        [_flag(f) for f in data.get(b"FLAGS", ())],
                        int(modseq[0]) if modseq else None,
                    )
    finally:
        if client.has_capability("UNSELECT"):
            client.unselect_folder()
        else:
            client.close_folder()
    return delta


# --- async part: credentials, locking, applying to the local copy -----------------------------------------------


def _flag_columns(flags: Sequence[str]) -> dict[str, bool]:
    lower = {f.lower() for f in flags}
    return {
        "seen": "\\seen" in lower,
        "flagged": "\\flagged" in lower,
        "answered": "\\answered" in lower,
        "deleted": "\\deleted" in lower,
    }


def _stored_flags(flags: Sequence[str]) -> list[str]:
    return sorted(f for f in flags if f.lower() != "\\recent")


async def special_folder_name(db: AsyncSession, mailbox_id: uuid.UUID, use: str) -> str | None:
    """IMAP name of the folder the folder list already maps to ``use`` (sent, drafts, …)."""
    return (
        await db.execute(
            select(FolderMeta.name).where(FolderMeta.mailbox_id == mailbox_id, FolderMeta.special_use == use).limit(1)
        )
    ).scalar_one_or_none()


async def known_state(db: AsyncSession, mailbox_id: uuid.UUID) -> dict[str, KnownFolder]:
    per_folder = select(Message.folder_id, func.count()).where(Message.mailbox_id == mailbox_id)
    counts = dict((await db.execute(per_folder.group_by(Message.folder_id))).all())
    folders = (await db.execute(select(FolderMeta).where(FolderMeta.mailbox_id == mailbox_id))).scalars()
    return {
        f.name: KnownFolder(f.uidvalidity, f.uidnext, f.highestmodseq, f.unread, int(counts.get(f.id, 0)))
        for f in folders
    }


async def apply_snapshot(db: AsyncSession, mailbox: Mailbox, snapshot: MailboxSnapshot, *, now: datetime) -> None:
    existing = {
        f.name: f for f in (await db.execute(select(FolderMeta).where(FolderMeta.mailbox_id == mailbox.id))).scalars()
    }
    listed_names = {f.name for f in snapshot.listed}
    gone = [f.id for name, f in existing.items() if name not in listed_names]
    if gone:
        await db.execute(delete(FolderMeta).where(FolderMeta.id.in_(gone)))
        existing = {name: f for name, f in existing.items() if name in listed_names}
    for folder in snapshot.listed:
        meta = existing.get(folder.name)
        if meta is None:
            meta = FolderMeta(mailbox_id=mailbox.id, name=folder.name)
            db.add(meta)
            existing[folder.name] = meta
        lower = {f.lower() for f in folder.flags}
        meta.delimiter = folder.delimiter
        meta.special_use = snapshot.special.get(folder.name)
        meta.subscribed = folder.name in snapshot.subscribed or meta.special_use == "inbox"
        meta.selectable = not ({"\\noselect", "\\nonexistent"} & lower)
    await db.flush()

    for delta in snapshot.folders:
        meta = existing[delta.name]
        if delta.reset:
            await db.execute(delete(Message).where(Message.folder_id == meta.id))
        if delta.new:
            rows = [
                {
                    "id": uuid.uuid4(),
                    "mailbox_id": mailbox.id,
                    "folder_id": meta.id,
                    "uid": e.uid,
                    "message_id": e.message_id[:998] if e.message_id else None,
                    "in_reply_to": e.in_reply_to[:998] if e.in_reply_to else None,
                    "references": e.references,
                    "subject": e.subject,
                    "from_name": e.from_name[:400] if e.from_name else None,
                    "from_email": e.from_email[:254] if e.from_email else None,
                    "to_addrs": e.to,
                    "cc_addrs": e.cc,
                    "sent_at": e.sent_at,
                    "received_at": e.received_at,
                    "size": e.size,
                    "flags": _stored_flags(e.flags),
                    "modseq": e.modseq,
                    **_flag_columns(e.flags),
                }
                for e in delta.new
            ]
            await db.execute(insert(Message).values(rows).on_conflict_do_nothing(index_elements=["folder_id", "uid"]))
        for uid, (flags, modseq) in delta.flags.items():
            await db.execute(
                update(Message)
                .where(Message.folder_id == meta.id, Message.uid == uid)
                .values(flags=_stored_flags(flags), modseq=modseq, **_flag_columns(flags))
            )
        if delta.present_uids is not None and not delta.reset:
            local = set((await db.execute(select(Message.uid).where(Message.folder_id == meta.id))).scalars())
            expunged = local - delta.present_uids
            if expunged:
                await db.execute(delete(Message).where(Message.folder_id == meta.id, Message.uid.in_(expunged)))
        meta.uidvalidity = delta.uidvalidity
        meta.uidnext = delta.uidnext
        meta.highestmodseq = delta.highestmodseq
        meta.total = delta.messages
        meta.unread = delta.unseen
        meta.last_synced_at = now

    mailbox.capabilities = snapshot.capabilities
    mailbox.quota_used_kb = snapshot.quota_used_kb
    mailbox.quota_limit_kb = snapshot.quota_limit_kb
    mailbox.quota_checked_at = now
    mailbox.sync_state = "ok"
    mailbox.sync_error = None
    mailbox.last_synced_at = now


def server_of(mailbox: Mailbox, settings: Settings) -> ImapServer:
    return ImapServer(mailbox.imap_host, mailbox.imap_port, mailbox.imap_security, settings.imap_login_timeout_s)


async def credentials_for(db: AsyncSession, mailbox: Mailbox, settings: Settings) -> Credentials | None:
    if mailbox.credential_account_id is None:
        return None
    account = await db.get(Account, mailbox.credential_account_id)
    if account is None or not account.active or not account.mailbox_password_enc:
        return None
    return Credentials(mailbox.email, decrypt(settings, account.mailbox_password_enc))


async def mark_auth_failed(db: AsyncSession, mailbox: Mailbox, *, now: datetime) -> None:
    """The stored password no longer works (changed on the mail server): stop using it, log the login out everywhere
    (ADR-003) — the next login stores the new password and the sync resumes."""
    mailbox.sync_state = "auth_failed"
    mailbox.sync_error = "auth_failed"
    revoked = 0
    if mailbox.credential_account_id is not None:
        account = await db.get(Account, mailbox.credential_account_id)
        if account is not None:
            account.mailbox_password_enc = None
        revoked = await revoke_account_sessions(
            db, mailbox.credential_account_id, RevokeReason.password_changed, now=now
        )
    audit(
        db,
        "mail.sync_auth_failed",
        account_id=mailbox.credential_account_id,
        object_type="mailbox",
        object_id=str(mailbox.id),
        details={"sessions_revoked": revoked},
    )


async def sync_mailbox(
    db: AsyncSession,
    mailbox: Mailbox,
    settings: Settings,
    *,
    scope: Scope = "all",
    redis: Redis | None = None,
    ssl_context: ssl.SSLContext | None = None,
    now: datetime | None = None,
    only_names: frozenset[str] | None = None,
) -> str:
    """One sync run. Returns the resulting `sync_state`. Never raises for server problems: the state says it."""
    if not settings.sync_host_allowed(mailbox.imap_host):
        log.warning("mail.sync_host_refused", mailbox_id=str(mailbox.id))
        mailbox.sync_state, mailbox.sync_error = "error", "host_not_allowed"
        await db.commit()
        return mailbox.sync_state
    creds = await credentials_for(db, mailbox, settings)
    if creds is None:
        if mailbox.sync_state != "auth_failed":
            mailbox.sync_state, mailbox.sync_error = "error", "no_credentials"
        await db.commit()
        return mailbox.sync_state

    key = f"smartmail:mail-sync:{mailbox.id}"
    lock = redis.lock(key, timeout=LOCK_TIMEOUT_S, blocking_timeout=30) if redis else None
    if lock is not None and not await lock.acquire():
        return mailbox.sync_state  # another run is busy with this mailbox; its result is as fresh
    try:
        known = await known_state(db, mailbox.id)
        server = server_of(mailbox, settings)

        def work() -> MailboxSnapshot:
            client = connect(server, creds, ssl_context)
            try:
                return collect(client, known, scope, settings.mail_sync_batch, only_names=only_names)
            except (OSError, IMAPClientError) as exc:
                raise SyncUnavailable(type(exc).__name__) from exc
            finally:
                logout_quietly(client)

        started = datetime.now(UTC)
        try:
            snapshot = await asyncio.to_thread(work)
        except SyncAuthError:
            await mark_auth_failed(db, mailbox, now=now or datetime.now(UTC))
            await db.commit()
            log.warning("mail.sync_auth_failed", mailbox_id=str(mailbox.id))
            return mailbox.sync_state
        except SyncUnavailable as exc:
            mailbox.sync_state, mailbox.sync_error = "error", str(exc)[:64] or "unavailable"
            await db.commit()
            log.warning("mail.sync_failed", mailbox_id=str(mailbox.id), error=str(exc))
            return mailbox.sync_state
        await apply_snapshot(db, mailbox, snapshot, now=now or datetime.now(UTC))
        from app.mail.threads import link_unthreaded

        linked = await link_unthreaded(db, mailbox.id)
        new_count = sum(len(d.new) for d in snapshot.folders)
        await db.commit()
        log.info(
            "mail.synced",
            mailbox_id=str(mailbox.id),
            scope="folder" if only_names else scope,
            folders=len(snapshot.folders),
            new=new_count,
            threaded=linked,
            ms=int((datetime.now(UTC) - started).total_seconds() * 1000),
        )
        # Phase 2a: enqueue AI skeleton after sync (Arq worker only — API redis has no enqueue_job)
        if (
            redis is not None
            and new_count
            and mailbox.ai_enabled
            and mailbox.ai_enabled_at is not None
            and hasattr(redis, "enqueue_job")
        ):
            try:
                await redis.enqueue_job(
                    "process_mailbox_ai_job",
                    str(mailbox.id),
                    _job_id=f"mail-ai:{mailbox.id}",
                )
            except Exception as exc:  # mail sync must succeed even when the AI worker is busy
                log.warning("ai.enqueue_failed", mailbox_id=str(mailbox.id), error=type(exc).__name__)
        return mailbox.sync_state
    finally:
        if lock is not None:
            try:
                await lock.release()
            except Exception as exc:  # lock expired meanwhile; nothing to undo
                log.warning("mail.sync_lock_release_failed", error=type(exc).__name__)
