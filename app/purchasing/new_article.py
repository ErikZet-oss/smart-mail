"""D32 (#239) — create a Money article / variant from a W6h line (MONEY_API 5.5.8b).

Only after the user's click (autonomy ≤ 2), roles warehouse / accounting / admin, Settings 14 switch
`create_article`. Per-line state lives in `DocumentLine.raw["_new_article"]` (no migration):

    {"status": "in_progress" | "partial" | "done" | "failed",
     "started_at": iso, "smids": {katalog: smid}, "main": card | None, "variant": card | None,
     "request": {mode, catalogs}, "error": code | None}

- SMID per card, stored on the line *before* the bridge is called; a retry of the same catalog reuses it, so the bridge
  answers with the card it already created instead of a second one (never an automatic retry of the mutation).
- `main_and_variant`: main first (persisted right away), then the variant; a failed variant leaves `partial` and the
  next call creates only the variant.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.money.schemas import Article, ArticleCreated

STATE = "_new_article"
IN_PROGRESS_TTL = timedelta(minutes=2)  # bridge timeout × 2 — an older `in_progress` is a crashed attempt
CATALOG_PATTERN = r"^[^~#|()]{1,50}$"  # used in a Money filter, never a filter character (same as the bridge)
PROPOSAL_TRIES = 20
NIL = uuid.UUID(int=0)

Mode = Literal["main", "variant", "main_and_variant"]


class CardIn(BaseModel):
    katalog: str = Field(min_length=1, max_length=50, pattern=CATALOG_PATTERN)
    nazev: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _strip(self) -> CardIn:
        self.katalog, self.nazev = self.katalog.strip(), self.nazev.strip()
        if not self.katalog or not self.nazev:
            raise ValueError("empty")
        return self


class NewArticleIn(BaseModel):
    mode: Mode
    main: CardIn | None = None
    parent_id: uuid.UUID | None = None
    variant: CardIn | None = None
    version: int

    @model_validator(mode="after")
    def _shape(self) -> NewArticleIn:
        if self.mode == "main" and self.main is None:
            raise ValueError("main_required")
        if self.mode == "variant" and (self.parent_id is None or self.variant is None):
            raise ValueError("parent_and_variant_required")
        if self.mode == "main_and_variant":
            if self.main is None or self.variant is None:
                raise ValueError("main_and_variant_required")
            if self.main.katalog == self.variant.katalog:
                raise ValueError("same_catalog")
        return self

    def catalogs(self) -> list[str]:
        return [c.katalog for c in (self.main if self.mode != "variant" else None, self.variant) if c is not None]


def state_of(raw: dict[str, Any] | None) -> dict[str, Any]:
    value = (raw or {}).get(STATE)
    return dict(value) if isinstance(value, dict) else {}


def in_progress(state: dict[str, Any], now: datetime) -> bool:
    if state.get("status") != "in_progress":
        return False
    try:
        started = datetime.fromisoformat(str(state.get("started_at")))
    except ValueError:
        return False
    return now - started < IN_PROGRESS_TTL


def card(c: ArticleCreated) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "katalog": c.katalog,
        "nazev": c.nazev,
        "parent_id": str(c.parent_id) if c.parent_id else None,
        "unit": c.unit,
    }


def as_article(c: dict[str, Any]) -> Article:
    return Article(
        id=uuid.UUID(c["id"]),
        code=None,
        catalog=c["katalog"],
        name=c["nazev"],
        ean=None,
        unit=c.get("unit"),
        parent_id=uuid.UUID(c["parent_id"]) if c.get("parent_id") else None,
    )


def payload(katalog: str, nazev: str, smid: str, parent_id: uuid.UUID | None) -> dict[str, Any]:
    """The bridge body — exactly these keys (the bridge maps them to Katalog, Nazev, Poznamka, NadrazenyArtikl_ID)."""
    out: dict[str, Any] = {"katalog": katalog, "nazev": nazev, "smid": smid}
    if parent_id is not None:
        out["parent_id"] = str(parent_id)
    return out


def body_bytes(p: dict[str, Any]) -> bytes:
    return json.dumps(p, separators=(",", ":")).encode()  # byte-identical to BridgeClient._post


def payload_hash(p: dict[str, Any]) -> str:
    return hashlib.sha256(body_bytes(p)).hexdigest()


def smid_for(state: dict[str, Any], katalog: str) -> str:
    """The same catalog keeps its SMID across retries (idempotent in the bridge); a new catalog gets a new one."""
    smids = state.setdefault("smids", {})
    if katalog not in smids:
        smids[katalog] = str(uuid.uuid4())
    return str(smids[katalog])


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ----- catalog proposal for a variant (D32: main catalog + 5-digit size suffix, next free when taken) -----

_SIZE = re.compile(r"(?<![A-Za-z0-9])M\s?(\d{1,3})(?![\d])", re.IGNORECASE)  # M10x30, M8, m 12


def size_of(text: str | None) -> int | None:
    """The thread diameter of the supplier text („Skrutka DIN 933 M10x30“ → 10); a bare number is taken as is."""
    if not text:
        return None
    t = text.strip()
    if t.isdigit():
        return int(t)
    m = _SIZE.search(t)
    return int(m.group(1)) if m else None


def proposals(main_catalog: str, size: int) -> list[str]:
    return [f"{main_catalog}{str(size + i).zfill(5)}" for i in range(PROPOSAL_TRIES)]
