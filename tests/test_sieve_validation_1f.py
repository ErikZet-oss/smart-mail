"""Phase 1f: filter validation, compile_condition safety, permissions, body/header."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role
from app.mail.models import Mailbox, MailboxAccess
from app.mail.sieve import (
    FilterAction,
    FilterCondition,
    FilterRule,
    FilterValidationError,
    apply_live_raw_to_readonly,
    compile_condition,
    compile_filters,
    validate_editable_rules,
)
from tests.conftest import Client, FakeMailServer, make_personal
from tests.test_mail_sync_1c import PASSWORD


def test_1f_compile_condition_rejects_empty_from() -> None:
    with pytest.raises(FilterValidationError) as exc:
        compile_condition(FilterCondition("from", "contains", ""))
    assert exc.value.code == "filter_condition_required"
    assert "podmienku" in exc.value.message


def test_1f_compile_condition_rejects_bad_size() -> None:
    with pytest.raises(FilterValidationError) as exc:
        compile_condition(FilterCondition("size", "gt", "abc"))
    assert exc.value.code == "filter_size_invalid"
    with pytest.raises(FilterValidationError):
        compile_condition(FilterCondition("size", "gt", "0"))
    with pytest.raises(FilterValidationError):
        compile_condition(FilterCondition("size", "gt", "-1"))


def test_1f_compile_condition_never_emits_match_all_subject() -> None:
    with pytest.raises(FilterValidationError):
        compile_condition(FilterCondition("subject", "contains", "  "))
    body = compile_condition(FilterCondition("body", "contains", "urgent"))
    assert body.startswith("body ")
    assert "Subject" not in body
    header = compile_condition(FilterCondition("header", "contains", "1", header_name="X-Priority"))
    assert 'header :contains "X-Priority" "1"' in header
    assert "Subject" not in header


def test_1f_compile_filters_body_requires_extension() -> None:
    script = compile_filters(
        [
            FilterRule(
                id="f1",
                name="Telo",
                conditions=[FilterCondition("body", "contains", "faktúra")],
                actions=[FilterAction("fileinto", "Faktúry"), FilterAction("stop")],
            )
        ]
    )
    assert '"body"' in script
    assert "body :contains" in script


def test_1f_validate_editable_rules_empty_od() -> None:
    with pytest.raises(FilterValidationError) as exc:
        validate_editable_rules(
            [
                FilterRule(
                    id="f1",
                    name="Prázdny Od",
                    conditions=[FilterCondition("from", "contains", "")],
                    actions=[FilterAction("fileinto", "INBOX")],
                )
            ]
        )
    assert exc.value.code == "filter_condition_required"


def test_1f_readonly_raw_comes_from_live_not_client() -> None:
    live = [
        FilterRule(
            id="rc-1",
            name="Regex",
            editable=False,
            raw='# rule:[Regex]\nif header :regex "Subject" "x" { stop; }\n',
            conditions=[],
            actions=[FilterAction("stop")],
        )
    ]
    client = [
        FilterRule(
            id="rc-1",
            name="Regex",
            editable=False,
            raw="# rule:[TAMPERED]\nif true { discard; }\n",
            conditions=[],
            actions=[FilterAction("discard")],
        ),
        FilterRule(
            id="f-new",
            name="Od",
            editable=True,
            raw=None,
            conditions=[FilterCondition("from", "contains", "@acme.test")],
            actions=[FilterAction("fileinto", "Dodávatelia")],
        ),
    ]
    merged = apply_live_raw_to_readonly(client, live)
    readonly = next(r for r in merged if not r.editable)
    assert "TAMPERED" not in (readonly.raw or "")
    assert "regex" in (readonly.raw or "")


@pytest.mark.asyncio
async def test_1f_put_filters_empty_od_returns_422(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    acc = await make_personal(db)
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200
    r = await client.send_json(
        "PUT",
        "/api/settings/mailboxes/default/filters",
        {
            "rules": [
                {
                    "id": "f1",
                    "name": "Prázdny",
                    "enabled": True,
                    "match": "allof",
                    "editable": True,
                    "conditions": [{"field": "from", "op": "contains", "value": ""}],
                    "actions": [{"type": "fileinto", "value": "INBOX"}],
                }
            ]
        },
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "filter_condition_required"
    assert "podmienku" in r.json()["detail"]["message"]


@pytest.mark.asyncio
async def test_1f_put_filters_bad_size_returns_422(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    acc = await make_personal(db)
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200
    r = await client.send_json(
        "PUT",
        "/api/settings/mailboxes/default/filters",
        {
            "rules": [
                {
                    "id": "f1",
                    "name": "Veľkosť",
                    "enabled": True,
                    "match": "allof",
                    "editable": True,
                    "conditions": [{"field": "size", "op": "gt", "value": "abc"}],
                    "actions": [{"type": "fileinto", "value": "INBOX"}],
                }
            ]
        },
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "filter_size_invalid"


@pytest.mark.asyncio
async def test_1f_viewer_cannot_put_filters(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    acc = await make_personal(db, role=Role.viewer)
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200
    r = await client.send_json("PUT", "/api/settings/mailboxes/default/filters", {"rules": []})
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "read_only"
    r = await client.send_json("PUT", "/api/settings/mailboxes/default/vacation", {"enabled": False, "body_sk": "x"})
    assert r.status_code == 403
    r = await client.send_json("POST", "/api/settings/mailboxes/default/sieve/restore")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_1f_no_send_access_cannot_put_filters(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    acc = await make_personal(db, role=Role.sales)
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200
    mailbox = (await db.execute(select(Mailbox).where(Mailbox.email == acc.email))).scalar_one()
    access = (
        await db.execute(
            select(MailboxAccess).where(MailboxAccess.account_id == acc.id, MailboxAccess.mailbox_id == mailbox.id)
        )
    ).scalar_one()
    access.can_send = False
    await db.commit()
    r = await client.send_json(
        "PUT",
        "/api/settings/mailboxes/default/filters",
        {
            "rules": [
                {
                    "id": "f1",
                    "name": "Od",
                    "enabled": True,
                    "editable": True,
                    "conditions": [{"field": "from", "op": "contains", "value": "@x.test"}],
                    "actions": [{"type": "fileinto", "value": "INBOX"}],
                }
            ]
        },
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "mailbox_send_forbidden"
