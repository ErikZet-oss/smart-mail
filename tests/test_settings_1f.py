"""Phase 1f settings: schema, preferences, profile, send-guard docs; sieve compile unit."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.mail.sieve import (
    FilterAction,
    FilterCondition,
    FilterRule,
    VacationSettings,
    compile_filters,
    compile_vacation,
)
from app.settings.schema import schema_document
from tests.conftest import Client, FakeMailServer, make_personal
from tests.test_mail_sync_1c import PASSWORD


def test_1f_settings_schema_has_phase_sections() -> None:
    doc = schema_document()
    ids = {s["id"] for s in doc["sections"]}
    assert {"01", "02", "03", "04", "05", "06", "07", "09", "09b", "10", "11", "12"} <= ids
    # 07 in 2b = summaries only; autonomy matrix = later Phase 2 milestones
    ai = next(s for s in doc["sections"] if s["id"] == "07")
    assert any(f["id"] == "show_ai_summary" for f in ai["fields"])
    root = Path(__file__).resolve().parents[1] / "settings_schema.json"
    assert json.loads(root.read_text(encoding="utf-8"))["version"] == doc["version"]


def test_1f_compile_filters_fileinto() -> None:
    script = compile_filters(
        [
            FilterRule(
                id="f1",
                name="Dodávatelia",
                conditions=[FilterCondition("from", "contains", "@dodavatel.example")],
                actions=[FilterAction("fileinto", "Dodávatelia"), FilterAction("stop")],
            )
        ]
    )
    assert 'fileinto "Dodávatelia"' in script
    assert "stop;" in script


def test_1f_compile_vacation_disabled_is_minimal() -> None:
    assert "vacation" in compile_vacation(VacationSettings(enabled=False))


@pytest.mark.asyncio
async def test_1f_preferences_round_trip(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    acc = await make_personal(db)
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200
    got = await client.get("/api/settings/preferences")
    assert got.status_code == 200, got.text
    body = got.json()
    body["ui"]["classic"] = True
    body["list"]["page_size"] = 25
    saved = await client.send_json("PUT", "/api/settings/preferences", body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["ui"]["classic"] is True
    assert saved.json()["list"]["page_size"] == 25


@pytest.mark.asyncio
async def test_1f_profile_and_nav(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    acc = await make_personal(db)
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200
    nav = await client.get("/api/settings/nav")
    assert nav.status_code == 200
    paths = {s["path"] for s in nav.json()["sections"]}
    assert "preferences" in paths and "filters" in paths and "vacation" in paths
    # non-admin must not see admin sections
    assert "users" not in paths
    profile = await client.get("/api/settings/profile")
    assert profile.status_code == 200
    assert "first_name" in profile.json()


@pytest.mark.asyncio
async def test_1f_schema_endpoint(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    acc = await make_personal(db)
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200
    r = await client.get("/api/settings/schema")
    assert r.status_code == 200
    assert r.json()["phase"] == "3f"
