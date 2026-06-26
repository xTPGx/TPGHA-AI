"""Route a natural-language command -> AI tool selection -> vetted action.

This is the orchestration core. It:
  1. Resolves the active assistant + user.
  2. Asks the AI to select ONE tool (or falls back to a deterministic parser).
  3. Validates the tool name against the allowlist (no arbitrary HA calls).
  4. Dispatches to the matching action handler.
  5. Gates sensitive actions behind confirmation tokens.
"""
from __future__ import annotations

import dataclasses
import logging
import json
import re
import time
from typing import Any, Optional

from sqlalchemy import desc

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
from ..ai.client import ToolCall, get_ai_client, pre_route, split_compound_command
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
from ..memory import propose_correction_memory
from ..models.results import ActionResult, CommandResponse
from ..outcomes import verify_action_outcome
from .permissions import PermissionEngine, get_confirmation_store
from .permissions import PendingConfirmation
from .action_policy import (
    CONFIDENCE_REVIEW_THRESHOLD,
    READ_ONLY_INTENTS,
    SENSITIVE_INTENTS,
    evaluate_action_policy,
)
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
    "draft_dashboard": dashboards_action.draft_dashboard,
    "create_simple_automation": automations_action.create_simple_automation,
    "create_routine": automations_action.create_routine,
    "explain_last_action": debug_action.explain_last_action,
    "control_device": control_action.control_device,
    "query_device": control_action.query_device,
}

ADMIN_OR_MANAGER_TOOLS = {
    "draft_dashboard",
}

# Stateful device tools that should ask before acting on a low-confidence
# target match. Sensitive tools (unlock/open) already require confirmation, so
# they are deliberately excluded here.
_CONFIDENCE_GATED_TOOLS = {
    "turn_on_light",
    "turn_off_light",
    "turn_on_fan",
    "turn_off_fan",
    "set_fan_percentage",
    "set_climate",
    "control_device",
    "play_music",
    "set_volume",
}


def source_identity_override(
    config: Any, command_context: Optional[dict[str, Any]]
) -> tuple[Optional[str], Optional[str]]:
    """Map a voice source (satellite/panel) to its room assistant + user.

    A satellite forwards its source_device_id/source_entity_id; if a configured
    voice_source matches and names an assistant, that assistant (the room's
    Atlas/Chatty/Jarvis) is used instead of the caller's fixed default.
    """
    cc = command_context or {}
    sdid = str(cc.get("source_device_id") or "").strip().lower()
    seid = str(cc.get("source_entity_id") or "").strip().lower()
    if not sdid and not seid:
        return (None, None)
    for source in getattr(config.devices, "voice_sources", []) or []:
        matched = False
        if sdid and source.source_device_id and source.source_device_id.lower() == sdid:
            matched = True
        elif seid and source.source_entity_id and source.source_entity_id.lower() == seid:
            matched = True
        else:
            aliases = {a.lower() for a in (source.aliases or [])}
            if (sdid and sdid in aliases) or (seid and seid in aliases):
                matched = True
        if matched:
            return (source.assistant, source.user)
    return (None, None)


def _strip_assistant_address(message: str, assistant_name: Optional[str]) -> str:
    """Remove a leading wake word/name before command routing.

    Voice transcripts commonly arrive as "Atlas, turn on the office light".
    Keeping "Atlas" in the command can poison target resolution, especially for
    short commands like fan speed changes.
    """

    original = (message or "").strip()
    if not original:
        return original
    names: set[str] = {"jarvis", "atlas", "chatty", "computer"}
    if assistant_name:
        names.add(str(assistant_name).strip().lower())
    try:
        config = get_config()
        for assistant in getattr(config.assistants, "assistants", []) or []:
            values = [
                assistant.id,
                assistant.name,
                *(assistant.aliases or []),
                *(assistant.wake_words or []),
                *(getattr(assistant, "conversation_wake_phrases", []) or []),
                *_default_conversation_wake_phrases([
                    assistant.id,
                    assistant.name,
                    *(assistant.aliases or []),
                    *(assistant.wake_words or []),
                ]),
            ]
            names.update(str(value).strip().lower() for value in values if str(value).strip())
    except Exception:  # pragma: no cover - config fallback only
        pass
    escaped = sorted((re.escape(name) for name in names if name), key=len, reverse=True)
    if not escaped:
        return original
    pattern = rf"^\s*(?:hey|ok|okay)?\s*(?:{'|'.join(escaped)})\s*[,.:;!?-]*\s+"
    cleaned = re.sub(pattern, "", original, flags=re.I).strip()
    return cleaned or original


