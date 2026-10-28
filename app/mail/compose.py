"""Compose drafts: create from reply/forward/new, autosave, send with undo (Phase 1e)."""

from __future__ import annotations

import html as html_lib
import re
import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path
from typing import Any, Literal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Branch, Person
from app.core.audit import audit
from app.core.config import Settings
from app.mail import storage
from app.mail.actions import add_flag_async
from app.mail.compose_html import assemble_outgoing_html
from app.mail.compose_models import ComposeAttachment, ComposeDraft, Identity
from app.mail.flags import ANSWERED_FLAG, FORWARDED_FLAG, apply_local_flag
from app.mail.imap_append import append_to_sent_async, delete_draft_uid_async, save_draft_replace_async
from app.mail.models import FolderMeta, Mailbox, Message
from app.mail.signature import LOGO_CID, PHOTO_CID, html_to_text, render_signature
from app.mail.signature_images import add_related_images, cids_in_html, image_dicts, sniff_image_type
from app.mail.smtp import SmtpError, send_message, smtp_endpoint
from app.mail.sync import (
    Credentials,
    SyncAuthError,
    SyncUnavailable,
    credentials_for,
    mark_auth_failed,
    server_of,
    special_folder_name,
    sync_mailbox,
)

log = structlog.get_logger(__name__)

Mode = Literal["new", "reply", "reply_all", "forward"]
Priority = Literal["low", "normal", "high"]

_PLACEHOLDER = re.compile(r"\[\[DOPLNIŤ\]\]", re.I)
_ATTACH_MENTION = re.compile(r"\b(príloh|priloh|attachment|attach|pdf|docx?)\w*", re.I)


def _addrs(raw: list[dict[str, Any]] | None) -> list[dict[str, str | None]]:
    out: list[dict[str, str | None]] = []
    for item in raw or []:
        email = (item.get("email") or "").strip().lower()
        if email:
            out.append({"name": item.get("name"), "email": email})
    return out


async def ensure_default_identity(db: AsyncSession, mailbox: Mailbox, display_name: str | None = None) -> Identity:
    existing = await db.scalar(
        select(Identity).where(Identity.mailbox_id == mailbox.id).order_by(Identity.is_default.desc())
    )
    if existing:
        return existing
    identity = Identity(
        mailbox_id=mailbox.id,
        display_name=display_name or mailbox.email.split("@")[0],
        email=mailbox.email,
        organization="Smart s.r.o.",
        is_default=True,
    )
    db.add(identity)
    await db.flush()
    return identity


async def create_draft(
    db: AsyncSession,
    settings: Settings,
    *,
    mailbox: Mailbox,
    account_id: uuid.UUID,
    person: Person | None,
    branch: Branch | None,
    mode: Mode = "new",
    source: Message | None = None,
) -> ComposeDraft:
    identity = await ensure_default_identity(db, mailbox, person.full_name if person else None)
    to: list[dict[str, str | None]] = []
    cc: list[dict[str, str | None]] = []
    subject = ""
    if source and mode in ("reply", "reply_all"):
        to = [{"name": source.from_name, "email": source.from_email}]
        if mode == "reply_all":
            for a in source.to_addrs or []:
                if (a.get("email") or "").lower() != mailbox.email:
                    cc.append({"name": a.get("name"), "email": a.get("email")})
            cc.extend(_addrs(source.cc_addrs))
        subj = source.subject or ""
        subject = subj if subj.lower().startswith("re:") else f"Re: {subj}"
    elif source and mode == "forward":
        subj = source.subject or ""
        subject = subj if subj.lower().startswith("fwd:") else f"Fwd: {subj}"

    quoted = ""
    if source and mode in ("reply", "reply_all", "forward"):
        if source.body_html_sanitized:
            quoted = source.body_html_sanitized
        elif source.body_text:
            quoted = f"<pre>{html_lib.escape(source.body_text)}</pre>"
    signature = render_signature(person=person, branch=branch, identity=identity, email=identity.email, language="sk")
    body_html = assemble_outgoing_html(
        user_html="<p></p>",
        quote_html=quoted or None,
        signature_html=signature or None,
        mode=mode,
        settings=settings,
    )

    draft = ComposeDraft(
        mailbox_id=mailbox.id,
        account_id=account_id,
        person_id=person.id if person else None,
        identity_id=identity.id,
        mode=mode,
        in_reply_to_message_id=source.id if source else None,
        thread_id=source.thread_id if source else None,
        to_addrs=to,
        cc_addrs=cc,
        subject=subject,
        body_html=body_html,
        body_text=html_to_text(body_html),
        signature_person_id=person.id if person else None,
        include_signature=True,
        status="editing",
    )
    db.add(draft)
    await db.flush()
    audit(
        db,
        action="mail.compose_created",
        account_id=account_id,
        person_id=person.id if person else None,
        details={"draft_id": str(draft.id), "mode": mode},
    )
    return draft


