"""Device adapter hints for real-world Home Assistant quirks.

This is intentionally advisory. Actions still use vetted service calls, but the
adapter map gives the UI and recovery brain a grounded answer to "how should
this actual device be controlled?"
"""
from __future__ import annotations

from typing import Any


def build_device_adapters(graph: dict[str, Any]) -> dict[str, Any]:
    adapters: list[dict[str, Any]] = []
    for device in graph.get("physical_devices", []):
        entities = device.get("entities", []) or []
        hints = [_hint_for_entity(entity) for entity in entities]
        hints = [hint for hint in hints if hint]
        if not hints:
            continue
        adapters.append({
            "device_id": device.get("id"),
            "name": device.get("name"),
            "area": device.get("area"),
            "device_type": device.get("device_type"),
            "entities": hints,
            "recovery": _recovery_for_hints(hints),
        })
    return {
        "adapters": adapters,
        "counts": {
            "devices": len(adapters),
            "entities": sum(len(a["entities"]) for a in adapters),
            "with_recovery": sum(1 for a in adapters if a["recovery"]),
        },
    }


def _hint_for_entity(entity: dict[str, Any]) -> dict[str, Any] | None:
    domain = entity.get("domain")
    entity_id = entity.get("entity_id")
    attrs = entity.get("attributes") or {}
    if not entity_id:
        return None

    if domain == "fan":
        preset_modes = attrs.get("preset_modes") or []
        supports_percentage = bool(attrs.get("percentage") is not None)
        return {
            "entity_id": entity_id,
            "domain": domain,
            "adapter": "fan_percentage_or_preset",
            "services": (
                ["fan.set_percentage", "fan.turn_on", "fan.turn_off"]
                if supports_percentage
                else ["fan.set_preset_mode", "fan.turn_on", "fan.turn_off"]
            ),
            "capabilities": {
                "percentage": supports_percentage,
                "preset_modes": preset_modes,
            },
            "quirks": [] if supports_percentage else ["preset_mode_fallback"],
        }

    if domain == "media_player":
        supported = attrs.get("supported_features")
        return {
            "entity_id": entity_id,
            "domain": domain,
            "adapter": "media_power_volume_source",
            "services": [
                "media_player.turn_on",
                "media_player.turn_off",
                "media_player.volume_set",
                "media_player.select_source",
                "media_player.media_stop",
            ],
            "capabilities": {
                "supported_features": supported,
                "source_list": attrs.get("source_list") or [],
            },
            "quirks": ["state_may_lag"] if entity.get("state") in {"unknown", "unavailable"} else [],
        }

    if domain == "cover":
        has_position = "current_position" in attrs
        return {
            "entity_id": entity_id,
            "domain": domain,
            "adapter": "cover_state_or_position",
            "services": ["cover.open_cover", "cover.close_cover", "cover.stop_cover"],
            "capabilities": {
                "device_class": attrs.get("device_class"),
                "position_feedback": has_position,
                "current_position": attrs.get("current_position"),
            },
            "quirks": [] if has_position else ["state_only_cover_feedback"],
        }

    if domain == "climate":
        modes = attrs.get("hvac_modes") or []
        return {
            "entity_id": entity_id,
            "domain": domain,
            "adapter": "climate_mode_temperature",
            "services": ["climate.set_hvac_mode", "climate.set_temperature"],
            "capabilities": {
                "hvac_modes": modes,
                "current_temperature": "current_temperature" in attrs,
                "target_temperature": "temperature" in attrs,
            },
            "quirks": [] if modes else ["hvac_modes_unknown"],
        }

    if domain == "vacuum":
        return {
            "entity_id": entity_id,
            "domain": domain,
            "adapter": "vacuum_state_family",
            "services": ["vacuum.start", "vacuum.stop", "vacuum.return_to_base"],
            "capabilities": {
                "supported_features": attrs.get("supported_features"),
                "fan_speed_list": attrs.get("fan_speed_list") or [],
                "battery_level": attrs.get("battery_level"),
            },
            "quirks": ["state_family_feedback"],
        }

    if domain == "number":
        return {
            "entity_id": entity_id,
            "domain": domain,
            "adapter": "number_range_value",
            "services": ["number.set_value"],
            "capabilities": {
                "min": attrs.get("min"),
                "max": attrs.get("max"),
                "step": attrs.get("step"),
                "mode": attrs.get("mode"),
            },
            "quirks": [] if attrs.get("min") is not None and attrs.get("max") is not None else ["range_unknown"],
        }

    if domain == "select":
        options = attrs.get("options") or []
        return {
            "entity_id": entity_id,
            "domain": domain,
            "adapter": "select_option_state",
            "services": ["select.select_option"],
            "capabilities": {"options": options},
            "quirks": [] if options else ["options_unknown"],
        }

    if domain == "humidifier":
        return {
            "entity_id": entity_id,
            "domain": domain,
            "adapter": "humidifier_power_humidity",
            "services": ["humidifier.turn_on", "humidifier.turn_off", "humidifier.set_humidity"],
            "capabilities": {
                "humidity": "humidity" in attrs,
                "min_humidity": attrs.get("min_humidity"),
                "max_humidity": attrs.get("max_humidity"),
            },
            "quirks": [] if "humidity" in attrs else ["humidity_feedback_unknown"],
        }

    if domain == "water_heater":
        modes = attrs.get("operation_list") or []
        return {
            "entity_id": entity_id,
            "domain": domain,
            "adapter": "water_heater_mode_temperature",
            "services": ["water_heater.set_operation_mode", "water_heater.set_temperature"],
            "capabilities": {
                "operation_list": modes,
                "temperature": "temperature" in attrs,
            },
            "quirks": [] if modes else ["operation_modes_unknown"],
        }

    if domain == "valve":
        return {
            "entity_id": entity_id,
            "domain": domain,
            "adapter": "valve_open_close",
            "services": ["valve.open_valve", "valve.close_valve"],
            "capabilities": {
                "device_class": attrs.get("device_class"),
                "state_feedback": True,
            },
            "quirks": ["open_may_be_sensitive"],
        }

    if domain in {"light", "switch"}:
        return {
            "entity_id": entity_id,
            "domain": domain,
            "adapter": "basic_power_brightness",
            "services": [f"{domain}.turn_on", f"{domain}.turn_off"],
            "capabilities": {
                "brightness": "brightness" in attrs or "brightness_pct" in attrs,
            },
            "quirks": [],
        }

    if domain == "lock":
        return {
            "entity_id": entity_id,
            "domain": domain,
            "adapter": "security_lock",
            "services": ["lock.lock", "lock.unlock"],
            "capabilities": {"lock": True, "unlock": True},
            "quirks": ["unlock_requires_pin"],
        }

    if domain in {"person", "device_tracker"} or _looks_personal_device(entity):
        return {
            "entity_id": entity_id,
            "domain": domain,
            "adapter": "personal_presence_device",
            "services": [],
            "capabilities": {"presence": True, "diagnostic": True},
            "quirks": ["do_not_control", "group_diagnostics"],
        }

    return None


