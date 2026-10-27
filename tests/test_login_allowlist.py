"""LOGIN_ALLOWLIST: who may sign in (deploy / Phase 1h-f)."""

from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from tests.conftest import Client, FakeMailServer

PASSWORD = "Spravne-Heslo-1"


def test_login_allowlist_empty_means_internal_domains() -> None:
    s = Settings(internal_domains="smartsro.sk", login_allowlist="")
    assert s.login_allowed("test@smartsro.sk")
    assert not s.login_allowed("cudzi@gmail.com")


def test_login_allowlist_restricts_exact_emails() -> None:
    s = Settings(internal_domains="smartsro.sk", login_allowlist="test@smartsro.sk")
    assert s.login_allowed("test@smartsro.sk")
    assert not s.login_allowed("iny@smartsro.sk")


async def test_login_allowlist_blocks_other_internal(
    client: Client, app: FastAPI, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    app.state.settings.login_allowlist = "test@smartsro.sk"
    mail_server.passwords["iny@smartsro.sk"] = PASSWORD
    mail_server.passwords["test@smartsro.sk"] = PASSWORD
    blocked = await client.login("iny@smartsro.sk", PASSWORD)
    assert blocked.status_code == 401
    assert blocked.json()["detail"]["code"] == "invalid_credentials"
    ok = await client.login("test@smartsro.sk", PASSWORD)
    assert ok.status_code == 200, ok.text
