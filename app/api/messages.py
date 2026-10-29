"""Message list, reading pane and toolbar actions (Phase 1d / SCREENS_SPEC W2, W2c, W2e, W2m, W2n)."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, asc, desc, func, or_, select

from app.ai.models import Classification
from app.api.mail import _folder, _mailbox, _redis, fail
from app.auth.deps import DB, ActivePerson, Auth, SettingsDep, client_ip
from app.core.audit import audit
from app.core.config import Settings
from app.core.content_disposition import content_disposition_attachment
from app.mail import storage
from app.mail.actions import MsgAction, MsgTarget, run_msg_action_async
from app.mail.body import ensure_body, load_attachments
from app.mail.flags import is_forwarded
from app.mail.local_apply import REMOVING, apply_action_locally
from app.mail.models import Attachment, FolderMeta, Mailbox, Message, Thread
from app.mail.prefs import ListPrefs, UiPrefs, get_list_prefs, get_ui_prefs, save_section, shortcuts_enabled
from app.mail.sync import Credentials, SyncAuthError, SyncUnavailable, credentials_for, mark_auth_failed, server_of
from app.mail.sync_schedule import schedule_sync

router = APIRouter(prefix="/api/mail", tags=["mail-messages"])
log = structlog.get_logger()

FilterName = Literal["all", "unread", "flagged", "attachments"]
MAX_BULK = 500


class AddrOut(BaseModel):
    name: str | None = None
    email: str | None = None


class MessageListItem(BaseModel):
    id: str
    thread_id: str | None
    folder_id: str
    uid: int
    subject: str | None
    from_name: str | None
    from_email: str | None
    preview: str | None
    received_at: datetime | None
    sent_at: datetime | None
    size: int
    seen: bool
    flagged: bool
    answered: bool
    forwarded: bool = False
    has_attachments: bool
    thread_count: int = 1
    # Phase 2b — from classifications (optional)
    ai_category: str | None = None
    ai_priority: str | None = None
    ai_summary: str | None = None
    ai_language: str | None = None
    ai_confidence: float | None = None
    ai_note_codes: list[str] = []


class ThreadListItem(BaseModel):
    id: str
    subject: str | None
    from_name: str | None
    from_email: str | None
    preview: str | None
    last_message_at: datetime | None
    message_count: int
    unread_count: int
    flagged: bool
    has_attachments: bool
    status: str
    snoozed_until: datetime | None
    assignee_id: str | None
    latest_message_id: str | None


class ListOut(BaseModel):
    mode: str
    total: int
    page: int
    page_size: int
    messages: list[MessageListItem] = []
    threads: list[ThreadListItem] = []
    prefs: ListPrefs


class AttachmentOut(BaseModel):
    id: str
    filename: str
    content_type: str
    size: int
    is_inline: bool
    av_status: str


class MessageDetail(BaseModel):
    id: str
    thread_id: str | None
    folder_id: str
    uid: int
    message_id: str | None
    subject: str | None
    from_name: str | None
    from_email: str | None
    to: list[AddrOut]
    cc: list[AddrOut]
    sent_at: datetime | None
    received_at: datetime | None
    size: int
    seen: bool
    flagged: bool
    answered: bool
    body_text: str | None
    body_html_sanitized: str | None
    attachments: list[AttachmentOut]
    auth_results: dict[str, Any] | None
    thread_status: str | None = None
    snoozed_until: datetime | None = None
    assignee_id: str | None = None
    # Phase 2b
    ai_category: str | None = None
    ai_summary: str | None = None
    ai_language: str | None = None
    security_notes: list[str] = []
    # Pilot #18 B6 — whether the "Zobraziť obrázky" bar may offer remote images
    remote_images_offered: bool = False
    # True = show the proxied images without a click (mode "always", or "known" and the sender is known)
    remote_images_auto: bool = False
    remote_images_mode: Literal["never", "known", "always"] = "known"


class FlagIn(BaseModel):
    seen: bool | None = None
    flagged: bool | None = None


class BulkIn(BaseModel):
    message_ids: list[uuid.UUID] = Field(max_length=MAX_BULK)
    action: Literal["mark_seen", "mark_unseen", "flag", "unflag", "delete", "purge", "junk", "archive", "move", "done"]
    dest_folder_id: uuid.UUID | None = None


class SnoozeIn(BaseModel):
    until: datetime | None = None  # null = clear snooze


class AssignIn(BaseModel):
    person_id: uuid.UUID | None = None


class PrefsIn(BaseModel):
    list: ListPrefs | None = None
    ui: UiPrefs | None = None


def _addrs(raw: list[dict[str, Any]] | None) -> list[AddrOut]:
    return [AddrOut(name=a.get("name"), email=a.get("email")) for a in (raw or [])]


async def _special_folder(db: DB, mailbox: Mailbox, use: str) -> FolderMeta | None:
    return await db.scalar(select(FolderMeta).where(FolderMeta.mailbox_id == mailbox.id, FolderMeta.special_use == use))


async def _own_named(db: DB, mailbox: Mailbox, name: str) -> FolderMeta | None:
    return await db.scalar(select(FolderMeta).where(FolderMeta.mailbox_id == mailbox.id, FolderMeta.name == name))


async def _creds(db: DB, mailbox: Mailbox, settings: Settings) -> Credentials:
    if not settings.sync_host_allowed(mailbox.imap_host):
        raise fail(409, "host_not_allowed")
    creds = await credentials_for(db, mailbox, settings)
    if creds is None:
        raise fail(409, "mailbox_credentials_missing")
    return creds


async def _run(
    request: Request,
    db: DB,
    settings: Settings,
    mailbox: Mailbox,
    action: MsgAction,
    folder: FolderMeta,
    messages: list[Message],
    *,
    dest: FolderMeta | None = None,
    audit_action: str,
    details: dict[str, object],
) -> None:
    """IMAP action, then the same change in the local copy, commit, and a scheduled (not awaited) sync (#89)."""
    creds = await _creds(db, mailbox, settings)
    started = time.monotonic()
    try:
        await run_msg_action_async(
            server_of(mailbox, settings),
            creds,
            action,
            MsgTarget(folder.name, tuple(m.uid for m in messages)),
            dest_folder=dest.name if dest else None,
        )
    except SyncAuthError:
        await mark_auth_failed(db, mailbox, now=datetime.now(UTC))
        await db.commit()
        raise HTTPException(status_code=401, detail={"code": "unauthenticated", "reason": "password_changed"}) from None
    except SyncUnavailable:
        raise fail(503, "mail_server_unavailable") from None
    imap_ms = int((time.monotonic() - started) * 1000)
    await apply_action_locally(db, action, folder, messages, dest=dest)
    audit(db, audit_action, object_type="mailbox", object_id=str(mailbox.id), ip=client_ip(request), details=details)
    await db.commit()
    if action in REMOVING:
        # Flags are exact locally already; moved messages need their new UIDs in the destination folder.
        await schedule_sync(_redis(request), mailbox.id)
    log.info(
        "mail.action_done",
        mailbox_id=str(mailbox.id),
        action=str(action),
        n=len(messages),
        imap_ms=imap_ms,
        ms=int((time.monotonic() - started) * 1000),
    )


def _sort_col(prefs: ListPrefs) -> Any:
    mapping = {
        "date_received": Message.received_at,
        "date_sent": Message.sent_at,
        "subject": Message.subject,
        "from": Message.from_email,
        "size": Message.size,
    }
    col = mapping.get(prefs.sort, Message.received_at)
    return asc(col).nulls_last() if prefs.sort_dir == "asc" else desc(col).nulls_last()


@router.get("/mailboxes/{ref}/folders/{folder_id}/messages")
async def list_messages(
    ref: str,
    folder_id: uuid.UUID,
    ctx: Auth,
    db: DB,
    settings: SettingsDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int | None, Query(ge=1, le=200)] = None,
    filter: FilterName = "all",
    q: str | None = None,
) -> ListOut:
    mailbox = await _mailbox(db, ctx, ref)
    folder = await _folder(db, mailbox, folder_id)
    person_id = ctx.session.active_person_id
    prefs = await get_list_prefs(db, person_id)
    size = page_size or prefs.page_size

    if prefs.mode == "conversations":
        return await _list_threads(db, mailbox, folder, prefs, page, size, filter, q)

    cond = [Message.folder_id == folder.id, Message.deleted.is_(False)]
    if filter == "unread":
        cond.append(Message.seen.is_(False))
    elif filter == "flagged":
        cond.append(Message.flagged.is_(True))
    elif filter == "attachments":
        cond.append(Message.has_attachments.is_(True))
    if q:
        like = f"%{q.strip()}%"
        cond.append(or_(Message.subject.ilike(like), Message.from_email.ilike(like), Message.from_name.ilike(like)))

    total = int(await db.scalar(select(func.count()).select_from(Message).where(and_(*cond))) or 0)
    rows = list(
        (
            await db.execute(
                select(Message)
                .where(and_(*cond))
                .order_by(_sort_col(prefs), desc(Message.uid))
                .offset((page - 1) * size)
                .limit(size)
            )
        ).scalars()
    )
    thread_counts: dict[uuid.UUID, int] = {}
    ids = [m.thread_id for m in rows if m.thread_id]
    if ids:
        for tid, cnt in (
            await db.execute(
                select(Message.thread_id, func.count()).where(Message.thread_id.in_(ids)).group_by(Message.thread_id)
            )
        ).all():
            if tid:
                thread_counts[tid] = int(cnt)

    cls_by_msg: dict[uuid.UUID, Classification] = {}
    if rows:
        for cls in (
            await db.execute(select(Classification).where(Classification.message_id.in_([m.id for m in rows])))
        ).scalars():
            cls_by_msg[cls.message_id] = cls

    messages_out: list[MessageListItem] = []
    for m in rows:
        classification = cls_by_msg.get(m.id)
        payload = (classification.payload if classification else None) or {}
        messages_out.append(
            MessageListItem(
                id=str(m.id),
                thread_id=str(m.thread_id) if m.thread_id else None,
                folder_id=str(m.folder_id),
                uid=m.uid,
                subject=m.subject,
                from_name=m.from_name,
                from_email=m.from_email,
                preview=m.preview,
                received_at=m.received_at,
                sent_at=m.sent_at,
                size=m.size,
                seen=m.seen,
                flagged=m.flagged,
                answered=m.answered,
                forwarded=is_forwarded(m.flags),
                has_attachments=m.has_attachments,
                thread_count=thread_counts.get(m.thread_id, 1) if m.thread_id else 1,
                ai_category=classification.category if classification else None,
                ai_priority=classification.priority if classification else None,
                ai_summary=payload.get("summary_sk") if classification else None,
                ai_language=classification.language if classification else None,
                ai_confidence=payload.get("confidence") if classification else None,
                ai_note_codes=list(payload.get("note_codes") or []) if classification else [],
            )
        )

    return ListOut(
        mode="list",
        total=total,
        page=page,
        page_size=size,
        prefs=prefs,
        messages=messages_out,
    )


