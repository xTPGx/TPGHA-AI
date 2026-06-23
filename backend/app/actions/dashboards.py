"""Dashboard actions and Lovelace draft generation."""
from __future__ import annotations

from typing import Any
from pathlib import Path
import os
import re

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


def _device_overview_cards(config: AppConfig, style: str) -> list[dict[str, Any]]:
    card = _mushroom_card if style == "mushroom" else _entity_card
    groups: list[tuple[str, str, list[tuple[str, str]]]] = [
        ("Lighting and Switches", "mdi:lightbulb-group", [
            (d.entity_id, d.name) for d in config.devices.device_aliases
            if (d.domain or d.entity_id.split(".", 1)[0]) in {"light", "switch", "fan"}
        ]),
        ("Personal Devices", "mdi:cellphone-link", [
            (d.entity_id, d.name) for d in config.devices.personal_devices
        ]),
        ("Displays", "mdi:television", [
            (d.entity_id, d.name) for d in config.devices.displays if d.entity_id
        ]),
        ("Speakers", "mdi:speaker", [
            (d.entity_id, d.name) for d in config.devices.speakers
        ]),
        ("Climate", "mdi:thermostat", [
            (d.entity_id, d.name) for d in config.devices.climate
        ]),
    ]
    cards: list[dict[str, Any]] = []
    for title, icon, entities in groups:
        unique = list(dict.fromkeys((eid, name) for eid, name in entities if eid))
        if not unique:
            continue
        cards.append({
            "type": "grid",
            "title": title,
            "columns": 2,
            "square": False,
            "cards": [
                {"type": "heading", "heading": title, "icon": icon},
                *[card(entity_id, name) for entity_id, name in unique],
            ] if style == "mushroom" else [card(entity_id, name) for entity_id, name in unique],
        })
    return cards


def _voice_source_cards(config: AppConfig) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for source in config.devices.voice_sources:
        cards.append({
            "type": "markdown",
            "content": (
                f"### {source.name}\n"
                f"- Room: `{source.room}`\n"
                f"- Source device: `{source.source_device_id or 'not set'}`\n"
                f"- Source entity: `{source.source_entity_id or 'not set'}`"
                f"\n- Trust: `{source.trust_level}`"
                f"\n- Default reply: `{source.default_reply}`"
            ),
        })
    return cards


def _voice_panel_cards(config: AppConfig) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = [
        {
            "type": "markdown",
            "content": (
                "## TPG HomeAI Voice Panel\n"
                "Use the Chat page, HA Assist, or configured voice sources to talk to the house."
            ),
        }
    ]
    for assistant in config.assistants.assistants:
        voice = assistant.voice.model_dump() if hasattr(assistant.voice, "model_dump") else {"preset": assistant.voice}
        cards.append({
            "type": "markdown",
            "content": (
                f"### {assistant.name}\n"
                f"- Owner: `{assistant.owner}`\n"
                f"- Tone: `{assistant.tone}`\n"
                f"- Voice: `{voice.get('voice', voice.get('preset', 'browser'))}`\n"
                f"- Provider: `{voice.get('provider', 'browser')}`"
            ),
        })
    return cards


def _tablet_view_cards(config: AppConfig) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for display in config.devices.displays:
        cards.append({
            "type": "markdown",
            "content": (
                f"### {display.name}\n"
                f"- Type: `{display.type}`\n"
                f"- Entity: `{display.entity_id or 'not set'}`\n"
                f"- Browser ID: `{display.browser_id or 'not set'}`\n"
                f"- Dashboard: `{display.dashboard_path or '/lovelace/tpg-home'}`"
            ),
        })
    return cards


def build_dashboard_draft(config: AppConfig, *, title: str = "TPG Home",
                          style: str = "native", room: str | None = None,
                          include_browser_mod: bool = True,
                          include_unavailable: bool = False,
                          tablet_mode: bool = False,
                          voice_panel: bool = False) -> dict[str, Any]:
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

    device_cards = _device_overview_cards(config, style)
    voice_cards = _voice_source_cards(config)
    if device_cards or voice_cards:
        views.append({
            "title": "Devices",
            "path": "tpg-devices",
            "icon": "mdi:devices",
            "cards": device_cards + voice_cards,
        })

    if voice_panel:
        views.append({
            "title": "Voice",
            "path": "tpg-voice",
            "icon": "mdi:microphone-message",
            "cards": _voice_panel_cards(config),
        })

    if tablet_mode:
        views.append({
            "title": "Tablets",
            "path": "tpg-tablets",
            "icon": "mdi:tablet-dashboard",
            "cards": _tablet_view_cards(config) or [
                {"type": "markdown", "content": "No display/tablet profiles configured yet."}
            ],
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
    if tablet_mode:
        notes.append("Tablet mode adds a display/profile view for wall panels and Browser Mod targets.")
    if voice_panel:
        notes.append("Voice panel adds assistant voice profile and source readiness cards.")
    if include_unavailable:
        notes.append("Unavailable devices are included when Home Assistant exposes them in approved config.")

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


def install_dashboard_yaml(yaml_text: str, title: str) -> dict[str, Any]:
    root = Path(os.environ.get("HA_CONFIG_DIR", "/config")).expanduser()
    folder = root / "tpg_homeai_dashboards"
    folder.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", title.lower()).strip("_") or "tpg_home"
    path = folder / f"{slug}.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    return {
        "installed": True,
        "path": str(path),
        "dashboard_key": slug,
        "note": (
            "Dashboard YAML written. Add it to Lovelace YAML dashboards or use "
            "the HA UI to import/recreate it from this file."
        ),
    }
