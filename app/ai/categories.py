"""AI mail categories — ids match AI_ASSISTANT §4; SK labels for UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class CategoryDef:
    id: str
    label_sk: str
    description_sk: str
    # token CSS variable name suffix under --color-* (UI maps to Tailwind)
    color_token: str
    show_in_triage: bool = True


# Order matches Figma W2f AI TRIEDENIE list.
CATEGORIES: Final[tuple[CategoryDef, ...]] = (
    CategoryDef("inquiry", "Dopyty", "žiadosti o ceny a dostupnosť", "warning"),
    CategoryDef("order", "Objednávky", "objednávky tovaru od zákazníkov", "success"),
    CategoryDef("order_change", "Zmeny objednávok", "zmeny existujúcich objednávok", "success", show_in_triage=False),
    CategoryDef("order_cancel", "Storná objednávok", "storná objednávok", "danger", show_in_triage=False),
    CategoryDef("invoice_request", "Žiadosti o faktúru", "prosby o vystavenie alebo kópiu faktúry", "info"),
    CategoryDef(
        "supplier_document",
        "Doklady dodávateľov",
        "faktúry a dodacie listy od dodávateľov",
        "danger",
    ),
    CategoryDef("complaint", "Reklamácie", "reklamácie tovaru alebo služieb", "danger"),
    CategoryDef("shipping", "Doprava", "zásielky, tracking, kuriér", "info"),
    CategoryDef("payment", "Platby", "platby, upomienky, potvrdenia úhrad", "danger"),
    CategoryDef(
        "document_request",
        "Žiadosti o dokument",
        "atesty, certifikáty, technické listy, VOP",
        "warning",
    ),
    CategoryDef("supplier_info", "Dodávatelia – info", "cenníky, výpadky, zmeny cien", "success"),
    CategoryDef("newsletter", "Feed", "newslettre a hromadné správy", "brand"),
    CategoryDef("notification", "Notifikácie", "systémové a automatické oznámenia", "info", show_in_triage=False),
    CategoryDef("spam", "Spam", "nevyžiadaná pošta", "danger", show_in_triage=False),
    CategoryDef("internal", "Interné", "pošta v rámci firmy", "brand", show_in_triage=False),
    CategoryDef("other", "Iné", "nezaradené správy", "neutral", show_in_triage=False),
)

CATEGORY_IDS: Final[frozenset[str]] = frozenset(c.id for c in CATEGORIES)
TRIAGE_CATEGORIES: Final[tuple[CategoryDef, ...]] = tuple(c for c in CATEGORIES if c.show_in_triage)
CATEGORY_BY_ID: Final[dict[str, CategoryDef]] = {c.id: c for c in CATEGORIES}

PRIORITY_IDS: Final[frozenset[str]] = frozenset({"urgent", "normal", "low"})
LANGUAGE_IDS: Final[frozenset[str]] = frozenset({"sk", "cs", "en", "de", "pl", "hu", "other"})
