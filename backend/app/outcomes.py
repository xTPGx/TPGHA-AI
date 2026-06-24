"""Closed-loop action verification and device profile helpers."""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any

from .actions import ActionContext
from .db.database import get_session
from .db.models import CommandLog, Suggestion
from .homeassistant.rest import HAError
from .models.results import ActionResult


async def verify_action_outcome(ctx: ActionContext, result: ActionResult) -> dict[str, Any]:
    """Best-effort state verification after an action executes.

    This does not make Home Assistant's eventual consistency magically instant,
    but it gives the brain a grounded post-action read instead of blindly
    trusting that a service call changed the real world.
    """
    if getattr(ctx, "dry_run", False) or not result.executed:
        return {"checked": False, "reason": "not_executed_or_dry_run"}

    targets = _target_entity_ids(result)
    if not targets:
        return {"checked": False, "reason": "no_entity_target"}

    expected = _expected_state(result)
    if expected is None and result.intent not in {"set_fan_percentage", "control_device"}:
        return {"checked": False, "reason": "no_expected_state", "entity_ids": targets}

    # Give HA integrations a tiny moment to publish the state update.
    await asyncio.sleep(0.05)

    readings: list[dict[str, Any]] = []
    for entity_id in targets:
        try:
            ent = await ctx.ha.get_entity(entity_id)
            state = str((ent or {}).get("state") or "")
            readings.append({
                "entity_id": entity_id,
                "state": state,
                "available": state not in {"unavailable", "unknown", "none", ""},
                "matches_expected": expected is None or state == expected,
            })
        except HAError as exc:
            readings.append({
                "entity_id": entity_id,
                "available": False,
                "error": exc.message,
                "matches_expected": False,
            })

    verified = all(r.get("matches_expected") for r in readings)
    outcome = {
        "checked": True,
        "verified": verified,
        "expected_state": expected,
        "readings": readings,
    }
    if not verified:
        _draft_repair_suggestion(result, outcome)
    return outcome


def build_device_profiles(graph: dict[str, Any]) -> dict[str, Any]:
    """Build operational profiles for physical devices from graph + history."""
    profiles: dict[str, dict[str, Any]] = {}
    for device in graph.get("physical_devices", []):
        entities = device.get("entities", [])
        entity_ids = [e.get("entity_id") for e in entities if e.get("entity_id")]
        profiles[device["id"]] = {
            "id": device["id"],
            "name": device.get("name"),
            "area": device.get("area"),
            "device_type": device.get("device_type"),
            "entity_ids": entity_ids,
            "capabilities": sorted({cap for e in entities for cap in _entity_capabilities(e)}),
            "quirks": _profile_quirks(device),
            "history": {
                "successful_actions": 0,
                "failed_actions": 0,
                "last_success": None,
                "last_failure": None,
            },
        }

    by_entity: dict[str, str] = {}
    for pid, profile in profiles.items():
        for entity_id in profile["entity_ids"]:
            by_entity[entity_id] = pid

    with get_session() as session:
        rows = session.query(CommandLog).order_by(CommandLog.created_at.desc()).limit(500).all()
    for row in rows:
        entity_ids = _entity_ids_from_json(row.resolved) | _entity_ids_from_json(row.data)
        for entity_id in entity_ids:
            pid = by_entity.get(entity_id)
            if not pid:
                continue
            hist = profiles[pid]["history"]
            if row.success:
                hist["successful_actions"] += 1
                hist["last_success"] = hist["last_success"] or _row_summary(row)
            else:
                hist["failed_actions"] += 1
                hist["last_failure"] = hist["last_failure"] or _row_summary(row)

    return {
        "profiles": list(profiles.values()),
        "counts": {
            "profiles": len(profiles),
            "with_quirks": sum(1 for p in profiles.values() if p["quirks"]),
        },
    }


def _target_entity_ids(result: ActionResult) -> list[str]:
    ids: list[str] = []
    resolved = result.resolved or {}
    entity_id = resolved.get("entity_id")
    if entity_id:
        ids.append(str(entity_id))
    for eid in resolved.get("entity_ids") or []:
        ids.append(str(eid))
    call = (result.data or {}).get("service_call") or {}
    data = call.get("data") or {}
    call_entity = data.get("entity_id")
    if isinstance(call_entity, list):
        ids.extend(str(e) for e in call_entity)
    elif call_entity:
        ids.append(str(call_entity))
    return sorted(set(ids))