def _default_conversation_wake_phrases(values: list[Any]) -> list[str]:
    phrases: list[str] = []
    seen: set[str] = set()
    for value in values:
        base = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
        if not base or base in seen:
            continue
        seen.add(base)
        phrases.extend([
            f"{base} let's chat",
            f"{base} lets chat",
            f"hey {base} let's chat",
            f"{base} chat with me",
        ])
    return phrases


async def build_context(
    assistant_name: Optional[str],
    user_name: Optional[str],
    command_context: Optional[dict[str, Any]] = None,
) -> ActionContext:
    config = get_config()
    # Route by origin: a known voice source picks the room's assistant/user.
    src_assistant, src_user = source_identity_override(config, command_context)
    if src_assistant:
        assistant_name = src_assistant
    if src_user and not user_name:
        user_name = src_user
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

    ctx = ActionContext(
        config=config,
        resolver=resolver,
        ha=get_ha_client(),
        permissions=PermissionEngine(config),
        confirmations=get_confirmation_store(),
        assistant=assistant_obj,
        user=user_obj,
    )
    ctx.command_context = command_context or {}
    return ctx


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
    command_context: Optional[dict[str, Any]] = None,
    *,
    allow_multi_step: bool = True,
) -> CommandResponse:
    message = _strip_assistant_address(message, assistant_name)
    # Multi-step: "dim the lights and play jazz" -> run each clause in order,
    # each independently gated (trust, confirmation, confidence).
    if allow_multi_step:
        steps = split_compound_command(message)
        if len(steps) > 1:
            return await _handle_multi_step(
                assistant_name, user_name, steps, conversation_id, command_context
            )

    ctx = await build_context(assistant_name, user_name, command_context)

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

    role_denied = _role_denied_response(ctx, tool_call, tool_dict)
    if role_denied is not None:
        return role_denied

    trust_level = _voice_source_trust(ctx)
    trust_denied = _trust_denied_response(ctx, tool_call, tool_dict, trust_level)
    if trust_denied is not None:
        trust_denied.conversation_id = conversation_id
        return trust_denied

    gated = await _low_confidence_gate(ctx, tool_call, tool_dict, conversation_id)
    if gated is not None:
        return gated

    _attach_original_request(tool_call, tool_dict, message)
    handler = _HANDLERS[tool_call.name]
    result: ActionResult = await handler(ctx, tool_call.arguments)
    correction_memory = _maybe_draft_correction_memory(ctx, message, result)
    outcome = await verify_action_outcome(ctx, result)
    result.data = {
        **(result.data or {}),
        "outcome": outcome,
        "policy": evaluate_action_policy(
            result, tool_dict, preview=False, trust_level=trust_level
        ),
    }
    if correction_memory:
        result.data["memory_draft"] = correction_memory

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


async def _handle_multi_step(
    assistant_name: str,
    user_name: Optional[str],
    steps: list[str],
    conversation_id: Optional[str],
    command_context: Optional[dict[str, Any]],
) -> CommandResponse:
    """Run compound sub-commands sequentially and aggregate the result."""
    step_results: list[CommandResponse] = []
    for step in steps:
        resp = await handle_command(
            assistant_name, user_name, step, conversation_id, command_context,
            allow_multi_step=False,
        )
        step_results.append(resp)

    assistant_id = next((r.assistant for r in step_results if r.assistant), assistant_name)
    user_id = next((r.user for r in step_results if r.user), user_name)
    pending = next((r for r in step_results if r.requires_confirmation), None)

    messages = []
    for step, r in zip(steps, step_results):
        messages.append(r.message or f"(no response for '{step}')")
    combined = " ".join(m.strip() for m in messages if m.strip())

    return CommandResponse(
        success=all(r.success for r in step_results),
        assistant=assistant_id,
        user=user_id,
        conversation_id=conversation_id,
        intent="multi_step",
        executed=any(r.executed for r in step_results),
        requires_confirmation=pending is not None,
        confirmation_message=(pending.confirmation_message if pending else None),
        confirmation_token=(pending.confirmation_token if pending else None),
        message=combined or "Done.",
        data={
            "multi_step": True,
            "steps": [
                {
                    "command": step,
                    "intent": r.intent,
                    "success": r.success,
                    "executed": r.executed,
                    "requires_confirmation": r.requires_confirmation,
                    "confirmation_token": r.confirmation_token,
                    "message": r.message,
                    "resolved": r.resolved,
                    "error": r.error,
                }
                for step, r in zip(steps, step_results)
            ],
        },
        error=next((r.error for r in step_results if r.error), None),
    )


