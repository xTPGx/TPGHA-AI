"""Route a natural-language command -> AI tool selection -> vetted action.

This is the orchestration core. It:
  1. Resolves the active assistant + user.
  2. Asks the AI to select ONE tool (or falls back to a deterministic parser).
  3. Validates the tool name against the allowlist (no arbitrary HA calls).
  4. Dispatches to the matching action handler.
  5. Gates sensitive actions behind confirmation tokens.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from ..actions import ActionContext
from ..actions import automations as automations_action
from ..actions import cameras as cameras_action
from ..actions import climate as climate_action
from ..actions import control as control_action
from ..actions import dashboards as dashboards_action
from ..actions import fans as fans_action
from ..actions import lights as lights_action
from ..actions import locks as locks_action
from ..actions import music as music_action
from ..actions import security as security_action
from ..ai.client import ToolCall, get_ai_client, pre_route
from ..ai.tools import TOOL_NAMES
from ..config_loader import get_config
from ..db.database import get_session
from ..db.models import CommandLog
from ..events import (
    EVT_ACTION_EXECUTED,
    EVT_ACTION_FAILED,
    EVT_CONFIRMATION_REQUIRED,
    get_event_bus,
)
from ..homeassistant.rest import get_ha_client
from ..homeassistant.services import safe_get_states
from ..models.results import ActionResult, CommandResponse
from .permissions import PermissionEngine, get_confirmation_store
from .resolver import Resolver

logger = logging.getLogger("tpg.router")

# Tool name -> handler.
_HANDLERS = {
    "show_camera": cameras_action.show_camera,
    "play_music": music_action.play_music,
    "stop_music": music_action.stop_music,
    "set_volume": music_action.set_volume,
    "lock_door": locks_action.lock_door,
    "unlock_door": locks_action.unlock_door,
    "turn_on_light": lights_action.turn_on_light,
    "turn_off_light": lights_action.turn_off_light,
    "turn_on_fan": fans_action.turn_on_fan,
    "turn_off_fan": fans_action.turn_off_fan,
    "set_fan_percentage": fans_action.set_fan_percentage,
    "set_climate": climate_action.set_climate,
    "security_check": security_action.security_check,
    "open_dashboard": dashboards_action.open_dashboard,
    "create_simple_automation": automations_action.create_simple_automation,
    "control_device": control_action.control_device,
    "query_device": control_action.query_device,
}


async def build_context(assistant_name: Optional[str], user_name: Optional[str]) -> ActionContext:
    config = get_config()
    live = await safe_get_states()
    resolver = Resolver(config, live)

    assistant_obj = None
    user_obj = None
    if assistant_name:
        a = resolver.resolve_assistant(assistant_name)
        if a.matched:
            assistant_obj = resolver.get_assistant(a.id)
    if user_name:
        u = resolver.resolve_user(user_name)
        if u.matched:
            user_obj = resolver.get_user(u.id)
    # Default the user to the assistant's owner.
    if user_obj is None and assistant_obj is not None:
        user_obj = resolver.get_user(assistant_obj.owner)

    return ActionContext(
        config=config,
        resolver=resolver,
        ha=get_ha_client(),
        permissions=PermissionEngine(config),
        confirmations=get_confirmation_store(),
        assistant=assistant_obj,
        user=user_obj,
    )


def _log_command(assistant: str, user: str, message: str, result: ActionResult) -> None:
    try:
        with get_session() as session:
            session.add(CommandLog(
                assistant=assistant or "", user=user or "", message=message,
                intent=result.intent, success=result.success,
                executed=result.executed, response_message=result.message,
            ))
            session.commit()
    except Exception:  # pragma: no cover
        logger.debug("Failed to persist command log", exc_info=True)


async def handle_command(assistant_name: str, user_name: Optional[str], message: str) -> CommandResponse:
    ctx = await build_context(assistant_name, user_name)

    if ctx.assistant is None:
        return CommandResponse(
            success=False, assistant=assistant_name, user=user_name,
            message=f"Unknown assistant '{assistant_name}'.",
            error="unknown_assistant",
        )

    # Deterministic pre-router first (e.g. fan commands), then the AI.
    tool_call: Optional[ToolCall] = pre_route(message)
    if tool_call is None:
        ai = get_ai_client()
        tool_call = ai.select_tool(message, ctx.config, ctx.assistant, ctx.user)

    tool_dict = tool_call.to_dict() if tool_call else None

    if tool_call is None or not tool_call.name:
        text = (tool_call.assistant_text if tool_call else "") or \
            "I couldn't map that to an action."
        return CommandResponse(
            success=False, assistant=ctx.assistant.id,
            user=(ctx.user.id if ctx.user else None),
            message=text, tool_call=tool_dict, error="no_tool_selected",
        )

    if tool_call.name not in TOOL_NAMES or tool_call.name not in _HANDLERS:
        return CommandResponse(
            success=False, assistant=ctx.assistant.id,
            user=(ctx.user.id if ctx.user else None), intent=tool_call.name,
            message=f"Tool '{tool_call.name}' is not allowed.",
            tool_call=tool_dict, error="tool_not_allowed",
        )

    handler = _HANDLERS[tool_call.name]
    result: ActionResult = await handler(ctx, tool_call.arguments)

    _log_command(ctx.assistant.id, ctx.user.id if ctx.user else "", message, result)
    _emit_command_events(ctx, message, result)

    return _to_response(ctx, result, tool_dict)


def _emit_command_events(ctx: ActionContext, message: str, result: ActionResult) -> None:
    bus = get_event_bus()
    bus.set_last_command({
        "assistant": ctx.assistant.id if ctx.assistant else None,
        "user": ctx.user.id if ctx.user else None,
        "message": message,
        "intent": result.intent,
        "success": result.success,
        "executed": result.executed,
        "requires_confirmation": result.requires_confirmation,
        "response_message": result.message,
    })
    if result.requires_confirmation:
        bus.emit(EVT_CONFIRMATION_REQUIRED, {
            "assistant": ctx.assistant.id if ctx.assistant else None,
            "user": ctx.user.id if ctx.user else None,
            "intent": result.intent,
            "confirmation_token": result.confirmation_token,
            "confirmation_message": result.confirmation_message,
            "target": result.resolved.get("target") or result.resolved.get("entity_id"),
        })
    elif result.executed and result.success:
        bus.emit(EVT_ACTION_EXECUTED, {"intent": result.intent, "message": result.message})
    elif not result.success:
        bus.emit(EVT_ACTION_FAILED, {"intent": result.intent, "message": result.message,
                                     "error": result.error})


async def handle_confirmation(token: str) -> CommandResponse:
    store = get_confirmation_store()
    pc = store.pop(token)
    if pc is None:
        # Fail safely: expired or invalid token never executes anything.
        return CommandResponse(
            success=False, executed=False, message="Confirmation expired or invalid.",
            error="invalid_confirmation",
        )
    ctx = await build_context(pc.assistant, pc.user)
    plan = pc.plan or {}
    friendly = pc.target or plan.get("data", {}).get("entity_id", pc.intent)

    result = await control_action.execute_service_plan(ctx, plan, friendly, pc.intent)
    _log_command(pc.assistant or "", pc.user or "", f"[confirm:{pc.intent}]", result)

    bus = get_event_bus()
    if result.executed and result.success:
        bus.emit(EVT_ACTION_EXECUTED, {"intent": pc.intent, "message": result.message,
                                       "confirmed": True})
    elif not result.success:
        bus.emit(EVT_ACTION_FAILED, {"intent": pc.intent, "message": result.message})
    return _to_response(ctx, result, None)


def cancel_confirmation(token: str) -> CommandResponse:
    store = get_confirmation_store()
    ok = store.cancel(token)
    return CommandResponse(
        success=ok, executed=False,
        message="Confirmation cancelled." if ok else "No such pending confirmation.",
        error=None if ok else "invalid_confirmation",
    )


def _to_response(ctx: ActionContext, result: ActionResult, tool_dict: Optional[dict]) -> CommandResponse:
    return CommandResponse(
        success=result.success,
        assistant=(ctx.assistant.id if ctx.assistant else None),
        user=(ctx.user.id if ctx.user else None),
        intent=result.intent,
        resolved=result.resolved,
        executed=result.executed,
        requires_confirmation=result.requires_confirmation,
        confirmation_message=result.confirmation_message,
        confirmation_token=result.confirmation_token,
        message=result.message,
        tool_call=tool_dict,
        data=result.data,
        error=result.error,
    )