async def _list_threads(
    db: DB,
    mailbox: Mailbox,
    folder: FolderMeta,
    prefs: ListPrefs,
    page: int,
    size: int,
    filter_name: FilterName,
    q: str | None,
) -> ListOut:
    # threads that have at least one message in this folder
    msg_cond = [Message.folder_id == folder.id, Message.deleted.is_(False)]
    if filter_name == "unread":
        msg_cond.append(Message.seen.is_(False))
    elif filter_name == "flagged":
        msg_cond.append(Message.flagged.is_(True))
    elif filter_name == "attachments":
        msg_cond.append(Message.has_attachments.is_(True))
    if q:
        like = f"%{q.strip()}%"
        msg_cond.append(or_(Message.subject.ilike(like), Message.from_email.ilike(like), Message.from_name.ilike(like)))

    thread_ids_q = select(Message.thread_id).where(and_(*msg_cond), Message.thread_id.is_not(None)).distinct()
    total = int(await db.scalar(select(func.count()).select_from(thread_ids_q.subquery())) or 0)
    order = (
        desc(Thread.last_message_at).nulls_last()
        if prefs.sort_dir == "desc"
        else asc(Thread.last_message_at).nulls_last()
    )
    threads = list(
        (
            await db.execute(
                select(Thread)
                .where(Thread.mailbox_id == mailbox.id, Thread.id.in_(thread_ids_q))
                .order_by(order)
                .offset((page - 1) * size)
                .limit(size)
            )
        ).scalars()
    )
    items: list[ThreadListItem] = []
    for th in threads:
        latest = await db.scalar(
            select(Message).where(Message.thread_id == th.id).order_by(desc(Message.received_at).nulls_last()).limit(1)
        )
        items.append(
            ThreadListItem(
                id=str(th.id),
                subject=th.subject,
                from_name=latest.from_name if latest else None,
                from_email=latest.from_email if latest else None,
                preview=latest.preview if latest else None,
                last_message_at=th.last_message_at,
                message_count=th.message_count,
                unread_count=th.unread_count,
                flagged=th.flagged,
                has_attachments=th.has_attachments,
                status=th.status,
                snoozed_until=th.snoozed_until,
                assignee_id=str(th.assignee_id) if th.assignee_id else None,
                latest_message_id=str(latest.id) if latest else None,
            )
        )
    return ListOut(mode="conversations", total=total, page=page, page_size=size, prefs=prefs, threads=items)


