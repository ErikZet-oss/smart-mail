"""Read endpoints of the bridge (MONEY_API §6, Phase 3). All need HMAC; there is no generic GraphQL proxy."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.backend import InvoiceQuery, MoneyBackend
from app.filters import UNSAFE, UnsafeFilterValue
from app.models import (
    Activity,
    CodebookName,
    CodebookPage,
    Company,
    CompanyPage,
    Delivery,
    InvoiceKind,
    InvoiceSearch,
    IssuedInvoice,
    Order,
    PersonPage,
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
    company_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> InvoiceSearch:
    for name, value in (("number", number), ("vs", vs), ("reference", reference)):
        if value and any(c in UNSAFE for c in value):
            raise UnsafeFilterValue(name)  # same answer from the mock and from Money
    query = InvoiceQuery(
        number=(number or "").strip() or None,
        variable_symbol=(vs or "").strip() or None,
        reference=(reference or "").strip() or None,
        company_id=company_id,
        date_from=date_from,
        date_to=date_to,
    )
    if not (query.number or query.variable_symbol or query.reference or query.company_id):
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
