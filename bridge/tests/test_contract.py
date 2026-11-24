"""One contract suite for the mock (CI) and the real Money TEST agenda (`pytest --money-live`, CLAUDE.md §0.1).

Assertions only use the response models and relations between endpoints, never mock-specific values.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from urllib.parse import urlencode

from app.models import (
    CodebookPage,
    Company,
    CompanyPage,
    DeliverySearch,
    InvoiceSearch,
    IssuedInvoice,
    OverduePage,
    PersonPage,
)
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


def test_contract_overdue_receivables(contract_client: SignedClient) -> None:
    page = OverduePage.model_validate(contract_client.get("/receivables/overdue?before=2026-10-01&count=50").json())
    assert all(i.remaining > Decimal("0") and i.due_on is not None and str(i.due_on) < "2026-10-01" for i in page.items)


def test_contract_222_delivery_note_search_and_pdf(contract_client: SignedClient) -> None:
    company = _first_company(contract_client)
    latest = DeliverySearch.model_validate(
        contract_client.get(f"/delivery-notes/issued/search?company_id={company.id}").json()
    )
    assert all(d.company_id == company.id for d in latest.items)
    dates = [d.issued_on for d in latest.items if d.issued_on]
    assert dates == sorted(dates, reverse=True)  # newest first
    if latest.items:
        note = latest.items[0]
        by_number = DeliverySearch.model_validate(
            contract_client.get(f"/delivery-notes/issued/search?number={note.number}").json()
        )
        assert by_number.matched_by == "number" and note.id in {d.id for d in by_number.items}
    assert contract_client.get("/delivery-notes/issued/search").status_code == 422
    assert contract_client.get("/delivery-notes/issued/search?order=OR12").status_code == 422
    assert contract_client.get("/delivery-notes/issued/search?number=DL%7C1").status_code == 422
    dead = "00000000-0000-4000-8000-00000000dead"
    for qs in ("report_id=x;y", "report_id=12&design_id=a%20b"):
        r = contract_client.get(f"/documents/issued_delivery_note/{dead}/pdf?{qs}")
        assert r.status_code == 422 and r.json()["detail"]["code"] == "report_id_invalid"
    assert contract_client.get(f"/documents/issued_invoice/{dead}/pdf?report_id=12").status_code == 422  # whitelist


def test_contract_228_article_supplier_sync_and_lookup(contract_client: SignedClient) -> None:
    from app.models import SupplierCode, SupplierCodePage

    page = SupplierCodePage.model_validate(contract_client.get("/sync/article-suppliers?count=5").json())
    assert len(page.items) <= 5 and all(c.id is not None for c in page.items)
    if page.items:
        first = page.items[0]
        found = [
            SupplierCode.model_validate(r)
            for r in contract_client.get(
                f"/suppliers/{first.supplier_id}/article-codes/lookup?{urlencode({'code': first.code})}"
            ).json()
        ]
        assert first.id in {c.id for c in found}
    sup = "00000000-0000-4000-8000-00000000dead"
    for bad in ("09150|1", "a~b", "(x)", "a#b"):
        r = contract_client.get(f"/suppliers/{sup}/article-codes/lookup?{urlencode({'code': bad})}")
        assert r.status_code == 422  # never reaches a filter


def test_contract_233_article_variants(contract_client: SignedClient) -> None:
    from app.models import Article

    variants = [
        Article.model_validate(r) for r in contract_client.get("/articles/search?q=Vrut").json() if r.get("parent_id")
    ]
    if variants:
        main = variants[0].parent_id
        out = contract_client.get(f"/articles/variants?parent_id={main}").json()
        rows = [Article.model_validate(r) for r in out[str(main)]]
        assert rows and all(a.parent_id == main for a in rows)
    eleven = "&".join(f"parent_id={uuid.uuid4()}" for _ in range(11))
    assert contract_client.get(f"/articles/variants?{eleven}").status_code == 422  # at most 10 main cards
    assert contract_client.get("/articles/variants").status_code == 422


def test_contract_catalog_info_and_search_limit(contract_client: SignedClient) -> None:
    """W6h Katalóg (pilot 2026-11-24): stock per warehouse + e-shop flag, read only; text search up to 100 rows."""
    from app.models import Article, ArticleCatalogInfo

    rows = [Article.model_validate(r) for r in contract_client.get("/articles/search?q=Vrut&limit=100").json()]
    if rows:
        ids = "&".join(f"id={a.id}" for a in rows[:5])
        info = [
            ArticleCatalogInfo.model_validate(r) for r in contract_client.get(f"/articles/catalog-info?{ids}").json()
        ]
        assert [i.article_id for i in info] == [a.id for a in rows[:5]]
        assert all(s.qty is not None for i in info for s in i.stocks)
    many = "&".join(f"id={uuid.uuid4()}" for _ in range(101))
    assert contract_client.get(f"/articles/catalog-info?{many}").status_code == 422  # at most 100 articles
    assert contract_client.get("/articles/catalog-info").status_code == 422
    assert contract_client.get("/articles/search?q=Vrut&limit=101").status_code == 422
