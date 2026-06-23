"""Install approved automation drafts into Home Assistant configuration."""
from __future__ import annotations

import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ..homeassistant.rest import HAError, HomeAssistantREST


def ha_config_root() -> Path:
    """Return the mapped Home Assistant config root when running as an add-on."""
    return Path(os.environ.get("HA_CONFIG_DIR", "/config")).expanduser()


def normalize_automation_yaml(proposed_yaml: str, draft_id: int) -> dict[str, Any]:
    data = yaml.safe_load(proposed_yaml) or {}
    if isinstance(data, list):
        if not data:
            raise ValueError("Automation YAML list is empty.")
        data = data[0]
    if not isinstance(data, dict):
        raise ValueError("Automation YAML must be a mapping or list of mappings.")
    alias = str(data.get("alias") or f"TPG HomeAI automation {draft_id}")
    automation_id = data.get("id") or _slug_id(f"tpg_homeai_{draft_id}_{alias}")
    data["id"] = automation_id
    data.setdefault("alias", alias)
    data.setdefault("mode", "single")
    if "trigger" not in data or "action" not in data:
        raise ValueError("Automation YAML must include trigger and action.")
    return data


async def install_automation_yaml(
    *,
    proposed_yaml: str,
    draft_id: int,
    ha: HomeAssistantREST,
    path: str | None = None,
) -> dict[str, Any]:
    automation = normalize_automation_yaml(proposed_yaml, draft_id)
    target = Path(path).expanduser() if path else ha_config_root() / "automations.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)

    existing = _load_existing(target)
    replaced = False
    for idx, item in enumerate(existing):
        if isinstance(item, dict) and item.get("id") == automation["id"]:
            existing[idx] = automation
            replaced = True
            break
    if not replaced:
        existing.append(automation)

    backup_path = None
    if target.exists():
        backup_path = target.with_suffix(
            target.suffix + f".tpg-backup-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        )
        shutil.copy2(target, backup_path)

    with target.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(existing, fh, sort_keys=False, allow_unicode=True)

    reload_error = ""
    try:
        await ha.call_service("automation", "reload", {})
    except HAError as exc:
        reload_error = exc.message

    return {
        "installed": True,
        "installed_id": automation["id"],
        "path": str(target),
        "backup_path": str(backup_path) if backup_path else None,
        "replaced": replaced,
        "reload_ok": not reload_error,
        "reload_error": reload_error,
        "automation": automation,
    }


def _load_existing(path: Path) -> list[Any]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return []
    if isinstance(data, list):
        return data
    raise ValueError(f"{path} must contain a YAML list of automations.")


def _slug_id(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", value.lower()).strip("_")
    return slug[:120] or "tpg_homeai_automation"
