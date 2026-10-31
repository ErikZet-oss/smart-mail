"""Bridge settings (CLAUDE.md §13). The bridge runs in the LAN next to Money S4."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_HMAC_SECRET = "dev-only-change-me"  # noqa: S105 — refused with MONEY_BACKEND=api


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
    bridge_hmac_key_id: str = "dev"
    bridge_hmac_secret: SecretStr = SecretStr(DEV_HMAC_SECRET)
    approval_jwt_public_key: str | None = None
    log_level: str = "INFO"

    def startup_problem(self) -> str | None:
        """Why the bridge must not start (checked in `create_app`): the real API only on the TEST agenda (Phase 3,
        CLAUDE.md §0) and never with the development HMAC secret."""
        if self.money_backend != "api":
            return None
        if self.money_agenda_label != "TEST":
            return "MONEY_BACKEND=api is allowed only with MONEY_AGENDA_LABEL=TEST"
        if self.bridge_hmac_secret.get_secret_value() in ("", DEV_HMAC_SECRET):
            return "BRIDGE_HMAC_SECRET must be set for MONEY_BACKEND=api"
        if not (self.money_base_url and self.money_client_id and self.money_client_secret):
            return "MONEY_BASE_URL / MONEY_CLIENT_ID / MONEY_CLIENT_SECRET missing"
        return None

    @property
    def writes_enabled(self) -> bool:
        """Phase 3f: writes need the approval public key (every write carries a single-use JWT signed by the app) and
        the TEST agenda. The main switch for people stays in Settings 13a of the app (default off)."""
        return bool(self.approval_jwt_public_key) and self.money_agenda_label == "TEST"


@lru_cache
def get_settings() -> BridgeSettings:
    return BridgeSettings()
