"""#233 main cards and variants (MONEY_API §5.5.8a): picker kinds and order, DL-B11 (never a main card with
variants). Read only. All articles, catalogs and codes are fictional."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role
from app.money.schemas import Article
from app.purchasing.item_matching import line_checks
from app.purchasing.models import DocumentLine, SupplierDocument
from app.purchasing.variants import picker_order
from tests.conftest import Client, FakeMailServer
from tests.test_mail_sync_1c import _signed_in
from tests.test_purchasing_4a import _supplier, money_on
from tests.test_purchasing_4b import A_NUT, ArticleBridge, _bridge, _doc, _sc

__all__ = ["_bridge", "money_on"]


def art(key: str, catalog: str, parent: uuid.UUID | None = None, name: str | None = None) -> Article:
    return Article(
        id=uuid.uuid5(uuid.NAMESPACE_URL, f"233-{key}"),
        code=key.upper(),
        catalog=catalog,
        name=name or f"Fiktívny {key}",
        ean=None,
        unit="ks",
        parent_id=parent,
    )


MAIN = art("main", "9990225")
V36 = art("v36", "99902250036", MAIN.id)
V06 = art("v06", "99902250006", MAIN.id)
V10 = art("v10", "99902250010", MAIN.id)
PLAIN = art("plain", "1234567")


# ----- picker order (pure) -----


def test_233_picker_main_card_then_its_variants_by_catalog_no_duplicates() -> None:
    rows = picker_order([V10, MAIN, PLAIN, V06], {MAIN.id: [V06, V10, V36]}, limit=30)
    assert [(a.catalog, k) for a, k in rows] == [
        ("9990225", "main"),
        ("99902250006", "variant"),
        ("99902250010", "variant"),
        ("99902250036", "variant"),
        ("1234567", "article"),
    ]


def test_233_picker_limit_never_cuts_the_variants_of_the_first_main_card() -> None:
    many = [art(f"x{n}", f"55{n:05d}") for n in range(40)]
    rows = picker_order([MAIN, *many], {MAIN.id: [V06, V10, V36]}, limit=3)
    assert [a.id for a, _ in rows] == [MAIN.id, V06.id, V10.id, V36.id]  # 4 rows > limit 3: variants kept


def test_233_variant_without_its_main_card_stays_a_variant() -> None:
    assert [(a.id, k) for a, k in picker_order([V10], {}, limit=30)] == [(V10.id, "variant")]


# ----- DL-B11 -----


def test_233_DL_B11_check_text_params() -> None:
    lines = [
        DocumentLine(line_no=1, is_fee=False, line_status="needs_review", match_method="supplier_code", raw={}),
        DocumentLine(line_no=2, is_fee=False, line_status="matched", match_method="supplier_code", raw={}),
    ]
    checks = line_checks(SupplierDocument(), lines, None)
    assert checks == [{"id": "DL-B11", "level": "blocking", "params": {"n": 1}}]


async def test_233_DL_B11_cascade_never_ends_on_a_main_card_and_confirm_is_refused(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    await _signed_in(client, db, mail_server, role=Role.warehouse)
    await _supplier(db)
    # the supplier code of line 2 points to A_NUT — which is a main card with two variants in Money
    nut_a = Article(
        id=uuid.uuid4(), code="N-A", catalog="M93410A2-1", name="Matica variant A", ean=None, unit="ks", parent_id=A_NUT
    )
    nut_b = Article(
        id=uuid.uuid4(), code="N-B", catalog="M93410A2-2", name="Matica variant B", ean=None, unit="ks", parent_id=A_NUT
    )
    ArticleBridge.extra = [nut_b, nut_a]
    ArticleBridge.codes = [_sc("934 10 A2", A_NUT, last="7.00", unit="bal", qty="200")]
    doc_id = await _doc(client)
    detail = (await client.get(f"/api/purchasing/documents/{doc_id}")).json()
    two = detail["items"][1]
    assert two["line_status"] == "needs_review" and two["match_method"] == "supplier_code"  # method stays visible
    assert two["article"]["kind"] == "main"
    assert [c["article_id"] for c in two["candidates"]] == [str(nut_a.id), str(nut_b.id)]  # its variants
    assert all(c["kind"] == "variant" for c in two["candidates"])
    b11 = [c for c in detail["checks"] if c["id"] == "DL-B11"]
    assert b11 == [{"id": "DL-B11", "level": "blocking", "params": {"n": 2}}]
    assert detail["status"] == "missing_data"

    url = f"/api/purchasing/documents/{doc_id}/lines/2/article"
    r = await client.send_json(
        "POST", url, {"article_id": str(A_NUT), "unit_factor": "1", "version": detail["version"]}
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "main_card_has_variants"  # never trusts the UI
    r = await client.send_json(
        "POST", url, {"article_id": str(nut_a.id), "unit_factor": "1", "version": detail["version"]}
    )
    assert r.status_code == 200, r.text
    after = r.json()
    assert after["items"][1]["line_status"] == "matched" and after["items"][1]["article"]["kind"] == "variant"
    assert not any(c["id"] == "DL-B11" for c in after["checks"])


async def test_233_DL_B11_a_learned_mapping_to_a_main_card_also_waits_for_a_person(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    from app.purchasing.models import SupplierItemMapping
    from app.purchasing.numbers import normalize_code
    from tests.test_purchasing_4a import SUPPLIER

    await _signed_in(client, db, mail_server, role=Role.warehouse)
    await _supplier(db)
    variant = Article(
        id=uuid.uuid4(), code="N-A", catalog="X-1", name="Matica variant", ean=None, unit="ks", parent_id=A_NUT
    )
    ArticleBridge.extra = [variant]
    db.add(
        SupplierItemMapping(
            supplier_money_id=SUPPLIER,
            code_norm=normalize_code("934 10 A2") or "",
            article_id=A_NUT,
            unit_factor=Decimal("200"),
            uses_count=0,
        )
    )
    await db.commit()
    doc_id = await _doc(client)
    two = (await client.get(f"/api/purchasing/documents/{doc_id}")).json()["items"][1]
    assert (two["line_status"], two["match_method"]) == ("needs_review", "learned")
    assert [c["article_id"] for c in two["candidates"]] == [str(variant.id)]


async def test_233_picker_marks_kinds_through_the_api(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    await _signed_in(client, db, mail_server, role=Role.warehouse)
    variant = Article(
        id=uuid.uuid4(),
        code="N-A",
        catalog="M934-10-A",
        name="Matica DIN 934 M10 A2 variant",
        ean=None,
        unit="ks",
        parent_id=A_NUT,
    )
    ArticleBridge.extra = [variant]
    found = (await client.get("/api/purchasing/articles", params={"q": "Matica"})).json()
    kinds = {a["id"]: a["kind"] for a in found}
    assert kinds[str(A_NUT)] == "main" and kinds[str(variant.id)] == "variant"
    ids = [a["id"] for a in found]
    assert ids.index(str(variant.id)) == ids.index(str(A_NUT)) + 1  # right under its main card
    assert all(  # the plain articles of 4b stay „article“
        k == "article" for i, k in kinds.items() if i not in (str(A_NUT), str(variant.id))
    )
