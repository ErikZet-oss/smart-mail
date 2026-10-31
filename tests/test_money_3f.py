"""Phase 3f: CRM activity in Money after a sent invoice / reminder — Ed25519 approval token, switches 13a + 13d,
idempotent SMID, one attempt, failures listed for the admin. Fictional data only; the bridge is faked."""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import OrgSettings
from app.auth.models import Account, Role
from app.core.audit import AuditLog
from app.core.config import Settings
from app.mail.compose_models import ComposeAttachment, ComposeDraft
from app.mail.models import Mailbox
from app.money.activities import (
    FAILED,
    SECTION_ACTIVITIES,
    SECTION_WRITES,
    WRITTEN,
    failed_activities,
    write_activity,
)
from app.money.approval import sign_approval
from app.money.bridge_client import BridgeUnavailable
from app.money.invoice_attach import storage_prefix
from app.money.models import MoneyCodebook
from app.money.schemas import ActivityOut
from tests.conftest import Client, FakeMailServer
from tests.test_mail_sync_1c import PASSWORD, _signed_in

COMPANY = uuid.uuid5(uuid.NAMESPACE_URL, "company-3f")
TYPE_EMAIL = uuid.uuid5(uuid.NAMESPACE_URL, "type-email")
TYPE_REMINDER = uuid.uuid5(uuid.NAMESPACE_URL, "type-reminder")
NOW = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)


def _keys() -> tuple[str, Any]:
    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return base64.b64encode(pem).decode(), private.public_key()


PRIV_B64, PUBLIC = _keys()


