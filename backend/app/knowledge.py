"""House knowledge graph and proactive intelligence helpers.

The graph is the compact, model-friendly description of the home. It combines
approved HomeAI YAML with HA's area/device/entity registries when available.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .config_loader import get_config
from .discovery import scanner
from .homeassistant.services import safe_get_states
from .homeassistant.websocket import HomeAssistantWebSocket


def _area_name(area_id: str | None, areas: dict[str, dict[str, Any]]) -> str | None:
    if not area_id:
        return None
    area = areas.get(area_id)
    return (area or {}).get("name") or area_id


def _device_name(device: dict[str, Any]) -> str:
    return (
        device.get("name_by_user")
        or device.get("name")
        or device.get("model")
        or device.get("id")
        or "Unknown device"
    )


def _entity_name(entity: dict[str, Any], state_attrs: dict[str, Any] | None = None) -> str:
    attrs = state_attrs or {}
    return (
        entity.get("name")
        or entity.get("original_name")
        or attrs.get("friendly_name")
        or entity.get("entity_id")
        or "Unknown entity"
    )


def _entity_category(entity: dict[str, Any], state_attrs: dict[str, Any] | None = None) -> str:
    entity_id = str(entity.get("entity_id") or "")
    domain = entity_id.split(".", 1)[0]
    category = entity.get("entity_category")
    device_class = entity.get("device_class") or (state_attrs or {}).get("device_class")
    text = f"{entity_id} {category or ''} {device_class or ''}".lower()
    if category == "diagnostic" or any(k in text for k in (
        "battery", "app_version", "bssid", "ssid", "rssi", "signal",
        "last_update", "location_permission", "sim_", "connection_type",
    )):
        return "diagnostic"
    if domain in {"light", "fan", "climate", "lock", "cover", "media_player",
                  "camera", "switch", "alarm_control_panel"}:
        return "controllable"
    if domain in {"person", "device_tracker"}:
        return "presence"
    return "status"


async def fetch_ha_registries() -> dict[str, Any]:
    """Return HA registries, with an error field instead of raising."""
    try:
        return await HomeAssistantWebSocket().fetch_registries()
    except Exception as err:  # noqa: BLE001 - registry enrichment is optional
        return {"areas": [], "devices": [], "entities": [],
                "error": f"{type(err).__name__}: {err}"}


async def build_house_graph(include_registries: bool = True) -> dict[str, Any]:
    config = get_config()
    states = await safe_get_states()
    registries = await fetch_ha_registries() if include_registries else {
        "areas": [], "devices": [], "entities": []
    }

    areas = {a.get("area_id"): a for a in registries.get("areas", []) if a.get("area_id")}
    devices = {d.get("id"): d for d in registries.get("devices", []) if d.get("id")}
    entities = registries.get("entities", []) or []

    device_entities: dict[str, list[dict[str, Any]]] = defaultdict(list)
    ungrouped_entities: list[dict[str, Any]] = []
    for ent in entities:
        entity_id = ent.get("entity_id")
        if not entity_id:
            continue
        state = states.get(entity_id)
        attrs = state.attributes if state else {}
        shaped = {
            "entity_id": entity_id,
            "name": _entity_name(ent, attrs),
            "domain": entity_id.split(".", 1)[0],
            "area": _area_name(ent.get("area_id"), areas),
            "category": _entity_category(ent, attrs),
            "device_class": ent.get("device_class") or attrs.get("device_class"),
            "available": state.available if state else None,
            "state": state.state if state else None,
        }
        device_id = ent.get("device_id")
        if device_id:
            device_entities[device_id].append(shaped)
        else:
            ungrouped_entities.append(shaped)

    enriched_devices: list[dict[str, Any]] = []
    for device_id, device in devices.items():
        ents = device_entities.get(device_id, [])
        area = _area_name(device.get("area_id"), areas)
        if area is None:
            area = next((e.get("area") for e in ents if e.get("area")), None)
        enriched_devices.append({
            "id": device_id,
            "name": _device_name(device),
            "manufacturer": device.get("manufacturer"),
            "model": device.get("model"),
            "area": area,
            "integration": ",".join(device.get("via_device_id") or [])
            if isinstance(device.get("via_device_id"), list) else device.get("via_device_id"),
            "entities": ents,
            "controllable_entities": [e for e in ents if e["category"] == "controllable"],
            "diagnostic_entities": [e for e in ents if e["category"] == "diagnostic"],
        })

    configured_rooms = []
    for room in config.devices.rooms:
        configured_rooms.append({
            "id": room.id,
            "name": room.name,
            "aliases": room.aliases,
            "lights": room.lights,
            "fans": room.fans,
            "speaker": room.speaker,
            "camera": room.camera,
            "display": room.display,
            "lock": room.lock,
            "climate": room.climate,
        })

    summary = await scanner.summary()
    graph = {
        "source": {
            "homeai_config": True,
            "ha_registries": not bool(registries.get("error")),
            "ha_registry_error": registries.get("error"),
        },
        "rooms": configured_rooms,
        "areas": [{"id": a.get("area_id"), "name": a.get("name")} for a in areas.values()],
        "devices": enriched_devices,
        "ungrouped_entities": ungrouped_entities[:250],
        "people": [u.model_dump() for u in config.assistants.users],
        "assistants": [a.model_dump() for a in config.assistants.assistants],
        "voice_sources": [v.model_dump() for v in config.devices.voice_sources],
        "pending_approvals": summary.get("pending_count", 0),
        "unavailable_devices": summary.get("unavailable_count", 0),
        "counts": {
            "rooms": len(configured_rooms),
            "areas": len(areas),
            "devices": len(enriched_devices),
            "entities": len(entities) if entities else len(states),
            "ungrouped_entities": len(ungrouped_entities),
            "voice_sources": len(config.devices.voice_sources),
        },
    }
    graph["physical_devices"] = build_physical_devices(graph)
    return graph


def build_physical_devices(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Group noisy HA entities into real-world devices.

    HA often exposes phones, TVs, and Tuya devices as many entities. This view
    creates one user-facing device record with controllable, presence, status,
    and diagnostic members so the UI/AI can reason about the thing, not the
    entity spam.
    """
    groups: dict[str, dict[str, Any]] = {}

    def add_entity(entity: dict[str, Any], device_name: str | None = None,
                   area: str | None = None) -> None:
        name = device_name or entity.get("name") or entity.get("entity_id") or "Unknown"
        key = _physical_key(name, entity.get("entity_id", ""))
        group = groups.setdefault(key, {
            "id": key,
            "name": _friendly_physical_name(name),
            "area": area or entity.get("area"),
            "device_type": _physical_type(name, entity.get("domain", ""), entity.get("entity_id", "")),
            "entities": [],
            "controllable_entities": [],
            "diagnostic_entities": [],
            "presence_entities": [],
            "status_entities": [],
        })
        group["entities"].append(entity)
        category = entity.get("category")
        if category == "controllable":
            group["controllable_entities"].append(entity)
        elif category == "diagnostic":
            group["diagnostic_entities"].append(entity)
        elif category == "presence":
            group["presence_entities"].append(entity)
        else:
            group["status_entities"].append(entity)

    for device in graph.get("devices", []):
        for ent in device.get("entities", []):
            add_entity(ent, device.get("name"), device.get("area"))

    for ent in graph.get("ungrouped_entities", []):
        add_entity(ent)

    return sorted(groups.values(), key=lambda d: (d.get("area") or "", d.get("name") or ""))


