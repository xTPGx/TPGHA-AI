"""Fan actions. Allowlisted fan control via Home Assistant `fan.*` services.

Only the three vetted fan services are used (turn_on, turn_off, set_percentage).
No arbitrary Home Assistant services are reachable from here.
"""
from __future__ import annotations

import json
from typing import Any

from ..homeassistant.rest import HAError
from ..memory import approved_memory_value
from ..models.results import ActionResult
from . import ActionContext

FAN_SET_SPEED = 1

_LOW_PRESETS = ("low", "1", "speed 1", "level 1", "silent", "quiet", "sleep")
_MID_PRESETS = ("medium", "med", "2", "3", "speed 2", "speed 3", "level 2", "level 3")
_HIGH_PRESETS = ("high", "4", "5", "speed 4", "speed 5", "level 4", "level 5", "turbo", "boost", "max", "maximum")


def _resolve(ctx: ActionContext, params: dict[str, Any], intent: str):
    target = (params.get("target") or "").strip()
    if not target:
        return target, None, ActionResult.fail(intent, "Which fan should I control?")
    user_id = ctx.user.id if ctx.user else None
    if not ctx.permissions.user_allows(user_id, "can_control_fans"):
        return target, None, ActionResult.fail(intent, "You are not allowed to control fans.")
    res = ctx.resolver.resolve_fan(target)
    if not res.matched:
        return target, None, ActionResult.fail(
            intent, f"I couldn't find a fan for '{target}'. {res.reason}"
        )
    return target, res, None


async def turn_on_fan(ctx: ActionContext, params: dict[str, Any]) -> ActionResult:
    intent = "turn_on_fan"
    target, res, err = _resolve(ctx, params, intent)
    if err:
        return err
    resolved = {"target": target, "entity_id": res.entity_id,
                "reason": res.reason, "confidence": res.confidence}
    try:
        await ctx.ha.call_service("fan", "turn_on", {"entity_id": res.entity_id})
        return ActionResult(success=True, intent=intent, executed=True,
                            message=f"Turned on {res.name}.", resolved=resolved)
    except HAError as exc:
        return ActionResult.fail(intent, f"Couldn't turn on {res.name}: {exc.message}",
                                 resolved=resolved)


async def turn_off_fan(ctx: ActionContext, params: dict[str, Any]) -> ActionResult:
    intent = "turn_off_fan"
    target, res, err = _resolve(ctx, params, intent)
    if err:
        return err
    resolved = {"target": target, "entity_id": res.entity_id,
                "reason": res.reason, "confidence": res.confidence}
    try:
        await ctx.ha.call_service("fan", "turn_off", {"entity_id": res.entity_id})
        return ActionResult(success=True, intent=intent, executed=True,
                            message=f"Turned off {res.name}.", resolved=resolved)
    except HAError as exc:
        return ActionResult.fail(intent, f"Couldn't turn off {res.name}: {exc.message}",
                                 resolved=resolved)


async def set_fan_percentage(ctx: ActionContext, params: dict[str, Any]) -> ActionResult:
    intent = "set_fan_percentage"
    target, res, err = _resolve(ctx, params, intent)
    if err:
        return err
    pct_raw = params.get("percentage")
    if pct_raw is None:
        return ActionResult.fail(intent, "What percentage should I set the fan to?")
    percentage = max(0, min(100, int(round(float(pct_raw)))))
    resolved = {"target": target, "entity_id": res.entity_id, "percentage": percentage,
                "reason": res.reason, "confidence": res.confidence}
    try:
        entity = await ctx.ha.get_entity(res.entity_id)
        attrs = (entity or {}).get("attributes", {}) or {}
        strategy = _approved_fan_strategy(res.entity_id)
        supported_features = int(attrs.get("supported_features") or 0)
        supports_percentage = bool(supported_features & FAN_SET_SPEED) or "percentage" in attrs
        if strategy == "preset_mode" or not supports_percentage:
            resolved["supported_features"] = supported_features
            resolved["preset_modes"] = attrs.get("preset_modes") or []
            preset = _preset_for_percentage(percentage, resolved["preset_modes"])
            if preset:
                await ctx.ha.call_service(
                    "fan", "set_preset_mode",
                    {"entity_id": res.entity_id, "preset_mode": preset},
                )
                resolved["service_strategy"] = "approved_preset_mode" if strategy == "preset_mode" else "preset_mode_fallback"
                return ActionResult(success=True, intent=intent, executed=True,
                                    message=f"Set {res.name} to {preset}.",
                                    resolved={**resolved, "preset_mode": preset})
            if percentage <= 0:
                await ctx.ha.call_service("fan", "turn_off", {"entity_id": res.entity_id})
                return ActionResult(success=True, intent=intent, executed=True,
                                    message=f"Turned off {res.name}.", resolved=resolved)
            if percentage >= 100:
                await ctx.ha.call_service("fan", "turn_on", {"entity_id": res.entity_id})
                return ActionResult(success=True, intent=intent, executed=True,
                                    message=(
                                        f"Turned on {res.name}. This fan does not expose "
                                        "percentage speed control in Home Assistant."
                                    ), resolved=resolved)
            return ActionResult.fail(
                intent,
                f"{res.name} does not support percentage speed control in Home Assistant.",
                resolved=resolved,
            )
        await ctx.ha.call_service(
            "fan", "set_percentage",
            {"entity_id": res.entity_id, "percentage": percentage},
        )
        return ActionResult(success=True, intent=intent, executed=True,
                            message=f"Set {res.name} to {percentage}%.", resolved=resolved)
    except HAError as exc:
        return ActionResult.fail(intent, f"Couldn't set {res.name}: {exc.message}",
                                 resolved=resolved)


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


def _approved_fan_strategy(entity_id: str) -> str:
    raw = approved_memory_value("device", entity_id, "preferred_fan_speed_control")
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = raw
    if isinstance(parsed, dict):
        return str(parsed.get("strategy") or "")
    return str(parsed or "")
