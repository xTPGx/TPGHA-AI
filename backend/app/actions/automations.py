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
_PERCENT_RE = re.compile(r"\b(\d{1,3})\s*(?:%|percent|pct|level)?\b", re.I)
_TEMP_RE = re.compile(r"\b(\d{2,3})\s*(?:degrees?|deg|f)?\b", re.I)
_DAY_MAP = {
    "monday": "mon",
    "mon": "mon",
    "tuesday": "tue",
    "tue": "tue",
    "wednesday": "wed",
    "wed": "wed",
    "thursday": "thu",
    "thu": "thu",
    "friday": "fri",
    "fri": "fri",
    "saturday": "sat",
    "sat": "sat",
    "sunday": "sun",
    "sun": "sun",
}


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


def _guess_sun_trigger(text: str) -> dict[str, Any] | None:
    lower = text.lower()
    if "sunset" in lower or "sundown" in lower:
        return {"platform": "sun", "event": "sunset"}
    if "sunrise" in lower or "sun up" in lower or "sunup" in lower:
        return {"platform": "sun", "event": "sunrise"}
    return None


def _presence_conditions(text: str) -> list[dict[str, Any]]:
    lower = text.lower()
    if any(phrase in lower for phrase in (
        "when nobody is home",
        "if nobody is home",
        "when no one is home",
        "if no one is home",
        "when everyone is away",
        "if everyone is away",
    )):
        return [{
            "condition": "template",
            "value_template": "{{ states.person | selectattr('state', 'eq', 'home') | list | count == 0 }}",
            "alias": "Nobody is home",
        }]
    if any(phrase in lower for phrase in (
        "when someone is home",
        "if someone is home",
        "when anybody is home",
        "if anybody is home",
        "when people are home",
        "if people are home",
    )):
        return [{
            "condition": "template",
            "value_template": "{{ states.person | selectattr('state', 'eq', 'home') | list | count > 0 }}",
            "alias": "Someone is home",
        }]
    return []


def _recurrence_conditions(text: str) -> list[dict[str, Any]]:
    lower = text.lower()
    if any(word in lower for word in ("weekday", "weekdays", "school night", "school nights", "workday", "workdays")):
        return [{
            "condition": "time",
            "weekday": ["mon", "tue", "wed", "thu", "fri"],
            "alias": "Weekdays only",
        }]
    if any(word in lower for word in ("weekend", "weekends")):
        return [{
            "condition": "time",
            "weekday": ["sat", "sun"],
            "alias": "Weekends only",
        }]
    days = []
    for word, value in _DAY_MAP.items():
        if re.search(rf"\b{re.escape(word)}s?\b", lower):
            days.append(value)
    unique_days = list(dict.fromkeys(days))
    if unique_days and len(unique_days) < 7:
        return [{
            "condition": "time",
            "weekday": unique_days,
            "alias": "Requested days only",
        }]
    return []


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
    sun_trigger = _guess_sun_trigger(trigger_desc) or _guess_sun_trigger(action_source)
    if sun_trigger:
        trigger = sun_trigger
    elif at_time:
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

    condition_source = " ".join([trigger_desc, action_source, original_request])
    conditions = [
        *_presence_conditions(condition_source),
        *_recurrence_conditions(condition_source),
    ]
    warnings = _automation_warnings(actions, trigger, conditions)
    summary = _automation_summary(trigger, conditions, actions, warnings)

    proposed = {
        "alias": _automation_alias(trigger_desc, action_source, original_request),
        "description": f"Draft generated from: '{trigger_desc}' -> '{action_source}'",
        "trigger": [trigger],
        "condition": conditions,
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
        data={
            "proposed_yaml": proposed_yaml,
            "draft_id": draft_id,
            "trigger": trigger,
            "conditions": conditions,
            "actions": actions,
            "summary": summary,
            "warnings": warnings,
        },
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
        for word in (
            "turn", "set", "dim", "lower", "raise", "play", "lock", "unlock",
            "open", "close", "stop", "start",
        )
    )
    if " and " in original_lower and action_lower and action_lower in original_lower:
        return original_request
    if has_action_word and len(original_request) > len(action_desc):
        return original_request
    return action_desc or original_request


def _action_parts(text: str) -> list[str]:
    cleaned = _strip_schedule_words(text)
    pieces = re.split(
        r"\s+(?:and then|then|and)\s+"
        r"(?=turn|set|dim|lower|raise|play|lock|unlock|open|close|stop|start)",
        cleaned,
        flags=re.I,
    )
    return [piece.strip(" .") for piece in pieces if piece.strip(" .")]