def _physical_key(name: str, entity_id: str) -> str:
    text = f"{name} {entity_id}".lower()
    text = text.replace("_", " ")
    for suffix in (
        " app version", " bssid", " ssid", " sim 1", " sim 2", " audio output",
        " location permission", " geocoded location", " last update trigger",
        " battery level", " battery state", " connection type", " activity",
    ):
        text = text.replace(suffix, " ")
    words = [w for w in text.split() if w not in {"sensor", "device", "tracker"}]
    return "_".join(words[:4]) or entity_id.replace(".", "_")


def _friendly_physical_name(name: str) -> str:
    cleaned = name
    for suffix in (
        " App Version", " BSSID", " SSID", " SIM 1", " SIM 2", " Audio Output",
        " Location permission", " Geocoded Location", " Last Update Trigger",
        " Battery Level", " Battery State", " Connection Type",
    ):
        cleaned = cleaned.replace(suffix, "")
    return cleaned.strip() or name


def _physical_type(name: str, domain: str, entity_id: str) -> str:
    text = f"{name} {domain} {entity_id}".lower()
    if any(k in text for k in ("iphone", "android", "phone")):
        return "phone"
    if any(k in text for k in ("ipad", "tablet")):
        return "tablet"
    if any(k in text for k in ("tv", "television", "monitor", "display")):
        return "display"
    if "fan" in text:
        return "fan"
    if "light" in text or "lamp" in text:
        return "light"
    if domain in {"person", "device_tracker"}:
        return "presence"
    return domain or "device"


def graph_prompt_context(graph: dict[str, Any], max_devices: int = 25) -> str:
    """Compact graph summary for the OpenAI system prompt."""
    rooms = ", ".join(r["name"] for r in graph.get("rooms", [])) or "none"
    lines = [f"House graph rooms: {rooms}."]
    if graph.get("source", {}).get("ha_registries"):
        lines.append("HA registry enrichment is available.")
    else:
        err = graph.get("source", {}).get("ha_registry_error")
        if err:
            lines.append(f"HA registry enrichment unavailable: {err}.")
    devices = graph.get("devices", [])[:max_devices]
    if devices:
        lines.append("Known physical devices:")
        for d in devices:
            controllable = [e["entity_id"] for e in d.get("controllable_entities", [])[:6]]
            diagnostics = len(d.get("diagnostic_entities", []))
            parts = [d.get("name") or d.get("id")]
            if d.get("area"):
                parts.append(f"area={d['area']}")
            if controllable:
                parts.append("controls=" + ", ".join(controllable))
            if diagnostics:
                parts.append(f"diagnostics={diagnostics}")
            lines.append("- " + "; ".join(str(p) for p in parts if p))
    return "\n".join(lines)
