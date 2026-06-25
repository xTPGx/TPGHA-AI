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
    expected_attr = _expected_attribute(result)
    if expected is None and expected_attr is None and result.intent not in {"control_device"}:
        return {"checked": False, "reason": "no_expected_state", "entity_ids": targets}

    # Give HA integrations a tiny moment to publish the state update.
    await asyncio.sleep(0.05)

    readings: list[dict[str, Any]] = []
    for entity_id in targets:
        try:
            ent = await ctx.ha.get_entity(entity_id)
            state = str((ent or {}).get("state") or "")
            attrs = (ent or {}).get("attributes") or {}
            matches = _reading_matches(result, state, attrs, expected, expected_attr)
            readings.append({
                "entity_id": entity_id,
                "state": state,
                "attributes": _interesting_attributes(attrs),
                "available": state not in {"unavailable", "unknown", "none", ""},
                "matches_expected": matches,
                "diagnostic": _reading_diagnostic(result, state, attrs, expected, expected_attr, matches),
            })
        except HAError as exc:
            readings.append({
                "entity_id": entity_id,
                "available": False,
                "error": exc.message,
                "matches_expected": False,
                "diagnostic": "Home Assistant could not read the target after the service call.",
            })

    verified = all(r.get("matches_expected") for r in readings)
    status = _outcome_status(readings, verified)
    recovery = [] if verified else _recovery_steps(result, {"readings": readings})
    outcome = {
        "checked": True,
        "verified": verified,
        "status": status,
        "confidence": _outcome_confidence(status, readings),
        "summary": _outcome_summary(result, status, readings),
        "expected_state": expected,
        "expected_attribute": expected_attr,
        "readings": readings,
        "diagnostics": [r.get("diagnostic") for r in readings if r.get("diagnostic")],
        "device_intelligence": [_device_intelligence(result, r, expected, expected_attr) for r in readings],
        "recovery_steps": recovery,
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
            "service_strategy": _service_strategy(device),
            "reliability": {
                "score": 1.0,
                "grade": "unseen",
                "last_outcome": None,
                "common_failures": [],
            },
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
            data = _json_obj(row.data)
            outcome = data.get("outcome") if isinstance(data.get("outcome"), dict) else None
            action_ok = bool(row.success)
            if outcome and outcome.get("checked"):
                action_ok = outcome.get("verified") is True
            if action_ok:
                hist["successful_actions"] += 1
                hist["last_success"] = hist["last_success"] or _row_summary(row)
            else:
                hist["failed_actions"] += 1
                hist["last_failure"] = hist["last_failure"] or _row_summary(row)
            reliability = profiles[pid]["reliability"]
            if outcome and reliability["last_outcome"] is None:
                reliability["last_outcome"] = {
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "intent": row.intent,
                    "status": outcome.get("status") or ("verified" if outcome.get("verified") else "mismatch"),
                    "summary": outcome.get("summary"),
                    "diagnostics": outcome.get("diagnostics") or [],
                }
            if outcome and outcome.get("verified") is False:
                for diagnostic in outcome.get("diagnostics") or []:
                    if diagnostic and diagnostic not in reliability["common_failures"]:
                        reliability["common_failures"].append(diagnostic)

    for profile in profiles.values():
        hist = profile["history"]
        total = hist["successful_actions"] + hist["failed_actions"]
        if total:
            score = round(hist["successful_actions"] / total, 2)
            profile["reliability"]["score"] = score
            profile["reliability"]["grade"] = (
                "excellent" if score >= 0.9 else
                "watch" if score >= 0.7 else
                "needs_attention"
            )
        profile["reliability"]["common_failures"] = profile["reliability"]["common_failures"][:5]

    return {
        "profiles": list(profiles.values()),
        "counts": {
            "profiles": len(profiles),
            "with_quirks": sum(1 for p in profiles.values() if p["quirks"]),
            "needs_attention": sum(
                1 for p in profiles.values()
                if p.get("reliability", {}).get("grade") == "needs_attention"
            ),
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


def _expected_attribute(result: ActionResult) -> dict[str, Any] | None:
    resolved = result.resolved or {}
    call = (result.data or {}).get("service_call") or {}
    data = call.get("data") or {}
    if result.intent == "set_fan_percentage":
        value = resolved.get("percentage", data.get("percentage"))
        return _numeric_expectation("percentage", value, tolerance=4)
    if result.intent in {"set_volume", "set_media_volume"}:
        value = resolved.get("volume_level", data.get("volume_level"))
        if value is None:
            value = resolved.get("percentage")
            try:
                value = float(value) / 100
            except (TypeError, ValueError):
                value = None
        return _numeric_expectation("volume_level", value, tolerance=0.04)
    if result.intent in {"set_temperature", "set_climate_temperature"}:
        value = resolved.get("temperature", data.get("temperature"))
        return _numeric_expectation("temperature", value, tolerance=1)
    service = call.get("service")
    if service == "set_percentage":
        return _numeric_expectation("percentage", data.get("percentage"), tolerance=4)
    if service == "volume_set":
        return _numeric_expectation("volume_level", data.get("volume_level"), tolerance=0.04)
    if service == "set_temperature":
        return _numeric_expectation("temperature", data.get("temperature"), tolerance=1)
    return None


def _numeric_expectation(attribute: str, value: Any, *, tolerance: float) -> dict[str, Any] | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number.is_integer():
        number = int(number)
    return {"attribute": attribute, "value": number, "tolerance": tolerance}


def _reading_matches(
    result: ActionResult,
    state: str,
    attrs: dict[str, Any],
    expected: str | None,
    expected_attr: dict[str, Any] | None,
) -> bool:
    normalized = str(state or "").lower()
    if normalized in {"unavailable", "unknown", "none", ""}:
        return False
    if expected_attr:
        attr = expected_attr["attribute"]
        if attr not in attrs:
            return False
        try:
            actual = float(attrs.get(attr))
            expected_value = float(expected_attr["value"])
        except (TypeError, ValueError):
            return str(attrs.get(attr)).lower() == str(expected_attr["value"]).lower()
        return abs(actual - expected_value) <= float(expected_attr.get("tolerance", 0))
    if expected:
        return _state_matches(result.intent, state, expected)
    return True


def _state_matches(intent: str, state: str, expected: str) -> bool:
    normalized = str(state or "").lower()
    if intent == "play_music":
        return normalized in {"playing", "buffering", "on"}
    if intent == "stop_music":
        return normalized in {"idle", "paused", "off", "standby"}
    if expected == "on" and normalized in {"on", "playing", "idle", "paused"}:
        return True
    if expected == "off" and normalized in {"off", "standby"}:
        return True
    return normalized == expected


def _outcome_status(readings: list[dict[str, Any]], verified: bool) -> str:
    if verified:
        return "verified"
    if any(not r.get("available", True) for r in readings):
        return "unavailable"
    return "mismatch"


def _outcome_confidence(status: str, readings: list[dict[str, Any]]) -> float:
    if status == "verified":
        return 0.98
    if status == "unavailable":
        return 0.25
    if not readings:
        return 0.0
    return 0.45


def _outcome_summary(result: ActionResult, status: str, readings: list[dict[str, Any]]) -> str:
    label = result.resolved.get("label") or result.resolved.get("target") or ", ".join(
        r.get("entity_id", "") for r in readings
    ) or result.intent.replace("_", " ")
    if status == "verified":
        return f"{label} verified after the action."
    if status == "unavailable":
        return f"{label} could not be verified because Home Assistant reported it unavailable or unreadable."
    return f"{label} did not report the expected state after the action."


def _reading_diagnostic(
    result: ActionResult,
    state: str,
    attrs: dict[str, Any],
    expected: str | None,
    expected_attr: dict[str, Any] | None,
    matches: bool,
) -> str:
    if matches:
        return "Expected post-action state confirmed."
    normalized = str(state or "").lower()
    if normalized in {"unavailable", "unknown", "none", ""}:
        return "Target is unavailable or unknown in Home Assistant after the action."
    if expected_attr:
        attr = expected_attr["attribute"]
        if attr not in attrs:
            if result.intent == "set_fan_percentage":
                return "Fan does not expose percentage feedback; it may need preset-mode mapping."
            return f"Target does not expose the {attr} attribute needed for verification."
        return f"Expected {attr} {expected_attr['value']} but Home Assistant reported {attrs.get(attr)}."
    if expected:
        return f"Expected state {expected} but Home Assistant reported {state}."
    return "Service call completed, but no exact verification rule exists yet."


def _device_intelligence(
    result: ActionResult,
    reading: dict[str, Any],
    expected: str | None,
    expected_attr: dict[str, Any] | None,
) -> dict[str, Any]:
    entity_id = str(reading.get("entity_id") or "")
    domain = entity_id.split(".", 1)[0] if "." in entity_id else ""
    issue = reading.get("diagnostic") or ""
    return {
        "entity_id": entity_id,
        "domain": domain,
        "expected": expected_attr or expected,
        "observed": {
            "state": reading.get("state"),
            "attributes": reading.get("attributes") or {},
        },
        "likely_issue": issue,
        "suggested_next_action": _suggested_next_action(result, domain, issue),
    }


def _suggested_next_action(result: ActionResult, domain: str, issue: str) -> str:
    text = issue.lower()
    if "unavailable" in text or "unknown" in text:
        return "Check device connectivity/integration health before retrying."
    if result.intent == "set_fan_percentage" or domain == "fan":
        return "Inspect fan attributes and map speed levels to preset modes if percentage is unsupported."
    if domain == "media_player":
        return "Check supported features and prefer play_media/volume paths when power services are unsupported."
    if domain == "lock":
        return "Verify lock battery/connectivity; keep unlock confirmation enabled."
    return "Review the Home Assistant entity attributes and update the device profile if this behavior is expected."


def _interesting_attributes(attrs: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "percentage", "preset_mode", "preset_modes", "speed_count",
        "volume_level", "media_content_id", "media_title", "source",
        "temperature", "target_temp_low", "target_temp_high", "hvac_mode",
        "brightness", "supported_features", "device_class", "battery_level",
    ]
    return {key: attrs.get(key) for key in keys if key in attrs}


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


def build_reliability_summary(limit: int = 100) -> dict[str, Any]:
    """Return a live reliability snapshot from recent command outcomes."""
    limit = max(1, min(500, limit))
    with get_session() as session:
        rows = session.query(CommandLog).order_by(
            CommandLog.created_at.desc(), CommandLog.id.desc()
        ).limit(limit).all()
        repairs = session.query(Suggestion).filter(
            Suggestion.category == "repair",
            Suggestion.status.in_(["suggested", "draft", "edited"]),
        ).count()

    outcomes: list[dict[str, Any]] = []
    statuses: dict[str, int] = defaultdict(int)
    by_domain: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        data = _json_obj(row.data)
        outcome = data.get("outcome") if isinstance(data.get("outcome"), dict) else None
        if not outcome:
            continue
        status = str(outcome.get("status") or ("verified" if outcome.get("verified") else "unchecked"))
        statuses[status] += 1
        entity_ids = _entity_ids_from_json(row.resolved) | _entity_ids_from_json(row.data)
        for entity_id in entity_ids:
            domain = str(entity_id).split(".", 1)[0] if "." in str(entity_id) else "unknown"
            by_domain[domain][status] += 1
        outcomes.append({
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "intent": row.intent,
            "message": row.message,
            "status": status,
            "summary": outcome.get("summary"),
            "diagnostics": outcome.get("diagnostics") or [],
        })

    checked = sum(statuses.values())
    verified = statuses.get("verified", 0)
    score = round(verified / checked, 2) if checked else 1.0
    return {
        "score": score,
        "grade": "excellent" if score >= 0.9 else "watch" if score >= 0.7 else "needs_attention",
        "checked_commands": checked,
        "status_counts": dict(statuses),
        "domain_counts": {domain: dict(counts) for domain, counts in by_domain.items()},
        "open_repair_suggestions": repairs,
        "recent_outcomes": outcomes[:25],
    }


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
        state = str(entity.get("state") or "").lower()
        if state in {"unavailable", "unknown"}:
            quirks.append("currently_unavailable")
        if entity.get("domain") == "fan" and attrs.get("preset_modes"):
            quirks.append("fan_may_prefer_presets")
        if entity.get("domain") == "fan" and attrs.get("preset_modes") and "percentage" not in attrs:
            quirks.append("fan_uses_presets_not_percentage")
        if entity.get("domain") == "media_player" and not attrs.get("supported_features"):
            quirks.append("media_player_supported_features_unknown")
    return sorted(set(quirks))


def _service_strategy(device: dict[str, Any]) -> dict[str, Any]:
    strategies: dict[str, Any] = {}
    for entity in device.get("entities", []):
        entity_id = entity.get("entity_id")
        if not entity_id:
            continue
        domain = entity.get("domain")
        attrs = entity.get("attributes") or {}
        if domain == "fan":
            strategies[entity_id] = {
                "preferred_speed_control": "preset_mode" if attrs.get("preset_modes") and "percentage" not in attrs else "percentage",
                "preset_modes": attrs.get("preset_modes") or [],
                "supports_percentage_feedback": "percentage" in attrs,
            }
        elif domain == "media_player":
            strategies[entity_id] = {
                "preferred_power_control": "turn_on_service_then_verify",
                "supports_feature_mask": attrs.get("supported_features"),
                "media_strategy": "play_media_with_source_account",
            }
        elif domain == "light":
            strategies[entity_id] = {
                "preferred_control": "light_service",
                "supports_brightness_feedback": "brightness" in attrs,
            }
    return strategies


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


def _json_obj(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _row_summary(row: CommandLog) -> dict[str, Any]:
    return {
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "intent": row.intent,
        "message": row.message,
        "response": row.response_message,
        "error": row.error,
    }
