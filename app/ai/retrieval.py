"""Knowledge retrieval for drafts (AI_ASSISTANT §6, §10) — ADR-015: PostgreSQL full-text now, embeddings later.

Everything that looks up company knowledge goes through `Retriever`, so a Voyage or local-embedding implementation
can replace `FullTextRetriever` in this one module once the eval shows drafts miss knowledge (#110).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import KnowledgeCard

MAX_CARDS = 3
MAX_QUERY_WORDS = 30
_WORD = re.compile(r"[^\W\d_]{4,}", re.UNICODE)  # letters only: nothing reaches to_tsquery as syntax
CARD_CHARS = 1500


class Retriever(Protocol):
    async def knowledge(self, db: AsyncSession, text: str, *, limit: int = MAX_CARDS) -> list[KnowledgeCard]: ...


def query_words(text: str) -> list[str]:
    """Distinct words (≥ 4 letters) of the mail, lower-case, in order — an OR query of plain words."""
    seen: list[str] = []
    for word in _WORD.findall((text or "")[:4000].lower()):
        if word not in seen:
            seen.append(word)
        if len(seen) >= MAX_QUERY_WORDS:
            break
    return seen


class FullTextRetriever:
    """Cards whose title / tags / body share words with the mail (simple + unaccent, like message search)."""

    async def knowledge(self, db: AsyncSession, text: str, *, limit: int = MAX_CARDS) -> list[KnowledgeCard]:
        words = query_words(text)
        if not words:
            return []
        query = func.to_tsquery("simple", func.unaccent(" | ".join(words)))
        rank = func.ts_rank(KnowledgeCard.search_vector, query)
        rows = await db.execute(
            select(KnowledgeCard)
            .where(
                KnowledgeCard.kind == "knowledge",
                KnowledgeCard.enabled.is_(True),
                or_(KnowledgeCard.valid_until.is_(None), KnowledgeCard.valid_until >= date.today()),
                KnowledgeCard.search_vector.op("@@")(query),
            )
            .order_by(rank.desc(), KnowledgeCard.title)
            .limit(limit)
        )
        return list(rows.scalars())


def default_retriever() -> Retriever:
    return FullTextRetriever()


async def style_guide_text(db: AsyncSession) -> str | None:
    row = await db.scalar(
        select(KnowledgeCard).where(KnowledgeCard.kind == "style_guide", KnowledgeCard.enabled.is_(True))
    )
    text = (row.body if row else "").strip()
    return text or None


def knowledge_block(cards: list[KnowledgeCard]) -> str:
    """Company data for the prompt — wrapped as data of Smart s.r.o., never as instructions from a mail (#110)."""
    if not cards:
        return "(no matching company knowledge)"
    parts = [
        f'<company_knowledge title="{c.title.replace(chr(34), "")}">\n{c.body[:CARD_CHARS]}\n</company_knowledge>'
        for c in cards
    ]
    return "\n".join(parts)
