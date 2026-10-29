"""Settings W12 API — Phase 1f sections 01–06, 09, 09b, 10–12."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.api.auth import Authenticator, Limiter
from app.auth.admin_accounts import AccountRuleError, convert_to_branch, create_account, ensure_admin_remains
from app.auth.deps import DB, ActivePerson, Auth, SettingsDep, client_ip
from app.auth.models import Account, AccountKind, Branch, Person, PersonBranch, Role
from app.auth.persons import eligible_persons, own_login_person_ids
from app.auth.reauth import RecentReauth, require_recent_reauth
from app.auth.security import decrypt
from app.auth.sessions import RevokeReason, forget_revoked_reauth, revoke_account_sessions
from app.core.audit import AuditLog, audit
from app.mail import storage
from app.mail.clamav import scan_bytes
from app.mail.compose_models import CannedResponse, ComposeDraft, Identity
from app.mail.image_proxy import proxy_path
from app.mail.imap import LoginResult
from app.mail.models import FolderMeta, Mailbox, MailboxAccess, SieveScriptBackup
from app.mail.prefs import get_list_prefs, get_ui_prefs, save_section
from app.mail.sanitize import sanitize_html
from app.mail.sieve import (
    DEFAULT_SCRIPT_NAME,
    FilterValidationError,
    ParsedScript,
    SieveError,
    VacationSettings,
    apply_live_raw_to_readonly,
    apply_vacation_to_script,
    compile_script,
    dicts_to_filters,
    filters_to_dicts,
    parse_roundcube_script,
    validate_editable_rules,
)
from app.mail.sieve_async import (
    SIEVE_UNAVAILABLE_MESSAGE_SK,
    load_active_script,
    read_then_write_script,
    save_active_script,
)
from app.mail.signature import (
    SignatureError,
    apply_signature_languages,
    default_branch_template,
    preview_signature_html,
    signature_presets,
)
from app.mail.signature_images import (
    MAX_SIGNATURE_IMAGES,
    SignatureImageError,
    image_dicts,
    normalize_person_photo,
    normalize_signature_image,
    sniff_image_type,
)
from app.settings.schema import SECTION_PATHS, schema_document

router = APIRouter(prefix="/api/settings", tags=["settings"])


def fail(status: int, code: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, **extra})


def require_admin(ctx: Auth) -> Person:
    if ctx.person is None or ctx.person.role != Role.admin:
        raise fail(403, "admin_required")
    return ctx.person


# ----- schema -----


@router.get("/schema")
async def get_schema() -> dict[str, Any]:
    return schema_document()


# ----- preferences (01) -----


class PrefsBundle(BaseModel):
    ui: dict[str, Any] = Field(default_factory=dict)
    list: dict[str, Any] = Field(default_factory=dict)
    reading: dict[str, Any] = Field(default_factory=dict)
    composing: dict[str, Any] = Field(default_factory=dict)
    shortcuts: dict[str, Any] = Field(default_factory=dict)


@router.get("/preferences")
async def get_preferences(ctx: Auth, person: ActivePerson, db: DB) -> PrefsBundle:
    ui = (await get_ui_prefs(db, person.id)).model_dump()
    lst = (await get_list_prefs(db, person.id)).model_dump()
    reading = await _section(db, person.id, "prefs.reading")
    composing = await _section(db, person.id, "prefs.composing")
    shortcuts = await _section(db, person.id, "prefs.shortcuts")
    return PrefsBundle(ui=ui, list=lst, reading=reading, composing=composing, shortcuts=shortcuts)


@router.put("/preferences")
async def put_preferences(body: PrefsBundle, request: Request, ctx: Auth, person: ActivePerson, db: DB) -> PrefsBundle:
    if body.ui:
        await save_section(db, person.id, "prefs.ui", body.ui)
    if body.list:
        # coerce page_size
        data = dict(body.list)
        if "page_size" in data:
            data["page_size"] = int(data["page_size"])
        await save_section(db, person.id, "prefs.list", data)
    if body.reading:
        await save_section(db, person.id, "prefs.reading", body.reading)
    if body.composing:
        await save_section(db, person.id, "prefs.composing", body.composing)
    if body.shortcuts:
        await save_section(db, person.id, "prefs.shortcuts", body.shortcuts)
    audit(
        db,
        "settings.preferences_saved",
        account_id=ctx.account.id,
        person_id=person.id,
        object_type="settings",
        object_id="01",
        ip=client_ip(request),
    )
    await db.commit()
    return await get_preferences(ctx, person, db)


async def _section(db: DB, person_id: uuid.UUID, section: str) -> dict[str, Any]:
    from app.mail.models import UserSettings

    row = await db.scalar(
        select(UserSettings).where(UserSettings.person_id == person_id, UserSettings.section == section)
    )
    return dict(row.data) if row else {}


# ----- profile 03b -----


class ProfileIn(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    function: str | None = None
    phone: str | None = None
    mobile: str | None = None
    personal_email: str | None = None
    languages: list[str] | None = None
    style_guide: str | None = None


@router.get("/profile")
async def get_profile(ctx: Auth, person: ActivePerson, db: DB) -> dict[str, Any]:
    branch = await db.get(Branch, person.branch_id) if person.branch_id else None
    preview = preview_signature_html(person=person, branch=branch, identity=None, email=ctx.account.email)
    return {
        "id": str(person.id),
        "first_name": person.first_name,
        "last_name": person.last_name,
        "function": person.function,
        "phone": person.phone,
        "mobile": person.mobile,
        "personal_email": person.personal_email,
        "languages": person.languages or ["sk"],
        "style_guide": person.style_guide,
        "role": person.role.value,
        "signature_preview_html": preview,
    }


@router.put("/profile")
async def put_profile(body: ProfileIn, request: Request, ctx: Auth, person: ActivePerson, db: DB) -> dict[str, Any]:
    if body.first_name is not None:
        person.first_name = body.first_name.strip()[:50] or person.first_name
    if body.last_name is not None:
        person.last_name = body.last_name.strip()[:50] or person.last_name
    if body.function is not None:
        person.function = (body.function.strip() or None) and body.function.strip()[:60]
    if body.phone is not None:
        person.phone = body.phone.strip() or None
    if body.mobile is not None:
        person.mobile = body.mobile.strip() or None
    if body.personal_email is not None:
        person.personal_email = body.personal_email.strip().lower() or None
    if body.languages is not None:
        person.languages = body.languages[:8]
    if body.style_guide is not None:
        person.style_guide = body.style_guide[:2000] or None
    audit(
        db,
        "settings.profile_saved",
        account_id=ctx.account.id,
        person_id=person.id,
        object_type="person",
        object_id=str(person.id),
        ip=client_ip(request),
    )
    await db.commit()
    return await get_profile(ctx, person, db)


# ----- identities 03a -----


class IdentityIn(BaseModel):
    display_name: str
    email: str
    organization: str | None = None
    reply_to: str | None = None
    bcc: list[str] = Field(default_factory=list)
    is_default: bool = False
    signature_html: dict[str, str] = Field(default_factory=dict)


@router.get("/mailboxes/{mailbox_ref}/identities")
async def list_identities_settings(mailbox_ref: str, ctx: Auth, db: DB) -> list[dict[str, Any]]:
    mailbox = await _mailbox(db, ctx, mailbox_ref)
    rows = (
        await db.scalars(select(Identity).where(Identity.mailbox_id == mailbox.id).order_by(Identity.is_default.desc()))
    ).all()
    return [_identity_out(i) for i in rows]


def _identity_state(i: Identity) -> dict[str, Any]:
    """Audited before/after of an identity — addresses and names only, never the signature HTML."""
    return {
        "display_name": i.display_name,
        "email": i.email,
        "reply_to": i.reply_to,
        "organization": i.organization,
        "is_default": i.is_default,
    }


@router.put("/identities/{identity_id}")
async def update_identity(
    identity_id: uuid.UUID,
    body: IdentityIn,
    request: Request,
    ctx: Auth,
    person: ActivePerson,
    db: DB,
    settings: SettingsDep,
) -> dict[str, Any]:
    identity = await db.get(Identity, identity_id)
    if identity is None:
        raise fail(404, "identity_not_found")
    mailbox = await _mailbox_by_id(db, ctx, identity.mailbox_id)
    managed = _branch_managed(mailbox, ctx.account)
    if managed:
        # A branch mailbox sends for everybody of the branch: only an admin sets its sender (#68). The sender must be a
        # company address (the alias the SMTP server accepts, e.g. nitra@ for the login smartsronitra@).
        require_admin(ctx)
        for address in (body.email, body.reply_to):
            if address and not settings.is_internal_address(address.strip().lower()):
                raise fail(422, "identity_email_not_internal")
    before = _identity_state(identity)
    identity.display_name = body.display_name.strip()[:100]
    identity.email = body.email.strip().lower()
    identity.organization = (body.organization or "").strip()[:100] or None
    identity.reply_to = (body.reply_to or "").strip().lower() or None
    identity.bcc = [a.strip().lower() for a in body.bcc if a.strip()]
    stripped: dict[str, list[str]] = {}
    if not managed:  # the signature of a branch identity stays the branch template (Pobočky a osoby › Podpis)
        try:
            cleaned, stripped = apply_signature_languages(body.signature_html, require_sk=False)
        except SignatureError as exc:
            raise fail(422, exc.code, **exc.extra) from exc
        identity.signature_html = cleaned
    if body.is_default:
        others = (
            await db.scalars(
                select(Identity).where(Identity.mailbox_id == identity.mailbox_id, Identity.id != identity.id)
            )
        ).all()
        for o in others:
            o.is_default = False
        identity.is_default = True
    audit(
        db,
        "settings.identity_saved",
        account_id=ctx.account.id,
        person_id=person.id,
        object_type="identity",
        object_id=str(identity.id),
        ip=client_ip(request),
        details={"before": before, "after": _identity_state(identity)},
    )
    await db.commit()
    await db.refresh(identity)
    return _identity_out(identity, stripped)


def _public_images(raw: object) -> list[dict[str, Any]]:
    return [
        {
            "id": rec["id"],
            "cid": rec["cid"],
            "preview_url": f"/api/settings/signature-images/{rec['id']}",
            "content_type": rec.get("content_type"),
            "size": rec.get("size"),
            "filename": rec.get("filename"),
        }
        for rec in image_dicts(raw)
    ]


def _identity_out(i: Identity, stripped: dict[str, list[str]] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(i.id),
        "mailbox_id": str(i.mailbox_id),
        "display_name": i.display_name,
        "email": i.email,
        "organization": i.organization,
        "reply_to": i.reply_to,
        "bcc": i.bcc,
        "is_default": i.is_default,
        "signature_html": i.signature_html,
        "signature_images": _public_images(i.signature_images),
    }
    if stripped is not None:
        out["signature_stripped"] = stripped
    return out


# ----- responses 04 -----


class ResponseIn(BaseModel):
    name: str
    language: str = "sk"
    body_html: str
    shared: bool = False
    shortcut: str | None = None


@router.get("/responses")
async def list_settings_responses(ctx: Auth, person: ActivePerson, db: DB) -> list[dict[str, Any]]:
    rows = (
        await db.scalars(
            select(CannedResponse).where((CannedResponse.person_id == person.id) | (CannedResponse.shared.is_(True)))
        )
    ).all()
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "language": r.language,
            "body_html": r.body_html,
            "shared": r.shared,
            "shortcut": r.shortcut,
            "mine": r.person_id == person.id,
        }
        for r in rows
    ]


@router.post("/responses")
async def create_response(
    body: ResponseIn, request: Request, ctx: Auth, person: ActivePerson, db: DB
) -> dict[str, Any]:
    if body.shared and person.role not in {Role.admin, Role.sales}:
        raise fail(403, "cannot_share")
    row = CannedResponse(
        person_id=person.id,
        name=body.name.strip()[:80],
        language=body.language[:8],
        body_html=sanitize_html(body.body_html[:20_000]),
        shared=body.shared,
        shortcut=(body.shortcut or "").strip()[:20] or None,
    )
    db.add(row)
    audit(
        db,
        "settings.response_created",
        account_id=ctx.account.id,
        person_id=person.id,
        object_type="response",
        object_id="new",
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(row)
    return {
        "id": str(row.id),
        "name": row.name,
        "language": row.language,
        "body_html": row.body_html,
        "shared": row.shared,
        "shortcut": row.shortcut,
        "mine": True,
    }


@router.put("/responses/{response_id}")
async def update_response(
    response_id: uuid.UUID, body: ResponseIn, request: Request, ctx: Auth, person: ActivePerson, db: DB
) -> dict[str, Any]:
    row = await db.get(CannedResponse, response_id)
    if row is None or (row.person_id != person.id and not row.shared):
        raise fail(404, "response_not_found")
    if row.person_id != person.id and person.role != Role.admin:
        raise fail(403, "not_owner")
    row.name = body.name.strip()[:80]
    row.language = body.language[:8]
    row.body_html = sanitize_html(body.body_html[:20_000])
    row.shared = body.shared
    row.shortcut = (body.shortcut or "").strip()[:20] or None
    await db.commit()
    return {
        "id": str(row.id),
        "name": row.name,
        "language": row.language,
        "body_html": row.body_html,
        "shared": row.shared,
        "shortcut": row.shortcut,
        "mine": row.person_id == person.id,
    }


@router.delete("/responses/{response_id}")
async def delete_response(
    response_id: uuid.UUID, request: Request, ctx: Auth, person: ActivePerson, db: DB
) -> dict[str, bool]:
    row = await db.get(CannedResponse, response_id)
    if row is None:
        raise fail(404, "response_not_found")
    if row.person_id != person.id and person.role != Role.admin:
        raise fail(403, "not_owner")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


# ----- filters 05 + vacation 06 (same active ManageSieve script) -----


class FiltersIn(BaseModel):
    rules: list[dict[str, Any]] = Field(default_factory=list)


class VacationIn(BaseModel):
    enabled: bool = False
    subject: str = "Mimo kancelárie: {predmet}"
    body_sk: str = "Ďakujem za správu. Momentálne som mimo kancelárie."
    body_en: str = "Thank you for your message. I am currently out of office."
    body_de: str = "Danke für Ihre Nachricht. Ich bin derzeit außer Haus."
    days: int = 7
    start: str | None = None
    end: str | None = None


async def _mailbox_creds(db: DB, settings: SettingsDep, ctx: Auth, mailbox: Mailbox) -> tuple[str, str]:
    account = ctx.account
    if mailbox.credential_account_id and mailbox.credential_account_id != account.id:
        account = await db.get(Account, mailbox.credential_account_id) or account
    if not account.mailbox_password_enc:
        raise fail(409, "mailbox_password_missing")
    return mailbox.email, decrypt(settings, account.mailbox_password_enc)


async def _require_sieve_write(db: DB, ctx: Auth, person: Person, mailbox: Mailbox) -> None:
    """PUT filters/vacation/restore: send access + non-viewer; admin always."""
    if person.role == Role.admin:
        return
    if person.role == Role.viewer:
        raise fail(403, "read_only")
    access = await db.scalar(
        select(MailboxAccess).where(MailboxAccess.account_id == ctx.account.id, MailboxAccess.mailbox_id == mailbox.id)
    )
    if access is None or not access.can_send:
        raise fail(403, "mailbox_send_forbidden")


async def _vacation_last_changed(db: DB, mailbox_id: uuid.UUID) -> dict[str, Any] | None:
    """Who last turned Mimo kancelárie on/off (from audit) and when."""
    result = await db.execute(
        select(AuditLog)
        .where(
            AuditLog.action == "settings.vacation_saved",
            AuditLog.object_type == "mailbox",
            AuditLog.object_id == str(mailbox_id),
        )
        .order_by(AuditLog.created_at.desc())
        .limit(1)
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        return None
    name = None
    if entry.person_id is not None:
        person = await db.get(Person, entry.person_id)
        if person is not None:
            name = f"{person.first_name} {person.last_name}".strip()
    return {
        "person_id": str(entry.person_id) if entry.person_id else None,
        "person_name": name,
        "at": entry.created_at.isoformat() if entry.created_at else None,
        "enabled": (entry.details or {}).get("enabled"),
    }


async def _latest_backup(db: DB, mailbox_id: uuid.UUID) -> SieveScriptBackup | None:
    result = await db.execute(
        select(SieveScriptBackup)
        .where(SieveScriptBackup.mailbox_id == mailbox_id)
        .order_by(SieveScriptBackup.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _backup_script(
    db: DB,
    *,
    mailbox: Mailbox,
    script_name: str,
    content: str,
    reason: str,
    person_id: uuid.UUID,
) -> None:
    if not content.strip():
        return
    db.add(
        SieveScriptBackup(
            mailbox_id=mailbox.id,
            script_name=script_name,
            content=content,
            reason=reason,
            person_id=person_id,
        )
    )


def _vacation_payload(vac: VacationSettings) -> dict[str, Any]:
    return {
        "enabled": vac.enabled,
        "subject": vac.subject,
        "body_sk": vac.body_sk,
        "body_en": vac.body_en,
        "body_de": vac.body_de,
        "days": vac.days,
        "start": vac.start,
        "end": vac.end,
    }


def _sieve_unavailable_payload(**extra: Any) -> dict[str, Any]:
    return {
        "sieve_unavailable": True,
        "sieve_message": SIEVE_UNAVAILABLE_MESSAGE_SK,
        **extra,
    }


@router.get("/mailboxes/{mailbox_ref}/filters")
async def get_filters(
    mailbox_ref: str, request: Request, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> dict[str, Any]:
    mailbox = await _mailbox(db, ctx, mailbox_ref)
    script_name = DEFAULT_SCRIPT_NAME
    script = ""
    unavailable = False
    user, password = await _mailbox_creds(db, settings, ctx, mailbox)
    try:
        script_name, script, _supports = await load_active_script(
            redis=request.app.state.redis,
            settings=settings,
            mailbox=mailbox,
            username=user,
            password=password,
        )
    except SieveError as exc:
        if exc.code in {"sieve_auth_failed", "sieve_host_not_allowed", "sieve_disabled"}:
            raise fail(409, exc.code) from exc
        # sieve_unavailable (and unexpected ManageSieve failures) → soft empty + SK banner
        unavailable = True
    parsed = parse_roundcube_script(script, script_name=script_name)
    rules = [r for r in parsed.rules if r.kind != "vacation"]
    backup = await _latest_backup(db, mailbox.id)
    payload: dict[str, Any] = {
        "rules": filters_to_dicts(rules),
        "script_name": script_name,
        "mailbox_scope": mailbox.kind,
        "has_backup": backup is not None,
        "help": (
            "Filter platí pre celú schránku (osobnú aj pobočkovú). "
            "Filtre nie sú predvolené – každá schránka má vlastné."
        ),
    }
    if unavailable:
        payload.update(_sieve_unavailable_payload())
    return payload


@router.put("/mailboxes/{mailbox_ref}/filters")
async def put_filters(
    mailbox_ref: str, body: FiltersIn, request: Request, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> dict[str, Any]:
    mailbox = await _mailbox(db, ctx, mailbox_ref)
    await _require_sieve_write(db, ctx, person, mailbox)
    rules = dicts_to_filters(body.rules)
    for i, rule in enumerate(rules):
        if not rule.id:
            rule.id = f"f{i + 1}-{uuid.uuid4().hex[:8]}"
    try:
        validate_editable_rules(rules)
    except FilterValidationError as exc:
        raise fail(422, exc.code, message=exc.message) from exc
    user, password = await _mailbox_creds(db, settings, ctx, mailbox)
    new_script_holder: dict[str, str] = {}
    compile_error: list[FilterValidationError] = []

    def build(script_name: str, current: str, supports_variables: bool) -> str:
        parsed = parse_roundcube_script(current, script_name=script_name)
        live_filters = [r for r in parsed.rules if r.kind != "vacation"]
        merged = apply_live_raw_to_readonly(rules, live_filters)
        try:
            compiled = compile_script(
                ParsedScript(
                    preamble=parsed.preamble,
                    rules=merged,
                    vacation=parsed.vacation,
                    script_name=script_name,
                ),
                vacation=parsed.vacation,
                rules=merged,
                include_vacation=parsed.vacation.enabled or any(r.kind == "vacation" for r in parsed.rules),
                supports_variables=supports_variables,
            )
        except FilterValidationError as exc:
            compile_error.append(exc)
            raise
        new_script_holder["content"] = compiled
        return compiled

    try:
        script_name, current = await read_then_write_script(
            redis=request.app.state.redis,
            settings=settings,
            mailbox=mailbox,
            username=user,
            password=password,
            build=build,
        )
    except FilterValidationError as exc:
        raise fail(422, exc.code, message=exc.message) from exc
    except SieveError as exc:
        raise fail(
            409,
            exc.code,
            detail=exc.detail,
            message=SIEVE_UNAVAILABLE_MESSAGE_SK if exc.code == "sieve_unavailable" else None,
        ) from exc
    if compile_error:
        err = compile_error[0]
        raise fail(422, err.code, message=err.message)
    await _backup_script(
        db, mailbox=mailbox, script_name=script_name, content=current, reason="filters_save", person_id=person.id
    )
    new_script = new_script_holder.get("content") or current
    audit(
        db,
        "settings.filters_saved",
        account_id=ctx.account.id,
        person_id=person.id,
        object_type="mailbox",
        object_id=str(mailbox.id),
        ip=client_ip(request),
        details={"script_name": script_name, "backup": True},
    )
    await db.commit()
    out = parse_roundcube_script(new_script, script_name=script_name)
    return {
        "rules": filters_to_dicts([r for r in out.rules if r.kind != "vacation"]),
        "script_name": script_name,
        "has_backup": True,
    }


@router.get("/mailboxes/{mailbox_ref}/vacation")
async def get_vacation(
    mailbox_ref: str, request: Request, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> dict[str, Any]:
    mailbox = await _mailbox(db, ctx, mailbox_ref)
    stored = await _section(db, person.id, f"vacation.{mailbox.id}")
    user, password = await _mailbox_creds(db, settings, ctx, mailbox)
    try:
        script_name, script, _supports = await load_active_script(
            redis=request.app.state.redis,
            settings=settings,
            mailbox=mailbox,
            username=user,
            password=password,
        )
        parsed = parse_roundcube_script(script, script_name=script_name)
        data = _vacation_payload(parsed.vacation)
        if stored:
            # Prefer script (combined SK/EN/DE); fill gaps from last saved settings
            data["body_en"] = data.get("body_en") or stored.get("body_en") or data["body_en"]
            data["body_de"] = data.get("body_de") or stored.get("body_de") or data["body_de"]
            if not data.get("subject") and stored.get("subject"):
                data["subject"] = stored["subject"]
        data["script_name"] = script_name
        data["has_backup"] = (await _latest_backup(db, mailbox.id)) is not None
        data["mailbox_scope_help"] = "Platí pre celú schránku"
        data["last_changed"] = await _vacation_last_changed(db, mailbox.id)
        return data
    except SieveError as exc:
        if exc.code in {"sieve_auth_failed", "sieve_host_not_allowed", "sieve_disabled"}:
            raise fail(409, exc.code) from exc
        data = stored or _vacation_payload(VacationSettings())
        data["mailbox_scope_help"] = "Platí pre celú schránku"
        data["last_changed"] = await _vacation_last_changed(db, mailbox.id)
        data.update(_sieve_unavailable_payload())
        return data


@router.put("/mailboxes/{mailbox_ref}/vacation")
async def put_vacation(
    mailbox_ref: str, body: VacationIn, request: Request, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> dict[str, Any]:
    mailbox = await _mailbox(db, ctx, mailbox_ref)
    await _require_sieve_write(db, ctx, person, mailbox)
    if body.end and body.start and body.end < body.start:
        raise fail(422, "vacation_range_invalid")
    vac = VacationSettings(
        enabled=body.enabled,
        subject=body.subject[:120],
        body_sk=body.body_sk,
        body_en=body.body_en,
        body_de=body.body_de,
        days=body.days,
        start=body.start,
        end=body.end,
    )
    user, password = await _mailbox_creds(db, settings, ctx, mailbox)

    def build(script_name: str, current: str, supports_variables: bool) -> str:
        # Same active script — never activate another set for vacation
        return apply_vacation_to_script(
            current,
            vac,
            script_name=script_name,
            supports_variables=supports_variables,
        )

    try:
        script_name, current = await read_then_write_script(
            redis=request.app.state.redis,
            settings=settings,
            mailbox=mailbox,
            username=user,
            password=password,
            build=build,
        )
    except SieveError as exc:
        raise fail(
            409,
            exc.code,
            detail=exc.detail,
            message=SIEVE_UNAVAILABLE_MESSAGE_SK if exc.code == "sieve_unavailable" else None,
        ) from exc
    await _backup_script(
        db, mailbox=mailbox, script_name=script_name, content=current, reason="vacation_save", person_id=person.id
    )
    data = _vacation_payload(vac)
    data["script_name"] = script_name
    await save_section(db, person.id, f"vacation.{mailbox.id}", data)
    audit(
        db,
        "settings.vacation_saved",
        account_id=ctx.account.id,
        person_id=person.id,
        object_type="mailbox",
        object_id=str(mailbox.id),
        ip=client_ip(request),
        details={"script_name": script_name, "enabled": vac.enabled, "backup": True},
    )
    await db.commit()
    data["has_backup"] = True
    return data


@router.post("/mailboxes/{mailbox_ref}/sieve/restore")
async def restore_sieve(
    mailbox_ref: str, request: Request, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> dict[str, Any]:
    """Obnoviť predchádzajúcu verziu of the active ManageSieve script."""
    mailbox = await _mailbox(db, ctx, mailbox_ref)
    await _require_sieve_write(db, ctx, person, mailbox)
    backup = await _latest_backup(db, mailbox.id)
    if backup is None:
        raise fail(404, "sieve_backup_missing")
    user, password = await _mailbox_creds(db, settings, ctx, mailbox)
    try:
        script_name, current, _supports = await save_active_script(
            redis=request.app.state.redis,
            settings=settings,
            mailbox=mailbox,
            username=user,
            password=password,
            content=backup.content,
            script_name=backup.script_name or None,
        )
    except SieveError as exc:
        raise fail(
            409,
            exc.code,
            detail=exc.detail,
            message=SIEVE_UNAVAILABLE_MESSAGE_SK if exc.code == "sieve_unavailable" else None,
        ) from exc
    await _backup_script(
        db, mailbox=mailbox, script_name=script_name, content=current, reason="restore", person_id=person.id
    )
    audit(
        db,
        "settings.sieve_restored",
        account_id=ctx.account.id,
        person_id=person.id,
        object_type="mailbox",
        object_id=str(mailbox.id),
        ip=client_ip(request),
        details={"script_name": backup.script_name, "backup_id": str(backup.id)},
    )
    await db.commit()
    parsed = parse_roundcube_script(backup.content, script_name=backup.script_name)
    return {
        "ok": True,
        "script_name": backup.script_name,
        "rules": filters_to_dicts([r for r in parsed.rules if r.kind != "vacation"]),
        "vacation": _vacation_payload(parsed.vacation),
    }


# ----- 09b provider -----


@router.get("/mailboxes/{mailbox_ref}/provider")
async def provider_info(mailbox_ref: str, ctx: Auth, db: DB) -> dict[str, Any]:
    mailbox = await _mailbox(db, ctx, mailbox_ref)
    return {
        "email": mailbox.email,
        "imap_host": mailbox.imap_host,
        "imap_port": mailbox.imap_port,
        "quota_used_kb": mailbox.quota_used_kb,
        "quota_limit_kb": mailbox.quota_limit_kb,
        "last_synced_at": mailbox.last_synced_at.isoformat() if mailbox.last_synced_at else None,
        "provider_admin_url": mailbox.provider_admin_url,
        "vacation_hint": "Používajte Mimo kancelárie (06).",
    }


# ----- 09 security sessions -----


@router.get("/security/sessions")
async def list_sessions(ctx: Auth, db: DB) -> list[dict[str, Any]]:
    from app.auth.models import Session

    rows = (
        await db.scalars(
            select(Session)
            .where(Session.account_id == ctx.account.id, Session.revoked_at.is_(None))
            .order_by(Session.last_seen_at.desc())
        )
    ).all()
    return [
        {
            "id": str(s.id),
            "device_id": s.device_id,
            "last_seen_at": s.last_seen_at.isoformat() if s.last_seen_at else None,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "active_person_id": str(s.active_person_id) if s.active_person_id else None,
            "current": s.id == ctx.session.id,
        }
        for s in rows
    ]


@router.post("/security/sessions/{session_id}/revoke")
async def revoke_session(session_id: uuid.UUID, request: Request, ctx: Auth, db: DB) -> dict[str, bool]:
    from app.auth.models import Session

    row = await db.get(Session, session_id)
    if row is None or row.account_id != ctx.account.id:
        raise fail(404, "session_not_found")
    if row.id == ctx.session.id:
        raise fail(409, "cannot_revoke_current")
    row.revoked_at = datetime.now(UTC)
    row.revoked_reason = "user"
    await db.commit()
    return {"ok": True}


# ----- admin 10 users -----


def _rule(exc: AccountRuleError) -> HTTPException:
    return fail(exc.status, exc.code)


async def _user_out(db: DB, a: Account) -> dict[str, Any]:
    person = await db.get(Person, a.person_id) if a.person_id else None
    branch = await db.get(Branch, a.branch_id) if a.branch_id else None
    return {
        # „Osoby“ of a branch login in the list (W12-10, #55): who appears in its „Kto ste?“
        "persons_count": len(await eligible_persons(db, a)) if a.kind == AccountKind.branch else None,
        "id": str(a.id),
        "email": a.email,
        "kind": a.kind.value,
        "active": a.active,
        "last_login_at": a.last_login_at.isoformat() if a.last_login_at else None,
        "require_2fa": a.require_2fa,
        "branch_id": str(branch.id) if branch else None,
        "branch_name": branch.name if branch else None,
        "person": {
            "id": str(person.id),
            "first_name": person.first_name,
            "last_name": person.last_name,
            "role": person.role.value,
            "active": person.active,
        }
        if person
        else None,
    }


async def _account_state(db: DB, a: Account) -> dict[str, Any]:
    """Audited before/after of an account (SETTINGS_SPEC: admin changes with before/after) — never secrets."""
    person = await db.get(Person, a.person_id) if a.person_id else None
    return {
        "kind": a.kind.value,
        "branch_id": str(a.branch_id) if a.branch_id else None,
        "role": person.role.value if person else None,
        "active": a.active,
    }


def _person_state(p: Person) -> dict[str, Any]:
    return {
        "first_name": p.first_name,
        "last_name": p.last_name,
        "function": p.function,
        "role": p.role.value,
        "is_manager": p.is_manager,
        "active": p.active,
        "branch_id": str(p.branch_id) if p.branch_id else None,
    }


@router.get("/admin/users")
async def admin_users(ctx: Auth, db: DB) -> list[dict[str, Any]]:
    require_admin(ctx)
    accounts = (await db.scalars(select(Account).order_by(Account.email))).all()
    return [await _user_out(db, a) for a in accounts]


class UserIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    kind: AccountKind = AccountKind.personal
    branch_id: uuid.UUID | None = None
    first_name: str | None = Field(default=None, max_length=50)
    last_name: str | None = Field(default=None, max_length=50)
    role: Role = Role.sales


@router.post("/admin/users")
async def create_user(body: UserIn, request: Request, ctx: RecentReauth, db: DB) -> dict[str, Any]:
    admin = require_admin(ctx)
    if "@" not in body.email:
        raise fail(422, "email_invalid")
    try:
        account = await create_account(
            db,
            body.email,
            kind=body.kind,
            branch_id=body.branch_id,
            first_name=body.first_name,
            last_name=body.last_name,
            role=body.role,
        )
    except AccountRuleError as exc:
        await db.rollback()
        raise _rule(exc) from None
    audit(
        db,
        "settings.user_created",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="account",
        object_id=str(account.id),
        ip=client_ip(request),
        details={"before": None, "after": await _account_state(db, account)},
    )
    await db.commit()
    return await _user_out(db, account)


class VerifyIn(BaseModel):
    password: str = Field(min_length=1, max_length=512)


class UserPatch(BaseModel):
    active: bool | None = None
    kind: AccountKind | None = None
    branch_id: uuid.UUID | None = None
    role: Role | None = None  # applied to the person of a personal account


@router.patch("/admin/users/{account_id}")
async def patch_user(
    account_id: uuid.UUID, body: UserPatch, request: Request, ctx: RecentReauth, db: DB
) -> dict[str, Any]:
    admin = require_admin(ctx)
    account = await db.get(Account, account_id)
    if account is None:
        raise fail(404, "account_not_found")
    details: dict[str, Any] = {"before": await _account_state(db, account)}
    try:
        if body.active is not None and body.active != account.active:
            account.active = body.active
        target_kind = body.kind or account.kind
        if target_kind == AccountKind.branch:
            branch_id = body.branch_id or account.branch_id
            branch = await db.get(Branch, branch_id) if branch_id else None
            if branch is None:
                raise AccountRuleError(422, "branch_required")
            if account.kind != AccountKind.branch or account.branch_id != branch.id:
                details["revoked_sessions"] = await convert_to_branch(db, account, branch)
        elif account.kind == AccountKind.branch:
            # a personal login needs its own person: create it as a new account instead
            raise AccountRuleError(422, "person_required")
        if body.role is not None and account.kind == AccountKind.personal and account.person_id:
            person = await db.get(Person, account.person_id)
            if person is not None and person.role != body.role:
                person.role = body.role
        await ensure_admin_remains(db)
        details["after"] = await _account_state(db, account)
    except AccountRuleError as exc:
        await db.rollback()
        raise _rule(exc) from None
    audit(
        db,
        "settings.user_patched",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="account",
        object_id=str(account.id),
        ip=client_ip(request),
        details=details,
    )
    await db.commit()
    if "revoked_sessions" in details:
        await forget_revoked_reauth(db, request.app.state.redis, account.id)
    return await _user_out(db, account)


@router.post("/admin/users/{account_id}/verify")
async def verify_user_login(
    account_id: uuid.UUID,
    body: VerifyIn,
    request: Request,
    ctx: RecentReauth,
    db: DB,
    authenticator: Authenticator,
    limiter: Limiter,
) -> dict[str, Any]:
    """„Overiť“ (W12-10): test the login on the mail server with a password typed by the admin. The password is
    neither stored nor logged; failures count towards the login rate limit of that address."""
    admin = require_admin(ctx)
    account = await db.get(Account, account_id)
    if account is None:
        raise fail(404, "account_not_found")
    ip = client_ip(request)
    lock = await limiter.check(account.email, ip)
    if lock.locked:
        raise fail(429, "rate_limited", retry_after=lock.retry_after_s)
    result = await authenticator.verify(account.email, body.password)
    if result is LoginResult.invalid_credentials:
        await limiter.fail(account.email, ip)
    audit(
        db,
        "settings.user_verified",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="account",
        object_id=str(account.id),
        ip=ip,
        details={"result": result.value},
    )
    await db.commit()
    if result is LoginResult.server_unavailable:
        raise fail(503, "mail_server_unavailable")
    if result is LoginResult.invalid_credentials:
        raise fail(422, "verify_failed")
    return {"result": "ok"}


@router.post("/admin/users/{account_id}/logout-all")
async def logout_user_everywhere(account_id: uuid.UUID, request: Request, ctx: RecentReauth, db: DB) -> dict[str, Any]:
    """„Odhlásiť zo všetkých zariadení“: revokes every session of the login (the admin's own too, if theirs)."""
    admin = require_admin(ctx)
    account = await db.get(Account, account_id)
    if account is None:
        raise fail(404, "account_not_found")
    revoked = await revoke_account_sessions(db, account.id, RevokeReason.admin_logout, now=datetime.now(UTC))
    audit(
        db,
        "settings.user_logged_out_everywhere",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="account",
        object_id=str(account.id),
        ip=client_ip(request),
        details={"revoked_sessions": revoked},
    )
    await db.commit()
    await forget_revoked_reauth(db, request.app.state.redis, account.id)
    return {"revoked_sessions": revoked}


async def _access_rows(db: DB, account: Account) -> list[dict[str, Any]]:
    own = await db.scalar(select(Mailbox.id).where(Mailbox.email == account.email))
    granted = {
        row.mailbox_id: row
        for row in (await db.scalars(select(MailboxAccess).where(MailboxAccess.account_id == account.id))).all()
    }
    mailboxes = (await db.scalars(select(Mailbox).order_by(Mailbox.email))).all()
    return [
        {
            "mailbox_id": str(m.id),
            "email": m.email,
            "read": m.id in granted,
            "send": bool(granted[m.id].can_send) if m.id in granted else False,
            # the login's own mailbox is granted again at every login, so it is not editable here
            "own": m.id == own,
        }
        for m in mailboxes
    ]


@router.get("/admin/users/{account_id}/mailbox-access")
async def user_mailbox_access(account_id: uuid.UUID, ctx: Auth, db: DB) -> list[dict[str, Any]]:
    require_admin(ctx)
    account = await db.get(Account, account_id)
    if account is None:
        raise fail(404, "account_not_found")
    return await _access_rows(db, account)


class AccessIn(BaseModel):
    mailbox_id: uuid.UUID
    read: bool
    send: bool = False


@router.put("/admin/users/{account_id}/mailbox-access")
async def save_user_mailbox_access(
    account_id: uuid.UUID, body: list[AccessIn], request: Request, ctx: RecentReauth, db: DB
) -> list[dict[str, Any]]:
    """„Prístup k schránkam“: Čítať / Odosielať ako per mailbox (Odosielať needs Čítať). The own mailbox stays."""
    admin = require_admin(ctx)
    account = await db.get(Account, account_id)
    if account is None:
        raise fail(404, "account_not_found")
    before = await _access_rows(db, account)
    own = {r["mailbox_id"] for r in before if r["own"]}
    known = {r["mailbox_id"] for r in before}
    for item in body:
        key = str(item.mailbox_id)
        if key not in known:
            raise fail(404, "mailbox_not_found")
        if key in own:
            continue
        row = await db.scalar(
            select(MailboxAccess).where(
                MailboxAccess.account_id == account.id, MailboxAccess.mailbox_id == item.mailbox_id
            )
        )
        if not item.read:
            if row is not None:
                await db.delete(row)
        elif row is None:
            db.add(MailboxAccess(account_id=account.id, mailbox_id=item.mailbox_id, can_send=item.send))
        else:
            row.can_send = item.send
    await db.flush()
    after = await _access_rows(db, account)
    audit(
        db,
        "settings.user_mailbox_access_saved",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="account",
        object_id=str(account.id),
        ip=client_ip(request),
        details={
            "before": [{k: r[k] for k in ("email", "read", "send")} for r in before],
            "after": [{k: r[k] for k in ("email", "read", "send")} for r in after],
        },
    )
    await db.commit()
    return after


# ----- admin 11 branches -----


def _admin_person(p: Person, covers: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "first_name": p.first_name,
        "last_name": p.last_name,
        "function": p.function,
        "role": p.role.value,
        "is_manager": p.is_manager,
        "active": p.active,
        "phone": p.phone,
        "mobile": p.mobile,
        "personal_email": p.personal_email,
        "photo_url": f"/api/settings/people/{p.id}/photo?v={p.updated_at.timestamp():.0f}" if p.photo_key else None,
        # „Pôsobí aj na pobočkách“ (person_branches, #55)
        "cover_branch_ids": covers or [],
    }


async def _covers(db: DB) -> dict[uuid.UUID, list[str]]:
    out: dict[uuid.UUID, list[str]] = {}
    for person_id, branch_id in (await db.execute(select(PersonBranch.person_id, PersonBranch.branch_id))).all():
        out.setdefault(person_id, []).append(str(branch_id))
    return out


@router.get("/admin/personal-people")
async def admin_personal_people(ctx: Auth, db: DB) -> list[dict[str, Any]]:
    """W12-11b „Osobné účty“ (#71): the persons of personal logins (eshop@), with the branch used for their
    signature."""
    require_admin(ctx)
    rows = (
        await db.execute(
            select(Person, Account.email)
            .join(Account, Account.person_id == Person.id)
            .where(Account.kind == AccountKind.personal)
            .order_by(Account.email)
        )
    ).all()
    return [
        {**_admin_person(p), "login_email": email, "branch_id": str(p.branch_id) if p.branch_id else None}
        for p, email in rows
    ]


@router.get("/admin/branches")
async def admin_branches(ctx: Auth, db: DB) -> list[dict[str, Any]]:
    require_admin(ctx)
    rows = (await db.scalars(select(Branch).order_by(Branch.name))).all()
    covers = await _covers(db)
    out = []
    for b in rows:
        # persons with an own login are listed under „Osobné účty“, their branch only feeds the signature (#71)
        people = (
            await db.scalars(select(Person).where(Person.branch_id == b.id, Person.id.not_in(own_login_person_ids())))
        ).all()
        mailbox = await db.get(Mailbox, b.mailbox_id) if b.mailbox_id else None
        login = await db.scalar(select(Account).where(Account.email == mailbox.email)) if mailbox else None
        out.append(
            {
                "id": str(b.id),
                "name": b.name,
                "address": b.address,
                "phone": b.phone,
                "hours": b.hours,
                "mailbox_id": str(b.mailbox_id) if b.mailbox_id else None,
                "mailbox_email": mailbox.email if mailbox else None,
                # the login that uses the branch mailbox; "Prepojiť prihlásenie s pobočkou" when not linked (#33)
                "login_account": {
                    "id": str(login.id),
                    "email": login.email,
                    "kind": login.kind.value,
                    "linked": login.kind == AccountKind.branch and login.branch_id == b.id,
                }
                if login
                else None,
                "idle_ask_minutes": b.idle_ask_minutes,
                "remember_days": b.remember_days,
                "signature_template_html": b.signature_template_html,
                "signature_images": _public_images(b.signature_images),
                "folder_ids": b.folder_ids,
                "money_centre_id": b.money_centre_id,
                "money_price_list_id": b.money_price_list_id,
                "money_warehouse_id": b.money_warehouse_id,
                "people": [_admin_person(p, covers.get(p.id)) for p in people],
                "logo_url": f"/api/settings/branches/{b.id}/logo?v={b.updated_at.timestamp():.0f}"
                if b.logo_key
                else None,
            }
        )
    return out


class BranchIn(BaseModel):
    name: str
    address: str | None = None
    phone: str | None = None
    hours: str | None = None
    mailbox_id: str | None = None
    idle_ask_minutes: int | None = None
    remember_days: int | None = None
    signature_template_html: dict[str, str] | None = None
    folder_ids: list[str] | None = None
    money_centre_id: str | None = None
    money_price_list_id: str | None = None
    money_warehouse_id: str | None = None


@router.post("/admin/branches")
async def create_branch(body: BranchIn, request: Request, ctx: Auth, db: DB) -> dict[str, Any]:
    admin = require_admin(ctx)
    existing = await db.scalar(select(Branch).where(Branch.name == body.name.strip()))
    if existing:
        raise fail(409, "branch_exists")
    branch = Branch(
        name=body.name.strip()[:120],
        address=body.address,
        phone=body.phone,
        hours=body.hours,
        mailbox_id=uuid.UUID(body.mailbox_id) if body.mailbox_id else None,
        signature_template_html=_branch_signature(body.signature_template_html),
        remember_days=body.remember_days or 30,
    )
    db.add(branch)
    await db.flush()
    audit(
        db,
        "settings.branch_created",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="branch",
        object_id=str(branch.id),
        ip=client_ip(request),
    )
    await db.commit()
    return {"id": str(branch.id), "name": branch.name}


@router.put("/admin/branches/{branch_id}")
async def update_branch(branch_id: uuid.UUID, body: BranchIn, request: Request, ctx: Auth, db: DB) -> dict[str, Any]:
    admin = require_admin(ctx)
    branch = await db.get(Branch, branch_id)
    if branch is None:
        raise fail(404, "branch_not_found")
    branch.name = body.name.strip()[:120]
    branch.address = body.address
    branch.phone = body.phone
    branch.hours = body.hours
    if body.mailbox_id:
        branch.mailbox_id = uuid.UUID(body.mailbox_id)
    if body.idle_ask_minutes is not None:
        branch.idle_ask_minutes = body.idle_ask_minutes or None
    if body.remember_days is not None:
        branch.remember_days = body.remember_days
    stripped: dict[str, list[str]] = {}
    if body.signature_template_html is not None:
        cleaned, stripped = _apply_branch_signature(body.signature_template_html)
        branch.signature_template_html = cleaned
    if body.folder_ids is not None:
        branch.folder_ids = body.folder_ids
    # Money IDs stored as opaque strings — never invent GUIDs (CLAUDE.md)
    if body.money_centre_id is not None:
        branch.money_centre_id = body.money_centre_id or None
    if body.money_price_list_id is not None:
        branch.money_price_list_id = body.money_price_list_id or None
    if body.money_warehouse_id is not None:
        branch.money_warehouse_id = body.money_warehouse_id or None
    audit(
        db,
        "settings.branch_saved",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="branch",
        object_id=str(branch.id),
        ip=client_ip(request),
    )
    await db.commit()
    return {
        "id": str(branch.id),
        "name": branch.name,
        "signature_template_html": branch.signature_template_html,
        "signature_images": _public_images(branch.signature_images),
        "signature_stripped": stripped,
    }


class PersonAdminIn(BaseModel):
    first_name: str
    last_name: str
    function: str | None = None
    phone: str | None = None
    mobile: str | None = None
    role: str = "sales"
    is_manager: bool = False
    active: bool = True
    personal_email: str | None = None
    # „Pobočka (pre podpis)“ — only for the person of a personal account; omitted = unchanged, null = no branch (#71)
    branch_id: uuid.UUID | None = None
    # „Pôsobí aj na pobočkách“ (#55): the person also shows in „Kto ste?“ of these branches; omitted = unchanged
    cover_branch_ids: list[uuid.UUID] | None = None


@router.post("/admin/branches/{branch_id}/people")
async def add_person(branch_id: uuid.UUID, body: PersonAdminIn, request: Request, ctx: Auth, db: DB) -> dict[str, Any]:
    admin = require_admin(ctx)
    branch = await db.get(Branch, branch_id)
    if branch is None:
        raise fail(404, "branch_not_found")
    try:
        role = Role(body.role)
    except ValueError:
        role = Role.sales
    person = Person(
        branch_id=branch.id,
        first_name=body.first_name.strip()[:50],
        last_name=body.last_name.strip()[:50],
        function=body.function,
        phone=body.phone,
        mobile=body.mobile,
        role=role,
        is_manager=body.is_manager,
        active=body.active,
        personal_email=body.personal_email,
    )
    db.add(person)
    await db.flush()
    if body.cover_branch_ids:
        await _set_covers(db, person, body.cover_branch_ids)
    audit(
        db,
        "settings.person_created",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="person",
        object_id=str(person.id),
        ip=client_ip(request),
        details={"before": None, "after": _person_state(person)},
    )
    await db.commit()
    return {"id": str(person.id), "first_name": person.first_name, "last_name": person.last_name}


async def _keep_one_active(db: DB, person: Person) -> None:
    """SETTINGS 11b: at least one active person stays on a branch (people with an own login only borrow the branch
    for their signature, #71)."""
    if await db.scalar(select(Account.id).where(Account.person_id == person.id)) is not None:
        return
    others = await db.scalar(
        select(func.count())
        .select_from(Person)
        .where(
            Person.branch_id == person.branch_id,
            Person.active.is_(True),
            Person.id != person.id,
            Person.id.not_in(own_login_person_ids()),
        )
    )
    if not others:
        raise fail(409, "last_active_person")


async def _set_covers(db: DB, person: Person, branch_ids: list[uuid.UUID]) -> list[str]:
    wanted = {b for b in branch_ids if b != person.branch_id}
    if wanted:
        known = set((await db.scalars(select(Branch.id).where(Branch.id.in_(wanted)))).all())
        if known != wanted:
            raise fail(404, "branch_not_found")
    await db.execute(delete(PersonBranch).where(PersonBranch.person_id == person.id))
    db.add_all(PersonBranch(person_id=person.id, branch_id=b) for b in wanted)
    await db.flush()
    return sorted(str(b) for b in wanted)


@router.put("/admin/people/{person_id}")
async def update_person_admin(
    person_id: uuid.UUID, body: PersonAdminIn, request: Request, ctx: Auth, db: DB
) -> dict[str, Any]:
    admin = require_admin(ctx)
    person = await db.get(Person, person_id)
    if person is None:
        raise fail(404, "person_not_found")
    before = _person_state(person)
    if body.role != person.role.value or body.active != person.active:
        await require_recent_reauth(request, ctx)  # ⚠ role / Aktívna (#54); names and phones need no re-auth
    covers_before = sorted((await _covers(db)).get(person.id, []))
    if person.active and not body.active and person.branch_id is not None:
        await _keep_one_active(db, person)
    person.first_name = body.first_name.strip()[:50]
    person.last_name = body.last_name.strip()[:50]
    person.function = body.function
    person.phone = body.phone
    person.mobile = body.mobile
    try:
        person.role = Role(body.role)
    except ValueError:
        pass
    person.is_manager = body.is_manager
    person.active = body.active
    person.personal_email = body.personal_email
    if "branch_id" in body.model_fields_set:
        own_login = await db.scalar(
            select(Account.id).where(Account.person_id == person.id, Account.kind == AccountKind.personal)
        )
        if own_login is None:
            raise fail(422, "branch_only_for_personal_account")
        if body.branch_id is not None and await db.get(Branch, body.branch_id) is None:
            raise fail(404, "branch_not_found")
        person.branch_id = body.branch_id
    covers_after = covers_before
    if body.cover_branch_ids is not None:
        covers_after = await _set_covers(db, person, body.cover_branch_ids)
    try:
        await ensure_admin_remains(db)
    except AccountRuleError as exc:
        await db.rollback()
        raise _rule(exc) from None
    audit(
        db,
        "settings.person_saved",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="person",
        object_id=str(person.id),
        ip=client_ip(request),
        details={
            "before": {**before, "cover_branch_ids": covers_before},
            "after": {**_person_state(person), "cover_branch_ids": covers_after},
        },
    )
    await db.commit()
    return {"id": str(person.id), "active": person.active, "role": person.role.value}


@router.delete("/admin/people/{person_id}")
async def delete_person_admin(person_id: uuid.UUID, request: Request, ctx: RecentReauth, db: DB) -> dict[str, Any]:
    """ "Odstrániť osobu": a person with history (audit, sent mail, own login) is only deactivated, so history keeps
    the name; the last active person of a branch stays (SETTINGS_SPEC 11b)."""
    admin = require_admin(ctx)
    person = await db.get(Person, person_id)
    if person is None:
        raise fail(404, "person_not_found")
    own_login = await db.scalar(select(Account.id).where(Account.person_id == person.id))
    if person.branch_id is not None and person.active and own_login is None:
        # people with an own login only borrow the branch for their signature (#71)
        others = await db.scalar(
            select(func.count())
            .select_from(Person)
            .where(
                Person.branch_id == person.branch_id,
                Person.active.is_(True),
                Person.id != person.id,
                Person.id.not_in(own_login_person_ids()),
            )
        )
        if not others:
            raise fail(409, "last_active_person")
    before = _person_state(person)
    drafts = select(func.count()).select_from(ComposeDraft)
    has_history = bool(
        await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.person_id == person.id))
        or own_login is not None
        or await db.scalar(
            drafts.where(or_(ComposeDraft.person_id == person.id, ComposeDraft.signature_person_id == person.id))
        )
    )
    if not has_history:
        # any other reference (a session, settings, …) makes the delete fail: then the person is only deactivated
        try:
            async with db.begin_nested():
                await db.delete(person)
                await db.flush()
        except IntegrityError:
            has_history = True
            person = await db.get(Person, person_id, populate_existing=True)
    if has_history and person is not None:
        person.active = False
    try:
        await ensure_admin_remains(db)
    except AccountRuleError as exc:
        await db.rollback()
        raise _rule(exc) from None
    outcome = "deactivated" if has_history else "deleted"
    audit(
        db,
        f"settings.person_{outcome}",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="person",
        object_id=str(person_id),
        ip=client_ip(request),
        details={"before": before, "after": _person_state(person) if has_history and person else None},
    )
    await db.commit()
    return {"id": str(person_id), "result": outcome}


