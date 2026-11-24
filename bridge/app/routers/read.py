"""Read endpoints of the bridge (MONEY_API §6, Phase 3). All need HMAC; there is no generic GraphQL proxy."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.backend import ArticleQuery, DeliveryQuery, InvoiceQuery, MoneyBackend
from app.filters import UNSAFE, UnsafeFilterValue
from app.models import (
    Activity,
    Article,
    ArticleCatalogInfo,
    ArticlePage,
    CatalogArticle,
    CatalogFree,
    CodebookName,
    CodebookPage,
    Company,
    CompanyPage,
    Delivery,
    DeliveryNoteTemplate,
    DeliverySearch,
    DocumentKind,
    InvoiceKind,
    InvoiceSearch,
    IssuedInvoice,
    Order,
    OverduePage,
    PersonPage,
    ReceivedNoteRow,
    SupplierCode,
    SupplierCodePage,
)

router = APIRouter()

MAX_PAGE = 500
_REPORT_ID = re.compile(r"^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|\d{1,9})$")
_TEXT = Annotated[str | None, Query(max_length=60)]
Start = Annotated[int, Query(ge=0, alias="from")]
Count = Annotated[int, Query(ge=1, le=MAX_PAGE)]


def _backend(request: Request) -> MoneyBackend:
    backend: MoneyBackend = request.app.state.backend
    return backend


def _default_since() -> date:
    return date.today() - timedelta(days=365)


MIN_ORDER = 6


@router.get("/sync/companies")
async def sync_companies(
    request: Request, since: datetime | None = None, start: Start = 0, count: Count = 200
) -> CompanyPage:
    return await _backend(request).companies(since, start, count)


@router.get("/sync/persons")
async def sync_persons(
    request: Request, since: datetime | None = None, start: Start = 0, count: Count = 200
) -> PersonPage:
    return await _backend(request).persons(since, start, count)


@router.get("/sync/articles")
async def sync_articles(
    request: Request, since: datetime | None = None, start: Start = 0, count: Count = 200
) -> ArticlePage:
    """W6h Katalóg read cache of `Articles` (`ChangeFrom` delta, paged; deleted dropped, hidden = `inactive`)."""
    return await _backend(request).all_articles(since, start, count)


@router.get("/sync/article-suppliers")
async def sync_article_suppliers(
    request: Request, since: datetime | None = None, start: Start = 0, count: Count = 200
) -> SupplierCodePage:
    """#228 read cache of `ArticleSuppliers` for all suppliers (`ChangeFrom` delta, paged)."""
    return await _backend(request).all_supplier_codes(since, start, count)


@router.get("/sync/codebooks/{name}")
async def sync_codebook(request: Request, name: CodebookName, start: Start = 0, count: Count = 200) -> CodebookPage:
    return await _backend(request).codebook(name, start, count)


@router.get("/companies/{company_id}")
async def get_company(request: Request, company_id: uuid.UUID) -> Company:
    company = await _backend(request).company(company_id)
    if company is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    return company


@router.get("/companies/{company_id}/receivables")
async def company_receivables(request: Request, company_id: uuid.UUID) -> list[IssuedInvoice]:
    return await _backend(request).receivables(company_id)


@router.get("/receivables/overdue")
async def overdue_receivables(
    request: Request, before: date | None = None, start: Start = 0, count: Count = 200
) -> OverduePage:
    """W8b Upomienky: open invoices due before `before` (default today), all customers."""
    return await _backend(request).overdue(before or date.today(), start, count)


@router.get("/companies/{company_id}/orders")
async def company_orders(request: Request, company_id: uuid.UUID, since: date | None = None) -> list[Order]:
    return await _backend(request).orders(company_id, since or _default_since())


@router.get("/companies/{company_id}/deliveries")
async def company_deliveries(request: Request, company_id: uuid.UUID, since: date | None = None) -> list[Delivery]:
    return await _backend(request).deliveries(company_id, since or _default_since())


@router.get("/companies/{company_id}/activities")
async def company_activities(request: Request, company_id: uuid.UUID) -> list[Activity]:
    return await _backend(request).activities(company_id)


