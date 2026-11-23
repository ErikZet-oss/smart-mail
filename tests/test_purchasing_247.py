"""Phase 4c (#247, D33) — the received delivery note is written to Money only as a KONCEPT: DL-B1–B11 again at
approval, roles + Settings 14 switch, SMID stored before the bridge call, double click → 409 `in_progress`, timeout →
`unknown` → reconciled by the same SMID, duplicate in Money (DL-B3), read-back comparison, supplier address path,
Settings 11e template. Money is a fake bridge; every ID, number and name is fictional."""

from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal
from typing import Any, ClassVar

import jwt
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Branch, Role
from app.core.audit import AuditLog
from app.money.bridge_client import BridgeRefused, BridgeUnavailable
from app.money.schemas import DeliveryNoteCreated, DeliveryNoteLineBack, DeliveryNoteTemplate, ReceivedNoteRow
from app.purchasing import org_settings
from app.purchasing.models import SupplierDocument
from tests.conftest import Client, FakeMailServer
from tests.test_mail_sync_1c import _signed_in
from tests.test_money_3f import PRIV_B64, PUBLIC
from tests.test_purchasing_4a import SUPPLIER, _supplier, money_on
from tests.test_purchasing_4b import A_NUT, ArticleBridge, _bridge, _doc, _sc

__all__ = ["_bridge", "money_on"]


def _id(key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"247-{key}"))


CENTRE, WAREHOUSE, SERIES = _id("centre-20"), _id("warehouse-20"), _id("series-dlp-se")
TEMPLATE_ID = _id("template-note")


def template(**line_over: Any) -> dict[str, Any]:
    line: dict[str, Any] = {
        "TypObsahu": 1,
        "TypCeny": 0,
        "DruhSazbyDPH": 2,
        "DphSazba": "23",
        "SazbaDPH_ID": _id("vat-23"),
        "DruhPolozky_ID": _id("item-goods"),
        "VazbaTypVazby": 0,
    }
    line.update(line_over)
    return {
        "id": TEMPLATE_ID,
        "number": "DLP0412/2026",
        "supplier": "Fiktívny dodávateľ s.r.o.",
        "issued_on": "2026-11-18",
        "centre_id": CENTRE,
        "header": {
            "CiselnaRada_ID": SERIES,
            "Stredisko_ID": CENTRE,
            "DruhPohybu_ID": _id("movement-purchase"),
            "DruhSkladovehoPohybu_ID": _id("stock-in"),
            "Predkontace_ID": _id("fp010"),
            "RegistraceDPH_ID": _id("vat-reg"),
            "DruhDokladu_ID": _id("doc-kind"),
            "Group_ID": _id("group-dlp-se"),
            "Mena_ID": _id("eur"),
        },
        "line": line,
        "text_line": None,
    }


class KonceptBridge(ArticleBridge):
    posts: ClassVar[list[tuple[dict[str, Any], str]]] = []
    fail_next: ClassVar[list[Exception]] = []
    made: ClassVar[dict[str, DeliveryNoteCreated]] = {}  # smid → koncept (the bridge reconciles by SMID)
    tweak: ClassVar[dict[str, Any]] = {}  # read-back differences a test wants
    address_empty: ClassVar[bool] = False
    rows: ClassVar[list[ReceivedNoteRow]] = []
    templates: ClassVar[dict[str, dict[str, Any]]] = {}

    async def create_delivery_note(self, payload: dict[str, Any], approval_token: str) -> DeliveryNoteCreated:
        self.posts.append((payload, approval_token))
        smid = payload["smid"]
        if smid in self.made:
            return self.made[smid].model_copy(update={"reconciled": True})
        if self.fail_next:
            raise self.fail_next.pop(0)
        lines = [
            DeliveryNoteLineBack(
                id=uuid.uuid4(),
                number=i,
                order=it["Poradi"],
                qty=Decimal(it["Mnozstvi"]) + Decimal(self.tweak.get("qty_delta", "0")),
                unit_price=Decimal(it["JednCena"]),
                content_type=it["TypObsahu"],
                article_id=uuid.UUID(it["ObsahPolozky"]["Artikl_ID"]) if it.get("ObsahPolozky") else None,
                warehouse_id=uuid.UUID(it["ObsahPolozky"]["Sklad_ID"]) if it.get("ObsahPolozky") else None,
                centre_id=uuid.UUID(it["Stredisko_ID"]),
            )
            for i, it in enumerate(payload["Polozky"], start=1)
        ]
        base = sum(((ln.qty * ln.unit_price).quantize(Decimal("0.01")) for ln in lines), Decimal("0"))
        out = DeliveryNoteCreated(
            id=uuid.uuid4(),
            number=f"DLP{len(self.made) + 500:04d}/2026",
            faze=0,
            schvaleno=False,
            group_id=uuid.UUID(payload["Group_ID"]),
            centre_id=uuid.UUID(payload["Stredisko_ID"]),
            total_base=base,
            total=base,
            address_empty=self.address_empty,
            lines=lines,
        )
        self.made[smid] = out
        return out

    async def received_notes(self, centre_id: uuid.UUID, count: int = 20) -> list[ReceivedNoteRow]:
        return list(self.rows)

    async def delivery_note_template(self, note_id: uuid.UUID) -> DeliveryNoteTemplate | None:
        found = self.templates.get(str(note_id))
        return DeliveryNoteTemplate.model_validate(found) if found else None


