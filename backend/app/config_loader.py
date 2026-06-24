"""Load and validate YAML configuration into typed Pydantic models.

Config is cached in-process and can be hot-reloaded via /config/reload. If
validation fails, the backend stays up in a DEGRADED state: it serves an empty
but valid config and records the error so /health, the integration, and the
frontend can surface it (PART 10).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from .models.schemas import (
    AppConfig,
    AssistantsConfig,
    DevicesConfig,
    HouseholdConfig,
    PermissionsConfig,
)
from .settings import get_settings

logger = logging.getLogger("tpg.config")

_CACHE: Optional[AppConfig] = None
# Populated when the most recent load failed validation. None when healthy.
_CONFIG_ERROR: Optional[str] = None


class ConfigState:
    """Snapshot of config health for /health and diagnostics."""

    @staticmethod
    def error() -> Optional[str]:
        return _CONFIG_ERROR

    @staticmethod
    def ok() -> bool:
        return _CONFIG_ERROR is None


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        logger.warning("Config file missing: %s", path.name)
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data or {}


_OVERLAY_LIST_KEYS = ["device_aliases", "cameras", "locks", "speakers",
                      "displays", "climate", "security_sensors",
                      "personal_devices", "avoid"]


def _merge_overlay(devices: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Merge discovery-approved entries (config/discovered.yaml) into the
    hand-written devices.yaml so approvals never rewrite the original file."""
    if not overlay:
        return devices
    merged = dict(devices)
    for key in _OVERLAY_LIST_KEYS:
        extra = overlay.get(key) or []
        if not extra:
            continue
        base_list = list(merged.get(key, []) or [])
        if key == "avoid":
            base_list = list({*base_list, *extra})
        else:
            seen = {e.get("entity_id") for e in base_list if isinstance(e, dict)}
            for e in extra:
                if isinstance(e, dict) and e.get("entity_id") in seen:
                    continue
                base_list.append(e)
        merged[key] = base_list
    return merged


def _empty_config() -> AppConfig:
    return AppConfig(
        household=HouseholdConfig(),
        assistants=AssistantsConfig(),
        devices=DevicesConfig(),
        permissions=PermissionsConfig(),
    )


def load_config(config_dir: Optional[Path] = None) -> AppConfig:
    """Read all YAML files and validate them into an AppConfig.

    On failure, returns a minimal valid config and sets the module-level
    config error rather than raising, so the server never crashes on bad YAML.
    """
    global _CONFIG_ERROR
    settings = get_settings()
    base = config_dir or settings.config_path

    try:
        household = HouseholdConfig(**_read_yaml(base / "household.yaml"))
        assistants = AssistantsConfig(**_read_yaml(base / "assistants.yaml"))
        devices_data = _merge_overlay(
            _read_yaml(base / "devices.yaml"),
            _read_yaml(base / "discovered.yaml"),
        )
        devices = DevicesConfig(**devices_data)
        permissions = PermissionsConfig(**_read_yaml(base / "permissions.yaml"))
        config = AppConfig(
            household=household,
            assistants=assistants,
            devices=devices,
            permissions=permissions,
        )
        _ensure_runtime_admin(config)
    except Exception as exc:  # noqa: BLE001 - we intentionally degrade, not crash
        _CONFIG_ERROR = f"{type(exc).__name__}: {exc}"
        logger.error("Config validation failed (degraded mode): %s", _CONFIG_ERROR)
        return _empty_config()

    _CONFIG_ERROR = None
    logger.info(
        "Loaded config: %d household(s), %d user(s), %d assistant(s), "
        "%d room(s), %d camera(s), %d lock(s), %d speaker(s)",
        len(config.household.households),
        len(config.assistants.users),
        len(config.assistants.assistants),
        len(config.devices.rooms),
        len(config.devices.cameras),
        len(config.devices.locks),
        len(config.devices.speakers),
    )
    return config


def _ensure_runtime_admin(config: AppConfig) -> None:
    """Prevent a bad user edit from permanently hiding owner/admin tools.

    This is an in-memory recovery guard. It does not overwrite YAML; once the
    owner can reach the Users page again, they can save the intended role.
    """
    users = config.assistants.users
    if not users or any(user.role == "admin" for user in users):
        return
    preferred = next(
        (
            user for user in users
            if user.id.lower() == "shawn"
            or user.name.lower() == "shawn"
            or "owner" in {alias.lower() for alias in user.aliases}
        ),
        users[0],
    )
    logger.warning(
        "No Owner/Admin user configured; temporarily treating %s as admin for UI recovery.",
        preferred.id,
    )
    preferred.role = "admin"


def get_config() -> AppConfig:
    global _CACHE
    if _CACHE is None:
        _CACHE = load_config()
    return _CACHE


def reload_config() -> AppConfig:
    global _CACHE
    _CACHE = load_config()
    return _CACHE


def config_error() -> Optional[str]:
    return _CONFIG_ERROR
