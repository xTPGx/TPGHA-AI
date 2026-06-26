"""Media, camera, security, and occupancy intelligence for Jarvis phases 66-71."""
from __future__ import annotations

from typing import Any

from .homeassistant.services import HAEntity, safe_get_states
from .models.schemas import AppConfig


async def build_music_assistant_brain(config: AppConfig) -> dict[str, Any]:
    states = await safe_get_states()
    speakers = []
    ma_ready = 0
    for speaker in config.devices.speakers:
        entity_id = speaker.music_assistant_entity_id or speaker.entity_id
        ent = states.get(entity_id) or states.get(speaker.entity_id)
        ready = bool(speaker.music_assistant_entity_id)
        if ready:
            ma_ready += 1
        speakers.append({
            "id": speaker.id,
            "name": speaker.name,
            "room": speaker.room,
            "entity_id": speaker.entity_id,
            "music_assistant_entity_id": speaker.music_assistant_entity_id,
            "state": ent.state if ent else "unknown",
            "available": ent.available if ent else None,
            "music_assistant_ready": ready,
            "recommended_backend": "music_assistant" if ready else "media_player_fallback",
            "aliases": speaker.aliases,
        })

    accounts = []
    users_by_id = {user.id: user for user in config.assistants.users}
    for account_id, account in config.devices.music_accounts.items():
        owner = users_by_id.get(account.owner)
        default_media = account.default_media.model_dump() if account.default_media else None
        accounts.append({
            "id": account_id,
            "name": account.name,
            "provider": account.provider,
            "account": account.account,
            "owner": account.owner,
            "owner_name": owner.name if owner else account.owner,
            "default_media": default_media,
            "ready": bool(account.provider and account.account),
            "search_service": "music_assistant.search",
            "play_service": "music_assistant.play_media",
        })

    return {
        "status": "ready" if accounts and ma_ready else "partial",
        "accounts": accounts,
        "speakers": speakers,
        "counts": {
            "accounts": len(accounts),
            "speakers": len(speakers),
            "music_assistant_speakers": ma_ready,
            "fallback_speakers": len(speakers) - ma_ready,
        },
        "capabilities": [
            "Search Music Assistant by playlist, track, album, artist, or radio.",
            "Route playback through the assistant owner's configured music account.",
            "Prefer Music Assistant players and fall back to media_player.play_media when unavailable.",
            "Keep per-user music account privacy boundaries.",
        ],
        "next_steps": _music_next_steps(accounts, speakers),
    }


async def build_media_control_brain(config: AppConfig) -> dict[str, Any]:
    states = await safe_get_states()
    media_entities = [entity for entity in states.values() if entity.domain == "media_player"]
    displays_by_entity = {
        display.entity_id: display
        for display in config.devices.displays
        if display.entity_id
    }
    speakers_by_entity = {speaker.entity_id: speaker for speaker in config.devices.speakers}
    cards = []
    for entity in media_entities:
        attrs = entity.attributes or {}
        display = displays_by_entity.get(entity.entity_id)
        speaker = speakers_by_entity.get(entity.entity_id)
        cards.append({
            "entity_id": entity.entity_id,
            "name": entity.friendly_name or entity.entity_id,
            "state": entity.state,
            "available": entity.available,
            "role": "display" if display else ("speaker" if speaker else "media_player"),
            "room": (display.id if display else None) or (speaker.room if speaker else None),
            "volume_level": attrs.get("volume_level"),
            "source": attrs.get("source"),
            "source_list": attrs.get("source_list") or [],
            "media_title": attrs.get("media_title"),
            "app_name": attrs.get("app_name"),
            "supported_features": attrs.get("supported_features"),
            "sleep_timer_candidate": entity.state in {"on", "playing", "paused", "idle"},
            "controls": _media_controls(attrs),
        })
    active = [card for card in cards if card["state"] in {"on", "playing", "paused", "idle"}]
    return {
        "status": "active" if active else "calm",
        "media_players": cards,
        "active": active,
        "display_routes": [
            {
                "id": display.id,
                "name": display.name,
                "type": display.type,
                "entity_id": display.entity_id,
                "browser_id": display.browser_id,
                "dashboard_path": display.dashboard_path,
            }
            for display in config.devices.displays
        ],
        "counts": {
            "media_players": len(cards),
            "active": len(active),
            "displays": len(config.devices.displays),
            "sleep_timer_candidates": sum(1 for card in cards if card["sleep_timer_candidate"]),
        },
        "capabilities": [
            "Draft sleep timers for TVs/displays through the automation builder.",
            "Verify media-player power and playback state after actions.",
            "Track source/app/volume state for better TV and speaker control.",
        ],
    }


