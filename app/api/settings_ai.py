"""Settings 17d Štýl a znalosti and 17e Pravidlá (G, admin): style guide, knowledge cards, NL rules (Phase 2e, #110).

The audit records which card changed, never its text (#110)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.budget import budget_allows_call
from app.ai.categories import CATEGORIES, CATEGORY_BY_ID, CATEGORY_IDS
from app.ai.category_settings import (
    CUSTOM_ID,
    FALLBACK_ID,
    MAX_CUSTOM,
    MAX_DELETED,
    MAX_DESCRIPTION,
    MAX_LABEL,
    SECTION_CATEGORIES,
    all_categories,
    category_lookup,
    custom_id,
    deleted_categories,
    load_category_data,
    prompt_categories,
)
from app.ai.eval import SECTION_EVAL
from app.ai.eval_cli import score
from app.ai.eval_labels import MAX_UPLOAD_BYTES, SAMPLE_DEFAULT, LabelError, parse_labels, sample_csv, sample_rows
from app.ai.models import AiRule, AiRun, AiSuggestion, Classification, KnowledgeCard, OrgSettings
from app.ai.org_settings import (
    ALERT_DEFAULT,
    SECTION_LIMITS,
    AiLimits,
    limits_from,
    load_ai_limits,
    parse_budget,
    save_org_section,
)
from app.ai.pricing import estimate_purpose_cost_usd
from app.ai.provider import get_llm_provider
from app.ai.rule_parse import parse_rule
from app.ai.service import daily_spend_usd, ensure_shadow_flag, shadow_mode_enabled
from app.ai.style_profile import MIN_MAILS, PROFILE_CHARS, load_profile, save_profile, sent_samples
from app.ai.style_profile import generate as generate_profile
from app.ai.user_rules import MailFacts, StructuredRule, describe, rule_matches
from app.api.mail import _ai_provider_configured, fail
from app.api.settings import require_admin
from app.auth.deps import DB, ActivePerson, Auth, SettingsDep
from app.auth.models import Person
from app.auth.reauth import RecentReauth
from app.core.audit import audit
from app.core.config import Settings
from app.mail.mailboxes import accessible_mailboxes
from app.mail.models import Attachment, Message

router = APIRouter(prefix="/api/settings/ai", tags=["settings-ai"])
Admin = Annotated[Person, Depends(require_admin)]

MAX_BODY = 20000


class StyleGuideIn(BaseModel):
    body: str = Field(default="", max_length=MAX_BODY)


class StyleGuideOut(BaseModel):
    body: str
    updated_at: datetime | None


class CardIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=MAX_BODY)
    valid_until: date | None = None
    tags: list[str] = Field(default_factory=list, max_length=20)
    enabled: bool = True

    @field_validator("title", "body")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("empty")
        return value

    @field_validator("tags")
    @classmethod
    def _tags(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for tag in value:
            clean = tag.strip()[:64]
            if clean and clean.lower() not in {t.lower() for t in out}:
                out.append(clean)
        return out


class CardOut(BaseModel):
    id: str
    title: str
    body: str
    valid_until: date | None
    tags: list[str]
    enabled: bool
    expired: bool
    updated_at: datetime | None


def _out(card: KnowledgeCard) -> CardOut:
    return CardOut(
        id=str(card.id),
        title=card.title,
        body=card.body,
        valid_until=card.valid_until,
        tags=list(card.tags or []),
        enabled=card.enabled,
        expired=card.valid_until is not None and card.valid_until < date.today(),
        updated_at=card.updated_at,
    )


async def _card(db: DB, card_id: uuid.UUID) -> KnowledgeCard:
    card = await db.get(KnowledgeCard, card_id)
    if card is None or card.kind != "knowledge":
        raise fail(404, "card_not_found")
    return card


@router.get("/style-guide")
async def get_style_guide(admin: Admin, db: DB) -> StyleGuideOut:
    row = await db.scalar(select(KnowledgeCard).where(KnowledgeCard.kind == "style_guide"))
    return StyleGuideOut(body=row.body if row else "", updated_at=row.updated_at if row else None)


@router.put("/style-guide")
async def put_style_guide(body: StyleGuideIn, admin: Admin, db: DB) -> StyleGuideOut:
    row = await db.scalar(select(KnowledgeCard).where(KnowledgeCard.kind == "style_guide").with_for_update())
    if row is None:
        row = KnowledgeCard(kind="style_guide", title="Štýlová príručka", created_by_person_id=admin.id)
        db.add(row)
    row.body = body.body.strip()
    audit(
        db, "ai.style_guide_updated", person_id=admin.id, object_type="knowledge_card", details={"chars": len(row.body)}
    )
    await db.commit()
    await db.refresh(row)
    return StyleGuideOut(body=row.body, updated_at=row.updated_at)


@router.get("/knowledge")
async def list_cards(admin: Admin, db: DB) -> list[CardOut]:
    rows = await db.execute(
        select(KnowledgeCard).where(KnowledgeCard.kind == "knowledge").order_by(KnowledgeCard.title)
    )
    return [_out(c) for c in rows.scalars()]


@router.post("/knowledge")
async def create_card(body: CardIn, admin: Admin, db: DB) -> CardOut:
    card = KnowledgeCard(kind="knowledge", created_by_person_id=admin.id, **body.model_dump())
    db.add(card)
    await db.flush()
    audit(
        db,
        "ai.knowledge_created",
        person_id=admin.id,
        object_type="knowledge_card",
        object_id=str(card.id),
        details={"title": card.title},
    )
    await db.commit()
    await db.refresh(card)
    return _out(card)


@router.put("/knowledge/{card_id}")
async def update_card(card_id: uuid.UUID, body: CardIn, admin: Admin, db: DB) -> CardOut:
    card = await _card(db, card_id)
    for key, value in body.model_dump().items():
        setattr(card, key, value)
    audit(
        db,
        "ai.knowledge_updated",
        person_id=admin.id,
        object_type="knowledge_card",
        object_id=str(card.id),
        details={"title": card.title, "enabled": card.enabled},
    )
    await db.commit()
    await db.refresh(card)
    return _out(card)


@router.delete("/knowledge/{card_id}")
async def delete_card(card_id: uuid.UUID, admin: Admin, db: DB) -> dict[str, str]:
    card = await _card(db, card_id)
    audit(
        db,
        "ai.knowledge_deleted",
        person_id=admin.id,
        object_type="knowledge_card",
        object_id=str(card.id),
        details={"title": card.title},
    )
    await db.delete(card)
    await db.commit()
    return {"status": "deleted"}


# ----- 17e Pravidlá (rules in natural language) -----


class RulePreviewIn(BaseModel):
    nl_text: str = Field(min_length=3, max_length=1000)


class RulePreviewOut(BaseModel):
    structured: dict[str, object]
    description: str


class RuleIn(BaseModel):
    nl_text: str = Field(min_length=3, max_length=1000)
    structured: StructuredRule


class RuleOut(BaseModel):
    id: str
    nl_text: str
    description: str
    enabled: bool
    last_used_at: datetime | None
    created_by: str | None


class RuleToggleIn(BaseModel):
    enabled: bool


class RuleTestIn(BaseModel):
    structured: StructuredRule


class RuleTestHit(BaseModel):
    id: str
    subject: str | None
    from_email: str | None
    received_at: datetime | None


class RuleTestOut(BaseModel):
    checked: int
    matches: list[RuleTestHit]


async def _rule_out(db: DB, row: AiRule) -> RuleOut:
    author = await db.get(Person, row.created_by_person_id) if row.created_by_person_id else None
    try:
        description = describe(StructuredRule.model_validate(row.structured))
    except ValidationError:
        description = "—"
    return RuleOut(
        id=str(row.id),
        nl_text=row.nl_text,
        description=description,
        enabled=row.enabled,
        last_used_at=row.last_used_at,
        created_by=author.full_name if author else None,
    )


@router.post("/rules/preview")
async def preview_rule(body: RulePreviewIn, admin: Admin, db: DB, settings: SettingsDep) -> RulePreviewOut:
    """The model proposes the structure; the „Ak … tak …“ text is generated by code. Nothing is saved here."""
    model = (settings.llm_model_classify or "").strip()
    if not _ai_provider_configured(settings) or not model:
        raise fail(409, "ai_unavailable")
    if not budget_allows_call(
        spent_usd=await daily_spend_usd(db),
        estimate_usd=estimate_purpose_cost_usd(model, "classify"),
        budget_usd=(await load_ai_limits(db, settings)).budget_usd,
    ):
        raise fail(429, "ai_budget_exceeded")
    result = await parse_rule(get_llm_provider(settings), model, body.nl_text.strip())
    db.add(
        AiRun(
            purpose="classify",
            provider="anthropic",
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=result.cost_usd,
            latency_ms=result.latency_ms,
            status=result.status,
            error_class=result.error_class,
        )
    )
    await db.commit()
    if result.rule is None:
        raise fail(422, "rule_not_understood")
    return RulePreviewOut(structured=result.rule.model_dump(), description=describe(result.rule))


@router.get("/rules")
async def list_rules(admin: Admin, db: DB) -> list[RuleOut]:
    rows = await db.execute(select(AiRule).order_by(AiRule.created_at))
    return [await _rule_out(db, r) for r in rows.scalars()]


@router.post("/rules")
async def create_rule(body: RuleIn, admin: Admin, db: DB) -> RuleOut:
    """Saved only after the person confirmed the description of exactly this structure (UI: preview → Uložiť)."""
    row = AiRule(nl_text=body.nl_text.strip(), structured=body.structured.model_dump(), created_by_person_id=admin.id)
    db.add(row)
    await db.flush()
    audit(
        db,
        "ai.rule_created",
        person_id=admin.id,
        object_type="ai_rule",
        object_id=str(row.id),
        details={"description": describe(body.structured)},
    )
    await db.commit()
    await db.refresh(row)
    return await _rule_out(db, row)


async def _rule(db: DB, rule_id: uuid.UUID) -> AiRule:
    row = await db.get(AiRule, rule_id)
    if row is None:
        raise fail(404, "rule_not_found")
    return row


@router.patch("/rules/{rule_id}")
async def toggle_rule(rule_id: uuid.UUID, body: RuleToggleIn, admin: Admin, db: DB) -> RuleOut:
    row = await _rule(db, rule_id)
    row.enabled = body.enabled
    audit(
        db,
        "ai.rule_updated",
        person_id=admin.id,
        object_type="ai_rule",
        object_id=str(row.id),
        details={"enabled": body.enabled},
    )
    await db.commit()
    await db.refresh(row)
    return await _rule_out(db, row)


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: uuid.UUID, admin: Admin, db: DB) -> dict[str, str]:
    row = await _rule(db, rule_id)
    audit(db, "ai.rule_deleted", person_id=admin.id, object_type="ai_rule", object_id=str(row.id), details={})
    await db.delete(row)
    await db.commit()
    return {"status": "deleted"}


@router.post("/rules/test")
async def test_rule(body: RuleTestIn, admin: Admin, ctx: Auth, db: DB) -> RuleTestOut:
    """„Vyskúšať na posledných 50 e-mailoch“ of the mailboxes this login can open — nothing is changed."""
    ids = [m.id for m in await accessible_mailboxes(db, ctx.account.id)]
    if not ids:
        return RuleTestOut(checked=0, matches=[])
    messages = list(
        (
            await db.execute(
                select(Message)
                .where(Message.mailbox_id.in_(ids))
                .order_by(Message.received_at.desc().nulls_last())
                .limit(50)
            )
        ).scalars()
    )
    names: dict[uuid.UUID, list[str]] = {}
    for att in (
        await db.execute(select(Attachment).where(Attachment.message_id.in_([m.id for m in messages])))
    ).scalars():
        names.setdefault(att.message_id, []).append(att.filename)
    hits = [
        RuleTestHit(id=str(m.id), subject=m.subject, from_email=m.from_email, received_at=m.received_at)
        for m in messages
        if rule_matches(
            body.structured,
            MailFacts(
                from_email=m.from_email or "",
                subject=m.subject or "",
                body=m.body_text or m.preview or "",
                attachment_names=tuple(names.get(m.id, [])),
            ),
        )
    ]
    return RuleTestOut(checked=len(messages), matches=hits)


# ----- 07 Personal style profile (each person, opt-in) -----


class StyleProfileOut(BaseModel):
    opt_in: bool
    text: str
    generated_at: str | None
    source_count: int


class StyleProfileIn(BaseModel):
    opt_in: bool
    text: str = Field(default="", max_length=PROFILE_CHARS)


@router.get("/style-profile")
async def get_style_profile(person: ActivePerson, db: DB) -> StyleProfileOut:
    return StyleProfileOut(**await load_profile(db, person.id))


@router.put("/style-profile")
async def put_style_profile(body: StyleProfileIn, person: ActivePerson, db: DB) -> StyleProfileOut:
    """Edit or switch off. Switching off deletes the profile text (opt-in, AI_ASSISTANT §10)."""
    current = await load_profile(db, person.id)
    data = {
        **current,
        "opt_in": body.opt_in,
        "text": body.text.strip() if body.opt_in else "",
    }
    if not body.opt_in:
        data.update(generated_at=None, source_count=0)
    await save_profile(db, person.id, data)
    audit(
        db,
        "ai.style_profile_updated",
        person_id=person.id,
        object_type="person",
        object_id=str(person.id),
        details={"opt_in": body.opt_in},
    )
    await db.commit()
    return StyleProfileOut(**await load_profile(db, person.id))


@router.post("/style-profile/generate")
async def generate_style_profile(person: ActivePerson, db: DB, settings: SettingsDep) -> StyleProfileOut:
    """Build the profile from the person's own last 200 sent e-mails — only after opt-in."""
    current = await load_profile(db, person.id)
    if not current["opt_in"]:
        raise fail(409, "opt_in_required")
    model = (settings.llm_model_draft or "").strip()
    if not _ai_provider_configured(settings) or not model:
        raise fail(409, "ai_unavailable")
    samples = await sent_samples(db, person.id)
    if len(samples) < MIN_MAILS:
        raise fail(422, "not_enough_mail", count=len(samples))
    if not budget_allows_call(
        spent_usd=await daily_spend_usd(db),
        estimate_usd=estimate_purpose_cost_usd(model, "draft"),
        budget_usd=(await load_ai_limits(db, settings)).budget_usd,
    ):
        raise fail(429, "ai_budget_exceeded")
    result = await generate_profile(get_llm_provider(settings), model, samples)
    db.add(
        AiRun(
            purpose="draft",
            provider="anthropic",
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=result.cost_usd,
            latency_ms=result.latency_ms,
            status=result.status,
            error_class=result.error_class,
        )
    )
    if result.text is None:
        await db.commit()
        raise fail(502, "ai_failed")
    await save_profile(
        db,
        person.id,
        {
            "opt_in": True,
            "text": result.text,
            "generated_at": datetime.now(UTC).isoformat(),
            "source_count": len(samples),
        },
    )
    audit(
        db,
        "ai.style_profile_generated",
        person_id=person.id,
        object_type="person",
        object_id=str(person.id),
        details={"source_count": len(samples)},
    )
    await db.commit()
    return StyleProfileOut(**await load_profile(db, person.id))