def pre_send_checks(draft: ComposeDraft, settings: Settings) -> list[dict[str, Any]]:
    """W4b checks. Blocking items disable 'Odoslať aj tak'."""
    issues: list[dict[str, Any]] = []
    if not draft.to_addrs:
        issues.append({"code": "no_recipients", "blocking": True, "message": "missing_to"})
    if _PLACEHOLDER.search(draft.body_html or "") or _PLACEHOLDER.search(draft.body_text or ""):
        issues.append({"code": "placeholder", "blocking": True, "message": "placeholder"})
    body = f"{draft.subject}\n{draft.body_text}\n{draft.body_html}"
    if _ATTACH_MENTION.search(body):
        # attachment presence is checked by caller with attachment count
        issues.append({"code": "attachment_mentioned", "blocking": False, "message": "attachment_mentioned"})
    domains = {(a.get("email") or "").rsplit("@", 1)[-1] for a in draft.to_addrs + draft.cc_addrs}
    external = [d for d in domains if d and not settings.is_internal_address(f"x@{d}")]
    if external:
        issues.append({"code": "external_recipient", "blocking": False, "message": "external"})
    return issues


def _logo_png() -> bytes | None:
    path = Path(__file__).resolve().parents[2] / "design" / "brand" / "logo-smart.png"
    if path.is_file():
        return path.read_bytes()
    return None


async def _signature_blobs(
    db: AsyncSession,
    settings: Settings,
    draft: ComposeDraft,
    identity: Identity,
    html: str,
) -> list[tuple[str, bytes, str]]:
    """Inline CID parts for signature images referenced by the HTML body (D22)."""
    wanted = cids_in_html(html)
    if not wanted:
        return []
    records = image_dicts(identity.signature_images)
    branch = await db.scalar(select(Branch).where(Branch.mailbox_id == draft.mailbox_id))
    if branch is not None:
        records.extend(image_dicts(branch.signature_images))
    by_cid = {str(rec["cid"]): rec for rec in records}
    blobs: list[tuple[str, bytes, str]] = []
    for cid in wanted:
        if cid == LOGO_CID:
            data = _logo_png()
            if data:
                blobs.append((cid, data, "image/png"))
            continue
        if cid == PHOTO_CID:
            person_id = draft.signature_person_id or draft.person_id
            person = await db.get(Person, person_id) if person_id else None
            if person is not None and person.photo_key:
                data = storage.get_bytes(settings, person.photo_key)
                if data:
                    blobs.append((cid, data, sniff_image_type(data)))
            continue
        rec = by_cid.get(cid)
        if rec is None:
            continue
        data = storage.get_bytes(settings, str(rec.get("storage_key") or ""))
        if data:
            blobs.append((cid, data, str(rec.get("content_type") or "image/png")))
    return blobs


