"""#116 / D8: autonomy per login (07) with the hard rule in code; 17b read-only overview."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.autonomy import ACTIONS, BY_ID, SECTION, clamp, effective_levels, load_levels
from app.ai.models import AccountSettings
from app.auth.models import Account, Role
from app.core.audit import AuditLog
from tests.conftest import Client, FakeMailServer, make_personal
from tests.test_knowledge_2e import PASSWORD, _admin

HARD = [a.id for a in ACTIONS if a.hard]


def test_116_defaults_follow_ai_assistant_table() -> None:
    levels = effective_levels(None)
    assert levels["classify"] == 4 and levels["reply"] == 2 and levels["reminder"] == 1 and levels["followup"] == 3
    assert {"reply", "invoice_attach", "delivery_note", "order_create", "offer", "money_company"} <= set(HARD)


def test_116_hard_actions_never_above_2_whatever_is_stored() -> None:
    stored = {a: 4 for a in HARD} | {"newsletter_feed": 4, "spam_move": 4, "assign": 9, "reply": True}
    levels = effective_levels(stored)
    assert all(levels[a] <= 2 for a in HARD)
    assert levels["newsletter_feed"] == 4  # its max is 4
    assert levels["spam_move"] == 3  # max 3
    assert levels["assign"] == BY_ID["assign"].default  # out of range → default
    assert levels["reply"] == 2  # a bool is not a level
    assert clamp(BY_ID["order_create"], 3) == 2 and clamp(BY_ID["reply"], 0) == 0


async def test_116_login_sets_own_levels_with_reauth_and_audit(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server, role=Role.sales)  # any login, not only admins (D8)
    r = await client.get("/api/settings/ai/autonomy")
    reply = next(a for a in r.json()["actions"] if a["id"] == "reply")
    assert reply == {"id": "reply", "level": 2, "default": 2, "max": 2, "hard": True}

    body = {"levels": {"reply": 1, "assign": 3}}
    r = await client.send_json("PUT", "/api/settings/ai/autonomy", body)
    assert r.status_code == 401 and r.json()["detail"]["code"] == "reauth_required"
    assert (await client.reauth(PASSWORD)).status_code == 200
    r = await client.send_json("PUT", "/api/settings/ai/autonomy", body)
    levels = {a["id"]: a["level"] for a in r.json()["actions"]}
    assert levels["reply"] == 1 and levels["assign"] == 3

    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "ai.autonomy_changed"))
    assert entry is not None
    assert entry.details == {"changed": {"reply": {"before": 2, "after": 1}, "assign": {"before": 2, "after": 3}}}


async def test_116_submitted_3_or_4_for_send_and_money_is_clamped_on_write(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    assert (await client.reauth(PASSWORD)).status_code == 200
    r = await client.send_json(
        "PUT", "/api/settings/ai/autonomy", {"levels": {"reply": 4, "order_create": 3, "unknown": 4}}
    )
    levels = {a["id"]: a["level"] for a in r.json()["actions"]}
    assert levels["reply"] == 2 and levels["order_create"] == 2 and "unknown" not in levels
    row = await db.scalar(select(AccountSettings).where(AccountSettings.section == SECTION))
    assert row is not None and row.data["reply"] == 2 and "unknown" not in row.data


async def test_116_stored_3_or_4_is_ignored_on_read(db: AsyncSession) -> None:
    acc = await make_personal(db)
    db.add(AccountSettings(account_id=acc.id, section=SECTION, data={"reply": 4, "delivery_note": 3}))
    await db.commit()
    levels = await load_levels(db, acc.id)
    assert levels["reply"] == 2 and levels["delivery_note"] == 2


async def test_116_levels_are_per_login(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    other = await make_personal(db, email="eva@smartsro.sk")
    db.add(AccountSettings(account_id=other.id, section=SECTION, data={"reply": 0}))
    await db.commit()
    await _admin(client, db, mail_server)
    reply = next(a for a in (await client.get("/api/settings/ai/autonomy")).json()["actions"] if a["id"] == "reply")
    assert reply["level"] == 2  # eva's choice does not touch this login


async def test_116_overview_17b_is_admin_only_and_read_only(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    other = await make_personal(db, email="eva@smartsro.sk")
    db.add(AccountSettings(account_id=other.id, section=SECTION, data={"reply": 0}))
    await db.commit()
    await _admin(client, db, mail_server)
    rows = (await client.get("/api/settings/ai/autonomy/overview")).json()
    eva = next(r for r in rows if r["email"] == "eva@smartsro.sk")
    assert eva["levels"]["reply"] == 0 and eva["customized"] is True
    assert (await client.send_json("PUT", "/api/settings/ai/autonomy/overview", {})).status_code == 405
    accounts = (await db.scalars(select(Account))).all()
    assert len(rows) == len(accounts)


async def test_116_overview_forbidden_for_non_admin(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server, role=Role.sales)
    assert (await client.get("/api/settings/ai/autonomy/overview")).status_code == 403