# ----- 17f Tieňový režim, spotreba a presnosť (admin) -----

USAGE_DAYS = 30


class DayCost(BaseModel):
    date: str
    cost_usd: str  # Decimal as string
    runs: int


class SuggestionStats(BaseModel):
    total: int
    shadow: int
    pending: int
    approved: int
    approved_unedited: int
    rejected: int
    approved_unedited_pct: int | None


class EvalConfusion(BaseModel):
    label: str
    predicted: str
    count: int


class EvalSummary(BaseModel):
    run_at: str
    mode: str  # stored | live
    total: int
    accuracy: str | None
    language_accuracy: str | None
    gate: str
    passed: bool
    too_small: bool
    confusion: list[EvalConfusion]


class UsageOut(BaseModel):
    days: list[DayCost]
    total_cost_usd: str
    budget_usd: str
    cost_by_purpose: dict[str, str]
    suggestions: SuggestionStats
    reject_reasons: dict[str, int]
    categories: dict[str, int]
    eval: EvalSummary | None = None  # the last `make eval --save` on the server (aggregates only)
    corrected_30d: int = 0  # #143: „Zmeniť kategóriu“ by people in the last 30 days (an info line only)


class ShadowOut(BaseModel):
    replies: bool  # True = reply suggestions are created but hidden (shadow week)


