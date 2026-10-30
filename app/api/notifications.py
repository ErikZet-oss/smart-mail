"""In-app notifications (W14 / M16): sync failure, assignment/handover, backup ready (#127). No Web Push.

API returns kind + params only (no UI language). Texts live in web/src/i18n/sk.json.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.deps import DB, Auth
from app.mail.mailboxes import accessible_mailboxes
from app.mail.models import Thread
from app.mail.prefs import save_section

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

Kind = Literal["sync_failed", "assigned", "export_ready"]
SECTION = "notifications.dismissed"
DISMISS_MAX = 500
DISMISS_MAX_AGE = timedelta(days=30)

# Codes exposed to the client — never pass through raw IMAP/exception text.
_SYNC_CODES = frozenset({"auth_failed", "host_not_allowed", "no_credentials", "unavailable"})
_UNAVAILABLE_ALIASES = frozenset(
    {"unavailable", "timeouterror", "connectionerror", "oserror", "sslerror", "brokenpipeerror"}
)


class NotificationOut(BaseModel):
    id: str
    kind: Kind
    created_at: datetime
    unread: bool
    href: str | None = None
    params: dict[str, str] = Field(default_factory=dict)


class ListOut(BaseModel):
    items: list[NotificationOut]
    unread_count: int


class DismissIn(BaseModel):
    ids: list[str] = Field(default_factory=list)
    all: bool = False


def _fail(status: int, code: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code})


def sync_error_code(raw: str | None) -> str:
    """Map stored sync_error / sync_state to a stable client code (never raw text)."""
    if not raw:
        return "unavailable"
    key = raw.strip().lower()
    if key in _SYNC_CODES:
        return key
    if key in _UNAVAILABLE_ALIASES or "timeout" in key or "unavailable" in key:
        return "unavailable"
    if key in {"auth_failed", "authenticationerror", "loginerror"}:
        return "auth_failed"
    return "unavailable"


def event_id(kind: str, entity_id: uuid.UUID, when: datetime) -> str:
    """Id includes event time so a new failure / reassignment is unread again."""
    ts = int(when.astimezone(UTC).timestamp())
    return f"{kind}:{entity_id}:{ts}"


def _id_timestamp(nid: str) -> datetime | None:
    parts = nid.rsplit(":", 1)
    if len(parts) != 2:
        return None
    try:
        return datetime.fromtimestamp(int(parts[1]), tz=UTC)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def prune_dismissed(ids: set[str], *, now: datetime | None = None) -> list[str]:
    """Keep at most DISMISS_MAX ids and drop those older than 30 days."""
    now = now or datetime.now(UTC)
    cutoff = now - DISMISS_MAX_AGE
    kept: list[tuple[datetime, str]] = []
    for nid in ids:
        when = _id_timestamp(nid) or now
        if when < cutoff:
            continue
        kept.append((when, nid))
    kept.sort(key=lambda x: x[0], reverse=True)
    return [nid for _, nid in kept[:DISMISS_MAX]]


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
    if not isinstance(raw, list):
        return set()
    return set(prune_dismissed({str(x) for x in raw}))


async def _save_dismissed(db: DB, person_id: uuid.UUID, ids: set[str]) -> list[str]:
    pruned = prune_dismissed(ids)
    await save_section(db, person_id, SECTION, {"ids": pruned})
    return pruned


async def _build(db: DB, ctx: Auth, request: Request | None = None) -> list[NotificationOut]:
    now = datetime.now(UTC)
    dismissed = await _dismissed(db, ctx.person.id if ctx.person else None)
    items: list[NotificationOut] = []

    for mailbox in await accessible_mailboxes(db, ctx.account.id):
        if mailbox.sync_state not in {"error", "auth_failed"}:
            continue
        failed_at = mailbox.updated_at or mailbox.last_synced_at or now
        nid = event_id("sync", mailbox.id, failed_at)
        code = sync_error_code(mailbox.sync_error or mailbox.sync_state)
        items.append(
            NotificationOut(
                id=nid,
                kind="sync_failed",
                created_at=failed_at,
                unread=nid not in dismissed,
                href=f"/mail/{mailbox.id}/inbox",
                params={"mailbox_email": mailbox.email, "error_code": code},
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
            # Self-assign does not create a notification.
            if thread.assigned_by_id is not None and thread.assigned_by_id == thread.assignee_id:
                continue
            if thread.assigned_by_id is None and thread.assigned_at is None:
                # Legacy rows without assignment meta: still notify (assigned by unknown).
                pass
            assigned_at = thread.assigned_at or thread.updated_at or now
            nid = event_id("assign", thread.id, assigned_at)
            subject = (thread.subject or "").strip() or "(no-subject)"
            items.append(
                NotificationOut(
                    id=nid,
                    kind="assigned",
                    created_at=assigned_at,
                    unread=nid not in dismissed,
                    href=f"/mail/{thread.mailbox_id}/inbox/{thread.id}",
                    params={"subject": subject},
                )
            )

    if ctx.person is not None and request is not None:
        # #127 „Archív je pripravený“: a finished backup of this person, while its 24 h link is valid
        from app.mail.export import is_expired, person_exports

        for state in await person_exports(request.app.state.redis, str(ctx.person.id)):
            if state.status != "ready" or state.finished_at is None or is_expired(state, now):
                continue
            finished = datetime.fromisoformat(state.finished_at)
            nid = event_id("export", uuid.UUID(state.id), finished)
            items.append(
                NotificationOut(
                    id=nid,
                    kind="export_ready",
                    created_at=finished,
                    unread=nid not in dismissed,
                    href=None,  # the web downloads /api/mail/exports/{id}/download
                    params={"export_id": state.id, "filename": state.filename, "messages": str(state.done)},
                )
            )

    items.sort(key=lambda n: n.created_at, reverse=True)
    return items


@router.get("")
async def list_notifications(request: Request, ctx: Auth, db: DB) -> ListOut:
    items = await _build(db, ctx, request)
    return ListOut(items=items, unread_count=sum(1 for i in items if i.unread))


@router.post("/dismiss")
async def dismiss(body: DismissIn, request: Request, ctx: Auth, db: DB) -> dict[str, Any]:
    if ctx.person is None:
        raise _fail(403, "person_required")
    current = await _dismissed(db, ctx.person.id)
    if body.all:
        items = await _build(db, ctx, request)
        current = {i.id for i in items} | current
    else:
        current = current | {str(i) for i in body.ids}
    pruned = await _save_dismissed(db, ctx.person.id, current)
    await db.commit()
    return {"ok": True, "dismissed": len(pruned)}
