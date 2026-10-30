"""Phase 2f 17f: shadow switch (default on) and read-only consumption / accuracy for admins."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AiRun, AiSuggestion, Classification, FeatureFlag
from app.auth.models import Role
from app.core.audit import AuditLog
from app.mail.models import FolderMeta, Mailbox, Message
from tests.conftest import Client, FakeMailServer
from tests.test_knowledge_2e import _admin


async def _seed(db: AsyncSession) -> None:
    mailbox = await db.scalar(select(Mailbox).limit(1))
    assert mailbox is not None
    folder = FolderMeta(mailbox_id=mailbox.id, name="Stat", subscribed=True, selectable=True)
    db.add(folder)
    await db.flush()
    now = datetime.now(UTC)
    yesterday = now - timedelta(days=1)
    db.add_all(
        [
            AiRun(
                purpose="classify",
                provider="anthropic",
                model="m",
                cost_usd=Decimal("0.0100"),
                status="ok",
                created_at=yesterday,
            ),
            AiRun(
                purpose="draft",
                provider="anthropic",
                model="m",
                cost_usd=Decimal("0.0500"),
                status="ok",
                created_at=now,
            ),
            AiRun(
                purpose="classify",
                provider="anthropic",
                model="m",
                cost_usd=Decimal("9.0"),
                status="ok",
                created_at=now - timedelta(days=40),
            ),  # outside 30 days
        ]
    )
    for i, (status, edited, reasons, shadow) in enumerate(
        [
            ("approved", False, None, False),
            ("approved", True, None, False),
            ("rejected", None, ["tone", "wrong_data"], False),
            ("rejected", None, ["tone"], False),
            ("pending", None, None, True),
        ]
    ):
        msg = Message(mailbox_id=mailbox.id, folder_id=folder.id, uid=900 + i, flags=[])
        db.add(msg)
        await db.flush()
        db.add(
            AiSuggestion(
                mailbox_id=mailbox.id,
                message_id=msg.id,
                suggestion_type="reply",
                payload={"body": "tajný text"},
                status=status,
                shadow=shadow,
                diff={"edited": edited} if edited is not None else None,
                final_payload={"reject_reasons": reasons} if reasons else None,
            )
        )
        db.add(
            Classification(
                mailbox_id=mailbox.id,
                message_id=msg.id,
                message_id_header=f"stat-{i}@x",
                category="inquiry" if i < 3 else "order",
                status="done",
                payload={},
            )
        )
    await db.commit()


async def test_2f_usage_numbers_for_30_days(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await _admin(client, db, mail_server)
    await _seed(db)
    r = await client.get("/api/settings/ai/usage")
    assert r.status_code == 200, r.text
    u = r.json()
    assert u["total_cost_usd"] == "0.0600" and len(u["days"]) == 2
    assert u["cost_by_purpose"] == {"classify": "0.0100", "draft": "0.0500"}
    assert u["budget_usd"] == "5.00"
    assert u["suggestions"] == {
        "total": 5,
        "shadow": 1,
        "pending": 1,
        "approved": 2,
        "approved_unedited": 1,
        "rejected": 2,
        "approved_unedited_pct": 25,
    }
    assert u["reject_reasons"] == {"tone": 2, "wrong_data": 1}
    assert u["categories"] == {"inquiry": 3, "order": 2}
    assert "tajný" not in r.text
    csv = await client.get("/api/settings/ai/usage.csv")
    assert csv.status_code == 200 and csv.text.startswith("datum;naklady_usd;volania\n")
    assert csv.headers["content-type"].startswith("text/csv")


async def test_2f_shadow_switch_default_on_and_audited(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    assert (await client.get("/api/settings/ai/shadow")).json() == {"replies": True}  # no row → shadow on
    r = await client.send_json("PUT", "/api/settings/ai/shadow", {"replies": False})
    assert r.json() == {"replies": False}
    row = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == "ai_shadow_mode"))
    assert row is not None and row.enabled is False
    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "ai.shadow_mode_changed"))
    assert entry is not None and entry.details == {"feature": "replies", "before": True, "after": False}


async def test_2f_usage_and_shadow_are_admin_only(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server, role=Role.sales)
    assert (await client.get("/api/settings/ai/usage")).status_code == 403
    assert (await client.send_json("PUT", "/api/settings/ai/shadow", {"replies": False})).status_code == 403
