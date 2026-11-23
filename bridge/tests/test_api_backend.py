"""Real Money backend against a respx-mocked server: token, 401 retry, Decimal parsing, filters, mapping, errors."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx

from app.api_backend import ApiBackend
from app.backend import DeliveryQuery, InvoiceQuery, MoneyError, MoneyUnavailable, WaitingForProbe
from app.config import BridgeSettings

BASE = "https://money.test"
CID = uuid.UUID("11111111-1111-4111-8111-111111111111")
INV = {
    "ID": "22222222-2222-4222-8222-222222222222",
    "CisloDokladu": "FV2600042",
    "VariabilniSymbol": "2600042",
    "Firma_ID": str(CID),
    "DatumVystaveni": "2026-09-01T00:00:00",
    "DatumSplatnosti": "2026-09-15T00:00:00",
    "DatumUhrady": "0001-01-01T00:00:00",
    "CelkovaCastka": 123.45,
    "UhradyZbyva": 0.1,
    "Mena_ID": "00000000-0000-0000-0000-000000000000",
    "Odkaz": "",
    "TypDokladu": 0,
}


def settings() -> BridgeSettings:
    return BridgeSettings(
        money_backend="api",
        money_base_url=BASE,
        money_client_id="cid",
        money_client_secret="secret",  # type: ignore[arg-type]
        bridge_hmac_secret="hmac",  # type: ignore[arg-type]
    )


def _token(route: respx.Route, n: list[int]) -> None:
    def answer(_: httpx.Request) -> httpx.Response:
        n[0] += 1
        return httpx.Response(200, json={"access_token": f"t{n[0]}", "expires_in": 3600})

    route.side_effect = answer


def _gql(data: dict[str, Any]) -> httpx.Response:
    # numbers as raw JSON text so the client must parse them without floats
    return httpx.Response(
        200, content=json.dumps({"data": data}).encode(), headers={"content-type": "application/json"}
    )


@respx.mock
async def test_token_cached_single_flight_and_decimals() -> None:
    tokens = [0]
    _token(respx.post(f"{BASE}/connect/token"), tokens)
    respx.post(f"{BASE}/graphql").mock(return_value=_gql({"IssuedInvoices": [INV]}))
    backend = ApiBackend(settings())
    rows = await asyncio.gather(*(backend.receivables(CID) for _ in range(5)))
    assert tokens[0] == 1
    inv = rows[0][0]
    assert inv.total == Decimal("123.45") and isinstance(inv.total, Decimal)
    assert inv.remaining == Decimal("0.1")
    assert inv.paid_on is None and inv.currency_id is None and inv.reference is None  # Money "empty" values
    await backend.aclose()


@respx.mock
async def test_401_refreshes_the_token_once() -> None:
    tokens = [0]
    _token(respx.post(f"{BASE}/connect/token"), tokens)
    gql = respx.post(f"{BASE}/graphql")
    gql.side_effect = [httpx.Response(401), _gql({"Version": "S4 1.2"})]
    backend = ApiBackend(settings())
    assert await backend.version() == "S4 1.2"
    assert tokens[0] == 2 and gql.calls[1].request.headers["authorization"] == "Bearer t2"


@respx.mock
async def test_repeated_401_and_network_errors_are_unavailable() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    respx.post(f"{BASE}/graphql").mock(return_value=httpx.Response(401))
    with pytest.raises(MoneyUnavailable):
        await ApiBackend(settings()).version()
    respx.post(f"{BASE}/graphql").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(MoneyUnavailable):
        await ApiBackend(settings()).version()
    respx.post(f"{BASE}/connect/token").mock(return_value=httpx.Response(400))
    with pytest.raises(MoneyUnavailable):
        await ApiBackend(settings()).version()


@respx.mock
async def test_graphql_errors_are_money_errors() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    respx.post(f"{BASE}/graphql").mock(return_value=httpx.Response(200, json={"errors": [{"message": "x"}]}))
    with pytest.raises(MoneyError):
        await ApiBackend(settings()).version()


@respx.mock
async def test_search_cascade_sends_safe_filters_in_order() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    gql = respx.post(f"{BASE}/graphql")
    gql.side_effect = [_gql({"IssuedInvoices": []}), _gql({"IssuedInvoices": []}), _gql({"IssuedInvoices": [INV]})]
    found = await ApiBackend(settings()).search_invoices(InvoiceQuery(number="FV 26/42", variable_symbol="2600042"))
    filters = [json.loads(c.request.content)["variables"]["filter"] for c in gql.calls]
    assert filters == ["CisloDokladu~eq~FV 26/42", "VariabilniSymbol~eq~2600042", "CisloDokladu~ct~2642"]
    assert found.matched_by == "number_digits" and found.items[0].number == "FV2600042"
    assert all(json.loads(c.request.content)["variables"]["count"] <= 200 for c in gql.calls)


@respx.mock
async def test_company_mapping_and_receivables_filter() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    gql = respx.post(f"{BASE}/graphql")
    gql.side_effect = [
        _gql(
            {
                "Company": {
                    "ID": str(CID),
                    "Kod": "F1",
                    "Nazev": "Fiktívna a.s.",
                    "ICO": "",
                    "HodnotaSlevy": 5,
                    "SplatnostPohledavek": 14,
                    "SeznamSpojeni": [
                        {"SpojeniCislo": "a@b.example", "TypSpojeni": {"Kod": "E-mail"}},
                        {"SpojeniCislo": "", "TypSpojeni": None},
                    ],
                }
            }
        ),
        _gql({"IssuedInvoices": [INV]}),
    ]
    backend = ApiBackend(settings())
    company = await backend.company(CID)
    assert company is not None and company.ico is None and company.discount_pct == Decimal("5")
    assert [c.value for c in company.connections] == ["a@b.example"]
    await backend.receivables(CID)
    assert json.loads(gql.calls[1].request.content)["variables"]["filter"] == f"Firma_ID~eq~{CID}#UhradyZbyva~gt~0"


@respx.mock
async def test_pdf_and_persons_use_rest_paths_from_the_swagger() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    inv = uuid.UUID(INV["ID"])
    pdf = respx.get(f"{BASE}/v2.0/PrepaymentIssuedInvoice/{inv}/Report/7").mock(
        return_value=httpx.Response(200, content=b"%PDF-1.4 x")
    )
    persons = respx.get(f"{BASE}/v2.0/Person/0/2").mock(
        return_value=httpx.Response(
            200, json=[{"id": str(CID), "parent_ID": str(CID), "jmeno": "Ján", "email": "j@x.example"}]
        )
    )
    backend = ApiBackend(settings())
    assert await backend.invoice_pdf("proforma", inv, "7") == b"%PDF-1.4 x"
    page = await backend.persons(None, 0, 2)
    assert pdf.called and persons.called
    assert page.items[0].first_name == "Ján" and page.next_from is None


async def test_activity_filter_waits_for_the_probe() -> None:
    with pytest.raises(WaitingForProbe):
        await ApiBackend(settings()).activities(CID)


def test_endpoints_map_probe_and_outage_to_codes() -> None:
    from tests.conftest import make_client

    client = make_client(backend=ApiBackend(settings()))
    r = client.get(f"/companies/{CID}/activities")
    assert r.status_code == 501 and r.json()["detail"] == {
        "code": "waiting_for_probe",
        "what": "REST Activity list: REST filters do not work (probe 2026-10-31)",
    }
    with respx.mock:
        respx.post(f"{BASE}/connect/token").mock(side_effect=httpx.ConnectError("down"))
        r = client.get(f"/companies/{CID}")
        assert r.status_code == 503 and r.json()["detail"]["code"] == "money_unavailable"
        assert client.client.get("/readyz").status_code == 503


def _envelope(data: Any, status: int = 1) -> httpx.Response:
    """Real Money S4 API 1.15.11 answer shape (TEST agenda, pilot 2026-10-31)."""
    body = {"PageCount": 5, "RowCount": 833, "Data": data, "Status": status, "Message": "", "StackTrace": ""}
    return httpx.Response(200, content=json.dumps(body).encode(), headers={"content-type": "application/json"})


@respx.mock
async def test_money_envelope_is_unwrapped_for_graphql() -> None:
    """Pilot 2026-10-31: Money answers `{"Data": {...}, "Status": 1}`, not `{"data": ...}` — /readyz stayed 503."""
    _token(respx.post(f"{BASE}/connect/token"), [0])
    respx.post(f"{BASE}/graphql").mock(return_value=_envelope({"Version": "1.15.11.7730"}))
    backend = ApiBackend(settings())
    assert await backend.version() == "1.15.11.7730"
    await backend.aclose()


@respx.mock
async def test_money_envelope_with_error_status_raises() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    respx.post(f"{BASE}/graphql").mock(return_value=_envelope(None, status=0))
    backend = ApiBackend(settings())
    with pytest.raises(MoneyError):
        await backend.version()
    await backend.aclose()


@respx.mock
async def test_money_envelope_with_invoice_rows_keeps_decimals() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    respx.post(f"{BASE}/graphql").mock(return_value=_envelope({"IssuedInvoices": [INV]}))
    backend = ApiBackend(settings())
    inv = (await backend.receivables(CID))[0]
    assert inv.total == Decimal("123.45") and isinstance(inv.total, Decimal)
    await backend.aclose()


@respx.mock
async def test_persons_from_real_api_envelope_with_pascal_case_fields() -> None:
    """Pilot 2026-10-31: `/v2.0/Person/{from}/{count}` answers the envelope with PascalCase keys (`ID`, `Parent_ID`,
    `Tel1Cislo`), the swagger says camelCase — the person sync failed with 502 on every run."""
    _token(respx.post(f"{BASE}/connect/token"), [0])
    pid, cid = uuid.uuid4(), uuid.uuid4()
    row = {
        "ID": str(pid),
        "Parent_ID": str(cid),
        "Jmeno": "Jana",
        "Prijmeni": "Testová",
        "Nazev": "Jana Testová",
        "Funkce": "nákup",
        "Email": "jana@example.test",
        "Tel1Cislo": "0900 000 000",
    }
    respx.get(f"{BASE}/v2.0/Person/0/2").mock(return_value=_envelope([row]))
    backend = ApiBackend(settings())
    page = await backend.persons(None, 0, 2)
    person = page.items[0]
    assert person.id == pid and person.company_id == cid
    assert person.email == "jana@example.test" and person.phone == "0900 000 000"
    assert person.last_name == "Testová" and page.next_from is None
    await backend.aclose()


@respx.mock
async def test_activity_types_from_real_api_envelope_with_pascal_case_fields() -> None:
    """#176: REST DTOs are PascalCase inside the envelope on API 1.15.11 (swagger says camelCase)."""
    _token(respx.post(f"{BASE}/connect/token"), [0])
    tid = uuid.uuid4()
    respx.get(f"{BASE}/v2.0/TypeOfActivity/0/2").mock(
        return_value=_envelope([{"ID": str(tid), "Kod": "EMAIL", "Nazev": "E-mail"}])
    )
    backend = ApiBackend(settings())
    page = await backend.codebook("activity-types", 0, 2)
    assert [(i.id, i.code, i.name) for i in page.items] == [(tid, "EMAIL", "E-mail")]
    assert page.next_from is None
    await backend.aclose()


