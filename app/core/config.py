"""Application settings (CLAUDE.md §13). Every variable is documented in .env.example."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- core
    app_env: Literal["dev", "test", "prod"] = "dev"
    app_base_url: str = "http://localhost:8080"
    app_secret_key: SecretStr = SecretStr("dev-only-change-me")
    app_encryption_key: SecretStr | None = None
    log_level: str = "INFO"

    # --- storage
    database_url: str = "postgresql+asyncpg://smartmail:smartmail@localhost:5432/smartmail"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint: str = "http://localhost:8333"
    s3_bucket: str = "smartmail"
    s3_access_key: SecretStr | None = None
    s3_secret_key: SecretStr | None = None
    clamav_host: str = "localhost"

    # --- mailbox login (PRODUCT_SPEC §2.0): the IMAP server Roundcube uses. Per-mailbox servers come with
    # Settings › Schránky; until then every login is verified against this server.
    imap_login_host: str = "localhost"
    imap_login_port: int = Field(default=993, ge=1, le=65535)
    imap_login_security: Literal["ssl", "starttls", "none"] = "ssl"
    imap_login_timeout_s: int = Field(default=10, ge=1, le=60)

    # --- sessions and login protection (CLAUDE.md §11, SCREENS_SPEC W1/W1a)
    session_idle_hours: int = Field(default=12, ge=1)
    session_remember_days: int = Field(default=30, ge=1, le=30)
    login_max_failures: int = Field(default=5, ge=1)
    login_ip_max_failures: int = Field(default=20, ge=1)
    login_lock_minutes: int = Field(default=5, ge=1)
    mfa_max_failures: int = Field(default=5, ge=1)
    mfa_trust_days: int = Field(default=30, ge=1)

    # --- auth (optional providers)
    oidc_ms_client_id: str | None = None
    oidc_ms_client_secret: SecretStr | None = None
    oidc_ms_tenant_id: str | None = None
    oidc_google_client_id: str | None = None
    oidc_google_client_secret: SecretStr | None = None
    vapid_public_key: str | None = None
    vapid_private_key: SecretStr | None = None
    internal_domains: str = "smartsro.sk"

    # --- AI (AI_ASSISTANT.md)
    llm_provider: Literal["anthropic", "bedrock"] = "anthropic"
    anthropic_api_key: SecretStr | None = None
    aws_region: str = "eu-central-1"
    llm_model_classify: str | None = None
    llm_model_draft: str | None = None
    llm_model_extract: str | None = None
    llm_model_assistant: str | None = None
    llm_model_embed: str | None = None
    ai_daily_budget_usd: float = Field(default=5.0, ge=0)  # budget, not money of a document

    # --- Money bridge (MONEY_API.md)
    bridge_url: str = "http://localhost:8100"
    bridge_hmac_key_id: str = "dev"
    bridge_hmac_secret: SecretStr = SecretStr("dev-only-change-me")
    approval_jwt_private_key: SecretStr | None = None

    eshop_feed_url: str | None = None
    sentry_dsn: SecretStr | None = None

    @property
    def cookie_secure(self) -> bool:
        return self.app_base_url.startswith("https://")

    @model_validator(mode="after")
    def _prod_requirements(self) -> Settings:
        if self.app_env == "prod":
            if self.app_secret_key.get_secret_value() in {"dev-only-change-me", "change-me"} or (
                len(self.app_secret_key.get_secret_value()) < 32
            ):
                raise ValueError("APP_SECRET_KEY must be a random value of at least 32 characters in prod")
            if self.app_encryption_key is None:
                raise ValueError("APP_ENCRYPTION_KEY is required in prod")
            if self.imap_login_security == "none":
                raise ValueError("IMAP_LOGIN_SECURITY=none is not allowed in prod (passwords would travel unencrypted)")
        return self

    @property
    def internal_domain_list(self) -> list[str]:
        return [d.strip().lower() for d in self.internal_domains.split(",") if d.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