async def rendered_signature(db: AsyncSession, draft: ComposeDraft) -> str:
    """Signature for this draft from the template or the stored per-message override."""
    if not draft.include_signature:
        return ""
    identity = await db.get(Identity, draft.identity_id) if draft.identity_id else None
    person_id = draft.signature_person_id or draft.person_id
    person = await db.get(Person, person_id) if person_id else None
    branch = None
    if person is not None and person.branch_id is not None:
        branch = await db.get(Branch, person.branch_id)
    if branch is None:
        branch = await db.scalar(select(Branch).where(Branch.mailbox_id == draft.mailbox_id))
    return render_signature(
        person=person,
        branch=branch,
        identity=identity,
        email=identity.email if identity else "",
        override_html=draft.signature_html_override,
    )


async def rehydrate_draft_html(db: AsyncSession, settings: Settings, draft: ComposeDraft) -> None:
    """Replace editor signature and quote with the server copies (issue #28)."""
    quote: str | None = None
    if draft.mode in {"reply", "reply_all", "forward"} and draft.in_reply_to_message_id is not None:
        source = await db.get(Message, draft.in_reply_to_message_id)
        if source is not None:
            if source.body_html_sanitized:
                quote = source.body_html_sanitized
            elif source.body_text:
                quote = f"<pre>{html_lib.escape(source.body_text)}</pre>"
    signature = await rendered_signature(db, draft)
    draft.body_html = assemble_outgoing_html(
        user_html=draft.body_html or "",
        quote_html=quote,
        signature_html=signature or None,
        mode=draft.mode,
        settings=settings,
    )
    draft.body_text = html_to_text(draft.body_html)


