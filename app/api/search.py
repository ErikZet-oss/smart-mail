"""Mail search API — Roundcube scope + fields, Postgres FTS unaccent (SCREENS_SPEC W10; ADR-009)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.auth.deps import DB, Auth, SettingsDep, SignedInPerson
from app.mail.search import SearchScope, oldest_downloaded_at, search_messages, server_uid_hits

router = APIRouter(prefix="/api/search", tags=["search"])


class MessageHitOut(BaseModel):
    id: str
    folder_id: str
    mailbox_id: str
    subject: str | None
    from_name: str | None
    from_email: str | None
    preview: str | None
    received_at: datetime | None
    rank: float


class SearchOut(BaseModel):
    q: str
    scope: str
    fields: list[str]
    total: int
    messages: list[MessageHitOut]
    oldest_downloaded_at: datetime | None = None
    # #38: None = the server was not asked; ok | partial | timeout | unavailable
    server_search: str | None = None


@router.get("")
async def search(
    ctx: Auth,
    person: SignedInPerson,
    db: DB,
    settings: SettingsDep,
    q: Annotated[str, Query(min_length=1, max_length=500)],
    scope: Annotated[SearchScope, Query()] = "all",
    fields: Annotated[list[str] | None, Query()] = None,
    folder_id: uuid.UUID | None = None,
    mailbox: Annotated[str, Query()] = "default",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    server: bool = False,
) -> SearchOut:
    server_uids: dict[uuid.UUID, set[int]] = {}
    server_state: str | None = None
    if server:
        # Telo / Celá správa also on the IMAP server: bodies of unopened messages are not indexed locally (#38)
        server_uids, server_state = await server_uid_hits(
            db,
            settings,
            ctx.account,
            q=q,
            scope=scope,
            fields=fields,
            folder_id=folder_id,
            mailbox_ref=mailbox,
            person_id=person.id,
        )
    hits, total = await search_messages(
        db,
        ctx.account,
        q=q,
        scope=scope,
        fields=fields,
        folder_id=folder_id,
        mailbox_ref=mailbox,
        person_id=person.id,
        limit=limit,
        offset=offset,
        server_uids=server_uids,
    )
    oldest = await oldest_downloaded_at(db, ctx.account, person_id=person.id)
    field_list = fields or ["full"]
    return SearchOut(
        q=q,
        scope=scope,
        fields=field_list,
        total=total,
        oldest_downloaded_at=oldest if isinstance(oldest, datetime) else None,
        server_search=server_state,
        messages=[
            MessageHitOut(
                id=str(h.id),
                folder_id=str(h.folder_id),
                mailbox_id=str(h.mailbox_id),
                subject=h.subject,
                from_name=h.from_name,
                from_email=h.from_email,
                preview=h.preview,
                received_at=h.received_at if isinstance(h.received_at, datetime) else None,
                rank=h.rank,
            )
            for h in hits
        ],
    )
