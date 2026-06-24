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

from .models.schemas import AssistantsConfig, DevicesConfig
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
    except ValidationError as exc:
        raise ValueError(f"{name} would be invalid: {exc}") from exc


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if v not in (None, "", [], {})}
    if isinstance(value, list):
        return [_clean(v) for v in value if v not in (None, "")]
    return value


def upsert_devices_item(section: str, item: dict[str, Any]) -> dict[str, Any]:
    if section not in {"rooms", "voice_sources"}:
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