class ShadowIn(BaseModel):
    replies: bool


async def usage_stats(db: DB, settings: Settings, *, days: int = USAGE_DAYS) -> UsageOut:
    since = datetime.now(UTC) - timedelta(days=days)
    day = func.date_trunc("day", AiRun.created_at)
    rows = await db.execute(
        select(day, func.coalesce(func.sum(AiRun.cost_usd), 0), func.count())
        .where(AiRun.created_at >= since)
        .group_by(day)
        .order_by(day)
    )
    per_day = [DayCost(date=d.date().isoformat(), cost_usd=f"{Decimal(c):.4f}", runs=n) for d, c, n in rows.all()]
    by_purpose = {
        str(p): f"{Decimal(c):.4f}"
        for p, c in (
            await db.execute(
                select(AiRun.purpose, func.coalesce(func.sum(AiRun.cost_usd), 0))
                .where(AiRun.created_at >= since)
                .group_by(AiRun.purpose)
            )
        ).all()
    }
    total = sum((Decimal(d.cost_usd) for d in per_day), Decimal("0"))

    suggestions = list(
        (
            await db.execute(
                select(AiSuggestion).where(AiSuggestion.created_at >= since, AiSuggestion.suggestion_type == "reply")
            )
        ).scalars()
    )
    approved = [s for s in suggestions if s.status == "approved"]
    unedited = [s for s in approved if not (s.diff or {}).get("edited")]
    rejected = [s for s in suggestions if s.status == "rejected"]
    reasons: dict[str, int] = {}
    for s in rejected:
        for r in (s.final_payload or {}).get("reject_reasons") or []:
            reasons[str(r)] = reasons.get(str(r), 0) + 1
    decided = len(approved) + len(rejected)
    categories = {
        str(c): int(n)
        for c, n in (
            await db.execute(
                select(Classification.category, func.count())
                .where(Classification.created_at >= since, Classification.status == "done")
                .group_by(Classification.category)
            )
        ).all()
        if c
    }
    return UsageOut(
        days=per_day,
        total_cost_usd=f"{total:.4f}",
        budget_usd=f"{(await load_ai_limits(db, settings)).budget_usd:.2f}",
        cost_by_purpose=by_purpose,
        suggestions=SuggestionStats(
            total=len(suggestions),
            shadow=sum(1 for s in suggestions if s.shadow),
            pending=sum(1 for s in suggestions if s.status == "pending"),
            approved=len(approved),
            approved_unedited=len(unedited),
            rejected=len(rejected),
            approved_unedited_pct=round(100 * len(unedited) / decided) if decided else None,
        ),
        reject_reasons=dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        categories=dict(sorted(categories.items(), key=lambda kv: -kv[1])),
        eval=await _eval_summary(db),
        corrected_30d=int(
            await db.scalar(
                select(func.count())
                .select_from(Classification)
                .where(Classification.payload["corrected_at"].astext >= since.isoformat())
            )
            or 0
        ),
    )