@router.post("/admin/branches/{branch_id}/link-login")
async def link_branch_login(branch_id: uuid.UUID, request: Request, ctx: RecentReauth, db: DB) -> dict[str, Any]:
    """ "Prepojiť prihlásenie s pobočkou": the login of the branch mailbox becomes the branch login (created when the
    mailbox has none yet), so its next login shows "Kto ste?" (#33)."""
    admin = require_admin(ctx)
    branch = await db.get(Branch, branch_id)
    if branch is None:
        raise fail(404, "branch_not_found")
    mailbox = await db.get(Mailbox, branch.mailbox_id) if branch.mailbox_id else None
    if mailbox is None:
        raise fail(422, "mailbox_required")
    account = await db.scalar(select(Account).where(Account.email == mailbox.email))
    before = await _account_state(db, account) if account else None
    try:
        if account is None:
            account = await create_account(db, mailbox.email, kind=AccountKind.branch, branch_id=branch.id)
            revoked = 0
        else:
            revoked = await convert_to_branch(db, account, branch)
        await ensure_admin_remains(db)
    except AccountRuleError as exc:
        await db.rollback()
        raise _rule(exc) from None
    audit(
        db,
        "settings.branch_login_linked",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="account",
        object_id=str(account.id),
        ip=client_ip(request),
        details={"before": before, "after": await _account_state(db, account), "revoked_sessions": revoked},
    )
    await db.commit()
    await forget_revoked_reauth(db, request.app.state.redis, account.id)
    return await _user_out(db, account)


