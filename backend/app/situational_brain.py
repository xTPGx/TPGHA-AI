"""Environment, schedule, presence, and briefing intelligence for Jarvis phases 72-76."""
from __future__ import annotations

import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .db.database import get_session
from .db.models import CommandLog, Suggestion
from .homeassistant.services import HAEntity, safe_get_states
from .models.schemas import AppConfig


async def build_environment_brain(config: AppConfig) -> dict[str, Any]:
    states = await safe_get_states()
    weather = [_weather_card(entity) for entity in states.values() if entity.domain == "weather"]
    sensors = [_environment_sensor(entity) for entity in states.values() if _is_environment_sensor(entity)]
    sun = [_generic_card(entity) for entity in states.values() if entity.domain == "sun"]
    attention = [
        item for item in sensors
        if item.get("attention")
    ]
    return {
        "status": "attention" if attention else ("ready" if weather or sensors else "needs_sources"),
        "weather": weather[:4],
        "environment_sensors": sensors[:60],
        "sun": sun[:2],
        "attention": attention[:20],
        "counts": {
            "weather": len(weather),
            "environment_sensors": len(sensors),
            "sun": len(sun),
            "attention": len(attention),
        },
        "capabilities": [
            "Answer weather and outside-condition questions from Home Assistant weather entities.",
            "Summarize temperature, humidity, air quality, illuminance, rain, UV, and wind sensors.",
            "Feed morning/evening briefings and comfort recommendations without changing devices automatically.",
        ],
        "next_steps": _environment_next_steps(weather, sensors),
    }


async def build_calendar_todo_brain(config: AppConfig) -> dict[str, Any]:
    states = await safe_get_states()
    calendars = [_calendar_card(entity) for entity in states.values() if entity.domain == "calendar"]
    todos = [_todo_card(entity) for entity in states.values() if entity.domain in {"todo", "shopping_list"}]
    active_calendars = [item for item in calendars if item.get("active")]
    open_todos = [item for item in todos if item.get("open_count", 0) > 0]
    return {
        "status": "active" if active_calendars or open_todos else ("ready" if calendars or todos else "needs_sources"),
        "calendars": calendars,
        "todos": todos,
        "attention": [*active_calendars[:10], *open_todos[:10]],
        "counts": {
            "calendars": len(calendars),
            "active_calendars": len(active_calendars),
            "todo_lists": len(todos),
            "open_todo_lists": len(open_todos),
        },
        "capabilities": [
            "Discover calendar and todo entities for future-aware briefings.",
            "Support automation drafts triggered by calendar events.",
            "Keep scheduling read-only until a user approves an automation or task change.",
        ],
        "next_steps": _calendar_next_steps(calendars, todos),
    }


async def build_presence_zone_brain(config: AppConfig) -> dict[str, Any]:
    states = await safe_get_states()
    people = [_presence_card(entity) for entity in states.values() if entity.domain in {"person", "device_tracker"}]
    zones = [_zone_card(entity) for entity in states.values() if entity.domain == "zone"]
    home = [item for item in people if item.get("state") in {"home", "on"}]
    away = [item for item in people if item.get("state") not in {"home", "on", "unknown", "unavailable"}]
    personal_devices = [
        {
            "id": device.id,
            "name": device.name,
            "entity_id": device.entity_id,
            "owner": device.owner,
            "platform": device.platform,
            "device_type": device.device_type,
            "room": device.room,
        }
        for device in config.devices.personal_devices
    ]
    return {
        "status": "ready" if people or personal_devices else "needs_sources",
        "people": people,
        "zones": zones,
        "personal_devices": personal_devices,
        "home": home,
        "away": away,
        "counts": {
            "people": len(people),
            "home": len(home),
            "away_or_zoned": len(away),
            "zones": len(zones),
            "personal_devices": len(personal_devices),
        },
        "capabilities": [
            "Summarize who appears home, away, or in a named zone.",
            "Use personal-device mappings to improve user identity and room/presence confidence.",
            "Feed away/home mode recommendations without bypassing security policy.",
        ],
        "next_steps": _presence_next_steps(people, personal_devices),
    }


