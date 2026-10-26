"""Bridge settings (CLAUDE.md §13). The bridge runs in the LAN next to Money S4."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class BridgeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    money_backend: Literal["api", "mock"] = "mock"
    money_base_url: str | None = None
    money_client_id: str | None = None
    money_client_secret: SecretStr | None = None
    money_scope: str = "S5Api"
    money_rest_version: str = "v2.0"
    money_agenda_label: Literal["TEST", "PROD"] = "TEST"
    money_page_size: int = 200
    bridge_hmac_secret: SecretStr = SecretStr("dev-only-change-me")
    approval_jwt_public_key: str | None = None
    log_level: str = "INFO"

    @property
    def writes_enabled(self) -> bool:
        """Writes are never enabled in Phase 0. From Phase 4 on they still require a single-use approval JWT,
        and the PRODUCTION agenda additionally needs the admin switch in Settings › Money S4 (W12-13a)."""
        return False


@lru_cache
def get_settings() -> BridgeSettings:
    return BridgeSettings()