async def handle_preview(
    assistant_name: str,
    user_name: Optional[str],
    message: str,
    conversation_id: Optional[str] = None,
    command_context: Optional[dict[str, Any]] = None,
) -> CommandResponse:
    """Resolve and run the command path in dry-run mode.

    Existing handlers still do all normal permission and resolver work, but HA
    service calls are recorded instead of sent, and confirmation tokens are not
    armed. This gives the UI/HA a reliable "what would happen?" layer.
    """
    message = _strip_assistant_address(message, assistant_name)
    ctx = await build_context(assistant_name, user_name, command_context)

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

    role_denied = _role_denied_response(ctx, tool_call, tool_dict)
    if role_denied is not None:
        role_denied.conversation_id = conversation_id
        return role_denied

    _attach_original_request(tool_call, tool_dict, message)
    recorder = RecordingHA(ctx.resolver.live_states)
    preview_confirmations = PreviewConfirmationStore()
    ctx.ha = recorder
    ctx.confirmations = preview_confirmations
    ctx.dry_run = True

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
    preview.data = {
        **(preview.data or {}),
        "policy": evaluate_action_policy(preview, tool_dict, preview=True),
    }
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
        tool_call = ai.select_tool(
            message, ctx.config, ctx.assistant, ctx.user,
            house_context=_house_state_summary(ctx),
            conversation_context=_recent_turns_transcript(
                ctx.assistant.id if ctx.assistant else "",
                ctx.user.id if ctx.user else user_name,
                conversation_id,
            ),
        )

    tool_call = _repair_direction_conflict(message, tool_call)
    if tool_call is not None and tool_call.name == "explain_last_action":
        tool_call.arguments = dict(tool_call.arguments or {})
        tool_call.arguments["conversation_id"] = conversation_id or ""
    tool_call = _apply_room_context(ctx, tool_call)
    return tool_call, (tool_call.to_dict() if tool_call else None)


def _house_state_summary(ctx: ActionContext, *, max_items: int = 8) -> str:
    """Compact live house snapshot to ground tool selection.

    Lets requests like "turn off the light that's on" or presence-aware replies
    work without a separate lookup. Reads the already-loaded live states.
    """
    live = getattr(ctx.resolver, "live_states", {}) or {}
    if not live:
        return ""
    lights_on: list[str] = []
    media_playing: list[str] = []
    people_home: list[str] = []
    open_covers: list[str] = []
    for eid, ent in live.items():
        try:
            domain = eid.split(".", 1)[0]
            state = str(getattr(ent, "state", "") or "").lower()
            name = getattr(ent, "friendly_name", None) or eid
        except Exception:
            continue
        if domain in {"light", "switch"} and state == "on":
            lights_on.append(name)
        elif domain == "media_player" and state == "playing":
            media_playing.append(name)
        elif domain in {"person", "device_tracker"} and state == "home":
            people_home.append(name)
        elif domain == "cover" and state == "open":
            open_covers.append(name)

    def _fmt(label: str, items: list[str]) -> str:
        if not items:
            return ""
        shown = items[:max_items]
        extra = f" (+{len(items) - len(shown)} more)" if len(items) > len(shown) else ""
        return f"- {label}: {', '.join(shown)}{extra}"

    lines = [
        _fmt("Lights/switches currently on", lights_on),
        _fmt("Media currently playing", media_playing),
        _fmt("People home", people_home),
        _fmt("Covers open", open_covers),
    ]
    body = "\n".join(line for line in lines if line)
    return body or "- No lights on, no media playing right now."