async def build_maintenance_brain(config: AppConfig) -> dict[str, Any]:
    states = await safe_get_states()
    unavailable = [_generic_card(entity) for entity in states.values() if not entity.available]
    batteries = [_battery_card(entity) for entity in states.values() if _is_battery_sensor(entity)]
    low_batteries = [item for item in batteries if item.get("low")]
    updates = [_generic_card(entity) for entity in states.values() if entity.domain == "update" and str(entity.state).lower() == "on"]
    backups = [
        _generic_card(entity)
        for entity in states.values()
        if "backup" in f"{entity.entity_id} {entity.friendly_name or ''}".lower()
    ]
    with get_session() as session:
        open_suggestions = session.query(Suggestion).filter(
            Suggestion.category.in_(["maintenance", "learning"]),
            Suggestion.status.in_(["suggested", "draft", "edited"]),
        ).count()
        recent_failures = session.query(CommandLog).filter(CommandLog.success.is_(False)).count()
    return {
        "status": "attention" if unavailable or low_batteries or updates else "ready",
        "unavailable": unavailable[:80],
        "low_batteries": low_batteries[:50],
        "updates": updates[:40],
        "backups": backups[:20],
        "counts": {
            "unavailable": len(unavailable),
            "battery_sensors": len(batteries),
            "low_batteries": len(low_batteries),
            "updates_available": len(updates),
            "backup_entities": len(backups),
            "open_maintenance_suggestions": open_suggestions,
            "historical_failed_commands": recent_failures,
        },
        "capabilities": [
            "Detect unavailable entities, low batteries, update entities, and backup-related sensors.",
            "Expose maintenance attention without hiding audit history.",
            "Feed proactive maintenance suggestions and daily briefings.",
        ],
    }


async def build_daily_briefing(config: AppConfig) -> dict[str, Any]:
    environment = await build_environment_brain(config)
    calendar = await build_calendar_todo_brain(config)
    presence = await build_presence_zone_brain(config)
    maintenance = await build_maintenance_brain(config)
    now = _now(config)
    headline = _briefing_headline(now, environment, calendar, presence, maintenance)
    sections = [
        _briefing_section("Environment", _environment_summary(environment)),
        _briefing_section("Schedule", _calendar_summary(calendar)),
        _briefing_section("Presence", _presence_summary(presence)),
        _briefing_section("Maintenance", _maintenance_summary(maintenance)),
    ]
    attention = [
        *environment.get("attention", [])[:5],
        *calendar.get("attention", [])[:5],
        *maintenance.get("unavailable", [])[:5],
        *maintenance.get("low_batteries", [])[:5],
    ]
    return {
        "status": "attention" if attention else "ready",
        "generated_at": now.isoformat(),
        "headline": headline,
        "spoken": " ".join([headline, *[section["summary"] for section in sections if section["summary"]]]),
        "sections": sections,
        "attention": attention[:20],
        "brains": {
            "environment": environment,
            "calendar_todo": calendar,
            "presence_zones": presence,
            "maintenance": maintenance,
        },
        "counts": {
            "attention": len(attention),
            "sections": len(sections),
        },
    }


async def build_jarvis_phase_72_76(config: AppConfig) -> dict[str, Any]:
    briefing = await build_daily_briefing(config)
    brains = briefing["brains"]
    score = int(round((
        _source_score(brains["environment"], "weather", "environment_sensors")
        + _source_score(brains["calendar_todo"], "calendars", "todo_lists")
        + _source_score(brains["presence_zones"], "people", "personal_devices")
        + 100
        + 100
    ) / 5))
    return {
        "status": "ready" if score >= 85 else "partial",
        "score": score,
        "environment": brains["environment"],
        "calendar_todo": brains["calendar_todo"],
        "presence_zones": brains["presence_zones"],
        "maintenance": brains["maintenance"],
        "daily_briefing": briefing,
    }


def _weather_card(entity: HAEntity) -> dict[str, Any]:
    attrs = entity.attributes or {}
    return {
        "entity_id": entity.entity_id,
        "name": entity.friendly_name or entity.entity_id,
        "condition": entity.state,
        "temperature": attrs.get("temperature"),
        "temperature_unit": attrs.get("temperature_unit"),
        "humidity": attrs.get("humidity"),
        "wind_speed": attrs.get("wind_speed"),
        "wind_speed_unit": attrs.get("wind_speed_unit"),
        "pressure": attrs.get("pressure"),
        "forecast_available": bool(attrs.get("forecast")),
        "available": entity.available,
    }