@router.get("/mailboxes/{ref}/messages/{message_id}")
async def get_message(
    ref: str,
    message_id: uuid.UUID,
    request: Request,
    ctx: Auth,
    db: DB,
    settings: SettingsDep,
    mark_read: bool = True,
) -> MessageDetail:
    mailbox = await _mailbox(db, ctx, ref)
    message = await db.get(Message, message_id)
    if message is None or message.mailbox_id != mailbox.id:
        raise fail(404, "message_not_found")
    creds = await credentials_for(db, mailbox, settings)
    if creds is not None and settings.mail_sync_enabled and settings.sync_host_allowed(mailbox.imap_host):
        try:
            await ensure_body(db, settings, mailbox, message, creds)
            await db.commit()
        except SyncAuthError:
            await mark_auth_failed(db, mailbox, now=datetime.now(UTC))
            await db.commit()
            raise HTTPException(
                status_code=401, detail={"code": "unauthenticated", "reason": "password_changed"}
            ) from None
        except SyncUnavailable:
            pass  # show whatever we have

    if mark_read and not message.seen and ctx.session.active_person_id is not None:
        folder = await db.get(FolderMeta, message.folder_id)
        if folder is not None:
            try:
                await _run(
                    request,
                    db,
                    settings,
                    mailbox,
                    MsgAction.mark_seen,
                    folder,
                    [message],
                    audit_action="mail.message_seen",
                    details={"uid": message.uid, "folder": folder.name},
                )
            except HTTPException:
                pass

    atts = await load_attachments(db, message.id)
    thread = await db.get(Thread, message.thread_id) if message.thread_id else None
    ui = await get_ui_prefs(db, ctx.session.active_person_id)
    html, remote_offered, remote_auto = await _render_message_html(
        db,
        settings,
        ref=ref,
        message=message,
        atts=atts,
        remote_mode=ui.remote_images,
        person_id=ctx.session.active_person_id,
    )
    return MessageDetail(
        id=str(message.id),
        thread_id=str(message.thread_id) if message.thread_id else None,
        folder_id=str(message.folder_id),
        uid=message.uid,
        message_id=message.message_id,
        subject=message.subject,
        from_name=message.from_name,
        from_email=message.from_email,
        to=_addrs(message.to_addrs),
        cc=_addrs(message.cc_addrs),
        sent_at=message.sent_at,
        received_at=message.received_at,
        size=message.size,
        seen=message.seen,
        flagged=message.flagged,
        answered=message.answered,
        body_text=message.body_text,
        body_html_sanitized=html,
        attachments=[
            AttachmentOut(
                id=str(a.id),
                filename=a.filename,
                content_type=a.content_type,
                size=a.size,
                is_inline=a.is_inline,
                av_status=a.av_status,
            )
            for a in atts
        ],
        auth_results=message.auth_results,
        thread_status=thread.status if thread else None,
        snoozed_until=thread.snoozed_until if thread else None,
        assignee_id=str(thread.assignee_id) if thread and thread.assignee_id else None,
        remote_images_offered=remote_offered,
        remote_images_auto=remote_auto,
        remote_images_mode=ui.remote_images,
        **(await _message_ai_fields(db, settings, message)),
    )


