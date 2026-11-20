"""#233 main cards and variants in Money (MONEY_API §5.5.8a): `Article.NadrazenyArtikl_ID` = the main card of a
variant; the variant catalog = main catalog + size suffix. Goods are never received on a main card that has variants
(DL-B11). Read only."""

from __future__ import annotations

import uuid
from typing import Literal

from app.money.bridge_client import BridgeClient
from app.money.schemas import Article

Kind = Literal["article", "main", "variant"]
BATCH = 10  # the bridge takes at most 10 main cards per call


def kind_of(article: Article, variants: dict[uuid.UUID, list[Article]]) -> Kind:
    if article.parent_id is not None:
        return "variant"
    return "main" if variants.get(article.id) else "article"


def by_catalog(items: list[Article]) -> list[Article]:
    return sorted(items, key=lambda a: (a.catalog or a.code or "", a.name))


async def variants_of(
    bridge: BridgeClient, ids: list[uuid.UUID], *, limit: int | None = None
) -> dict[uuid.UUID, list[Article]]:
    """Variants of the given (non-variant) articles, in batches of 10; `limit` caps how many ids are asked."""
    unique = list(dict.fromkeys(ids))[:limit] if limit else list(dict.fromkeys(ids))
    out: dict[uuid.UUID, list[Article]] = {}
    for i in range(0, len(unique), BATCH):
        out.update(await bridge.article_variants(unique[i : i + BATCH]))
    return {k: by_catalog(v) for k, v in out.items() if v}


async def has_variants(bridge: BridgeClient, article: Article) -> bool:
    """A main card with variants (a variant itself never has variants)."""
    if article.parent_id is not None:
        return False
    return bool((await bridge.article_variants([article.id])).get(article.id))


def picker_order(
    found: list[Article], variants: dict[uuid.UUID, list[Article]], limit: int
) -> list[tuple[Article, Kind]]:
    """Results in their order, every main card followed by its variants (by catalog, no duplicates). At most `limit`
    rows — except the variants of the first main card, which are never cut."""
    ordered: list[tuple[Article, Kind]] = []
    seen: set[uuid.UUID] = set()
    listed_mains = {a.id for a in found if variants.get(a.id)}
    first_main = next((a.id for a in found if variants.get(a.id)), None)
    keep_all = {v.id for v in variants.get(first_main, [])} if first_main else set()

    def push(a: Article, kind: Kind) -> None:
        if a.id in seen:
            return
        if len(ordered) >= limit and a.id not in keep_all:
            return
        seen.add(a.id)
        ordered.append((a, kind))

    for a in found:
        if a.parent_id is not None and a.parent_id in listed_mains:
            continue  # shown right under its main card
        push(a, kind_of(a, variants))
        for v in variants.get(a.id, []):
            push(v, "variant")
    return ordered