@respx.mock
async def test_activity_types_camel_case_still_read() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    tid = uuid.uuid4()
    respx.get(f"{BASE}/v2.0/TypeOfActivity/0/2").mock(
        return_value=_envelope([{"id": str(tid), "kod": "TEL", "nazev": "Telefonát"}])
    )
    backend = ApiBackend(settings())
    page = await backend.codebook("activity-types", 0, 2)
    assert page.items[0].code == "TEL"
    await backend.aclose()


@respx.mock
async def test_rest_envelope_error_status_is_money_error() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    respx.get(f"{BASE}/v2.0/TypeOfActivity/0/2").mock(
        return_value=httpx.Response(200, json={"Data": None, "Status": 0, "Message": "x", "StackTrace": None})
    )
    backend = ApiBackend(settings())
    with pytest.raises(MoneyError):
        await backend.codebook("activity-types", 0, 2)
    await backend.aclose()


@respx.mock
async def test_invoice_pdf_from_real_api_octet_stream() -> None:
    """#176 probe: `GET /v2.0/IssuedInvoice/{id}/Report/{reportId}` → 200 application/octet-stream (~5 s, bridge
    timeout 20 s) — the bytes are passed through untouched."""
    _token(respx.post(f"{BASE}/connect/token"), [0])
    iid = uuid.uuid4()
    pdf = b"%PDF-1.4 fictional"
    respx.get(f"{BASE}/v2.0/IssuedInvoice/{iid}/Report/7").mock(
        return_value=httpx.Response(200, content=pdf, headers={"content-type": "application/octet-stream"})
    )
    backend = ApiBackend(settings())
    assert await backend.invoice_pdf("invoice", iid, "7") == pdf
    await backend.aclose()


