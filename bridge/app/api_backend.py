"""Money S4 backend over the official API (MONEY_BACKEND=api). Reads + the approved writes (activity, article,
received delivery note as a koncept).

Only GraphQL list/detail queries from `queries/*.graphql` and the REST calls whose shape is in the swagger files.
REST list filters (`Filters`, `PropertyName`, `Operation`, `ExpectedValue`) and `?text=` do NOT work on the customer's
API 1.15.11 (probe on the TEST agenda 2026-10-31: no syntax returned only the searched invoice). Searching is GraphQL
only; REST is used only for PDF reports, persons, activity types and (later) activities. Calls that would need a REST
filter raise `WaitingForProbe`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx

from app import wildcard
from app.backend import (
    ArticleQuery,
    CatalogExists,
    DeliveryQuery,
    DuplicateNote,
    InvoiceQuery,
    MoneyError,
    MoneyUnavailable,
    WaitingForProbe,
)
from app.config import BridgeSettings
from app.filters import all_, any_, cond
from app.gql_client import TIMEOUT, MoneyHttp, TokenProvider
from app.models import (
    KONCEPT_PREFIX,
    Activity,
    ActivityIn,
    ActivityOut,
    Article,
    ArticleCatalogInfo,
    ArticleCreated,
    ArticleCreateIn,
    ArticlePage,
    ArticleUnit,
    CodebookItem,
    CodebookName,
    CodebookPage,
    Company,
    CompanyPage,
    Connection,
    Delivery,
    DeliveryMatchedBy,
    DeliveryNoteCreated,
    DeliveryNoteIn,
    DeliveryNoteLineBack,
    DeliveryNoteTemplate,
    DeliverySearch,
    DocumentKind,
    InvoiceKind,
    InvoiceSearch,
    IssuedInvoice,
    MatchedBy,
    Order,
    OverduePage,
    Person,
    PersonPage,
    ReceivedNoteRow,
    SupplierCode,
    SupplierCodePage,
    WarehouseStockRow,
)

CODEBOOK_QUERIES: dict[str, tuple[str, str]] = {
    "warehouses": ("warehouses", "Warehouses"),
    "centres": ("centres", "Centres"),
    "numerical-series": ("numerical_series", "NumericalSeries"),
    "currencies": ("currencies", "Currencies"),
}
REPORT_PATHS: dict[InvoiceKind, str] = {"invoice": "IssuedInvoice", "proforma": "PrepaymentIssuedInvoice"}
# #222 `objectname` of `/pdfreport` = the object name from the API reference; only this whitelist, never mail text
PDFREPORT_OBJECTS: dict[DocumentKind, str] = {"issued_delivery_note": "issueddeliverynote"}
LATEST_DELIVERY_DAYS = 400
VARIANT_LIMIT = 300  # #233: variants of up to 10 main cards in one GraphQL call
SEARCH_LIMIT = 20
ARTICLE_LIMIT = 20
CATALOG_INFO_MAX = 100  # W6h Katalóg: articles per catalog-info call
STOCK_LIMIT = 1000  # WarehouseStocks / EShopArticles rows for up to 100 articles (a few warehouses / e-shops each)
WILDCARD_SCAN = 300  # `%` search: rows read from Money for the AND of the pieces, then filtered by their order
WILDCARD_LIMIT = 50
HISTORY_LIMIT = 200


def _s(value: Any) -> str | None:
    return None if value in (None, "") else str(value)


def _uuid(value: Any) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    try:
        parsed = uuid.UUID(str(value))
    except ValueError:
        return None
    return None if parsed.int == 0 else parsed


def _date(value: Any) -> date | None:
    text = _s(value)
    if text is None or text.startswith("0001-01-01"):
        return None
    return date.fromisoformat(text[:10])


def _dt(value: Any) -> datetime | None:
    text = _s(value)
    if text is None or text.startswith("0001-01-01"):
        return None
    return datetime.fromisoformat(text)


def _dec(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _int(value: Any) -> int | None:
    return None if value is None else int(value)


def _required_uuid(value: Any) -> uuid.UUID:
    parsed = _uuid(value)
    if parsed is None:
        raise MoneyError("record without ID")
    return parsed


def company_from(raw: dict[str, Any]) -> Company:
    conns = raw.get("SeznamSpojeni") or []
    if isinstance(conns, dict):
        conns = [conns]
    return Company(
        id=_required_uuid(raw.get("ID")),
        code=_s(raw.get("Kod")),
        name=_s(raw.get("Nazev")) or "",
        ico=_s(raw.get("ICO")),
        dic=_s(raw.get("DIC")),
        icdph=_s(raw.get("ICDPH")),
        email=_s(raw.get("Email")),
        discount_pct=None if raw.get("HodnotaSlevy") is None else _dec(raw.get("HodnotaSlevy")),
        own_discount=raw.get("VlastniSleva"),
        due_days=_int(raw.get("SplatnostPohledavek")),
        connections=[
            Connection(kind=_s((c.get("TypSpojeni") or {}).get("Kod")), value=str(c["SpojeniCislo"]))
            for c in conns
            if c and _s(c.get("SpojeniCislo"))
        ],
    )


def invoice_from(raw: dict[str, Any], kind: InvoiceKind = "invoice") -> IssuedInvoice:
    return IssuedInvoice(
        id=_required_uuid(raw.get("ID")),
        kind=kind,
        number=_s(raw.get("CisloDokladu")) or "",
        variable_symbol=_s(raw.get("VariabilniSymbol")),
        company_id=_uuid(raw.get("Firma_ID")),
        issued_on=_date(raw.get("DatumVystaveni")),
        due_on=_date(raw.get("DatumSplatnosti")),
        paid_on=_date(raw.get("DatumUhrady")),
        total=_dec(raw.get("CelkovaCastka")),
        remaining=_dec(raw.get("UhradyZbyva")),
        currency_id=_uuid(raw.get("Mena_ID")),
        reference=_s(raw.get("Odkaz")),
        doc_type=_int(raw.get("TypDokladu")),
        centre_id=_uuid(raw.get("Stredisko_ID")),
        description=_s(raw.get("Nazev")),
        note=_s(raw.get("Poznamka")),
    )


def order_from(raw: dict[str, Any]) -> Order:
    return Order(
        id=_required_uuid(raw.get("ID")),
        number=_s(raw.get("CisloDokladu")) or "",
        company_id=_uuid(raw.get("Firma_ID")),
        issued_on=_date(raw.get("DatumVystaveni")),
        reference=_s(raw.get("Odkaz")),
        state=_int(raw.get("Stav")),
        done=_int(raw.get("Vyrizeno")),
        total=_dec(raw.get("CelkovaCastka")),
    )


def delivery_from(raw: dict[str, Any]) -> Delivery:
    return Delivery(
        id=_required_uuid(raw.get("ID")),
        number=_s(raw.get("CisloDokladu")) or "",
        company_id=_uuid(raw.get("Firma_ID")),
        issued_on=_date(raw.get("DatumVystaveni")),
        moved_on=_date(raw.get("DatumSkladovehoPohybu")),
        reference=_s(raw.get("Odkaz")),
        state=_int(raw.get("Stav")),
        transport=_s((raw.get("ZpusobDopravy") or {}).get("Nazev")),
        total=_dec(raw.get("CelkovaCastka")),
        centre_id=_uuid(raw.get("Stredisko_ID")),
        description=_s(raw.get("Nazev")),
        note=_s(raw.get("Poznamka")),
    )


def _ci(raw: dict[str, Any]) -> dict[str, Any]:
    """REST DTOs: swagger documents camelCase, the real API 1.15.11 answers PascalCase (`ID`, `Parent_ID`, `Kod`,
    `Tel1Cislo`, …; probe on the TEST agenda 2026-10-31). Every REST mapper reads keys case-insensitively."""
    return {str(k).lower(): v for k, v in raw.items()}


def _rest_rows(body: Any) -> list[dict[str, Any]]:
    """A REST list after `unwrap`: a plain list, or (older versions) a dict wrapping it."""
    if isinstance(body, dict):
        body = body.get("Data") or body.get("data") or body.get("items") or []
    if not isinstance(body, list):
        raise MoneyError("REST list: not a list")
    return [r for r in body if isinstance(r, dict)]


def codebook_item_from_rest(raw: dict[str, Any]) -> CodebookItem:
    raw = _ci(raw)
    return CodebookItem(id=_required_uuid(raw.get("id")), code=_s(raw.get("kod")), name=_s(raw.get("nazev")))


def person_from(raw: dict[str, Any]) -> Person:
    """REST `PersonOutputDto`, keys case-insensitive (`_ci`)."""
    raw = _ci(raw)
    return Person(
        id=_required_uuid(raw.get("id")),
        company_id=_uuid(raw.get("parent_id")),
        first_name=_s(raw.get("jmeno")),
        last_name=_s(raw.get("prijmeni")),
        name=_s(raw.get("nazev")),
        function=_s(raw.get("funkce")),
        email=_s(raw.get("email")),
        phone=_s(raw.get("tel1cislo")),
    )


def _unit(raw: Any) -> ArticleUnit | None:
    if not isinstance(raw, dict):
        return None
    dec = raw.get("DesetinnaMista")
    return ArticleUnit(
        code=_s(raw.get("Kod")),
        qty=None if raw.get("Mnozstvi") is None else _dec(raw.get("Mnozstvi")),
        decimals=None if dec is None else int(_dec(dec)),
    )


def article_from(raw: dict[str, Any]) -> Article:
    main: dict[str, Any] = raw["HlavniJednotka"] if isinstance(raw.get("HlavniJednotka"), dict) else {}
    units = [u for u in (_unit(x) for x in raw.get("SeznamJednotek") or []) if u is not None]
    return Article(
        id=_required_uuid(raw.get("ID")),
        code=_s(raw.get("Kod")),
        catalog=_s(raw.get("Katalog")),
        name=_s(raw.get("Nazev")) or "",
        ean=_s(raw.get("CarovyKod")),
        unit=_s(main.get("Kod")),
        units=units,
        inactive=raw.get("Hidden") is True,
        parent_id=_uuid(raw.get("NadrazenyArtikl_ID")),
        plu=_s(raw.get("PLU")),
        last_price=_dec(raw["PosledniCena"]) if raw.get("PosledniCena") is not None else None,
    )


def stock_row_from(raw: dict[str, Any]) -> WarehouseStockRow | None:
    warehouse = _uuid(raw.get("Sklad_ID"))
    if warehouse is None:
        return None
    sklad, state = _obj(raw.get("Sklad")), _obj(raw.get("AktualniStav"))
    price = state.get("ZustatekJednotkaCena")
    return WarehouseStockRow(
        warehouse_id=warehouse,
        code=_s(sklad.get("Kod")),
        name=_s(sklad.get("Nazev")),
        qty=_dec(state.get("ZustatekMnozstvi")),
        reserved=_dec(raw.get("Rezervovano")),
        ordered=_dec(raw.get("Objednano")),
        expected=_dec(raw.get("PredpokladaneMnozstvi")),
        available=_dec(raw.get("DostupneMnozstvi")),
        unit_price=_dec(price) if price is not None else None,
    )


def _created(raw: dict[str, Any], *, reconciled: bool = False) -> ArticleCreated:
    unit: dict[str, Any] = raw["HlavniJednotka"] if isinstance(raw.get("HlavniJednotka"), dict) else {}
    return ArticleCreated(
        id=_required_uuid(raw.get("ID")),
        katalog=_s(raw.get("Katalog")) or "",
        nazev=_s(raw.get("Nazev")) or "",
        parent_id=_uuid(raw.get("NadrazenyArtikl_ID")),
        unit=_s(unit.get("Kod")),
        reconciled=reconciled,
    )


def supplier_code_from(raw: dict[str, Any]) -> SupplierCode | None:
    article_id, supplier_id, code = (
        _uuid(raw.get("Parent_ID")),
        _uuid(raw.get("Firma_ID")),
        _s(raw.get("DodavatelskyKod")),
    )
    if article_id is None or supplier_id is None or code is None:
        return None
    unit: dict[str, Any] = raw["Jednotka"] if isinstance(raw.get("Jednotka"), dict) else {}
    art_unit: dict[str, Any] = raw["ArtiklJednotka"] if isinstance(raw.get("ArtiklJednotka"), dict) else {}
    return SupplierCode(
        id=_uuid(raw.get("ID")),
        article_id=article_id,
        supplier_id=supplier_id,
        code=code,
        name=_s(raw.get("DodavatelskyNazev")),
        last_price=None if raw.get("PosledniCena") is None else _dec(raw.get("PosledniCena")),
        unit=_s(unit.get("Kod")),
        article_unit=_s(art_unit.get("Kod")),
        article_unit_qty=None if art_unit.get("Mnozstvi") is None else _dec(art_unit.get("Mnozstvi")),
    )


def _alive(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Money keeps deleted records and the API returns them (`Deleted: true`): on the TEST agenda 603 of 1104 unpaid
    issued invoices were deleted ones, and an invoice number existed twice (deleted + live, different customers,
    pilot 2026-10-31). Every read drops them; keys are matched case-insensitively (REST is PascalCase)."""
    return [r for r in rows if _ci(r).get("deleted") is not True]