@pytest.fixture(autouse=True)
def _koncept_bridge(monkeypatch: pytest.MonkeyPatch, _bridge: None) -> None:
    KonceptBridge.posts, KonceptBridge.fail_next, KonceptBridge.made, KonceptBridge.tweak = [], [], {}, {}
    KonceptBridge.address_empty, KonceptBridge.rows, KonceptBridge.templates = False, [], {TEMPLATE_ID: template()}
    KonceptBridge.codes = [_sc("934-10-A2", A_NUT, unit="bal", qty="200")]
    monkeypatch.setattr("app.api.purchasing.BridgeClient", KonceptBridge)
    monkeypatch.setattr("app.api.settings_dl_template.BridgeClient", KonceptBridge)


@pytest.fixture
async def switch_on(app: FastAPI, db: AsyncSession, money_on: None) -> Any:
    app.state.settings.approval_jwt_private_key = SecretStr(PRIV_B64)
    conf = await org_settings.load(db)
    await org_settings.save(db, conf.model_copy(update={"write_delivery_notes": True}))
    await db.commit()
    yield
    app.state.settings.approval_jwt_private_key = None


async def _branch(db: AsyncSession, *, tpl: dict[str, Any] | None = None, configured: bool = True) -> Branch:
    branch = Branch(name=f"Senica {uuid.uuid4().hex[:6]}")
    if configured:
        branch.money_centre_id, branch.money_warehouse_id = CENTRE, WAREHOUSE
        branch.dl_template_money_id, branch.dl_template_values = TEMPLATE_ID, tpl or template()
    db.add(branch)
    await db.commit()
    return branch


async def _open(
    client: Client,
    db: AsyncSession,
    mail_server: FakeMailServer,
    *,
    role: Role = Role.warehouse,
    tpl: dict[str, Any] | None = None,
    configured: bool = True,
) -> dict[str, Any]:
    await _signed_in(client, db, mail_server, role=role)
    await _supplier(db)
    branch = await _branch(db, tpl=tpl, configured=configured)
    doc_id = await _doc(client)
    doc = await db.get(SupplierDocument, uuid.UUID(doc_id))
    assert doc is not None
    doc.branch_id = branch.id  # the branch must be known before the first open (matching sets the line warehouse)
    await db.commit()
    return dict((await client.get(f"/api/purchasing/documents/{doc_id}")).json())


async def _create(client: Client, detail: dict[str, Any], version: int | None = None) -> Any:
    url = f"/api/purchasing/documents/{detail['id']}/create"
    return await client.send_json("POST", url, {"version": detail["version"] if version is None else version})


# ----- checks, roles, switch -----


async def test_247_DL_B1_DL_B5_DL_B6_block_without_branch_setup(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, switch_on: None
) -> None:
    detail = await _open(client, db, mail_server, configured=False)
    ids = {c["id"] for c in detail["checks"] if c["level"] == "blocking"}
    assert {"DL-B1", "DL-B5", "DL-B6"} <= ids and detail["status"] == "missing_data"
    r = await _create(client, detail)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "checks_failed"
    assert {c["id"] for c in r.json()["detail"]["checks"]} >= {"DL-B1", "DL-B6"}
    assert KonceptBridge.posts == []


async def test_247_DL_B6_vat_rate_not_in_the_template_blocks(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, switch_on: None
) -> None:
    detail = await _open(client, db, mail_server, tpl=template(DphSazba="20"))
    b6 = [c for c in detail["checks"] if c["id"] == "DL-B6"]
    assert b6 and b6[0]["params"]["reason"] == "vat_rate" and b6[0]["params"]["rates"] == ["23"]
    assert (await _create(client, detail)).status_code == 409 and KonceptBridge.posts == []


