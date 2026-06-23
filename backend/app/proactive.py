"""Proactive home intelligence scans."""
from __future__ import annotations

import json
from typing import Any

from .db.database import get_session
from .db.models import Suggestion
from .homeassistant.services import safe_get_states


def _exists(session, title: str, category: str) -> bool:
    return session.query(Suggestion).filter(
        Suggestion.title == title,
        Suggestion.category == category,
        Suggestion.status.in_(["suggested", "draft", "edited"]),
    ).first() is not None


def _add(session, *, title: str, message: str, category: str,
         priority: str = "normal", action_type: str = "",
         payload: dict[str, Any] | None = None) -> bool:
    if _exists(session, title, category):
        return False
    session.add(Suggestion(
        title=title,
        message=message,
        category=category,
        priority=priority,
        action_type=action_type,
        payload=json.dumps(payload or {}),
        status="suggested",
    ))
    return True


async def scan_proactive() -> dict[str, Any]:
    states = await safe_get_states()
    created = 0
    findings: list[dict[str, Any]] = []
    people = [e for e in states.values() if e.domain in {"person", "device_tracker"}]
    nobody_home = bool(people) and all((p.state or "").lower() not in {"home", "on"} for p in people)
    with get_session() as session:
        for entity in states.values():
            eid = entity.entity_id
            state = (entity.state or "").lower()
            name = entity.friendly_name or eid
            if entity.domain == "lock" and state == "unlocked":
                if _add(
                    session,
                    title=f"{name} is unlocked",
                    message=f"{name} is currently unlocked. Review or lock it.",
                    category="security",
                    priority="high",
                    action_type="security_check",
                    payload={"entity_id": eid, "state": state},
                ):
                    created += 1
                findings.append({"type": "unlocked", "entity_id": eid, "name": name})
            elif entity.domain in {"cover", "garage_door"} and state in {"open", "opening"}:
                if _add(
                    session,
                    title=f"{name} is open",
                    message=f"{name} is {state}. Review before leaving it open.",
                    category="security",
                    priority="high",
                    action_type="close_cover",
                    payload={"entity_id": eid, "state": state},
                ):
                    created += 1
                findings.append({"type": "open_cover", "entity_id": eid, "name": name})
            elif entity.domain == "media_player" and state in {"on", "playing", "paused"}:
                if _add(
                    session,
                    title=f"Create sleep timer for {name}",
                    message=f"{name} is {state}. Create an approval-based sleep timer routine?",
                    category="routine",
                    priority="normal",
                    action_type="automation_draft",
                    payload={"entity_id": eid, "state": state, "kind": "sleep_timer"},
                ):
                    created += 1
                findings.append({"type": "media_active", "entity_id": eid, "name": name})
            elif entity.domain == "light" and state == "on" and nobody_home:
                if _add(
                    session,
                    title=f"{name} is on while nobody is home",
                    message=f"{name} is still on and all tracked people appear away.",
                    category="energy",
                    priority="normal",
                    action_type="turn_off_light",
                    payload={"entity_id": eid, "state": state, "nobody_home": True},
                ):
                    created += 1
                findings.append({"type": "light_on_away", "entity_id": eid, "name": name})
            elif "battery" in eid.lower() and _low_battery_state(state):
                if _add(
                    session,
                    title=f"{name} battery is low",
                    message=f"{name} reports battery state {entity.state}.",
                    category="maintenance",
                    priority="normal",
                    action_type="review_battery",
                    payload={"entity_id": eid, "state": entity.state},
                ):
                    created += 1
                findings.append({"type": "low_battery", "entity_id": eid, "name": name})
            elif not entity.available:
                if _add(
                    session,
                    title=f"{name} is unavailable",
                    message=f"{name} is unavailable. Review mapping, power, or integration health.",
                    category="maintenance",
                    priority="normal",
                    action_type="review_unavailable",
                    payload={"entity_id": eid, "state": state},
                ):
                    created += 1
        session.commit()
    return {"created": created, "findings": findings}


def _low_battery_state(state: str) -> bool:
    if state in {"low", "critical"}:
        return True
    try:
        return float(state) <= 20
    except (TypeError, ValueError):
        return False
