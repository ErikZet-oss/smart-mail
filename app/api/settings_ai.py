"""Settings 17d Štýl a znalosti and 17e Pravidlá (G, admin): style guide, knowledge cards, NL rules (Phase 2e, #110).

The audit records which card changed, never its text (#110)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import func, select

from app.ai.budget import budget_allows_call
from app.ai.models import AiRule, AiRun, AiSuggestion, Classification, KnowledgeCard
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
        budget_usd=Decimal(str(settings.ai_daily_budget_usd)),
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
        budget_usd=Decimal(str(settings.ai_daily_budget_usd)),
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


class UsageOut(BaseModel):
    days: list[DayCost]
    total_cost_usd: str
    budget_usd: str
    cost_by_purpose: dict[str, str]
    suggestions: SuggestionStats
    reject_reasons: dict[str, int]
    categories: dict[str, int]


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
        budget_usd=f"{Decimal(str(settings.ai_daily_budget_usd)):.2f}",
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
    )


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