async def test_247_switch_off_and_roles(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    detail = await _open(client, db, mail_server)
    assert detail["can_write"] is False and detail["write"] is None
    r = await _create(client, detail)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "write_disabled"


async def test_247_sales_role_cannot_write(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, switch_on: None
) -> None:
    await _signed_in(client, db, mail_server, role=Role.sales)
    r = await client.send_json("POST", f"/api/purchasing/documents/{uuid.uuid4()}/create", {"version": 1})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "role_not_allowed"


# ----- the write -----


async def test_247_koncept_payload_readback_audit_and_repeat(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, switch_on: None
) -> None:
    detail = await _open(client, db, mail_server, role=Role.accounting)
    assert detail["can_write"] is True
    assert not [c for c in detail["checks"] if c["level"] == "blocking"], detail["checks"]
    r = await _create(client, detail)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "created" and out["write"]["state"] == "created"
    assert out["write"]["number"] == "DLP0500/2026" and out["write"]["mismatches"] == []
    ((payload, tok),) = KonceptBridge.posts
    # D33 koncept + template values, never guessed
    assert payload["Faze"] == 0 and payload["Schvaleno"] is False
    assert "Schvalil_ID" not in payload and "DatumSchvaleni" not in payload
    assert payload["Nazev"].startswith("Smartmail · ") and len(payload["Nazev"]) <= 100
    assert payload["Group_ID"] == _id("group-dlp-se") and payload["CiselnaRada_ID"] == SERIES
    assert payload["Stredisko_ID"] == CENTRE and payload["Firma_ID"] == str(SUPPLIER)
    assert payload["Odkaz"] == "DL-77812" and payload["ParovaciSymbol"] == "FA-2026-00456"
    assert payload["DatumVystaveni"] == "2026-10-28" and payload["CasSkladovehoPohybu"].count(":") == 2
    assert payload["smid"] == (await db.get(SupplierDocument, uuid.UUID(detail["id"]))).idempotency_key  # type: ignore[union-attr]
    items = payload["Polozky"]
    assert len(items) == 2  # D14: the fee line (Doprava) is not written
    for it in items:
        assert it["TypObsahu"] == 1 and it["TypCeny"] == 0 and it["Stredisko_ID"] == CENTRE  # DL-B9
        assert it["ObsahPolozky"]["Sklad_ID"] == WAREHOUSE and it["SazbaDPH_ID"] == _id("vat-23")
    nut = items[1]
    assert nut["Mnozstvi"] == "2400" and nut["JednCena"] == "0.0403"  # 12 bal × 200, 8.05 / 200 — no rounding to bal
    assert nut["ObsahPolozky"]["PartnerskyKod"] == "934-10-A2"
    assert all(not isinstance(v, float) for it in items for v in it.values())  # Decimal as strings, never float
    claims = jwt.decode(tok, PUBLIC, algorithms=["EdDSA"])
    body = json.dumps(payload, separators=(",", ":")).encode()
    assert claims["act"] == "delivery_note.create" and claims["sha256"] == hashlib.sha256(body).hexdigest()
    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "purchasing.delivery_note_created"))
    assert entry is not None and entry.details["number"] == "DLP0500/2026" and entry.details["koncept"] is True
    assert entry.details["payload_sha256"] == hashlib.sha256(body).hexdigest() and "Polozky" not in entry.details
    # a repeat after success returns the stored result — nothing new in Money
    again = await _create(client, out)
    assert again.status_code == 200 and again.json()["write"]["number"] == "DLP0500/2026"
    assert len(KonceptBridge.posts) == 1
    listed = (await client.get("/api/purchasing/documents?status=all")).json()["items"]
    assert listed[0]["money_number"] == "DLP0500/2026" and listed[0]["status"] == "created"


async def test_247_double_click_and_version_conflict(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, switch_on: None
) -> None:
    detail = await _open(client, db, mail_server)
    stale = await _create(client, detail, version=detail["version"] - 1)
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "version_conflict"
    doc = await db.get(SupplierDocument, uuid.UUID(detail["id"]))
    assert doc is not None
    from datetime import UTC, datetime

    doc.status, doc.readback_diff = "creating", {"started_at": datetime.now(UTC).isoformat()}
    await db.commit()
    r = await _create(client, detail)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "in_progress"
    assert KonceptBridge.posts == []


