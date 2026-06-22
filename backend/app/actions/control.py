"""Generic capability-based device control (PART 3).

control_device / query_device resolve a target to a concrete entity, map the
requested action to a vetted Home Assistant service via the capability layer,
gate sensitive operations behind confirmation, execute, and verify. This is how
we avoid hand-writing a new tool for every device type.
"""
from __future__ import annotations

from typing import Any, Optional

from ..discovery import capabilities as caps
from ..homeassistant.rest import HAError
from ..models.results import ActionResult
from . import ActionContext

# Map a domain to the permission capability that guards it.
_PERM_BY_DOMAIN = {
    "light": "can_control_lights",
    "switch": "can_control_lights",
    "fan": "can_control_fans",
    "climate": "can_control_climate",
    "water_heater": "can_control_climate",
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
    try:
        await ctx.ha.call_service(domain, service, data)
    except HAError as exc:
        # Be honest: the service call failed, so do NOT claim execution.
        return ActionResult.fail(intent, f"{friendly}: {exc.message}",
                                 data={"service_call": {"domain": domain,
                                                        "service": service, "data": data}})
    verification = await _verify(ctx, data.get("entity_id"))
    return ActionResult(
        success=True, intent=intent, executed=True,
        message=plan.get("success_message", f"Done ({domain}.{service})."),
        data={"service_call": {"domain": domain, "service": service, "data": data},
              "verification": verification},
    )


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
                "reason": res.reason, "confidence": res.confidence}
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
        return ActionResult(success=True, intent=intent, executed=True,
                            message=f"{res.name} is configured but live state is "
                                    f"unavailable: {exc.message}",
                            resolved={"entity_id": res.entity_id})
    return ActionResult(success=True, intent=intent, executed=True,
                        message=f"{res.name} is {state}.",
                        resolved={"entity_id": res.entity_id, "domain": res.data.get("domain")},
                        data={"state": state, "attributes": attrs})


def _sensitive_success(key: str, friendly: str) -> str:
    return {
        "unlock_door": f"Unlocked {friendly}.",
        "open_garage": f"Opened {friendly}.",
        "disarm_alarm": "Alarm disarmed.",
    }.get(key, f"Confirmed: {friendly}.")