# ----- admin 12 mailboxes -----


@router.get("/admin/mailboxes")
async def admin_mailboxes(ctx: Auth, db: DB) -> list[dict[str, Any]]:
    require_admin(ctx)
    rows = (await db.scalars(select(Mailbox).order_by(Mailbox.email))).all()
    return [_mailbox_admin_out(m) for m in rows]


class MailboxAdminIn(BaseModel):
    kind: str | None = None
    imap_host: str | None = None
    imap_port: int | None = None
    imap_security: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_security: str | None = None
    sieve_enabled: bool | None = None
    sieve_host: str | None = None
    sieve_port: int | None = None
    provider_admin_url: str | None = None
    ai_enabled: bool | None = None


@router.put("/admin/mailboxes/{mailbox_id}")
async def update_mailbox_admin(
    mailbox_id: uuid.UUID, body: MailboxAdminIn, request: Request, ctx: RecentReauth, db: DB
) -> dict[str, Any]:
    admin = require_admin(ctx)
    mailbox = await db.get(Mailbox, mailbox_id)
    if mailbox is None:
        raise fail(404, "mailbox_not_found")
    data = body.model_dump(exclude_unset=True)
    if "ai_enabled" in data:
        from datetime import UTC, datetime

        from app.ai.service import disable_ai_on_mailbox, enable_ai_on_mailbox

        if data.pop("ai_enabled"):
            enable_ai_on_mailbox(mailbox, now=datetime.now(UTC))
        else:
            disable_ai_on_mailbox(mailbox)
    for key, value in data.items():
        setattr(mailbox, key, value)
    audit(
        db,
        "settings.mailbox_saved",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="mailbox",
        object_id=str(mailbox.id),
        ip=client_ip(request),
    )
    await db.commit()
    return _mailbox_admin_out(mailbox)


