"""Settings W12 API — Phase 1f sections 01–06, 09, 09b, 10–12."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.deps import DB, ActivePerson, Auth, SettingsDep, client_ip
from app.auth.models import Account, AccountKind, Branch, Person, Role
from app.auth.security import decrypt
from app.core.audit import audit
from app.mail.compose_models import CannedResponse, Identity
from app.mail.models import Mailbox, MailboxAccess, SieveScriptBackup
from app.mail.prefs import get_list_prefs, get_ui_prefs, save_section
from app.mail.sanitize import sanitize_html
from app.mail.sieve import (
    DEFAULT_SCRIPT_NAME,
    ParsedScript,
    SieveError,
    VacationSettings,
    active_script_name,
    apply_vacation_to_script,
    compile_script,
    connect_sieve,
    dicts_to_filters,
    filters_to_dicts,
    get_script,
    parse_roundcube_script,
    put_script,
)
from app.mail.signature import default_branch_template, render_signature
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
    preview = render_signature(person=person, branch=branch, identity=None, email=ctx.account.email)
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


@router.put("/identities/{identity_id}")
async def update_identity(
    identity_id: uuid.UUID, body: IdentityIn, request: Request, ctx: Auth, person: ActivePerson, db: DB
) -> dict[str, Any]:
    identity = await db.get(Identity, identity_id)
    if identity is None:
        raise fail(404, "identity_not_found")
    await _mailbox_by_id(db, ctx, identity.mailbox_id)
    identity.display_name = body.display_name.strip()[:100]
    identity.email = body.email.strip().lower()
    identity.organization = (body.organization or "").strip()[:100] or None
    identity.reply_to = (body.reply_to or "").strip().lower() or None
    identity.bcc = [a.strip().lower() for a in body.bcc if a.strip()]
    cleaned: dict[str, str] = {}
    for lang, html in body.signature_html.items():
        cleaned[lang] = sanitize_html(html[:65_536])
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
    )
    await db.commit()
    await db.refresh(identity)
    return _identity_out(identity)


def _identity_out(i: Identity) -> dict[str, Any]:
    return {
        "id": str(i.id),
        "mailbox_id": str(i.mailbox_id),
        "display_name": i.display_name,
        "email": i.email,
        "organization": i.organization,
        "reply_to": i.reply_to,
        "bcc": i.bcc,
        "is_default": i.is_default,
        "signature_html": i.signature_html,
    }


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


@router.get("/mailboxes/{mailbox_ref}/filters")
async def get_filters(
    mailbox_ref: str, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> dict[str, Any]:
    mailbox = await _mailbox(db, ctx, mailbox_ref)
    script_name = DEFAULT_SCRIPT_NAME
    try:
        user, password = await _mailbox_creds(db, settings, ctx, mailbox)
        client = connect_sieve(settings, mailbox, username=user, password=password)
        script_name = active_script_name(client)
        script = get_script(client, script_name)
        client.logout()
    except SieveError as exc:
        if exc.code in {"sieve_auth_failed", "sieve_host_not_allowed", "sieve_disabled"}:
            raise fail(409, exc.code) from exc
        script = ""
    parsed = parse_roundcube_script(script, script_name=script_name)
    rules = [r for r in parsed.rules if r.kind != "vacation"]
    backup = await _latest_backup(db, mailbox.id)
    return {
        "rules": filters_to_dicts(rules),
        "script_name": script_name,
        "mailbox_scope": mailbox.kind,
        "has_backup": backup is not None,
        "help": (
            "Filter platí pre celú schránku (osobnú aj pobočkovú). "
            "Filtre nie sú predvolené – každá schránka má vlastné."
        ),
    }


@router.put("/mailboxes/{mailbox_ref}/filters")
async def put_filters(
    mailbox_ref: str, body: FiltersIn, request: Request, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> dict[str, Any]:
    mailbox = await _mailbox(db, ctx, mailbox_ref)
    rules = dicts_to_filters(body.rules)
    for i, rule in enumerate(rules):
        if not rule.id:
            rule.id = f"f{i + 1}-{uuid.uuid4().hex[:8]}"
        # UI edit clears raw so we recompile from conditions
        if rule.editable and rule.raw is None:
            pass
    try:
        user, password = await _mailbox_creds(db, settings, ctx, mailbox)
        client = connect_sieve(settings, mailbox, username=user, password=password)
        script_name = active_script_name(client)
        current = get_script(client, script_name)
        await _backup_script(
            db, mailbox=mailbox, script_name=script_name, content=current, reason="filters_save", person_id=person.id
        )
        parsed = parse_roundcube_script(current, script_name=script_name)
        # Keep vacation from the live script; replace only filter rules
        new_script = compile_script(
            ParsedScript(
                preamble=parsed.preamble,
                rules=rules,
                vacation=parsed.vacation,
                script_name=script_name,
            ),
            vacation=parsed.vacation,
            rules=rules,
            include_vacation=parsed.vacation.enabled or any(r.kind == "vacation" for r in parsed.rules),
        )
        put_script(client, script_name, new_script, activate=True)
        client.logout()
    except SieveError as exc:
        raise fail(409, exc.code, detail=exc.detail) from exc
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
    mailbox_ref: str, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> dict[str, Any]:
    mailbox = await _mailbox(db, ctx, mailbox_ref)
    stored = await _section(db, person.id, f"vacation.{mailbox.id}")
    try:
        user, password = await _mailbox_creds(db, settings, ctx, mailbox)
        client = connect_sieve(settings, mailbox, username=user, password=password)
        script_name = active_script_name(client)
        script = get_script(client, script_name)
        client.logout()
        parsed = parse_roundcube_script(script, script_name=script_name)
        data = _vacation_payload(parsed.vacation)
        if stored:
            # EN/DE live in DB (Sieve has one body — SK)
            data["body_en"] = stored.get("body_en") or data["body_en"]
            data["body_de"] = stored.get("body_de") or data["body_de"]
            if stored.get("subject"):
                data["subject"] = stored["subject"]
        data["script_name"] = script_name
        data["has_backup"] = (await _latest_backup(db, mailbox.id)) is not None
        return data
    except SieveError as exc:
        if exc.code in {"sieve_auth_failed", "sieve_host_not_allowed", "sieve_disabled"}:
            raise fail(409, exc.code) from exc
        if stored:
            return stored
        return _vacation_payload(VacationSettings())


@router.put("/mailboxes/{mailbox_ref}/vacation")
async def put_vacation(
    mailbox_ref: str, body: VacationIn, request: Request, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> dict[str, Any]:
    mailbox = await _mailbox(db, ctx, mailbox_ref)
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
    try:
        user, password = await _mailbox_creds(db, settings, ctx, mailbox)
        client = connect_sieve(settings, mailbox, username=user, password=password)
        script_name = active_script_name(client)
        current = get_script(client, script_name)
        await _backup_script(
            db, mailbox=mailbox, script_name=script_name, content=current, reason="vacation_save", person_id=person.id
        )
        # Same active script — never activate another set for vacation
        new_script = apply_vacation_to_script(current, vac, script_name=script_name)
        put_script(client, script_name, new_script, activate=True)
        client.logout()
    except SieveError as exc:
        raise fail(409, exc.code, detail=exc.detail) from exc
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
    backup = await _latest_backup(db, mailbox.id)
    if backup is None:
        raise fail(404, "sieve_backup_missing")
    try:
        user, password = await _mailbox_creds(db, settings, ctx, mailbox)
        client = connect_sieve(settings, mailbox, username=user, password=password)
        script_name = active_script_name(client)
        current = get_script(client, script_name)
        await _backup_script(
            db, mailbox=mailbox, script_name=script_name, content=current, reason="restore", person_id=person.id
        )
        put_script(client, backup.script_name or script_name, backup.content, activate=True)
        client.logout()
    except SieveError as exc:
        raise fail(409, exc.code, detail=exc.detail) from exc
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


@router.get("/admin/users")
async def admin_users(ctx: Auth, db: DB) -> list[dict[str, Any]]:
    require_admin(ctx)
    accounts = (await db.scalars(select(Account).order_by(Account.email))).all()
    return [
        {
            "id": str(a.id),
            "email": a.email,
            "kind": a.kind.value,
            "active": a.active,
            "last_login_at": a.last_login_at.isoformat() if a.last_login_at else None,
            "require_2fa": a.require_2fa,
        }
        for a in accounts
    ]


class UserPatch(BaseModel):
    active: bool | None = None
    kind: str | None = None
    role: str | None = None  # applied to linked personal person when present


@router.patch("/admin/users/{account_id}")
async def patch_user(account_id: uuid.UUID, body: UserPatch, request: Request, ctx: Auth, db: DB) -> dict[str, Any]:
    admin = require_admin(ctx)
    account = await db.get(Account, account_id)
    if account is None:
        raise fail(404, "account_not_found")
    if body.active is not None:
        account.active = body.active
    if body.kind is not None and body.kind in {"personal", "branch"}:
        account.kind = AccountKind(body.kind)
    await db.commit()
    audit(
        db,
        "settings.user_patched",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="account",
        object_id=str(account.id),
        ip=client_ip(request),
    )
    await db.commit()
    return {"id": str(account.id), "email": account.email, "kind": account.kind.value, "active": account.active}


# ----- admin 11 branches -----


@router.get("/admin/branches")
async def admin_branches(ctx: Auth, db: DB) -> list[dict[str, Any]]:
    require_admin(ctx)
    rows = (await db.scalars(select(Branch).order_by(Branch.name))).all()
    out = []
    for b in rows:
        people = (await db.scalars(select(Person).where(Person.branch_id == b.id))).all()
        mailbox = await db.get(Mailbox, b.mailbox_id) if b.mailbox_id else None
        out.append(
            {
                "id": str(b.id),
                "name": b.name,
                "address": b.address,
                "phone": b.phone,
                "hours": b.hours,
                "mailbox_id": str(b.mailbox_id) if b.mailbox_id else None,
                "mailbox_email": mailbox.email if mailbox else None,
                "idle_ask_minutes": b.idle_ask_minutes,
                "remember_days": b.remember_days,
                "signature_template_html": b.signature_template_html,
                "folder_ids": b.folder_ids,
                "money_centre_id": b.money_centre_id,
                "money_price_list_id": b.money_price_list_id,
                "money_warehouse_id": b.money_warehouse_id,
                "people": [
                    {
                        "id": str(p.id),
                        "first_name": p.first_name,
                        "last_name": p.last_name,
                        "function": p.function,
                        "role": p.role.value,
                        "is_manager": p.is_manager,
                        "active": p.active,
                        "mobile": p.mobile,
                    }
                    for p in people
                ],
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
        signature_template_html=body.signature_template_html or default_branch_template(),
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
    if body.signature_template_html is not None:
        cleaned = {lang: sanitize_html(html[:65_536]) for lang, html in body.signature_template_html.items()}
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
    return {"id": str(branch.id), "name": branch.name}


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
    audit(
        db,
        "settings.person_created",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="person",
        object_id=str(person.id),
        ip=client_ip(request),
    )
    await db.commit()
    return {"id": str(person.id), "first_name": person.first_name, "last_name": person.last_name}


@router.put("/admin/people/{person_id}")
async def update_person_admin(
    person_id: uuid.UUID, body: PersonAdminIn, request: Request, ctx: Auth, db: DB
) -> dict[str, Any]:
    admin = require_admin(ctx)
    person = await db.get(Person, person_id)
    if person is None:
        raise fail(404, "person_not_found")
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
    audit(
        db,
        "settings.person_saved",
        account_id=ctx.account.id,
        person_id=admin.id,
        object_type="person",
        object_id=str(person.id),
        ip=client_ip(request),
    )
    await db.commit()
    return {"id": str(person.id), "active": person.active, "role": person.role.value}


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
    mailbox_id: uuid.UUID, body: MailboxAdminIn, request: Request, ctx: Auth, db: DB
) -> dict[str, Any]:
    admin = require_admin(ctx)
    mailbox = await db.get(Mailbox, mailbox_id)
    if mailbox is None:
        raise fail(404, "mailbox_not_found")
    for key, value in body.model_dump(exclude_unset=True).items():
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
        "sync_state": m.sync_state,
        "quota_used_kb": m.quota_used_kb,
        "quota_limit_kb": m.quota_limit_kb,
        "last_synced_at": m.last_synced_at.isoformat() if m.last_synced_at else None,
    }


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
