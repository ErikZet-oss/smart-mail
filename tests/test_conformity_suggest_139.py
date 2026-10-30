"""#139 part C: an atest 2.1 request gets a prefilled `conformity_declaration` suggestion — the AI never issues."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.conformity_suggest import SUGGESTION_TYPE, asks_for_conformity, suggest_conformity
from app.ai.models import AiRun, AiSuggestion
from app.ai.provider import LLMResponse
from app.api.ai_mail import suggestion_out
from app.core.config import Settings
from app.documents.models import ConformityDeclaration
from tests.test_ai_classify_review_2b import ScriptedAnthropic
from tests.test_ai_reply_2c import MODEL, _seed

REQUEST = (
    "Dobrý deň, k faktúre FV2026/0815 prosím o atest 2.1 (prehlásenie o zhode) na skrutky DIN 933 M8x40.\n"
    "S pozdravom Ján Novák, ABC Stav s.r.o., Hlavná 1, 949 01 Nitra"
)


def _extract(**tool: Any) -> LLMResponse:
    tool_input: dict[str, Any] = {
        "customer": "ABC Stav s.r.o., Hlavná 1, 949 01 Nitra",
        "document_ref": "FV2026/0815",
        "items": [{"nazov": "Skrutka M8x40", "kod": "", "norma": "DIN 933", "poznamka": ""}, {"nazov": ""}],
        "confidence": 0.8,
        "rationale_sk": "Zákazník žiada atest 2.1 k faktúre.",
    }
    tool_input.update(tool)
    return LLMResponse(
        text="",
        model=MODEL,
        input_tokens=800,
        output_tokens=90,
        cost_usd=Decimal("0.004"),
        latency_ms=120,
        provider="anthropic",
        tool_input=tool_input,
    )


def _settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"llm_model_extract": MODEL})


async def _run(db: AsyncSession, mailbox: Any, settings: Settings, llm: ScriptedAnthropic) -> dict[str, int]:
    model = _settings(settings)
    return await suggest_conformity(db, mailbox, model, spent_usd=Decimal("0"), shadow=False, provider=llm)


@pytest.mark.parametrize(
    ("text", "hit"),
    [
        ("Prosím o atest 2.1", True),
        ("prosim ATEST 2,1 k dodavke", True),
        ("Pošlite prehlásenie o zhode", True),
        ("Potřebujeme prohlášení o shodě", True),
        ("Please send the declaration of conformity", True),
        ("Bitte Werkszeugnis 2.1 und Konformitätserklärung", True),
        ("Pošlite certifikát zhody", True),
        ("Pošlite certifikát ISO 9001", False),  # another document
        ("Prosím o cenovú ponuku", False),
    ],
)
def test_139c_request_detection(text: str, hit: bool) -> None:
    assert asks_for_conformity("", text) is hit


async def test_139c_suggestion_prefills_the_form_and_issues_nothing(db: AsyncSession, settings: Settings) -> None:
    mailbox, message = await _seed(db, category="document_request", body=REQUEST)
    llm = ScriptedAnthropic([_extract()])
    stats = await suggest_conformity(
        db, mailbox, _settings(settings), spent_usd=Decimal("0"), shadow=False, provider=llm
    )
    assert stats["created"] == 1 and len(llm.calls) == 1
    assert "<untrusted_email>" in llm.calls[0].user and llm.calls[0].purpose == "extract"
    row = await db.scalar(select(AiSuggestion).where(AiSuggestion.suggestion_type == SUGGESTION_TYPE))
    assert row is not None and row.message_id == message.id and row.status == "pending"
    assert row.payload["document_ref"] == "FV2026/0815"
    assert row.payload["items"] == [{"nazov": "Skrutka M8x40", "kod": "", "norma": "DIN 933", "poznamka": ""}]
    assert row.checks == []  # every number is in the e-mail
    out = suggestion_out(row)
    assert out.type == SUGGESTION_TYPE and out.conformity is not None and out.conformity["customer"].startswith("ABC")
    assert await db.scalar(select(ConformityDeclaration)) is None  # nothing issued
    run = await db.scalar(select(AiRun).where(AiRun.purpose == "extract"))
    assert run is not None and run.cost_usd == Decimal("0.004")
    # idempotent: a second run makes no second card
    again = await suggest_conformity(
        db, mailbox, _settings(settings), spent_usd=Decimal("0"), shadow=False, provider=llm
    )
    assert again["candidates"] == 0


async def test_139c_made_up_document_number_is_flagged(db: AsyncSession, settings: Settings) -> None:
    mailbox, _ = await _seed(db, category="document_request", body=REQUEST)
    llm = ScriptedAnthropic([_extract(document_ref="FV2026/9999")])
    await suggest_conformity(db, mailbox, _settings(settings), spent_usd=Decimal("0"), shadow=True, provider=llm)
    row = await db.scalar(select(AiSuggestion).where(AiSuggestion.suggestion_type == SUGGESTION_TYPE))
    assert row is not None and row.shadow is True
    assert row.checks[0]["id"] == "unverified_number" and row.checks[0]["level"] == "warning"


@pytest.mark.parametrize(
    ("seed", "why"),
    [
        ({"category": "inquiry", "body": REQUEST}, "other category"),
        ({"category": "document_request", "body": "Pošlite prosím technický list."}, "no atest request"),
    ],
)
async def test_139c_no_card_when_not_asked(
    db: AsyncSession, settings: Settings, seed: dict[str, Any], why: str
) -> None:
    mailbox, _ = await _seed(db, **seed)
    llm = ScriptedAnthropic([_extract()])
    await suggest_conformity(db, mailbox, _settings(settings), spent_usd=Decimal("0"), shadow=False, provider=llm)
    assert llm.calls == [], why


async def test_139c_budget_spent_means_no_call(db: AsyncSession, settings: Settings) -> None:
    mailbox, _ = await _seed(db, category="document_request", body=REQUEST)
    llm = ScriptedAnthropic([_extract()])
    stats = await suggest_conformity(
        db,
        mailbox,
        _settings(settings).model_copy(update={"ai_daily_budget_usd": 5.0}),
        spent_usd=Decimal("5"),
        shadow=False,
        provider=llm,
    )
    assert stats["skipped_budget"] == 1 and llm.calls == []