def _environment_sensor(entity: HAEntity) -> dict[str, Any]:
    blob = f"{entity.entity_id} {entity.friendly_name or ''} {entity.attributes.get('device_class') if entity.attributes else ''}".lower()
    kind = next((k for k in _ENVIRONMENT_KEYWORDS if k in blob), "environment")
    value = _numeric(entity.state)
    return {
        "entity_id": entity.entity_id,
        "name": entity.friendly_name or entity.entity_id,
        "kind": kind,
        "state": entity.state,
        "unit": (entity.attributes or {}).get("unit_of_measurement"),
        "available": entity.available,
        "attention": _environment_attention(kind, value),
    }


def _calendar_card(entity: HAEntity) -> dict[str, Any]:
    attrs = entity.attributes or {}
    return {
        "entity_id": entity.entity_id,
        "name": entity.friendly_name or entity.entity_id,
        "state": entity.state,
        "active": str(entity.state).lower() == "on",
        "message": attrs.get("message"),
        "start_time": attrs.get("start_time"),
        "end_time": attrs.get("end_time"),
        "location": attrs.get("location"),
        "available": entity.available,
    }


def _todo_card(entity: HAEntity) -> dict[str, Any]:
    attrs = entity.attributes or {}
    open_count = attrs.get("open_todo_count") or attrs.get("items") or attrs.get("incomplete_items")
    return {
        "entity_id": entity.entity_id,
        "name": entity.friendly_name or entity.entity_id,
        "state": entity.state,
        "open_count": int(open_count) if isinstance(open_count, int) else 0,
        "available": entity.available,
    }


def _presence_card(entity: HAEntity) -> dict[str, Any]:
    attrs = entity.attributes or {}
    return {
        "entity_id": entity.entity_id,
        "name": entity.friendly_name or entity.entity_id,
        "state": str(entity.state or "").lower(),
        "source_type": attrs.get("source_type"),
        "gps_accuracy": attrs.get("gps_accuracy"),
        "battery": attrs.get("battery_level"),
        "available": entity.available,
    }


def _zone_card(entity: HAEntity) -> dict[str, Any]:
    attrs = entity.attributes or {}
    return {
        "entity_id": entity.entity_id,
        "name": entity.friendly_name or entity.entity_id,
        "persons": _numeric(entity.state) or 0,
        "latitude": attrs.get("latitude"),
        "longitude": attrs.get("longitude"),
        "radius": attrs.get("radius"),
    }


def _battery_card(entity: HAEntity) -> dict[str, Any]:
    value = _numeric(entity.state)
    low = str(entity.state).lower() in {"low", "critical"} or (value is not None and value <= 20)
    return {
        "entity_id": entity.entity_id,
        "name": entity.friendly_name or entity.entity_id,
        "state": entity.state,
        "value": value,
        "unit": (entity.attributes or {}).get("unit_of_measurement"),
        "low": low,
        "available": entity.available,
    }


def _generic_card(entity: HAEntity) -> dict[str, Any]:
    return {
        "entity_id": entity.entity_id,
        "name": entity.friendly_name or entity.entity_id,
        "state": entity.state,
        "available": entity.available,
    }


_ENVIRONMENT_KEYWORDS = (
    "temperature", "humidity", "illuminance", "light level", "air quality", "pm2", "pm10",
    "carbon dioxide", "co2", "voc", "uv", "rain", "precipitation", "wind", "pressure",
)


def _is_environment_sensor(entity: HAEntity) -> bool:
    if entity.domain not in {"sensor", "binary_sensor"}:
        return False
    blob = f"{entity.entity_id} {entity.friendly_name or ''} {(entity.attributes or {}).get('device_class', '')}".lower()
    return any(keyword in blob for keyword in _ENVIRONMENT_KEYWORDS)


def _is_battery_sensor(entity: HAEntity) -> bool:
    blob = f"{entity.entity_id} {entity.friendly_name or ''} {(entity.attributes or {}).get('device_class', '')}".lower()
    return "battery" in blob


