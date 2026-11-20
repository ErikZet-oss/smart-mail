"""D32 (#239) POST /articles — `CreateArticle` after the user's click: HMAC + single-use approval JWT, only the
allowed fields, catalog checked right before the mutation, never retried (reconciliation once), PROD only when
`MONEY_PROD_ALLOW=create_article`. All catalogs and names are fictional."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest
import respx

from app.api_backend import ApiBackend
from app.backend import CatalogExists, MoneyUnavailable
from app.mock import MockBackend
from app.models import ArticleCreateIn
from tests.conftest import make_client
from tests.test_api_backend import BASE, _gql, _token, settings
from tests.test_write_activity import _TS, PUB, token

SMID = "0b0e9c3e-1111-4a2b-8c3d-000000000239"
MAIN_ID = "12121212-1212-4121-8121-121212121212"


def article_body(**over: Any) -> bytes:
    data: dict[str, Any] = {"katalog": "99902390", "nazev": "Vrut fiktívny (hlavná)", "smid": SMID}
    data.update(over)
    return json.dumps(data).encode()


def post(client: Any, raw: bytes, tok: str | None) -> Any:
    _TS[0] += 1
    headers = client.headers("POST", "/articles", raw, ts=_TS[0])
    if tok:
        headers["X-Approval-Token"] = tok
    return client.client.post("/articles", content=raw, headers={**headers, "Content-Type": "application/json"})


def art_token(raw: bytes, **over: Any) -> str:
    return token(raw, act="article.create", **over)


class Spy(MockBackend):
    def __init__(self) -> None:
        super().__init__()
        self.creates = 0

    async def create_article(self, article: ArticleCreateIn) -> Any:
        self.creates += 1
        return await super().create_article(article)


# ----- the router: approval, PROD allowlist -----


def test_239_create_needs_the_approval_token_bound_to_the_body() -> None:
    spy = Spy()
    client = make_client(backend=spy, approval_jwt_public_key=PUB)
    raw = article_body()
    assert post(client, raw, None).json()["detail"]["code"] == "approval_missing"
    assert post(client, raw, art_token(article_body(katalog="X1"))).status_code == 403  # token for another body
    assert post(client, raw, token(raw)).status_code == 403  # an activity token is not an article token
    r = post(client, raw, art_token(raw))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["katalog"] == "99902390" and out["unit"] == "ks" and out["reconciled"] is False
    assert spy.creates == 1
    # a variant of the new main card; a taken catalog answers 409 before anything is created
    raw2 = article_body(katalog="9990239000010", nazev="Vrut M10", parent_id=out["id"], smid=SMID[:-1] + "1")
    assert post(client, raw2, art_token(raw2)).json()["parent_id"] == out["id"]
    raw3 = article_body(smid=SMID[:-1] + "2")
    taken = post(client, raw3, art_token(raw3))
    assert taken.status_code == 409 and taken.json()["detail"]["code"] == "catalog_exists"


@pytest.mark.parametrize("bad", ["9990|1", "a~b", "(x)", "a#b", ""])
def test_239_catalog_with_filter_characters_is_refused(bad: str) -> None:
    client = make_client(backend=Spy(), approval_jwt_public_key=PUB)
    raw = article_body(katalog=bad)
    assert post(client, raw, art_token(raw)).status_code == 422


def test_239_prod_allows_only_post_articles_and_only_with_the_variable() -> None:
    spy = Spy()
    closed = make_client(backend=spy, approval_jwt_public_key=PUB, money_agenda_label="PROD")
    raw = article_body()
    r = post(closed, raw, art_token(raw))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "prod_read_only"  # no MONEY_PROD_ALLOW
    opened = make_client(
        backend=spy, approval_jwt_public_key=PUB, money_agenda_label="PROD", money_prod_allow="create_article"
    )
    assert post(opened, raw, art_token(raw)).status_code == 200
    assert spy.creates == 1
    # every other write stays closed on PROD even with the variable
    from tests.test_write_activity import body as activity_body
    from tests.test_write_activity import post as post_activity
    from tests.test_write_activity import token as activity_token

    a = activity_body()
    r = post_activity(opened, a, activity_token(a))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "prod_read_only"
    # an unknown name in the variable opens nothing
    other = make_client(backend=Spy(), approval_jwt_public_key=PUB, money_agenda_label="PROD", money_prod_allow="all")
    raw2 = article_body(smid=SMID[:-1] + "9")
    assert post(other, raw2, art_token(raw2)).status_code == 403


def test_239_catalog_free_check() -> None:
    client = make_client()
    free = client.get("/articles/catalog-free?katalog=FREE-0001").json()
    assert free == {"free": True, "article": None}
    taken = client.get("/articles/catalog-free?katalog=933-8-30-ZN").json()
    assert taken["free"] is False and taken["article"]["katalog"] == "933-8-30-ZN"
    assert client.get("/articles/catalog-free?katalog=a%7Cb").status_code == 422


# ----- the API backend: exact payload, check before the mutation, no retry, reconciliation -----


def _row(**over: Any) -> dict[str, Any]:
    row = {
        "ID": MAIN_ID,
        "Deleted": False,
        "Hidden": False,
        "Kod": None,
        "Katalog": "99902390",
        "Nazev": "Vrut fiktívny (hlavná)",
        "Poznamka": f"SMID:{SMID} · Smart Mail",
        "NadrazenyArtikl_ID": None,
        "CarovyKod": None,
        "HlavniJednotka": {"Kod": "ks"},
        "SeznamJednotek": [],
    }
    row.update(over)
    return row


@respx.mock
async def test_239_payload_holds_only_the_allowed_fields_and_the_card_is_read_back() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    gql = respx.post(f"{BASE}/graphql")
    gql.side_effect = [
        _gql({"Articles": []}),  # catalog free
        _gql({"CreateArticle": {"ID": MAIN_ID, "Katalog": "99902390"}}),
        _gql({"Article": _row()}),  # read back
    ]
    parent = uuid.uuid4()
    out = await ApiBackend(settings()).create_article(
        ArticleCreateIn(katalog="99902390", nazev="Vrut fiktívny", parent_id=parent, smid=SMID)
    )
    check = json.loads(gql.calls[0].request.content)
    assert check["variables"]["filter"] == "Katalog~eq~99902390"
    mutation = json.loads(gql.calls[1].request.content)
    assert "CreateArticle" in mutation["query"]
    assert mutation["variables"] == {
        "a": {
            "Katalog": "99902390",
            "Nazev": "Vrut fiktívny",
            "Poznamka": f"SMID:{SMID} · Smart Mail",
            "NadrazenyArtikl_ID": str(parent),
        }
    }  # never a group, category, unit, VAT or parameter
    assert out.id == uuid.UUID(MAIN_ID) and out.unit == "ks" and out.reconciled is False


@respx.mock
async def test_239_taken_catalog_stops_before_the_mutation() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    gql = respx.post(f"{BASE}/graphql")
    gql.side_effect = [_gql({"Articles": [_row(Poznamka=None, Nazev="Iný artikel")]})]
    with pytest.raises(CatalogExists) as exc:
        await ApiBackend(settings()).create_article(ArticleCreateIn(katalog="99902390", nazev="X", smid=SMID))
    assert exc.value.nazev == "Iný artikel" and len(gql.calls) == 1  # no mutation sent


@respx.mock
async def test_239_timeout_is_never_retried_and_reconciled_once_by_catalog_and_smid() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    gql = respx.post(f"{BASE}/graphql")
    gql.side_effect = [
        _gql({"Articles": []}),
        httpx.ReadTimeout("slow"),  # the mutation: Money may or may not have created the card
        _gql({"Articles": [_row()]}),  # found with our SMID → it is ours
    ]
    out = await ApiBackend(settings()).create_article(ArticleCreateIn(katalog="99902390", nazev="X", smid=SMID))
    assert out.reconciled is True and out.id == uuid.UUID(MAIN_ID)
    assert sum("CreateArticle" in json.loads(c.request.content)["query"] for c in gql.calls) == 1


@respx.mock
async def test_239_timeout_with_a_foreign_card_or_nothing_stays_an_error() -> None:
    _token(respx.post(f"{BASE}/connect/token"), [0])
    gql = respx.post(f"{BASE}/graphql")
    gql.side_effect = [
        _gql({"Articles": []}),
        httpx.ReadTimeout("slow"),
        _gql({"Articles": [_row(Poznamka="iná karta")]}),  # someone else's card → never claimed
    ]
    with pytest.raises(MoneyUnavailable):
        await ApiBackend(settings()).create_article(ArticleCreateIn(katalog="99902390", nazev="X", smid=SMID))
    assert sum("CreateArticle" in json.loads(c.request.content)["query"] for c in gql.calls) == 1
