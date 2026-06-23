"""Application settings loaded from environment variables.

Secrets (Home Assistant token, OpenAI key) live here and are NEVER logged or
exposed to the frontend. Use `settings.safe_dict()` for any diagnostic output.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- AI ---
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")

    # --- Home Assistant ---
    home_assistant_url: str = Field(default="", alias="HOME_ASSISTANT_URL")
    home_assistant_token: str = Field(default="", alias="HOME_ASSISTANT_TOKEN")
    ha_timeout_seconds: float = Field(default=10.0, alias="HA_TIMEOUT_SECONDS")

    # --- Config / storage ---
    config_dir: str = Field(default="./config", alias="CONFIG_DIR")
    database_url: str = Field(
        default="sqlite:///./tpg_homeai.db", alias="DATABASE_URL"
    )

    # --- Discovery / startup bootstrap (PART 2/3) ---
    scan_on_start: bool = Field(default=True, alias="SCAN_ON_START")
    scan_interval_minutes: int = Field(default=5, alias="SCAN_INTERVAL_MINUTES")
    notify_on_new_devices: bool = Field(default=True, alias="NOTIFY_ON_NEW_DEVICES")
    notify_on_unavailable_devices: bool = Field(
        default=True, alias="NOTIFY_ON_UNAVAILABLE_DEVICES"
    )
    auto_approve_low_risk_entities: bool = Field(
        default=False, alias="AUTO_APPROVE_LOW_RISK_ENTITIES"
    )
    auto_approve_domains: str = Field(default="", alias="AUTO_APPROVE_DOMAINS")
    ha_connect_timeout_seconds: float = Field(
        default=10.0, alias="HA_CONNECT_TIMEOUT_SECONDS"
    )
    initial_scan_timeout_seconds: float = Field(
        default=30.0, alias="INITIAL_SCAN_TIMEOUT_SECONDS"
    )

    # --- Server / CORS ---
    cors_origins: str = Field(default="*", alias="CORS_ORIGINS")

    @property
    def ha_base_url(self) -> str:
        return self.home_assistant_url.rstrip("/")

    @property
    def config_path(self) -> Path:
        return Path(self.config_dir).expanduser()

    @property
    def openai_configured(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def ha_configured(self) -> bool:
        return bool(self.home_assistant_url and self.home_assistant_token)

    @property
    def supervisor_mode(self) -> bool:
        """True when running as an HA add-on talking to the Supervisor proxy."""
        return "supervisor" in self.home_assistant_url

    @property
    def ha_auth_mode(self) -> str:
        if not self.home_assistant_token:
            return "none"
        return "supervisor_token" if self.supervisor_mode else "long_lived_token"

    @property
    def app_mode(self) -> str:
        import os

        if self.supervisor_mode or os.environ.get("SUPERVISOR_TOKEN"):
            return "addon"
        return "standalone"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def auto_approve_domain_list(self) -> list[str]:
        return [d.strip() for d in self.auto_approve_domains.split(",") if d.strip()]

    def safe_dict(self) -> dict:
        """Diagnostic snapshot with secrets masked. Safe to log / return."""
        return {
            "openai_configured": self.openai_configured,
            "openai_model": self.openai_model,
            "home_assistant_url": self.home_assistant_url,
            "ha_configured": self.ha_configured,
            "config_dir": self.config_dir,
            "database_url": _mask_db_url(self.database_url),
        }


def _mask_db_url(url: str) -> str:
    # Hide credentials embedded in a DB URL if present.
    if "@" in url and "//" in url:
        scheme, rest = url.split("//", 1)
        if "@" in rest:
            _creds, host = rest.split("@", 1)
            return f"{scheme}//***@{host}"
    return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