def _expected_state(result: ActionResult) -> str | None:
    intent = result.intent
    if intent in {"turn_on_light", "turn_on_fan"}:
        return "on"
    if intent in {"turn_off_light", "turn_off_fan"}:
        return "off"
    if intent == "lock_door":
        return "locked"
    if intent == "unlock_door":
        return "unlocked"
    if intent == "play_music":
        return "playing"
    if intent == "stop_music":
        return "idle"
    call = (result.data or {}).get("service_call") or {}
    service = call.get("service")
    if service == "turn_on":
        return "on"
    if service == "turn_off":
        return "off"
    if service == "lock":
        return "locked"
    if service == "unlock":
        return "unlocked"
    return None


def _draft_repair_suggestion(result: ActionResult, outcome: dict[str, Any]) -> None:
    title = f"Verify {result.intent.replace('_', ' ')} outcome"
    recovery = _recovery_steps(result, outcome)
    payload = {
        "intent": result.intent,
        "resolved": result.resolved,
        "outcome": outcome,
        "recovery_steps": recovery,
    }
    with get_session() as session:
        exists = session.query(Suggestion).filter(
            Suggestion.title == title,
            Suggestion.category == "repair",
            Suggestion.status.in_(["suggested", "draft", "edited"]),
        ).first()
        if exists:
            return
        session.add(Suggestion(
            title=title,
            message=(
                "A command executed but the follow-up state check did not match. "
                + (recovery[0] if recovery else "Review the device profile and Home Assistant integration.")
            ),
            category="repair",
            priority="high",
            action_type="device_recovery",
            payload=json.dumps(payload),
            status="suggested",
        ))
        session.commit()


def _recovery_steps(result: ActionResult, outcome: dict[str, Any]) -> list[str]:
    resolved = result.resolved or {}
    entity_ids = _target_entity_ids(result)
    entity_id = entity_ids[0] if entity_ids else str(resolved.get("entity_id") or "")
    domain = entity_id.split(".", 1)[0] if "." in entity_id else ""
    steps: list[str] = []
    if result.intent == "set_fan_percentage" or domain == "fan":
        steps.extend([
            "Check whether this fan uses preset modes instead of percentage speed.",
            "If preset_modes exist, map requested levels to fan.set_preset_mode.",
            "Approve a device memory such as 'office fan uses preset speed modes'.",
        ])
    elif domain == "media_player":
        steps.extend([
            "Verify the media player supports turn_on/turn_off in Home Assistant.",
            "Try a direct media_player.turn_on or media_player.turn_off service call.",
            "If the TV needs an alternate integration, mark that in the device profile.",
        ])
    elif domain in {"light", "switch"}:
        steps.extend([
            "Check if the entity is unavailable or delayed by the integration.",
            "Retry after refreshing Home Assistant state.",
        ])
    elif domain == "lock":
        steps.extend([
            "Check lock connectivity and battery state before retrying.",
            "Do not bypass unlock confirmation or PIN requirements.",
        ])
    if any(not r.get("available", True) for r in outcome.get("readings", [])):
        steps.insert(0, "Home Assistant reported the target unavailable or unreadable.")
    return steps


def _entity_capabilities(entity: dict[str, Any]) -> list[str]:
    domain = entity.get("domain")
    category = entity.get("category")
    if category == "diagnostic":
        return ["diagnostic"]
    return {
        "light": ["turn_on", "turn_off", "brightness"],
        "fan": ["turn_on", "turn_off", "speed_or_preset"],
        "media_player": ["turn_on", "turn_off", "media", "volume"],
        "lock": ["lock", "unlock_sensitive"],
        "cover": ["open_sensitive", "close"],
        "climate": ["temperature", "hvac_mode"],
        "camera": ["view"],
        "switch": ["turn_on", "turn_off"],
    }.get(str(domain), ["status"])


def _profile_quirks(device: dict[str, Any]) -> list[str]:
    quirks: list[str] = []
    dtype = device.get("device_type")
    diagnostics = device.get("diagnostic_entities") or []
    if dtype in {"phone", "tablet"} and diagnostics:
        quirks.append("personal_device_entity_spam")
    for entity in device.get("entities", []):
        attrs = entity.get("attributes") or {}
        if entity.get("domain") == "fan" and attrs.get("preset_modes"):
            quirks.append("fan_may_prefer_presets")
    return sorted(set(quirks))


def _entity_ids_from_json(value: str | None) -> set[str]:
    if not value:
        return set()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return set()
    found: set[str] = set()

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "entity_id":
                    if isinstance(v, list):
                        found.update(str(i) for i in v)
                    else:
                        found.add(str(v))
                else:
                    walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(parsed)
    return found


def _row_summary(row: CommandLog) -> dict[str, Any]:
    return {
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "intent": row.intent,
        "message": row.message,
        "response": row.response_message,
        "error": row.error,
    }