class FakeBridge:
    calls: list[tuple[dict[str, Any], str]] = []  # noqa: RUF012
    fail: str | None = None

    async def create_activity(self, payload: dict[str, Any], token: str) -> ActivityOut:
        if FakeBridge.fail:
            raise BridgeUnavailable(FakeBridge.fail)
        FakeBridge.calls.append((payload, token))
        return ActivityOut(id=uuid.uuid4(), created=True)

    async def aclose(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeBridge.calls = []
    FakeBridge.fail = None


def live(settings: Settings) -> Settings:
    return settings.model_copy(update={"feature_money": True, "approval_jwt_private_key": SecretStr(PRIV_B64)})


async def _switches(db: AsyncSession, writes: bool = True, enabled: bool = True) -> None:
    db.add(OrgSettings(section=SECTION_WRITES, data={"enabled": writes}))
    db.add(
        OrgSettings(
            section=SECTION_ACTIVITIES,
            data={"enabled": enabled, "type_email": str(TYPE_EMAIL), "type_reminder": str(TYPE_REMINDER)},
        )
    )
    await db.commit()


async def _sent_draft(db: AsyncSession, mailbox: Mailbox, *, marked: bool = True) -> ComposeDraft:
    draft = ComposeDraft(
        mailbox_id=mailbox.id,
        account_id=await db.scalar(select(Account.id).where(Account.email == mailbox.email)),
        subject="Kópia faktúry FV2600042",
        body_html="<p>Telo e-mailu, ktoré do Money nesmie ísť.</p>",
        to_addrs=[{"email": "faktury@firma.example"}],
        status="sent",
    )
    db.add(draft)
    await db.flush()
    prefix = storage_prefix(draft.id, COMPANY) if marked else f"compose/{draft.id}"
    db.add(
        ComposeAttachment(
            draft_id=draft.id,
            filename="Faktura_FV2600042.pdf",
            content_type="application/pdf",
            size=10,
            storage_key=f"{prefix}/ab/cd/x",
            sha256="0" * 64,
            av_status="clean",
        )
    )
    await db.commit()
    return draft


def test_3f_token_is_ed25519_bound_to_the_body(settings: Settings) -> None:
    body = b'{"a":1}'
    token = sign_approval(live(settings), action="activity.create", company_id=COMPANY, person_id=None, body=body)
    claims = jwt.decode(token, PUBLIC, algorithms=["EdDSA"])
    assert claims["act"] == "activity.create" and claims["company_id"] == str(COMPANY)
    assert claims["sha256"] == hashlib.sha256(body).hexdigest() and claims["exp"] - claims["iat"] == 300
    assert jwt.get_unverified_header(token)["alg"] == "EdDSA"


async def test_3f_activity_written_once_with_subject_and_numbers_only(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    await _switches(db)
    draft = await _sent_draft(db, mailbox)
    outcome = await write_activity(db, live(settings), draft.id, client=FakeBridge())  # type: ignore[arg-type]
    await db.commit()
    assert outcome == "written"
    payload, token = FakeBridge.calls[0]
    assert payload == {
        "company_id": str(COMPANY),
        "type_id": str(TYPE_EMAIL),
        "subject": "Kópia faktúry FV2600042",
        "description": "Faktúry: FV2600042",
        "smid": f"SMID:{draft.id}",
    }
    assert "Telo" not in json.dumps(payload)  # never the mail body
    body = json.dumps(payload, separators=(",", ":")).encode()
    assert jwt.decode(token, PUBLIC, algorithms=["EdDSA"])["sha256"] == hashlib.sha256(body).hexdigest()
    again = await write_activity(db, live(settings), draft.id, client=FakeBridge())  # type: ignore[arg-type]
    assert again == "already_written" and len(FakeBridge.calls) == 1


@pytest.mark.parametrize(
    ("writes", "enabled", "expected"), [(False, True, "switched_off"), (True, False, "switched_off")]
)
async def test_3f_switches(
    client: Client,
    db: AsyncSession,
    mail_server: FakeMailServer,
    settings: Settings,
    writes: bool,
    enabled: bool,
    expected: str,
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    await _switches(db, writes=writes, enabled=enabled)
    draft = await _sent_draft(db, mailbox)
    assert await write_activity(db, live(settings), draft.id, client=FakeBridge()) == expected  # type: ignore[arg-type]
    assert FakeBridge.calls == []


async def test_3f_plain_mail_and_missing_key(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    await _switches(db)
    plain = await _sent_draft(db, mailbox, marked=False)
    assert await write_activity(db, live(settings), plain.id, client=FakeBridge()) == "no_company"  # type: ignore[arg-type]
    draft = await _sent_draft(db, mailbox)
    no_key = settings.model_copy(update={"feature_money": True})
    assert await write_activity(db, no_key, draft.id, client=FakeBridge()) == "approval_key_missing"  # type: ignore[arg-type]


async def test_3f_failure_is_listed_never_retried_then_admin_retry_and_success(
    client: Client,
    db: AsyncSession,
    mail_server: FakeMailServer,
    settings: Settings,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mailbox = await _signed_in(client, db, mail_server, role=Role.admin)
    await _switches(db)
    draft = await _sent_draft(db, mailbox)
    FakeBridge.fail = "money_unavailable"
    assert await write_activity(db, live(settings), draft.id, client=FakeBridge()) == "money_unavailable"  # type: ignore[arg-type]
    await db.commit()
    failed = await failed_activities(db)
    assert [f.object_id for f in failed] == [str(draft.id)] and failed[0].details["error"] == "money_unavailable"

    jobs: list[tuple[Any, ...]] = []

    async def enqueue(self: Any, name: str, *args: Any, **kwargs: Any) -> None:
        jobs.append((name, *args))

    monkeypatch.setattr("arq.connections.ArqRedis.enqueue_job", enqueue)
    app.state.settings.feature_money = True
    try:
        listed = (await client.get("/api/settings/money/activities")).json()
        assert listed["failed"][0]["draft_id"] == str(draft.id)
        r = await client.send_json("POST", f"/api/settings/money/activities/{draft.id}/retry")
        assert r.status_code == 202 and jobs == [("money_activity_job", str(draft.id))]
    finally:
        app.state.settings.feature_money = False
    FakeBridge.fail = None
    assert await write_activity(db, live(settings), draft.id, client=FakeBridge()) == "written"  # type: ignore[arg-type]
    await db.commit()
    assert await failed_activities(db) == []
    assert await db.scalar(select(AuditLog).where(AuditLog.action == WRITTEN)) is not None
    assert await db.scalar(select(AuditLog).where(AuditLog.action == FAILED)) is not None


async def test_3f_settings_writes_needs_reauth_and_key(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, app: FastAPI
) -> None:
    await _signed_in(client, db, mail_server, role=Role.admin)
    r = await client.send_json("PUT", "/api/settings/money/writes", {"enabled": True})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "reauth_required"
    assert (await client.reauth(PASSWORD)).status_code == 200
    r = await client.send_json("PUT", "/api/settings/money/writes", {"enabled": True})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "approval_key_missing"
    app.state.settings.approval_jwt_private_key = SecretStr(PRIV_B64)
    try:
        r = await client.send_json("PUT", "/api/settings/money/writes", {"enabled": True})
        assert r.status_code == 200 and r.json() == {"enabled": True, "key_configured": True}
    finally:
        app.state.settings.approval_jwt_private_key = None


async def test_3f_settings_activities_types_from_codebook_only(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _signed_in(client, db, mail_server, role=Role.admin)
    for money_id, name in ((TYPE_EMAIL, "E-mail"), (TYPE_REMINDER, "Upomienka")):
        db.add(MoneyCodebook(kind="activity-types", money_id=money_id, code=name[:3], name=name, synced_at=NOW))
    await db.commit()
    body = {"enabled": True, "type_email": str(TYPE_EMAIL), "type_reminder": str(uuid.uuid4())}
    r = await client.send_json("PUT", "/api/settings/money/activities", body)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "activity_type_unknown"
    r = await client.send_json(
        "PUT", "/api/settings/money/activities", {"enabled": True, "type_email": str(TYPE_EMAIL)}
    )
    assert r.json()["detail"]["code"] == "activity_type_required"
    body["type_reminder"] = str(TYPE_REMINDER)
    r = await client.send_json("PUT", "/api/settings/money/activities", body)
    assert r.status_code == 200 and [t["name"] for t in r.json()["types"]] == ["E-mail", "Upomienka"]


async def test_3f_enqueue_after_send_only_for_money_drafts_with_switches_on(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.money.activities import enqueue_after_send

    jobs: list[tuple[Any, ...]] = []

    class Pool:
        async def enqueue_job(self, name: str, *args: Any, **kwargs: Any) -> None:
            jobs.append((name, *args))

        async def aclose(self) -> None:
            return None

    async def create_pool(*_: Any, **__: Any) -> Pool:
        return Pool()

    monkeypatch.setattr("arq.create_pool", create_pool)
    mailbox = await _signed_in(client, db, mail_server)
    plain = await _sent_draft(db, mailbox, marked=False)
    money = await _sent_draft(db, mailbox)
    await enqueue_after_send(db, live(settings), money)
    assert jobs == []  # switches off by default
    await _switches(db)
    await enqueue_after_send(db, live(settings), plain)
    await enqueue_after_send(db, settings, money)  # FEATURE_MONEY off
    assert jobs == []
    await enqueue_after_send(db, live(settings), money)
    assert jobs == [("money_activity_job", str(money.id))]