def _newest_first(items: list[Any]) -> list[Any]:
    """The server has no `Order` argument (MONEY_API §2) — sort client-side."""
    return sorted(items, key=lambda i: (i.issued_on or date.min, i.number), reverse=True)


# ----- Phase 4c (#247, D33): received delivery note as a koncept -----

TEMPLATE_HEADER = (
    "CiselnaRada_ID",
    "Stredisko_ID",
    "DruhPohybu_ID",
    "DruhSkladovehoPohybu_ID",
    "Predkontace_ID",
    "RegistraceDPH_ID",
    "DruhDokladu_ID",
    "Group_ID",
    "Mena_ID",
)
NOTES_SCAN = 100  # received notes of a centre read for „Vybrať iný“ (no server-side ordering, MONEY_API §2)


def _rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    return [r for r in (value or []) if isinstance(r, dict)]


def _obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _koncept(raw: dict[str, Any]) -> bool:
    return raw.get("Faze") == 0 and raw.get("Schvaleno") is False


def note_created_from(raw: dict[str, Any], *, reconciled: bool) -> DeliveryNoteCreated:
    lines = []
    for item in _rows(raw.get("Polozky")):
        content = _obj(item.get("ObsahPolozky"))
        lines.append(
            DeliveryNoteLineBack(
                id=_uuid(item.get("ID")),
                number=_int(item.get("CisloPolozky")),
                order=_int(item.get("Poradi")),
                qty=_dec(item.get("Mnozstvi")),
                unit_price=_dec(item.get("JednCena")),
                content_type=_int(item.get("TypObsahu")),
                article_id=_uuid(content.get("Artikl_ID")),
                warehouse_id=_uuid(content.get("Sklad_ID")),
                centre_id=_uuid(item.get("Stredisko_ID")),
            )
        )
    lines.sort(key=lambda ln: (ln.order or 0, ln.number or 0))
    return DeliveryNoteCreated(
        id=_required_uuid(raw.get("ID")),
        number=_s(raw.get("CisloDokladu")),
        faze=_int(raw.get("Faze")),
        schvaleno=raw.get("Schvaleno"),
        group_id=_uuid(raw.get("Group_ID")),
        centre_id=_uuid(raw.get("Stredisko_ID")),
        total_base=_dec(raw.get("SumaZaklad")),
        total=_dec(raw.get("CelkovaCastka")),
        address_empty=_s(raw.get("AdresaNazev")) is None,
        lines=lines,
        reconciled=reconciled,
        side_costs=_dec(raw.get("DodatecnePorizovaciNaklady")),
    )


