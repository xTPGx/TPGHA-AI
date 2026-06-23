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
import json
import re
import time
from typing import Any, Optional

from ..actions import ActionContext
from ..actions import automations as automations_action
from ..actions import cameras as cameras_action
from ..actions import climate as climate_action
from ..actions import control as control_action
from ..actions import dashboards as dashboards_action
from ..actions import debug as debug_action
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
from .permissions import PendingConfirmation
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
    "explain_last_action": debug_action.explain_last_action,
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


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value or {}, default=str)
    except TypeError:
        return "{}"


def _log_command(
    assistant: str,
    user: str,
    message: str,
    result: ActionResult,
    *,
    conversation_id: Optional[str] = None,
    tool_call: Optional[dict[str, Any]] = None,
) -> None:
    try:
        with get_session() as session:
            session.add(CommandLog(
                assistant=assistant or "", user=user or "", message=message,
                conversation_id=conversation_id or "",
                intent=result.intent, success=result.success,
                executed=result.executed, response_message=result.message,
                tool_call=_safe_json(tool_call),
                resolved=_safe_json(result.resolved),
                data=_safe_json(result.data),
                error=result.error or "",
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

    tool_call, tool_dict = _select_tool(ctx, user_name, message, conversation_id)

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

    _log_command(
        ctx.assistant.id,
        ctx.user.id if ctx.user else "",
        message,
        result,
        conversation_id=conversation_id,
        tool_call=tool_dict,
    )
    _emit_command_events(ctx, message, result)
    if result.intent != "explain_last_action":
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


async def handle_preview(
    assistant_name: str,
    user_name: Optional[str],
    message: str,
    conversation_id: Optional[str] = None,
) -> CommandResponse:
    """Resolve and run the command path in dry-run mode.

    Existing handlers still do all normal permission and resolver work, but HA
    service calls are recorded instead of sent, and confirmation tokens are not
    armed. This gives the UI/HA a reliable "what would happen?" layer.
    """
    ctx = await build_context(assistant_name, user_name)

    if ctx.assistant is None:
        return CommandResponse(
            success=False, assistant=assistant_name, user=user_name,
            message=f"Unknown assistant '{assistant_name}'.",
            error="unknown_assistant",
        )

    tool_call, tool_dict = _select_tool(ctx, user_name, message, conversation_id)

    if tool_call is None or not tool_call.name:
        text = (tool_call.assistant_text if tool_call else "") or \
            "I couldn't map that to an action."
        return CommandResponse(
            success=False, assistant=ctx.assistant.id,
            user=(ctx.user.id if ctx.user else None),
            conversation_id=conversation_id,
            message=text, tool_call=tool_dict, error="no_tool_selected",
        )

    if tool_call.name not in TOOL_NAMES or tool_call.name not in _HANDLERS:
        return CommandResponse(
            success=False, assistant=ctx.assistant.id,
            user=(ctx.user.id if ctx.user else None), intent=tool_call.name,
            conversation_id=conversation_id,
            message=f"Tool '{tool_call.name}' is not allowed.",
            tool_call=tool_dict, error="tool_not_allowed",
        )

    recorder = RecordingHA(ctx.resolver.live_states)
    preview_confirmations = PreviewConfirmationStore()
    ctx.ha = recorder
    ctx.confirmations = preview_confirmations

    result: ActionResult = await _HANDLERS[tool_call.name](ctx, tool_call.arguments)
    would_execute = bool(result.executed or recorder.calls or result.requires_confirmation)
    data = dict(result.data or {})
    data["preview"] = {
        "dry_run": True,
        "would_execute": would_execute,
        "service_calls": recorder.calls,
        "confirmations": [pc.public_dict() for pc in preview_confirmations.items],
        "original_executed": result.executed,
    }
    message_prefix = "Preview:"
    if result.requires_confirmation:
        msg = result.confirmation_message or result.message
        message = f"{message_prefix} this would require confirmation. {msg}"
    elif recorder.calls:
        call_text = ", ".join(f"{c['domain']}.{c['service']}" for c in recorder.calls)
        message = f"{message_prefix} I would run {call_text}. {result.message}"
    else:
        message = f"{message_prefix} {result.message}"

    preview = ActionResult(
        success=result.success,
        intent=result.intent,
        executed=False,
        message=message,
        requires_confirmation=result.requires_confirmation,
        confirmation_message=result.confirmation_message,
        confirmation_token=None,
        resolved=result.resolved,
        data=data,
        error=result.error,
    )
    resp = _to_response(ctx, preview, tool_dict)
    resp.conversation_id = conversation_id
    return resp


def _select_tool(
    ctx: ActionContext,
    user_name: Optional[str],
    message: str,
    conversation_id: Optional[str],
) -> tuple[Optional[ToolCall], Optional[dict[str, Any]]]:
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
    if tool_call is not None and tool_call.name == "explain_last_action":
        tool_call.arguments = dict(tool_call.arguments or {})
        tool_call.arguments["conversation_id"] = conversation_id or ""
    return tool_call, (tool_call.to_dict() if tool_call else None)


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
        "resolved": result.resolved,
        "data": result.data,
        "error": result.error,
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


class RecordingHA:
    """Home Assistant client shim for command previews.

    It exposes the small HomeAssistantREST surface used by action handlers, but
    never sends a write to Home Assistant.
    """

    configured = True

    def __init__(self, live_states: dict[str, Any]) -> None:
        self.live_states = live_states or {}
        self.calls: list[dict[str, Any]] = []

    async def get_entity(self, entity_id: str) -> dict[str, Any]:
        ent = self.live_states.get(entity_id)
        if ent is None:
            return {"entity_id": entity_id, "state": "unknown", "attributes": {}}
        return {
            "entity_id": ent.entity_id,
            "state": ent.state,
            "attributes": ent.attributes or {},
        }

    async def is_available(self, entity_id: str) -> bool:
        ent = self.live_states.get(entity_id)
        if ent is None:
            return True
        return bool(ent.available)

    async def call_service(
        self, domain: str, service: str, data: Optional[dict] = None
    ) -> dict[str, Any]:
        call = {"domain": domain, "service": service, "data": data or {}}
        self.calls.append(call)
        return {"preview": True, "service_call": call}

    async def turn_on(self, entity_id: str, **extra: Any) -> dict[str, Any]:
        domain = entity_id.split(".", 1)[0]
        return await self.call_service(domain, "turn_on", {"entity_id": entity_id, **extra})

    async def turn_off(self, entity_id: str, **extra: Any) -> dict[str, Any]:
        domain = entity_id.split(".", 1)[0]
        return await self.call_service(domain, "turn_off", {"entity_id": entity_id, **extra})

    async def lock(self, entity_id: str) -> dict[str, Any]:
        return await self.call_service("lock", "lock", {"entity_id": entity_id})

    async def unlock(self, entity_id: str) -> dict[str, Any]:
        return await self.call_service("lock", "unlock", {"entity_id": entity_id})

    async def set_volume(self, entity_id: str, level: float) -> dict[str, Any]:
        return await self.call_service(
            "media_player",
            "volume_set",
            {"entity_id": entity_id, "volume_level": max(0.0, min(1.0, float(level)))},
        )

    async def media_stop(self, entity_id: str) -> dict[str, Any]:
        return await self.call_service("media_player", "media_stop", {"entity_id": entity_id})

    async def play_media(
        self, entity_id: str, media_content_id: str, media_content_type: str
    ) -> dict[str, Any]:
        return await self.call_service(
            "media_player",
            "play_media",
            {
                "entity_id": entity_id,
                "media_content_id": media_content_id,
                "media_content_type": media_content_type,
            },
        )

    async def set_climate_temperature(
        self,
        entity_id: str,
        temperature: float,
        hvac_mode: Optional[str] = None,
    ) -> dict[str, Any]:
        if hvac_mode:
            await self.call_service(
                "climate",
                "set_hvac_mode",
                {"entity_id": entity_id, "hvac_mode": hvac_mode},
            )
        return await self.call_service(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": float(temperature)},
        )


class PreviewConfirmationStore:
    """Records confirmation requirements without arming real tokens."""

    def __init__(self) -> None:
        self.items: list[PendingConfirmation] = []

    def create(self, intent: str, params: dict[str, Any], message: str,
               ttl: int, assistant: Optional[str], user: Optional[str],
               plan: dict[str, Any], risk_level: str = "critical",
               target: str = "") -> PendingConfirmation:
        now = time.monotonic()
        pc = PendingConfirmation(
            token=f"preview-{len(self.items) + 1}",
            intent=intent,
            params=params,
            assistant=assistant,
            user=user,
            expires_at=now + ttl,
            created_at=now,
            message=message,
            plan=plan,
            risk_level=risk_level,
            target=target,
        )
        self.items.append(pc)
        return pc

    def pop(self, token: str) -> None:
        return None

    def cancel(self, token: str) -> bool:
        return False

    def list_pending(self) -> list[PendingConfirmation]:
        return list(self.items)

    def purge_expired(self) -> None:
        return None


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
