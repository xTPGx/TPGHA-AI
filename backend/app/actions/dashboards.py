"""Dashboard actions and Lovelace draft generation."""
from __future__ import annotations

from typing import Any

import yaml

from ..models.schemas import AppConfig
from ..models.results import ActionResult
from . import ActionContext


async def open_dashboard(ctx: ActionContext, params: dict[str, Any]) -> ActionResult:
    intent = "open_dashboard"
    household = ctx.config.household.default_household()
    dashboards = household.dashboards if household else None

    key = (params.get("dashboard") or "").strip().lower()
    target = (params.get("target") or "").strip()

    path = None
    label = key or "default"
    if dashboards:
        mapping = {
            "default": dashboards.default,
            "security": dashboards.security,
            "cameras": dashboards.cameras,
            "music": dashboards.music,
            "climate": dashboards.climate,
        }
        # Infer dashboard from a free-text target if no key was given.
        if not key and target:
            for k in mapping:
                if k in target.lower():
                    key = k
                    break
        path = mapping.get(key) or dashboards.default
        label = key or "default"

    resolved = {"dashboard": label, "path": path, "target": target or None}
    msg = (
        f"Opening the {label} dashboard"
        + (f" ({path})" if path else "")
        + (f" for {target}." if target else ".")
        + " (Browser Mod navigation is a placeholder in the MVP.)"
    )
    data = {
        "browser_mod": {
            "service": "browser_mod.navigate",
            "data": {"path": path},
        }
    }
    return ActionResult(success=True, intent=intent, executed=False,
                        message=msg, resolved=resolved, data=data)


def _entity_card(entity_id: str, name: str | None = None) -> dict[str, Any]:
    card: dict[str, Any] = {"type": "tile", "entity": entity_id}
    if name:
        card["name"] = name
    return card


def _mushroom_card(entity_id: str, name: str | None = None) -> dict[str, Any]:
    card: dict[str, Any] = {"type": "custom:mushroom-entity-card", "entity": entity_id}
    if name:
        card["name"] = name
    return card


def _room_entities(room) -> list[str]:
    entities: list[str] = []
    entities.extend(room.lights or [])
    entities.extend(room.fans or [])
    for entity_id in (room.climate, room.speaker, room.display, room.camera, room.lock):
        if entity_id:
            entities.append(entity_id)
    return list(dict.fromkeys(entities))


def _room_card(room, style: str) -> dict[str, Any] | None:
    entities = _room_entities(room)
    if not entities:
        return None
    if style == "mushroom":
        return {
            "type": "vertical-stack",
            "cards": [
                {"type": "heading", "heading": room.name, "icon": "mdi:home-variant"},
                *[_mushroom_card(entity_id) for entity_id in entities],
            ],
        }
    return {
        "type": "entities",
        "title": room.name,
        "show_header_toggle": False,
        "entities": entities,
    }


def _security_cards(config: AppConfig, style: str) -> list[dict[str, Any]]:
    card = _mushroom_card if style == "mushroom" else _entity_card
    cards: list[dict[str, Any]] = []
    if config.devices.locks:
        cards.append({
            "type": "grid",
            "title": "Security",
            "columns": 2,
            "square": False,
            "cards": [card(lock.entity_id, lock.name) for lock in config.devices.locks],
        })
    if config.devices.security_sensors:
        cards.append({
            "type": "entities",
            "title": "Sensors",
            "entities": [s.entity_id for s in config.devices.security_sensors],
        })
    return cards


def _camera_cards(config: AppConfig) -> list[dict[str, Any]]:
    return [
        {"type": "picture-entity", "entity": cam.entity_id, "name": cam.name,
         "camera_view": "live", "show_state": False}
        for cam in config.devices.cameras
    ]


def build_dashboard_draft(config: AppConfig, *, title: str = "TPG Home",
                          style: str = "native", room: str | None = None,
                          include_browser_mod: bool = True) -> dict[str, Any]:
    """Build a Lovelace dashboard draft from approved HomeAI config.

    This intentionally returns a draft rather than writing HA storage directly.
    The user can review/copy/import it, and a later installer can put an
    approval boundary around live dashboard writes.
    """
    style = style if style in {"native", "mushroom"} else "native"
    rooms = config.devices.rooms
    if room:
        needle = room.strip().lower().replace(" ", "_")
        rooms = [r for r in rooms if needle in {r.id.lower(), r.name.lower().replace(" ", "_")}]

    home_cards = [c for r in rooms if (c := _room_card(r, style))]
    if not home_cards:
        home_cards = [{"type": "markdown", "content": "No approved room devices yet."}]

    views: list[dict[str, Any]] = [{
        "title": "Home",
        "path": "tpg-home",
        "icon": "mdi:home-assistant",
        "cards": home_cards,
    }]

    cameras = _camera_cards(config)
    if cameras:
        views.append({
            "title": "Cameras",
            "path": "tpg-cameras",
            "icon": "mdi:cctv",
            "cards": cameras,
        })

    security = _security_cards(config, style)
    if security:
        views.append({
            "title": "Security",
            "path": "tpg-security",
            "icon": "mdi:shield-home",
            "cards": security,
        })

    media_entities = [s.entity_id for s in config.devices.speakers]
    if media_entities:
        views.append({
            "title": "Media",
            "path": "tpg-media",
            "icon": "mdi:speaker",
            "cards": [{"type": "media-control", "entity": e} for e in media_entities],
        })

    dashboard: dict[str, Any] = {
        "title": title,
        "views": views,
    }
    notes = [
        "Draft only: review before importing into Home Assistant dashboards.",
        "Uses standard Lovelace cards by default.",
    ]
    if style == "mushroom":
        notes.append("Mushroom style requires custom:mushroom-* cards installed in HA.")
    if include_browser_mod:
        dashboard["tpg_homeai_browser_mod"] = {
            "service": "browser_mod.navigate",
            "example_data": {"path": "/lovelace/tpg-home"},
        }
        notes.append("Browser Mod can navigate displays to the dashboard after it exists.")

    yaml_text = yaml.safe_dump(dashboard, sort_keys=False, allow_unicode=True)
    return {
        "title": title,
        "style": style,
        "room": room,
        "view_count": len(views),
        "dashboard": dashboard,
        "yaml": yaml_text,
        "notes": notes,
    }
