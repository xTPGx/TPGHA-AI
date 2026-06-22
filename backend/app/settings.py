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
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

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
