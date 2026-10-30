"""Folder / mailbox backup to ZIP (#127): estimate, start (ARQ), status, download within 24 h.

Only a person with access to the mailbox may export it; private folders only their owner. The archive is streamed
through the API (no public link) to the person who started it. Audit carries folders, range, count and size —
never mail content.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any, Literal

from arq.connections import ArqRedis
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from app.api.mail import _mailbox, _redis, fail
from app.auth.deps import DB, ActivePerson, Auth, SettingsDep
from app.auth.reauth import ReauthedSession
from app.core.audit import audit
from app.core.content_disposition import content_disposition_attachment
from app.mail import export, storage
from app.mail.models import Mailbox
from app.mail.sync import SyncAuthError, SyncUnavailable
from app.mail.sync_schedule import schedule_sync

router = APIRouter(prefix="/api/mail", tags=["mail-export"])


class RangeIn(BaseModel):
    kind: Literal["all", "older", "between"] = "all"
    months: int | None = Field(default=None, ge=1, le=240)
    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def _check(self) -> RangeIn:
        if self.kind == "older" and self.months is None:
            raise ValueError("months_required")
        if self.kind == "between" and (self.date_from is None or self.date_to is None or self.date_from > self.date_to):
            raise ValueError("dates_required")
        return self

    def to_range(self) -> export.ExportRange:
        return export.ExportRange(self.kind, self.months, self.date_from, self.date_to)


class ExportIn(BaseModel):
    folder_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)  # None = the whole mailbox
    include_children: bool = False
    range: RangeIn = Field(default_factory=RangeIn)


class EstimateOut(BaseModel):
    folders: int
    messages: int
    bytes: int


async def _folders(db: DB, ctx: Auth, ref: str, body: ExportIn) -> tuple[Any, list[Any]]:
    mailbox = await _mailbox(db, ctx, ref)
    try:
        folders = await export.select_folders(
            db, mailbox, ctx.person.id if ctx.person else None, body.folder_ids, body.include_children
        )
    except export.ExportError as exc:
        raise fail(403 if exc.code == "folder_private" else 404, exc.code) from exc
    folders = [f for f in folders if f.selectable]
    if not folders:
        raise fail(422, "no_folders")
    return mailbox, folders


@router.post("/mailboxes/{ref}/exports/estimate")
async def estimate_export(ref: str, body: ExportIn, ctx: Auth, person: ActivePerson, db: DB) -> EstimateOut:
    _, folders = await _folders(db, ctx, ref, body)
    messages, size = await export.estimate(db, folders, body.range.to_range(), datetime.now(UTC).date())
    return EstimateOut(folders=len(folders), messages=messages, bytes=size)


@router.post("/mailboxes/{ref}/exports", status_code=202)
async def start_export(
    ref: str, body: ExportIn, request: Request, ctx: Auth, person: ActivePerson, db: DB
) -> dict[str, Any]:
    mailbox, folders = await _folders(db, ctx, ref, body)
    _, estimated = await export.estimate(db, folders, body.range.to_range(), datetime.now(UTC).date())
    if not export.enough_space(estimated):
        raise fail(507, "export_no_space")  # the test server has a small disk; a whole mailbox can be GBs
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    scope: Literal["folders", "mailbox"] = "mailbox" if body.folder_ids is None else "folders"
    name = mailbox.email.split("@")[0] if scope == "mailbox" else export.folder_dir(folders[0]).replace("/", "-")
    state = export.ExportState(
        id=uuid.uuid4().hex,
        mailbox_id=str(mailbox.id),
        account_id=str(ctx.account.id),
        person_id=str(person.id),
        folder_ids=[str(f.id) for f in folders],
        folder_names=[f.name for f in folders],
        range=body.range.model_dump(mode="json"),
        scope=scope,
        filename=f"smartmail-{export.slug(name, 40)}-{stamp}.zip",
    )
    redis = _redis(request)
    if not await export.start(redis, state):
        raise fail(409, "export_running")
    await ArqRedis(connection_pool=redis.connection_pool).enqueue_job(
        "export_mail_job", state.id, _job_id=f"mail-export:{state.id}"
    )
    audit(
        db,
        "mail.export_started",
        account_id=ctx.account.id,
        person_id=person.id,
        object_type="mailbox",
        object_id=str(mailbox.id),
        details={"export_id": state.id, "folders": state.folder_names, "range": state.range, "scope": scope},
    )
    await db.commit()
    return state.public()


async def _own(request: Request, person: Any, export_id: str) -> export.ExportState:
    state = await export.load_state(_redis(request), export_id)
    if state is None or state.person_id != str(person.id):
        raise fail(404, "export_not_found")  # someone else's export is not even visible
    return state


@router.get("/exports")
async def list_exports(request: Request, person: ActivePerson) -> list[dict[str, Any]]:
    return [s.public() for s in await export.person_exports(_redis(request), str(person.id))]


@router.get("/exports/{export_id}")
async def get_export(export_id: str, request: Request, person: ActivePerson) -> dict[str, Any]:
    return (await _own(request, person, export_id)).public()


@router.get("/exports/{export_id}/download")
async def download_export(
    export_id: str, request: Request, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> StreamingResponse:
    state = await _own(request, person, export_id)
    if state.status != "ready" or not state.storage_key:
        raise fail(409, "export_not_ready")
    if export.is_expired(state):
        raise fail(410, "export_expired")
    chunks = storage.iter_key(settings, state.storage_key)
    if chunks is None:
        raise fail(410, "export_expired")
    state.downloaded_at = datetime.now(UTC).isoformat()
    await export.save_state(_redis(request), state)
    audit(
        db,
        "mail.export_downloaded",
        account_id=ctx.account.id,
        person_id=person.id,
        object_type="mailbox",
        object_id=state.mailbox_id,
        details={"export_id": state.id, "messages": state.done, "bytes": state.archive_size, "sha256": state.sha256},
    )
    await db.commit()
    return StreamingResponse(
        chunks,
        media_type="application/zip",
        headers={
            "Content-Disposition": content_disposition_attachment(state.filename),
            "Content-Length": str(state.archive_size),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/exports/{export_id}/purge")
async def purge_export(
    export_id: str,
    request: Request,
    ctx: ReauthedSession,
    person: ActivePerson,
    db: DB,
    settings: SettingsDep,
) -> dict[str, Any]:
    """⚠ part 2 of #127: delete from the server exactly the messages in the archive (manifest UIDs, \\Deleted +
    EXPUNGE — not the Kôš, so the quota is freed). Needs a re-auth, a downloaded archive whose stored copy still
    matches its sha256, and runs once per archive."""
    state = await _own(request, person, export_id)
    if state.status != "ready" or export.is_expired(state):
        raise fail(409, "export_not_ready")
    if state.purged_at:
        raise fail(409, "export_already_purged")
    if not state.downloaded_at:
        raise fail(409, "export_not_downloaded")
    if not await export.archive_intact(settings, state):
        raise fail(409, "export_archive_mismatch")
    mailbox = await db.get(Mailbox, uuid.UUID(state.mailbox_id))
    if mailbox is None:
        raise fail(404, "mailbox_not_found")
    try:
        result = await export.purge_exported(db, settings, state, mailbox)
    except export.ExportError as exc:
        raise fail(409, exc.code) from exc
    except (SyncUnavailable, SyncAuthError) as exc:
        raise fail(503, "mail_server_unavailable") from exc
    state.purged_at = datetime.now(UTC).isoformat()
    state.purged = result.deleted
    await export.save_state(_redis(request), state)
    audit(
        db,
        "mail.export_purged",
        account_id=ctx.account.id,
        person_id=person.id,
        object_type="mailbox",
        object_id=state.mailbox_id,
        details={
            "export_id": state.id,
            "deleted": result.deleted,
            "folders": result.folders,
            "skipped": result.skipped,
            "sha256": state.sha256,
        },
    )
    await db.commit()
    await schedule_sync(_redis(request), mailbox.id)
    return {"deleted": result.deleted, "folders": result.folders, "skipped": result.skipped}
