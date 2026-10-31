"""Phase 3f: CRM activity in Money after a person sent an invoice / reminder e-mail (Erik's answers in #144).

- Automatic after the send (the person's send is the approval), only when Settings 13a „Zápisy do Money povolené“
  (default off) **and** 13d „Zapisovať aktivitu…“ are on and the activity type is chosen.
- Only the subject and the invoice numbers go to Money — never the mail body. `SMID:<draft_id>` makes it idempotent.
- One attempt, never retried automatically; a failure is listed for the admin (13d) who may retry by hand.
- Every outcome is in the audit log (`money.activity_written` / `money.activity_failed`), which is also the list.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Literal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import OrgSettings
from app.core.audit import AuditLog, audit
from app.core.config import Settings
from app.mail.compose_models import ComposeAttachment, ComposeDraft
from app.money.approval import ApprovalKeyMissing, sign_approval
from app.money.bridge_client import BridgeClient, BridgeUnavailable
from app.money.invoice_attach import marked_company
from app.money.reminders import AUDIT_ACTION as REMINDER_ACTION

log = structlog.get_logger(__name__)

SECTION_WRITES = "money.writes"
SECTION_ACTIVITIES = "money.activities"
WRITTEN = "money.activity_written"
FAILED = "money.activity_failed"
ACTION = "activity.create"
Kind = Literal["email", "reminder"]


@dataclass(frozen=True)
class ActivitySettings:
    writes_enabled: bool
    enabled: bool
    type_email: str | None
    type_reminder: str | None


async def _data(db: AsyncSession, section: str) -> dict[str, Any]:
    row = await db.scalar(select(OrgSettings).where(OrgSettings.section == section))
    return dict(row.data) if row else {}


async def load_activity_settings(db: AsyncSession) -> ActivitySettings:
    writes = await _data(db, SECTION_WRITES)
    data = await _data(db, SECTION_ACTIVITIES)
    return ActivitySettings(
        writes_enabled=writes.get("enabled") is True,
        enabled=data.get("enabled", True) is True,  # SETTINGS_SPEC 13d: default on (the 13a main switch is off)
        type_email=str(data["type_email"]) if data.get("type_email") else None,
        type_reminder=str(data["type_reminder"]) if data.get("type_reminder") else None,
    )


async def _marked(db: AsyncSession, draft: ComposeDraft) -> tuple[uuid.UUID | None, list[str]]:
    atts = (await db.scalars(select(ComposeAttachment).where(ComposeAttachment.draft_id == draft.id))).all()
    companies = {c for c in (marked_company(a.storage_key) for a in atts) if c is not None}
    numbers = [
        m.group(1) for a in atts if marked_company(a.storage_key) and (m := re.search(r"_([^_]+)\.pdf$", a.filename))
    ]
    return (next(iter(companies)) if len(companies) == 1 else None), numbers


async def _kind(db: AsyncSession, draft: ComposeDraft) -> Kind:
    rows = await db.scalars(select(AuditLog.details).where(AuditLog.action == REMINDER_ACTION))
    return "reminder" if any((d or {}).get("draft_id") == str(draft.id) for d in rows) else "email"


def needs_activity(storage_keys: list[str]) -> bool:
    return any(marked_company(k) is not None for k in storage_keys)


async def write_activity(
    db: AsyncSession, settings: Settings, draft_id: uuid.UUID, *, client: BridgeClient | None = None
) -> str:
    """One attempt for one sent draft. Returns the outcome; the caller commits. Never raises for Money errors."""
    draft = await db.get(ComposeDraft, draft_id)
    if draft is None or draft.status != "sent":
        return "not_sent"
    if not settings.feature_money:
        return "money_disabled"
    conf = await load_activity_settings(db)
    if not conf.writes_enabled or not conf.enabled:
        return "switched_off"
    company, numbers = await _marked(db, draft)
    if company is None:
        return "no_company"
    if await db.scalar(select(AuditLog.id).where(AuditLog.action == WRITTEN, AuditLog.object_id == str(draft.id))):
        return "already_written"
    kind = await _kind(db, draft)
    type_id = conf.type_reminder if kind == "reminder" else conf.type_email
    details: dict[str, Any] = {"company_money_id": str(company), "kind": kind, "invoices": numbers}
    if not type_id:
        return _fail(db, draft, details, "activity_type_missing")
    payload = {
        "company_id": str(company),
        "type_id": type_id,
        "subject": (draft.subject or "")[:200] or "E-mail",
        "description": ("Faktúry: " + ", ".join(numbers))[:1000] if numbers else "",
        "smid": f"SMID:{draft.id}",
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    try:
        token = sign_approval(settings, action=ACTION, company_id=company, person_id=draft.person_id, body=body)
    except ApprovalKeyMissing:
        return _fail(db, draft, details, "approval_key_missing")
    bridge = client or BridgeClient(settings)
    try:
        out = await bridge.create_activity(payload, token)
    except BridgeUnavailable as exc:
        return _fail(db, draft, details, exc.code)
    finally:
        if client is None:
            await bridge.aclose()
    audit(
        db,
        WRITTEN,
        account_id=draft.account_id,
        person_id=draft.person_id,
        object_type="compose_draft",
        object_id=str(draft.id),
        details={**details, "money_activity_id": str(out.id), "created": out.created},
    )
    log.info("money.activity_written", draft_id=str(draft.id), created=out.created)
    return "written"


def _fail(db: AsyncSession, draft: ComposeDraft, details: dict[str, Any], code: str) -> str:
    audit(
        db,
        FAILED,
        account_id=draft.account_id,
        person_id=draft.person_id,
        object_type="compose_draft",
        object_id=str(draft.id),
        details={**details, "error": code[:60]},
    )
    log.warning("money.activity_failed", draft_id=str(draft.id), error=code)
    return code


async def failed_activities(db: AsyncSession, limit: int = 50) -> list[AuditLog]:
    """13d list: the latest failure per draft that has no later success."""
    written = set(await db.scalars(select(AuditLog.object_id).where(AuditLog.action == WRITTEN)))
    rows = (
        await db.scalars(
            select(AuditLog).where(AuditLog.action == FAILED).order_by(AuditLog.created_at.desc()).limit(limit * 4)
        )
    ).all()
    out: list[AuditLog] = []
    seen: set[str] = set()
    for row in rows:
        key = str(row.object_id)
        if key in written or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out[:limit]


async def enqueue_after_send(db: AsyncSession, settings: Settings, draft: ComposeDraft) -> None:
    """Called once the SMTP server accepted a draft. Only drafts with a Money invoice attachment (3d / 3e) and only
    while both switches are on; the job runs once (`max_tries=1`). Never breaks the send."""
    if not settings.feature_money:
        return
    keys = list(await db.scalars(select(ComposeAttachment.storage_key).where(ComposeAttachment.draft_id == draft.id)))
    if not needs_activity(keys):
        return
    conf = await load_activity_settings(db)
    if not conf.writes_enabled or not conf.enabled:
        return
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await redis.enqueue_job("money_activity_job", str(draft.id), _job_id=f"money-activity:{draft.id}")
        await redis.aclose()
    except Exception as exc:  # the mail is sent; the admin sees the missing activity in 13d
        company, numbers = await _marked(db, draft)
        _fail(db, draft, {"company_money_id": str(company), "invoices": numbers}, "enqueue_failed")
        await db.commit()
        log.warning("money.activity_enqueue_failed", draft_id=str(draft.id), error=type(exc).__name__)
