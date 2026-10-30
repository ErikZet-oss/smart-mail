"""Settings 17d Štýl a znalosti and 17e Pravidlá (G, admin): style guide, knowledge cards, NL rules (Phase 2e, #110).

The audit records which card changed, never its text (#110)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select

from app.ai.budget import budget_allows_call
from app.ai.models import AiRule, AiRun, KnowledgeCard
from app.ai.pricing import estimate_purpose_cost_usd
from app.ai.provider import get_llm_provider
from app.ai.rule_parse import parse_rule
from app.ai.service import daily_spend_usd
from app.ai.style_profile import MIN_MAILS, PROFILE_CHARS, load_profile, save_profile, sent_samples
from app.ai.style_profile import generate as generate_profile
from app.ai.user_rules import MailFacts, StructuredRule, describe, rule_matches
from app.api.mail import _ai_provider_configured, fail
from app.api.settings import require_admin
from app.auth.deps import DB, ActivePerson, Auth, SettingsDep
from app.auth.models import Person
from app.core.audit import audit
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
