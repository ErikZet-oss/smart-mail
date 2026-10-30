"""Settings 17d Štýl a znalosti (G, admin): the company style guide and the knowledge cards (Phase 2e, #110).

The audit records which card changed, never its text (#110)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.ai.models import KnowledgeCard
from app.api.mail import fail
from app.api.settings import require_admin
from app.auth.deps import DB
from app.auth.models import Person
from app.core.audit import audit

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
