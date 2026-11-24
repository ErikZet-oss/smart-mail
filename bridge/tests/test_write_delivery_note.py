"""#247 / D33 POST /delivery-notes/received — the received delivery note goes to Money only as a KONCEPT (`Faze` 0,
`Schvaleno` false, Popis „Smartmail…“): HMAC + single-use approval JWT, own SMID → returned, same supplier + Odkaz →
409 `duplicate` before the mutation, never retried (SMID looked up once), PROD only with `MONEY_PROD_ALLOW` naming
`create_delivery_note`. All IDs, numbers and names are fictional."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx

from app.api_backend import ApiBackend, template_from
from app.backend import DuplicateNote, MoneyUnavailable
from app.mock import MockBackend, mid
from app.models import DeliveryNoteIn
from tests.conftest import make_client
from tests.test_api_backend import BASE, _gql, _token, settings
from tests.test_write_activity import _TS, PUB, token

SMID = "0b0e9c3e-2222-4a2b-8c3d-000000000247"
CENTRE = mid("centre", 1)
NEW_ID = "24724724-7247-4247-8247-247247247247"


def note(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "smid": SMID,
        "Firma_ID": str(mid("company", 1)),
        "CiselnaRada_ID": str(mid("series", 3)),
        "Stredisko_ID": str(CENTRE),
        "Group_ID": str(mid("note-group", 1)),
        "DruhPohybu_ID": str(mid("movement-kind", 1)),
        "DruhSkladovehoPohybu_ID": str(mid("stock-movement-kind", 1)),
        "Predkontace_ID": str(mid("account-assignment", 1)),
        "RegistraceDPH_ID": str(mid("vat-registration", 1)),
        "Odkaz": "DL-2026-04417",
        "ParovaciSymbol": "2611452",
        "Nazev": "Smartmail · Skrutka DIN 933 M10x30 A2 (fiktívna)",
        "Poznamka": "zdroj: e-mail",
        "DatumVystaveni": "2026-11-20",
        "DatumUcetnihoPripadu": "2026-11-23",
        "DatumSkladovehoPohybu": "2026-11-23",
        "CasSkladovehoPohybu": "2026-11-23T09:14:00",
        "Faze": 0,
        "Schvaleno": False,
        "Polozky": [
            {
                "Poradi": 1,
                "Nazev": "Skrutka DIN 933 M10x30 A2 (fiktívna)",
                "Katalog": "933-10-30-A2",
                "Mnozstvi": "5000",
                "Jednotka": "ks",
                "JednCena": "0.0612",
                "TypCeny": 0,
                "TypObsahu": 1,
                "SazbaDPH_ID": str(mid("vat-rate", 23)),
                "DruhSazbyDPH": 2,
                "Stredisko_ID": str(CENTRE),
                "ObsahPolozky": {
                    "Artikl_ID": str(mid("article", 2)),
                    "Sklad_ID": str(mid("warehouse", 1)),
                    "Mnozstvi": "5000",
                    "PartnerskyKod": "FX-933-1030-A2",
                    "PartnerskyNazev": "Šroub ISO 4017 M10x30 A2",
                },
            }
        ],
    }
    data.update(over)
    return data


def raw(**over: Any) -> bytes:
    return json.dumps(note(**over)).encode()


def post(client: Any, body: bytes, tok: str | None) -> Any:
    _TS[0] += 1
    headers = client.headers("POST", "/delivery-notes/received", body, ts=_TS[0])
    if tok:
        headers["X-Approval-Token"] = tok
    return client.client.post(
        "/delivery-notes/received", content=body, headers={**headers, "Content-Type": "application/json"}
    )


def dl_token(body: bytes) -> str:
    return token(body, act="delivery_note.create")


class Spy(MockBackend):
    def __init__(self) -> None:
        super().__init__()
        self.creates = 0

    async def create_delivery_note(self, n: DeliveryNoteIn) -> Any:
        self.creates += 1
        return await super().create_delivery_note(n)


# ----- router: approval, koncept only, PROD allowlist -----


def test_247_create_koncept_then_repeat_returns_it_and_duplicate_answers_409() -> None:
    spy = Spy()
    client = make_client(backend=spy, approval_jwt_public_key=PUB)
    body = raw()
    assert post(client, body, None).json()["detail"]["code"] == "approval_missing"
    assert post(client, body, token(body)).status_code == 403  # an activity token is not a delivery-note token
    r = post(client, body, dl_token(body))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["faze"] == 0 and out["schvaleno"] is False and out["reconciled"] is False
    assert out["number"].startswith("DLP") and out["group_id"] == str(mid("note-group", 1))
    assert out["lines"][0]["article_id"] == str(mid("article", 2)) and out["lines"][0]["content_type"] == 1
    again = post(client, body, dl_token(body))  # the same SMID → the koncept already made, nothing new
    assert again.json()["id"] == out["id"] and again.json()["reconciled"] is True
    other = raw(smid=SMID[:-1] + "9")  # another SMID, same supplier + Odkaz → DL-B3
    dup = post(client, other, dl_token(other))
    assert dup.status_code == 409 and dup.json()["detail"] == {"code": "duplicate", "number": out["number"]}
    assert len([n for n in spy.data.received_notes if n["Odkaz"] == "DL-2026-04417"]) == 1


@pytest.mark.parametrize(
    "over",
    [
        {"Faze": 1},
        {"Faze": "0"},
        {"Faze": False},
        {"Schvaleno": True},
        {"Schvaleno": None},
        {"Schvalil_ID": str(uuid.uuid4())},
        {"DatumSchvaleni": "2026-11-23T09:00:00"},
    ],
)
def test_247_D33_not_koncept_is_refused_before_money(over: dict[str, Any]) -> None:
    spy = Spy()
    client = make_client(backend=spy, approval_jwt_public_key=PUB)
    body = raw(**over)
    r = post(client, body, dl_token(body))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "not_koncept"
    assert spy.creates == 0


def test_247_D33_missing_koncept_fields_and_popis_prefix() -> None:
    client = make_client(backend=Spy(), approval_jwt_public_key=PUB)
    data = note()
    del data["Faze"]
    body = json.dumps(data).encode()
    assert post(client, body, dl_token(body)).json()["detail"]["code"] == "not_koncept"
    body = raw(Nazev="Skrutka bez prefixu")
    assert post(client, body, dl_token(body)).json()["detail"]["code"] == "delivery_note_invalid"
    body = raw(Polozky=[{**note()["Polozky"][0], "Mnozstvi": "-1"}])  # D15: no returns
    assert post(client, body, dl_token(body)).json()["detail"]["code"] == "delivery_note_invalid"


def test_247_prod_allows_only_with_create_delivery_note_in_the_variable() -> None:
    body = raw()
    for allow in ("", "create_article"):
        spy = Spy()
        prod = make_client(backend=spy, approval_jwt_public_key=PUB, money_agenda_label="PROD", money_prod_allow=allow)
        r = post(prod, body, dl_token(body))
        assert r.status_code == 403 and r.json()["detail"]["code"] == "prod_read_only"
        assert spy.creates == 0
    spy = Spy()
    prod = make_client(
        backend=spy,
        approval_jwt_public_key=PUB,
        money_agenda_label="PROD",
        money_prod_allow="create_article, create_delivery_note",
    )
    assert post(prod, body, dl_token(body)).status_code == 200 and spy.creates == 1
    bad = raw(Schvaleno=True, smid=SMID[:-1] + "1")
    assert post(prod, bad, dl_token(bad)).json()["detail"]["code"] == "not_koncept"  # on PROD too
    from tests.test_write_activity import body as activity_body
    from tests.test_write_activity import post as post_activity
    from tests.test_write_activity import token as activity_token

    a = activity_body()
    assert post_activity(prod, a, activity_token(a)).json()["detail"]["code"] == "prod_read_only"


def test_247_template_endpoints() -> None:
    client = make_client()
    rows = client.get(f"/delivery-notes/received?centre_id={CENTRE}").json()
    assert [r["number"] for r in rows] == ["DLP0001/2026"] and rows[0]["by_smart_mail"] is False
    tpl = client.get(f"/delivery-notes/received/{rows[0]['id']}/template").json()
    assert tpl["header"]["Group_ID"] == str(mid("note-group", 1))
    assert tpl["header"]["CiselnaRada_ID"] == str(mid("series", 3))
    assert tpl["line"] == {
        "TypObsahu": 1,
        "TypCeny": 0,
        "DruhSazbyDPH": 2,
        "DruhPolozky_ID": str(mid("item-kind", 1)),
        "SazbaDPH_ID": str(mid("vat-rate", 23)),
        "DphSazba": "23",
        "VazbaTypVazby": 0,
        "VazbaPocetNadrizene": "1",
        "VazbaPocetPodrizene": "1",
    }
    assert tpl["text_line"] == {"TypObsahu": 0}
    assert client.get(f"/delivery-notes/received/{uuid.uuid4()}/template").status_code == 404


def test_247_template_never_invents_a_value() -> None:
    tpl = template_from({"ID": NEW_ID, "Group_ID": "00000000-0000-0000-0000-000000000000", "Polozky": []})
    assert tpl.header == {} and tpl.line == {} and tpl.text_line is None


# ----- API backend: exact payload, checks before the mutation, no retry, reconciliation -----


def _back(**over: Any) -> dict[str, Any]:
    row = {
        "ID": NEW_ID,
        "Deleted": False,
        "CisloDokladu": "DLP0099/2026",
        "Nazev": "Smartmail · x",
        "Poznamka": f"SMID:{SMID}",
        "Faze": 0,
        "Schvaleno": False,
        "Group_ID": str(mid("note-group", 1)),
        "Stredisko_ID": str(CENTRE),
        "AdresaNazev": "Fiktívny dodávateľ",
        "SumaZaklad": "306.00",
        "CelkovaCastka": "376.38",
        "Polozky": [
            {
                "ID": str(uuid.uuid4()),
                "CisloPolozky": 1,
                "Poradi": 1,
                "Mnozstvi": 5000,
                "JednCena": "0.0612",
                "TypObsahu": 1,
                "Stredisko_ID": str(CENTRE),
                "ObsahPolozky": {"Artikl_ID": str(mid("article", 2)), "Sklad_ID": str(mid("warehouse", 1))},
            }
        ],
    }
    row.update(over)
    return row


def _queries(gql: Any) -> list[str]:
    return [json.loads(c.request.content)["query"].split("(")[0].split()[-1] for c in gql.calls]


@respx.mock
async def test_247_payload_is_a_koncept_with_template_values_and_numbers_as_numbers() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    gql = respx.post(f"{BASE}/graphql")
    gql.side_effect = [
        _gql({"ReceivedDeliveryNotes": []}),  # own SMID
        _gql({"ReceivedDeliveryNotes": []}),  # same supplier + Odkaz
        _gql({"CreateReceivedDeliveryNote": {"ID": NEW_ID, "CisloDokladu": "DLP0099/2026"}}),
        _gql({"ReceivedDeliveryNote": _back()}),
    ]
    out = await ApiBackend(settings()).create_delivery_note(DeliveryNoteIn.model_validate(note()))
    assert _queries(gql) == [
        "ReceivedDeliveryNotes",
        "ReceivedDeliveryNotes",
        "CreateReceivedDeliveryNote",
        "ReceivedDeliveryNote",
    ]
    first = json.loads(gql.calls[0].request.content)["variables"]
    assert first["filter"] == f"Poznamka~ct~SMID:{SMID}"
    second = json.loads(gql.calls[1].request.content)["variables"]
    assert second["filter"] == f"Firma_ID~eq~{mid('company', 1)}#Odkaz~eq~DL-2026-04417"
    sent = gql.calls[2].request.content.decode()
    dl = json.loads(sent, parse_float=Decimal)["variables"]["dl"]
    assert dl["Faze"] == 0 and dl["Schvaleno"] is False
    assert "Schvalil_ID" not in dl and "DatumSchvaleni" not in dl and "smid" not in dl and "with_address" not in dl
    assert dl["Group_ID"] == str(mid("note-group", 1)) and dl["Nazev"].startswith("Smartmail · ")
    assert dl["Poznamka"] == f"SMID:{SMID} · zdroj: e-mail"
    assert dl["DatumVystaveni"] == "2026-11-20T00:00:00" and dl["CasSkladovehoPohybu"] == "2026-11-23T09:14:00"
    item = dl["Polozky"][0]
    assert item["TypObsahu"] == 1 and item["ObsahPolozky"]["Sklad_ID"] == str(mid("warehouse", 1))
    assert '"JednCena":0.0612' in sent and '"Mnozstvi":5000' in sent  # Decimal → JSON number, no float on the way
    assert item["JednCena"] == Decimal("0.0612")
    assert not any(k.startswith("Adresa") for k in dl)  # 1st path: only Firma_ID
    assert out.number == "DLP0099/2026" and out.reconciled is False and out.address_empty is False
    assert out.lines[0].qty == Decimal("5000") and out.total_base == Decimal("306.00")


@respx.mock
async def test_247_DL_B3_duplicate_stops_before_the_mutation() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    gql = respx.post(f"{BASE}/graphql")
    gql.side_effect = [
        _gql({"ReceivedDeliveryNotes": []}),
        _gql(
            {
                "ReceivedDeliveryNotes": [
                    {
                        "ID": str(uuid.uuid4()),
                        "CisloDokladu": "DLP0007/2026",
                        "Odkaz": "DL-2026-04417",
                        "Deleted": False,
                    }
                ]
            }
        ),
    ]
    with pytest.raises(DuplicateNote) as exc:
        await ApiBackend(settings()).create_delivery_note(DeliveryNoteIn.model_validate(note()))
    assert exc.value.number == "DLP0007/2026" and len(gql.calls) == 2


@respx.mock
async def test_247_own_smid_found_first_no_mutation() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    gql = respx.post(f"{BASE}/graphql")
    gql.side_effect = [
        _gql({"ReceivedDeliveryNotes": [{"ID": NEW_ID, "Poznamka": f"SMID:{SMID}", "Deleted": False}]}),
        _gql({"ReceivedDeliveryNote": _back()}),
    ]
    out = await ApiBackend(settings()).create_delivery_note(DeliveryNoteIn.model_validate(note()))
    assert out.reconciled is True and "CreateReceivedDeliveryNote" not in _queries(gql)


@respx.mock
async def test_247_timeout_never_retried_reconciled_once_by_smid() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    gql = respx.post(f"{BASE}/graphql")
    gql.side_effect = [
        _gql({"ReceivedDeliveryNotes": []}),
        _gql({"ReceivedDeliveryNotes": []}),
        httpx.ReadTimeout("slow"),
        _gql({"ReceivedDeliveryNotes": [{"ID": NEW_ID, "Poznamka": f"SMID:{SMID}", "Deleted": False}]}),
        _gql({"ReceivedDeliveryNote": _back()}),
    ]
    out = await ApiBackend(settings()).create_delivery_note(DeliveryNoteIn.model_validate(note()))
    assert out.reconciled is True and _queries(gql).count("CreateReceivedDeliveryNote") == 1


@respx.mock
async def test_247_timeout_and_not_found_stays_an_error() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    gql = respx.post(f"{BASE}/graphql")
    gql.side_effect = [
        _gql({"ReceivedDeliveryNotes": []}),
        _gql({"ReceivedDeliveryNotes": []}),
        httpx.ReadTimeout("slow"),
        _gql({"ReceivedDeliveryNotes": []}),
    ]
    with pytest.raises(MoneyUnavailable):
        await ApiBackend(settings()).create_delivery_note(DeliveryNoteIn.model_validate(note()))
    assert _queries(gql).count("CreateReceivedDeliveryNote") == 1


@respx.mock
async def test_247_address_path_from_the_company_card_and_empty_read_back_is_reported() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    gql = respx.post(f"{BASE}/graphql")
    company = {
        "ID": str(mid("company", 1)),
        "Nazev": "Fiktívny s.r.o.",
        "ObchNazev": None,
        "ObchUlice": "Hlavná 1",
        "ObchMisto": "Senica",
        "ObchPsc": "90501",
        "ObchStat_ID": str(mid("country", 1)),
        "ICO": "12345678",
        "DIC": "2020000000",
        "ICDPH": None,
    }
    gql.side_effect = [
        _gql({"ReceivedDeliveryNotes": []}),
        _gql({"ReceivedDeliveryNotes": []}),
        _gql({"Company": company}),
        _gql({"CreateReceivedDeliveryNote": {"ID": NEW_ID}}),
        _gql({"ReceivedDeliveryNote": _back(AdresaNazev=None)}),
    ]
    out = await ApiBackend(settings()).create_delivery_note(DeliveryNoteIn.model_validate(note(with_address=True)))
    dl = json.loads(gql.calls[3].request.content)["variables"]["dl"]
    assert dl["AdresaNazev"] == "Fiktívny s.r.o." and dl["AdresaMisto"] == "Senica" and dl["IC"] == "12345678"
    assert "ICDPH" not in dl  # nothing invented for an empty card value
    assert out.address_empty is True


def test_247_dumps_writes_decimals_as_numbers_and_never_turns_text_into_a_number() -> None:
    from app.gql_client import dumps

    assert (
        dumps({"a": Decimal("0.0612"), "b": [Decimal("5000")], "t": "0.0612"})
        == b'{"a":0.0612,"b":[5000],"t":"0.0612"}'
    )
    with pytest.raises(ValueError):
        dumps({"t": "\u0000dec:1"})
    with pytest.raises(ValueError):
        dumps({"a": Decimal("NaN")})


def test_item_sends_exactly_one_of_unit_price_or_line_total() -> None:
    """Pilot 2026-11-24 (PROD probe 302600973): a stock line with the invoice total sends `CelkovaCena` only."""
    from pydantic import ValidationError

    from app.models import DeliveryNoteItemIn

    base = {"Poradi": 1, "Nazev": "x", "Mnozstvi": "1000", "TypCeny": 0, "TypObsahu": 1, "Stredisko_ID": str(NEW_ID)}
    total = DeliveryNoteItemIn.model_validate({**base, "CelkovaCena": "40.25"})
    assert total.CelkovaCena == Decimal("40.25") and total.JednCena is None
    assert "JednCena" not in total.model_dump(exclude_none=True)
    assert DeliveryNoteItemIn.model_validate({**base, "JednCena": "0.0403"}).CelkovaCena is None
    for bad in ({}, {"JednCena": "0.0403", "CelkovaCena": "40.25"}):
        with pytest.raises(ValidationError):
            DeliveryNoteItemIn.model_validate({**base, **bad})


def test_D34_header_side_costs_must_equal_the_lines() -> None:
    from pydantic import ValidationError

    def body(header: str | None, lines: list[str | None]) -> dict[str, Any]:
        items = [
            {
                "Poradi": i,
                "Nazev": "x",
                "Mnozstvi": "10",
                "CelkovaCena": "10",
                "TypCeny": 0,
                "TypObsahu": 1,
                "Stredisko_ID": str(NEW_ID),
                **({"CelkoveVedlejsiNaklady": c} if c else {}),
            }
            for i, c in enumerate(lines, start=1)
        ]
        out: dict[str, Any] = {
            "smid": "a" * 32,
            "Firma_ID": str(NEW_ID),
            "CiselnaRada_ID": str(NEW_ID),
            "Stredisko_ID": str(NEW_ID),
            "Group_ID": str(NEW_ID),
            "DruhPohybu_ID": str(NEW_ID),
            "DruhSkladovehoPohybu_ID": str(NEW_ID),
            "Predkontace_ID": str(NEW_ID),
            "Odkaz": "DL-1",
            "Nazev": "Smartmail · x",
            "DatumVystaveni": "2026-11-24",
            "DatumUcetnihoPripadu": "2026-11-24",
            "DatumSkladovehoPohybu": "2026-11-24",
            "CasSkladovehoPohybu": "2026-11-24T10:00:00",
            "Faze": 0,
            "Schvaleno": False,
            "Polozky": items,
        }
        if header:
            out["DodatecnePorizovaciNaklady"] = header
        return out

    ok = DeliveryNoteIn.model_validate(body("2.50", ["0.83", "0.83", "0.84"]))
    assert ok.money_input()["DodatecnePorizovaciNaklady"] == Decimal("2.50")
    assert "DodatecnePorizovaciNaklady" not in DeliveryNoteIn.model_validate(body(None, [None])).money_input()
    for bad in (body("2.50", [None, None]), body(None, ["0.50"]), body("2.50", ["0.83", "0.83", "0.83"])):
        with pytest.raises(ValidationError):
            DeliveryNoteIn.model_validate(bad)