async def _contact_emails_for_person(db: DB, person_id: uuid.UUID | None) -> set[str]:
    if person_id is None:
        return set()
    from app.contacts.models import AddressBook, Contact
    from app.contacts.service import ensure_default_books

    await ensure_default_books(db, person_id)
    books = (
        await db.execute(
            select(AddressBook.id).where(
                or_(
                    and_(AddressBook.kind == "personal", AddressBook.owner_person_id == person_id),
                    AddressBook.kind == "shared",
                )
            )
        )
    ).scalars()
    book_ids = list(books)
    if not book_ids:
        return set()
    out: set[str] = set()
    rows = (await db.execute(select(Contact.emails).where(Contact.address_book_id.in_(book_ids)))).scalars()
    for emails in rows:
        for entry in emails or []:
            em = str(entry.get("email") or "").strip().lower()
            if em:
                out.add(em)
    return out


async def _render_message_html(
    db: DB,
    settings: Settings,
    *,
    ref: str,
    message: Message,
    atts: list[Attachment],
    remote_mode: Literal["never", "known", "always"],
    person_id: uuid.UUID | None,
) -> tuple[str | None, bool, bool]:
    """Rewrite cid: → inline URLs (B5) and sign remote images for the proxy (B6)."""
    from app.mail.cid_rewrite import normalize_cid, rewrite_cid_images
    from app.mail.remote_images import (
        html_has_remote_placeholder,
        proxy_signature_images,
        should_offer_remote_images,
        sign_remote_image_attrs,
    )

    html = message.body_html_sanitized
    if not html:
        return None, False, False
    cid_map = {
        normalize_cid(a.content_id): str(a.id)
        for a in atts
        if a.content_id and (a.content_type or "").lower().startswith("image/")
    }
    html = rewrite_cid_images(html, mailbox_ref=ref, cid_to_attachment_id=cid_map)
    html = proxy_signature_images(html, settings)
    # Like Roundcube: blocked remote images always get the bar ("Zobraziť obrázky · Vždy od tohto odosielateľa").
    # The setting only decides whether they load without a click.
    offered = html_has_remote_placeholder(html)
    contacts = await _contact_emails_for_person(db, person_id)
    auto = offered and should_offer_remote_images(
        remote_mode,
        from_email=message.from_email,
        contact_emails=contacts,
        internal_domains=list(settings.internal_domain_list),
    )
    if offered:
        html = sign_remote_image_attrs(html, settings)
    return html, offered, auto


