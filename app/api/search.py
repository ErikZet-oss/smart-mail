"""Mail search API — Roundcube scope + fields, Postgres FTS unaccent (SCREENS_SPEC W10; ADR-009)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.auth.deps import DB, ActivePerson, Auth
from app.mail.search import SearchScope, search_messages

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


@router.get("")
async def search(
    ctx: Auth,
    person: ActivePerson,
    db: DB,
    q: Annotated[str, Query(min_length=1, max_length=500)],
    scope: Annotated[SearchScope, Query()] = "all",
    fields: Annotated[list[str] | None, Query()] = None,
    folder_id: uuid.UUID | None = None,
    mailbox: Annotated[str, Query()] = "default",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SearchOut:
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
    )
    field_list = fields or ["full"]
    return SearchOut(
        q=q,
        scope=scope,
        fields=field_list,
        total=total,
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