def test_bridge_timeout_covers_slow_pdf_report() -> None:
    from app.gql_client import TIMEOUT

    assert TIMEOUT.read is not None and TIMEOUT.read >= 15


DELETED_INV = {**INV, "ID": "33333333-3333-4333-8333-333333333333", "Deleted": True}


@respx.mock
async def test_deleted_invoices_are_dropped_everywhere() -> None:
    """Pilot 2026-10-31 (TEST agenda): Money returns deleted documents (`Deleted: true`) — 603 of 1104 unpaid
    invoices; one number existed as a deleted invoice of customer A and a live paid one of customer B, and the
    customer card of A listed the deleted invoice as unpaid."""
    _token(respx.post(f"{BASE}/connect/token"), [0])
    respx.post(f"{BASE}/graphql").mock(
        return_value=_envelope({"IssuedInvoices": [{**INV, "Deleted": False}, DELETED_INV]})
    )
    backend = ApiBackend(settings())
    assert [i.number for i in await backend.receivables(CID)] == ["FV2600042"]
    found = await backend.search_invoices(InvoiceQuery(number="FV2600042"))
    assert [str(i.id) for i in found.items] == [INV["ID"]]
    await backend.aclose()


@respx.mock
async def test_dropping_deleted_rows_does_not_end_paging_early() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    respx.post(f"{BASE}/graphql").mock(return_value=_envelope({"IssuedInvoices": [INV, DELETED_INV]}))
    backend = ApiBackend(settings())
    page = await backend.overdue(date(2026, 10, 31), 0, 2)
    assert len(page.items) == 1 and page.next_from == 2  # raw page was full -> keep paging
    await backend.aclose()