async def _message_ai_fields(db: DB, settings: Settings, message: Message) -> dict[str, Any]:
    from app.ai.classify import phishing_signals

    cls = await db.scalar(select(Classification).where(Classification.message_id == message.id).limit(1))
    payload = (cls.payload if cls else None) or {}
    notes = list(payload.get("note_codes") or [])
    for code in phishing_signals(
        from_name=message.from_name,
        from_email=message.from_email,
        auth_results=message.auth_results,
        body_text=message.body_text,
        internal_domains=settings.internal_domain_list,
    ):
        if code not in notes:
            notes.append(code)
    return {
        "ai_category": cls.category if cls else None,
        "ai_summary": payload.get("summary_sk"),
        "ai_language": cls.language if cls else None,
        "security_notes": notes,
    }


@router.patch("/mailboxes/{ref}/messages/{message_id}/flags")
async def patch_flags(
    ref: str,
    message_id: uuid.UUID,
    body: FlagIn,
    request: Request,
    ctx: Auth,
    person: ActivePerson,
    db: DB,
    settings: SettingsDep,
) -> MessageDetail:
    mailbox = await _mailbox(db, ctx, ref)
    message = await db.get(Message, message_id)
    if message is None or message.mailbox_id != mailbox.id:
        raise fail(404, "message_not_found")
    folder = await _folder(db, mailbox, message.folder_id)
    if body.seen is True:
        await _run(
            request,
            db,
            settings,
            mailbox,
            MsgAction.mark_seen,
            folder,
            [message],
            audit_action="mail.message_seen",
            details={"uid": message.uid},
        )
    elif body.seen is False:
        await _run(
            request,
            db,
            settings,
            mailbox,
            MsgAction.mark_unseen,
            folder,
            [message],
            audit_action="mail.message_unseen",
            details={"uid": message.uid},
        )
    if body.flagged is True:
        await _run(
            request,
            db,
            settings,
            mailbox,
            MsgAction.flag,
            folder,
            [message],
            audit_action="mail.message_flagged",
            details={"uid": message.uid},
        )
    elif body.flagged is False:
        await _run(
            request,
            db,
            settings,
            mailbox,
            MsgAction.unflag,
            folder,
            [message],
            audit_action="mail.message_unflagged",
            details={"uid": message.uid},
        )
    await db.refresh(message)
    return await get_message(ref, message_id, request, ctx, db, settings, mark_read=False)