def _recent_turns_transcript(
    assistant: str,
    user: Optional[str],
    conversation_id: Optional[str],
    *,
    limit: int = 4,
) -> str:
    """Build a short transcript of recent turns for follow-up grounding."""
    if not conversation_id:
        return ""
    try:
        with get_session() as session:
            rows = (
                session.query(CommandLog)
                .filter(CommandLog.conversation_id == conversation_id)
                .order_by(desc(CommandLog.id))
                .limit(limit)
                .all()
            )
    except Exception:  # pragma: no cover - history is best-effort
        return ""
    if not rows:
        return ""
    lines: list[str] = []
    for row in reversed(rows):
        msg = (row.message or "").strip()
        reply = (row.response_message or "").strip()
        if msg:
            lines.append(f"User: {msg}")
        if reply:
            lines.append(f"Assistant: {reply}")
    return "\n".join(lines[-(limit * 2):])


def _attach_original_request(
    tool_call: ToolCall,
    tool_dict: Optional[dict[str, Any]],
    message: str,
) -> None:
    """Preserve the full utterance for tools that need compound instructions."""
    if tool_call.name != "create_simple_automation":
        return
    args = dict(tool_call.arguments or {})
    args.setdefault("original_request", message)
    tool_call.arguments = args
    if isinstance(tool_dict, dict):
        dict_args = tool_dict.setdefault("arguments", {})
        if isinstance(dict_args, dict):
            dict_args.setdefault("original_request", message)


def _apply_room_context(ctx: ActionContext, tool_call: Optional[ToolCall]) -> Optional[ToolCall]:
    if tool_call is None or not tool_call.name:
        return tool_call
    room = _room_from_command_source(ctx)
    if not room:
        return tool_call
    args = dict(tool_call.arguments or {})
    key = "target"
    if tool_call.name in {"show_camera"}:
        key = "camera"
    elif tool_call.name in {"lock_door", "unlock_door"}:
        key = "door"
    elif tool_call.name in {"play_music", "stop_music", "set_volume", "set_climate"}:
        key = "room"
    target = str(args.get(key) or "").strip()
    generic = {"", "it", "this", "that", "there", "light", "lights", "fan", "fans",
               "tv", "television", "display", "screen", "speaker", "music"}
    if target.lower() in generic:
        suffix = target if target and target.lower() not in {"it", "this", "that", "there"} else ""
        args[key] = f"{room} {suffix}".strip()
        return ToolCall(tool_call.name, args, source=f"{tool_call.source}:room_context",
                        assistant_text=tool_call.assistant_text)
    return tool_call


def _room_from_command_source(ctx: ActionContext) -> str:
    command_context = getattr(ctx, "command_context", {}) or {}
    room = str(command_context.get("room") or "").strip()
    if room:
        return room

    source_device_id = str(command_context.get("source_device_id") or "").strip().lower()
    source_entity_id = str(command_context.get("source_entity_id") or "").strip().lower()
    if not source_device_id and not source_entity_id:
        return ""

    for source in getattr(ctx.config.devices, "voice_sources", []) or []:
        if source_device_id and source.source_device_id and source.source_device_id.lower() == source_device_id:
            return source.room
        if source_entity_id and source.source_entity_id and source.source_entity_id.lower() == source_entity_id:
            return source.room
        aliases = {a.lower() for a in (source.aliases or [])}
        if source_device_id in aliases or source_entity_id in aliases:
            return source.room
    return ""


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


_CORRECTION_MEMORY_RE = re.compile(
    r"\b(that'?s not|not what|i said|i meant|actually|correction|wrong|no,?)\b",
    re.I,
)