async def _eval_summary(db: AsyncSession) -> EvalSummary | None:
    row = await db.scalar(select(OrgSettings).where(OrgSettings.section == SECTION_EVAL))
    if row is None:
        return None
    try:
        return EvalSummary.model_validate({**row.data, "confusion": row.data.get("confusion", [])[:30]})
    except ValidationError:
        return None


@router.get("/usage")
async def get_usage(admin: Admin, db: DB, settings: SettingsDep) -> UsageOut:
    """Read-only 17f numbers for the last 30 days (no mail text)."""
    return await usage_stats(db, settings)


@router.get("/usage.csv")
async def get_usage_csv(admin: Admin, db: DB, settings: SettingsDep) -> Response:
    usage = await usage_stats(db, settings)
    lines = ["datum;naklady_usd;volania"] + [f"{d.date};{d.cost_usd};{d.runs}" for d in usage.days]
    return Response(
        "\n".join(lines) + "\n",
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="ai-spotreba.csv"'},
    )


@router.get("/shadow")
async def get_shadow(admin: Admin, db: DB) -> ShadowOut:
    return ShadowOut(replies=await shadow_mode_enabled(db))


@router.put("/shadow")
async def put_shadow(body: ShadowIn, ctx: RecentReauth, db: DB) -> ShadowOut:
    """Turning shadow off makes new reply suggestions visible to everybody (Erik decides on the server — #116) —
    a ⚠ change, so it needs a recent re-auth (#54)."""
    admin = ctx.person
    assert admin is not None  # require_recent_reauth answers 403 without an active admin person
    row = await ensure_shadow_flag(db)
    before = row.enabled
    row.enabled = body.replies
    audit(
        db,
        "ai.shadow_mode_changed",
        person_id=admin.id,
        object_type="feature_flag",
        object_id=str(row.id),
        details={"feature": "replies", "before": before, "after": body.replies},
    )
    await db.commit()
    return ShadowOut(replies=await shadow_mode_enabled(db))