async def test_247_timeout_unknown_then_the_same_smid_reconciles(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, switch_on: None
) -> None:
    detail = await _open(client, db, mail_server)
    KonceptBridge.fail_next = [BridgeUnavailable("money_unavailable")]
    r = await _create(client, detail)
    assert r.status_code == 503
    fresh = (await client.get(f"/api/purchasing/documents/{detail['id']}")).json()
    assert fresh["status"] == "unknown" and fresh["write"]["state"] == "unknown"
    assert len(KonceptBridge.posts) == 1  # never retried by Smart Mail
    # Money did write it: the next click sends the same SMID and gets that koncept back
    smid = KonceptBridge.posts[0][0]["smid"]
    KonceptBridge.made[smid] = DeliveryNoteCreated(
        id=uuid.uuid4(),
        number="DLP0777/2026",
        faze=0,
        schvaleno=False,
        group_id=None,
        centre_id=None,
        total_base=Decimal("516.72"),
        total=Decimal("516.72"),
        address_empty=False,
        lines=[],
    )
    r = await _create(client, fresh)
    assert r.status_code == 200, r.text
    assert KonceptBridge.posts[1][0]["smid"] == smid
    out = r.json()["write"]
    assert out["number"] == "DLP0777/2026" and out["reconciled"] is True
    assert {m["field"] for m in out["mismatches"]} == {"lines"}  # the read-back had no lines → red banner
    # a koncept in Money: the lines can no longer be changed in Smart Mail
    url = f"/api/purchasing/documents/{detail['id']}/lines/1/non-stock"
    stuck = await client.send_json("POST", url, {"version": r.json()["version"]})
    assert stuck.status_code == 409 and stuck.json()["detail"]["code"] == "document_not_reviewable"


async def test_247_DL_B3_duplicate_in_money(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, switch_on: None
) -> None:
    detail = await _open(client, db, mail_server)
    KonceptBridge.fail_next = [BridgeRefused(409, "duplicate", {"code": "duplicate", "number": "DLP0300/2026"})]
    r = await _create(client, detail)
    assert r.status_code == 409 and r.json()["detail"] == {"code": "duplicate", "number": "DLP0300/2026"}
    fresh = (await client.get(f"/api/purchasing/documents/{detail['id']}")).json()
    b3 = [c for c in fresh["checks"] if c["id"] == "DL-B3"]
    assert fresh["status"] == "missing_data" and b3[0]["params"] == {"number": "DLP0300/2026", "money": True}


async def test_247_refused_by_money_is_write_failed_and_can_be_tried_again(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, switch_on: None
) -> None:
    detail = await _open(client, db, mail_server)
    KonceptBridge.fail_next = [BridgeRefused(403, "prod_read_only", {"code": "prod_read_only"})]
    r = await _create(client, detail)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "prod_read_only"
    fresh = (await client.get(f"/api/purchasing/documents/{detail['id']}")).json()
    assert fresh["write"] == {**fresh["write"], "state": "write_failed", "error": "prod_read_only"}
    assert (await _create(client, fresh)).status_code == 200


async def test_247_readback_mismatch_and_supplier_address_path(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, switch_on: None
) -> None:
    detail = await _open(client, db, mail_server)
    KonceptBridge.tweak = {"qty_delta": "1"}
    KonceptBridge.address_empty = True
    out = (await _create(client, detail)).json()
    fields = {m["field"] for m in out["write"]["mismatches"]}
    assert "qty" in fields and "total" in fields and out["status"] == "created"
    assert KonceptBridge.posts[0][0]["with_address"] is False
    assert (await org_settings.load_state(db)).send_supplier_address is True  # the next writes send the address


# ----- Settings 11e: branch template -----


