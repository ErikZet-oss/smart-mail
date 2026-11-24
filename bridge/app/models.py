"""Bridge response models — shared by the mock and the real Money backend (one contract, CLAUDE.md §0.1).

Field names are English; the Money source field is in each comment. Money values are `Decimal` (JSON: strings).
Enum-like Money integers (`Stav`, `TypDokladu`, `Vyrizeno`) are passed through raw: their meaning is [PROBE] and is
never guessed here.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

InvoiceKind = Literal["invoice", "proforma"]
# #222: documents whose PDF comes from Money's generic print endpoint `/pdfreport` (whitelist, extendable)
DocumentKind = Literal["issued_delivery_note"]
DeliveryMatchedBy = Literal["number", "order", "company", "none"]
CodebookName = Literal["warehouses", "centres", "numerical-series", "currencies", "activity-types"]
MatchedBy = Literal["number", "variable_symbol", "reference", "company_dates", "number_digits", "order", "none"]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Connection(_Model):
    kind: str | None  # TypSpojeni.Kod
    value: str  # SpojeniCislo


class Company(_Model):
    id: uuid.UUID
    code: str | None  # Kod
    name: str  # Nazev
    ico: str | None
    dic: str | None
    icdph: str | None
    email: str | None
    discount_pct: Decimal | None  # HodnotaSlevy
    own_discount: bool | None  # VlastniSleva
    due_days: int | None  # SplatnostPohledavek
    connections: list[Connection]  # SeznamSpojeni


class Person(_Model):
    id: uuid.UUID
    company_id: uuid.UUID | None  # REST parent_ID — that it is the company is [PROBE]
    first_name: str | None
    last_name: str | None
    name: str | None
    function: str | None
    email: str | None
    phone: str | None


class IssuedInvoice(_Model):
    id: uuid.UUID
    kind: InvoiceKind
    number: str  # CisloDokladu
    variable_symbol: str | None
    company_id: uuid.UUID | None  # Firma_ID
    issued_on: date | None
    due_on: date | None
    paid_on: date | None  # DatumUhrady
    total: Decimal  # CelkovaCastka
    remaining: Decimal  # UhradyZbyva
    currency_id: uuid.UUID | None
    reference: str | None  # Odkaz
    doc_type: int | None  # TypDokladu, raw
    centre_id: uuid.UUID | None = None  # Stredisko_ID — selects the branch print report (#174)
    description: str | None = None  # Nazev = card „Popis“; holds the e-shop order number (#210)
    note: str | None = None  # Poznamka = card „Poznámka“; also holds the customer's order number (#217)


class Order(_Model):
    id: uuid.UUID
    number: str
    company_id: uuid.UUID | None
    issued_on: date | None
    reference: str | None
    state: int | None  # Stav, raw
    done: int | None  # Vyrizeno, raw
    total: Decimal


class Delivery(_Model):
    id: uuid.UUID
    number: str
    company_id: uuid.UUID | None
    issued_on: date | None
    moved_on: date | None  # DatumSkladovehoPohybu
    reference: str | None
    state: int | None  # Stav, raw
    transport: str | None  # ZpusobDopravy.Nazev
    total: Decimal
    centre_id: uuid.UUID | None = None  # Stredisko_ID — selects the branch print report (#222)
    description: str | None = None  # Nazev = „Popis“; usually holds the customer's order number (#222)
    note: str | None = None  # Poznamka = „Poznámka“; also the customer's order number (#222)


class Activity(_Model):
    id: uuid.UUID
    company_id: uuid.UUID | None
    person_id: uuid.UUID | None
    type_id: uuid.UUID | None
    description: str | None  # popis
    started_at: datetime | None
    done: bool | None


class CodebookItem(_Model):
    id: uuid.UUID
    code: str | None
    name: str | None


class CompanyPage(_Model):
    items: list[Company]
    next_from: int | None


class PersonPage(_Model):
    items: list[Person]
    next_from: int | None


class CodebookPage(_Model):
    items: list[CodebookItem]
    next_from: int | None


class OverduePage(_Model):
    """Issued invoices with a balance and due before a date, all customers (W8b Upomienky)."""

    items: list[IssuedInvoice]
    next_from: int | None


class InvoiceSearch(_Model):
    matched_by: MatchedBy
    items: list[IssuedInvoice]


class DeliverySearch(_Model):
    """#222 issued delivery notes: by number, by the customer's order in Popis/Poznámka, or the company's latest."""

    matched_by: DeliveryMatchedBy
    items: list[Delivery]


