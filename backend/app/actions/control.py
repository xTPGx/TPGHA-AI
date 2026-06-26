"""Generic capability-based device control (PART 3).

control_device / query_device resolve a target to a concrete entity, map the
requested action to a vetted Home Assistant service via the capability layer,
gate sensitive operations behind confirmation, execute, and verify. This is how
we avoid hand-writing a new tool for every device type.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from ..discovery import capabilities as caps
from ..homeassistant.rest import HAError
from ..memory import approved_memory_value
from ..models.results import ActionResult
from . import ActionContext

FAN_SET_SPEED = 1
_LOW_PRESETS = ("low", "1", "speed 1", "level 1", "silent", "quiet", "sleep")
_MID_PRESETS = ("medium", "med", "2", "3", "speed 2", "speed 3", "level 2", "level 3")
_HIGH_PRESETS = ("high", "4", "5", "speed 4", "speed 5", "level 4", "level 5", "turbo", "boost", "max", "maximum")

# Map a domain to the permission capability that guards it.
_PERM_BY_DOMAIN = {
    "light": "can_control_lights",
    "switch": "can_control_lights",
    "fan": "can_control_fans",
    "climate": "can_control_climate",
    "water_heater": "can_control_climate",
    "humidifier": "can_control_climate",
    "media_player": "can_control_music",
    "cover": "can_control_covers",
    "valve": "can_control_covers",
    "lock": "can_lock_doors",
    "camera": "can_view_cameras",
}


def _plan_to_dict(plan: caps.ServicePlan, success_message: str) -> dict[str, Any]:
    return {
        "type": "service",
        "domain": plan.domain,
        "service": plan.service,
        "data": plan.data,
        "success_message": success_message,
    }


async def _verify(ctx: ActionContext, entity_id: Optional[str]) -> dict[str, Any]:
    """Best-effort post-action read so we never falsely claim success."""
    if not entity_id:
        return {}
    try:
        ent = await ctx.ha.get_entity(entity_id)
    except HAError:
        return {"available": False}
    if not ent:
        return {"available": False}
    return {"state": ent.get("state"), "available": ent.get("state") not in
            ("unavailable", "unknown", "none", None)}


async def execute_service_plan(ctx: ActionContext, plan: dict[str, Any],
                               friendly: str, intent: str) -> ActionResult:
    """Execute a previously-resolved service plan and verify the result.

    Reused by /confirm so the actual side effect happens in exactly one place.
    """
    if plan.get("type") == "noop":
        return ActionResult(success=True, intent=intent, executed=False,
                            message=plan.get("message",
                                              "Confirmed, but this action is not "
                                              "implemented in this build."))
    domain = plan["domain"]
    service = plan["service"]
    data = plan.get("data", {})
    if domain == "media_player":
        media_result = await _execute_media_player_plan(ctx, plan, friendly, intent)
        if media_result is not None:
            return media_result
    service_strategy = _approved_generic_strategy(domain, str(data.get("entity_id") or ""))
    try:
        if domain == "fan" and service == "set_percentage":
            guarded = await _fan_percentage_guard(ctx, data, friendly, intent)
            if guarded is not None:
                return guarded
        await ctx.ha.call_service(domain, service, data)
    except HAError as exc:
        # Be honest: the service call failed, so do NOT claim execution.
        return ActionResult.fail(intent, f"{friendly}: {exc.message}",
                                 data={"service_call": {"domain": domain,
                                                        "service": service, "data": data},
                                       "service_strategy": service_strategy or "native"})
    verification = await _verify(ctx, data.get("entity_id"))
    return ActionResult(
        success=True, intent=intent, executed=True,
        message=plan.get("success_message", f"Done ({domain}.{service})."),
        data={"service_call": {"domain": domain, "service": service, "data": data},
              "service_strategy": service_strategy or "native",
              "verification": verification},
    )


async def _execute_media_player_plan(
    ctx: ActionContext,
    plan: dict[str, Any],
    friendly: str,
    intent: str,
) -> Optional[ActionResult]:
    """Execute media_player power/play plans with approved device strategy memory.

    Some TVs and cast targets expose media_player entities but do not reliably
    honor turn_on/turn_off. Once reliability repair approves a device strategy,
    the generic executor should use that knowledge instead of repeating the
    same failing service forever.
    """
    service = str(plan.get("service") or "")
    data = dict(plan.get("data") or {})
    entity_id = str(data.get("entity_id") or "")
    if not entity_id:
        return None
    strategy = _approved_media_strategy(entity_id)
    strategy_name = str(strategy.get("strategy") or "")
    attempts: list[dict[str, Any]] = []

    if service == "turn_on" and strategy_name in {"media_play_wake", "play_media_wake"}:
        result = await _try_media_attempts(
            ctx,
            [
                ("media_player", "media_play", {"entity_id": entity_id}),
                ("media_player", "turn_on", data),
            ],
            attempts,
        )
        if result.get("success"):
            verification = await _verify(ctx, entity_id)
            return _media_action_result(plan, friendly, intent, result, attempts, verification, strategy_name)
        return _media_action_fail(plan, friendly, intent, result, attempts, strategy_name)

    if service == "turn_off" and strategy_name in {"media_stop_sleep", "media_stop_then_turn_off"}:
        result = await _try_media_attempts(
            ctx,
            [
                ("media_player", "media_stop", {"entity_id": entity_id}),
                ("media_player", "turn_off", data),
            ],
            attempts,
        )
        if result.get("success"):
            verification = await _verify(ctx, entity_id)
            return _media_action_result(plan, friendly, intent, result, attempts, verification, strategy_name)
        return _media_action_fail(plan, friendly, intent, result, attempts, strategy_name)

    if service not in {"turn_on", "turn_off"}:
        return None

    primary = await _try_media_attempts(ctx, [("media_player", service, data)], attempts)
    if primary.get("success"):
        verification = await _verify(ctx, entity_id)
        return _media_action_result(plan, friendly, intent, primary, attempts, verification, strategy_name or "native")

    fallbacks = (
        [("media_player", "media_play", {"entity_id": entity_id})]
        if service == "turn_on"
        else [("media_player", "media_stop", {"entity_id": entity_id})]
    )
    fallback = await _try_media_attempts(ctx, fallbacks, attempts)
    if fallback.get("success"):
        verification = await _verify(ctx, entity_id)
        fallback["fallback_reason"] = primary.get("message")
        fallback_strategy = "media_play_wake" if service == "turn_on" else "media_stop_sleep"
        return _media_action_result(plan, friendly, intent, fallback, attempts, verification, fallback_strategy)
    return _media_action_fail(plan, friendly, intent, fallback or primary, attempts, strategy_name or "native_then_fallback")


async def _try_media_attempts(
    ctx: ActionContext,
    calls: list[tuple[str, str, dict[str, Any]]],
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    last: dict[str, Any] = {"success": False, "message": "No media service attempts were available."}
    for domain, service, data in calls:
        call = {"domain": domain, "service": service, "data": data}
        try:
            await ctx.ha.call_service(domain, service, data)
            attempts.append({**call, "success": True})
            return {"success": True, "service_call": call}
        except HAError as exc:
            attempts.append({**call, "success": False, "error": exc.message, "status": exc.status})
            last = {"success": False, "message": exc.message, "service_call": call, "status": exc.status}
    return last


def _media_action_result(
    plan: dict[str, Any],
    friendly: str,
    intent: str,
    result: dict[str, Any],
    attempts: list[dict[str, Any]],
    verification: dict[str, Any],
    strategy: str,
) -> ActionResult:
    call = result.get("service_call") or {"domain": "media_player", "service": plan.get("service"), "data": plan.get("data", {})}
    message = plan.get("success_message", f"Done (media_player.{call.get('service')}).")
    if result.get("fallback_reason"):
        message = f"{message} Used media fallback for {friendly} because native power control failed."
    return ActionResult(
        success=True,
        intent=intent,
        executed=True,
        message=message,
        data={
            "service_call": call,
            "service_attempts": attempts,
            "service_strategy": strategy,
            "verification": verification,
        },
    )


def _media_action_fail(
    plan: dict[str, Any],
    friendly: str,
    intent: str,
    result: dict[str, Any],
    attempts: list[dict[str, Any]],
    strategy: str,
) -> ActionResult:
    call = result.get("service_call") or {"domain": "media_player", "service": plan.get("service"), "data": plan.get("data", {})}
    return ActionResult.fail(
        intent,
        f"{friendly}: {result.get('message') or 'media_player service failed'}",
        data={
            "service_call": call,
            "service_attempts": attempts,
            "service_strategy": strategy,
        },
    )


def _approved_media_strategy(entity_id: str) -> dict[str, Any]:
    raw = approved_memory_value("device", entity_id, "preferred_media_control")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"strategy": raw}
    return parsed if isinstance(parsed, dict) else {"strategy": str(parsed or "")}


def _approved_generic_strategy(domain: str, entity_id: str) -> str:
    key = {
        "cover": "preferred_cover_control",
        "climate": "preferred_climate_control",
        "vacuum": "preferred_vacuum_control",
        "number": "preferred_number_control",
        "select": "preferred_select_control",
        "humidifier": "preferred_humidifier_control",
        "water_heater": "preferred_water_heater_control",
        "valve": "preferred_valve_control",
    }.get(domain)
    if not key or not entity_id:
        return ""
    raw = approved_memory_value("device", entity_id, key)
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(parsed, dict):
        return str(parsed.get("strategy") or "")
    return str(parsed or "")


async def _fan_percentage_guard(ctx: ActionContext, data: dict[str, Any],
                                friendly: str, intent: str) -> Optional[ActionResult]:
    entity_id = data.get("entity_id")
    percentage = int(data.get("percentage") or 0)
    try:
        entity = await ctx.ha.get_entity(entity_id)
    except HAError as exc:
        return ActionResult.fail(intent, f"{friendly}: {exc.message}",
                                 data={"service_call": {"domain": "fan",
                                                        "service": "set_percentage",
                                                        "data": data}})
    attrs = (entity or {}).get("attributes", {}) or {}
    supported_features = int(attrs.get("supported_features") or 0)
    supports_percentage = bool(supported_features & FAN_SET_SPEED) or "percentage" in attrs
    if supports_percentage:
        return None
    preset_modes = attrs.get("preset_modes") or []
    preset = _preset_for_percentage(percentage, preset_modes)
    if preset:
        await ctx.ha.call_service(
            "fan",
            "set_preset_mode",
            {"entity_id": entity_id, "preset_mode": preset},
        )
        return ActionResult(success=True, intent=intent, executed=True,
                            message=f"Set {friendly} to {preset}.",
                            data={"service_call": {"domain": "fan",
                                                   "service": "set_preset_mode",
                                                   "data": {"entity_id": entity_id,
                                                            "preset_mode": preset}}})
    if percentage <= 0:
        await ctx.ha.call_service("fan", "turn_off", {"entity_id": entity_id})
        return ActionResult(success=True, intent=intent, executed=True,
                            message=f"Turned off {friendly}.",
                            data={"service_call": {"domain": "fan",
                                                   "service": "turn_off",
                                                   "data": {"entity_id": entity_id}}})
    if percentage >= 100:
        await ctx.ha.call_service("fan", "turn_on", {"entity_id": entity_id})
        return ActionResult(success=True, intent=intent, executed=True,
                            message=(
                                f"Turned on {friendly}. This fan does not expose "
                                "percentage speed control in Home Assistant."
                            ),
                            data={"service_call": {"domain": "fan",
                                                   "service": "turn_on",
                                                   "data": {"entity_id": entity_id}}})
    return ActionResult.fail(
        intent,
        f"{friendly} does not support percentage speed control in Home Assistant.",
        data={
            "supported_features": supported_features,
            "preset_modes": attrs.get("preset_modes") or [],
            "service_call": {"domain": "fan", "service": "set_percentage", "data": data},
        },
    )


def _preset_for_percentage(percentage: int, preset_modes: list[str]) -> str:
    if not preset_modes:
        return ""
    normalized = [(str(p), str(p).strip().lower()) for p in preset_modes if str(p).strip()]
    if not normalized:
        return ""
    buckets = [_LOW_PRESETS, _MID_PRESETS, _HIGH_PRESETS]
    bucket = buckets[0] if percentage <= 33 else (buckets[1] if percentage <= 66 else buckets[2])
    for original, lower in normalized:
        if any(word == lower or word in lower for word in bucket):
            return original
    index = round((max(1, min(100, percentage)) - 1) / 99 * (len(normalized) - 1))
    return normalized[index][0]


async def control_device(ctx: ActionContext, params: dict[str, Any]) -> ActionResult:
    intent = "control_device"
    target = (params.get("target") or "").strip()
    action = (params.get("action") or "").strip()
    value = params.get("value")
    if not target:
        return ActionResult.fail(intent, "Which device should I control?")
    if not action:
        return ActionResult.fail(intent, "What should I do with it?")

    res = ctx.resolver.resolve_target(target)
    if not res.matched:
        return ActionResult.fail(intent, f"I couldn't find '{target}'. {res.reason}")
    domain = res.data.get("domain") or res.entity_id.split(".", 1)[0]

    plan = caps.plan_for(domain, action, value, res.entity_id, res.name or "")
    resolved = {"target": target, "entity_id": res.entity_id, "domain": domain,
                "action": action, "value": value, "available": res.data.get("available"),
                "reason": res.reason, "confidence": res.confidence,
                "alternatives": res.alternatives, "ambiguous": res.ambiguous}
    if not plan.ok:
        return ActionResult.fail(intent, plan.reason or f"Can't '{action}' a {domain}.",
                                 resolved=resolved)
    if plan.query:
        return await query_device(ctx, {"target": target})

    user_id = ctx.user.id if ctx.user else None
    perm = _PERM_BY_DOMAIN.get(domain)
    if perm and not ctx.permissions.user_allows(user_id, perm):
        return ActionResult.fail(intent, f"You are not allowed to control {domain} devices.",
                                 resolved=resolved)

    success_message = f"{action.replace('_', ' ').capitalize()}: {res.name}."
    plan_dict = _plan_to_dict(plan, success_message)

    if plan.sensitive:
        # Self-gate so even a direct /test/action call cannot execute.
        msg = ctx.permissions.confirmation_message(plan.sensitive_key, res.name or target)
        plan_dict["success_message"] = _sensitive_success(plan.sensitive_key, res.name)
        pc = ctx.confirmations.create(
            intent=plan.sensitive_key, params={"target": target}, message=msg,
            ttl=ctx.config.permissions.confirmation_ttl_seconds,
            assistant=ctx.assistant.id if ctx.assistant else None,
            user=user_id, plan=plan_dict, risk_level=plan.risk, target=res.name or target,
        )
        return ActionResult.needs_confirmation(plan.sensitive_key, msg, pc.token, resolved)

    return await execute_service_plan(ctx, plan_dict, res.name or target, intent)


async def query_device(ctx: ActionContext, params: dict[str, Any]) -> ActionResult:
    intent = "query_device"
    target = (params.get("target") or "").strip()
    if not target:
        return ActionResult.fail(intent, "Which device do you want the status of?")
    res = ctx.resolver.resolve_target(target)
    if not res.matched:
        return ActionResult.fail(intent, f"I couldn't find '{target}'. {res.reason}")
    state = "unknown"
    attrs: dict[str, Any] = {}
    try:
        ent = await ctx.ha.get_entity(res.entity_id)
        if ent:
            state = ent.get("state", "unknown")
            attrs = ent.get("attributes", {}) or {}
    except HAError as exc:
        return ActionResult(success=True, intent=intent, executed=False,
                            message=f"{res.name} is configured but live state is "
                                    f"unavailable: {exc.message}",
                            resolved={"entity_id": res.entity_id})
    return ActionResult(success=True, intent=intent, executed=False,
                        message=f"{res.name} is {state}.",
                        resolved={"entity_id": res.entity_id, "domain": res.data.get("domain")},
                        data={"state": state, "attributes": attrs})


def _sensitive_success(key: str, friendly: str) -> str:
    return {
        "unlock_door": f"Unlocked {friendly}.",
        "open_garage": f"Opened {friendly}.",
        "disarm_alarm": "Alarm disarmed.",
    }.get(key, f"Confirmed: {friendly}.")
