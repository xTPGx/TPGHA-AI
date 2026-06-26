"""General conversation brain for TPG HomeAI.

Home actions stay in the guarded tool router. This module handles normal
assistant conversation: advice, brainstorming, weather/status questions, and
planning around dashboards, zones, rooms, blueprints, and future house design.
"""
from __future__ import annotations

from typing import Any, Optional

from .ai.client import get_ai_client
from .config_loader import get_config
from .db.database import get_session
from .db.models import CommandLog
from .homeassistant.services import safe_get_states
from .models.schemas import Assistant, User
from .house_assets import approved_asset_context
from .research import format_search_context, search_web, should_search
from .router.resolver import Resolver


async def answer_general(
    assistant_name: str,
    user_name: Optional[str],
    message: str,
    conversation_id: Optional[str] = None,
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    config = get_config()
    states = await safe_get_states()
    resolver = Resolver(config, states)
    assistant = _assistant(resolver, assistant_name)
    user = _user(resolver, user_name, assistant)
    assistant_id = assistant.id if assistant else assistant_name
    user_id = user.id if user else (user_name or "")
    house_context = _house_context(config, states, message)
    research = None
    if should_search(message):
        research = await search_web(message, max_results=5)
        house_context = f"{house_context}\n\n{format_search_context(research)}"
    recent_context = _recent_context(assistant_id, user_id, conversation_id)
    response = get_ai_client().general_chat(
        message,
        config,
        assistant,
        user,
        conversation_context=recent_context,
        house_context=house_context,
        attachments=attachments or [],
    )
    _log_general(assistant_id, user_id, message, response.get("message", ""), conversation_id)
    return {
        "success": True,
        "mode": response.get("mode", "conversation"),
        "provider": response.get("provider", "fallback_parser"),
        "response": response.get("message", ""),
        "data": {
            "house_context": house_context,
            "conversation_context": recent_context,
            "research": research,
            "attachments": [
                {
                    "filename": item.get("filename", ""),
                    "content_type": item.get("content_type", ""),
                    "size": item.get("size", 0),
                }
                for item in (attachments or [])
            ],
        },
    }


def _assistant(resolver: Resolver, assistant_name: str) -> Optional[Assistant]:
    result = resolver.resolve_assistant(assistant_name)
    return resolver.get_assistant(result.id) if result.matched and result.id else None


def _user(resolver: Resolver, user_name: Optional[str], assistant: Optional[Assistant]) -> Optional[User]:
    if user_name:
        result = resolver.resolve_user(user_name)
        if result.matched and result.id:
            return resolver.get_user(result.id)
    if assistant:
        return resolver.get_user(assistant.owner)
    return None


def _house_context(config, states: dict[str, Any], message: str) -> str:
    parts: list[str] = []
    text = message.lower()
    design_keywords = (
        "switch", "install", "where should", "where do", "weak", "weakness",
        "review what i", "review my", "already have", "recommend", "input",
        "improve", "smart home", "dashboard", "room", "zone", "blueprint",
        "floor plan", "floorplan", "map",
    )
    weather = [entity for entity in states.values() if entity.domain == "weather"]
    if weather and any(k in text for k in ["weather", "temperature outside", "forecast", "rain", "hot outside", "cold outside"]):
        parts.append("Weather from Home Assistant:")
        for entity in weather[:3]:
            attrs = entity.attributes or {}
            temp = attrs.get("temperature")
            humidity = attrs.get("humidity")
            wind = attrs.get("wind_speed")
            details = [f"condition={entity.state}"]
            if temp is not None:
                details.append(f"temperature={temp}{attrs.get('temperature_unit', '')}")
            if humidity is not None:
                details.append(f"humidity={humidity}%")
            if wind is not None:
                details.append(f"wind={wind}{attrs.get('wind_speed_unit', '')}")
            parts.append(f"- {entity.friendly_name or entity.entity_id}: " + ", ".join(details))
    if any(k in text for k in design_keywords):
        parts.append(_structured_house_inventory(config, states))
        rooms = ", ".join(room.name for room in config.devices.rooms) or "none"
        displays = ", ".join(display.name for display in config.devices.displays) or "none"
        parts.append(f"Configured rooms: {rooms}.")
        parts.append(f"Configured displays/tablets: {displays}.")
        asset_context = approved_asset_context()
        if asset_context:
            parts.append(asset_context)
        parts.append(
            "Dashboard builder can draft Lovelace YAML from approved rooms/devices. "
            "Blueprint/floor-plan uploads should be reviewed and converted into approved room/zone context before automation use."
        )
    if not parts:
        parts.append(_structured_house_inventory(config, states, compact=True))
    return "\n".join(parts)


def _structured_house_inventory(config, states: dict[str, Any], *, compact: bool = False) -> str:
    """Ground advice with actual configured rooms and live HA inventory.

    This is the difference between generic advice and a Jarvis-style answer.
    It gives the model the mapped rooms/devices plus likely weak spots without
    requiring the user to restate the devices Home Assistant already knows.
    """

    lines: list[str] = ["Home Assistant / TPG HomeAI inventory snapshot:"]
    rooms = list(config.devices.rooms or [])
    if rooms:
        lines.append("Configured rooms and mapped controls:")
        for room in rooms[:18]:
            controls: list[str] = []
            if room.lights:
                controls.append(f"lights={', '.join(room.lights[:5])}")
            if room.fans:
                controls.append(f"fans={', '.join(room.fans[:5])}")
            if room.climate:
                controls.append(f"climate={room.climate}")
            if room.speaker:
                controls.append(f"speaker={room.speaker}")
            if room.display:
                controls.append(f"display={room.display}")
            if room.camera:
                controls.append(f"camera={room.camera}")
            if room.lock:
                controls.append(f"lock={room.lock}")
            summary = "; ".join(controls) if controls else "no mapped controls yet"
            lines.append(f"- {room.name} ({room.id}): {summary}")
        if len(rooms) > 18:
            lines.append(f"- plus {len(rooms) - 18} more configured rooms")

    domains = {"light", "fan", "switch", "media_player", "climate", "cover", "lock", "person", "device_tracker"}
    live_items: list[str] = []
    unavailable: list[str] = []
    for entity_id in sorted(states):
        entity = states[entity_id]
        domain = getattr(entity, "domain", entity_id.split(".", 1)[0])
        if domain not in domains:
            continue
        friendly = getattr(entity, "friendly_name", None) or entity_id
        state = str(getattr(entity, "state", "") or "")
        item = f"{entity_id} ({friendly}) = {state}"
        if state.lower() in {"unavailable", "unknown"}:
            unavailable.append(item)
        elif len(live_items) < (32 if compact else 80):
            live_items.append(item)

    if live_items:
        lines.append("Relevant live entities:")
        lines.extend(f"- {item}" for item in live_items)
    if unavailable:
        lines.append("Unavailable or unknown relevant entities:")
        lines.extend(f"- {item}" for item in unavailable[:20])
        if len(unavailable) > 20:
            lines.append(f"- plus {len(unavailable) - 20} more unavailable/unknown relevant entities")

    voice_rooms = {source.room for source in (config.devices.voice_sources or []) if source.room}
    rooms_without_voice = [room.name for room in rooms if room.id not in voice_rooms and room.name not in voice_rooms]
    weak_spots: list[str] = []
    if rooms_without_voice:
        weak_spots.append(
            "Rooms without mapped voice source/panel context: "
            + ", ".join(rooms_without_voice[:12])
            + ("..." if len(rooms_without_voice) > 12 else "")
        )
    for room in rooms:
        if not room.lights and not room.fans and not room.speaker and not room.display and not room.climate:
            weak_spots.append(f"{room.name} has no mapped controllable devices in TPG config.")
    if weak_spots:
        lines.append("Likely smart-home weak spots to consider:")
        lines.extend(f"- {item}" for item in weak_spots[:16])

    lines.append(
        "Instruction for advice: use the inventory above first. Do not ask the user to list devices "
        "that are already present here. If data is missing, name the exact missing mapping or sensor."
    )
    return "\n".join(lines)


def _recent_context(assistant: str, user: Optional[str], conversation_id: Optional[str]) -> str:
    with get_session() as session:
        query = session.query(CommandLog).filter(CommandLog.assistant == (assistant or ""))
        if user:
            query = query.filter(CommandLog.user == user)
        if conversation_id:
            query = query.filter(CommandLog.conversation_id == conversation_id)
        rows = query.order_by(CommandLog.created_at.desc()).limit(5).all()
    lines = []
    for row in reversed(rows):
        lines.append(f"- User: {row.message}\n  Assistant: {row.response_message}")
    return "\n".join(lines)


def _log_general(assistant: str, user: str, message: str, response: str,
                 conversation_id: Optional[str]) -> None:
    try:
        with get_session() as session:
            session.add(CommandLog(
                assistant=assistant or "",
                user=user or "",
                message=message,
                conversation_id=conversation_id or "",
                intent="conversation",
                success=True,
                executed=False,
                response_message=response,
                tool_call="{}",
                resolved="{}",
                data='{"provider":"conversation"}',
                error="",
            ))
            session.commit()
    except Exception:
        return
