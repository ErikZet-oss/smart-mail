"""Bridge ↔ main app contract fixture (`fixtures/money/bridge_contract.json`).

Regenerate after a deliberate change of the bridge models:  cd bridge && uv run python -m tests.contract_fixture
The bridge test fails when the mock output drifts from the file; the app test parses the file with `app/money/schemas`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.conftest import make_client

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "money" / "bridge_contract.json"


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
        "activities": client.get(f"/companies/{first}/activities").json()[:2],
        "overdue": client.get("/receivables/overdue?before=2026-10-01&count=2").json(),
    }


if __name__ == "__main__":
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(current(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {FIXTURE}")