def _mailbox_admin_out(m: Mailbox) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "email": m.email,
        "kind": m.kind,
        "imap_host": m.imap_host,
        "imap_port": m.imap_port,
        "imap_security": m.imap_security,
        "smtp_host": m.smtp_host,
        "smtp_port": m.smtp_port,
        "smtp_security": m.smtp_security,
        "sieve_enabled": m.sieve_enabled,
        "sieve_host": m.sieve_host,
        "sieve_port": m.sieve_port,
        "provider_admin_url": m.provider_admin_url,
        "ai_enabled": m.ai_enabled,
        "ai_enabled_at": m.ai_enabled_at.isoformat() if m.ai_enabled_at else None,
        "sync_state": m.sync_state,
        "quota_used_kb": m.quota_used_kb,
        "quota_limit_kb": m.quota_limit_kb,
        "last_synced_at": m.last_synced_at.isoformat() if m.last_synced_at else None,
    }


def _apply_branch_signature(raw: dict[str, str]) -> tuple[dict[str, str], dict[str, list[str]]]:
    try:
        return apply_signature_languages(raw, require_sk=True)
    except SignatureError as exc:
        raise fail(422, exc.code, **exc.extra) from exc


def _branch_signature(raw: dict[str, str] | None) -> dict[str, str]:
    if not raw:
        return default_branch_template()
    cleaned, _stripped = _apply_branch_signature(raw)
    return cleaned