def _maybe_draft_correction_memory(
    ctx: ActionContext,
    message: str,
    result: ActionResult,
) -> Optional[dict[str, Any]]:
    if not (result.success and result.executed):
        return None
    if not _CORRECTION_MEMORY_RE.search(message):
        return None
    try:
        return propose_correction_memory(ctx.user.id if ctx.user else "", message, result)
    except Exception:  # pragma: no cover - memory drafting should never break actions
        logger.debug("Failed to draft correction memory", exc_info=True)
        return None


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
        self,
        domain: str,
        service: str,
        data: Optional[dict] = None,
        *,
        return_response: bool = False,
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

    async def music_assistant_play_media(
        self,
        entity_id: str,
        media_id: str | list[str],
        media_type: Optional[str] = None,
        enqueue: str = "replace",
        radio_mode: bool = False,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "entity_id": entity_id,
            "media_id": media_id,
            "enqueue": enqueue,
        }
        if media_type:
            data["media_type"] = media_type
        if radio_mode:
            data["radio_mode"] = True
        return await self.call_service("music_assistant", "play_media", data)

    async def music_assistant_search(
        self,
        name: str,
        *,
        limit: int = 8,
        media_type: Optional[str] = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {"name": name, "limit": limit}
        if media_type:
            data["media_type"] = [media_type]
        return await self.call_service(
            "music_assistant", "search", data, return_response=True
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
               target: str = "", pin_required: bool = False) -> PendingConfirmation:
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
            pin_required=pin_required,
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


async def handle_confirmation(token: str, security_pin: Optional[str] = None) -> CommandResponse:
    store = get_confirmation_store()
    pc = store.pop(token)
    if pc is None:
        # Fail safely: expired or invalid token never executes anything.
        return CommandResponse(
            success=False, executed=False, message="Confirmation expired or invalid.",
            error="invalid_confirmation",
        )
    ctx = await build_context(pc.assistant, pc.user)
    if pc.pin_required and not ctx.permissions.verify_pin(security_pin):
        return CommandResponse(
            success=False,
            executed=False,
            message="Security PIN required or incorrect.",
            error="invalid_security_pin",
        )
    plan = pc.plan or {}
    friendly = pc.target or plan.get("data", {}).get("entity_id", pc.intent)

    result = await control_action.execute_service_plan(ctx, plan, friendly, pc.intent)
    outcome = await verify_action_outcome(ctx, result)
    result.data = {**(result.data or {}), "outcome": outcome}
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


def _role_denied_response(
    ctx: ActionContext,
    tool_call: ToolCall,
    tool_dict: Optional[dict[str, Any]],
) -> CommandResponse | None:
    """Server-side AI tool authorization by user role.

    UI menus are convenience only. This keeps HA Assist, Chat, preview, and
    direct command calls aligned: residents can talk, brainstorm, control
    permitted devices, and draft schedules/automations, but dashboard/view
    builder tools stay admin/manager-only.
    """
    role = (ctx.user.role if ctx.user else "guest").lower()
    if tool_call.name in ADMIN_OR_MANAGER_TOOLS and role not in {"admin", "manager"}:
        return CommandResponse(
            success=False,
            assistant=(ctx.assistant.id if ctx.assistant else None),
            user=(ctx.user.id if ctx.user else None),
            intent=tool_call.name,
            executed=False,
            message=(
                "That is an owner/admin management action. I can brainstorm the idea "
                "with you, but dashboard and view changes need Shawn/Owner/Admin."
            ),
            tool_call=tool_dict,
            data={
                "policy": {
                    "decision": "denied",
                    "risk": "medium",
                    "confidence": 1.0,
                    "requires_review": False,
                    "can_auto_execute": False,
                    "preview": False,
                    "reasons": ["role_not_allowed"],
                    "required_role": "admin_or_manager",
                    "actual_role": role,
                }
            },
            error="role_not_allowed",
        )
    return None


def _voice_source_trust(ctx: ActionContext) -> str:
    """Resolve the trust level of the command's origin.

    Direct UI/API/HA Assist calls (no voice-source context) are 'trusted'. A
    mapped `voice_sources` entry supplies its configured trust_level. Callers
    may also pass an explicit trust_level in command_context.
    """
    cc = getattr(ctx, "command_context", {}) or {}
    explicit = str(cc.get("trust_level") or "").strip().lower()
    if explicit in {"trusted", "household", "guest", "outside"}:
        return explicit

    sdid = str(cc.get("source_device_id") or "").strip().lower()
    seid = str(cc.get("source_entity_id") or "").strip().lower()
    if not sdid and not seid:
        return "trusted"

    for source in getattr(ctx.config.devices, "voice_sources", []) or []:
        if sdid and source.source_device_id and source.source_device_id.lower() == sdid:
            return source.trust_level
        if seid and source.source_entity_id and source.source_entity_id.lower() == seid:
            return source.trust_level
        aliases = {a.lower() for a in (source.aliases or [])}
        if (sdid and sdid in aliases) or (seid and seid in aliases):
            return source.trust_level
    # Known external origin but not mapped: treat as household (normal control
    # allowed; sensitive actions still require confirmation downstream).
    return "household"


def _trust_denied_response(
    ctx: ActionContext,
    tool_call: ToolCall,
    tool_dict: Optional[dict[str, Any]],
    trust_level: str,
) -> CommandResponse | None:
    """Block sensitive/state-changing actions from untrusted voice sources.

    - 'outside' sources may only ask questions (read-only intents).
    - 'guest' sources may control normal devices but never security/access.
    Enforced before execution so an untrusted mic can't unlock a door.
    """
    trust = (trust_level or "trusted").lower()
    if trust in {"trusted", "household"}:
        return None

    name = tool_call.name
    is_read_only = name in READ_ONLY_INTENTS
    is_sensitive = name in SENSITIVE_INTENTS

    reason = ""
    risk = "high"
    if trust == "outside" and not is_read_only:
        reason = "outside_source_blocked"
    elif trust == "guest" and is_sensitive:
        reason = "guest_source_sensitive_blocked"
        risk = "critical"
    if not reason:
        return None

    msg = (
        f"That request came from a '{trust}' voice source, so I can't run "
        "security or device-changing actions from there."
    )
    return CommandResponse(
        success=False,
        assistant=(ctx.assistant.id if ctx.assistant else None),
        user=(ctx.user.id if ctx.user else None),
        intent=name,
        executed=False,
        message=msg,
        tool_call=tool_dict,
        data={
            "policy": {
                "decision": "denied",
                "risk": risk,
                "confidence": 1.0,
                "requires_review": False,
                "can_auto_execute": False,
                "preview": False,
                "trust_level": trust,
                "reasons": [reason],
            }
        },
        error="untrusted_source",
    )


def _confidence_value(resolved: Optional[dict[str, Any]]) -> float:
    value = (resolved or {}).get("confidence")
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 1.0


async def _run_preview_pass(
    ctx: ActionContext, tool_call: ToolCall
) -> tuple[ActionResult, "RecordingHA"]:
    """Run a handler in dry-run mode to learn confidence + planned calls."""
    recorder = RecordingHA(ctx.resolver.live_states)
    pctx = dataclasses.replace(
        ctx,
        ha=recorder,
        confirmations=PreviewConfirmationStore(),
        dry_run=True,
    )
    result = await _HANDLERS[tool_call.name](pctx, dict(tool_call.arguments or {}))
    return result, recorder


def _disambiguation_response(
    ctx: ActionContext,
    tool_call: ToolCall,
    tool_dict: Optional[dict[str, Any]],
    resolved: dict[str, Any],
    conversation_id: Optional[str],
) -> CommandResponse | None:
    """Ask which device when the resolver reports a near-equal tie."""
    if not resolved.get("ambiguous"):
        return None
    alts = [a for a in (resolved.get("alternatives") or []) if isinstance(a, dict)][:3]
    if len(alts) < 2:
        return None
    names = [str(a.get("name") or a.get("entity_id")) for a in alts]
    options = " or ".join(filter(None, (", ".join(names[:-1]), names[-1]))) if len(names) > 2 else " or ".join(names)
    msg = f"Did you mean {options}? Tell me which one and I'll do it."
    resp = CommandResponse(
        success=True,
        assistant=(ctx.assistant.id if ctx.assistant else None),
        user=(ctx.user.id if ctx.user else None),
        intent=tool_call.name,
        resolved=resolved,
        executed=False,
        message=msg,
        tool_call=tool_dict,
        data={
            "policy": {
                "decision": "clarify",
                "risk": "low",
                "confidence": _confidence_value(resolved),
                "requires_review": True,
                "can_auto_execute": False,
                "preview": False,
                "trust_level": _voice_source_trust(ctx),
                "reasons": ["needs_disambiguation"],
            },
            "disambiguation": {"options": alts},
        },
        error="needs_disambiguation",
    )
    resp.conversation_id = conversation_id
    return resp


async def _low_confidence_gate(
    ctx: ActionContext,
    tool_call: ToolCall,
    tool_dict: Optional[dict[str, Any]],
    conversation_id: Optional[str],
) -> CommandResponse | None:
    """Ask before acting when the resolved device match is below threshold.

    Runs the handler once in dry-run mode (no HA writes) to learn the resolved
    confidence and the exact service call. Sub-threshold stateful actions become
    a confirmation (single planned call) or a clarification (ambiguous), so the
    assistant never silently acts on a weak guess.
    """
    if tool_call.name not in _CONFIDENCE_GATED_TOOLS:
        return None
    try:
        preview_result, recorder = await _run_preview_pass(ctx, tool_call)
    except Exception:  # pragma: no cover - never let the gate break a command
        logger.debug("Low-confidence preview gate failed; proceeding", exc_info=True)
        return None

    # Sensitive/handler-driven confirmations are handled by the real run.
    if preview_result.requires_confirmation:
        return None

    resolved = preview_result.resolved or {}
    would_execute = bool(preview_result.executed or recorder.calls)

    # Disambiguation: two near-equal device matches -> ask which one.
    disambig = _disambiguation_response(ctx, tool_call, tool_dict, resolved, conversation_id)
    if disambig is not None and would_execute:
        return disambig

    confidence = _confidence_value(resolved)
    if not would_execute or confidence >= CONFIDENCE_REVIEW_THRESHOLD:
        return None

    target = resolved.get("name") or resolved.get("entity_id") or "that device"
    pct = int(round(confidence * 100))
    calls = recorder.calls

    if len(calls) == 1:
        call = calls[0]
        plan = {
            "domain": call.get("domain"),
            "service": call.get("service"),
            "data": call.get("data") or {},
        }
        ttl = int(getattr(ctx.config.permissions, "confirmation_ttl_seconds", 120) or 120)
        msg = (
            f"I'm only about {pct}% sure you mean {target}. "
            "Want me to go ahead?"
        )
        pc = ctx.confirmations.create(
            intent=tool_call.name,
            params=dict(tool_call.arguments or {}),
            message=msg,
            ttl=ttl,
            assistant=(ctx.assistant.id if ctx.assistant else None),
            user=(ctx.user.id if ctx.user else None),
            plan=plan,
            risk_level="low",
            target=str(target),
            pin_required=False,
        )
        resp = CommandResponse(
            success=True,
            assistant=(ctx.assistant.id if ctx.assistant else None),
            user=(ctx.user.id if ctx.user else None),
            intent=tool_call.name,
            resolved=resolved,
            executed=False,
            requires_confirmation=True,
            confirmation_message=msg,
            confirmation_token=pc.token,
            message=msg,
            tool_call=tool_dict,
            data={
                "policy": {
                    "decision": "review_required",
                    "risk": "low",
                    "confidence": confidence,
                    "requires_review": True,
                    "can_auto_execute": False,
                    "preview": False,
                    "trust_level": _voice_source_trust(ctx),
                    "reasons": ["low_target_confidence_gate"],
                },
                "preview": {"would_execute": True, "service_calls": calls},
            },
        )
        resp.conversation_id = conversation_id
        return resp

    # Multiple planned calls + low confidence -> ask for specifics, don't guess.
    msg = (
        "I'm not sure which device you meant. Could you be more specific? "
        f"(closest match: {target})"
    )
    resp = CommandResponse(
        success=False,
        assistant=(ctx.assistant.id if ctx.assistant else None),
        user=(ctx.user.id if ctx.user else None),
        intent=tool_call.name,
        resolved=resolved,
        executed=False,
        message=msg,
        tool_call=tool_dict,
        data={
            "policy": {
                "decision": "clarify",
                "risk": "low",
                "confidence": confidence,
                "requires_review": True,
                "can_auto_execute": False,
                "preview": False,
                "trust_level": _voice_source_trust(ctx),
                "reasons": ["ambiguous_low_confidence"],
            }
        },
        error="needs_clarification",
    )
    resp.conversation_id = conversation_id
    return resp


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
