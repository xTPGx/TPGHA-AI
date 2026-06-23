"""Lock actions. Locking is immediate (if allowed); unlocking is sensitive and
requires confirmation before the backend executes it."""
from __future__ import annotations

from typing import Any

from ..homeassistant.rest import HAError
from ..models.results import ActionResult
from . import ActionContext


async def lock_door(ctx: ActionContext, params: dict[str, Any]) -> ActionResult:
    intent = "lock_door"
    name = (params.get("door") or "").strip()
    res = ctx.resolver.resolve_lock(name)
    if not res.matched:
        return ActionResult.fail(intent, f"I couldn't find a lock for '{name}'. {res.reason}")

    user_id = ctx.user.id if ctx.user else None
    if not ctx.permissions.user_allows(user_id, "can_lock_doors"):
        return ActionResult.fail(intent, "You are not allowed to lock doors.")

    resolved = {"door": name or res.name, "entity_id": res.entity_id,
                "reason": res.reason, "confidence": res.confidence}
    try:
        await ctx.ha.lock(res.entity_id)
        return ActionResult(success=True, intent=intent, executed=True,
                            message=f"Locked the {res.name}.", resolved=resolved)
    except HAError as exc:
        return ActionResult.fail(intent, f"Couldn't lock {res.name}: {exc.message}",
                                 resolved=resolved)


async def unlock_door(ctx: ActionContext, params: dict[str, Any]) -> ActionResult:
    """Unlocking is sensitive: gate behind confirmation. The actual HA call
    happens via the stored execution plan after /confirm. /command NEVER
    executes this directly."""
    intent = "unlock_door"
    name = (params.get("door") or "").strip()
    res = ctx.resolver.resolve_lock(name)
    if not res.matched:
        return ActionResult.fail(intent, f"I couldn't find a lock for '{name}'. {res.reason}")

    user_id = ctx.user.id if ctx.user else None
    if not ctx.permissions.user_allows(user_id, "can_unlock_doors"):
        return ActionResult.fail(intent, "You are not allowed to unlock doors.")

    resolved = {"door": name or res.name, "entity_id": res.entity_id,
                "reason": res.reason, "confidence": res.confidence}
    msg = ctx.permissions.confirmation_message(intent, res.name)
    plan = {
        "type": "service", "domain": "lock", "service": "unlock",
        "data": {"entity_id": res.entity_id},
        "success_message": f"Unlocked the {res.name}.",
    }
    pc = ctx.confirmations.create(
        intent=intent,
        params={"door": name, "entity_id": res.entity_id, "name": res.name},
        message=msg,
        ttl=ctx.config.permissions.confirmation_ttl_seconds,
        assistant=ctx.assistant.id if ctx.assistant else None,
        user=user_id,
        plan=plan,
        risk_level="critical",
        target=res.name,
        pin_required=ctx.permissions.pin_required(intent, "critical"),
    )
    result = ActionResult.needs_confirmation(intent, msg, pc.token, resolved)
    result.data = {"security": {"pin_required": pc.pin_required}}
    return result
