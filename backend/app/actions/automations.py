"""Automation drafting. The MVP NEVER creates live automations. It produces a
proposed Home Assistant automation YAML for human review/approval."""
from __future__ import annotations

import re
from typing import Any, Optional

import yaml

from ..events import get_event_bus
from ..models.results import ActionResult
from . import ActionContext

_TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.I)
_AT_TIME_RE = re.compile(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.I)
_DELAY_RE = re.compile(r"\bin\s+(\d{1,3})\s*(minute|minutes|min|hour|hours|hr|hrs)\b", re.I)


def _guess_time(text: str) -> Optional[str]:
    m = _AT_TIME_RE.search(text) or _TIME_RE.search(text)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    ampm = (m.group(3) or "").lower()
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return f"{hour:02d}:{minute:02d}:00"
    return None


def _guess_delay(text: str) -> Optional[str]:
    m = _DELAY_RE.search(text)
    if not m:
        return None
    amount = int(m.group(1))
    unit = m.group(2).lower()
    minutes = amount * 60 if unit.startswith(("hour", "hr")) else amount
    hours, mins = divmod(minutes, 60)
    return f"{hours:02d}:{mins:02d}:00"


async def create_simple_automation(ctx: ActionContext, params: dict[str, Any]) -> ActionResult:
    intent = "create_simple_automation"
    trigger_desc = (params.get("trigger_description") or "").strip()
    action_desc = (params.get("action_description") or "").strip()
    original_request = (params.get("original_request") or "").strip()
    if not trigger_desc and not action_desc:
        return ActionResult.fail(intent, "Describe the trigger and the action.")
    action_source = _richer_action_text(action_desc, original_request)

    # Best-effort structured trigger.
    at_time = _guess_time(trigger_desc) or _guess_time(action_source)
    delay = _guess_delay(trigger_desc) or _guess_delay(action_source)
    trigger: dict[str, Any]
    if at_time:
        trigger = {"platform": "time", "at": at_time}
    elif delay:
        trigger = {"platform": "manual", "note": "Start this timer when approved."}
    else:
        trigger = {"platform": "template", "value_template": f"<<< {trigger_desc} >>>"}

    actions = _automation_actions(ctx, action_source)
    if not actions:
        actions = [{"service": "<<< choose service >>>", "data": {"note": action_desc}}]
    if delay:
        actions = [{"delay": delay}, *actions]

    proposed = {
        "alias": f"TPG HomeAI: {trigger_desc[:48]}",
        "description": f"Draft generated from: '{trigger_desc}' -> '{action_source}'",
        "trigger": [trigger],
        "condition": [],
        "action": actions,
        "mode": "single",
    }
    proposed_yaml = yaml.safe_dump(proposed, sort_keys=False)

    # Persist as a draft (status=draft). Never pushed to HA. Preview mode must
    # not create database rows or emit actionable notifications.
    draft_id = None
    if not ctx.dry_run:
        try:
            from ..db.database import get_session
            from ..db.models import AutomationDraft

            with get_session() as session:
                draft = AutomationDraft(
                    trigger_description=trigger_desc,
                    action_description=action_source,
                    proposed_yaml=proposed_yaml,
                    status="draft",
                )
                session.add(draft)
                session.commit()
                draft_id = draft.id
        except Exception:  # pragma: no cover - DB optional in some contexts
            pass

    if not ctx.dry_run:
        get_event_bus().emit("tpg_homeai_suggestion_created", {
            "draft_id": draft_id,
            "trigger_description": trigger_desc,
            "action_description": action_source,
            "title": "TPG HomeAI suggestion ready",
            "message": "A timer, routine, or automation draft is ready for review.",
        })

    return ActionResult(
        success=True, intent=intent, executed=False,
        message=(
            "Here is a proposed automation for your approval. It has NOT been "
            "created in Home Assistant. Review and approve to create it."
        ),
        resolved={"trigger": trigger, "draft_id": draft_id},
        data={"proposed_yaml": proposed_yaml, "draft_id": draft_id},
    )


def _automation_actions(ctx: ActionContext, action_desc: str) -> list[dict[str, Any]]:
    parts = _action_parts(action_desc)
    actions = [_action_block(ctx, part) for part in parts]
    return [action for action in actions if action]


def _richer_action_text(action_desc: str, original_request: str) -> str:
    if not original_request:
        return action_desc
    original_lower = original_request.lower()
    action_lower = action_desc.lower()
    has_action_word = any(
        word in original_lower
        for word in ("turn", "set", "dim", "lower", "play", "lock", "unlock")
    )
    if " and " in original_lower and action_lower and action_lower in original_lower:
        return original_request
    if has_action_word and len(original_request) > len(action_desc):
        return original_request
    return action_desc or original_request