@router.post("/mailboxes/{ref}/messages/bulk")
async def bulk(
    ref: str,
    body: BulkIn,
    request: Request,
    ctx: Auth,
    person: ActivePerson,
    db: DB,
    settings: SettingsDep,
) -> dict[str, int]:
    if not body.message_ids:
        return {"ok": 0}
    if len(body.message_ids) > MAX_BULK:
        raise fail(422, "bulk_too_large")
    mailbox = await _mailbox(db, ctx, ref)
    messages = list(
        (
            await db.execute(select(Message).where(Message.id.in_(body.message_ids), Message.mailbox_id == mailbox.id))
        ).scalars()
    )
    if not messages:
        return {"ok": 0}

    if body.action == "done":
        thread_ids = {m.thread_id for m in messages if m.thread_id}
        for tid in thread_ids:
            th = await db.get(Thread, tid)
            if th:
                th.status = "done"
                th.snoozed_until = None
        audit(
            db,
            "mail.threads_done",
            object_type="mailbox",
            object_id=str(mailbox.id),
            ip=client_ip(request),
            details={"n": len(thread_ids)},
        )
        await db.commit()
        return {"ok": len(thread_ids)}

    dest: FolderMeta | None = None
    action: MsgAction
    if body.action == "mark_seen":
        action = MsgAction.mark_seen
    elif body.action == "mark_unseen":
        action = MsgAction.mark_unseen
    elif body.action == "flag":
        action = MsgAction.flag
    elif body.action == "unflag":
        action = MsgAction.unflag
    elif body.action == "delete":
        action = MsgAction.delete
        dest = await _special_folder(db, mailbox, "trash")
        if dest is None:
            raise fail(409, "folder_not_found")
    elif body.action == "purge":
        # Shift+Delete (Roundcube): \Deleted + UID EXPUNGE of these messages, no copy in Kôš; the UI confirms first.
        action = MsgAction.expunge
    elif body.action == "junk":
        action = MsgAction.junk
        dest = await _special_folder(db, mailbox, "junk")
        if dest is None:
            raise fail(409, "folder_not_found")
    elif body.action == "archive":
        action = MsgAction.archive
        dest = await _own_named(db, mailbox, "Archív") or await _own_named(db, mailbox, "Archive")
        if dest is None:
            raise fail(409, "folder_not_found")
    elif body.action == "move":
        action = MsgAction.move
        if body.dest_folder_id is None:
            raise fail(422, "dest_required")
        dest = await _folder(db, mailbox, body.dest_folder_id)
    else:
        raise fail(422, "unknown_action")

    # group by source folder
    by_folder: dict[uuid.UUID, list[Message]] = {}
    for m in messages:
        by_folder.setdefault(m.folder_id, []).append(m)
    done = 0
    for folder_id, group in by_folder.items():
        folder = await _folder(db, mailbox, folder_id)
        folder_action, folder_dest = action, dest
        if action is MsgAction.delete and dest is not None and folder.id == dest.id:
            # Already in Kôš: delete permanently (a MOVE to the same folder is refused by the server).
            folder_action, folder_dest = MsgAction.expunge, None
        await _run(
            request,
            db,
            settings,
            mailbox,
            folder_action,
            folder,
            group,
            dest=folder_dest,
            audit_action=f"mail.bulk_{body.action}",
            details={"n": len(group), "folder": folder.name},
        )
        done += len(group)
    return {"ok": done}


