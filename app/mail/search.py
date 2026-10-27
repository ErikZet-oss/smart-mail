"""Mail full-text search with Roundcube scope/fields and unaccent (PRODUCT_SPEC §2.7, ADR-009)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import ColumnElement, String, func, or_, select
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


def _tsquery(q: str) -> ColumnElement[object]:
    return func.plainto_tsquery("simple", func.unaccent(q))


def _field_source(field: SearchField) -> Any:
    if field == "subject":
        return func.coalesce(Message.subject, "")
    if field == "from":
        return func.concat(func.coalesce(Message.from_name, ""), " ", func.coalesce(Message.from_email, ""))
    if field == "to":
        return func.coalesce(func.cast(Message.to_addrs, String), "")
    if field == "cc":
        return func.coalesce(func.cast(Message.cc_addrs, String), "")
    return func.concat(func.coalesce(Message.body_text, ""), " ", func.coalesce(Message.preview, ""))


def _field_match(field: SearchField, q: str) -> ColumnElement[bool]:
    tsq = _tsquery(q)
    if field == "full":
        return Message.search_vector.op("@@")(tsq)
    vec = func.to_tsvector("simple", func.unaccent(_field_source(field)))
    return vec.op("@@")(tsq)


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
            or_(FolderMeta.id == folder.id, FolderMeta.name.startswith(prefix)),
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

    match = or_(*[_field_match(f, q) for f in field_set])
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
    empty_vec = func.to_tsvector("simple", "")
    rank = func.ts_rank_cd(func.coalesce(Message.search_vector, empty_vec), _tsquery(q))
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