@respx.mock
async def test_deleted_company_and_persons_are_dropped() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    respx.post(f"{BASE}/graphql").mock(
        return_value=_envelope({"Company": {"ID": str(CID), "Nazev": "Zmazaná s.r.o.", "Deleted": True}})
    )
    pid = uuid.uuid4()
    rows = [{"ID": str(pid), "Deleted": False, "Email": "a@example.test"}, {"ID": str(uuid.uuid4()), "Deleted": True}]
    respx.get(f"{BASE}/v2.0/Person/0/2").mock(return_value=_envelope(rows))
    backend = ApiBackend(settings())
    assert await backend.company(CID) is None
    page = await backend.persons(None, 0, 2)
    assert [p.id for p in page.items] == [pid] and page.next_from == 2
    await backend.aclose()


@respx.mock
async def test_4b_articles_and_supplier_codes_from_the_api_shape() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    art_id, sup_id = uuid.uuid4(), uuid.uuid4()
    seen: list[dict[str, Any]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body["variables"])
        if "ArticleSuppliers" in body["query"]:
            return _envelope(
                {
                    "ArticleSuppliers": [
                        {
                            "ID": str(uuid.uuid4()),
                            "Deleted": False,
                            "Parent_ID": str(art_id),
                            "Firma_ID": str(sup_id),
                            "DodavatelskyKod": "934-10-A2",
                            "DodavatelskyNazev": "Matica M10",
                            "PosledniCena": 8.05,
                            "Jednotka": {"Kod": "bal"},
                            "ArtiklJednotka": {"Kod": "bal", "Mnozstvi": 200},
                        },
                        {
                            "ID": str(uuid.uuid4()),
                            "Deleted": True,
                            "Parent_ID": str(art_id),
                            "Firma_ID": str(sup_id),
                            "DodavatelskyKod": "OLD",
                        },
                    ]
                }
            )
        return _envelope(
            {
                "Articles": [
                    {
                        "ID": str(art_id),
                        "Deleted": False,
                        "Hidden": False,
                        "Kod": "ART-3",
                        "Katalog": "934-10-A2",
                        "Nazev": "Matica DIN 934 M10 A2",
                        "CarovyKod": None,
                        "HlavniJednotka": {"Kod": "ks"},
                        "SeznamJednotek": [
                            {"Kod": "ks", "Mnozstvi": 1, "DesetinnaMista": 0},
                            {"Kod": "bal", "Mnozstvi": 200, "DesetinnaMista": 0},
                        ],
                    },
                ]
            }
        )

    respx.post(f"{BASE}/graphql").mock(side_effect=answer)
    backend = ApiBackend(settings())
    from app.backend import ArticleQuery

    arts = await backend.articles(ArticleQuery(code="934-10-A2"))
    assert arts[0].catalog == "934-10-A2" and arts[0].units[1].qty == Decimal("200")
    assert (
        seen[0]["filter"] == "(Kod~eq~934-10-A2)|(Katalog~eq~934-10-A2)" or "Katalog~eq~934-10-A2" in seen[0]["filter"]
    )
    page = await backend.supplier_codes(sup_id, 0, 50)
    assert [c.code for c in page.items] == ["934-10-A2"]  # the deleted row is dropped
    assert page.items[0].last_price == Decimal("8.05") and isinstance(page.items[0].last_price, Decimal)
    assert seen[1]["filter"] == f"Firma_ID~eq~{sup_id}"
    await backend.aclose()