@router.post("/mailboxes/{ref}/threads/{thread_id}/snooze")
async def snooze(
    ref: str, thread_id: uuid.UUID, body: SnoozeIn, request: Request, ctx: Auth, person: ActivePerson, db: DB
) -> dict[str, str]:
    mailbox = await _mailbox(db, ctx, ref)
    thread = await db.get(Thread, thread_id)
    if thread is None or thread.mailbox_id != mailbox.id:
        raise fail(404, "thread_not_found")
    if body.until is None:
        thread.status = "open"
        thread.snoozed_until = None
    else:
        thread.status = "snoozed"
        thread.snoozed_until = body.until
    audit(
        db,
        "mail.thread_snoozed",
        object_type="thread",
        object_id=str(thread.id),
        ip=client_ip(request),
        details={"until": body.until.isoformat() if body.until else None},
    )
    await db.commit()
    return {"ok": "1", "status": thread.status}


@router.post("/mailboxes/{ref}/threads/{thread_id}/assign")
async def assign(
    ref: str, thread_id: uuid.UUID, body: AssignIn, request: Request, ctx: Auth, person: ActivePerson, db: DB
) -> dict[str, str | None]:
    mailbox = await _mailbox(db, ctx, ref)
    thread = await db.get(Thread, thread_id)
    if thread is None or thread.mailbox_id != mailbox.id:
        raise fail(404, "thread_not_found")
    thread.assignee_id = body.person_id
    if body.person_id is None:
        thread.assigned_by_id = None
        thread.assigned_at = None
    else:
        thread.assigned_by_id = person.id
        thread.assigned_at = datetime.now(UTC)
    audit(
        db,
        "mail.thread_assigned",
        object_type="thread",
        object_id=str(thread.id),
        ip=client_ip(request),
        details={"assignee_id": str(body.person_id) if body.person_id else None},
    )
    await db.commit()
    return {"ok": "1", "assignee_id": str(thread.assignee_id) if thread.assignee_id else None}


@router.get("/mailboxes/{ref}/messages/{message_id}/source")
async def message_source(ref: str, message_id: uuid.UUID, ctx: Auth, db: DB, settings: SettingsDep) -> Response:
    mailbox = await _mailbox(db, ctx, ref)
    message = await db.get(Message, message_id)
    if message is None or message.mailbox_id != mailbox.id:
        raise fail(404, "message_not_found")
    if not message.raw_storage_key:
        creds = await credentials_for(db, mailbox, settings)
        if creds is None:
            raise fail(409, "mailbox_credentials_missing")
        await ensure_body(db, settings, mailbox, message, creds)
        await db.commit()
    raw = storage.get_bytes(settings, message.raw_storage_key or "") if message.raw_storage_key else None
    if raw is None:
        raise fail(404, "source_unavailable")
    return PlainTextResponse(raw.decode("utf-8", errors="replace"), media_type="text/plain; charset=utf-8")