def _strip_schedule_words(text: str) -> str:
    text = re.sub(r"\b(create|make|add|build)\s+(a\s+)?(scheduled task|schedule|automation)\b[:,]?\s*", "", text, flags=re.I)
    text = _AT_TIME_RE.sub("", text)
    text = _DELAY_RE.sub("", text)
    text = re.sub(r"\b(at|around)\s+(sunset|sundown|sunrise|sun up|sunup)\b", "", text, flags=re.I)
    text = re.sub(
        r"\b(if|when)\s+(nobody|no one|everyone|someone|anybody|people)\s+"
        r"(is|are)\s+(home|away)\b",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"\b(every|each)\s+(day|weekday|weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?\b", "", text, flags=re.I)
    return " ".join(text.split())


def _action_block(ctx: ActionContext, action_desc: str) -> dict[str, Any]:
    lower = action_desc.lower()
    if "light" in lower:
        return _light_action(ctx, lower, action_desc)
    if "fan" in lower:
        return _fan_action(ctx, lower, action_desc)
    if any(word in lower for word in ("thermostat", "climate", "heat", "cool", "ac", "a/c")):
        return _climate_action(ctx, lower, action_desc)
    if any(word in lower for word in ("garage", "blind", "shade", "cover", "curtain")):
        return _cover_action(ctx, lower, action_desc)
    if "lock" in lower or "door" in lower:
        lock_action = _lock_action(ctx, lower, action_desc)
        if lock_action:
            return lock_action
    if any(word in lower for word in ("switch", "plug", "outlet")):
        return _generic_domain_action(ctx, lower, action_desc, "switch")
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


def _fan_action(ctx: ActionContext, lower: str, action_desc: str) -> dict[str, Any]:
    service = "fan.turn_off" if re.search(r"\b(off|stop|disable|shut)\b", lower) else "fan.turn_on"
    pct = _percent_value(lower)
    target_text = _clean_target_text(lower, ("fan", "speed", "level", "percentage", "percent"))
    resolved = ctx.resolver.resolve_device_alias(target_text or action_desc)
    entity_id = ""
    if resolved and resolved.matched and (resolved.entity_id or "").startswith("fan."):
        entity_id = resolved.entity_id
    else:
        room = ctx.resolver.resolve_room(target_text) if target_text else None
        if room and room.matched:
            room_obj = next((r for r in ctx.config.devices.rooms if r.id == room.id), None)
            if room_obj and room_obj.fans:
                entity_id = room_obj.fans[0]
    if pct is not None and service != "fan.turn_off":
        return {"service": "fan.set_percentage", "target": {"entity_id": entity_id or "<<< choose fan entity >>>"}, "data": {"percentage": pct}}
    return {"service": service, "target": {"entity_id": entity_id or "<<< choose fan entity >>>"}}


def _climate_action(ctx: ActionContext, lower: str, action_desc: str) -> dict[str, Any]:
    target_text = _clean_target_text(lower, ("thermostat", "climate", "temperature", "temp", "degrees", "degree", "heat", "cool", "ac", "a/c"))
    entity_id = ""
    room = ctx.resolver.resolve_room(target_text) if target_text else None
    if room and room.matched:
        room_obj = next((r for r in ctx.config.devices.rooms if r.id == room.id), None)
        entity_id = getattr(room_obj, "climate", "") if room_obj else ""
    if not entity_id:
        resolved = ctx.resolver.resolve_device_alias(target_text or action_desc)
        if resolved and resolved.matched and (resolved.entity_id or "").startswith("climate."):
            entity_id = resolved.entity_id
    temp = _temperature_value(lower)
    if temp is not None:
        data: dict[str, Any] = {"temperature": temp}
        if "cool" in lower or "ac" in lower or "a/c" in lower:
            data["hvac_mode"] = "cool"
        elif "heat" in lower:
            data["hvac_mode"] = "heat"
        return {"service": "climate.set_temperature", "target": {"entity_id": entity_id or "<<< choose climate entity >>>"}, "data": data}
    if any(word in lower for word in ("off", "stop")):
        return {"service": "climate.turn_off", "target": {"entity_id": entity_id or "<<< choose climate entity >>>"}}
    return {"service": "climate.turn_on", "target": {"entity_id": entity_id or "<<< choose climate entity >>>"}}


def _cover_action(ctx: ActionContext, lower: str, action_desc: str) -> dict[str, Any]:
    service = "cover.close_cover" if re.search(r"\b(close|shut|down)\b", lower) else "cover.open_cover"
    target_text = _clean_target_text(lower, ("garage", "door", "blind", "shade", "cover", "curtain"))
    resolved = ctx.resolver.resolve_device_alias(target_text or action_desc)
    entity_id = resolved.entity_id if resolved and resolved.matched and (resolved.entity_id or "").startswith("cover.") else ""
    return {"service": service, "target": {"entity_id": entity_id or "<<< choose cover entity >>>"}}


