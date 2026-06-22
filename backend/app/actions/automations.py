"""Automation drafting. The MVP NEVER creates live automations. It produces a
proposed Home Assistant automation YAML for human review/approval."""
from __future__ import annotations

import re
from typing import Any, Optional

import yaml

from ..models.results import ActionResult
from . import ActionContext

_TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.I)


def _guess_time(text: str) -> Optional[str]:
    m = _TIME_RE.search(text)
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


async def create_simple_automation(ctx: ActionContext, params: dict[str, Any]) -> ActionResult:
    intent = "create_simple_automation"
    trigger_desc = (params.get("trigger_description") or "").strip()
    action_desc = (params.get("action_description") or "").strip()
    if not trigger_desc and not action_desc:
        return ActionResult.fail(intent, "Describe the trigger and the action.")

    # Best-effort structured trigger.
    at_time = _guess_time(trigger_desc) or _guess_time(action_desc)
    trigger: dict[str, Any]
    if at_time:
        trigger = {"platform": "time", "at": at_time}
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

    return ActionResult(
        success=True, intent=intent, executed=False,
        message=(
            "Here is a proposed automation for your approval. It has NOT been "
            "created in Home Assistant. Review and approve to create it."
        ),
        resolved={"trigger": trigger, "draft_id": draft_id},
        data={"proposed_yaml": proposed_yaml, "draft_id": draft_id},
    )
