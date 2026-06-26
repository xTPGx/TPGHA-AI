"""Climate actions. Sets HVAC mode + temperature on a mapped thermostat.

If no climate entity is mapped (devices.yaml -> climate is empty / room has no
climate), we ask the user for a target room instead of guessing."""
from __future__ import annotations

import json
from typing import Any, Optional

from ..homeassistant.rest import HAError
from ..memory import approved_memory_value
from ..models.results import ActionResult
from . import ActionContext

VALID_MODES = {"heat", "cool", "heat_cool", "auto", "off", "dry", "fan_only"}


def _find_climate_entity(ctx: ActionContext, room: str) -> tuple[Optional[str], str, str]:
    """Return (entity_id, label, reason). entity_id None if unmapped."""
    climates = ctx.config.devices.climate
    # Room-scoped first.
    if room:
        room_res = ctx.resolver.resolve_room(room)
        if room_res.matched:
            if room_res.data.get("climate"):
                return room_res.data["climate"], room_res.name, room_res.reason
            for c in climates:
                if c.room == room_res.id:
                    return c.entity_id, c.name, f"Climate mapped to room '{room_res.name}'."
    # Single global thermostat fallback.
    if len(climates) == 1 and not room:
        c = climates[0]
        return c.entity_id, c.name, "Only one thermostat configured."
    return None, room, "No climate entity mapped."


async def set_climate(ctx: ActionContext, params: dict[str, Any]) -> ActionResult:
    intent = "set_climate"
    room = (params.get("room") or "").strip()
    mode = (params.get("mode") or "").strip().lower()
    temperature = params.get("temperature")

    if mode and mode not in VALID_MODES:
        mode = {"ac": "cool", "heating": "heat", "cooling": "cool"}.get(mode, mode)

    user_id = ctx.user.id if ctx.user else None
    if not ctx.permissions.user_allows(user_id, "can_control_climate"):
        return ActionResult.fail(intent, "You are not allowed to control climate.")

    entity_id, label, reason = _find_climate_entity(ctx, room)
    resolved = {"room": room or None, "mode": mode or None, "temperature": temperature,
                "entity_id": entity_id, "reason": reason}

    if not entity_id:
        # Ask for the target room (acceptance test requirement).
        rooms = ", ".join(r.name for r in ctx.config.devices.rooms) or "a room"
        return ActionResult(
            success=True, intent=intent, executed=False,
            message=(
                f"I can set the thermostat to {mode or 'a mode'} "
                f"{int(temperature) if temperature is not None else ''}, but no "
                f"thermostat is mapped yet. Which room's thermostat? ({rooms}) "
                "You can also map a climate entity in devices.yaml."
            ),
            resolved=resolved,
        )

    if temperature is None:
        return ActionResult.fail(intent, "What temperature should I set?", resolved=resolved)

    attempts: list[dict[str, Any]] = []
    strategy = _approved_climate_strategy(entity_id)
    strategy_name = str(strategy.get("strategy") or "mode_then_temperature")
    try:
        if mode and strategy_name != "temperature_only":
            mode_call = {
                "domain": "climate",
                "service": "set_hvac_mode",
                "data": {"entity_id": entity_id, "hvac_mode": mode},
            }
            try:
                await ctx.ha.call_service(mode_call["domain"], mode_call["service"], mode_call["data"])
                attempts.append({**mode_call, "success": True})
            except HAError as exc:
                attempts.append({**mode_call, "success": False, "error": exc.message, "status": exc.status})
                if strategy_name != "temperature_only":
                    raise
        temp_call = {
            "domain": "climate",
            "service": "set_temperature",
            "data": {"entity_id": entity_id, "temperature": float(temperature)},
        }
        await ctx.ha.call_service(temp_call["domain"], temp_call["service"], temp_call["data"])
        attempts.append({**temp_call, "success": True})
        msg = f"Set {label} to {mode or 'its current mode'} {int(float(temperature))}\u00b0."
        return ActionResult(success=True, intent=intent, executed=True,
                            message=msg, resolved=resolved,
                            data={
                                "service_call": temp_call,
                                "service_attempts": attempts,
                                "service_strategy": strategy_name,
                            })
    except HAError as exc:
        return ActionResult.fail(intent, f"Couldn't set {label}: {exc.message}",
                                 resolved=resolved,
                                 data={"service_attempts": attempts, "service_strategy": strategy_name})


def _approved_climate_strategy(entity_id: str) -> dict[str, Any]:
    raw = approved_memory_value("device", entity_id, "preferred_climate_control")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"strategy": raw}
    return parsed if isinstance(parsed, dict) else {"strategy": str(parsed or "")}
