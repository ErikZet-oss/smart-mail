"""Prehlásenie o zhode (atest 2.1) — render and numbering (#139 part B, ADR-015).

The PDF is rendered on the server with Jinja2 + WeasyPrint from `templates/print/conformity.html.j2` (a port of
Erik's approved template). The branch stamp and the manager's signature are read from storage only here and are
embedded as data URIs — they are never served. Numbers are one company-wide series `PZ-RRRR-NNNN`, a counter row in
`org_settings` locked with SELECT … FOR UPDATE inside the issue transaction (no gaps, never repeats).
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import OrgSettings

TEMPLATES = Path(__file__).resolve().parents[2] / "templates" / "print"
COUNTER_SECTION = "conformity.counter"
COMPANY_SECTION = "company"
MAX_ITEMS = 500
ITEM_KEYS = ("nazov", "kod", "norma", "poznamka")
ITEM_LIMITS = {"nazov": 200, "kod": 60, "norma": 80, "poznamka": 200}
COLUMN_LABELS = {"nazov": "Názov výrobku", "kod": "Kód", "norma": "Norma", "poznamka": "Poznámka"}

FIRM: dict[str, str] = {
    "name": "SMART s.r.o.",
    "slogan": "Spojovací materiál · Kotviaca technika",
    "street": "Novozámocká 232",
    "city": "949 01 Nitra",
    "ic_dph": "SK2020393606",
    "web": "www.smartsro.sk",
}
LEGAL_BASIS = "podľa zákona č. 22/1997 Z. z. o technických požiadavkách na výrobky"
TEXT_INTRO = (
    "Na základe zákona č. 22/1997 Z. z. a ďalej vykonávacích predpisov vlády SR č. 173/1997 Z. z. "
    "a č. 163/2002 Z. z., v platných zneniach, vydávame uistenie, že nami dodávaný spojovací materiál "
    "a kotviaca technika, vrátane materiálu, ktorý patrí medzi vybrané výrobky pre nosné stavebné "
    "konštrukcie podľa predpisu č. 163/2002 Z. z., bolo ich výrobcami, resp. dovozcami vystavené podľa "
    "§ 13 cit. zákona prehlásenie o zhode, predložené príslušnými certifikátmi a osvedčeniami "
    "potvrdzujúcimi, že tento materiál spĺňa zákonné požiadavky predpísané platnými slovenskými normami, "
    "prípadne prevzatými medzinárodnými normami a predpismi týkajúcimi sa oprávneného záujmu "
    "a požiadaviek na bezpečnosť výrobkov."
)
TEXT_SCOPE = (
    "Toto prehlásenie sa vzťahuje na sortiment výrobkov písomne deklarovaný a publikovaný firmou "
    "SMART s.r.o. v bežnom obchodnom styku vrátane plnenia verejných zákaziek a súčasne nadväzuje "
    "na už vystavené uistenia tuzemských výrobcov a dovozcov nami distribuovaných výrobkov na sprievodné "
    "doklady a vydané prehlásenia o zhode, ktoré sú v sídle našej spoločnosti k dispozícii pre príslušné "
    "kontrolné orgány."
)


@dataclass(frozen=True, slots=True)
class Party:
    name: str
    address: str | None = None
    phone: str | None = None


@dataclass(frozen=True, slots=True)
class Signer:
    name: str
    function: str | None


@dataclass(slots=True)
class DeclarationData:
    number: str
    issued_on: date
    customer: str
    document_ref: str
    place: str
    items: list[dict[str, str]] = field(default_factory=list)


def clean_items(raw: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Strings only, trimmed and length-limited; rows without a product name are dropped."""
    out: list[dict[str, str]] = []
    for row in raw[:MAX_ITEMS]:
        item = {k: str(row.get(k) or "").strip()[: ITEM_LIMITS[k]] for k in ITEM_KEYS}
        if item["nazov"]:
            out.append(item)
    return out


def columns(items: list[dict[str, str]]) -> list[tuple[str, str]]:
    """Názov always; Kód / Norma / Poznámka only when some row has them (Erik's template)."""
    cols = [("nazov", COLUMN_LABELS["nazov"])]
    cols += [(k, COLUMN_LABELS[k]) for k in ("kod", "norma", "poznamka") if any(i.get(k) for i in items)]
    return cols


def _data_uri(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def render_html(
    d: DeclarationData, *, branch: Party, signer: Signer, stamp_png: bytes, signature_png: bytes, ico: str
) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html", "j2"]))
    template = env.get_template("conformity.html.j2")
    return template.render(
        # our own stylesheet, not user data: autoescape would turn its quotes into &#34; and break font-family
        css=Markup((TEMPLATES / "conformity.css").read_text(encoding="utf-8")),  # noqa: S704
        logo=_data_uri((TEMPLATES / "assets" / "logo-smart.svg").read_bytes(), "image/svg+xml"),
        stamp=_data_uri(stamp_png, "image/png"),
        signature=_data_uri(signature_png, "image/png"),
        firm={**FIRM, "ico": ico},
        branch=branch,
        signer=signer,
        d={
            "number": d.number,
            "date": d.issued_on.strftime("%d.%m.%Y"),
            "customer": d.customer,
            "document_ref": d.document_ref,
            "place": d.place,
            "rows": d.items,
        },
        columns=columns(d.items),
        legal_basis=LEGAL_BASIS,
        text_intro=TEXT_INTRO,
        text_scope=TEXT_SCOPE,
    )


def render_pdf(html: str) -> bytes:
    from weasyprint import HTML

    pdf = HTML(string=html, base_url=str(TEMPLATES)).write_pdf()
    assert pdf is not None
    return bytes(pdf)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def company_ico(db: AsyncSession) -> str:
    row = await db.scalar(select(OrgSettings).where(OrgSettings.section == COMPANY_SECTION))
    value = (row.data or {}).get("ico") if row else None
    return str(value).strip() if value else ""  # empty = left out of the footer, as in Erik's script


async def next_number(db: AsyncSession, today: date) -> str:
    """Take the next `PZ-RRRR-NNNN` inside the caller's transaction. The counter row is locked FOR UPDATE, so two
    issues at once wait for each other; the number restarts at 0001 every year. The caller commits."""
    await db.execute(
        insert(OrgSettings)
        .values(section=COUNTER_SECTION, data={"year": today.year, "last": 0})
        .on_conflict_do_nothing(index_elements=["section"])
    )
    row = await db.scalar(select(OrgSettings).where(OrgSettings.section == COUNTER_SECTION).with_for_update())
    assert row is not None
    data = dict(row.data or {})
    last = int(data.get("last") or 0) if int(data.get("year") or 0) == today.year else 0
    number = last + 1
    row.data = {"year": today.year, "last": number}
    await db.flush()
    return f"PZ-{today.year}-{number:04d}"
