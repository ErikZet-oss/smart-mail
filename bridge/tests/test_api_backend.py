"""Real Money backend against a respx-mocked server: token, 401 retry, Decimal parsing, filters, mapping, errors."""

from __future__ import annotations

import asyncio
import json
import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx

from app.api_backend import ApiBackend
from app.backend import InvoiceQuery, MoneyError, MoneyUnavailable, WaitingForProbe
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
