"""Light actions. Resolve a light entity or a room's lights and toggle them."""
from __future__ import annotations

from typing import Any, Optional

from ..homeassistant.rest import HAError
from ..models.results import ActionResult
from . import ActionContext


def _resolve_light_targets(ctx: ActionContext, target: str) -> tuple[list[str], str]:
    """Return (entity_ids, friendly_label) for a light target.

    Order: explicit light.* entity -> device alias -> room.lights.
    """
    target = (target or "").strip()
    if target.startswith("light."):
        return [target], target

    alias = ctx.resolver.resolve_device_alias(target)
    if alias.matched and alias.entity_id and alias.entity_id.startswith("light."):
        return [alias.entity_id], alias.name or alias.entity_id

    room = ctx.resolver.resolve_room(target)
    if room.matched:
        lights = room.data.get("lights") or []
        if lights:
            return list(lights), f"{room.name} lights"
        return [], room.name
    return [], target


async def _toggle(ctx: ActionContext, params: dict[str, Any], on: bool) -> ActionResult:
    intent = "turn_on_light" if on else "turn_off_light"
    target = (params.get("target") or "").strip()
    if not target:
        return ActionResult.fail(intent, "Which light or room?")

    user_id = ctx.user.id if ctx.user else None
    if not ctx.permissions.user_allows(user_id, "can_control_lights"):
        return ActionResult.fail(intent, "You are not allowed to control lights.")

    entity_ids, label = _resolve_light_targets(ctx, target)
    resolved = {"target": target, "entity_ids": entity_ids, "label": label}
    if not entity_ids:
        return ActionResult.fail(
            intent,
            f"I recognized '{label}' but no light entities are mapped to it yet. "
            "Map lights to this room in devices.yaml.",
            resolved=resolved,
        )
    errors = []
    for eid in entity_ids:
        try:
            await (ctx.ha.turn_on(eid) if on else ctx.ha.turn_off(eid))
        except HAError as exc:
            errors.append(f"{eid}: {exc.message}")
    verb = "on" if on else "off"
    if errors:
        return ActionResult.fail(intent, f"Some lights failed: {'; '.join(errors)}",
                                 resolved=resolved)
    return ActionResult(success=True, intent=intent, executed=True,
                        message=f"Turned {verb} {label}.", resolved=resolved)


async def turn_on_light(ctx: ActionContext, params: dict[str, Any]) -> ActionResult:
    return await _toggle(ctx, params, on=True)


async def turn_off_light(ctx: ActionContext, params: dict[str, Any]) -> ActionResult:
    return await _toggle(ctx, params, on=False)