# --- 17a Poskytovateľ a rozpočet (#116) ---


class ModelOut(BaseModel):
    purpose: str
    model: str | None


class LimitsOut(BaseModel):
    provider: str  # read-only: LLM_PROVIDER on the server
    region: str | None
    models: list[ModelOut]
    daily_budget_usd: str
    budget_source: str  # env = „z nastavenia servera“, app = „nastavené v aplikácii“
    env_budget_usd: str
    alert_pct: int
    on_exhausted: str
    retention_days: int


class LimitsIn(BaseModel):
    # None = back to the server value (AI_DAILY_BUDGET_USD); a decimal string within 1–500 otherwise
    daily_budget_usd: str | None = Field(default=None, max_length=12)
    alert_pct: int = Field(default=ALERT_DEFAULT, ge=1, le=100)
    on_exhausted: Literal["rules_only", "ai_off"] = "rules_only"
    retention_days: Literal[30, 90, 365] = 90  # RETENTION_DEFAULT

    @field_validator("daily_budget_usd")
    @classmethod
    def _budget(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        parsed = parse_budget(value.replace(",", "."))
        if parsed is None:
            raise ValueError("budget_out_of_range")
        return str(parsed)


def _limits_out(limits: AiLimits, settings: Settings) -> LimitsOut:
    return LimitsOut(
        provider=settings.llm_provider,
        region=settings.aws_region if settings.llm_provider == "bedrock" else None,
        models=[
            ModelOut(purpose=purpose, model=(getattr(settings, f"llm_model_{purpose}") or "").strip() or None)
            for purpose in ("classify", "draft", "extract", "assistant", "embed")
        ],
        daily_budget_usd=f"{limits.budget_usd:.2f}",
        budget_source=limits.budget_source,
        env_budget_usd=f"{Decimal(str(settings.ai_daily_budget_usd)):.2f}",
        alert_pct=limits.alert_pct,
        on_exhausted=limits.on_exhausted,
        retention_days=limits.retention_days,
    )


@router.get("/limits")
async def get_limits(admin: Admin, db: DB, settings: SettingsDep) -> LimitsOut:
    return _limits_out(await load_ai_limits(db, settings), settings)


@router.put("/limits")
async def put_limits(body: LimitsIn, ctx: RecentReauth, db: DB, settings: SettingsDep) -> LimitsOut:
    """⚠ company-wide AI change: re-auth (#54) and audit before/after (#116)."""
    before = await load_ai_limits(db, settings)
    data: dict[str, object] = {
        "alert_pct": body.alert_pct,
        "on_exhausted": body.on_exhausted,
        "retention_days": body.retention_days,
    }
    if body.daily_budget_usd is not None:
        data["daily_budget_usd"] = body.daily_budget_usd  # decimal as a string, never a float
    await save_org_section(db, SECTION_LIMITS, data)
    after = limits_from(data, settings)
    audit(
        db,
        "ai.limits_changed",
        person_id=ctx.person.id if ctx.person else None,
        object_type="org_settings",
        object_id=SECTION_LIMITS,
        details={
            "before": _limits_audit(before),
            "after": _limits_audit(after),
        },
    )
    await db.commit()
    return _limits_out(after, settings)


def _limits_audit(limits: AiLimits) -> dict[str, object]:
    return {
        "daily_budget_usd": f"{limits.budget_usd:.2f}",
        "budget_source": limits.budget_source,
        "alert_pct": limits.alert_pct,
        "on_exhausted": limits.on_exhausted,
        "retention_days": limits.retention_days,
    }


# --- 17c Kategórie (#116) ---


class CategoryRowOut(BaseModel):
    id: str
    label: str
    description: str
    default_description: str | None  # built-ins: the text from code, to restore
    color: str
    enabled: bool
    builtin: bool
    locked: bool  # „Iné“ is the fallback and stays on
    count_30d: int


class CategoryRowIn(BaseModel):
    id: str | None = Field(default=None, max_length=64)  # None = a new custom category
    label: str | None = Field(default=None, max_length=MAX_LABEL)
    description: str = Field(default="", max_length=MAX_DESCRIPTION)
    color: Literal["warning", "success", "danger", "info", "brand", "neutral"] = "neutral"
    enabled: bool = True


class CategoriesIn(BaseModel):
    categories: list[CategoryRowIn] = Field(max_length=len(CATEGORIES) + MAX_CUSTOM)


async def _category_rows(db: AsyncSession, data: dict[str, Any] | None) -> list[CategoryRowOut]:
    since = datetime.now(UTC) - timedelta(days=30)
    counts = dict(
        (
            await db.execute(
                select(Classification.category, func.count())
                .where(Classification.created_at >= since, Classification.status == "done")
                .group_by(Classification.category)
            )
        ).all()
    )
    return [
        CategoryRowOut(
            id=c.id,
            label=c.label_sk,
            description=c.description_sk,
            default_description=CATEGORY_BY_ID[c.id].description_sk if builtin else None,
            color=c.color_token,
            enabled=enabled,
            builtin=builtin,
            locked=c.id == FALLBACK_ID,
            count_30d=int(counts.get(c.id, 0)),
        )
        for c, enabled, builtin in all_categories(data)
    ]


@router.get("/categories")
async def get_categories(admin: Admin, db: DB) -> list[CategoryRowOut]:
    return await _category_rows(db, await load_category_data(db))


@router.put("/categories")
async def put_categories(body: CategoriesIn, ctx: RecentReauth, db: DB) -> list[CategoryRowOut]:
    """⚠ changes what the AI classifies into: re-auth + audit before/after. Built-ins: description and on/off;
    custom (max 15): name, description, colour, on/off. Stored classifications are never touched."""
    before_data = await load_category_data(db)
    builtin: dict[str, dict[str, Any]] = {}
    custom: list[dict[str, Any]] = []
    used: set[str] = set(CATEGORY_IDS)
    for row in body.categories:
        if row.id in CATEGORY_IDS:
            default = CATEGORY_BY_ID[row.id].description_sk
            entry: dict[str, Any] = {"enabled": row.enabled or row.id == FALLBACK_ID}
            if row.description.strip() and row.description.strip() != default:
                entry["description"] = row.description.strip()
            builtin[row.id] = entry
            continue
        label = (row.label or "").strip()
        if not label:
            raise fail(422, "category_label_required")
        cid = row.id
        if cid is None:
            cid = base = custom_id(label)
            n = 2
            while cid in used:
                cid, n = f"{base[:37]}_{n}", n + 1
        elif not CUSTOM_ID.match(cid):
            raise fail(422, "category_unknown")
        if cid in used:
            raise fail(422, "category_duplicate")
        used.add(cid)
        description = row.description.strip()
        custom.append(
            {"id": cid, "label": label, "description": description, "color": row.color, "enabled": row.enabled},
        )
    if len(custom) > MAX_CUSTOM:
        raise fail(422, "too_many_categories")
    # removed custom categories stay known (hidden) so stored classifications keep their view (#126 review)
    kept = {c["id"] for c in custom}
    previous = [c for c, _, b in all_categories(before_data) if not b] + deleted_categories(before_data)
    deleted = [{"id": c.id, "label": c.label_sk, "color": c.color_token} for c in previous if c.id not in kept][
        :MAX_DELETED
    ]
    data: dict[str, Any] = {"builtin": builtin, "custom": custom, "deleted": deleted}
    await save_org_section(db, SECTION_CATEGORIES, data)

    def _snapshot(d: dict[str, Any] | None) -> dict[str, Any]:
        return {c.id: {"enabled": on, "description": c.description_sk} for c, on, _ in all_categories(d)}

    before, after = _snapshot(before_data), _snapshot(data)
    changed = {k: {"before": before.get(k), "after": v} for k, v in after.items() if before.get(k) != v}
    removed = {k: {"before": v, "after": None} for k, v in before.items() if k not in after}
    audit(
        db,
        "ai.categories_changed",
        person_id=ctx.person.id if ctx.person else None,
        object_type="org_settings",
        object_id=SECTION_CATEGORIES,
        details={"changed": {**changed, **removed}},
    )
    await db.commit()
    return await _category_rows(db, data)


# --- 17f: eval label file download / upload (Erik's answer B on #129) ---


class EvalSampleOut(BaseModel):
    filename: str
    csv: str  # UTF-8 with BOM, `;` — the browser saves it; the app keeps nothing
    rows: int


class EvalUploadIn(BaseModel):
    csv: str = Field(max_length=MAX_UPLOAD_BYTES + 1000)  # chars ≥ bytes/4; the byte limit is checked in the parser


@router.post("/eval/sample")
async def download_eval_sample(ctx: RecentReauth, db: DB) -> EvalSampleOut:
    """⚠ the file holds subjects and sender domains of real mail: admin + re-auth, audited; nothing stored."""
    rows = await sample_rows(db, SAMPLE_DEFAULT)
    text = sample_csv(rows, prompt_categories(await load_category_data(db)))
    audit(
        db,
        "ai.eval_sample_downloaded",
        person_id=ctx.person.id if ctx.person else None,
        object_type="org_settings",
        object_id=SECTION_EVAL,
        details={"rows": len(rows)},
    )
    await db.commit()
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    return EvalSampleOut(filename=f"smartmail-oznacenie-{stamp}.csv", csv=text, rows=len(rows))


@router.post("/eval/upload")
async def upload_eval_labels(body: EvalUploadIn, ctx: RecentReauth, db: DB, settings: SettingsDep) -> EvalSummary:
    """Score the labeled file against the stored classifications; only aggregates are kept (`ai.eval_last`)."""
    try:
        labels = parse_labels(body.csv, category_lookup(await load_category_data(db)))
    except LabelError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "line": exc.line, "value": exc.value}) from exc
    report, _ = await score(db, settings, labels, save=True)
    audit(
        db,
        "ai.eval_uploaded",
        person_id=ctx.person.id if ctx.person else None,
        object_type="org_settings",
        object_id=SECTION_EVAL,
        details={"labeled": report.total, "accuracy": report.to_summary()["accuracy"], "passed": report.passes()},
    )
    await db.commit()
    summary = await _eval_summary(db)
    assert summary is not None  # just saved
    return summary