@respx.mock
async def test_210_order_step_searches_popis_nazev_with_a_safe_filter() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    gql = respx.post(f"{BASE}/graphql")
    gql.side_effect = [_gql({"IssuedInvoices": [{**INV, "Nazev": "Objednávka 2410006820"}]})]
    found = await ApiBackend(settings()).search_invoices(InvoiceQuery(order="2410006820", company_id=CID))
    body = json.loads(gql.calls[0].request.content)
    # #217: „Popis“ OR „Poznámka“
    assert body["variables"]["filter"] == f"Firma_ID~eq~{CID}#(Nazev~ct~2410006820)|(Poznamka~ct~2410006820)"
    assert "Nazev" in body["query"] and "Poznamka" in body["query"]
    assert found.matched_by == "order" and found.items[0].description == "Objednávka 2410006820"
    gql.side_effect = [_gql({"IssuedInvoices": []})]
    none = await ApiBackend(settings()).search_invoices(InvoiceQuery(order="2410006820"))
    assert none.matched_by == "none"
    assert (
        json.loads(gql.calls[-1].request.content)["variables"]["filter"]
        == "(Nazev~ct~2410006820)|(Poznamka~ct~2410006820)"
    )


@respx.mock
async def test_217_order_with_letters_reads_poznamka() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    gql = respx.post(f"{BASE}/graphql")
    gql.side_effect = [_gql({"IssuedInvoices": [{**INV, "Nazev": None, "Poznamka": "Vaša obj. PO-45821"}]})]
    found = await ApiBackend(settings()).search_invoices(InvoiceQuery(order="PO-45821"))
    body = json.loads(gql.calls[0].request.content)
    assert body["variables"]["filter"] == "(Nazev~ct~PO-45821)|(Poznamka~ct~PO-45821)"
    assert found.items[0].note == "Vaša obj. PO-45821" and found.items[0].description is None


DL = {
    "ID": "33333333-3333-4333-8333-333333333333",
    "Deleted": False,
    "CisloDokladu": "DV260042",
    "Firma_ID": str(CID),
    "DatumVystaveni": "2026-11-10T00:00:00",
    "DatumSkladovehoPohybu": "2026-11-10T00:00:00",
    "Odkaz": None,
    "Stav": 1,
    "ZpusobDopravy": {"Nazev": "Kuriér"},
    "CelkovaCastka": 120.5,
    "Stredisko_ID": "44444444-4444-4444-8444-444444444444",
    "Nazev": "Objednávka OR06024026",
    "Poznamka": None,
}


