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
    if not trigger_desc and not action_desc:
        return ActionResult.fail(intent, "Describe the trigger and the action.")

    # Best-effort structured trigger.
    at_time = _guess_time(trigger_desc) or _guess_time(action_desc)
    delay = _guess_delay(trigger_desc) or _guess_delay(action_desc)
    trigger: dict[str, Any]
    if at_time:
        trigger = {"platform": "time", "at": at_time}
    elif delay:
        trigger = {"platform": "manual", "note": "Start this timer when approved."}
    else:
        trigger = {"platform": "template", "value_template": f"<<< {trigger_desc} >>>"}

    # Best-effort action: try to resolve a room's lights for "turn on ... lights".
    action_block: dict[str, Any] = {"service": "<<< choose service >>>",
                                     "data": {"note": action_desc}}
    lower = action_desc.lower()
    if "light" in lower:
        room_word = re.sub(r".*turn (on|off) (the )?", "", lower)
        room_word = room_word.replace("lights", "").replace("light", "").strip()
        room = ctx.resolver.resolve_room(room_word) if room_word else None
        service = "light.turn_off" if "off" in lower else "light.turn_on"
        if room and room.matched and room.data.get("lights"):
            action_block = {"service": service,
                            "target": {"entity_id": room.data["lights"]}}
        else:
            action_block = {"service": service,
                            "target": {"entity_id": "<<< map room lights in devices.yaml >>>"}}
    elif any(word in lower for word in ("tv", "display", "screen", "monitor")) and \
            any(word in lower for word in ("off", "sleep", "timer", "turn off")):
        display_word = re.sub(r".*(turn off|sleep timer on|sleep timer for|timer on|timer for)\s+(the )?", "", lower)
        display_word = _DELAY_RE.sub("", display_word).strip()
        display = ctx.resolver.resolve_display(display_word) if display_word else None
        entity_id = display.entity_id if display and display.matched else "<<< choose TV/display entity >>>"
        action_block = {"service": "media_player.turn_off",
                        "target": {"entity_id": entity_id}}
    elif any(word in lower for word in ("brightness", "bright", "dim", "lower")):
        pct_match = re.search(r"(\d{1,3})", lower)
        pct = max(1, min(100, int(pct_match.group(1)))) if pct_match else 25
        room_word = re.sub(r".*(dim|lower|set)\s+(the )?", "", lower)
        room_word = room_word.replace("brightness", "").replace("bright", "").strip()
        room = ctx.resolver.resolve_room(room_word) if room_word else None
        if room and room.matched and room.data.get("lights"):
            action_block = {"service": "light.turn_on",
                            "target": {"entity_id": room.data["lights"]},
                            "data": {"brightness_pct": pct}}
        else:
            action_block = {"service": "<<< display brightness service or light.turn_on >>>",
                            "data": {"brightness_pct": pct, "note": action_desc}}

    if delay:
        action_block = {"delay": delay, "then": action_block}

    proposed = {
        "alias": f"TPG HomeAI: {trigger_desc[:48]}",
        "description": f"Draft generated from: '{trigger_desc}' -> '{action_desc}'",
        "trigger": [trigger],
        "condition": [],
        "action": [action_block],
        "mode": "single",
    }
    proposed_yaml = yaml.safe_dump(proposed, sort_keys=False)

    # Persist as a draft (status=draft). Never pushed to HA.
    draft_id = None
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
            draft_id = draft.id
    except Exception:  # pragma: no cover - DB optional in some contexts
        pass

    get_event_bus().emit("tpg_homeai_suggestion_created", {
        "draft_id": draft_id,
        "trigger_description": trigger_desc,
        "action_description": action_desc,
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
