"""OpenAI tool/function-calling definitions.

The AI may ONLY select one of these structured tools. It never executes
anything and never makes arbitrary Home Assistant service calls. The backend
maps each tool name to a vetted action handler.
"""
from __future__ import annotations

# Canonical list of tool/intent names the backend knows how to execute.
TOOL_NAMES = [
    "show_camera",
    "play_music",
    "stop_music",
    "set_volume",
    "lock_door",
    "unlock_door",
    "turn_on_light",
    "turn_off_light",
    "turn_on_fan",
    "turn_off_fan",
    "set_fan_percentage",
    "set_climate",
    "security_check",
    "open_dashboard",
    "draft_dashboard",
    "create_simple_automation",
    "create_routine",
    "explain_last_action",
    "control_device",
    "query_device",
]


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


TOOLS = [
    _fn(
        "show_camera",
        "Show or pull up a security camera feed by friendly name or location "
        "(e.g. 'driveway', 'front door', 'back yard').",
        {
            "camera": {"type": "string", "description": "Camera or location name."},
            "target": {"type": "string", "description": "Optional display/room to show it on."},
        },
        ["camera"],
    ),
    _fn(
        "play_music",
        "Play music on a speaker/room. Use the requesting user's own music "
        "account. 'room' may be a room name or 'everywhere'.",
        {
            "user": {"type": "string", "description": "User requesting music (defaults to assistant owner)."},
            "room": {"type": "string", "description": "Room or speaker, e.g. 'office', 'everywhere'."},
            "query": {"type": "string", "description": "Optional song/artist/playlist."},
        },
        ["room"],
    ),
    _fn(
        "stop_music",
        "Stop music in a room or speaker.",
        {"room": {"type": "string", "description": "Room or speaker to stop."}},
        ["room"],
    ),
    _fn(
        "set_volume",
        "Set the volume of a room/speaker. Level is 0-100 (percent) or 0-1.",
        {
            "room": {"type": "string"},
            "level": {"type": "number", "description": "Volume 0-100 or 0-1."},
        },
        ["room", "level"],
    ),
    _fn(
        "lock_door",
        "Lock a door immediately.",
        {"door": {"type": "string", "description": "Door name, e.g. 'front door'."}},
        ["door"],
    ),
    _fn(
        "unlock_door",
        "Unlock a door. This is sensitive and requires user confirmation.",
        {"door": {"type": "string"}},
        ["door"],
    ),
    _fn(
        "turn_on_light",
        "Turn on a light by entity or room.",
        {"target": {"type": "string", "description": "Light or room name."}},
        ["target"],
    ),
    _fn(
        "turn_off_light",
        "Turn off a light by entity or room.",
        {"target": {"type": "string"}},
        ["target"],
    ),
    _fn(
        "turn_on_fan",
        "Turn on a fan by entity, room, or name (e.g. 'office fan').",
        {"target": {"type": "string", "description": "Fan or room name, e.g. 'office fan'."}},
        ["target"],
    ),
    _fn(
        "turn_off_fan",
        "Turn off a fan by entity, room, or name (e.g. 'office fan').",
        {"target": {"type": "string", "description": "Fan or room name, e.g. 'office fan'."}},
        ["target"],
    ),
    _fn(
        "set_fan_percentage",
        "Set a fan's speed/level/power. Accept natural requests like "
        "'fan speed 50', 'fan level high', or 'fan power max'. The numeric "
        "argument is normalized to 0-100.",
        {
            "target": {"type": "string", "description": "Fan or room name, e.g. 'office fan'."},
            "percentage": {"type": "number", "description": "Normalized fan speed/level 0-100."},
        },
        ["target", "percentage"],
    ),
    _fn(
        "set_climate",
        "Set thermostat mode and temperature for a room. mode is one of "
        "heat, cool, heat_cool, auto, off.",
        {
            "room": {"type": "string"},
            "mode": {"type": "string", "description": "heat|cool|heat_cool|auto|off"},
            "temperature": {"type": "number"},
        },
        ["mode", "temperature"],
    ),
    _fn(
        "security_check",
        "Report the security status: locks, cameras, and security sensors.",
        {},
        [],
    ),
    _fn(
        "open_dashboard",
        "Open a Home Assistant dashboard or a specific view.",
        {
            "target": {"type": "string", "description": "Optional area/room context."},
            "dashboard": {"type": "string", "description": "Dashboard key e.g. security, cameras, music."},
        },
        [],
    ),
    _fn(
        "create_simple_automation",
        "Draft a scheduled action, state/event automation, conditional automation, notification automation, sleep timer, routine, or smart suggestion "
        "from natural language. Never created live; returned for human approval "
        "or editing. Use for requests like 'turn the TV off in 30 minutes', "
        "'set a sleep timer', 'dim the kitchen display at 10', 'when the front "
        "door unlocks turn on the hall light', 'if the battery drops below 20 "
        "notify me', 'between 10 PM and 6 AM', 'only if the office light is off', "
        "'notify me when the garage opens', 'turn on the fan for 10 minutes', "
        "'every 15 minutes notify me', 'every hour check the garage', "
        "'tomorrow at 7 turn off all lights', 'next Monday at 6 PM lock up', "
        "'weekdays during summer at 6 PM', 'on Christmas at 7 PM', "
        "'when my calendar event starts notify me', "
        "and proactive suggestions.",
        {
            "trigger_description": {"type": "string"},
            "action_description": {"type": "string"},
        },
        ["trigger_description", "action_description"],
    ),
    _fn(
        "create_routine",
        "Draft a named multi-step house routine such as movie mode, bedtime, "
        "morning, leaving home, or security check. Returned for approval before "
        "installing.",
        {
            "routine": {"type": "string", "description": "Routine name/type."},
            "room": {"type": "string", "description": "Optional room context."},
        },
        ["routine"],
    ),
    _fn(
        "explain_last_action",
        "Explain the most recent house action: what command was heard, which "
        "tool was selected, what target was resolved, whether it executed, and "
        "what error/result came back. Use for questions like 'why did you do "
        "that?', 'what did you just do?', or 'explain the last action'.",
        {
            "conversation_id": {
                "type": "string",
                "description": "Optional active conversation id for the chat session.",
            },
            "include_failed": {
                "type": "boolean",
                "description": "Whether failed commands are allowed in the explanation.",
            },
        },
        [],
    ),
    _fn(
        "draft_dashboard",
        "Draft a Home Assistant Lovelace dashboard from the approved TPG HomeAI "
        "house graph. Use for requests like 'build a dashboard for the office', "
        "'create a tablet dashboard', 'make a dashboard for these lights', or "
        "'edit/redesign a dashboard for this room'. This returns a reviewable "
        "draft; it does not overwrite a live dashboard.",
        {
            "title": {"type": "string", "description": "Dashboard title."},
            "room": {"type": "string", "description": "Optional room/area to focus."},
            "style": {"type": "string", "description": "native or mushroom."},
            "target": {"type": "string", "description": "Free-text dashboard target or edit request."},
            "include_tablets": {"type": "boolean", "description": "Include tablet/display view."},
            "include_voice": {"type": "boolean", "description": "Include voice/source view."},
        },
        ["title"],
    ),
    _fn(
        "control_device",
        "Generic device control for any supported device by friendly name, "
        "room, or entity id. Use when no specific tool fits. action is a verb "
        "like 'turn_on', 'turn_off', 'set_percentage', 'speed', 'level', "
        "'open', 'close', "
        "'set_temperature', 'set_volume'. Sensitive actions (unlock, open "
        "garage, disarm) are confirmation-gated by the backend.",
        {
            "target": {"type": "string", "description": "Device/room/entity, e.g. 'office fan'."},
            "action": {"type": "string", "description": "Verb to perform."},
            "value": {"type": "string",
                      "description": "Optional value as text (speed/level percentage, temperature, source, etc.)."},
        },
        ["target", "action"],
    ),
    _fn(
        "query_device",
        "Get the current status/state of a device by friendly name, room, or "
        "entity id.",
        {"target": {"type": "string", "description": "Device/room/entity to query."}},
        ["target"],
    ),
]