def _environment_attention(kind: str, value: float | None) -> bool:
    if value is None:
        return False
    if kind in {"humidity"}:
        return value < 25 or value > 65
    if kind in {"carbon dioxide", "co2"}:
        return value >= 1200
    if kind in {"pm2", "pm10", "voc", "air quality"}:
        return value >= 100
    if kind in {"uv"}:
        return value >= 7
    return False


def _numeric(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _now(config: AppConfig) -> dt.datetime:
    household = config.household.default_household()
    tz_name = household.timezone if household else "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = dt.timezone.utc
    return dt.datetime.now(tz)


def _briefing_headline(
    now: dt.datetime,
    environment: dict[str, Any],
    calendar: dict[str, Any],
    presence: dict[str, Any],
    maintenance: dict[str, Any],
) -> str:
    attention = (
        environment.get("counts", {}).get("attention", 0)
        + calendar.get("counts", {}).get("active_calendars", 0)
        + maintenance.get("counts", {}).get("unavailable", 0)
        + maintenance.get("counts", {}).get("low_batteries", 0)
    )
    greeting = "Morning" if now.hour < 12 else ("Afternoon" if now.hour < 18 else "Evening")
    people_home = presence.get("counts", {}).get("home", 0)
    return f"{greeting} briefing ready. {attention} item(s) need attention. {people_home} tracked person/device source(s) appear home."


def _briefing_section(title: str, summary: str) -> dict[str, str]:
    return {"title": title, "summary": summary}


def _environment_summary(brain: dict[str, Any]) -> str:
    weather = brain.get("weather") or []
    if weather:
        first = weather[0]
        temp = first.get("temperature")
        temp_unit = first.get("temperature_unit") or ""
        temp_text = f", {temp}{temp_unit}" if temp is not None else ""
        return f"{first.get('name')} reports {first.get('condition')}{temp_text}."
    return f"{brain.get('counts', {}).get('environment_sensors', 0)} environment sensors are available."


def _calendar_summary(brain: dict[str, Any]) -> str:
    active = brain.get("counts", {}).get("active_calendars", 0)
    todos = brain.get("counts", {}).get("open_todo_lists", 0)
    return f"{active} active calendar source(s) and {todos} todo list(s) with open items."


def _presence_summary(brain: dict[str, Any]) -> str:
    counts = brain.get("counts", {})
    return f"{counts.get('home', 0)} source(s) home; {counts.get('away_or_zoned', 0)} away or in another zone."


def _maintenance_summary(brain: dict[str, Any]) -> str:
    counts = brain.get("counts", {})
    return (
        f"{counts.get('unavailable', 0)} unavailable entities, "
        f"{counts.get('low_batteries', 0)} low batteries, "
        f"{counts.get('updates_available', 0)} updates available."
    )


def _environment_next_steps(weather: list[dict[str, Any]], sensors: list[dict[str, Any]]) -> list[str]:
    steps = []
    if not weather:
        steps.append("Expose a Home Assistant weather entity for stronger local forecasts.")
    if not sensors:
        steps.append("Add or approve temperature/humidity/air-quality/light sensors for comfort awareness.")
    return steps or ["Environment awareness is ready from available HA weather and sensor entities."]


def _calendar_next_steps(calendars: list[dict[str, Any]], todos: list[dict[str, Any]]) -> list[str]:
    steps = []
    if not calendars:
        steps.append("Add calendar entities for upcoming-event briefings and calendar-triggered automations.")
    if not todos:
        steps.append("Add todo entities for household task briefings.")
    return steps or ["Calendar and todo awareness is ready from HA entities."]


def _presence_next_steps(people: list[dict[str, Any]], personal_devices: list[dict[str, Any]]) -> list[str]:
    steps = []
    if not people:
        steps.append("Enable person or device_tracker entities for home/away awareness.")
    if not personal_devices:
        steps.append("Map personal devices to users so identity and presence confidence improve.")
    return steps or ["Presence and personal-device awareness is ready."]


def _source_score(brain: dict[str, Any], *keys: str) -> int:
    counts = brain.get("counts", {})
    return 100 if any(int(counts.get(key, 0) or 0) > 0 for key in keys) else 70