def note_row_from(raw: dict[str, Any]) -> ReceivedNoteRow:
    firma = _obj(raw.get("Firma"))
    return ReceivedNoteRow(
        id=_required_uuid(raw.get("ID")),
        number=_s(raw.get("CisloDokladu")),
        supplier=_s(firma.get("Nazev")) or _s(raw.get("AdresaNazev")),
        issued_on=_date(raw.get("DatumVystaveni")),
        koncept=_koncept(raw),
        by_smart_mail=(_s(raw.get("Nazev")) or "").startswith(KONCEPT_PREFIX),
    )


def template_from(raw: dict[str, Any]) -> DeliveryNoteTemplate:
    """Header IDs + the first stock line (article + warehouse) + a text line's `TypObsahu` — only values Money has."""
    header = {k: str(v) for k in TEMPLATE_HEADER if (v := _uuid(raw.get(k))) is not None}
    line: dict[str, str | int] = {}
    text_line: dict[str, int] | None = None
    for item in _rows(raw.get("Polozky")):
        content = _obj(item.get("ObsahPolozky"))
        stock = _uuid(content.get("Artikl_ID")) is not None and _uuid(content.get("Sklad_ID")) is not None
        if stock and not line:
            for k in ("TypObsahu", "TypCeny", "DruhSazbyDPH"):
                if item.get(k) is not None:
                    line[k] = int(item[k])
            for k in ("DruhPolozky_ID", "SazbaDPH_ID"):
                if (v := _uuid(item.get(k))) is not None:
                    line[k] = str(v)
            if item.get("DphSazba") is not None:  # the VAT % of SazbaDPH_ID — lines with another rate never get it
                line["DphSazba"] = format(_dec(item["DphSazba"]).normalize(), "f")
            if content.get("VazbaTypVazby") is not None:
                line["VazbaTypVazby"] = int(content["VazbaTypVazby"])
            # pilot 2026-11-24: without „Počet nadradenej položky“ Money refuses to save an edited line (must be > 0)
            for k in ("VazbaPocetNadrizene", "VazbaPocetPodrizene"):
                if content.get(k) is not None:
                    line[k] = format(_dec(content[k]).normalize(), "f")
            if "DruhPolozky_ID" not in line and (v := _uuid(content.get("DruhPolozky_ID"))) is not None:
                line["DruhPolozky_ID"] = str(v)
        elif not stock and text_line is None and item.get("TypObsahu") is not None:
            text_line = {"TypObsahu": int(item["TypObsahu"])}
    firma = _obj(raw.get("Firma"))
    return DeliveryNoteTemplate(
        id=_required_uuid(raw.get("ID")),
        number=_s(raw.get("CisloDokladu")),
        supplier=_s(firma.get("Nazev")),
        issued_on=_date(raw.get("DatumVystaveni")),
        centre_id=_uuid(raw.get("Stredisko_ID")),
        header=header,
        line=line,
        text_line=text_line,
    )