@router.get("/mailboxes/{ref}/attachments/{attachment_id}")
async def download_attachment(ref: str, attachment_id: uuid.UUID, ctx: Auth, db: DB, settings: SettingsDep) -> Response:
    mailbox = await _mailbox(db, ctx, ref)
    att = await db.get(Attachment, attachment_id)
    if att is None:
        raise fail(404, "attachment_not_found")
    message = await db.get(Message, att.message_id)
    if message is None or message.mailbox_id != mailbox.id:
        raise fail(404, "attachment_not_found")
    if att.av_status == "infected":
        raise fail(403, "attachment_infected")
    data = storage.get_bytes(settings, att.storage_key)
    if data is None:
        raise fail(404, "attachment_not_found")
    headers = {"Content-Disposition": content_disposition_attachment(att.filename)}
    return Response(content=data, media_type=att.content_type, headers=headers)


@router.get("/mailboxes/{ref}/attachments/{attachment_id}/inline")
async def inline_attachment(ref: str, attachment_id: uuid.UUID, ctx: Auth, db: DB, settings: SettingsDep) -> Response:
    """Serve an inline image part for cid: rewrite (pilot #18 B5). image/* only."""
    mailbox = await _mailbox(db, ctx, ref)
    att = await db.get(Attachment, attachment_id)
    if att is None:
        raise fail(404, "attachment_not_found")
    message = await db.get(Message, att.message_id)
    if message is None or message.mailbox_id != mailbox.id:
        raise fail(404, "attachment_not_found")
    if att.av_status == "infected":
        raise fail(403, "attachment_infected")
    ctype = (att.content_type or "").split(";")[0].strip().lower()
    if not ctype.startswith("image/") or ctype in {"image/svg+xml", "image/svg"}:
        raise fail(415, "not_inline_image")
    data = storage.get_bytes(settings, att.storage_key)
    if data is None:
        raise fail(404, "attachment_not_found")
    headers = {
        "Content-Disposition": f'inline; filename="{att.filename.replace(chr(34), "")}"',
        "Cache-Control": "private, max-age=3600",
        "X-Content-Type-Options": "nosniff",
    }
    return Response(content=data, media_type=ctype, headers=headers)


@router.get("/image-proxy")
async def image_proxy(
    ctx: Auth,
    settings: SettingsDep,
    u: Annotated[str, Query(min_length=1, max_length=2048)],
    sig: Annotated[str, Query(min_length=16, max_length=128)],
) -> Response:
    """HMAC-signed remote image proxy (pilot #18 B6). CSP stays without https: in img-src."""
    from app.mail.image_proxy import ImageProxyError, fetch_proxied_image

    _ = ctx  # auth required — anonymous open proxy forbidden
    try:
        body, content_type = await fetch_proxied_image(settings, u, sig)
    except ImageProxyError as exc:
        raise fail(exc.status, exc.code) from None
    return Response(
        content=body,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=600", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/prefs")
async def get_prefs(ctx: Auth, db: DB) -> dict[str, Any]:
    pid = ctx.session.active_person_id
    return {
        "list": (await get_list_prefs(db, pid)).model_dump(),
        "ui": (await get_ui_prefs(db, pid)).model_dump(),
        # Settings 01e „Klávesové skratky zapnuté“ (#93); the shell reads it with the other mail prefs.
        "shortcuts": {"enabled": await shortcuts_enabled(db, pid)},
    }


@router.put("/prefs")
async def put_prefs(body: PrefsIn, ctx: Auth, person: ActivePerson, db: DB) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if body.list is not None:
        out["list"] = await save_section(db, person.id, "prefs.list", body.list.model_dump())
    else:
        out["list"] = (await get_list_prefs(db, person.id)).model_dump()
    if body.ui is not None:
        out["ui"] = await save_section(db, person.id, "prefs.ui", body.ui.model_dump())
    else:
        out["ui"] = (await get_ui_prefs(db, person.id)).model_dump()
    await db.commit()
    return out
