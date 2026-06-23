"""Situational house-state brain.

This layer converts Home Assistant entities and HomeAI config into human-scale
states: away/home, active media, security attention, maintenance, rooms, and
recommended next actions. It is intentionally read-only; actions still route
through the guarded command/policy path.
"""
from __future__ import annotations

import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .db.database import get_session
from .db.models import CommandLog, MemoryItem, Suggestion
from .homeassistant.services import safe_get_states
from .models.schemas import AppConfig, HouseMode


async def build_house_state(config: AppConfig, graph: dict[str, Any] | None = None) -> dict[str, Any]:
    states = await safe_get_states()
    state_list = list(states.values())
    people = [e for e in state_list if e.domain in {"person", "device_tracker"}]
    home_people = [e for e in people if (e.state or "").lower() in {"home", "on"}]
    away = bool(people) and not home_people

    security = []
    energy = []
    media = []
    maintenance = []
    rooms = []

    for entity in state_list:
        eid = entity.entity_id
        name = entity.friendly_name or eid
        state = (entity.state or "").lower()
        if entity.domain == "lock" and state == "unlocked":
            security.append(_finding("unlocked", eid, name, "high", "Lock is unlocked."))
        elif entity.domain in {"cover", "garage_door"} and state in {"open", "opening"}:
            security.append(_finding("open_cover", eid, name, "high", f"Cover is {state}."))
        elif entity.domain == "light" and state == "on":
            energy.append(_finding("light_on", eid, name, "normal", "Light is on.", {"away": away}))
        elif entity.domain == "media_player" and state in {"on", "playing", "paused"}:
            media.append(_finding("media_active", eid, name, "normal", f"Media player is {state}."))
        elif _low_battery(entity):
            maintenance.append(_finding("low_battery", eid, name, "normal", f"Battery reports {entity.state}."))
        elif not entity.available:
            maintenance.append(_finding("unavailable", eid, name, "normal", "Entity is unavailable."))

    for room in config.devices.rooms:
        entity_ids = list(dict.fromkeys([
            *(room.lights or []),
            *(room.fans or []),
            *[e for e in [room.climate, room.speaker, room.display, room.camera, room.lock] if e],
        ]))
        room_states = [states[eid] for eid in entity_ids if eid in states]
        active = [e.entity_id for e in room_states if (e.state or "").lower() in {"on", "playing", "open", "unlocked"}]
        rooms.append({
            "id": room.id,
            "name": room.name,
            "entity_count": len(entity_ids),
            "available_count": sum(1 for e in room_states if e.available),
            "active_entities": active,
            "has_voice_source": any(v.room == room.id or v.room == room.name for v in config.devices.voice_sources),
            "speaker": room.speaker,
            "display": room.display,
        })

    with get_session() as session:
        recent_commands = session.query(CommandLog).order_by(CommandLog.created_at.desc()).limit(8).all()
        approved_memories = session.query(MemoryItem).filter(MemoryItem.status == "approved").count()
        pending_suggestions = session.query(Suggestion).filter(
            Suggestion.status.in_(["suggested", "draft", "edited"])
        ).count()

    modes = _infer_modes(away, security, media, rooms)
    snapshot = {
        "away": away,
        "security": security,
        "energy": energy,
        "media": media,
        "maintenance": maintenance,
        "rooms": rooms,
    }
    mode_brain = build_mode_brain(config, snapshot)
    wake_word = build_wake_word_deployment(config)
    recommendations = _recommendations(away, security, energy, media, maintenance)
    return {
        "status": "attention" if security else ("active" if media or energy else "calm"),
        "modes": modes,
        "mode_brain": mode_brain,
        "wake_word": wake_word,
        "presence": {
            "known_people": len(people),
            "home": [p.friendly_name or p.entity_id for p in home_people],
            "away": away,
        },
        "attention": {
            "security": security,
            "energy": energy[:20],
            "media": media[:20],
            "maintenance": maintenance[:20],
        },
        "rooms": rooms,
        "recommendations": recommendations,
        "memory": {
            "approved_memories": approved_memories,
            "pending_suggestions": pending_suggestions,
            "recent_commands": [
                {
                    "message": row.message,
                    "intent": row.intent,
                    "success": row.success,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in recent_commands
            ],
        },
        "graph_summary": graph.get("counts", {}) if graph else {},
    }


def build_assistant_intelligence(config: AppConfig) -> dict[str, Any]:
    with get_session() as session:
        memories = session.query(MemoryItem).filter(MemoryItem.status == "approved").all()
    users = {user.id: user for user in config.assistants.users}
    return {
        "assistants": [
            {
                "id": assistant.id,
                "name": assistant.name,
                "owner": assistant.owner,
                "owner_name": users.get(assistant.owner).name if users.get(assistant.owner) else assistant.owner,
                "personality": assistant.personality,
                "tone": assistant.tone,
                "voice": assistant.voice.model_dump() if hasattr(assistant.voice, "model_dump") else assistant.voice,
                "approved_memories": [
                    {
                        "scope": memory.scope,
                        "subject": memory.subject,
                        "key": memory.key,
                        "value": memory.value,
                    }
                    for memory in memories
                    if memory.owner in {"", assistant.owner, assistant.id}
                ],
            }
            for assistant in config.assistants.assistants
        ],
        "users": [
            {
                "id": user.id,
                "name": user.name,
                "music_account": user.music_account,
                "permissions": user.permissions.model_dump(),
            }
            for user in config.assistants.users
        ],
    }


def build_tablet_profiles(config: AppConfig) -> dict[str, Any]:
    profiles = []
    for display in config.devices.displays:
        room = _room_for_display(config, display.entity_id or display.id)
        profiles.append({
            "id": display.id,
            "name": display.name,
            "type": display.type,
            "room": room.id if room else None,
            "browser_id": display.browser_id,
            "entity_id": display.entity_id,
            "dashboard_path": display.dashboard_path or f"/lovelace/{room.id if room else 'tpg-home'}",
            "suggested_view": f"room_{room.id}" if room else "home",
            "browser_mod": {
                "navigate": display.type == "browser_mod",
                "browser_id": display.browser_id,
                "path": display.dashboard_path or f"/lovelace/{room.id if room else 'tpg-home'}",
            },
        })
    return {
        "tablet_profiles": profiles,
        "counts": {
            "total": len(profiles),
            "browser_mod": sum(1 for p in profiles if p["type"] == "browser_mod"),
            "media_player": sum(1 for p in profiles if p["type"] == "media_player"),
        },
    }


def build_mode_brain(config: AppConfig, state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return active house modes and the policy they imply.

    This is the layer that turns "the house feels like sleep/away/movie mode"
    into concrete behavior: reply routing, confirmation gates, and whether safe
    actions can still auto-execute.
    """

    state = state or {}
    configured = [mode for mode in config.devices.modes if mode.enabled]
    configured_by_id = {mode.id: mode for mode in configured}
    active_ids: list[str] = []
    reasons: dict[str, list[str]] = {}

    def activate(mode_id: str, reason: str) -> None:
        if mode_id not in active_ids:
            active_ids.append(mode_id)
        reasons.setdefault(mode_id, []).append(reason)

    away = bool(state.get("away"))
    security = list(state.get("security") or [])
    media = list(state.get("media") or [])
    rooms = list(state.get("rooms") or [])
    quiet_hours = _is_quiet_hours(config)

    activate("away" if away else "home", "presence")
    if security:
        activate("security", "security_attention")
    if media:
        activate("movie", "media_active")
    if quiet_hours:
        activate("sleep", "quiet_hours")

    for source in config.devices.voice_sources:
        if source.trust_level == "guest":
            activate("guest", f"guest_source:{source.id}")

    active_modes = _mode_payloads(active_ids, configured_by_id, reasons)
    primary = active_modes[0] if active_modes else _mode_payload(_fallback_mode("home", "Home"), ["default"])
    confirm_actions = _policy_confirm_actions(config, active_modes)
    reply_mode = _first_non_auto_reply(active_modes) or "auto"
    allow_auto_execute = all(mode.get("allow_auto_execute", True) for mode in active_modes)
    source_policy = _source_policy(config)

    return {
        "configured_modes": [_mode_payload(mode, []) for mode in configured],
        "active_modes": active_modes,
        "primary_mode": primary,
        "quiet_hours_active": quiet_hours,
        "policy": {
            "reply_mode": reply_mode,
            "allow_auto_execute": allow_auto_execute,
            "confirmation_keywords": confirm_actions,
            "security_actions_always_confirm": sorted(set(config.permissions.sensitive_actions or [])),
            "safe_actions_auto_execute": allow_auto_execute,
        },
        "source_policy": source_policy,
        "recommendations": _mode_recommendations(away, security, media, rooms, quiet_hours, active_modes),
    }


def build_wake_word_deployment(config: AppConfig) -> dict[str, Any]:
    """Explain microphone/satellite readiness room by room."""

    from .voice import list_voice_source_readiness

    readiness = list_voice_source_readiness(config)
    sources = []
    for source in readiness.get("voice_sources", []):
        route = source.get("resolved_reply_route") or {}
        missing = []
        if not source.get("has_room"):
            missing.append("room")
        if not source.get("has_source_identity"):
            missing.append("source_device_id_or_source_entity_id")
        if source.get("default_reply") == "room_speaker" and not route.get("target_entity_id"):
            missing.append("speaker_route")
        setup_status = "ready" if not missing else ("partial" if source.get("has_room") else "needs_mapping")
        sources.append({
            **source,
            "setup_status": setup_status,
            "missing": missing,
            "next_step": _voice_source_next_step(missing),
        })

    rooms_with_source = {str(s.get("room")) for s in sources if s.get("room")}
    recommended = []
    for room in config.devices.rooms:
        if room.id in rooms_with_source or room.name in rooms_with_source:
            continue
        recommended.append({
            "room": room.id,
            "name": room.name,
            "speaker": room.speaker,
            "recommended_default_reply": "room_speaker" if room.speaker else "browser",
            "next_step": "Add a voice_sources entry with source_device_id/source_entity_id for this room.",
        })

    missing_identity = sum(1 for s in sources if "source_device_id_or_source_entity_id" in s["missing"])
    missing_room = sum(1 for s in sources if "room" in s["missing"])
    missing_speaker = sum(1 for s in sources if "speaker_route" in s["missing"])
    return {
        "counts": {
            **readiness.get("counts", {}),
            "ready": sum(1 for s in sources if s["setup_status"] == "ready"),
            "partial": sum(1 for s in sources if s["setup_status"] == "partial"),
            "missing_source_identity": missing_identity,
            "missing_room": missing_room,
            "missing_speaker_route": missing_speaker,
            "rooms_without_voice_source": len(recommended),
        },
        "sources": sources,
        "recommended_satellites": recommended,
        "policies": [
            "Trusted sources may request sensitive actions, but unlock/open/disarm still require backend confirmation.",
            "Household sources can run normal lights, fans, media, and climate commands when target confidence is high.",
            "Guest/outside sources should never auto-run unlock, open, disarm, garage, or private information requests.",
        ],
    }


def _room_for_display(config: AppConfig, display_ref: str):
    for room in config.devices.rooms:
        if display_ref in {room.display or "", room.id, room.name}:
            return room
    return None


def _finding(kind: str, entity_id: str, name: str, priority: str, message: str,
             extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "type": kind,
        "entity_id": entity_id,
        "name": name,
        "priority": priority,
        "message": message,
        **(extra or {}),
    }


def _low_battery(entity) -> bool:
    if "battery" not in entity.entity_id.lower() and "battery" not in (entity.friendly_name or "").lower():
        return False
    try:
        return float(entity.state) <= 20
    except (TypeError, ValueError):
        return str(entity.state).lower() in {"low", "critical"}


def _infer_modes(away: bool, security: list[dict[str, Any]], media: list[dict[str, Any]],
                 rooms: list[dict[str, Any]]) -> list[str]:
    modes = ["away"] if away else ["home"]
    if security:
        modes.append("security_attention")
    if media:
        modes.append("media_active")
    if any(room["active_entities"] for room in rooms):
        modes.append("rooms_active")
    return modes


def _fallback_mode(mode_id: str, name: str) -> HouseMode:
    return HouseMode(id=mode_id, name=name, priority=0)


def _mode_payloads(active_ids: list[str], configured_by_id: dict[str, HouseMode],
                   reasons: dict[str, list[str]]) -> list[dict[str, Any]]:
    modes = []
    for mode_id in active_ids:
        mode = configured_by_id.get(mode_id) or _fallback_mode(mode_id, mode_id.replace("_", " ").title())
        modes.append(_mode_payload(mode, reasons.get(mode_id, [])))
    return sorted(modes, key=lambda item: item["priority"], reverse=True)


def _mode_payload(mode: HouseMode, reasons: list[str]) -> dict[str, Any]:
    return {
        "id": mode.id,
        "name": mode.name,
        "priority": mode.priority,
        "aliases": mode.aliases,
        "triggers": mode.triggers,
        "quiet_hours": mode.quiet_hours,
        "reply_mode": mode.reply_mode,
        "requires_confirmation_for": mode.requires_confirmation_for,
        "allow_auto_execute": mode.allow_auto_execute,
        "description": mode.description,
        "reasons": reasons,
    }


def _policy_confirm_actions(config: AppConfig, active_modes: list[dict[str, Any]]) -> list[str]:
    actions = set(config.permissions.sensitive_actions or [])
    for mode in active_modes:
        actions.update(mode.get("requires_confirmation_for") or [])
    return sorted(actions)


def _first_non_auto_reply(active_modes: list[dict[str, Any]]) -> str | None:
    for mode in active_modes:
        reply_mode = str(mode.get("reply_mode") or "auto")
        if reply_mode != "auto":
            return reply_mode
    return None


def _source_policy(config: AppConfig) -> list[dict[str, Any]]:
    policies = []
    for source in config.devices.voice_sources:
        blocked = []
        if source.trust_level in {"guest", "outside"}:
            blocked = ["unlock", "open", "disarm", "garage", "private"]
        elif source.trust_level == "household":
            blocked = ["unlock", "disarm"]
        policies.append({
            "source_id": source.id,
            "name": source.name,
            "room": source.room,
            "user": source.user,
            "trust_level": source.trust_level,
            "default_reply": source.default_reply,
            "blocked_without_confirmation": blocked,
            "can_auto_execute_safe_actions": source.trust_level in {"trusted", "household"},
        })
    return policies


def _mode_recommendations(away: bool, security: list[dict[str, Any]], media: list[dict[str, Any]],
                          rooms: list[dict[str, Any]], quiet_hours: bool,
                          active_modes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    recs = []
    if quiet_hours and (media or any(room.get("active_entities") for room in rooms)):
        recs.append({
            "title": "Offer sleep mode cleanup",
            "priority": "normal",
            "approval_required": True,
            "reason": "Quiet hours are active and devices are still active.",
        })
    if away:
        recs.append({
            "title": "Use away-mode safety sweep",
            "priority": "normal",
            "approval_required": False,
            "reason": "Tracked people appear away.",
        })
    if security:
        recs.append({
            "title": "Keep security mode active until attention is clear",
            "priority": "high",
            "approval_required": True,
            "reason": "Security attention exists.",
        })
    if not active_modes:
        recs.append({
            "title": "Configure house modes",
            "priority": "normal",
            "approval_required": False,
            "reason": "No active modes were inferred.",
        })
    return recs


def _is_quiet_hours(config: AppConfig) -> bool:
    household = config.household.default_household()
    tz_name = household.timezone if household else "UTC"
    try:
        now = dt.datetime.now(ZoneInfo(tz_name))
    except ZoneInfoNotFoundError:
        now = dt.datetime.now(dt.timezone.utc)
    return now.hour >= 22 or now.hour < 6


def _voice_source_next_step(missing: list[str]) -> str:
    if not missing:
        return "Ready for room-aware wake-word routing."
    if "room" in missing:
        return "Assign this source to a room."
    if "source_device_id_or_source_entity_id" in missing:
        return "Add the HA Assist satellite, Browser Mod device, or media_player entity id so commands can identify the source."
    if "speaker_route" in missing:
        return "Map a room speaker or set default_reply to browser/quiet."
    return "Review this voice source mapping."


def _recommendations(away: bool, security: list[dict[str, Any]], energy: list[dict[str, Any]],
                     media: list[dict[str, Any]], maintenance: list[dict[str, Any]]) -> list[dict[str, Any]]:
    recs = []
    if security:
        recs.append({"title": "Review security attention", "priority": "high", "approval_required": True})
    if away and energy:
        recs.append({"title": "Offer to turn off away lights", "priority": "normal", "approval_required": False})
    if media:
        recs.append({"title": "Suggest sleep timers for active TVs/speakers", "priority": "normal", "approval_required": True})
    if maintenance:
        recs.append({"title": "Create maintenance review list", "priority": "normal", "approval_required": False})
    return recs
