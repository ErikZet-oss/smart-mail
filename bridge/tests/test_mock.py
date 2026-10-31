"""The mock seed is fictional (no real companies, IČO, mail domains) and stable."""

from __future__ import annotations

from datetime import date

from app.mock import CUSTOMERS, build, minimal_pdf
from tests.conftest import make_client


def _ico_valid(ico: str) -> bool:
    digits = [int(c) for c in ico]
    total = sum(d * w for d, w in zip(digits[:7], range(8, 1, -1), strict=True))
    return (11 - total % 11) % 10 == digits[7]


def test_seed_is_fictional_and_deterministic() -> None:
    data = build()
    assert len(data.companies) == CUSTOMERS and build().companies == data.companies
    for c in data.companies:
        assert "Fiktívna" in c.name and c.email and c.email.endswith(".example")
        assert c.ico and len(c.ico) == 8 and not _ico_valid(c.ico)
        assert all(conn.value.endswith(".example") for conn in c.connections if "@" in conn.value)
    assert all(p.email and p.email.endswith(".example") for p in data.persons)


def test_seed_has_overdue_paid_and_proformas() -> None:
    data = build()
    today = date(2026, 10, 1)
    assert any(i.remaining > 0 and i.due_on and i.due_on < today for i in data.invoices)
    assert any(i.remaining == 0 for i in data.invoices)
    assert any(i.kind == "proforma" for i in data.invoices)


def test_pdf_is_a_real_pdf() -> None:
    pdf = minimal_pdf("FIKTIVNY DOKLAD FV2600001 (x)")
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
    xref = int(pdf.rsplit(b"startxref\n", 1)[1].split(b"\n")[0])
    assert pdf[xref:].startswith(b"xref")


def test_mock_pdf_endpoint_and_kind() -> None:
    client = make_client()
    inv = next(i for i in build().invoices if i.kind == "invoice")
    r = client.get(f"/invoices/issued/invoice/{inv.id}/pdf?report_id=12")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    assert client.get(f"/invoices/issued/proforma/{inv.id}/pdf?report_id=12").status_code == 404


def test_mock_delta_sync_returns_nothing_after_the_seed() -> None:
    client = make_client()
    assert client.get("/sync/companies?since=2026-10-02T00:00:00Z").json()["items"] == []
    assert client.get("/sync/companies?since=2026-01-01T00:00:00Z").json()["items"]


def test_mock_activities_endpoint() -> None:
    client = make_client()
    company = next(a.company_id for a in build().activities)
    rows = client.get(f"/companies/{company}/activities").json()
    assert rows and all(r["company_id"] == str(company) for r in rows)


def test_182_company_window_returns_the_whole_window_not_20() -> None:
    from datetime import date as _date

    from tests.conftest import make_client

    client = make_client()
    companies = client.get("/sync/companies?count=50").json()["items"]
    best = None
    for c in companies:
        out = client.get(
            f"/invoices/issued/search?company_id={c['id']}&date_from=2020-01-01&date_to={_date(2030, 1, 1).isoformat()}"
        ).json()
        if best is None or len(out["items"]) > len(best["items"]):
            best = out
    assert best is not None and best["matched_by"] == "company_dates"
    assert len(best["items"]) > 20  # fictional seed: some customer has more than one page of 20
