"""Situational house-state brain.

This layer converts Home Assistant entities and HomeAI config into human-scale
states: away/home, active media, security attention, maintenance, rooms, and
recommended next actions. It is intentionally read-only; actions still route
through the guarded command/policy path.
"""
from __future__ import annotations

from typing import Any

from .db.database import get_session
from .db.models import CommandLog, MemoryItem, Suggestion
from .homeassistant.services import safe_get_states
from .models.schemas import AppConfig


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
    recommendations = _recommendations(away, security, energy, media, maintenance)
    return {
        "status": "attention" if security else ("active" if media or energy else "calm"),
        "modes": modes,
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