def _action_parts(text: str) -> list[str]:
    cleaned = _strip_schedule_words(text)
    pieces = re.split(r"\s+(?:and then|then|and)\s+(?=turn|set|dim|lower|play|lock|unlock)", cleaned, flags=re.I)
    return [piece.strip(" .") for piece in pieces if piece.strip(" .")]


def _strip_schedule_words(text: str) -> str:
    text = re.sub(r"\b(create|make|add|build)\s+(a\s+)?(scheduled task|schedule|automation)\b[:,]?\s*", "", text, flags=re.I)
    text = _AT_TIME_RE.sub("", text)
    text = _DELAY_RE.sub("", text)
    return " ".join(text.split())


def _action_block(ctx: ActionContext, action_desc: str) -> dict[str, Any]:
    lower = action_desc.lower()
    if "light" in lower:
        return _light_action(ctx, lower, action_desc)
    if any(word in lower for word in ("tv", "display", "screen", "monitor")) and \
            any(word in lower for word in ("off", "sleep", "timer", "turn off")):
        display_word = re.sub(r".*(turn off|sleep timer on|sleep timer for|timer on|timer for)\s+(the )?", "", lower)
        display_word = _DELAY_RE.sub("", display_word).strip()
        display = ctx.resolver.resolve_display(display_word) if display_word else None
        entity_id = display.entity_id if display and display.matched else "<<< choose TV/display entity >>>"
        return {"service": "media_player.turn_off", "target": {"entity_id": entity_id}}
    if any(word in lower for word in ("brightness", "bright", "dim", "lower")):
        pct_match = re.search(r"(\d{1,3})", lower)
        pct = max(1, min(100, int(pct_match.group(1)))) if pct_match else 25
        room_word = re.sub(r".*(dim|lower|set)\s+(the )?", "", lower)
        room_word = room_word.replace("brightness", "").replace("bright", "").strip()
        room = ctx.resolver.resolve_room(room_word) if room_word else None
        if room and room.matched and room.data.get("lights"):
            return {"service": "light.turn_on", "target": {"entity_id": room.data["lights"]}, "data": {"brightness_pct": pct}}
        return {"service": "<<< display brightness service or light.turn_on >>>", "data": {"brightness_pct": pct, "note": action_desc}}
    if lower.startswith(("turn on ", "turn off ")):
        service = "turn_off" if lower.startswith("turn off ") else "turn_on"
        target = re.sub(r"^turn (on|off)\s+(the )?", "", lower).strip()
        resolved = ctx.resolver.resolve_device_alias(target)
        if resolved and resolved.matched and resolved.entity_id and "." in resolved.entity_id:
            domain = resolved.entity_id.split(".", 1)[0]
            return {"service": f"{domain}.{service}", "target": {"entity_id": resolved.entity_id}}
    return {"service": "<<< choose service >>>", "data": {"note": action_desc}}


def _light_action(ctx: ActionContext, lower: str, action_desc: str) -> dict[str, Any]:
    service = "light.turn_off" if re.search(r"\b(off|disable|shut)\b", lower) else "light.turn_on"
    if any(phrase in lower for phrase in ("all lights", "all light", "every light", "house lights")):
        lights = _all_room_lights(ctx)
        return {"service": service, "target": {"entity_id": lights or "all"}}
    room_word = re.sub(r".*turn (on|off) (the )?", "", lower)
    room_word = room_word.replace("lights", "").replace("light", "").strip()
    room = ctx.resolver.resolve_room(room_word) if room_word else None
    if room and room.matched and room.data.get("lights"):
        return {"service": service, "target": {"entity_id": room.data["lights"]}}
    resolved = ctx.resolver.resolve_device_alias(room_word or action_desc)
    if resolved and resolved.matched and (resolved.entity_id or "").startswith("light."):
        return {"service": service, "target": {"entity_id": resolved.entity_id}}
    return {"service": service, "target": {"entity_id": "<<< map room lights in devices.yaml >>>"}}


def _all_room_lights(ctx: ActionContext) -> list[str]:
    lights = [entity for room in ctx.config.devices.rooms for entity in (room.lights or [])]
    return list(dict.fromkeys(lights))


