"""Mailboxes and the folder column (SCREENS_SPEC G1 badge, G3, W2; CLAUDE.md §5).

GET    /api/mail/mailboxes                                  mailboxes of this login (⋮ Prepnúť schránku)
GET    /api/mail/mailboxes/{ref}/folders                    folder column: folders, counts, quota, sync state
POST   /api/mail/mailboxes/{ref}/refresh                    Obnoviť (IMAP sync now)
POST   /api/mail/mailboxes/{ref}/folders                    Nový podpriečinok
PATCH  /api/mail/mailboxes/{ref}/folders/{id}               Premenovať
DELETE /api/mail/mailboxes/{ref}/folders/{id}               Vymazať
POST   /api/mail/mailboxes/{ref}/folders/{id}/mark-read     Označiť všetko ako prečítané
POST   /api/mail/mailboxes/{ref}/folders/{id}/empty         Vyprázdniť (Kôš, Nevyžiadaná pošta)
POST   /api/mail/mailboxes/{ref}/folders/{id}/compact       Zhustiť

`ref` is a mailbox id or `default`. Reading needs a session; every change needs an active person (CLAUDE.md §9).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import select

from app.auth.deps import DB, ActivePerson, Auth, SettingsDep, client_ip
from app.core.audit import audit
from app.core.config import Settings
from app.mail.folder_ops import FolderAction, FolderActionRefused, run_folder_action
from app.mail.folders import (
    FolderNameError,
    QuotaLevel,
    child_name,
    order_folders,
    quota_view,
    rename_target,
    validate_folder_name,
)
from app.mail.mailboxes import accessible_mailbox, accessible_mailboxes
from app.mail.models import FolderMeta, Mailbox
from app.mail.sync import SyncAuthError, SyncUnavailable, credentials_for, mark_auth_failed, server_of, sync_mailbox

router = APIRouter(prefix="/api/mail", tags=["mail"])

EMPTYABLE = frozenset({"trash", "junk"})


class MailboxOut(BaseModel):
    id: str
    email: str
    unread: int
    sync_state: str
    ai_enabled: bool = False
    ai_available: bool = False


class FolderOut(BaseModel):
    id: str
    name: str
    label: str
    parent_id: str | None
    depth: int
    special_use: str | None
    unread: int
    total: int
    selectable: bool


class QuotaOut(BaseModel):
    used_kb: int
    limit_kb: int
    percent: int
    level: QuotaLevel


class SyncOut(BaseModel):
    state: str
    error: str | None
    last_synced_at: datetime | None


class FoldersOut(BaseModel):
    mailbox: MailboxOut
    folders: list[FolderOut]
    quota: QuotaOut | None
    sync: SyncOut


class NewFolderIn(BaseModel):
    parent_id: uuid.UUID | None = None
    name: str = Field(max_length=200)


class RenameIn(BaseModel):
    name: str = Field(max_length=200)


def fail(status: int, code: str, **extra: object) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, **extra})


async def _inbox_unread(db: DB, mailbox_id: uuid.UUID) -> int:
    value = await db.scalar(
        select(FolderMeta.unread).where(FolderMeta.mailbox_id == mailbox_id, FolderMeta.special_use == "inbox")
    )
    return int(value or 0)


def _ai_provider_configured(settings: Settings) -> bool:
    """True when classify can run (Anthropic key present — Bedrock remains a stub)."""
    if settings.llm_provider == "bedrock":
        return False
    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
    return bool(key and key.strip())


async def _mailbox_out(db: DB, mailbox: Mailbox, settings: Settings | None = None) -> MailboxOut:
    ai_on = bool(mailbox.ai_enabled and mailbox.ai_enabled_at is not None)
    available = _ai_provider_configured(settings) if settings is not None else False
    return MailboxOut(
        id=str(mailbox.id),
        email=mailbox.email,
        unread=await _inbox_unread(db, mailbox.id),
        sync_state=mailbox.sync_state,
        ai_enabled=ai_on,
        ai_available=available and ai_on,
    )


async def folders_out(db: DB, mailbox: Mailbox, settings: Settings | None = None) -> FoldersOut:
    metas = list((await db.execute(select(FolderMeta).where(FolderMeta.mailbox_id == mailbox.id))).scalars())
    by_name = {m.name: m for m in metas}
    # the column shows subscribed folders (Roundcube) and the parents they need to hang under
    shown = {m.name for m in metas if m.subscribed or m.special_use == "inbox"}
    for name in list(shown):
        meta = by_name[name]
        while meta.delimiter and meta.delimiter in meta.name:
            parent = by_name.get(meta.name.rsplit(meta.delimiter, 1)[0])
            if parent is None:
                break
            shown.add(parent.name)
            meta = parent
    special = {m.name: m.special_use for m in metas if m.special_use}
    ordered = order_folders([(n, by_name[n].delimiter) for n in shown], special)
    quota = quota_view(mailbox.quota_used_kb, mailbox.quota_limit_kb)
    return FoldersOut(
        mailbox=await _mailbox_out(db, mailbox, settings),
        folders=[
            FolderOut(
                id=str(by_name[f.name].id),
                name=f.name,
                label=f.label,
                parent_id=str(by_name[f.parent].id) if f.parent else None,
                depth=f.depth,
                special_use=by_name[f.name].special_use,
                unread=by_name[f.name].unread,
                total=by_name[f.name].total,
                selectable=by_name[f.name].selectable,
            )
            for f in ordered
        ],
        quota=QuotaOut(used_kb=quota.used_kb, limit_kb=quota.limit_kb, percent=quota.percent, level=quota.level)
        if quota
        else None,
        sync=SyncOut(state=mailbox.sync_state, error=mailbox.sync_error, last_synced_at=mailbox.last_synced_at),
    )


async def _mailbox(db: DB, ctx: Auth, ref: str) -> Mailbox:
    mailbox = await accessible_mailbox(db, ctx.account, ref)
    if mailbox is None:
        raise fail(404, "mailbox_not_found")
    return mailbox


async def _folder(db: DB, mailbox: Mailbox, folder_id: uuid.UUID) -> FolderMeta:
    meta = await db.get(FolderMeta, folder_id)
    if meta is None or meta.mailbox_id != mailbox.id:
        raise fail(404, "folder_not_found")
    return meta


def _redis(request: Request) -> Redis:
    redis: Redis = request.app.state.redis
    return redis


async def _sync(request: Request, db: DB, mailbox: Mailbox, settings: Settings) -> None:
    state = await sync_mailbox(db, mailbox, settings, redis=_redis(request))
    if state == "auth_failed":
        raise HTTPException(status_code=401, detail={"code": "unauthenticated", "reason": "password_changed"})


@router.get("/mailboxes")
async def mailboxes(ctx: Auth, db: DB, settings: SettingsDep) -> list[MailboxOut]:
    return [await _mailbox_out(db, m, settings) for m in await accessible_mailboxes(db, ctx.account.id)]


@router.get("/mailboxes/{ref}/folders")
async def folders(ref: str, request: Request, ctx: Auth, db: DB, settings: SettingsDep) -> FoldersOut:
    mailbox = await _mailbox(db, ctx, ref)
    if mailbox.sync_state == "new" and settings.mail_sync_enabled:
        await _sync(request, db, mailbox, settings)  # first open after the first login: fill the column now
    return await folders_out(db, mailbox, settings)


@router.post("/mailboxes/{ref}/refresh")
async def refresh(ref: str, request: Request, ctx: Auth, db: DB, settings: SettingsDep) -> FoldersOut:
    mailbox = await _mailbox(db, ctx, ref)
    await _sync(request, db, mailbox, settings)
    return await folders_out(db, mailbox, settings)


async def _act(
    request: Request,
    db: DB,
    settings: Settings,
    mailbox: Mailbox,
    action: FolderAction,
    folder: str,
    *,
    target: str | None = None,
    audit_action: str,
    details: dict[str, object],
) -> FoldersOut:
    if not settings.sync_host_allowed(mailbox.imap_host):
        raise fail(409, "host_not_allowed")
    creds = await credentials_for(db, mailbox, settings)
    if creds is None:
        raise fail(409, "mailbox_credentials_missing")
    try:
        await asyncio.to_thread(run_folder_action, server_of(mailbox, settings), creds, action, folder, target)
    except SyncAuthError:
        await mark_auth_failed(db, mailbox, now=datetime.now(UTC))
        await db.commit()
        raise HTTPException(status_code=401, detail={"code": "unauthenticated", "reason": "password_changed"}) from None
    except SyncUnavailable:
        raise fail(503, "mail_server_unavailable") from None
    except FolderActionRefused:
        raise fail(409, "folder_action_failed") from None
    audit(db, audit_action, object_type="mailbox", object_id=str(mailbox.id), ip=client_ip(request), details=details)
    await db.commit()
    await _sync(request, db, mailbox, settings)
    return await folders_out(db, mailbox, settings)


@router.post("/mailboxes/{ref}/folders/{folder_id}/mark-read")
async def mark_read(
    ref: str, folder_id: uuid.UUID, request: Request, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> FoldersOut:
    mailbox = await _mailbox(db, ctx, ref)
    meta = await _folder(db, mailbox, folder_id)
    return await _act(
        request, db, settings, mailbox, FolderAction.mark_read, meta.name,
        audit_action="mail.folder_marked_read", details={"folder": meta.name},
    )  # fmt: skip


@router.post("/mailboxes/{ref}/folders/{folder_id}/empty")
async def empty(
    ref: str, folder_id: uuid.UUID, request: Request, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> FoldersOut:
    mailbox = await _mailbox(db, ctx, ref)
    meta = await _folder(db, mailbox, folder_id)
    if meta.special_use not in EMPTYABLE:
        raise fail(409, "folder_not_emptyable")
    return await _act(
        request, db, settings, mailbox, FolderAction.empty, meta.name,
        audit_action="mail.folder_emptied", details={"folder": meta.name, "messages": meta.total},
    )  # fmt: skip


@router.post("/mailboxes/{ref}/folders/{folder_id}/compact")
async def compact(
    ref: str, folder_id: uuid.UUID, request: Request, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> FoldersOut:
    mailbox = await _mailbox(db, ctx, ref)
    meta = await _folder(db, mailbox, folder_id)
    return await _act(
        request, db, settings, mailbox, FolderAction.compact, meta.name,
        audit_action="mail.folder_compacted", details={"folder": meta.name},
    )  # fmt: skip


def _segment(name: str, delimiter: str | None) -> str:
    try:
        return validate_folder_name(name, delimiter)
    except FolderNameError as exc:
        raise fail(422, f"folder_name_{exc}") from None


async def _delimiter(db: DB, mailbox: Mailbox) -> str | None:
    inbox = await db.scalar(
        select(FolderMeta.delimiter).where(FolderMeta.mailbox_id == mailbox.id, FolderMeta.special_use == "inbox")
    )
    return inbox or "/"


async def _ensure_free(db: DB, mailbox: Mailbox, name: str) -> None:
    taken = await db.scalar(select(FolderMeta.id).where(FolderMeta.mailbox_id == mailbox.id, FolderMeta.name == name))
    if taken is not None:
        raise fail(409, "folder_exists")


@router.post("/mailboxes/{ref}/folders")
async def create_folder(
    ref: str, body: NewFolderIn, request: Request, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> FoldersOut:
    mailbox = await _mailbox(db, ctx, ref)
    parent = await _folder(db, mailbox, body.parent_id) if body.parent_id else None
    delimiter = parent.delimiter if parent else await _delimiter(db, mailbox)
    name = child_name(parent.name if parent else None, delimiter, _segment(body.name, delimiter))
    await _ensure_free(db, mailbox, name)
    return await _act(
        request, db, settings, mailbox, FolderAction.create, name,
        audit_action="mail.folder_created", details={"folder": name},
    )  # fmt: skip


@router.patch("/mailboxes/{ref}/folders/{folder_id}")
async def rename_folder(
    ref: str,
    folder_id: uuid.UUID,
    body: RenameIn,
    request: Request,
    ctx: Auth,
    person: ActivePerson,
    db: DB,
    settings: SettingsDep,
) -> FoldersOut:
    mailbox = await _mailbox(db, ctx, ref)
    meta = await _folder(db, mailbox, folder_id)
    if meta.special_use:
        raise fail(409, "special_folder")
    target = rename_target(meta.name, meta.delimiter, _segment(body.name, meta.delimiter))
    if target == meta.name:
        return await folders_out(db, mailbox, settings)
    await _ensure_free(db, mailbox, target)
    return await _act(
        request, db, settings, mailbox, FolderAction.rename, meta.name, target=target,
        audit_action="mail.folder_renamed", details={"folder": meta.name, "to": target},
    )  # fmt: skip


@router.delete("/mailboxes/{ref}/folders/{folder_id}")
async def delete_folder(
    ref: str, folder_id: uuid.UUID, request: Request, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> FoldersOut:
    mailbox = await _mailbox(db, ctx, ref)
    meta = await _folder(db, mailbox, folder_id)
    if meta.special_use:
        raise fail(409, "special_folder")
    return await _act(
        request, db, settings, mailbox, FolderAction.delete, meta.name,
        audit_action="mail.folder_deleted", details={"folder": meta.name, "messages": meta.total},
    )  # fmt: skip