@respx.mock
async def test_222_delivery_note_order_search_reads_popis_and_poznamka() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    gql = respx.post(f"{BASE}/graphql")
    gql.side_effect = [_gql({"IssuedDeliveryNotes": [DL, {**DL, "ID": str(uuid.uuid4()), "Deleted": True}]})]
    found = await ApiBackend(settings()).search_deliveries(DeliveryQuery(order="OR06024026", company_id=CID))
    body = json.loads(gql.calls[0].request.content)
    assert body["variables"]["filter"] == f"Firma_ID~eq~{CID}#(Nazev~ct~OR06024026)|(Poznamka~ct~OR06024026)"
    assert "Stredisko_ID" in body["query"] and "Poznamka" in body["query"]
    assert found.matched_by == "order" and [d.number for d in found.items] == ["DV260042"]  # deleted row dropped
    assert found.items[0].centre_id == uuid.UUID(DL["Stredisko_ID"]) and found.items[0].total == Decimal("120.5")


@respx.mock
async def test_222_pdfreport_with_and_without_designid_and_rejects_non_pdf() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    route = respx.get(f"{BASE}/pdfreport")
    route.side_effect = [
        httpx.Response(200, content=b"%PDF-1.4 fiktivny", headers={"content-type": "application/pdf"}),
        httpx.Response(200, content=b"%PDF-1.4 fiktivny", headers={"content-type": "application/pdf"}),
        httpx.Response(200, content=b"<html>login</html>", headers={"content-type": "text/html"}),
        httpx.Response(200, content=b"not a pdf", headers={"content-type": "application/pdf"}),
        httpx.Response(404),
    ]
    backend = ApiBackend(settings())
    rid = uuid.UUID(DL["ID"])
    assert await backend.document_pdf("issued_delivery_note", rid, "12", "34") == b"%PDF-1.4 fiktivny"
    params = dict(route.calls[0].request.url.params)
    assert params == {"objectname": "issueddeliverynote", "id": str(rid), "reportid": "12", "designid": "34"}
    assert await backend.document_pdf("issued_delivery_note", rid, "12", None) == b"%PDF-1.4 fiktivny"
    assert "designid" not in dict(route.calls[1].request.url.params)
    for _ in range(2):
        with pytest.raises(MoneyError):
            await backend.document_pdf("issued_delivery_note", rid, "12", None)
    assert await backend.document_pdf("issued_delivery_note", rid, "12", None) is None
    await backend.aclose()


def test_222_pdf_endpoint_is_allowed_on_prod() -> None:
    from app.mock import build
    from tests.conftest import make_client

    prod = make_client(money_agenda_label="PROD")
    note = build().deliveries[0]
    r = prod.get(f"/documents/issued_delivery_note/{note.id}/pdf?report_id=12")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")  # a GET, read only (#212)


SUP = uuid.UUID("55555555-5555-4555-8555-555555555555")
AS_ROW = {
    "ID": "66666666-6666-4666-8666-666666666666",
    "Deleted": False,
    "Parent_ID": "77777777-7777-4777-8777-777777777777",
    "Firma_ID": str(SUP),
    "DodavatelskyKod": "09150.14.01.120.000",
    "DodavatelskyNazev": "Skrutka fiktívna",
    "PosledniCena": 0.084,
    "Jednotka": {"Kod": "ks"},
    "ArtiklJednotka": {"Kod": "ks", "Mnozstvi": 1},
}


