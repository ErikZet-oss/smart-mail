"""Bridge ↔ main app contract fixture (`fixtures/money/bridge_contract.json`).

Regenerate after a deliberate change of the bridge models:  cd bridge && uv run python -m tests.contract_fixture
The bridge test fails when the mock output drifts from the file; the app test parses the file with `app/money/schemas`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.mock import mid
from tests.conftest import make_client

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "money" / "bridge_contract.json"


def _trim(search: dict[str, Any]) -> dict[str, Any]:
    return {**search, "items": search["items"][:2]}


def current() -> dict[str, Any]:
    client = make_client()
    companies = client.get("/sync/companies?count=2").json()
    first = companies["items"][0]["id"]
    receivables = client.get(f"/companies/{first}/receivables").json()
    return {
        "_comment": "FICTIONAL data from the bridge mock — the contract between bridge and app (Phase 3b)",
        "healthz": client.client.get("/healthz").json(),
        "sync_companies": companies,
        "sync_persons": client.get("/sync/persons?count=2").json(),
        "sync_codebook_currencies": client.get("/sync/codebooks/currencies").json(),
        "receivables": receivables[:2],
        "orders": client.get(f"/companies/{first}/orders?since=2020-01-01").json()[:2],
        "deliveries": client.get(f"/companies/{first}/deliveries?since=2020-01-01").json()[:2],
        "delivery_search": _trim(client.get(f"/delivery-notes/issued/search?company_id={first}").json()),
        "activities": client.get(f"/companies/{first}/activities").json()[:2],
        "overdue": client.get("/receivables/overdue?before=2026-10-01&count=2").json(),
        "articles": client.get("/articles/search?code=934-10-A2").json(),
        "catalog_articles": client.get("/articles/search?q=Vrut").json()[:2],
        "catalog_info": client.get(f"/articles/catalog-info?id={mid('article', 100)}&id={mid('article', 101)}").json(),
        "supplier_codes": client.get(f"/suppliers/{first}/article-codes?count=2").json(),
        "sync_article_suppliers": client.get("/sync/article-suppliers?count=2").json(),
        "catalog_free": client.get("/articles/catalog-free?katalog=FREE-0001").json(),
        "catalog_taken": client.get("/articles/catalog-free?katalog=934-10-A2").json(),
        "article_created": _created(),
        "received_notes": (rows := client.get("/delivery-notes/received?centre_id=" + str(_centre())).json()),
        "delivery_note_template": client.get(f"/delivery-notes/received/{rows[0]['id']}/template").json(),
        "delivery_note_created": _note_created(),
    }


def _centre() -> Any:
    from app.mock import mid

    return mid("centre", 1)


def _note_created() -> dict[str, Any]:
    """#247 the body of `POST /delivery-notes/received` (the route needs an approval JWT; the mock answers the same)."""
    import asyncio
    import json as _json
    import uuid

    from app.mock import MockBackend
    from app.models import DeliveryNoteIn
    from tests.test_write_delivery_note import note

    out = asyncio.run(MockBackend().create_delivery_note(DeliveryNoteIn.model_validate(note())))
    data = _json.loads(out.model_dump_json())
    data["id"] = str(uuid.UUID(int=0x247))  # stable ids in the file
    for i, line in enumerate(data["lines"], start=1):
        line["id"] = str(uuid.UUID(int=0x2470 + i))
    return dict(data)


def _created() -> dict[str, Any]:
    """#239 the body of `POST /articles` (the HTTP route needs an approval JWT — the mock backend answers the same)."""
    import asyncio
    import uuid

    from app.mock import MockBackend
    from app.models import ArticleCreateIn

    smid = str(uuid.UUID(int=239))
    out = asyncio.run(
        MockBackend().create_article(ArticleCreateIn(katalog="FIKT-239", nazev="Fiktívny artikel", smid=smid))
    )
    return {**out.model_dump(mode="json"), "id": str(uuid.UUID(int=0x239))}  # stable id in the file


if __name__ == "__main__":
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(current(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {FIXTURE}")