class RemotePreviewIn(BaseModel):
    urls: list[str] = Field(default_factory=list)


def _branch_managed(mailbox: Mailbox, account: Account) -> bool:
    return mailbox.kind in {"branch", "shared"} or account.kind == AccountKind.branch


@router.get("/signature-presets")
async def get_signature_presets(ctx: Auth) -> dict[str, dict[str, str]]:
    del ctx
    return signature_presets()


@router.get("/mailboxes/{mailbox_ref}/signature-context")
async def signature_context(mailbox_ref: str, ctx: Auth, db: DB) -> dict[str, Any]:
    mailbox = await _mailbox(db, ctx, mailbox_ref)
    branch = await db.scalar(select(Branch).where(Branch.mailbox_id == mailbox.id))
    managed = _branch_managed(mailbox, ctx.account)
    preview = ""
    if managed:
        # {email_pobocky} as in compose: the sender of the default identity, not the login mailbox (#68)
        default = await db.scalar(
            select(Identity)
            .where(Identity.mailbox_id == mailbox.id)
            .order_by(Identity.is_default.desc(), Identity.created_at)
            .limit(1)
        )
        preview = preview_signature_html(
            person=ctx.person,
            branch=branch,
            identity=None,
            email=default.email if default else mailbox.email,
            language="sk",
        )
    return {
        "mailbox_kind": mailbox.kind,
        "account_kind": ctx.account.kind.value,
        "branch_managed": managed,
        "preview_html": preview,
        "branch_id": str(branch.id) if branch else None,
    }


