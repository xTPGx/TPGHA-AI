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


def sync_ha_users(auth_users: list[dict[str, Any]]) -> dict[str, Any]:
    """Sync Home Assistant people into TPG profiles.

    HA owns access level: admin/owner -> TPG admin, everyone else -> resident.
    TPG keeps profile-only settings such as music account, aliases, assistant
    personality, and per-user smart-home safety overrides.
    """
    data = _read("assistants.yaml")
    users = list(data.get("users") or [])
    assistants = list(data.get("assistants") or [])
    changed = False
    created = 0
    updated = 0
    skipped = 0

    for auth_user in auth_users:
        parsed = _parse_ha_user(auth_user)
        if not parsed["name"]:
            skipped += 1
            continue
        idx = _find_synced_user_index(users, parsed)
        if idx is None:
            user_id = _unique_id(_slug(parsed["username"] or parsed["name"]), users)
            role = "admin" if parsed["is_admin"] else _default_non_admin_role(parsed)
            user = {
                "id": user_id,
                "name": parsed["name"],
                "role": role,
                "aliases": sorted({parsed["name"], parsed["username"]} - {""}),
                "ha_user_id": parsed["ha_user_id"],
                "ha_username": parsed["username"],
                "ha_is_admin": parsed["is_admin"],
                "access_source": "home_assistant",
            }
            users.append(user)
            assistants.append(_unique_assistant(_default_assistant_for_synced_user(user), assistants))
            created += 1
            changed = True
            continue

        user = dict(users[idx])
        aliases = set(user.get("aliases") or [])
        aliases.update(v for v in (parsed["name"], parsed["username"]) if v)
        role = "admin" if parsed["is_admin"] else _preserved_non_admin_role(user)
        desired = {
            **user,
            "name": user.get("name") or parsed["name"],
            "role": role,
            "aliases": sorted(aliases),
            "ha_user_id": parsed["ha_user_id"] or user.get("ha_user_id"),
            "ha_username": parsed["username"] or user.get("ha_username"),
            "ha_is_admin": parsed["is_admin"],
            "access_source": "home_assistant",
        }
        if desired != user:
            users[idx] = desired
            updated += 1
            changed = True
        if not _assistant_for_owner(assistants, desired["id"]):
            assistants.append(_unique_assistant(_default_assistant_for_synced_user(desired), assistants))
            changed = True

    data["users"] = users
    data["assistants"] = assistants
    _ensure_admin_not_removed(users, "ha_sync")
    _validate("assistants.yaml", data)
    if changed:
        _write("assistants.yaml", data)
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "total_ha_users": len(auth_users),
        "changed": changed,
    }


def _default_non_admin_role(parsed: dict[str, Any]) -> str:
    identity = _normalize(" ".join([parsed.get("name") or "", parsed.get("username") or ""]))
    if any(token in identity for token in ("kiosk", "houseremote", "roomremote", "wallpanel", "tablet")):
        return "kiosk"
    if "guest" in identity:
        return "guest"
    return "resident"


def _preserved_non_admin_role(user: dict[str, Any]) -> str:
    role = str(user.get("role") or "").strip().lower()
    if role in {"resident", "kiosk", "guest"}:
        return role
    return "resident"


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


def _parse_ha_user(user: dict[str, Any]) -> dict[str, Any]:
    name = str(user.get("name") or user.get("username") or user.get("id") or "").strip()
    username = str(user.get("username") or user.get("name") or "").strip()
    groups = user.get("groups") or user.get("group_ids") or []
    group_ids = {
        str(group.get("id") if isinstance(group, dict) else group).lower()
        for group in groups
    }
    is_admin = bool(
        user.get("is_admin")
        or user.get("is_owner")
        or user.get("owner")
        or "system-admin" in group_ids
        or "admin" in group_ids
        or "administrators" in group_ids
    )
    return {
        "ha_user_id": str(user.get("id") or user.get("user_id") or "").strip(),
        "name": name,
        "username": username,
        "is_admin": is_admin,
    }


def _find_synced_user_index(users: list[Any], parsed: dict[str, Any]) -> int | None:
    targets = {
        _normalize(parsed.get("ha_user_id")),
        _normalize(parsed.get("username")),
        _normalize(parsed.get("name")),
    } - {""}
    for idx, user in enumerate(users):
        if not isinstance(user, dict):
            continue
        identities = {
            _normalize(user.get("ha_user_id")),
            _normalize(user.get("ha_username")),
            _normalize(user.get("id")),
            _normalize(user.get("name")),
            *(_normalize(alias) for alias in user.get("aliases") or []),
        } - {""}
        if identities & targets:
            return idx
    return None


def _default_assistant_for_synced_user(user: dict[str, Any]) -> dict[str, Any]:
    user_id = user["id"]
    assistant_id = _slug(user.get("name") or user_id)
    if user_id == "shawn" or assistant_id == "shawn":
        assistant_id = "atlas"
        name = "Atlas"
        tone = "confident"
        voice = "cedar"
    else:
        name = f"{user.get('name') or user_id} AI"
        tone = "helpful"
        voice = "coral"
    return {
        "id": assistant_id,
        "name": name,
        "owner": user_id,
        "aliases": [assistant_id],
        "wake_words": [assistant_id],
        "listen_enabled": True,
        "tone": tone,
        "personality": f"{name} is {user.get('name') or user_id}'s personal home AI profile.",
        "voice": {
            "provider": "openai",
            "model": "gpt-4o-mini-tts",
            "voice": voice,
            "response_format": "mp3",
            "output": "browser",
            "fallback_provider": "browser",
        },
    }


def _unique_assistant(assistant: dict[str, Any], assistants: list[Any]) -> dict[str, Any]:
    existing = {
        item.get("id") for item in assistants
        if isinstance(item, dict) and item.get("id")
    }
    if assistant["id"] not in existing:
        return assistant
    base = assistant["id"]
    index = 2
    while f"{base}_{index}" in existing:
        index += 1
    assistant = dict(assistant)
    assistant["id"] = f"{base}_{index}"
    assistant["aliases"] = sorted({*assistant.get("aliases", []), assistant["id"]})
    assistant["wake_words"] = sorted({*assistant.get("wake_words", []), assistant["id"]})
    return assistant


def _assistant_for_owner(assistants: list[Any], owner: str) -> dict[str, Any] | None:
    for assistant in assistants:
        if isinstance(assistant, dict) and assistant.get("owner") == owner:
            return assistant
    return None


def _unique_id(base: str, users: list[Any]) -> str:
    base = base or "ha_user"
    existing = {
        user.get("id") for user in users
        if isinstance(user, dict) and user.get("id")
    }
    if base not in existing:
        return base
    index = 2
    while f"{base}_{index}" in existing:
        index += 1
    return f"{base}_{index}"


def _slug(value: Any) -> str:
    text = "".join(ch if ch.isalnum() else "_" for ch in str(value or "").lower())
    return "_".join(part for part in text.split("_") if part)


def _normalize(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


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