def _lock_action(ctx: ActionContext, lower: str, action_desc: str) -> dict[str, Any] | None:
    if not re.search(r"\b(lock|unlock)\b", lower):
        return None
    service = "lock.unlock" if "unlock" in lower else "lock.lock"
    target_text = _clean_target_text(lower, ("lock", "door"))
    lock = ctx.resolver.resolve_lock(target_text or action_desc)
    entity_id = lock.entity_id if lock and lock.matched else ""
    return {"service": service, "target": {"entity_id": entity_id or "<<< choose lock entity >>>"}}


def _generic_domain_action(ctx: ActionContext, lower: str, action_desc: str, domain: str) -> dict[str, Any]:
    service = "turn_off" if re.search(r"\b(off|stop|disable|shut)\b", lower) else "turn_on"
    target_text = _clean_target_text(lower, (domain, "switch", "plug", "outlet"))
    resolved = ctx.resolver.resolve_device_alias(target_text or action_desc)
    entity_id = resolved.entity_id if resolved and resolved.matched and (resolved.entity_id or "").startswith(f"{domain}.") else ""
    return {"service": f"{domain}.{service}", "target": {"entity_id": entity_id or f"<<< choose {domain} entity >>>"}}


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


def _percent_value(text: str) -> int | None:
    match = _PERCENT_RE.search(text)
    if not match:
        return None
    value = int(match.group(1))
    if value <= 10 and re.search(r"\blevel\b", text, re.I):
        value *= 10
    return max(1, min(100, value))


def _temperature_value(text: str) -> int | None:
    values = [int(m.group(1)) for m in _TEMP_RE.finditer(text)]
    plausible = [v for v in values if 45 <= v <= 95]
    return plausible[-1] if plausible else None


def _clean_target_text(text: str, noise_words: tuple[str, ...]) -> str:
    cleaned = re.sub(r"\b(turn|set|make|put|open|close|shut|lock|unlock|start|stop|enable|disable|raise|lower|dim|to|on|off|the|a|an|all|every)\b", " ", text, flags=re.I)
    cleaned = _PERCENT_RE.sub(" ", cleaned)
    for word in noise_words:
        cleaned = re.sub(rf"\b{re.escape(word)}s?\b", " ", cleaned, flags=re.I)
    return " ".join(cleaned.split()).strip()


def _automation_alias(trigger_desc: str, action_source: str, original_request: str) -> str:
    seed = original_request or action_source or trigger_desc or "Automation"
    seed = re.sub(r"\b(create|make|add|build)\s+(a\s+)?(scheduled task|schedule|automation)\b[:,]?\s*", "", seed, flags=re.I)
    seed = " ".join(seed.split())[:60] or "Automation"
    return f"TPG HomeAI: {seed}"


def _automation_warnings(actions: list[dict[str, Any]], trigger: dict[str, Any], conditions: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    blob = yaml.safe_dump({"trigger": trigger, "condition": conditions, "action": actions}, sort_keys=False)
    if "<<<" in blob:
        warnings.append("Some targets or services still need mapping before this automation is production-ready.")
    if trigger.get("platform") == "template" and "<<<" in str(trigger.get("value_template", "")):
        warnings.append("The trigger was too vague for a native HA trigger and needs review.")
    if any(str(a.get("service", "")).startswith("lock.unlock") for a in actions):
        warnings.append("Unlock actions are sensitive and should keep PIN/approval protection.")
    return warnings


def _automation_summary(trigger: dict[str, Any], conditions: list[dict[str, Any]], actions: list[dict[str, Any]], warnings: list[str]) -> dict[str, Any]:
    return {
        "trigger": _describe_trigger(trigger),
        "conditions": [_describe_condition(c) for c in conditions],
        "actions": [_describe_action(a) for a in actions],
        "action_count": len(actions),
        "condition_count": len(conditions),
        "warnings": warnings,
        "ready_to_install": not warnings,
    }


def _describe_trigger(trigger: dict[str, Any]) -> str:
    platform = trigger.get("platform")
    if platform == "time":
        return f"At {trigger.get('at')}"
    if platform == "sun":
        return f"At {trigger.get('event')}"
    if platform == "manual":
        return trigger.get("note") or "Manual start"
    return platform or "Custom trigger"


def _describe_condition(condition: dict[str, Any]) -> str:
    if condition.get("alias"):
        return str(condition["alias"])
    if condition.get("weekday"):
        return f"Only on {', '.join(condition['weekday'])}"
    return str(condition.get("condition") or "condition")


def _describe_action(action: dict[str, Any]) -> str:
    if "delay" in action:
        return f"Wait {action['delay']}"
    service = action.get("service", "unknown service")
    target = (action.get("target") or {}).get("entity_id")
    if isinstance(target, list):
        target = f"{len(target)} entities"
    data = action.get("data") or {}
    extra = ""
    if "percentage" in data:
        extra = f" to {data['percentage']}%"
    elif "brightness_pct" in data:
        extra = f" to {data['brightness_pct']}%"
    elif "temperature" in data:
        extra = f" to {data['temperature']}"
    return f"{service}{extra} -> {target or 'target'}"


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
