"""Compose drafts: create from reply/forward/new, autosave, send with undo (Phase 1e)."""

from __future__ import annotations

import html as html_lib
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path
from typing import Any, Literal

import structlog
from sqlalchemy import func, select
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
from app.mail.models import Attachment, FolderMeta, Mailbox, Message
from app.mail.outgoing_images import normalize_outgoing_images
from app.mail.parse import parse_rfc822
from app.mail.sanitize import REMOTE_PLACEHOLDER, sanitize_quote_html
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

# Every [[DOPLNIŤ…]] form, also [[DOPLNIŤ: cena]] as AI drafts write it (2d: the bare form alone let those through).
_PLACEHOLDER = re.compile(r"\[\[\s*DOPLNI[TŤ][^\]]*\]\]", re.I)
_PROTECTED_HTML = re.compile(
    r'<blockquote data-sm-quote="1">.*?</blockquote>|<div data-sm-signature="1">.*$', re.S | re.I
)
# A Slovak reply to a Czech customer is normal; other pairs are worth a look (W4a „cudzí jazyk“).
_COMPATIBLE_LANGUAGES = ({"sk", "cs"},)
_LANGUAGE_MIN_CHARS = 40
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
    user_html: str = "<p></p>",
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

    quoted = quote_html_for_message(settings, source) if source and mode in ("reply", "reply_all", "forward") else None
    signature = render_signature(person=person, branch=branch, identity=identity, email=identity.email, language="sk")
    body_html = assemble_outgoing_html(
        user_html=user_html,
        quote_html=quoted,
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
    if source is not None and mode == "forward":
        await copy_forward_attachments(db, draft, source)
    audit(
        db,
        action="mail.compose_created",
        account_id=account_id,
        person_id=person.id if person else None,
        details={"draft_id": str(draft.id), "mode": mode},
    )
    return draft


async def copy_forward_attachments(db: AsyncSession, draft: ComposeDraft, source: Message) -> None:
    """Point the draft at the original files. The bytes stay where they are.

    Infected files are left behind. ``skipped`` and ``error`` are copied with that
    status so the compose chip can show the same antivírus label as the reading pane.
    The copied status is only a snapshot: the chip and every send re-read the
    ``Attachment`` row with the same ``storage_key``. Inline images stay in the quote
    as related parts, not as a second file chip.
    """
    rows = list((await db.execute(select(Attachment).where(Attachment.message_id == source.id))).scalars())
    for row in rows:
        if row.is_inline or row.av_status == "infected" or not row.storage_key:
            continue
        db.add(
            ComposeAttachment(
                draft_id=draft.id,
                filename=row.filename,
                content_type=row.content_type,
                size=row.size,
                storage_key=row.storage_key,
                sha256=row.sha256,
                av_status=row.av_status or "skipped",
                is_inline=False,
            )
        )


async def release_compose_storage(db: AsyncSession, settings: Settings, att: ComposeAttachment) -> None:
    """Delete blob bytes only when no message and no other draft still points at the key."""
    shared_message = await db.scalar(
        select(func.count()).select_from(Attachment).where(Attachment.storage_key == att.storage_key)
    )
    shared_draft = await db.scalar(
        select(func.count())
        .select_from(ComposeAttachment)
        .where(ComposeAttachment.storage_key == att.storage_key, ComposeAttachment.id != att.id)
    )
    if not shared_message and not shared_draft:
        storage.delete_key(settings, att.storage_key)


def user_text_of(draft: ComposeDraft) -> str:
    """The person's own text: without the quoted mail and the signature (they must not trigger checks)."""
    return html_to_text(_PROTECTED_HTML.sub("", draft.body_html or "")).strip()


def pre_send_checks(draft: ComposeDraft, settings: Settings, *, has_attachments: bool = False) -> list[dict[str, Any]]:
    """W4b checks (also the live W4a checklist). Blocking items disable 'Odoslať aj tak'."""
    issues: list[dict[str, Any]] = []
    if not draft.to_addrs:
        issues.append({"code": "no_recipients", "blocking": True, "message": "missing_to"})
    if _PLACEHOLDER.search(draft.body_html or "") or _PLACEHOLDER.search(draft.body_text or ""):
        issues.append({"code": "placeholder", "blocking": True, "message": "placeholder"})
    own = f"{draft.subject}\n{user_text_of(draft)}"
    if _ATTACH_MENTION.search(own) and not has_attachments:
        issues.append({"code": "attachment_mentioned", "blocking": False, "message": "attachment_mentioned"})
    domains = {(a.get("email") or "").rsplit("@", 1)[-1].lower() for a in draft.to_addrs + draft.cc_addrs}
    external = sorted(d for d in domains if d and not settings.is_internal_address(f"x@{d}"))
    if external:
        issues.append({"code": "external_recipient", "blocking": False, "message": "external"})
    if len(external) > 1:
        # W4a „príjemcovia z jednej firmy“: one company per message, by domain until Money links them (Phase 3)
        issues.append({"code": "multiple_companies", "blocking": False, "message": ", ".join(external[:5])})
    return issues


def language_check(own_text: str, customer_language: str | None) -> dict[str, Any] | None:
    """W4a „cudzí jazyk vs. jazyk zákazníka“ (warning only)."""
    from app.ai.language import detect_language

    if not customer_language or customer_language == "other" or len(own_text) < _LANGUAGE_MIN_CHARS:
        return None
    mine = detect_language(own_text)
    if mine in ("other", customer_language) or any({mine, customer_language} <= pair for pair in _COMPATIBLE_LANGUAGES):
        return None
    return {"code": "language_mismatch", "blocking": False, "message": f"{mine}:{customer_language}"}


class PreSendBlocked(Exception):
    """Send refused until the user confirms a warning or fixes a blocking check."""

    def __init__(self, checks: list[dict[str, Any]]) -> None:
        super().__init__("pre_send_blocked")
        self.checks = checks


class AttachmentNotSendable(Exception):
    """Hard send block. ``force`` cannot override it."""

    def __init__(self, code: str, filename: str) -> None:
        super().__init__(code)
        self.code = code
        self.filename = filename


# Same sentence as compose.checks.attachment_pending / compose.attachmentPending in sk.json.
PENDING_AV_WARNING = "Príloha ešte nebola skontrolovaná antivírusom"


def _prefer_av_status(found: list[str], fallback: str) -> str:
    """Current status of a shared blob. Infected wins; otherwise the source row."""
    if "infected" in found:
        return "infected"
    if "pending" in found:
        return "pending"
    if found:
        return found[0]
    return fallback


async def live_av_statuses(db: AsyncSession, atts: list[ComposeAttachment]) -> dict[uuid.UUID, str]:
    """Status from the ``Attachment`` row that shares ``storage_key``, when one exists.

    ``copy_forward_attachments`` stores the status at forward time. A later scan can mark
    the original infected while the draft row stays pending. The chip and the send path
    both use this lookup.
    """
    keys = [a.storage_key for a in atts if a.storage_key]
    by_key: dict[str, list[str]] = {}
    if keys:
        rows = (
            await db.execute(
                select(Attachment.storage_key, Attachment.av_status).where(Attachment.storage_key.in_(keys))
            )
        ).all()
        for key, status in rows:
            by_key.setdefault(key, []).append(status)
    return {a.id: _prefer_av_status(by_key.get(a.storage_key, []), a.av_status) for a in atts}


async def compose_checks(
    db: AsyncSession,
    draft: ComposeDraft,
    settings: Settings,
    atts: list[ComposeAttachment],
) -> list[dict[str, Any]]:
    """``pre_send_checks`` plus a non-blocking warning when a file is still ``pending`` and the language check."""
    issues = pre_send_checks(draft, settings, has_attachments=any(not a.is_inline for a in atts))
    if draft.in_reply_to_message_id is not None:
        source = await db.get(Message, draft.in_reply_to_message_id)
        if source is not None:
            from app.ai.language import detect_language
            from app.ai.models import Classification

            known = await db.scalar(
                select(Classification.language).where(Classification.message_id == source.id).limit(1)
            )
            customer = known or detect_language(f"{source.subject or ''}\n{source.body_text or source.preview or ''}")
            found = language_check(user_text_of(draft), customer)
            if found:
                issues.append(found)
    statuses = await live_av_statuses(db, atts)
    if any(not att.is_inline and statuses[att.id] == "pending" for att in atts):
        issues.append({"code": "attachment_pending", "blocking": False, "message": PENDING_AV_WARNING})
    return issues


async def attachment_send_block(
    db: AsyncSession,
    settings: Settings,
    draft: ComposeDraft,
    atts: list[ComposeAttachment] | None = None,
) -> AttachmentNotSendable | None:
    """Infected or missing regular files. Re-run on every send, including the undo job."""
    rows = atts
    if rows is None:
        rows = list(
            (await db.execute(select(ComposeAttachment).where(ComposeAttachment.draft_id == draft.id))).scalars()
        )
    regular = [att for att in rows if not att.is_inline]
    statuses = await live_av_statuses(db, regular)
    for att in regular:
        if statuses[att.id] == "infected":
            return AttachmentNotSendable("attachment_infected", att.filename)
    for att in regular:
        if storage.get_bytes(settings, att.storage_key) is None:
            return AttachmentNotSendable("attachment_missing", att.filename)
    # Phase 3d: a Money invoice PDF goes only to its own company — checked again here, at every send
    from app.money.invoice_attach import marked_company, recipient_block

    marked = [att for att in regular if marked_company(att.storage_key) is not None]
    if marked:
        recipients = [
            str(a.get("email") or "")
            for a in [*(draft.to_addrs or []), *(draft.cc_addrs or []), *(draft.bcc_addrs or [])]
        ]
        bad = await recipient_block(db, settings, recipients, [att.storage_key for att in marked])
        if bad is not None:
            return AttachmentNotSendable("recipient_not_document_owner", marked[0].filename)
    return None


def text_to_html(body: str) -> str:
    """Plain text (model or template) → escaped paragraphs for the editor; the text is never HTML."""
    paragraphs = [p.strip() for p in body.replace("\r\n", "\n").split("\n\n") if p.strip()]
    return "".join(f"<p>{html_lib.escape(p).replace(chr(10), '<br>')}</p>" for p in paragraphs) or "<p></p>"


def _send_error_with_filename(code: str, filename: str) -> str:
    return f"{code}:{filename}"[:200]


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
    signer, signature_branch = await signature_person_branch(db, draft)
    for cid in wanted:
        if cid == LOGO_CID:
            # „Logo do podpisu“ of the branch (#55), else the company logo
            data = (
                storage.get_bytes(settings, signature_branch.logo_key)
                if signature_branch and signature_branch.logo_key
                else None
            )
            data = data or _logo_png()
            if data:
                blobs.append((cid, data, sniff_image_type(data)))
            continue
        if cid == PHOTO_CID:
            person = signer
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


async def _outgoing_images_by_id(
    db: AsyncSession, settings: Settings, draft: ComposeDraft, identity: Identity
) -> dict[str, tuple[str, bytes, str]]:
    """Uploaded signature files addressable as ``/api/settings/signature-images/<id>``."""
    records = image_dicts(identity.signature_images)
    mailbox_branch = await db.scalar(select(Branch).where(Branch.mailbox_id == draft.mailbox_id))
    if mailbox_branch is not None:
        records.extend(image_dicts(mailbox_branch.signature_images))
    person_id = draft.signature_person_id or draft.person_id
    person = await db.get(Person, person_id) if person_id else None
    if person is not None and person.branch_id is not None:
        person_branch = await db.get(Branch, person.branch_id)
        if person_branch is not None:
            records.extend(image_dicts(person_branch.signature_images))
    found: dict[str, tuple[str, bytes, str]] = {}
    for rec in records:
        image_id = rec.get("id")
        cid = rec.get("cid")
        if not isinstance(image_id, str) or not isinstance(cid, str):
            continue
        data = storage.get_bytes(settings, str(rec.get("storage_key") or "")) or b""
        found[image_id] = (cid, data, str(rec.get("content_type") or "image/png"))
    return found


def log_stripped_images(draft_id: str, count: int) -> None:
    """How many images were dropped. The URL is not logged."""
    if count > 0:
        log.info("compose.images_stripped", draft_id=draft_id, count=count)


async def signature_person_branch(db: AsyncSession, draft: ComposeDraft) -> tuple[Person | None, Branch | None]:
    """Signer of the draft and the branch whose data fills the signature: the person's branch, else the branch of
    the mailbox."""
    person_id = draft.signature_person_id or draft.person_id
    person = await db.get(Person, person_id) if person_id else None
    branch = None
    if person is not None and person.branch_id is not None:
        branch = await db.get(Branch, person.branch_id)
    if branch is None:
        branch = await db.scalar(select(Branch).where(Branch.mailbox_id == draft.mailbox_id))
    return person, branch


async def rendered_signature(db: AsyncSession, draft: ComposeDraft) -> str:
    """Signature for this draft from the template or the stored per-message override."""
    if not draft.include_signature:
        return ""
    identity = await db.get(Identity, draft.identity_id) if draft.identity_id else None
    person, branch = await signature_person_branch(db, draft)
    return render_signature(
        person=person,
        branch=branch,
        identity=identity,
        email=identity.email if identity else "",
        override_html=draft.signature_html_override,
    )


def quote_html_for_message(settings: Settings, source: Message) -> str | None:
    """Original HTML from stored raw, sanitized without rewriting remote images.

    ``body_html_sanitized`` is the reading-pane copy (remote images are placeholders or
    ``/api/mail/image-proxy``). A reply or forward must not send that. When raw is missing
    and the stored HTML has no display image, that HTML is still used so a text table survives.
    """
    if source.raw_storage_key:
        raw = storage.get_bytes(settings, source.raw_storage_key)
        if raw:
            parsed = parse_rfc822(raw, settings)
            if parsed.body_html and parsed.body_html.strip():
                cleaned = sanitize_quote_html(parsed.body_html).strip()
                if cleaned:
                    return cleaned
    stored = source.body_html_sanitized or ""
    if stored and REMOTE_PLACEHOLDER not in stored and "/api/mail/image-proxy" not in stored:
        return stored
    if source.body_text:
        return f"<pre>{html_lib.escape(source.body_text)}</pre>"
    return None


def quoted_image_parts(
    html: str,
    attachments: list[Attachment],
    read: Callable[[str], bytes | None],
    *,
    skip_cids: set[str],
) -> list[tuple[str, bytes, str]]:
    """Bytes for ``cid:`` images referenced by the outgoing quote (same related parts as a signature)."""
    wanted = {cid.lower(): cid for cid in cids_in_html(html)}
    if not wanted:
        return []
    blobs: list[tuple[str, bytes, str]] = []
    used = {cid.lower() for cid in skip_cids}
    for att in attachments:
        if att.av_status == "infected" or not att.content_id:
            continue
        key = att.content_id.strip().strip("<>").strip().lower()
        html_cid = wanted.get(key)
        if html_cid is None or key in used:
            continue
        data = read(att.storage_key) or b""
        if not data:
            continue
        ctype = att.content_type or ""
        if not ctype.startswith("image/"):
            sniffed = sniff_image_type(data)
            if not sniffed.startswith("image/"):
                continue
            ctype = sniffed
        blobs.append((html_cid, data, ctype))
        used.add(key)
    return blobs


async def rehydrate_draft_html(db: AsyncSession, settings: Settings, draft: ComposeDraft) -> None:
    """Replace editor signature and quote with the server copies (issue #28)."""
    quote: str | None = None
    if draft.mode in {"reply", "reply_all", "forward"} and draft.in_reply_to_message_id is not None:
        source = await db.get(Message, draft.in_reply_to_message_id)
        if source is not None:
            quote = quote_html_for_message(settings, source)
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
    # Keep the draft HTML (it may still hold data: icons for the editor). The MIME copy
    # is the one Gmail can display: CID parts and https only.
    raw_html = draft.body_html or ""
    html, blobs, stripped = normalize_outgoing_images(
        raw_html,
        logo_png=_logo_png(),
        images_by_id=await _outgoing_images_by_id(db, settings, draft, identity),
    )
    log_stripped_images(str(draft.id), stripped)
    text = draft.body_text or html_to_text(raw_html)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    seen = {cid.lower() for cid, _data, _ctype in blobs}
    for cid, data, ctype in await _signature_blobs(db, settings, draft, identity, html):
        if cid.lower() in seen:
            continue
        blobs.append((cid, data, ctype))
        seen.add(cid.lower())
    if draft.in_reply_to_message_id is not None:
        # A forward already copied ordinary files onto the draft. A reply does not.
        # cid: images referenced by the quote are related parts, on reply and on forward.
        source_atts = list(
            (
                await db.execute(select(Attachment).where(Attachment.message_id == draft.in_reply_to_message_id))
            ).scalars()
        )
        blobs.extend(
            quoted_image_parts(
                html,
                source_atts,
                lambda key: storage.get_bytes(settings, key),
                skip_cids=seen,
            )
        )
        seen.update(cid.lower() for cid, _data, _ctype in blobs)

    atts = list((await db.execute(select(ComposeAttachment).where(ComposeAttachment.draft_id == draft.id))).scalars())
    regular: list[ComposeAttachment] = []
    for att in atts:
        if att.is_inline and att.content_id:
            if att.content_id.lower() in seen:
                continue
            data = storage.get_bytes(settings, att.storage_key) or b""
            if data:
                blobs.append((att.content_id, data, att.content_type or "image/png"))
                seen.add(att.content_id)
            continue
        regular.append(att)
    add_related_images(msg, blobs)
    statuses = await live_av_statuses(db, regular)
    for att in regular:
        if statuses[att.id] == "infected":
            raise AttachmentNotSendable("attachment_infected", att.filename)
        payload = storage.get_bytes(settings, att.storage_key)
        if payload is None:
            raise AttachmentNotSendable("attachment_missing", att.filename)
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
    atts = list((await db.execute(select(ComposeAttachment).where(ComposeAttachment.draft_id == draft.id))).scalars())
    checks = await compose_checks(db, draft, settings, atts)
    # Blocking items ([[DOPLNIŤ]], no recipient) can never be forced — „Odoslať aj tak“ is only for warnings (W4b).
    # Pending AV is a warning the user confirms (force).
    if any(c["blocking"] for c in checks):
        raise PreSendBlocked(checks)
    if any(c["code"] == "attachment_pending" for c in checks) and not force:
        raise PreSendBlocked(checks)
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
    An infected or missing attachment is not copied to Koncepty; the local draft still saves.
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
    except AttachmentNotSendable as exc:
        # Do not APPEND the file, and do not fail the local autosave. The name stays out of the log.
        log.warning("compose.draft_imap_skipped", draft_id=str(draft.id), code=exc.code)
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
    blocked = await attachment_send_block(db, settings, draft)
    if blocked is not None:
        draft.status = "failed"
        draft.send_error = _send_error_with_filename(blocked.code, blocked.filename)
        draft.undo_until = None
        await db.commit()
        return "failed"
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
    except AttachmentNotSendable as exc:
        draft.status = "failed"
        draft.send_error = _send_error_with_filename(exc.code, exc.filename)
        draft.undo_until = None
        await db.commit()
        return "failed"
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

    # Phase 3f: a sent Money invoice / reminder → CRM activity in Money (switches 13a + 13d, one attempt)
    from app.money.activities import enqueue_after_send

    await enqueue_after_send(db, settings, draft)

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