async def build_camera_security_brain(config: AppConfig) -> dict[str, Any]:
    states = await safe_get_states()
    cameras = []
    for camera in config.devices.cameras:
        ent = states.get(camera.entity_id)
        cameras.append({
            "id": camera.id,
            "name": camera.name,
            "entity_id": camera.entity_id,
            "state": ent.state if ent else "unknown",
            "online": ent.available if ent else None,
            "dashboard_path": camera.dashboard_path,
            "aliases": camera.aliases,
        })

    events = _camera_event_sensors(states)
    locks = []
    for lock in config.devices.locks:
        ent = states.get(lock.entity_id)
        locks.append({
            "id": lock.id,
            "name": lock.name,
            "entity_id": lock.entity_id,
            "state": ent.state if ent else "unknown",
            "battery_sensor": lock.battery_sensor,
            "attention": (ent.state if ent else "") == "unlocked",
        })

    security_sensors = []
    for sensor in config.devices.security_sensors:
        ent = states.get(sensor.entity_id)
        security_sensors.append({
            "name": sensor.name,
            "entity_id": sensor.entity_id,
            "state": ent.state if ent else "unknown",
            "attention": (ent.state if ent else "").lower() in {"on", "open", "detected", "motion"},
        })

    attention = [
        *(lock for lock in locks if lock["attention"]),
        *(sensor for sensor in security_sensors if sensor["attention"]),
        *(camera for camera in cameras if camera["online"] is False),
    ]
    return {
        "status": "attention" if attention else "ready",
        "cameras": cameras,
        "events": events,
        "locks": locks,
        "security_sensors": security_sensors,
        "attention": attention,
        "counts": {
            "cameras": len(cameras),
            "online_cameras": sum(1 for camera in cameras if camera["online"] is True),
            "event_sensors": len(events),
            "locks": len(locks),
            "attention": len(attention),
        },
        "briefing": _security_briefing(cameras, events, locks, security_sensors),
    }


async def build_room_occupancy_brain(config: AppConfig) -> dict[str, Any]:
    states = await safe_get_states()
    rooms = []
    for room in config.devices.rooms:
        entity_ids = list(dict.fromkeys([
            *(room.lights or []),
            *(room.fans or []),
            *[item for item in [room.climate, room.speaker, room.display, room.camera, room.lock] if item],
        ]))
        room_states = [states[eid] for eid in entity_ids if eid in states]
        signals = _occupancy_signals(room_states)
        voice_sources = [
            source.id for source in config.devices.voice_sources
            if source.room in {room.id, room.name}
        ]
        score = min(100, signals["score"] + (20 if voice_sources else 0))
        rooms.append({
            "id": room.id,
            "name": room.name,
            "score": score,
            "occupied_likelihood": "high" if score >= 70 else ("medium" if score >= 35 else "low"),
            "signals": signals,
            "voice_sources": voice_sources,
            "active_entities": [entity.entity_id for entity in room_states if _active_room_state(entity)],
            "recommended_context": {
                "speaker": room.speaker,
                "display": room.display,
                "camera": room.camera,
                "climate": room.climate,
            },
        })
    return {
        "status": "ready" if rooms else "needs_rooms",
        "rooms": rooms,
        "counts": {
            "rooms": len(rooms),
            "high_likelihood": sum(1 for room in rooms if room["occupied_likelihood"] == "high"),
            "with_voice_source": sum(1 for room in rooms if room["voice_sources"]),
        },
        "capabilities": [
            "Infer room activity from lights, fans, media players, covers, locks, and motion-style binary sensors.",
            "Use voice source mappings as a strong room-context signal.",
            "Feed future mode automation and proactive suggestions without creating automations automatically.",
        ],
    }


async def build_jarvis_phase_66_71(config: AppConfig) -> dict[str, Any]:
    music = await build_music_assistant_brain(config)
    media = await build_media_control_brain(config)
    security = await build_camera_security_brain(config)
    occupancy = await build_room_occupancy_brain(config)
    score = int(round((
        (100 if music["status"] == "ready" else 72)
        + (100 if media["counts"]["media_players"] else 65)
        + (100 if security["counts"]["cameras"] or security["counts"]["locks"] else 65)
        + (100 if occupancy["counts"]["rooms"] else 50)
    ) / 4))
    return {
        "status": "ready" if score >= 85 else "partial",
        "score": score,
        "music_assistant": music,
        "media_control": media,
        "camera_security": security,
        "room_occupancy": occupancy,
    }


