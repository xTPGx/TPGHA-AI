"""Small, safe config editing helpers for the web UI.

These endpoints intentionally edit only first-class user-managed lists. Discovery
overlays still own entity approvals, and the loader validates the whole config
after every write before the app starts using it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models.schemas import AssistantsConfig, DevicesConfig, PermissionsConfig
from .settings import get_settings


def _path(name: str) -> Path:
    base = get_settings().config_path
    base.mkdir(parents=True, exist_ok=True)
    return base / name


def _read(name: str) -> dict[str, Any]:
    path = _path(name)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _write(name: str, data: dict[str, Any]) -> None:
    path = _path(name)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)


def _validate(name: str, data: dict[str, Any]) -> None:
    try:
        if name == "devices.yaml":
            DevicesConfig(**data)
        elif name == "assistants.yaml":
            AssistantsConfig(**data)
        elif name == "permissions.yaml":
            PermissionsConfig(**data)
    except ValidationError as exc:
        raise ValueError(f"{name} would be invalid: {exc}") from exc


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if v not in (None, "", [], {})}
    if isinstance(value, list):
        return [_clean(v) for v in value if v not in (None, "")]
    return value


def upsert_devices_item(section: str, item: dict[str, Any]) -> dict[str, Any]:
    if section not in {"rooms", "voice_sources", "speakers"}:
        raise ValueError(f"Unsupported devices section '{section}'.")
    data = _read("devices.yaml")
    items = list(data.get(section) or [])
    item = _clean(item)
    item_id = item.get("id")
    if not item_id:
        raise ValueError("Item id is required.")
    replaced = False
    for idx, existing in enumerate(items):
        if isinstance(existing, dict) and existing.get("id") == item_id:
            items[idx] = item
            replaced = True
            break
    if not replaced:
        items.append(item)
    data[section] = items
    _validate("devices.yaml", data)
    _write("devices.yaml", data)
    return {"section": section, "item": item, "created": not replaced}


def upsert_assistant(item: dict[str, Any]) -> dict[str, Any]:
    data = _read("assistants.yaml")
    items = list(data.get("assistants") or [])
    item = _clean(item)
    item_id = item.get("id")
    if not item_id:
        raise ValueError("Assistant id is required.")
    replaced = False
    for idx, existing in enumerate(items):
        if isinstance(existing, dict) and existing.get("id") == item_id:
            items[idx] = item
            replaced = True
            break
    if not replaced:
        items.append(item)
    data["assistants"] = items
    _validate("assistants.yaml", data)
    _write("assistants.yaml", data)
    return {"section": "assistants", "item": item, "created": not replaced}


def upsert_user(item: dict[str, Any]) -> dict[str, Any]:
    data = _read("assistants.yaml")
    items = list(data.get("users") or [])
    item = _clean(item)
    item_id = item.get("id")
    if not item_id:
        raise ValueError("User id is required.")
    replaced = False
    for idx, existing in enumerate(items):
        if isinstance(existing, dict) and existing.get("id") == item_id:
            items[idx] = item
            replaced = True
            break
    if not replaced:
        items.append(item)
    data["users"] = items
    _ensure_admin_not_removed(items, item_id)
    _validate("assistants.yaml", data)
    _write("assistants.yaml", data)
    return {"section": "users", "item": item, "created": not replaced}


def _ensure_admin_not_removed(users: list[Any], edited_id: str) -> None:
    admin_users = [
        user for user in users
        if isinstance(user, dict) and user.get("role") == "admin"
    ]
    if admin_users:
        return
    raise ValueError(
        f"Cannot save user '{edited_id}' because it would leave TPG HomeAI "
        "with no Owner/Admin account."
    )


def upsert_music_account(item: dict[str, Any]) -> dict[str, Any]:
    data = _read("devices.yaml")
    accounts = dict(data.get("music_accounts") or {})
    item = _clean(item)
    item_id = item.pop("id", None)
    if not item_id:
        raise ValueError("Music account id is required.")
    created = item_id not in accounts
    accounts[item_id] = item
    data["music_accounts"] = accounts
    _validate("devices.yaml", data)
    _write("devices.yaml", data)
    return {"section": "music_accounts", "id": item_id, "item": item, "created": created}


def save_permissions(item: dict[str, Any]) -> dict[str, Any]:
    data = _clean(item)
    _validate("permissions.yaml", data)
    _write("permissions.yaml", data)
    return {"section": "permissions", "item": data}