class ApiBackend:
    def __init__(self, settings: BridgeSettings, http: httpx.AsyncClient | None = None) -> None:
        if not (settings.money_base_url and settings.money_client_id and settings.money_client_secret):
            raise RuntimeError("MONEY_BASE_URL / MONEY_CLIENT_ID / MONEY_CLIENT_SECRET missing")
        self._own_http = http is None
        self._http = http or httpx.AsyncClient(timeout=TIMEOUT)
        tokens = TokenProvider(
            self._http,
            settings.money_base_url,
            settings.money_client_id,
            settings.money_client_secret.get_secret_value(),
            settings.money_scope,
        )
        self._money = MoneyHttp(self._http, tokens, settings.money_base_url, settings.money_rest_version)
        self._page = max(1, min(settings.money_page_size, 500))

    async def aclose(self) -> None:
        if self._own_http:
            await self._http.aclose()

    async def _list(
        self,
        query: str,
        root: str,
        *,
        filter_: str | None = None,
        start: int = 0,
        count: int | None = None,
        since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        variables: dict[str, Any] = {"from": start, "count": min(count or self._page, self._page)}
        if filter_:
            variables["filter"] = filter_
        if since is not None:
            variables["changeFrom"] = since.isoformat()
        return _alive(await self._raw(query, root, variables))

    async def _raw(self, query: str, root: str, variables: dict[str, Any]) -> list[dict[str, Any]]:
        data = await self._money.graphql(query, variables)
        rows = data.get(root) or []
        if not isinstance(rows, list):
            raise MoneyError(f"{root}: not a list")
        return [r for r in rows if isinstance(r, dict)]

    async def _page_rows(
        self,
        query: str,
        root: str,
        *,
        filter_: str | None = None,
        start: int,
        count: int,
        since: datetime | None = None,
    ) -> tuple[list[dict[str, Any]], int | None]:
        """A page without deleted rows + the next offset computed from the RAW page size (dropping deleted rows must
        not end the paging early)."""
        variables: dict[str, Any] = {"from": start, "count": count}
        if filter_:
            variables["filter"] = filter_
        if since is not None:
            variables["changeFrom"] = since.isoformat()
        raw = await self._raw(query, root, variables)
        return _alive(raw), (start + len(raw) if len(raw) == count else None)

    async def _all(self, query: str, root: str, filter_: str) -> list[dict[str, Any]]:
        """Every page of a filtered read, at most `STOCK_LIMIT` rows (the catalog asks for ≤ 100 articles)."""
        out: list[dict[str, Any]] = []
        start: int | None = 0
        while start is not None and start < STOCK_LIMIT:
            rows, start = await self._page_rows(query, root, filter_=filter_, start=start, count=self._page)
            out.extend(rows)
        return out

    async def version(self) -> str:
        return str((await self._money.graphql("version")).get("Version") or "")

    async def companies(self, since: datetime | None, start: int, count: int) -> CompanyPage:
        count = min(count, self._page)
        rows, next_from = await self._page_rows("companies", "Companies", start=start, count=count, since=since)
        return CompanyPage(items=[company_from(r) for r in rows], next_from=next_from)

    async def company(self, company_id: uuid.UUID) -> Company | None:
        raw = (await self._money.graphql("company", {"id": str(company_id)})).get("Company")
        return company_from(raw) if isinstance(raw, dict) and raw.get("ID") and _alive([raw]) else None

    async def persons(self, since: datetime | None, start: int, count: int) -> PersonPage:
        """REST paging `/Person/{from}/{count}` needs no filter. `since` is ignored (full list): REST filters do not
        work (probe 2026-10-31), so the cache sync treats persons as a full refresh."""
        count = min(count, self._page)
        rows = _rest_rows(await self._money.rest_json(f"Person/{start}/{count}") or [])
        items = [person_from(r) for r in _alive(rows)]
        return PersonPage(items=items, next_from=start + len(rows) if len(rows) == count else None)

    async def codebook(self, name: CodebookName, start: int, count: int) -> CodebookPage:
        if name == "activity-types":
            return await self._activity_types(start, count)
        query, root = CODEBOOK_QUERIES[name]
        count = min(count, self._page)
        rows, next_from = await self._page_rows(query, root, start=start, count=count)
        items = [
            CodebookItem(id=_required_uuid(r.get("ID")), code=_s(r.get("Kod")), name=_s(r.get("Nazev"))) for r in rows
        ]
        return CodebookPage(items=items, next_from=next_from)

    async def _invoices(self, filter_: str, count: int = SEARCH_LIMIT) -> list[IssuedInvoice]:
        rows = await self._list("issued_invoices", "IssuedInvoices", filter_=filter_, count=count)
        return _newest_first([invoice_from(r) for r in rows])

    async def search_invoices(self, query: InvoiceQuery) -> InvoiceSearch:
        """MONEY_API §5.1 cascade on GraphQL `IssuedInvoices`. Proformas are REST-only and REST filters do not work
        (probe 2026-10-31), so proformas are not searched on the API backend."""
        steps: list[tuple[MatchedBy, str]] = []
        if query.number:
            steps.append(("number", cond("CisloDokladu", "eq", query.number)))
        if query.variable_symbol:
            steps.append(("variable_symbol", cond("VariabilniSymbol", "eq", query.variable_symbol)))
        if query.reference:
            steps.append(("reference", cond("Odkaz", "eq", query.reference)))
        if query.company_id and query.date_from and query.date_to:
            steps.append(
                (
                    "company_dates",
                    all_(
                        cond("Firma_ID", "eq", query.company_id),
                        cond("DatumVystaveni", "gte", query.date_from),
                        cond("DatumVystaveni", "lte", query.date_to),
                    ),
                )
            )
        digits = "".join(c for c in (query.number or "") if c.isdigit())
        if digits and digits != query.number:
            steps.append(("number_digits", cond("CisloDokladu", "ct", digits)))
        if query.order:
            # #210 / #217: the customer's order number is written in the invoice „Popis“ (Nazev) or „Poznámka“
            # (Poznamka), e.g. „Objednávka OR06024026“
            order = any_(cond("Nazev", "ct", query.order), cond("Poznamka", "ct", query.order))
            steps.append(
                ("order", all_(cond("Firma_ID", "eq", query.company_id), order) if query.company_id else order)
            )
        for matched_by, filter_ in steps:
            # a company + date window can hold more than 20 invoices; the server cannot sort, so fetch the whole
            # (bounded) window and sort here — „the latest invoice“ (#182) must not depend on the server's order
            found = await self._invoices(filter_, HISTORY_LIMIT if matched_by == "company_dates" else SEARCH_LIMIT)
            if found:
                return InvoiceSearch(matched_by=matched_by, items=found)
        return InvoiceSearch(matched_by="none", items=[])

    async def receivables(self, company_id: uuid.UUID) -> list[IssuedInvoice]:
        filter_ = all_(cond("Firma_ID", "eq", company_id), cond("UhradyZbyva", "gt", Decimal("0")))
        rows = await self._list("issued_invoices", "IssuedInvoices", filter_=filter_, count=HISTORY_LIMIT)
        return _newest_first([invoice_from(r) for r in rows])

    async def overdue(self, before: date, start: int, count: int) -> OverduePage:
        """MONEY_API §5.2 for all customers: `UhradyZbyva~gt~0#DatumSplatnosti~lt~<date>`, paged."""
        count = min(count, self._page)
        filter_ = all_(cond("UhradyZbyva", "gt", Decimal("0")), cond("DatumSplatnosti", "lt", before))
        rows, next_from = await self._page_rows(
            "issued_invoices", "IssuedInvoices", filter_=filter_, start=start, count=count
        )
        return OverduePage(items=[invoice_from(r) for r in rows], next_from=next_from)

    async def orders(self, company_id: uuid.UUID, since: date) -> list[Order]:
        filter_ = all_(cond("Firma_ID", "eq", company_id), cond("DatumVystaveni", "gte", since))
        rows = await self._list("received_orders", "ReceivedOrders", filter_=filter_, count=HISTORY_LIMIT)
        return _newest_first([order_from(r) for r in rows])

    async def deliveries(self, company_id: uuid.UUID, since: date) -> list[Delivery]:
        filter_ = all_(cond("Firma_ID", "eq", company_id), cond("DatumVystaveni", "gte", since))
        rows = await self._list("issued_delivery_notes", "IssuedDeliveryNotes", filter_=filter_, count=HISTORY_LIMIT)
        return _newest_first([delivery_from(r) for r in rows])

    async def search_deliveries(self, query: DeliveryQuery) -> DeliverySearch:
        """#222 `IssuedDeliveryNotes`: number → the customer's order in „Popis“ OR „Poznámka“ (+ `Firma_ID`) → the
        company's latest (≤ 400 days, whole window, sorted here — the server cannot sort). Deleted rows dropped."""
        steps: list[tuple[DeliveryMatchedBy, str, int]] = []
        if query.number:
            steps.append(("number", cond("CisloDokladu", "eq", query.number), SEARCH_LIMIT))
        if query.order:
            order = any_(cond("Nazev", "ct", query.order), cond("Poznamka", "ct", query.order))
            by_order = all_(cond("Firma_ID", "eq", query.company_id), order) if query.company_id else order
            steps.append(("order", by_order, SEARCH_LIMIT))
        if query.company_id and not query.number and not query.order:
            since = date.today() - timedelta(days=LATEST_DELIVERY_DAYS)
            latest = all_(cond("Firma_ID", "eq", query.company_id), cond("DatumVystaveni", "gte", since))
            steps.append(("company", latest, HISTORY_LIMIT))
        for matched_by, filter_, count in steps:
            rows = await self._list("issued_delivery_notes", "IssuedDeliveryNotes", filter_=filter_, count=count)
            found = _newest_first([delivery_from(r) for r in rows])
            if found:
                return DeliverySearch(matched_by=matched_by, items=found)
        return DeliverySearch(matched_by="none", items=[])

    async def document_pdf(
        self, kind: DocumentKind, record_id: uuid.UUID, report_id: str, design_id: str | None
    ) -> bytes | None:
        """#222 Money's own print report through `/pdfreport` (read only, also on PROD)."""
        return await self._money.pdfreport(PDFREPORT_OBJECTS[kind], record_id, report_id, design_id)

    async def activities(self, company_id: uuid.UUID) -> list[Activity]:
        raise WaitingForProbe("REST Activity list: REST filters do not work (probe 2026-10-31)")

    async def _activity_types(self, start: int, count: int) -> CodebookPage:
        """REST `TypeOfActivity/{from}/{count}` (no filter needed; swagger v1/v2)."""
        count = min(count, self._page)
        rows = _rest_rows(await self._money.rest_json(f"TypeOfActivity/{start}/{count}") or [])
        items = [codebook_item_from_rest(r) for r in _alive(rows)]
        return CodebookPage(items=items, next_from=start + len(rows) if len(rows) == count else None)

    async def create_activity(self, activity: ActivityIn) -> ActivityOut:
        """Not enabled: the required fields of `ActivityInputDto` are unconfirmed and the SMID duplicate check
        cannot use a REST filter (filters do not work, probe 2026-10-31). Never guessed (CLAUDE.md §7); a mutation
        is never retried. Erik approves a write test on the TEST agenda first (#176)."""
        raise WaitingForProbe("REST Activity create (required fields, SMID filter)")

    async def invoice_pdf(self, kind: InvoiceKind, invoice_id: uuid.UUID, report_id: str) -> bytes | None:
        """The original Money PDF (never rendered by Smart Mail, DOCUMENTS_SPEC §6). `report_id` comes from
        Settings 13b in the main app."""
        return await self._money.rest_bytes(f"{REPORT_PATHS[kind]}/{invoice_id}/Report/{report_id}")

    # ----- Phase 4b (read-only): item matching (MONEY_API §5.5.3) -----

    async def articles(self, query: ArticleQuery) -> list[Article]:
        if query.ean:
            filter_ = cond("CarovyKod", "eq", query.ean)
        elif query.code:
            filter_ = any_(cond("Kod", "eq", query.code), cond("Katalog", "eq", query.code))
        elif query.text and wildcard.is_wildcard(query.text):
            # `%mat%4%934` like in Money S4: every piece in the name (AND in Money), then their order checked here
            pieces = wildcard.parts(query.text)
            if not pieces:
                return []
            filter_ = all_(*(cond("Nazev", "ct", p) for p in dict.fromkeys(pieces)))
            rows = await self._list("articles", "Articles", filter_=filter_, count=WILDCARD_SCAN)
            found = [a for a in (article_from(r) for r in rows) if wildcard.in_order(a.name, pieces)]
            return found[: query.limit or WILDCARD_LIMIT]
        elif query.text:
            filter_ = any_(cond("Nazev", "ct", query.text), cond("Katalog", "ct", query.text))
        else:
            return []
        rows = await self._list("articles", "Articles", filter_=filter_, count=query.limit or ARTICLE_LIMIT)
        return [article_from(r) for r in rows]

    async def catalog_info(self, article_ids: list[uuid.UUID]) -> list[ArticleCatalogInfo]:
        """W6h Katalóg: stock per warehouse (`WarehouseStocks`) and the e-shop flag (`EShopArticles`) of up to
        `CATALOG_INFO_MAX` articles — two reads with an OR of the article ids, read only (D18)."""
        if not article_ids:
            return []
        ids = list(dict.fromkeys(article_ids))
        filter_ = any_(*(cond("Artikl_ID", "eq", a) for a in ids))
        stock_rows = await self._all("warehouse_stocks", "WarehouseStocks", filter_)
        eshop_rows = await self._all("eshop_articles", "EShopArticles", filter_)
        eshop = {_uuid(r.get("Artikl_ID")) for r in eshop_rows}
        stocks: dict[uuid.UUID, list[WarehouseStockRow]] = {a: [] for a in ids}
        for r in stock_rows:
            article = _uuid(r.get("Artikl_ID"))
            row = stock_row_from(r)
            if article in stocks and row is not None:
                stocks[article].append(row)
        return [
            ArticleCatalogInfo(
                article_id=a, eshop=a in eshop, stocks=sorted(stocks[a], key=lambda s: (s.code or "", s.name or ""))
            )
            for a in ids
        ]

    async def article_variants(self, parent_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Article]]:
        """#233 variants of up to 10 main cards in one call: `(NadrazenyArtikl_ID~eq~A)|(NadrazenyArtikl_ID~eq~B)`.
        Deleted rows are dropped, hidden ones come as `inactive`."""
        out: dict[uuid.UUID, list[Article]] = {p: [] for p in parent_ids}
        if not parent_ids:
            return out
        filter_ = any_(*(cond("NadrazenyArtikl_ID", "eq", p) for p in parent_ids))
        rows = await self._list("articles", "Articles", filter_=filter_, count=VARIANT_LIMIT)
        for a in (article_from(r) for r in rows):
            if a.parent_id in out:
                out[a.parent_id].append(a)
        return out

    async def article_by_catalog(self, katalog: str) -> Article | None:
        """D32: the (not deleted) article with exactly this catalog number, or None."""
        row = await self._catalog_row(katalog)
        return article_from(row) if row else None

    async def _catalog_row(self, katalog: str) -> dict[str, Any] | None:
        rows = await self._raw("article_by_catalog", "Articles", {"filter": cond("Katalog", "eq", katalog)})
        alive = [r for r in _alive(rows) if _s(r.get("Katalog")) == katalog]
        return alive[0] if alive else None

    async def create_article(self, article: ArticleCreateIn) -> ArticleCreated:
        """D32 / MONEY_API 5.5.8b: the catalog must be free right before the mutation (else `CatalogExists`); the
        payload holds only Katalog, Nazev, Poznamka (SMID) and NadrazenyArtikl_ID for a variant. Never retried: after an
        error or a timeout the catalog is looked up ONCE — a card carrying this SMID is the one just created
        (`reconciled`), anything else is an error. A repeat with the same SMID returns that card. Read back."""
        smid = f"SMID:{article.smid}"
        existing = await self._catalog_row(article.katalog)
        if existing is not None:
            if smid in (_s(existing.get("Poznamka")) or ""):
                return _created(existing, reconciled=True)  # a repeat of our own earlier create (same SMID)
            raise CatalogExists(article.katalog, _s(existing.get("Nazev")) or "")
        payload: dict[str, Any] = {
            "Katalog": article.katalog,
            "Nazev": article.nazev,
            "Poznamka": f"{smid} · Smart Mail",
        }
        if article.parent_id is not None:
            payload["NadrazenyArtikl_ID"] = str(article.parent_id)
        try:
            data = await self._money.graphql("create_article", {"a": payload})
            created = data.get("CreateArticle")
            new_id = _uuid(created.get("ID")) if isinstance(created, dict) else None
            if new_id is None:
                raise MoneyError("CreateArticle returned no ID")
        except (MoneyError, MoneyUnavailable):
            found = await self._catalog_row(article.katalog)  # reconciliation — once, never a second create
            if found is None or smid not in (_s(found.get("Poznamka")) or ""):
                raise
            return _created(found, reconciled=True)
        back = await self.article(new_id)  # read back what Money stored
        if back is None:
            raise MoneyError("created article not found on read-back")
        return ArticleCreated(
            id=back.id,
            katalog=back.catalog or article.katalog,
            nazev=back.name,
            parent_id=back.parent_id,
            unit=back.unit,
        )

    # ----- Phase 4c (#247, D33): received delivery note as a koncept -----

    async def _note_by_smid(self, smid: str) -> dict[str, Any] | None:
        rows = await self._raw(
            "received_delivery_notes", "ReceivedDeliveryNotes", {"filter": cond("Poznamka", "ct", smid), "count": 5}
        )
        alive = [r for r in _alive(rows) if smid in (_s(r.get("Poznamka")) or "")]
        return alive[0] if alive else None

    async def _note_back(self, note_id: uuid.UUID, *, reconciled: bool) -> DeliveryNoteCreated:
        raw = (await self._money.graphql("received_delivery_note", {"id": str(note_id)})).get("ReceivedDeliveryNote")
        if not isinstance(raw, dict) or not raw.get("ID"):
            raise MoneyError("created note not found on read-back")
        return note_created_from(raw, reconciled=reconciled)

    async def _address(self, company_id: uuid.UUID) -> dict[str, Any]:
        """MONEY_API 5.5.7 fallback: the supplier address from the Money company card — never from the PDF."""
        raw = (await self._money.graphql("company_address", {"id": str(company_id)})).get("Company")
        if not isinstance(raw, dict):
            raise MoneyError("supplier card not found")
        values = {
            "AdresaNazev": _s(raw.get("ObchNazev")) or _s(raw.get("Nazev")),
            "AdresaUlice": _s(raw.get("ObchUlice")),
            "AdresaMisto": _s(raw.get("ObchMisto")),
            "AdresaPSC": _s(raw.get("ObchPsc")),
            "AdresaStat_ID": _s(_uuid(raw.get("ObchStat_ID"))),
            "IC": _s(raw.get("ICO")),
            "DIC": _s(raw.get("DIC")),
            "ICDPH": _s(raw.get("ICDPH")),
        }
        return {k: v for k, v in values.items() if v is not None}

    async def create_delivery_note(self, note: DeliveryNoteIn) -> DeliveryNoteCreated:
        """D33 / MONEY_API 5.5.7 `CreateReceivedDeliveryNote` as a koncept (`Faze` 0, `Schvaleno` false). Before the
        mutation: a note with this SMID → returned (`reconciled`); a note of the same supplier + `Odkaz` →
        `DuplicateNote` (DL-B3). Never retried: after an error or a timeout the SMID is looked up ONCE. Read back."""
        smid = f"SMID:{note.smid}"
        mine = await self._note_by_smid(smid)
        if mine is not None:
            return await self._note_back(_required_uuid(mine.get("ID")), reconciled=True)
        dupes = await self._raw(
            "received_delivery_notes",
            "ReceivedDeliveryNotes",
            {"filter": all_(cond("Firma_ID", "eq", note.Firma_ID), cond("Odkaz", "eq", note.Odkaz)), "count": 5},
        )
        dupes = [r for r in _alive(dupes) if _s(r.get("Odkaz")) == note.Odkaz]
        if dupes:
            raise DuplicateNote(_s(dupes[0].get("CisloDokladu")))
        payload = note.money_input()
        if note.with_address:
            payload.update(await self._address(note.Firma_ID))
        try:
            data = await self._money.graphql("create_received_delivery_note", {"dl": payload})
            created = data.get("CreateReceivedDeliveryNote")
            new_id = _uuid(created.get("ID")) if isinstance(created, dict) else None
            if new_id is None:
                raise MoneyError("CreateReceivedDeliveryNote returned no ID")
        except (MoneyError, MoneyUnavailable):
            found = await self._note_by_smid(smid)  # reconciliation — once, never a second create
            if found is None:
                raise
            return await self._note_back(_required_uuid(found.get("ID")), reconciled=True)
        return await self._note_back(new_id, reconciled=False)

    async def received_notes(self, centre_id: uuid.UUID, count: int) -> list[ReceivedNoteRow]:
        """Settings 11e „Vybrať iný“: the newest received delivery notes of a centre (sorted here — no server order)."""
        rows = await self._raw(
            "received_delivery_notes",
            "ReceivedDeliveryNotes",
            {"filter": cond("Stredisko_ID", "eq", centre_id), "count": NOTES_SCAN},
        )
        alive = _alive(rows)
        alive.sort(key=lambda r: (_s(r.get("Create_Date")) or "", _s(r.get("CisloDokladu")) or ""), reverse=True)
        return [note_row_from(r) for r in alive[:count]]

    async def delivery_note_template(self, note_id: uuid.UUID) -> DeliveryNoteTemplate | None:
        raw = (await self._money.graphql("received_delivery_note_template", {"id": str(note_id)})).get(
            "ReceivedDeliveryNote"
        )
        if not isinstance(raw, dict) or not raw.get("ID") or not _alive([raw]):
            return None
        return template_from(raw)

    async def article(self, article_id: uuid.UUID) -> Article | None:
        raw = (await self._money.graphql("article", {"id": str(article_id)})).get("Article")
        return article_from(raw) if isinstance(raw, dict) and raw.get("ID") and _alive([raw]) else None

    async def supplier_codes(self, supplier_id: uuid.UUID, start: int, count: int) -> SupplierCodePage:
        count = min(count, self._page)
        rows, next_from = await self._page_rows(
            "article_suppliers",
            "ArticleSuppliers",
            filter_=cond("Firma_ID", "eq", supplier_id),
            start=start,
            count=count,
        )
        items = [c for c in (supplier_code_from(r) for r in rows) if c is not None]
        return SupplierCodePage(items=items, next_from=next_from)

    async def all_supplier_codes(self, since: datetime | None, start: int, count: int) -> SupplierCodePage:
        """#228 read cache: every `ArticleSuppliers` row, no supplier filter, `ChangeFrom` delta (deleted dropped)."""
        count = min(count, self._page)
        rows, next_from = await self._page_rows(
            "article_suppliers", "ArticleSuppliers", start=start, count=count, since=since
        )
        items = [c for c in (supplier_code_from(r) for r in rows) if c is not None]
        return SupplierCodePage(items=items, next_from=next_from)

    async def all_articles(self, since: datetime | None, start: int, count: int) -> ArticlePage:
        """W6h Katalóg read cache: every `Articles` row, `ChangeFrom` delta, paged (deleted rows dropped)."""
        count = min(count, self._page)
        rows, next_from = await self._page_rows("articles", "Articles", start=start, count=count, since=since)
        return ArticlePage(items=[article_from(r) for r in rows], next_from=next_from)

    async def lookup_supplier_code(self, supplier_id: uuid.UUID, code: str) -> list[SupplierCode]:
        """#228 fallback for a code the cache does not know yet: `Firma_ID~eq~X#DodavatelskyKod~eq~<code>`."""
        filter_ = all_(cond("Firma_ID", "eq", supplier_id), cond("DodavatelskyKod", "eq", code))
        rows = await self._list("article_suppliers", "ArticleSuppliers", filter_=filter_, count=SEARCH_LIMIT)
        return [c for c in (supplier_code_from(r) for r in rows) if c is not None]