@router.post("/signature-remote-previews")
async def signature_remote_previews(body: RemotePreviewIn, ctx: Auth, settings: SettingsDep) -> dict[str, Any]:
    del ctx
    previews: dict[str, str] = {}
    for url in body.urls[:20]:
        if isinstance(url, str) and url.startswith("https://") and len(url) <= 2048:
            previews[url] = proxy_path(settings, url)
    return {"previews": previews}


async def _store_signature_file(settings: SettingsDep, existing: object, file: UploadFile) -> dict[str, Any]:
    if len(image_dicts(existing)) >= MAX_SIGNATURE_IMAGES:
        raise fail(422, "image_limit")
    data = await file.read()
    try:
        payload, content_type = normalize_signature_image(data)
    except SignatureImageError as exc:
        raise fail(422, exc.code) from exc
    av = await scan_bytes(settings, payload)
    if av == "infected":
        raise fail(422, "attachment_infected")
    key, _digest = storage.put_bytes(settings, payload, prefix="signatures")
    filename = (file.filename or "obrazok").rsplit("/", 1)[-1].rsplit("\\", 1)[-1][:80] or "obrazok"
    image_id = uuid.uuid4().hex
    return {
        "id": image_id,
        "cid": f"sig-{uuid.uuid4().hex}@smartmail",
        "storage_key": key,
        "content_type": content_type,
        "size": len(payload),
        "filename": filename,
    }