async def test_247_settings_11e_template_default_pick_and_verify(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    await _signed_in(client, db, mail_server, role=Role.admin)
    branch = await _branch(db, configured=False)
    branch.money_centre_id, branch.money_warehouse_id = CENTRE, WAREHOUSE
    await db.commit()
    other = _id("other-note")
    KonceptBridge.rows = [
        ReceivedNoteRow(
            id=uuid.uuid4(), number="DLP0999/2026", supplier="x", issued_on=None, koncept=True, by_smart_mail=True
        ),
        ReceivedNoteRow(
            id=uuid.UUID(TEMPLATE_ID),
            number="DLP0412/2026",
            supplier="Fiktívny dodávateľ s.r.o.",
            issued_on=None,
            koncept=False,
            by_smart_mail=False,
        ),
    ]
    KonceptBridge.templates[other] = {**template(), "id": other, "centre_id": _id("centre-30")}
    state = (await client.get(f"/api/settings/money/branches/{branch.id}/dl-template")).json()
    assert state["template"]["id"] == TEMPLATE_ID and state["template"]["missing"] == []  # never a Smart Mail note
    rows = (await client.get(f"/api/settings/money/branches/{branch.id}/dl-templates")).json()
    assert [r["selected"] for r in rows] == [False, True]
    bad = await client.send_json("PUT", f"/api/settings/money/branches/{branch.id}/dl-template", {"note_id": other})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "template_other_centre"
    incomplete = _id("incomplete")
    KonceptBridge.templates[incomplete] = {**template(), "id": incomplete, "header": {"CiselnaRada_ID": SERIES}}
    r = await client.send_json("PUT", f"/api/settings/money/branches/{branch.id}/dl-template", {"note_id": incomplete})
    assert r.status_code == 422 and "Group_ID" in r.json()["detail"]["missing"]
    verify = (await client.send_json("POST", f"/api/settings/money/branches/{branch.id}/verify")).json()
    by_id = {row["id"]: row for row in verify["rows"]}
    assert by_id["template"]["ok"] is True and by_id["price_list"]["ok"] is False
    entries = list(await db.scalars(select(AuditLog).where(AuditLog.action == "settings.dl_template")))
    assert entries and entries[0].details["auto"] is True


# ----- pure: quantities and prices (CLAUDE.md §0.1 property-based, D17 no packaging rounding) -----

from hypothesis import given  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from app.purchasing.delivery_note import BranchValues, build_payload  # noqa: E402
from app.purchasing.models import DocumentLine  # noqa: E402

_dec = st.decimals(min_value=Decimal("0.001"), max_value=Decimal("100000"), places=3, allow_nan=False)


@given(qty=_dec, factor=st.integers(min_value=1, max_value=1000), price=_dec)
def test_247_quantity_is_exact_and_price_per_unit_is_4dp(qty: Decimal, factor: int, price: Decimal) -> None:
    from datetime import UTC, datetime

    doc = SupplierDocument(
        kind="delivery_note",
        doc_number="DL-1",
        supplier_money_id=uuid.UUID(int=1),
        idempotency_key="a" * 32,
        filename="x.pdf",
    )
    line = DocumentLine(
        line_no=1,
        name="x",
        is_fee=False,
        qty=qty,
        unit_price=price,
        unit_factor=Decimal(factor),
        line_status="matched",
        article_id=uuid.UUID(int=2),
        warehouse_id=None,
        raw={},
    )
    branch = Branch(name="B", money_centre_id=CENTRE, money_warehouse_id=WAREHOUSE, dl_template_values=template())
    values = BranchValues(CENTRE, WAREHOUSE, SERIES)
    payload, expected = build_payload(
        doc,
        [line],
        branch,
        values,
        now=datetime(2026, 11, 23, 8, tzinfo=UTC),
        issue_on_approval=False,
        with_address=False,
    )
    item = payload["Polozky"][0]
    assert Decimal(item["Mnozstvi"]) == qty * factor  # never rounded to a package
    assert Decimal(item["JednCena"]) == (price / factor).quantize(Decimal("0.0001"), rounding="ROUND_HALF_UP")
    assert expected[0].qty == qty * factor and payload["CasSkladovehoPohybu"] == "2026-11-23T09:00:00"  # local time


async def test_247_settings_11e_branch_warehouse_from_the_money_codebook(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    from datetime import UTC, datetime

    from app.money.models import MoneyCodebook

    await _signed_in(client, db, mail_server, role=Role.admin)
    branch = await _branch(db, configured=False)
    db.add(
        MoneyCodebook(
            kind="warehouses",
            money_id=uuid.UUID(WAREHOUSE),
            code="20",
            name="Senica",
            active=True,
            synced_at=datetime.now(UTC),
        )
    )
    await db.commit()
    listed = (await client.get("/api/settings/money/branches")).json()
    assert [w["code"] for w in listed["warehouses"]] == ["20"]
    url = f"/api/settings/money/branches/{branch.id}"
    bad = await client.send_json("PUT", url, {"reports": {}, "warehouse_id": str(uuid.uuid4())})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "warehouse_unknown"
    ok = await client.send_json("PUT", url, {"reports": {}, "warehouse_id": WAREHOUSE})
    assert ok.status_code == 200 and ok.json()["warehouse_id"] == WAREHOUSE
    kept = await client.send_json("PUT", url, {"reports": {}})  # an older client without the field keeps it
    assert kept.json()["warehouse_id"] == WAREHOUSE