def _music_next_steps(accounts: list[dict[str, Any]], speakers: list[dict[str, Any]]) -> list[str]:
    steps = []
    if not accounts:
        steps.append("Add at least one Music Assistant/Spotify account in TPG HomeAI.")
    if any(not speaker["music_assistant_ready"] for speaker in speakers):
        steps.append("Map music_assistant_entity_id for speakers that should search/play through Music Assistant.")
    if any(not account.get("default_media") for account in accounts):
        steps.append("Set optional default media per user for 'play my music' commands.")
    return steps or ["Music Assistant routing is ready for configured accounts and speakers."]


def _media_controls(attrs: dict[str, Any]) -> dict[str, bool]:
    features = int(attrs.get("supported_features") or 0)
    return {
        "volume": "volume_level" in attrs or bool(features),
        "source": bool(attrs.get("source_list")),
        "app_tracking": "app_name" in attrs,
        "media_title": "media_title" in attrs,
    }


def _camera_event_sensors(states: dict[str, HAEntity]) -> list[dict[str, Any]]:
    events = []
    keywords = ("motion", "person", "package", "vehicle", "doorbell", "camera event")
    for entity in states.values():
        blob = f"{entity.entity_id} {entity.friendly_name or ''}".lower()
        if entity.domain not in {"binary_sensor", "sensor"}:
            continue
        if not any(keyword in blob for keyword in keywords):
            continue
        events.append({
            "entity_id": entity.entity_id,
            "name": entity.friendly_name or entity.entity_id,
            "state": entity.state,
            "available": entity.available,
            "event_type": next((keyword for keyword in keywords if keyword in blob), "event"),
            "active": str(entity.state).lower() in {"on", "detected", "motion", "person", "vehicle", "package"},
        })
    return events[:50]


def _security_briefing(
    cameras: list[dict[str, Any]],
    events: list[dict[str, Any]],
    locks: list[dict[str, Any]],
    sensors: list[dict[str, Any]],
) -> str:
    unlocked = [lock["name"] for lock in locks if lock["state"] == "unlocked"]
    offline_cameras = [camera["name"] for camera in cameras if camera["online"] is False]
    active_events = [event["name"] for event in events if event["active"]]
    active_sensors = [sensor["name"] for sensor in sensors if sensor["attention"]]
    parts = []
    if unlocked:
        parts.append(f"Unlocked: {', '.join(unlocked)}.")
    if offline_cameras:
        parts.append(f"Cameras offline: {', '.join(offline_cameras)}.")
    if active_events:
        parts.append(f"Recent/active events: {', '.join(active_events[:6])}.")
    if active_sensors:
        parts.append(f"Active sensors: {', '.join(active_sensors[:6])}.")
    return " ".join(parts) or "Security looks calm from configured locks, cameras, and sensors."


def _occupancy_signals(room_states: list[HAEntity]) -> dict[str, Any]:
    active_media = [e.entity_id for e in room_states if e.domain == "media_player" and e.state in {"on", "playing", "paused"}]
    active_lights = [e.entity_id for e in room_states if e.domain == "light" and e.state == "on"]
    active_fans = [e.entity_id for e in room_states if e.domain == "fan" and e.state == "on"]
    active_motion = [
        e.entity_id for e in room_states
        if e.domain == "binary_sensor"
        and any(word in f"{e.entity_id} {e.friendly_name or ''}".lower() for word in ("motion", "occupancy", "presence"))
        and e.state == "on"
    ]
    score = (
        min(35, len(active_motion) * 35)
        + min(25, len(active_media) * 25)
        + min(20, len(active_lights) * 10)
        + min(10, len(active_fans) * 10)
    )
    return {
        "score": score,
        "motion": active_motion,
        "media": active_media,
        "lights": active_lights,
        "fans": active_fans,
    }


def _active_room_state(entity: HAEntity) -> bool:
    state = str(entity.state or "").lower()
    if entity.domain == "media_player":
        return state in {"on", "playing", "paused"}
    return state in {"on", "open", "opening", "unlocked", "cool", "heat", "heating", "cooling"}