def _looks_personal_device(entity: dict[str, Any]) -> bool:
    text = f"{entity.get('entity_id', '')} {entity.get('friendly_name', '')}".lower()
    return any(word in text for word in ("iphone", "ipad", "android", "watch", "phone"))


def _recovery_for_hints(hints: list[dict[str, Any]]) -> list[str]:
    recovery: list[str] = []
    for hint in hints:
        if "preset_mode_fallback" in hint.get("quirks", []):
            recovery.append("If percentage speed fails, retry with fan.set_preset_mode.")
        if hint.get("domain") == "media_player":
            recovery.append("If power state does not change, verify media_player support and try turn_on/turn_off service directly.")
        if hint.get("domain") == "cover":
            recovery.append("If cover state does not change, compare open/closed state with current_position feedback.")
        if hint.get("domain") == "climate":
            recovery.append("If thermostat changes fail, verify hvac_modes and try mode then temperature as separate calls.")
        if hint.get("domain") == "vacuum":
            recovery.append("If vacuum verification fails, compare cleaning/returning/docked/idle state families instead of one exact state.")
        if hint.get("domain") in {"number", "select"}:
            recovery.append("If helper verification fails, inspect allowed ranges/options and whether state or attributes echo the requested value.")
        if hint.get("domain") == "humidifier":
            recovery.append("If humidity changes fail, turn the humidifier on first and verify target humidity feedback.")
        if hint.get("domain") == "water_heater":
            recovery.append("If water-heater changes fail, verify operation_list and split mode and temperature service calls.")
        if hint.get("domain") == "valve":
            recovery.append("If valve state does not change, add delayed verification and keep risky open actions gated.")
        if "group_diagnostics" in hint.get("quirks", []):
            recovery.append("Group mobile diagnostic entities into one personal device profile.")
    return sorted(set(recovery))
