"""Mail full-text search with Roundcube scope/fields and unaccent (PRODUCT_SPEC §2.7, ADR-009).

Prefix FTS (to_tsquery + :*), address substring LIKE for Od/Komu/Kópia, weighted search_vector
(subject A, addresses B, body D). Subfolder scope escapes LIKE wildcards in folder names.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import ColumnElement, String, and_, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Account
from app.mail.mailboxes import accessible_mailbox, accessible_mailboxes
from app.mail.models import FolderMeta, Message

SearchScope = Literal["current", "subfolders", "all"]
SearchField = Literal["subject", "from", "to", "cc", "body", "full"]

FIELD_MAP: dict[str, SearchField] = {
    "subject": "subject",
    "predmet": "subject",
    "from": "from",
    "od": "from",
    "to": "to",
    "komu": "to",
    "cc": "cc",
    "kopia": "cc",
    "kópia": "cc",
    "body": "body",
    "telo": "body",
    "full": "full",
    "cela": "full",
    "celá": "full",
    "cela_sprava": "full",
    "celá_správa": "full",
}

# Weights on messages.search_vector (maintained by DB trigger, ADR-009).
WEIGHT: dict[SearchField, str | None] = {
    "subject": "A",
    "from": "B",
    "to": "B",
    "cc": "B",
    "body": "D",
    "full": None,
}

_TSQUERY_SAFE = re.compile(r"[^\w]+", re.UNICODE)


@dataclass
class SearchHit:
    id: uuid.UUID
    folder_id: uuid.UUID
    mailbox_id: uuid.UUID
    subject: str | None
    from_name: str | None
    from_email: str | None
    preview: str | None
    received_at: object | None
    rank: float


def normalize_fields(raw: list[str] | None) -> set[SearchField]:
    if not raw:
        return {"full"}
    out: set[SearchField] = set()
    for item in raw:
        key = item.strip().lower().replace(" ", "_")
        mapped = FIELD_MAP.get(key)
        if mapped:
            out.add(mapped)
    return out or {"full"}


def strip_accents(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", value) if unicodedata.category(c) != "Mn")


def tokenize(q: str) -> list[str]:
    """Split query into words (space/hyphen/punct); keep tokens after stripping accents."""
    words: list[str] = []
    for part in re.split(r"[\s\-_/.,;:]+", q):
        cleaned = _TSQUERY_SAFE.sub("", strip_accents(part.lower()))
        if cleaned:
            words.append(cleaned)
    return words


def like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def prefix_tsquery(q: str, *, weight: str | None = None) -> str | None:
    """Build `word1:* & word2:*` (optional weight letter) after unaccent — Roundcube word fragments."""
    words = tokenize(q)
    if not words:
        return None
    parts: list[str] = []
    for w in words:
        # Prefix + optional weight: 'faktúr:*A' (PostgreSQL allows :*WEIGHT)
        parts.append(f"{w}:*{weight}" if weight else f"{w}:*")
    return " & ".join(parts)


def _tsquery_expr(q: str, *, weight: str | None = None) -> ColumnElement[object] | None:
    raw = prefix_tsquery(q, weight=weight)
    if raw is None:
        return None
    return func.to_tsquery("simple", literal(raw))


def _addr_like(column: Any, q: str) -> ColumnElement[bool] | None:
    """Each query part must appear as substring of unaccent(lower(column)); %/_ escaped."""
    # Keep dots/@ for domains (firma.sk); split only on whitespace.
    parts = [strip_accents(p.lower()) for p in q.split() if strip_accents(p.lower()).strip()]
    if not parts:
        return None
    conds: list[ColumnElement[bool]] = []
    for part in parts:
        safe = like_escape(part)
        if not safe:
            continue
        pattern = f"%{safe}%"
        conds.append(func.unaccent(func.lower(func.coalesce(column, ""))).like(pattern, escape="\\"))
    if not conds:
        return None
    return and_(*conds)


def _field_match(field: SearchField, q: str) -> ColumnElement[bool] | None:
    weight = WEIGHT[field]
    tsq = _tsquery_expr(q, weight=weight)
    parts: list[ColumnElement[bool]] = []
    if tsq is not None:
        # Always use the maintained GIN-indexed search_vector (never to_tsvector at query time).
        parts.append(Message.search_vector.op("@@")(tsq))
    if field in ("from", "full"):
        like_email = _addr_like(Message.from_email, q)
        like_name = _addr_like(Message.from_name, q)
        if like_email is not None:
            parts.append(like_email)
        if like_name is not None:
            parts.append(like_name)
    if field in ("to", "full"):
        like_to = _addr_like(func.cast(Message.to_addrs, String), q)
        if like_to is not None:
            parts.append(like_to)
    if field in ("cc", "full"):
        like_cc = _addr_like(func.cast(Message.cc_addrs, String), q)
        if like_cc is not None:
            parts.append(like_cc)
    if not parts:
        return None
    return or_(*parts)


def _visible_folder_filter(person_id: uuid.UUID | None) -> ColumnElement[bool]:
    """Private folders are visible only to their owner_person_id (ADR-009)."""
    if person_id is None:
        return FolderMeta.private.is_(False)
    return or_(FolderMeta.private.is_(False), FolderMeta.owner_person_id == person_id)


async def folder_ids_for_scope(
    db: AsyncSession,
    *,
    mailbox_ids: list[uuid.UUID],
    scope: SearchScope,
    folder_id: uuid.UUID | None,
    person_id: uuid.UUID | None,
) -> list[uuid.UUID] | None:
    """Return folder ids to search, or None if the scope folder is missing/forbidden."""
    visible = _visible_folder_filter(person_id)
    if scope == "all":
        rows = await db.execute(select(FolderMeta.id).where(FolderMeta.mailbox_id.in_(mailbox_ids), visible))
        return list(rows.scalars())
    if folder_id is None:
        return []
    folder = await db.get(FolderMeta, folder_id)
    if folder is None or folder.mailbox_id not in mailbox_ids:
        return None
    if folder.private and (folder.owner_person_id is None or folder.owner_person_id != person_id):
        return None
    if scope == "current":
        return [folder.id]
    delim = folder.delimiter or "/"
    prefix = folder.name + delim
    rows = await db.execute(
        select(FolderMeta.id).where(
            FolderMeta.mailbox_id == folder.mailbox_id,
            visible,
            or_(FolderMeta.id == folder.id, FolderMeta.name.startswith(prefix, autoescape=True)),
        )
    )
    return list(rows.scalars())


async def search_messages(
    db: AsyncSession,
    account: Account,
    *,
    q: str,
    scope: SearchScope = "all",
    fields: list[str] | None = None,
    folder_id: uuid.UUID | None = None,
    mailbox_ref: str = "default",
    person_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[SearchHit], int]:
    q = q.strip()
    if not q:
        return [], 0
    field_set = normalize_fields(fields)
    if scope == "all":
        mailboxes = await accessible_mailboxes(db, account.id)
        mailbox_ids = [m.id for m in mailboxes]
    else:
        mailbox = await accessible_mailbox(db, account, mailbox_ref)
        if mailbox is None:
            return [], 0
        mailbox_ids = [mailbox.id]
    if not mailbox_ids:
        return [], 0
    folder_ids = await folder_ids_for_scope(
        db, mailbox_ids=mailbox_ids, scope=scope, folder_id=folder_id, person_id=person_id
    )
    if folder_ids is None or not folder_ids:
        return [], 0

    field_conds = [_field_match(f, q) for f in field_set]
    field_conds_ok = [c for c in field_conds if c is not None]
    if not field_conds_ok:
        return [], 0
    match = or_(*field_conds_ok)
    base = (
        select(Message)
        .join(FolderMeta, FolderMeta.id == Message.folder_id)
        .where(
            Message.mailbox_id.in_(mailbox_ids),
            Message.folder_id.in_(folder_ids),
            Message.deleted.is_(False),
            match,
        )
    )
    total = int(await db.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rank_tsq = _tsquery_expr(q, weight=None)
    empty_vec = func.to_tsvector("simple", "")
    # Special-char-only queries may match via address LIKE with no FTS tokens — avoid empty to_tsquery.
    if rank_tsq is None:
        rank = literal(0.0)
    else:
        rank = func.ts_rank_cd(func.coalesce(Message.search_vector, empty_vec), rank_tsq)
    rows = (
        await db.execute(
            base.add_columns(rank).order_by(rank.desc(), Message.received_at.desc()).limit(limit).offset(offset)
        )
    ).all()
    hits = [
        SearchHit(
            id=m.id,
            folder_id=m.folder_id,
            mailbox_id=m.mailbox_id,
            subject=m.subject,
            from_name=m.from_name,
            from_email=m.from_email,
            preview=m.preview,
            received_at=m.received_at,
            rank=float(r or 0),
        )
        for m, r in rows
    ]
    return hits, total


async def oldest_downloaded_at(
    db: AsyncSession,
    account: Account,
    *,
    person_id: uuid.UUID | None = None,
) -> object | None:
    """Earliest received_at among messages the account may search (downloaded corpus only)."""
    mailboxes = await accessible_mailboxes(db, account.id)
    mailbox_ids = [m.id for m in mailboxes]
    if not mailbox_ids:
        return None
    visible = _visible_folder_filter(person_id)
    return await db.scalar(
        select(func.min(Message.received_at))
        .join(FolderMeta, FolderMeta.id == Message.folder_id)
        .where(
            Message.mailbox_id.in_(mailbox_ids),
            Message.deleted.is_(False),
            visible,
        )
    )