async def build_mime(
    db: AsyncSession,
    settings: Settings,
    draft: ComposeDraft,
    identity: Identity,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = f"{identity.display_name} <{identity.email}>"
    msg["To"] = ", ".join(
        f"{a['name']} <{a['email']}>" if a.get("name") else (a.get("email") or "") for a in draft.to_addrs
    )
    if draft.cc_addrs:
        msg["Cc"] = ", ".join(a.get("email") or "" for a in draft.cc_addrs)
    msg["Subject"] = draft.subject or ""
    msg["Date"] = format_datetime(datetime.now(UTC))
    mid = make_msgid(domain=identity.email.split("@")[-1])
    msg["Message-ID"] = mid
    if draft.priority == "high":
        msg["X-Priority"] = "1"
        msg["Importance"] = "high"
    elif draft.priority == "low":
        msg["X-Priority"] = "5"
        msg["Importance"] = "low"
    if draft.request_mdn:
        msg["Disposition-Notification-To"] = identity.email
    if draft.in_reply_to_message_id:
        source = await db.get(Message, draft.in_reply_to_message_id)
        if source and source.message_id:
            msg["In-Reply-To"] = source.message_id
            refs = (source.references or "").strip()
            msg["References"] = f"{refs} {source.message_id}".strip() if refs else source.message_id

    await rehydrate_draft_html(db, settings, draft)
    html = draft.body_html or ""
    text = draft.body_text or html_to_text(html)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    blobs = await _signature_blobs(db, settings, draft, identity, html)
    seen = {cid for cid, _data, _ctype in blobs}

    atts = list((await db.execute(select(ComposeAttachment).where(ComposeAttachment.draft_id == draft.id))).scalars())
    regular: list[ComposeAttachment] = []
    for att in atts:
        if att.is_inline and att.content_id:
            if att.content_id in seen:
                continue
            data = storage.get_bytes(settings, att.storage_key) or b""
            if data:
                blobs.append((att.content_id, data, att.content_type or "image/png"))
                seen.add(att.content_id)
            continue
        regular.append(att)
    add_related_images(msg, blobs)
    for att in regular:
        payload = storage.get_bytes(settings, att.storage_key) or b""
        maintype, _, subtype = (att.content_type or "application/octet-stream").partition("/")
        msg.add_attachment(
            payload,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=att.filename,
        )
    draft.final_message_id = mid
    return msg


async def queue_send(
    db: AsyncSession,
    settings: Settings,
    draft: ComposeDraft,
    *,
    account_id: uuid.UUID,
    person_id: uuid.UUID | None,
    force: bool = False,
) -> ComposeDraft:
    checks = pre_send_checks(draft, settings)
    atts = list((await db.execute(select(ComposeAttachment).where(ComposeAttachment.draft_id == draft.id))).scalars())
    if any(c["code"] == "attachment_mentioned" for c in checks) and not atts:
        pass  # keep warning
    else:
        checks = [c for c in checks if c["code"] != "attachment_mentioned" or not atts]
    blocking = [c for c in checks if c["blocking"]]
    if blocking and not force:
        raise ValueError("pre_send_blocked")
    delay = settings.undo_send_seconds
    draft.status = "queued"
    draft.undo_until = datetime.now(UTC) + timedelta(seconds=delay) if delay > 0 else None
    draft.send_error = None
    audit(
        db,
        action="mail.compose_queued",
        account_id=account_id,
        person_id=person_id,
        details={"draft_id": str(draft.id), "undo_seconds": delay},
    )
    await db.flush()
    return draft


async def cancel_send(
    db: AsyncSession, draft: ComposeDraft, *, account_id: uuid.UUID, person_id: uuid.UUID | None
) -> ComposeDraft:
    if draft.status != "queued":
        raise ValueError("not_queued")
    draft.status = "editing"
    draft.undo_until = None
    audit(
        db,
        action="mail.compose_undo",
        account_id=account_id,
        person_id=person_id,
        details={"draft_id": str(draft.id)},
    )
    await db.flush()
    return draft


async def sync_draft_to_imap(db: AsyncSession, settings: Settings, draft: ComposeDraft) -> None:
    """APPEND the draft to IMAP Koncepty / \\Drafts and drop the previous UID (CLAUDE.md §5).

    Failures are logged only — local autosave must still succeed when IMAP is down.
    """
    if draft.status not in {"editing", "failed", "scheduled"}:
        return
    mailbox = await db.get(Mailbox, draft.mailbox_id)
    if mailbox is None:
        return
    identity = await db.get(Identity, draft.identity_id) if draft.identity_id else None
    if identity is None:
        return
    creds = await credentials_for(db, mailbox, settings)
    if creds is None:
        return
    if not settings.sync_host_allowed(mailbox.imap_host):
        return
    try:
        mime = await build_mime(db, settings, draft, identity)
        new_uid = await save_draft_replace_async(
            server_of(mailbox, settings),
            creds,
            mime,
            previous_uid=draft.imap_draft_uid,
        )
        if new_uid is not None:
            draft.imap_draft_uid = new_uid
            await db.flush()
    except SyncAuthError:
        await mark_auth_failed(db, mailbox, now=datetime.now(UTC))
        log.warning("compose.draft_imap_auth_failed", draft_id=str(draft.id))
    except SyncUnavailable as exc:
        log.warning("compose.draft_imap_unavailable", draft_id=str(draft.id), error=str(exc))


async def mark_reply_or_forward(
    db: AsyncSession,
    settings: Settings,
    draft: ComposeDraft,
    mailbox: Mailbox,
    creds: Credentials,
) -> None:
    """After SMTP: ``\\Answered`` on a reply, ``$Forwarded`` on a forward (IMAP + local list)."""
    if draft.mode not in {"reply", "reply_all", "forward"} or draft.in_reply_to_message_id is None:
        return
    source = await db.get(Message, draft.in_reply_to_message_id)
    if source is None:
        return
    folder = await db.get(FolderMeta, source.folder_id)
    if folder is None:
        return
    flag = FORWARDED_FLAG if draft.mode == "forward" else ANSWERED_FLAG
    try:
        await add_flag_async(server_of(mailbox, settings), creds, folder.name, int(source.uid), flag)
    except SyncAuthError:
        log.warning("compose.flag_auth_failed", draft_id=str(draft.id))
        return
    except SyncUnavailable as exc:
        log.warning("compose.flag_failed", draft_id=str(draft.id), error=str(exc))
        return
    apply_local_flag(source, flag)
    await db.commit()


async def execute_send(db: AsyncSession, settings: Settings, draft_id: uuid.UUID) -> str:
    """SMTP with mailbox AUTH, then APPEND to \\Sent. APPEND failure never re-sends (GitHub #20)."""
    draft = await db.get(ComposeDraft, draft_id)
    if draft is None:
        return "missing"
    if draft.status == "editing":
        return "undone"
    if draft.status == "sent":
        return "already"
    if draft.status not in {"queued", "scheduled", "sending"}:
        return draft.status
    if draft.undo_until and datetime.now(UTC) < draft.undo_until and draft.status == "queued":
        return "waiting"
    draft.status = "sending"
    await db.flush()
    identity = await db.get(Identity, draft.identity_id) if draft.identity_id else None
    mailbox = await db.get(Mailbox, draft.mailbox_id)
    if identity is None or mailbox is None:
        draft.status = "failed"
        draft.send_error = "identity_missing"
        await db.commit()
        return "failed"

    creds = await credentials_for(db, mailbox, settings)
    if creds is None:
        draft.status = "failed"
        draft.send_error = "no_credentials"
        await db.commit()
        return "failed"

    host, port, security = smtp_endpoint(mailbox, settings)
    mime: EmailMessage | None = None
    try:
        mime = await build_mime(db, settings, draft, identity)
        await send_message(
            settings,
            mime,
            host=host,
            port=port,
            security=security,
            username=creds.email,
            password=creds.password,
            mail_from=identity.email,
        )
    except SmtpError as exc:
        draft.status = "failed"
        draft.send_error = exc.reason[:200]
        if exc.reason == "auth_failed" or exc.reason.startswith("auth_failed"):
            await mark_auth_failed(db, mailbox, now=datetime.now(UTC))
        await db.commit()
        return "failed"

    # SMTP accepted the message — commit sent before IMAP APPEND so a store failure cannot resend.
    draft.status = "sent"
    draft.undo_until = None
    draft.send_error = None
    audit(
        db,
        action="mail.compose_sent",
        account_id=draft.account_id,
        person_id=draft.person_id,
        details={"draft_id": str(draft.id), "smtp_host": host},
    )
    await db.commit()

    await mark_reply_or_forward(db, settings, draft, mailbox, creds)

    if draft.save_sent and mime is not None:
        try:
            known = await special_folder_name(db, mailbox.id, "sent")
            appended = await append_to_sent_async(server_of(mailbox, settings), creds, mime, known_folder=known)
            try:
                await sync_mailbox(db, mailbox, settings, only_names=frozenset({appended.folder}))
            except Exception as exc:
                log.warning("compose.sent_sync_failed", draft_id=str(draft.id), error=type(exc).__name__)
        except SyncAuthError:
            draft.send_error = "append_failed"
            await mark_auth_failed(db, mailbox, now=datetime.now(UTC))
            await db.commit()
            log.warning("compose.sent_append_auth_failed", draft_id=str(draft.id))
        except SyncUnavailable as exc:
            draft.send_error = "append_failed"
            await db.commit()
            log.warning("compose.sent_append_failed", draft_id=str(draft.id), error=str(exc))

    if draft.imap_draft_uid is not None:
        try:
            await delete_draft_uid_async(server_of(mailbox, settings), creds, draft.imap_draft_uid)
            draft.imap_draft_uid = None
            await db.commit()
        except (SyncAuthError, SyncUnavailable) as exc:
            log.warning("compose.draft_cleanup_failed", draft_id=str(draft.id), error=type(exc).__name__)

    return "sent"
