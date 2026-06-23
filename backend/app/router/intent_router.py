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
import re
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
from .conversation_context import context_tool_call, load_context, save_context
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
    "create_routine": automations_action.create_routine,
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


async def handle_command(
    assistant_name: str,
    user_name: Optional[str],
    message: str,
    conversation_id: Optional[str] = None,
) -> CommandResponse:
    ctx = await build_context(assistant_name, user_name)

    if ctx.assistant is None:
        return CommandResponse(
            success=False, assistant=assistant_name, user=user_name,
            message=f"Unknown assistant '{assistant_name}'.",
            error="unknown_assistant",
        )

    conv = load_context(ctx.assistant.id, ctx.user.id if ctx.user else user_name,
                        conversation_id)

    # Conversation context first for pronouns/corrections ("turn it off",
    # "actually the fan"), then deterministic pre-router, then the AI.
    tool_call: Optional[ToolCall] = context_tool_call(message, conv)
    if tool_call is None:
        tool_call = pre_route(message)
    if tool_call is None:
        ai = get_ai_client()
        tool_call = ai.select_tool(message, ctx.config, ctx.assistant, ctx.user)

    tool_call = _repair_direction_conflict(message, tool_call)
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
    save_context(
        assistant=ctx.assistant.id,
        user=ctx.user.id if ctx.user else user_name,
        conversation_id=conversation_id,
        message=message,
        result=result,
    )

    resp = _to_response(ctx, result, tool_dict)
    resp.conversation_id = conversation_id
    return resp


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


_ON_RE = re.compile(r"\b(turn|switch|power)\s+on\b|\benable\b", re.I)
_OFF_RE = re.compile(r"\b(turn|switch|power|shut)\s+off\b|\bdisable\b", re.I)


def _repair_direction_conflict(message: str, tool_call: Optional[ToolCall]) -> Optional[ToolCall]:
    """Never let model/tool ambiguity invert obvious on/off/lock commands.

    The deterministic pre-router should catch common commands first, but this
    belt-and-suspenders guard protects OpenAI tool calls, generic control calls,
    and future voice transcripts where a wrong polarity would be unacceptable.
    """
    if tool_call is None or not tool_call.name:
        return tool_call

    text = message.lower()
    wants_on = bool(_ON_RE.search(text))
    wants_off = bool(_OFF_RE.search(text))
    if wants_on == wants_off:
        # Either no explicit direction, or contradictory wording. Leave it for
        # normal routing/clarification instead of guessing.
        return tool_call

    args = dict(tool_call.arguments or {})
    corrected = tool_call.name

    if wants_on:
        if tool_call.name == "turn_off_light":
            corrected = "turn_on_light"
        elif tool_call.name == "turn_off_fan":
            corrected = "turn_on_fan"
        elif tool_call.name == "control_device" and _action_is_off(args.get("action")):
            args["action"] = "turn_on"
    else:
        if tool_call.name == "turn_on_light":
            corrected = "turn_off_light"
        elif tool_call.name == "turn_on_fan":
            corrected = "turn_off_fan"
        elif tool_call.name == "control_device" and _action_is_on(args.get("action")):
            args["action"] = "turn_off"

    if "unlock" in text and tool_call.name == "lock_door":
        corrected = "unlock_door"
    elif "lock" in text and "unlock" not in text and tool_call.name == "unlock_door":
        corrected = "lock_door"

    if corrected != tool_call.name or args != tool_call.arguments:
        logger.warning(
            "Corrected conflicting tool direction: message=%r tool=%s corrected=%s",
            message,
            tool_call.name,
            corrected,
        )
        return ToolCall(corrected, args, source=f"{tool_call.source}:direction_guard",
                        assistant_text=tool_call.assistant_text)
    return tool_call


def _action_is_on(action: Any) -> bool:
    return str(action or "").lower() in {"on", "turn_on", "switch_on", "enable", "power_on"}


def _action_is_off(action: Any) -> bool:
    return str(action or "").lower() in {"off", "turn_off", "switch_off", "disable", "power_off"}


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