class ActivityIn(_Model):
    """Phase 3f: CRM activity after a person sent an e-mail to a Money company (REST `Activity`). Only the subject and
    document numbers — never a mail body. `smid` = `SMID:<draft_id>` makes the write idempotent."""

    company_id: uuid.UUID
    type_id: uuid.UUID
    subject: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    smid: str = Field(pattern=r"^SMID:[0-9a-f-]{36}$")


CATALOG_RE = r"^[^~#|()]{1,50}$"  # used in a filter (`Katalog~eq~…`), so never a filter character
SMID_RE = r"^[A-Za-z0-9-]{8,64}$"


class ArticleCreateIn(_Model):
    """D32 (#239) `CreateArticle` — only these values; Money fills unit, VAT and kind, the card lands in the unnamed
    root group without a category. Never a group, category, unit, VAT or parameter."""

    katalog: str = Field(pattern=CATALOG_RE)
    nazev: str = Field(min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None  # NadrazenyArtikl_ID — a variant of this main card
    smid: str = Field(pattern=SMID_RE)  # written to Poznamka as `SMID:<smid> · Smart Mail`


class ArticleCreated(_Model):
    id: uuid.UUID
    katalog: str
    nazev: str
    parent_id: uuid.UUID | None = None
    unit: str | None = None  # read back: HlavniJednotka.Kod filled by Money
    reconciled: bool = False  # True = the create answered with an error, the card was then found by its catalog + SMID


class CatalogArticle(_Model):
    katalog: str
    nazev: str


class CatalogFree(_Model):
    free: bool
    article: CatalogArticle | None = None


class ActivityOut(_Model):
    id: uuid.UUID
    created: bool  # False = an activity with this SMID already existed (idempotent repeat)


class Health(_Model):
    status: str
    version: str
    backend: str
    agenda: str
    writes_enabled: bool


# ----- Phase 4b: articles and supplier codes (read-only, MONEY_API §5.5.3–§5.5.4) -----


class ArticleUnit(_Model):
    code: str | None  # e.g. ks, bal
    qty: Decimal | None  # how many main units (`Mnozstvi`), e.g. bal = 200 ks
    decimals: int | None = None  # `DesetinnaMista`


class Article(_Model):
    id: uuid.UUID
    code: str | None  # Kod
    catalog: str | None  # Katalog
    name: str
    ean: str | None  # CarovyKod
    unit: str | None  # main unit (HlavniJednotka.Kod)
    units: list[ArticleUnit] = []
    inactive: bool = False
    parent_id: uuid.UUID | None = None  # NadrazenyArtikl_ID — a variant points to its main card (#233)
    plu: str | None = None  # PLU — Money groups the variants of a main card by it (W6h Katalóg, pilot 2026-11-24)
    last_price: Decimal | None = None  # PosledniCena — „Posledná nákupná cena“ of the catalog


class WarehouseStockRow(_Model):
    """`WarehouseStocks` row of one article in one warehouse (W6h Katalóg „Zásoby“, information only — D18)."""

    warehouse_id: uuid.UUID
    code: str | None  # Sklad.Kod
    name: str | None  # Sklad.Nazev
    qty: Decimal  # AktualniStav.ZustatekMnozstvi — „Aktuálne množstvo“
    reserved: Decimal  # Rezervovano
    ordered: Decimal  # Objednano
    expected: Decimal  # PredpokladaneMnozstvi
    available: Decimal  # DostupneMnozstvi
    unit_price: Decimal | None  # AktualniStav.ZustatekJednotkaCena — „Aktuálna skladová cena“


class ArticleCatalogInfo(_Model):
    """W6h Katalóg: e-shop flag (`EShopArticles`) and stock per warehouse of one article — read only."""

    article_id: uuid.UUID
    eshop: bool
    stocks: list[WarehouseStockRow]


class SupplierCode(_Model):
    """`ArticleSuppliers` row: the supplier's code for one of our articles."""

    id: uuid.UUID | None = None  # `ArticleSuppliers.ID` — the key of the app's read cache (#228)
    article_id: uuid.UUID
    supplier_id: uuid.UUID
    code: str
    name: str | None
    last_price: Decimal | None
    unit: str | None  # unit the supplier sells in (`Jednotka.Kod`)
    article_unit: str | None  # our unit that corresponds to it (`ArtiklJednotka.Kod`)
    article_unit_qty: Decimal | None  # `ArtiklJednotka.Mnozstvi` (main units per supplier unit)


class SupplierCodePage(_Model):
    items: list[SupplierCode]
    next_from: int | None


# ----- Phase 4c (#247, D33): received delivery note written to Money as a KONCEPT -----

UUID_ZERO = uuid.UUID(int=0)
KONCEPT_PREFIX = "Smartmail"  # D33: Popis (`Nazev`) of every note written by Smart Mail starts with it


class DeliveryNoteContentIn(_Model):
    """`ObsahPolozky` of a stock line (`ContentOfItemWithArticleInput`)."""

    Artikl_ID: uuid.UUID
    Sklad_ID: uuid.UUID
    Mnozstvi: Decimal = Field(gt=0)
    PartnerskyKod: str | None = Field(default=None, max_length=100)
    PartnerskyNazev: str | None = Field(default=None, max_length=255)
    DruhPolozky_ID: uuid.UUID | None = None  # copied from the branch template line
    VazbaTypVazby: int | None = None  # copied from the branch template line
    # copied from the branch template line (pilot 2026-11-24: 0 → Money refuses to save an edited line)
    VazbaPocetNadrizene: Decimal | None = Field(default=None, gt=0)
    VazbaPocetPodrizene: Decimal | None = Field(default=None, gt=0)


class DeliveryNoteItemIn(_Model):
    """One line (`ReceivedDeliveryNoteItemInput`). `TypObsahu` comes from the branch template (1 = article line —
    without it Money stores a text line without article / warehouse, PROD probe 2026-11-23)."""

    Poradi: int = Field(ge=1)
    Nazev: str = Field(min_length=1, max_length=255)
    Katalog: str | None = Field(default=None, max_length=100)
    Mnozstvi: Decimal = Field(gt=0)  # D15: never negative, returns only in Money
    Jednotka: str | None = Field(default=None, max_length=20)
    # exactly one of them: a stock line with the invoice line total sends `CelkovaCena` and Money derives the unit
    # price (PROD probe 2026-11-24: 1000 pcs + 40.25 → JednCena 0.0403, CelkovaCena 40.25 — the invoice to the cent;
    # JednCena 0.04025 would be stored as 0.0403 → 40.30)
    JednCena: Decimal | None = Field(default=None, ge=0)
    CelkovaCena: Decimal | None = Field(default=None, ge=0)
    TypCeny: int
    TypObsahu: int
    SazbaDPH_ID: uuid.UUID | None = None
    DruhSazbyDPH: int | None = None
    Stredisko_ID: uuid.UUID
    DruhPolozky_ID: uuid.UUID | None = None
    ObsahPolozky: DeliveryNoteContentIn | None = None  # None = text (non-stock) line
    # D34 side costs (doprava, balné …) of this line, like Money's „Náklady – rovnomerne podľa počtu položiek“;
    # PROD probe 302600973: Money keeps CelkoveVedlejsiNaklady but fills the per-unit values only when they are sent
    CelkoveVedlejsiNaklady: Decimal | None = Field(default=None, ge=0)
    JednotkoveVedlejsiNaklady: Decimal | None = Field(default=None, ge=0)
    JednotkovaPorizovaciCena: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _one_price(self) -> DeliveryNoteItemIn:
        if (self.JednCena is None) == (self.CelkovaCena is None):
            raise ValueError("exactly one of JednCena / CelkovaCena")
        return self


class DeliveryNoteIn(_Model):
    """`CreateReceivedDeliveryNote` body (DOCUMENTS_SPEC §2.8, MONEY_API 5.5.7). Koncept only (D33): `Faze` 0 and
    `Schvaleno` false are required and `Schvalil_ID` / `DatumSchvaleni` do not exist here — the router refuses such a
    body with 422 `not_koncept` before it is parsed. Header IDs are copied from the branch template, never guessed."""

    smid: str = Field(pattern=SMID_RE)  # written into Poznamka as `SMID:<smid>`; not a Money field
    with_address: bool = False  # MONEY_API 5.5.7: send Adresa*/IC/DIC/ICDPH from the Money company card
    Firma_ID: uuid.UUID
    CiselnaRada_ID: uuid.UUID
    Stredisko_ID: uuid.UUID
    Group_ID: uuid.UUID  # list group of the branch (DLP NR / SE / TN / TT) — else „Nezaradené“
    DruhPohybu_ID: uuid.UUID
    DruhSkladovehoPohybu_ID: uuid.UUID
    Predkontace_ID: uuid.UUID
    RegistraceDPH_ID: uuid.UUID | None = None
    DruhDokladu_ID: uuid.UUID | None = None
    Mena_ID: uuid.UUID | None = None
    Odkaz: str = Field(min_length=1, max_length=50)
    ParovaciSymbol: str | None = Field(default=None, max_length=50)
    Nazev: str = Field(min_length=len(KONCEPT_PREFIX), max_length=100)
    Poznamka: str = Field(default="", max_length=1000)
    DatumVystaveni: date
    DatumUcetnihoPripadu: date
    DatumSkladovehoPohybu: date
    CasSkladovehoPohybu: datetime  # D13: the moment of the write
    Faze: Literal[0]
    Schvaleno: Literal[False]
    Polozky: list[DeliveryNoteItemIn] = Field(min_length=1, max_length=500)
    DodatecnePorizovaciNaklady: Decimal | None = Field(default=None, gt=0)  # D34: = Σ line side costs

    @model_validator(mode="after")
    def _side_costs_add_up(self) -> DeliveryNoteIn:
        lines = sum((it.CelkoveVedlejsiNaklady or Decimal("0") for it in self.Polozky), Decimal("0"))
        if lines != (self.DodatecnePorizovaciNaklady or Decimal("0")):
            raise ValueError("side_costs_mismatch")  # D34: the header is exactly the sum of the lines
        return self

    @field_validator("Nazev")
    @classmethod
    def _smartmail_prefix(cls, v: str) -> str:
        if not v.startswith(KONCEPT_PREFIX):
            raise ValueError("popis_prefix")  # D33: always „Smartmail…“, so the notes are easy to find in Money
        return v

    def money_input(self) -> dict[str, Any]:
        """The `ReceivedDeliveryNoteInput` variables: Money field names only, IDs as strings, Decimals kept."""
        data = self.model_dump(exclude={"smid", "with_address", "Poznamka"}, exclude_none=True)
        data["Poznamka"] = f"SMID:{self.smid}" + (f" · {self.Poznamka}" if self.Poznamka else "")
        out = _money_values(data)
        assert isinstance(out, dict)
        return out


def _money_values(value: object) -> object:
    if isinstance(value, dict):
        return {k: _money_values(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_money_values(v) for v in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat()
    if isinstance(value, date):
        return f"{value.isoformat()}T00:00:00"  # Money `DateTime`
    return value


class DeliveryNoteLineBack(_Model):
    """A line of the note as Money stored it (read-back)."""

    id: uuid.UUID | None
    number: int | None  # CisloPolozky
    order: int | None  # Poradi
    qty: Decimal
    unit_price: Decimal
    content_type: int | None  # TypObsahu
    article_id: uuid.UUID | None
    warehouse_id: uuid.UUID | None
    centre_id: uuid.UUID | None


class DeliveryNoteCreated(_Model):
    id: uuid.UUID
    number: str | None  # CisloDokladu
    faze: int | None
    schvaleno: bool | None
    group_id: uuid.UUID | None
    centre_id: uuid.UUID | None
    total_base: Decimal  # SumaZaklad
    total: Decimal  # CelkovaCastka
    address_empty: bool  # read-back AdresaNazev empty → the next writes send the address (MONEY_API 5.5.7)
    lines: list[DeliveryNoteLineBack]
    reconciled: bool = False  # found by its SMID (a repeat or after an error/timeout) instead of created now
    side_costs: Decimal = Decimal("0")  # DodatecnePorizovaciNaklady (D34)


class ReceivedNoteRow(_Model):
    """Settings 11e „Vybrať iný“: one received delivery note of the branch centre."""

    id: uuid.UUID
    number: str | None
    supplier: str | None
    issued_on: date | None
    koncept: bool  # Faze 0 + Schvaleno false
    by_smart_mail: bool  # Popis starts with „Smartmail“ — never the default template


class DeliveryNoteTemplate(_Model):
    """Values copied from the branch template note (DOCUMENTS_SPEC §2.6, D33) — every ID read from Money."""

    id: uuid.UUID
    number: str | None
    supplier: str | None
    issued_on: date | None
    centre_id: uuid.UUID | None
    header: dict[str, str]  # CiselnaRada_ID … Group_ID, Mena_ID (only present values)
    line: dict[
        str, str | int
    ]  # first stock line: TypObsahu, TypCeny, DruhPolozky_ID, SazbaDPH_ID, DruhSazbyDPH, VazbaTypVazby, VazbaPocet*
    text_line: dict[str, int] | None  # TypObsahu of a text line, when the template has one
