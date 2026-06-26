"""Proactive home intelligence scans."""
from __future__ import annotations

import json
from typing import Any

from .db.database import get_session
from .db.models import AcceptanceRun, CommandLog, Suggestion
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
            elif entity.domain == "climate" and nobody_home and state not in {"off", "unavailable", "unknown"}:
                if _add(
                    session,
                    title=f"Review away-mode climate for {name}",
                    message=f"{name} is {state} while tracked people appear away. Suggest an away-mode temperature rule?",
                    category="energy",
                    priority="normal",
                    action_type="automation_draft",
                    payload={"entity_id": eid, "state": state, "kind": "away_climate"},
                ):
                    created += 1
                findings.append({"type": "climate_away", "entity_id": eid, "name": name})
        mined = _mine_command_patterns(session)
        created += mined["created"]
        findings.extend(mined["findings"])
        acceptance_repairs = _mine_acceptance_repairs(session)
        created += acceptance_repairs["created"]
        findings.extend(acceptance_repairs["findings"])
        session.commit()
    return {"created": created, "findings": findings}


def _low_battery_state(state: str) -> bool:
    if state in {"low", "critical"}:
        return True
    try:
        return float(state) <= 20
    except (TypeError, ValueError):
        return False


def _mine_command_patterns(session) -> dict[str, Any]:
    rows = session.query(CommandLog).order_by(CommandLog.created_at.desc()).limit(80).all()
    buckets: dict[tuple[str, str], list[CommandLog]] = {}
    for row in rows:
        if not row.success or not row.intent:
            continue
        target = ""
        try:
            resolved = json.loads(row.resolved or "{}")
            target = resolved.get("label") or resolved.get("entity_id") or resolved.get("target") or ""
        except (TypeError, ValueError):
            target = ""
        key = (row.intent, str(target))
        buckets.setdefault(key, []).append(row)

    created = 0
    findings: list[dict[str, Any]] = []
    for (intent, target), matches in buckets.items():
        if len(matches) < 3 or not target:
            continue
        title = f"Learn routine for {target}"
        if _add(
            session,
            title=title,
            message=(
                f"You have asked for '{intent}' on {target} {len(matches)} times recently. "
                "Draft a suggested routine or preference?"
            ),
            category="learning",
            priority="normal",
            action_type="memory_or_automation_draft",
            payload={
                "intent": intent,
                "target": target,
                "recent_count": len(matches),
                "examples": [row.message for row in matches[:3]],
            },
        ):
            created += 1
        findings.append({"type": "repeated_command", "intent": intent, "target": target, "count": len(matches)})
    return {"created": created, "findings": findings}


def _mine_acceptance_repairs(session) -> dict[str, Any]:
    rows = session.query(AcceptanceRun).order_by(
        AcceptanceRun.created_at.desc()
    ).limit(100).all()
    latest_by_test: dict[str, AcceptanceRun] = {}
    for row in rows:
        if row.test_id and row.test_id not in latest_by_test:
            latest_by_test[row.test_id] = row

    created = 0
    findings: list[dict[str, Any]] = []
    for row in latest_by_test.values():
        if row.status not in {"failed", "blocked"}:
            continue
        test_id = row.test_id or "unknown_acceptance_test"
        title = f"Resolve acceptance {row.status}: {test_id}"
        try:
            evidence = json.loads(row.evidence or "{}")
        except (TypeError, ValueError):
            evidence = {}
        payload = {
            "test_id": test_id,
            "status": row.status,
            "assistant": row.assistant,
            "user": row.user,
            "notes": row.notes,
            "evidence": evidence,
            "version": row.version,
            "recorded_at": row.created_at.isoformat() if row.created_at else None,
            "repair_steps": _acceptance_repair_steps(test_id, row.status, row.notes),
        }
        if _add(
            session,
            title=title,
            message=(
                f"Live acceptance check {test_id} is marked {row.status}. "
                "Review the evidence, fix the blocker, rerun the check, and record a passed result."
            ),
            category="acceptance",
            priority="high",
            action_type="acceptance_repair",
            payload=payload,
        ):
            created += 1
        findings.append({
            "type": "acceptance_failure",
            "test_id": test_id,
            "status": row.status,
            "suggestion_title": title,
        })
    return {"created": created, "findings": findings}


def _acceptance_repair_steps(test_id: str, status: str, notes: str) -> list[str]:
    lowered = f"{test_id} {notes}".lower()
    steps = [
        "Open the live acceptance report and read the latest evidence for this test.",
        "Fix the device mapping, role policy, voice source, or integration issue that caused the failure.",
        "Rerun the same acceptance check from the real Home Assistant login/device.",
        "Record a passed acceptance result once the behavior is confirmed.",
    ]
    if "voice" in lowered or "mic" in lowered or "wake" in lowered:
        steps.insert(1, "Verify HTTPS/Tailscale/Nabu Casa access, browser mic permission, and voice source room mapping.")
    elif "role" in lowered or "resident" in lowered or "kiosk" in lowered:
        steps.insert(1, "Verify the HA user is synced and mapped to the expected TPG role/profile.")
    elif "media" in lowered or "music" in lowered:
        steps.insert(1, "Verify speaker routing, Music Assistant player mapping, and the user's music account.")
    elif "security" in lowered or "lock" in lowered:
        steps.insert(1, "Verify confirmation/PIN policy before testing any security-disabling action.")
    return steps
