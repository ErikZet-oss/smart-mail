"""D32 (#239) „Založiť artikel v Money“ from a W6h line (MONEY_API 5.5.8b): roles, Settings 14 switch, catalogs
re-checked before the write, SMID stored first, double submit → 409 `in_progress`, partial main + variant, optimistic
lock, audit, catalog proposal. Money is a fake bridge; every catalog, name and ID is fictional."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import jwt
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role
from app.core.audit import AuditLog
from app.money.bridge_client import BridgeRefused, BridgeUnavailable
from app.money.schemas import Article, ArticleCreated, CatalogArticle, CatalogFree
from app.purchasing import new_article, org_settings
from app.purchasing.models import DocumentLine, SupplierItemMapping
from app.purchasing.numbers import normalize_code
from tests.conftest import Client, FakeMailServer
from tests.test_mail_sync_1c import _signed_in
from tests.test_money_3f import PRIV_B64, PUBLIC
from tests.test_purchasing_4a import SUPPLIER, _supplier, money_on
from tests.test_purchasing_4b import ArticleBridge, _bridge, _doc

__all__ = ["_bridge", "money_on"]

MAIN = Article(
    id=uuid.uuid5(uuid.NAMESPACE_URL, "239-main"),
    code=None,
    catalog="9990933",
    name="Skrutka fiktívna",
    ean=None,
    unit="ks",
)
VARIANT = Article(
    id=uuid.uuid5(uuid.NAMESPACE_URL, "239-v"),
    code=None,
    catalog="999093300008",
    name="Skrutka fiktívna M8",
    ean=None,
    unit="ks",
    parent_id=MAIN.id,
)


class CreateBridge(ArticleBridge):
    taken: ClassVar[dict[str, str]] = {}  # katalog → name already in Money
    creates: ClassVar[list[tuple[dict[str, Any], str]]] = []
    fail_on: ClassVar[dict[str, Exception]] = {}  # katalog → error of its create
    created: ClassVar[dict[str, ArticleCreated]] = {}  # smid → card (the bridge is idempotent per SMID)

    async def catalog_free(self, katalog: str) -> CatalogFree:
        name = self.taken.get(katalog)
        return CatalogFree(free=name is None, article=CatalogArticle(katalog=katalog, nazev=name) if name else None)

    async def create_article(self, payload: dict[str, Any], approval_token: str) -> ArticleCreated:
        self.creates.append((payload, approval_token))
        if payload["smid"] in self.created:
            return self.created[payload["smid"]].model_copy(update={"reconciled": True})
        err = self.fail_on.pop(payload["katalog"], None)
        if err is not None:
            raise err
        out = ArticleCreated(
            id=uuid.uuid5(uuid.NAMESPACE_URL, "239-new-" + payload["katalog"]),
            katalog=payload["katalog"],
            nazev=payload["nazev"],
            parent_id=uuid.UUID(payload["parent_id"]) if payload.get("parent_id") else None,
            unit="ks",
        )
        self.created[payload["smid"]] = out
        self.taken[payload["katalog"]] = payload["nazev"]
        return out


@pytest.fixture(autouse=True)
def _create_bridge(monkeypatch: pytest.MonkeyPatch, _bridge: None) -> None:
    CreateBridge.taken = {MAIN.catalog or "": MAIN.name, VARIANT.catalog or "": VARIANT.name}
    CreateBridge.creates, CreateBridge.fail_on, CreateBridge.created = [], {}, {}
    CreateBridge.extra = [MAIN, VARIANT]
    monkeypatch.setattr("app.api.purchasing.BridgeClient", CreateBridge)


@pytest.fixture
async def flag_on(app: FastAPI, db: AsyncSession, money_on: None) -> AsyncIterator[None]:
    app.state.settings.approval_jwt_private_key = SecretStr(PRIV_B64)
    conf = await org_settings.load(db)
    await org_settings.save(db, conf.model_copy(update={"create_article": True}))
    await db.commit()
    yield
    app.state.settings.approval_jwt_private_key = None


async def _open(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, role: Role = Role.warehouse
) -> dict[str, Any]:
    await _signed_in(client, db, mail_server, role=role)
    await _supplier(db)
    doc_id = await _doc(client)
    detail = (await client.get(f"/api/purchasing/documents/{doc_id}")).json()
    return dict(detail)


async def _create(client: Client, detail: dict[str, Any], body: dict[str, Any], line: int = 1) -> Any:
    url = f"/api/purchasing/documents/{detail['id']}/lines/{line}/new-article"
    return await client.send_json("POST", url, {"version": detail["version"], **body})


def _claims(token: str) -> dict[str, Any]:
    return dict(jwt.decode(token, PUBLIC, algorithms=["EdDSA"]))


# ----- pure -----


def test_239_size_from_supplier_text() -> None:
    assert new_article.size_of("Skrutka DIN 933 M10x30 A2") == 10
    assert new_article.size_of("Matica m8 pozink") == 8
    assert new_article.size_of("12") == 12
    assert new_article.size_of("Podložka bez rozmeru") is None
    assert new_article.proposals("9990933", 10)[:2] == ["999093300010", "999093300011"]


def test_239_body_shape() -> None:
    with pytest.raises(ValueError):
        new_article.NewArticleIn.model_validate(
            {"mode": "variant", "variant": {"katalog": "A", "nazev": "B"}, "version": 1}
        )
    with pytest.raises(ValueError):
        new_article.NewArticleIn.model_validate(
            {
                "mode": "main_and_variant",
                "main": {"katalog": "A", "nazev": "B"},
                "variant": {"katalog": "A", "nazev": "C"},
                "version": 1,
            }
        )
    with pytest.raises(ValueError):  # a filter character can never reach Money
        new_article.NewArticleIn.model_validate(
            {"mode": "main", "main": {"katalog": "A|B", "nazev": "B"}, "version": 1}
        )


# ----- roles and the switch -----


async def test_239_switch_off_or_wrong_role_is_refused(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None, app: FastAPI
) -> None:
    detail = await _open(client, db, mail_server)
    assert detail["can_create_article"] is False
    r = await _create(client, detail, {"mode": "main", "main": {"katalog": "N-1", "nazev": "Nový"}})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "create_article_disabled"
    assert CreateBridge.creates == []


async def test_239_sales_role_cannot_create(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, flag_on: None
) -> None:
    await _signed_in(client, db, mail_server, role=Role.sales)
    r = await client.get("/api/purchasing/catalog-proposal?main_catalog=9990933&size=M10")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "role_not_allowed"


# ----- main card -----


async def test_239_main_card_payload_only_allowed_fields_line_picked_code_learned_audited(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, flag_on: None
) -> None:
    detail = await _open(client, db, mail_server, role=Role.accounting)
    assert detail["can_create_article"] is True
    r = await _create(client, detail, {"mode": "main", "main": {"katalog": " 9990777 ", "nazev": "Skrutka nová"}})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "done" and out["main"]["katalog"] == "9990777" and out["variant"] is None
    ((payload, token),) = CreateBridge.creates
    assert set(payload) == {"katalog", "nazev", "smid"}  # never a group, unit, VAT, category or parameter
    claims = _claims(token)
    raw = json.dumps(payload, separators=(",", ":")).encode()
    assert claims["act"] == "article.create" and claims["sha256"] == hashlib.sha256(raw).hexdigest()
    assert claims["company_id"] == str(SUPPLIER)
    line = out["document"]["items"][0]
    assert line["article_id"] == out["article_id"] == out["main"]["id"]
    assert line["match_method"] == "user" and line["line_status"] == "matched"
    assert line["new_article"] is None
    mapping = await db.scalar(
        select(SupplierItemMapping).where(SupplierItemMapping.code_norm == normalize_code("933-10-30-A2"))
    )
    assert mapping is not None and str(mapping.article_id) == out["main"]["id"]
    entries = list(await db.scalars(select(AuditLog).where(AuditLog.action == "purchasing.article_created")))
    assert len(entries) == 1
    d = entries[0].details
    assert d["katalog"] == "9990777" and d["money_id"] == out["main"]["id"] and d["card"] == "main"
    assert d["payload_sha256"] == hashlib.sha256(raw).hexdigest() and entries[0].person_id is not None
    assert "nazev" not in d  # no Money payload in the audit


async def test_239_catalog_taken_409_before_any_write(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, flag_on: None
) -> None:
    detail = await _open(client, db, mail_server)
    r = await _create(client, detail, {"mode": "main", "main": {"katalog": "9990933", "nazev": "Duplicitná"}})
    assert r.status_code == 409 and r.json()["detail"] == {"code": "catalog_exists", "katalog": "9990933"}
    assert CreateBridge.creates == []
    free = await client.get("/api/purchasing/articles/catalog-free?katalog=9990933")
    assert free.json() == {"free": False, "article": {"katalog": "9990933", "nazev": MAIN.name}}
    bad = await client.get("/api/purchasing/articles/catalog-free?katalog=a%7Cb")
    assert bad.status_code == 422


async def test_239_optimistic_lock_and_double_submit(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, flag_on: None
) -> None:
    detail = await _open(client, db, mail_server)
    stale = {**detail, "version": detail["version"] - 1}
    r = await _create(client, stale, {"mode": "main", "main": {"katalog": "N-2", "nazev": "Nový"}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "version_conflict"
    # an attempt still running (its SMID already on the line) → a second click is refused
    line = await db.scalar(select(DocumentLine).where(DocumentLine.line_no == 1))
    assert line is not None
    line.raw = {**line.raw, "_new_article": {"status": "in_progress", "started_at": datetime.now(UTC).isoformat()}}
    await db.commit()
    r = await _create(client, detail, {"mode": "main", "main": {"katalog": "N-2", "nazev": "Nový"}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "in_progress"
    # a crashed attempt (older than the TTL) does not block forever
    line.raw = {
        **line.raw,
        "_new_article": {"status": "in_progress", "started_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat()},
    }
    await db.commit()
    r = await _create(client, detail, {"mode": "main", "main": {"katalog": "N-2", "nazev": "Nový"}})
    assert r.status_code == 200, r.text
    # the same request again after success returns the stored result, nothing new in Money
    again = await _create(client, detail, {"mode": "main", "main": {"katalog": "N-2", "nazev": "Nový"}})
    assert again.status_code == 200 and again.json()["main"] == r.json()["main"]
    assert len(CreateBridge.creates) == 1


async def test_239_timeout_never_retried_then_the_same_smid_reconciles(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, flag_on: None
) -> None:
    detail = await _open(client, db, mail_server)
    CreateBridge.fail_on["N-3"] = BridgeUnavailable("money_timeout")
    r = await _create(client, detail, {"mode": "main", "main": {"katalog": "N-3", "nazev": "Nový"}})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "money_timeout"
    assert len(CreateBridge.creates) == 1  # never retried automatically
    first_smid = CreateBridge.creates[0][0]["smid"]
    # Money did create it after all: the next click sends the SAME SMID, the bridge answers with that card
    CreateBridge.created[first_smid] = ArticleCreated(id=uuid.uuid4(), katalog="N-3", nazev="Nový", unit="ks")
    CreateBridge.taken["N-3"] = "Nový"
    fresh = (await client.get(f"/api/purchasing/documents/{detail['id']}")).json()
    assert fresh["items"][0]["new_article"]["status"] == "failed"
    r = await _create(client, fresh, {"mode": "main", "main": {"katalog": "N-3", "nazev": "Nový"}})
    assert r.status_code == 200, r.text  # the app pre-check skips a catalog it has an SMID for
    assert CreateBridge.creates[1][0]["smid"] == first_smid


# ----- variant / main + variant -----


async def test_239_variant_of_an_existing_main_card(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, flag_on: None
) -> None:
    detail = await _open(client, db, mail_server)
    prop = (await client.get(f"/api/purchasing/catalog-proposal?parent_id={MAIN.id}&size=Skrutka M10x30")).json()
    assert prop == {"katalog": "999093300010", "size": 10, "main_catalog": "9990933"}
    body = {"mode": "variant", "parent_id": str(MAIN.id), "variant": {"katalog": prop["katalog"], "nazev": "M10x30"}}
    r = await _create(client, detail, body)
    assert r.status_code == 200, r.text
    ((payload, _),) = CreateBridge.creates
    assert payload["parent_id"] == str(MAIN.id) and set(payload) == {"katalog", "nazev", "smid", "parent_id"}
    assert r.json()["document"]["items"][0]["article"]["kind"] == "variant"
    # a variant can never be the parent
    detail2 = r.json()["document"]
    bad = await _create(
        client, detail2, {**body, "parent_id": str(VARIANT.id), "variant": {"katalog": "Z-1", "nazev": "x"}}
    )
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "parent_not_main"


async def test_239_proposal_skips_taken_numbers(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, flag_on: None
) -> None:
    await _open(client, db, mail_server)
    CreateBridge.taken.update({"999093300010": "x", "999093300011": "y"})
    prop = (await client.get("/api/purchasing/catalog-proposal?main_catalog=9990933&size=M10")).json()
    assert prop["katalog"] == "999093300012"
    none = (await client.get("/api/purchasing/catalog-proposal?main_catalog=9990933&size=bez")).json()
    assert none == {"katalog": None, "size": None, "main_catalog": "9990933"}


async def test_239_main_and_variant_partial_then_retry_creates_only_the_variant(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, flag_on: None
) -> None:
    detail = await _open(client, db, mail_server)
    body = {
        "mode": "main_and_variant",
        "main": {"katalog": "9990555", "nazev": "Skrutka hlavná"},
        "variant": {"katalog": "999055500010", "nazev": "Skrutka M10"},
    }
    CreateBridge.fail_on["999055500010"] = BridgeRefused(422, "money_error", {"code": "money_error"})
    r = await _create(client, detail, body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "partial" and out["error"] == "money_error" and out["variant"] is None
    assert out["main"]["katalog"] == "9990555" and out["article_id"] is None
    line = out["document"]["items"][0]
    assert line["article_id"] != out["main"]["id"] and line["new_article"]["status"] == "partial"
    assert line["new_article"]["main"]["katalog"] == "9990555"
    # retry: the main card is NOT created again (the stored one is the parent), only the variant
    r2 = await _create(client, out["document"], body)
    assert r2.status_code == 200, r2.text
    done = r2.json()
    assert done["status"] == "done" and done["article_id"] == done["variant"]["id"]
    assert [p["katalog"] for p, _ in CreateBridge.creates] == ["9990555", "999055500010", "999055500010"]
    assert CreateBridge.creates[2][0]["parent_id"] == out["main"]["id"]
    assert done["document"]["items"][0]["article_id"] == done["variant"]["id"]
    cards = [
        e.details["card"]
        for e in await db.scalars(select(AuditLog).where(AuditLog.action == "purchasing.article_created"))
    ]
    assert sorted(cards) == ["main", "variant"]  # one audit entry per card


# ----- bridge client -----


async def test_239_client_posts_signed_body_and_maps_refusals(settings: Any) -> None:
    import httpx

    from tests.test_money_3b import _client

    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if json.loads(req.content)["katalog"] == "TAKEN":
            return httpx.Response(409, json={"detail": {"code": "catalog_exists", "katalog": "TAKEN", "nazev": "x"}})
        return httpx.Response(200, json={"id": str(MAIN.id), "katalog": "N", "nazev": "n", "unit": "ks"})

    client = _client(settings, handler)
    out = await client.create_article({"katalog": "N", "nazev": "n", "smid": "abcdefgh"}, "tok")
    assert out.id == MAIN.id and seen[0].url.path == "/articles"
    assert seen[0].headers["X-Approval-Token"] == "tok" and seen[0].headers["X-Bridge-Signature"]
    with pytest.raises(BridgeRefused) as err:
        await client.create_article({"katalog": "TAKEN", "nazev": "n", "smid": "abcdefgh"}, "tok")
    assert err.value.status == 409 and err.value.code == "catalog_exists" and err.value.detail["katalog"] == "TAKEN"
