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
from .router.resolver import Resolver


async def answer_general(
    assistant_name: str,
    user_name: Optional[str],
    message: str,
    conversation_id: Optional[str] = None,
) -> dict[str, Any]:
    config = get_config()
    states = await safe_get_states()
    resolver = Resolver(config, states)
    assistant = _assistant(resolver, assistant_name)
    user = _user(resolver, user_name, assistant)
    house_context = _house_context(config, states, message)
    recent_context = _recent_context(assistant.id if assistant else assistant_name, user.id if user else user_name, conversation_id)
    response = get_ai_client().general_chat(
        message,
        config,
        assistant,
        user,
        conversation_context=recent_context,
        house_context=house_context,
    )
    _log_general(assistant_name, user_name or "", message, response.get("message", ""), conversation_id)
    return {
        "success": True,
        "mode": response.get("mode", "conversation"),
        "provider": response.get("provider", "fallback_parser"),
        "response": response.get("message", ""),
        "data": {
            "house_context": house_context,
            "conversation_context": recent_context,
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
    if any(k in text for k in ["dashboard", "room", "zone", "blueprint", "floor plan", "floorplan", "map"]):
        rooms = ", ".join(room.name for room in config.devices.rooms) or "none"
        displays = ", ".join(display.name for display in config.devices.displays) or "none"
        parts.append(f"Configured rooms: {rooms}.")
        parts.append(f"Configured displays/tablets: {displays}.")
        parts.append(
            "Dashboard builder can draft Lovelace YAML from approved rooms/devices. "
            "Blueprint/floor-plan uploads should be reviewed and converted into approved room/zone context before automation use."
        )
    if not parts:
        rooms = len(config.devices.rooms)
        devices = len(config.devices.device_aliases) + len(config.devices.speakers) + len(config.devices.displays)
        parts.append(f"House has {rooms} configured rooms and at least {devices} approved mapped devices/surfaces.")
    return "\n".join(parts)


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
