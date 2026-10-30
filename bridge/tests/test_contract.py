"""One contract suite for the mock (CI) and the real Money TEST agenda (`pytest --money-live`, CLAUDE.md §0.1).

Assertions only use the response models and relations between endpoints, never mock-specific values.
"""

from __future__ import annotations

from decimal import Decimal

from app.models import CodebookPage, Company, CompanyPage, InvoiceSearch, IssuedInvoice, PersonPage
from tests.conftest import SignedClient


def _first_company(client: SignedClient) -> Company:
    page = CompanyPage.model_validate(client.get("/sync/companies?count=5").json())
    assert page.items, "the agenda has no companies"
    return page.items[0]


def test_contract_company_sync_and_detail(contract_client: SignedClient) -> None:
    first = _first_company(contract_client)
    detail = contract_client.get(f"/companies/{first.id}")
    assert detail.status_code == 200
    assert Company.model_validate(detail.json()).id == first.id


def test_contract_paging_has_no_gaps(contract_client: SignedClient) -> None:
    one = CompanyPage.model_validate(contract_client.get("/sync/companies?count=2").json())
    if one.next_from is None:
        return
    two = CompanyPage.model_validate(contract_client.get(f"/sync/companies?from={one.next_from}&count=2").json())
    assert not {c.id for c in one.items} & {c.id for c in two.items}


def test_contract_unknown_company_is_404(contract_client: SignedClient) -> None:
    r = contract_client.get("/companies/00000000-0000-4000-8000-00000000dead")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "not_found"


def test_contract_persons_and_codebooks(contract_client: SignedClient) -> None:
    PersonPage.model_validate(contract_client.get("/sync/persons?count=5").json())
    for name in ("warehouses", "centres", "numerical-series", "currencies"):
        page = CodebookPage.model_validate(contract_client.get(f"/sync/codebooks/{name}?count=50").json())
        assert all(item.id for item in page.items)


def test_contract_receivables_belong_to_the_company(contract_client: SignedClient) -> None:
    company = _first_company(contract_client)
    rows = [IssuedInvoice.model_validate(r) for r in contract_client.get(f"/companies/{company.id}/receivables").json()]
    assert all(r.company_id == company.id and r.remaining > Decimal("0") for r in rows)


def test_contract_invoice_search_finds_by_number(contract_client: SignedClient) -> None:
    for company in CompanyPage.model_validate(contract_client.get("/sync/companies?count=20").json()).items:
        rows = contract_client.get(f"/companies/{company.id}/receivables").json()
        if rows:
            invoice = IssuedInvoice.model_validate(rows[0])
            break
    else:
        return  # nothing open on this agenda
    found = InvoiceSearch.model_validate(contract_client.get(f"/invoices/issued/search?number={invoice.number}").json())
    assert found.matched_by == "number" and invoice.id in {i.id for i in found.items}
    assert all(i.number == invoice.number for i in found.items)


def test_contract_search_needs_criteria_and_rejects_unsafe_values(contract_client: SignedClient) -> None:
    assert contract_client.get("/invoices/issued/search").status_code == 422
    r = contract_client.get("/invoices/issued/search?number=FV1%23Firma_ID~ne~x")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unsafe_filter_value"


def test_contract_orders_and_deliveries_shape(contract_client: SignedClient) -> None:
    company = _first_company(contract_client)
    for path in ("orders", "deliveries"):
        r = contract_client.get(f"/companies/{company.id}/{path}?since=2020-01-01")
        assert r.status_code == 200
        assert all(row["company_id"] == str(company.id) for row in r.json())
        assert all(isinstance(row["total"], str) for row in r.json())  # Decimal as string, never a float


def test_contract_pdf_report_id_is_validated(contract_client: SignedClient) -> None:
    r = contract_client.get("/invoices/issued/invoice/00000000-0000-4000-8000-00000000dead/pdf?report_id=x;y")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "report_id_invalid"