@respx.mock
async def test_228_sync_all_article_suppliers_with_changefrom_and_lookup_one_code() -> None:
    from datetime import UTC, datetime

    _token(respx.post(f"{BASE}/connect/token"), [0])
    gql = respx.post(f"{BASE}/graphql")
    gql.side_effect = [
        _gql({"ArticleSuppliers": [AS_ROW, {**AS_ROW, "ID": str(uuid.uuid4()), "Deleted": True}]}),
        _gql({"ArticleSuppliers": [AS_ROW]}),
    ]
    backend = ApiBackend(settings())
    since = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)
    page = await backend.all_supplier_codes(since, 0, 200)
    body = json.loads(gql.calls[0].request.content)
    assert "filter" not in body["variables"] and body["variables"]["changeFrom"].startswith("2026-11-20T08:00")
    assert [c.code for c in page.items] == ["09150.14.01.120.000"]  # the deleted row is dropped
    assert page.items[0].id == uuid.UUID(AS_ROW["ID"]) and page.items[0].last_price == Decimal("0.084")
    found = await backend.lookup_supplier_code(SUP, "09150.14.01.120.000")
    body = json.loads(gql.calls[1].request.content)
    assert body["variables"]["filter"] == f"Firma_ID~eq~{SUP}#DodavatelskyKod~eq~09150.14.01.120.000"
    assert [c.article_id for c in found] == [uuid.UUID(AS_ROW["Parent_ID"])]
    await backend.aclose()


ART = {
    "ID": "88888888-8888-4888-8888-888888888888",
    "Deleted": False,
    "Hidden": False,
    "Kod": "V-1",
    "Katalog": "99901000006",
    "Nazev": "Vrut fiktívny 6 mm",
    "CarovyKod": None,
    "NadrazenyArtikl_ID": "99999999-9999-4999-8999-999999999999",
    "HlavniJednotka": {"Kod": "ks"},
    "SeznamJednotek": [],
}


@respx.mock
async def test_233_variants_of_several_main_cards_in_one_or_call() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    gql = respx.post(f"{BASE}/graphql")
    main_a = uuid.UUID(ART["NadrazenyArtikl_ID"])
    main_b = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    gql.side_effect = [
        _gql(
            {
                "Articles": [
                    ART,
                    {**ART, "ID": str(uuid.uuid4()), "Hidden": True},
                    {**ART, "ID": str(uuid.uuid4()), "Deleted": True},
                ]
            }
        )
    ]
    found = await ApiBackend(settings()).article_variants([main_a, main_b])
    body = json.loads(gql.calls[0].request.content)
    assert body["variables"]["filter"] == f"(NadrazenyArtikl_ID~eq~{main_a})|(NadrazenyArtikl_ID~eq~{main_b})"
    assert body["variables"]["count"] <= 300 and "NadrazenyArtikl_ID" in body["query"]
    assert [a.inactive for a in found[main_a]] == [False, True] and found[main_b] == []  # deleted dropped
    assert found[main_a][0].parent_id == main_a


@respx.mock
async def test_wildcard_article_search_ands_the_pieces_and_checks_their_order() -> None:
    """Pilot 2026-11-23: `%mat%4%934` like in Money S4 — no `%` in the filter, pieces in order, accents ignored."""
    from app.backend import ArticleQuery

    _token(respx.post(f"{BASE}/connect/token"), [0])

    def row(i: int, name: str) -> dict[str, Any]:
        return {
            "ID": f"a0000000-0000-4000-8000-{i:012d}",
            "Deleted": False,
            "Hidden": False,
            "Kod": f"K{i}",
            "Katalog": f"99{i}",
            "Nazev": name,
            "HlavniJednotka": {"Kod": "ks"},
            "SeznamJednotek": [],
        }

    gql = respx.post(f"{BASE}/graphql")
    gql.side_effect = [
        _gql({"Articles": [row(1, "Matica DIN 934 M4 A2"), row(2, "mat. M4 4.8 DIN 934"), row(3, "MATICA 8 DIN 934")]})
    ]
    found = await ApiBackend(settings()).articles(ArticleQuery(text="%mat%4%934"))
    body = json.loads(gql.calls[0].request.content)
    assert body["variables"]["filter"] == "Nazev~ct~mat#Nazev~ct~4#Nazev~ct~934"
    assert "%" not in body["variables"]["filter"]
    # 1: „4“ only after „934“ → out; 3: no „4“ before „934“ → out
    assert [a.name for a in found] == ["mat. M4 4.8 DIN 934"]


def test_wildcard_helpers() -> None:
    from app import wildcard

    assert wildcard.parts("%mat%4%934") == ["mat", "4", "934"]
    assert wildcard.parts("%%") == []
    assert wildcard.in_order("Podložka DIN 125 M10", ["podlozka", "m10"])
    assert not wildcard.in_order("M10 podložka", ["podlozka", "m10"])