@router.get("/invoices/issued/search")
async def search_invoices(
    request: Request,
    number: _TEXT = None,
    vs: _TEXT = None,
    reference: _TEXT = None,
    order: _TEXT = None,
    company_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> InvoiceSearch:
    for name, value in (("number", number), ("vs", vs), ("reference", reference), ("order", order)):
        if value and any(c in UNSAFE for c in value):
            raise UnsafeFilterValue(name)  # same answer from the mock and from Money
    query = InvoiceQuery(
        number=(number or "").strip() or None,
        variable_symbol=(vs or "").strip() or None,
        reference=(reference or "").strip() or None,
        company_id=company_id,
        date_from=date_from,
        date_to=date_to,
        order=(order or "").strip() or None,
    )
    if query.order is not None and len(query.order) < MIN_ORDER:
        # #217: `ct` over the whole agenda — never for a short text like „OR12“
        raise HTTPException(status_code=422, detail={"code": "order_too_short", "min": MIN_ORDER})
    if not (query.number or query.variable_symbol or query.reference or query.company_id or query.order):
        raise HTTPException(status_code=422, detail={"code": "search_criteria_required"})
    return await _backend(request).search_invoices(query)


@router.get("/invoices/issued/{kind}/{invoice_id}/pdf")
async def invoice_pdf(request: Request, kind: InvoiceKind, invoice_id: uuid.UUID, report_id: str) -> Response:
    """The original Money PDF; `report_id` (GUID or report config id) comes from Settings 13b."""
    if not _REPORT_ID.match(report_id):
        raise HTTPException(status_code=422, detail={"code": "report_id_invalid"})
    pdf = await _backend(request).invoice_pdf(kind, invoice_id, report_id)
    if not pdf:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    return Response(content=pdf, media_type="application/pdf", headers={"Cache-Control": "no-store"})


# ----- #222 (read-only): issued delivery notes and their PDF through Money's `/pdfreport` -----


@router.get("/delivery-notes/issued/search")
async def search_delivery_notes(
    request: Request,
    number: _TEXT = None,
    order: _TEXT = None,
    company_id: uuid.UUID | None = None,
) -> DeliverySearch:
    for name, value in (("number", number), ("order", order)):
        if value and any(c in UNSAFE for c in value):
            raise UnsafeFilterValue(name)
    query = DeliveryQuery(
        number=(number or "").strip() or None, order=(order or "").strip() or None, company_id=company_id
    )
    if query.order is not None and len(query.order) < MIN_ORDER:
        raise HTTPException(status_code=422, detail={"code": "order_too_short", "min": MIN_ORDER})
    if not (query.number or query.order or query.company_id):
        raise HTTPException(status_code=422, detail={"code": "search_criteria_required"})
    return await _backend(request).search_deliveries(query)


@router.get("/documents/{kind}/{record_id}/pdf")
async def document_pdf(
    request: Request, kind: DocumentKind, record_id: uuid.UUID, report_id: str, design_id: str | None = None
) -> Response:
    """Money's own print report (`/pdfreport`, „tlač do PDF“) — `kind` is a whitelist, ids are validated; read
    only, so allowed on the PRODUCTION agenda as well (#212)."""
    if not _REPORT_ID.match(report_id) or (design_id and not _REPORT_ID.match(design_id)):
        raise HTTPException(status_code=422, detail={"code": "report_id_invalid"})
    pdf = await _backend(request).document_pdf(kind, record_id, report_id, design_id or None)
    if not pdf:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    return Response(content=pdf, media_type="application/pdf", headers={"Cache-Control": "no-store"})


# ----- Phase 4b (read-only): item matching of supplier documents (MONEY_API §5.5.3) -----


@router.get("/articles/search")
async def search_articles(
    request: Request,
    code: _TEXT = None,
    ean: _TEXT = None,
    q: _TEXT = None,
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
) -> list[Article]:
    """Exactly one of: `code` (Kod or Katalog, exact), `ean` (CarovyKod), `q` (name / catalog contains; with `%` the
    Money S4 pattern search in the name, e.g. `%mat%4%934`)."""
    for name, value in (("code", code), ("ean", ean), ("q", q)):
        if value and any(c in UNSAFE for c in value):
            raise UnsafeFilterValue(name)
    query = ArticleQuery(
        code=(code or "").strip() or None, ean=(ean or "").strip() or None, text=(q or "").strip() or None, limit=limit
    )
    if not (query.code or query.ean or (query.text and len(query.text) >= 2)):
        raise HTTPException(status_code=422, detail={"code": "search_criteria_required"})
    return await _backend(request).articles(query)


MAX_VARIANT_PARENTS = 10


@router.get("/articles/variants")
async def article_variants(
    request: Request, parent_id: Annotated[list[uuid.UUID], Query(min_length=1, max_length=MAX_VARIANT_PARENTS)]
) -> dict[str, list[Article]]:
    """#233 variants of up to 10 main cards (`NadrazenyArtikl_ID`), keyed by the main card id."""
    found = await _backend(request).article_variants(list(dict.fromkeys(parent_id)))
    return {str(k): v for k, v in found.items()}


@router.get("/articles/catalog-info")
async def article_catalog_info(
    request: Request, id: Annotated[list[uuid.UUID], Query(min_length=1, max_length=100)]
) -> list[ArticleCatalogInfo]:
    """W6h Katalóg: e-shop flag + stock per warehouse of up to 100 articles (information only — D18)."""
    return await _backend(request).catalog_info(list(dict.fromkeys(id)))


@router.get("/articles/catalog-free")
async def catalog_free(request: Request, katalog: Annotated[str, Query(min_length=1, max_length=50)]) -> CatalogFree:
    """D32: is this catalog number free in Money? (live check while the user types; checked again before the write)"""
    value = katalog.strip()
    if not value or any(c in UNSAFE for c in value):
        raise UnsafeFilterValue("katalog")
    found = await _backend(request).article_by_catalog(value)
    if found is None:
        return CatalogFree(free=True)
    return CatalogFree(free=False, article=CatalogArticle(katalog=found.catalog or value, nazev=found.name))


@router.get("/articles/{article_id}")
async def get_article(request: Request, article_id: uuid.UUID) -> Article:
    article = await _backend(request).article(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    return article


@router.get("/suppliers/{supplier_id}/article-codes/lookup")
async def supplier_article_code_lookup(
    request: Request, supplier_id: uuid.UUID, code: Annotated[str, Query(min_length=1, max_length=60)]
) -> list[SupplierCode]:
    """#228 one supplier code exactly as written on the document (the cache does not know it yet)."""
    if any(c in UNSAFE for c in code):
        raise UnsafeFilterValue("code")
    return await _backend(request).lookup_supplier_code(supplier_id, code.strip())


@router.get("/suppliers/{supplier_id}/article-codes")
async def supplier_article_codes(
    request: Request, supplier_id: uuid.UUID, start: Start = 0, count: Count = 500
) -> SupplierCodePage:
    return await _backend(request).supplier_codes(supplier_id, start, count)


# ----- Phase 4c (#247): branch template note for Settings 11e „Vzorový dodací list pobočky“ -----


@router.get("/delivery-notes/received")
async def received_notes(
    request: Request, centre_id: uuid.UUID, count: Annotated[int, Query(ge=1, le=50)] = 20
) -> list[ReceivedNoteRow]:
    """The newest received delivery notes of a centre (Číslo · Dodávateľ · Dátum) — read only."""
    backend: MoneyBackend = request.app.state.backend
    return await backend.received_notes(centre_id, count)


@router.get("/delivery-notes/received/{note_id}/template")
async def delivery_note_template(request: Request, note_id: uuid.UUID) -> DeliveryNoteTemplate:
    """Values copied from a template note (header IDs incl. `Group_ID`, first stock line, text line `TypObsahu`)."""
    backend: MoneyBackend = request.app.state.backend
    found = await backend.delivery_note_template(note_id)
    if found is None:
        raise HTTPException(status_code=404, detail={"code": "note_not_found"})
    return found