async def create_routine(ctx: ActionContext, params: dict[str, Any]) -> ActionResult:
    intent = "create_routine"
    routine = (params.get("routine") or params.get("name") or "").strip().lower()
    room_name = re.sub(r"^\s*the\s+", "", (params.get("room") or "").strip(), flags=re.I)
    if not routine:
        return ActionResult.fail(intent, "Which routine should I build?")

    actions = _routine_actions(ctx, routine, room_name)
    if not actions:
        return ActionResult.fail(
            intent,
            f"I don't have enough mapped devices to build a {routine} routine yet.",
            resolved={"routine": routine, "room": room_name},
        )

    alias = f"TPG HomeAI: {routine.title()} Routine"
    if room_name:
        alias += f" ({room_name.title()})"
    proposed = {
        "alias": alias,
        "description": f"Routine draft generated by TPG HomeAI for '{routine}'.",
        "trigger": [{"platform": "manual", "note": "Run after approval or attach a trigger."}],
        "condition": [],
        "action": actions,
        "mode": "single",
    }
    proposed_yaml = yaml.safe_dump(proposed, sort_keys=False, allow_unicode=True)
    draft_id = None if ctx.dry_run else _persist_draft(routine, f"Run {routine} routine", proposed_yaml)
    if not ctx.dry_run:
        get_event_bus().emit("tpg_homeai_suggestion_created", {
            "draft_id": draft_id,
            "title": f"{routine.title()} routine ready",
            "message": "A multi-step routine draft is ready for approval.",
        })
    return ActionResult(
        success=True,
        intent=intent,
        executed=False,
        message="Routine draft ready for review. Approve it to install in Home Assistant.",
        resolved={"routine": routine, "room": room_name, "draft_id": draft_id},
        data={"proposed_yaml": proposed_yaml, "draft_id": draft_id, "actions": actions},
    )


def _persist_draft(trigger_desc: str, action_desc: str, proposed_yaml: str) -> int | None:
    try:
        from ..db.database import get_session
        from ..db.models import AutomationDraft

        with get_session() as session:
            draft = AutomationDraft(
                trigger_description=trigger_desc,
                action_description=action_desc,
                proposed_yaml=proposed_yaml,
                status="draft",
            )
            session.add(draft)
            session.commit()
            return draft.id
    except Exception:  # pragma: no cover - DB optional in some contexts
        return None


def _routine_actions(ctx: ActionContext, routine: str, room_name: str) -> list[dict[str, Any]]:
    routine_text = routine.lower()
    target_rooms = ctx.config.devices.rooms
    if room_name:
        resolved = ctx.resolver.resolve_room(room_name)
        target_rooms = [r for r in target_rooms if resolved.matched and r.id == resolved.id]

    actions: list[dict[str, Any]] = []
    room_lights = list(dict.fromkeys(e for r in target_rooms for e in (r.lights or [])))
    room_fans = list(dict.fromkeys(e for r in target_rooms for e in (r.fans or [])))
    room_displays = list(dict.fromkeys(e for r in target_rooms for e in ([r.display] if r.display else [])))
    room_speakers = list(dict.fromkeys(e for r in target_rooms for e in ([r.speaker] if r.speaker else [])))

    if any(k in routine_text for k in ("movie", "cinema", "tv")):
        if room_lights:
            actions.append({"service": "light.turn_on", "target": {"entity_id": room_lights},
                            "data": {"brightness_pct": 25}})
        if room_displays:
            actions.append({"service": "media_player.turn_on", "target": {"entity_id": room_displays}})
        if room_speakers:
            actions.append({"service": "media_player.volume_set",
                            "target": {"entity_id": room_speakers},
                            "data": {"volume_level": 0.35}})
    elif any(k in routine_text for k in ("bed", "night", "sleep")):
        if room_lights:
            actions.append({"service": "light.turn_off", "target": {"entity_id": room_lights}})
        if room_displays:
            actions.append({"service": "media_player.turn_off", "target": {"entity_id": room_displays}})
        if room_fans:
            actions.append({"service": "fan.turn_on", "target": {"entity_id": room_fans}})
    elif any(k in routine_text for k in ("morning", "wake")):
        if room_lights:
            actions.append({"service": "light.turn_on", "target": {"entity_id": room_lights},
                            "data": {"brightness_pct": 65}})
        if room_speakers:
            actions.append({"service": "media_player.volume_set",
                            "target": {"entity_id": room_speakers},
                            "data": {"volume_level": 0.25}})
    elif any(k in routine_text for k in ("leave", "away", "leaving")):
        if room_lights:
            actions.append({"service": "light.turn_off", "target": {"entity_id": room_lights}})
        if room_displays:
            actions.append({"service": "media_player.turn_off", "target": {"entity_id": room_displays}})
        if room_fans:
            actions.append({"service": "fan.turn_off", "target": {"entity_id": room_fans}})
    elif any(k in routine_text for k in ("security", "lock")):
        for lock in ctx.config.devices.locks:
            actions.append({"service": "lock.lock", "target": {"entity_id": lock.entity_id}})

    return actions