@router.post("/identities/{identity_id}/signature-images")
async def upload_identity_signature_image(
    identity_id: uuid.UUID,
    ctx: Auth,
    person: ActivePerson,
    db: DB,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    del person
    identity = await db.get(Identity, identity_id)
    if identity is None:
        raise fail(404, "identity_not_found")
    await _mailbox_by_id(db, ctx, identity.mailbox_id)
    rec = await _store_signature_file(settings, identity.signature_images, file)
    identity.signature_images = [*image_dicts(identity.signature_images), rec]
    await db.commit()
    return _public_images([rec])[0]


@router.post("/admin/branches/{branch_id}/signature-images")
async def upload_branch_signature_image(
    branch_id: uuid.UUID,
    ctx: Auth,
    db: DB,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    require_admin(ctx)
    branch = await db.get(Branch, branch_id)
    if branch is None:
        raise fail(404, "branch_not_found")
    rec = await _store_signature_file(settings, branch.signature_images, file)
    branch.signature_images = [*image_dicts(branch.signature_images), rec]
    await db.commit()
    return _public_images([rec])[0]


@router.get("/signature-images/{image_id}")
async def get_signature_image(image_id: str, ctx: Auth, db: DB, settings: SettingsDep) -> Response:
    if len(image_id) != 32 or any(ch not in "0123456789abcdef" for ch in image_id):
        raise fail(404, "not_found")
    found: dict[str, Any] | None = None
    owner: uuid.UUID | None = None
    for identity in (await db.scalars(select(Identity))).all():
        for rec in image_dicts(identity.signature_images):
            if rec.get("id") == image_id:
                found = rec
                owner = identity.mailbox_id
                break
        if found:
            break
    if found is None:
        for branch in (await db.scalars(select(Branch))).all():
            for rec in image_dicts(branch.signature_images):
                if rec.get("id") == image_id:
                    found = rec
                    owner = branch.mailbox_id
                    break
            if found:
                break
    if found is None:
        raise fail(404, "not_found")
    admin = ctx.person is not None and ctx.person.role == Role.admin
    if not admin:
        if owner is None:
            raise fail(404, "not_found")
        access = await db.scalar(
            select(MailboxAccess).where(MailboxAccess.account_id == ctx.account.id, MailboxAccess.mailbox_id == owner)
        )
        if access is None:
            raise fail(404, "not_found")
    key = str(found.get("storage_key") or "")
    data = storage.get_bytes(settings, key)
    if not data:
        raise fail(404, "not_found")
    media = str(found.get("content_type") or "image/png")
    return Response(content=data, media_type=media)


# ----- 11a logo, 11b photo, „Vymazať pobočku“ (#55) -----


def _image_file(data: bytes | None) -> Response:
    if not data:
        raise fail(404, "not_found")
    return Response(content=data, media_type=sniff_image_type(data), headers={"Cache-Control": "private, max-age=300"})


@router.get("/branches/{branch_id}/logo")
async def branch_logo(branch_id: uuid.UUID, ctx: Auth, db: DB, settings: SettingsDep) -> Response:
    del ctx
    branch = await db.get(Branch, branch_id)
    if branch is None or not branch.logo_key:
        raise fail(404, "not_found")
    return _image_file(storage.get_bytes(settings, branch.logo_key))


@router.post("/admin/branches/{branch_id}/logo")
async def upload_branch_logo(
    branch_id: uuid.UUID,
    request: Request,
    ctx: Auth,
    db: DB,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    """„Logo do podpisu“: PNG (SVG is converted to PNG in the browser), max 200 kB — the {logo} variable."""
    admin = require_admin(ctx)
    branch = await db.get(Branch, branch_id)
    if branch is None:
        raise fail(404, "branch_not_found")
    try:
        payload, _ctype = normalize_signature_image(await file.read())
    except SignatureImageError as exc:
        raise fail(422, exc.code) from exc
    if await scan_bytes(settings, payload) == "infected":
        raise fail(422, "attachment_infected")
    branch.logo_key, _digest = storage.put_bytes(settings, payload, prefix="branch-logos")
    audit(
        db,
        "settings.branch_logo_saved",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="branch",
        object_id=str(branch.id),
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(branch)
    return {"logo_url": f"/api/settings/branches/{branch.id}/logo?v={branch.updated_at.timestamp():.0f}"}


@router.delete("/admin/branches/{branch_id}/logo")
async def delete_branch_logo(branch_id: uuid.UUID, request: Request, ctx: Auth, db: DB) -> dict[str, Any]:
    admin = require_admin(ctx)
    branch = await db.get(Branch, branch_id)
    if branch is None:
        raise fail(404, "branch_not_found")
    branch.logo_key = None
    audit(
        db,
        "settings.branch_logo_removed",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="branch",
        object_id=str(branch.id),
        ip=client_ip(request),
    )
    await db.commit()
    return {"logo_url": None}


@router.get("/people/{person_id}/photo")
async def person_photo(person_id: uuid.UUID, ctx: Auth, db: DB, settings: SettingsDep) -> Response:
    del ctx
    person = await db.get(Person, person_id)
    if person is None or not person.photo_key:
        raise fail(404, "not_found")
    return _image_file(storage.get_bytes(settings, person.photo_key))


@router.post("/admin/people/{person_id}/photo")
async def upload_person_photo(
    person_id: uuid.UUID,
    request: Request,
    ctx: Auth,
    db: DB,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    """„Fotka“ (SETTINGS 11b): JPG/PNG up to 5 MB, cropped to a square — {fotka} in the signature."""
    admin = require_admin(ctx)
    person = await db.get(Person, person_id)
    if person is None:
        raise fail(404, "person_not_found")
    try:
        payload, _ctype = normalize_person_photo(await file.read())
    except SignatureImageError as exc:
        raise fail(422, exc.code) from exc
    if await scan_bytes(settings, payload) == "infected":
        raise fail(422, "attachment_infected")
    person.photo_key, _digest = storage.put_bytes(settings, payload, prefix="person-photos")
    audit(
        db,
        "settings.person_photo_saved",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="person",
        object_id=str(person.id),
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(person)
    return {"photo_url": f"/api/settings/people/{person.id}/photo?v={person.updated_at.timestamp():.0f}"}


@router.delete("/admin/people/{person_id}/photo")
async def delete_person_photo(person_id: uuid.UUID, request: Request, ctx: Auth, db: DB) -> dict[str, Any]:
    admin = require_admin(ctx)
    person = await db.get(Person, person_id)
    if person is None:
        raise fail(404, "person_not_found")
    person.photo_key = None
    audit(
        db,
        "settings.person_photo_removed",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="person",
        object_id=str(person.id),
        ip=client_ip(request),
    )
    await db.commit()
    return {"photo_url": None}


@router.get("/admin/branch-folders")
async def branch_folders(ctx: Auth, db: DB) -> list[dict[str, Any]]:
    """„Priečinky pobočky“ (SETTINGS 11a, D21): the customer's own folders of all mailboxes (no special folders)."""
    require_admin(ctx)
    rows = (
        await db.execute(
            select(FolderMeta.id, FolderMeta.name, Mailbox.email)
            .join(Mailbox, Mailbox.id == FolderMeta.mailbox_id)
            .where(FolderMeta.special_use.is_(None), FolderMeta.selectable.is_(True))
            .order_by(Mailbox.email, FolderMeta.name)
        )
    ).all()
    return [{"id": str(fid), "name": name, "mailbox_email": email} for fid, name, email in rows]


@router.delete("/admin/branches/{branch_id}")
async def delete_branch(branch_id: uuid.UUID, request: Request, ctx: RecentReauth, db: DB) -> dict[str, Any]:
    """„Vymazať pobočku“: only an empty branch — no active person and no login of the branch (409 otherwise).
    Inactive persons keep their name in history and lose the branch; covers go with the branch."""
    admin = require_admin(ctx)
    branch = await db.get(Branch, branch_id)
    if branch is None:
        raise fail(404, "branch_not_found")
    active = await db.scalar(
        select(func.count())
        .select_from(Person)
        .where(Person.branch_id == branch.id, Person.active.is_(True), Person.id.not_in(own_login_person_ids()))
    )
    if active:
        raise fail(409, "branch_has_people", count=int(active))
    if await db.scalar(select(Account.id).where(Account.branch_id == branch.id)) is not None:
        raise fail(409, "branch_has_login")
    before = {"name": branch.name, "mailbox_id": str(branch.mailbox_id) if branch.mailbox_id else None}
    await db.execute(update(Person).where(Person.branch_id == branch.id).values(branch_id=None))
    try:
        async with db.begin_nested():
            await db.delete(branch)
            await db.flush()
    except IntegrityError:
        await db.rollback()
        raise fail(409, "branch_in_use") from None
    audit(
        db,
        "settings.branch_deleted",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="branch",
        object_id=str(branch_id),
        ip=client_ip(request),
        details={"before": before, "after": None},
    )
    await db.commit()
    return {"id": str(branch_id), "result": "deleted"}


# ----- helpers -----


async def _mailbox(db: DB, ctx: Auth, ref: str) -> Mailbox:
    if ref == "default":
        access = await db.scalar(select(MailboxAccess).where(MailboxAccess.account_id == ctx.account.id).limit(1))
        if access is None:
            raise fail(404, "mailbox_not_found")
        mailbox = await db.get(Mailbox, access.mailbox_id)
    else:
        try:
            mid = uuid.UUID(ref)
        except ValueError:
            mailbox = await db.scalar(select(Mailbox).where(Mailbox.email == ref.lower()))
        else:
            mailbox = await db.get(Mailbox, mid)
    if mailbox is None:
        raise fail(404, "mailbox_not_found")
    access = await db.scalar(
        select(MailboxAccess).where(MailboxAccess.account_id == ctx.account.id, MailboxAccess.mailbox_id == mailbox.id)
    )
    if access is None and (ctx.person is None or ctx.person.role != Role.admin):
        raise fail(403, "mailbox_forbidden")
    return mailbox


async def _mailbox_by_id(db: DB, ctx: Auth, mailbox_id: uuid.UUID) -> Mailbox:
    return await _mailbox(db, ctx, str(mailbox_id))


@router.get("/nav")
async def settings_nav(ctx: Auth) -> dict[str, Any]:
    """Section list in Roundcube order for the W12 left column."""
    is_admin = ctx.person is not None and ctx.person.role == Role.admin
    sections = []
    for section in schema_document()["sections"]:
        if section.get("admin_only") and not is_admin:
            continue
        sections.append(
            {
                "id": section["id"],
                "path": section["path"],
                "title": section["title"],
                "subs": [{"id": s["id"], "path": s["path"], "title": s["title"]} for s in section.get("subs") or []],
            }
        )
    return {"sections": sections, "paths": SECTION_PATHS}
