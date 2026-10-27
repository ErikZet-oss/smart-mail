"""Phase-1 in-app notifications (W14 / M16): sync failure + assignment/handover. No Web Push."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.deps import DB, Auth
from app.mail.mailboxes import accessible_mailboxes
from app.mail.models import Thread
from app.mail.prefs import save_section

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

Kind = Literal["sync_failed", "assigned"]
SECTION = "notifications.dismissed"


class NotificationOut(BaseModel):
    id: str
    kind: Kind
    title: str
    body: str
    created_at: datetime
    unread: bool
    href: str | None = None


class ListOut(BaseModel):
    items: list[NotificationOut]
    unread_count: int


class DismissIn(BaseModel):
    ids: list[str] = Field(default_factory=list)
    all: bool = False


def _fail(status: int, code: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code})


async def _dismissed(db: DB, person_id: uuid.UUID | None) -> set[str]:
    if person_id is None:
        return set()
    from app.mail.models import UserSettings

    row = await db.scalar(
        select(UserSettings).where(UserSettings.person_id == person_id, UserSettings.section == SECTION)
    )
    if row is None:
        return set()
    raw = row.data.get("ids") if isinstance(row.data, dict) else None
    return {str(x) for x in raw} if isinstance(raw, list) else set()


async def _build(db: DB, ctx: Auth) -> list[NotificationOut]:
    now = datetime.now(UTC)
    dismissed = await _dismissed(db, ctx.person.id if ctx.person else None)
    items: list[NotificationOut] = []

    for mailbox in await accessible_mailboxes(db, ctx.account.id):
        if mailbox.sync_state not in {"error", "auth_failed"}:
            continue
        nid = f"sync:{mailbox.id}"
        reason = mailbox.sync_error or mailbox.sync_state
        items.append(
            NotificationOut(
                id=nid,
                kind="sync_failed",
                title="Synchronizácia zlyhala",
                body=f"{mailbox.email}: {reason}",
                created_at=mailbox.last_synced_at or mailbox.updated_at or now,
                unread=nid not in dismissed,
                href="/mail/default/inbox",
            )
        )

    if ctx.person is not None:
        rows = (
            await db.execute(
                select(Thread)
                .where(Thread.assignee_id == ctx.person.id, Thread.status != "done")
                .order_by(Thread.updated_at.desc())
                .limit(50)
            )
        ).scalars()
        for thread in rows:
            nid = f"assign:{thread.id}"
            subject = (thread.subject or "").strip() or "(bez predmetu)"
            items.append(
                NotificationOut(
                    id=nid,
                    kind="assigned",
                    title="Pridelené vám",
                    body=subject,
                    created_at=thread.updated_at or thread.last_message_at or now,
                    unread=nid not in dismissed,
                    href="/mail/default/inbox",
                )
            )

    items.sort(key=lambda n: n.created_at, reverse=True)
    return items


@router.get("")
async def list_notifications(ctx: Auth, db: DB) -> ListOut:
    items = await _build(db, ctx)
    return ListOut(items=items, unread_count=sum(1 for i in items if i.unread))


@router.post("/dismiss")
async def dismiss(body: DismissIn, ctx: Auth, db: DB) -> dict[str, Any]:
    if ctx.person is None:
        raise _fail(403, "person_required")
    current = await _dismissed(db, ctx.person.id)
    if body.all:
        items = await _build(db, ctx)
        current = {i.id for i in items} | current
    else:
        current = current | {str(i) for i in body.ids}
    await save_section(db, ctx.person.id, SECTION, {"ids": sorted(current)})
    await db.commit()
    return {"ok": True, "dismissed": len(current)}
