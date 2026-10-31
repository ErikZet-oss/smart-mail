"""Money S4 backend over the official API (MONEY_BACKEND=api). Read-only.

Only GraphQL list/detail queries from `queries/*.graphql` and the REST calls whose shape is in the swagger files.
REST list filters (`Filters`, `PropertyName`, `Operation`, `ExpectedValue`) have no documented syntax in the swagger,
so calls that need them raise `WaitingForProbe` until `probe_output/report.md` confirms it (plan phase-3 › [PROBE]).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import httpx

from app.backend import InvoiceQuery, MoneyError, WaitingForProbe
from app.config import BridgeSettings
from app.filters import all_, cond
from app.gql_client import TIMEOUT, MoneyHttp, TokenProvider
from app.models import (
    Activity,
    ActivityIn,
    ActivityOut,
    CodebookItem,
    CodebookName,
    CodebookPage,
    Company,
    CompanyPage,
    Connection,
    Delivery,
    InvoiceKind,
    InvoiceSearch,
    IssuedInvoice,
    MatchedBy,
    Order,
    OverduePage,
    Person,
    PersonPage,
)

CODEBOOK_QUERIES: dict[str, tuple[str, str]] = {
    "warehouses": ("warehouses", "Warehouses"),
    "centres": ("centres", "Centres"),
    "numerical-series": ("numerical_series", "NumericalSeries"),
    "currencies": ("currencies", "Currencies"),
}
REPORT_PATHS: dict[InvoiceKind, str] = {"invoice": "IssuedInvoice", "proforma": "PrepaymentIssuedInvoice"}
SEARCH_LIMIT = 20
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
    )


def person_from(raw: dict[str, Any]) -> Person:
    """REST `PersonOutputDto` (camelCase, swagger v1/v2)."""
    return Person(
        id=_required_uuid(raw.get("id")),
        company_id=_uuid(raw.get("parent_ID")),
        first_name=_s(raw.get("jmeno")),
        last_name=_s(raw.get("prijmeni")),
        name=_s(raw.get("nazev")),
        function=_s(raw.get("funkce")),
        email=_s(raw.get("email")),
        phone=_s(raw.get("tel1Cislo")),
    )


def _newest_first(items: list[Any]) -> list[Any]:
    """The server has no `Order` argument (MONEY_API §2) — sort client-side."""
    return sorted(items, key=lambda i: (i.issued_on or date.min, i.number), reverse=True)


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
        data = await self._money.graphql(query, variables)
        rows = data.get(root) or []
        if not isinstance(rows, list):
            raise MoneyError(f"{root}: not a list")
        return [r for r in rows if isinstance(r, dict)]

    async def version(self) -> str:
        return str((await self._money.graphql("version")).get("Version") or "")

    async def companies(self, since: datetime | None, start: int, count: int) -> CompanyPage:
        count = min(count, self._page)
        rows = await self._list("companies", "Companies", start=start, count=count, since=since)
        return CompanyPage(
            items=[company_from(r) for r in rows], next_from=start + len(rows) if len(rows) == count else None
        )

    async def company(self, company_id: uuid.UUID) -> Company | None:
        raw = (await self._money.graphql("company", {"id": str(company_id)})).get("Company")
        return company_from(raw) if isinstance(raw, dict) and raw.get("ID") else None

    async def persons(self, since: datetime | None, start: int, count: int) -> PersonPage:
        """REST paging `/Person/{from}/{count}` needs no filter. `since` is ignored (full list) — the REST delta
        syntax is [PROBE]; the cache sync treats persons as a full refresh."""
        count = min(count, self._page)
        rows = await self._money.rest_json(f"Person/{start}/{count}") or []
        if isinstance(rows, dict):  # some versions wrap lists
            rows = rows.get("Data") or rows.get("data") or rows.get("items") or []
        items = [person_from(r) for r in rows if isinstance(r, dict)]
        return PersonPage(items=items, next_from=start + len(rows) if len(rows) == count else None)

    async def codebook(self, name: CodebookName, start: int, count: int) -> CodebookPage:
        if name == "activity-types":
            return await self._activity_types(start, count)
        query, root = CODEBOOK_QUERIES[name]
        count = min(count, self._page)
        rows = await self._list(query, root, start=start, count=count)
        items = [
            CodebookItem(id=_required_uuid(r.get("ID")), code=_s(r.get("Kod")), name=_s(r.get("Nazev"))) for r in rows
        ]
        return CodebookPage(items=items, next_from=start + len(rows) if len(rows) == count else None)

    async def _invoices(self, filter_: str) -> list[IssuedInvoice]:
        rows = await self._list("issued_invoices", "IssuedInvoices", filter_=filter_, count=SEARCH_LIMIT)
        return _newest_first([invoice_from(r) for r in rows])

    async def search_invoices(self, query: InvoiceQuery) -> InvoiceSearch:
        """MONEY_API §5.1 cascade on GraphQL `IssuedInvoices`. Proformas (REST, filter syntax [PROBE]) are not
        searched on the API backend yet."""
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
        for matched_by, filter_ in steps:
            found = await self._invoices(filter_)
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
        rows = await self._list("issued_invoices", "IssuedInvoices", filter_=filter_, start=start, count=count)
        return OverduePage(
            items=[invoice_from(r) for r in rows], next_from=start + len(rows) if len(rows) == count else None
        )

    async def orders(self, company_id: uuid.UUID, since: date) -> list[Order]:
        filter_ = all_(cond("Firma_ID", "eq", company_id), cond("DatumVystaveni", "gte", since))
        rows = await self._list("received_orders", "ReceivedOrders", filter_=filter_, count=HISTORY_LIMIT)
        return _newest_first([order_from(r) for r in rows])

    async def deliveries(self, company_id: uuid.UUID, since: date) -> list[Delivery]:
        filter_ = all_(cond("Firma_ID", "eq", company_id), cond("DatumVystaveni", "gte", since))
        rows = await self._list("issued_delivery_notes", "IssuedDeliveryNotes", filter_=filter_, count=HISTORY_LIMIT)
        return _newest_first([delivery_from(r) for r in rows])

    async def activities(self, company_id: uuid.UUID) -> list[Activity]:
        raise WaitingForProbe("REST Activity filter by firma_ID")

    async def _activity_types(self, start: int, count: int) -> CodebookPage:
        """REST `TypeOfActivity/{from}/{count}` (no filter needed; swagger v1/v2)."""
        count = min(count, self._page)
        rows = await self._money.rest_json(f"TypeOfActivity/{start}/{count}") or []
        if isinstance(rows, dict):
            rows = rows.get("Data") or rows.get("data") or rows.get("items") or []
        items = [
            CodebookItem(id=_required_uuid(r.get("id")), code=_s(r.get("kod")), name=_s(r.get("nazev")))
            for r in rows
            if isinstance(r, dict)
        ]
        return CodebookPage(items=items, next_from=start + len(rows) if len(rows) == count else None)

    async def create_activity(self, activity: ActivityIn) -> ActivityOut:
        """The required fields of `ActivityInputDto` and the REST filter for the SMID check are [PROBE] — never
        guessed (CLAUDE.md §7); a mutation is never retried."""
        raise WaitingForProbe("REST Activity create (required fields, SMID filter)")

    async def invoice_pdf(self, kind: InvoiceKind, invoice_id: uuid.UUID, report_id: str) -> bytes | None:
        """The original Money PDF (never rendered by Smart Mail, DOCUMENTS_SPEC §6). `report_id` comes from
        Settings 13b in the main app."""
        return await self._money.rest_bytes(f"{REPORT_PATHS[kind]}/{invoice_id}/Report/{report_id}")
