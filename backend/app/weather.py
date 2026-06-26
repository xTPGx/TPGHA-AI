"""Deterministic weather lookup for general conversation."""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

import httpx

logger = logging.getLogger("tpg.weather")

_WEATHER_HINT_RE = re.compile(
    r"\b(weather|forecast|temperature|rain|snow|wind|hot|cold|humidity)\b",
    re.I,
)
_LOCATION_RE = re.compile(
    r"\b(?:weather|forecast|temperature|rain|snow|wind|humidity)\b.*?\b(?:in|for|near)\s+(.+)$",
    re.I,
)
_TRAILING_LOCATION_RE = re.compile(r"\b(?:in|for|near)\s+([A-Za-z][A-Za-z .,'-]{1,80})[?.!]*$", re.I)
_JUNK_LOCATION_TAIL_RE = re.compile(
    r"\s+\b(today|tomorrow|tonight|right now|now|please|pls|for me|currently|outside)\b.*$",
    re.I,
)
_ASSISTANT_ADDRESS_RE = re.compile(
    r"^\s*(?:hey|hi|ok|okay)?\s*(?:atlas|atlass|alice|alex|jarvis|chatty|computer)[,\s]+",
    re.I,
)

_WEATHER_CODES = {
    0: "clear",
    1: "mostly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "foggy with rime",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    80: "light showers",
    81: "showers",
    82: "heavy showers",
    95: "thunderstorms",
    96: "thunderstorms with hail",
    99: "severe thunderstorms with hail",
}


def should_fetch_weather(message: str) -> bool:
    return bool(_WEATHER_HINT_RE.search(message or ""))


async def fetch_weather_for_message(message: str) -> dict[str, Any] | None:
    """Return current weather for a named location, or None if none is named."""

    location = extract_weather_location(message)
    if not location:
        return None
    started_location = location
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            geo = await _geocode(client, location)
            if not geo:
                return {
                    "success": False,
                    "provider": "open-meteo",
                    "location": started_location,
                    "error": f"I could not resolve a weather location for '{started_location}'.",
                }
            forecast = await _forecast(client, geo)
    except Exception as exc:  # noqa: BLE001 - degraded weather should not break chat
        logger.warning("Weather lookup failed (%s).", type(exc).__name__)
        return {
            "success": False,
            "provider": "open-meteo",
            "location": started_location,
            "error": f"Weather lookup failed: {type(exc).__name__}.",
        }
    current = forecast.get("current") or {}
    units = forecast.get("current_units") or {}
    daily = forecast.get("daily") or {}
    return {
        "success": True,
        "provider": "open-meteo",
        "requested_location": started_location,
        "location": {
            "name": geo.get("name"),
            "admin1": geo.get("admin1"),
            "country": geo.get("country"),
            "latitude": geo.get("latitude"),
            "longitude": geo.get("longitude"),
            "timezone": geo.get("timezone"),
        },
        "current": {
            "condition": _weather_code_label(current.get("weather_code")),
            "temperature": current.get("temperature_2m"),
            "apparent_temperature": current.get("apparent_temperature"),
            "humidity": current.get("relative_humidity_2m"),
            "wind_speed": current.get("wind_speed_10m"),
            "wind_gusts": current.get("wind_gusts_10m"),
            "precipitation": current.get("precipitation"),
            "time": current.get("time"),
        },
        "units": {
            "temperature": units.get("temperature_2m") or "F",
            "humidity": units.get("relative_humidity_2m") or "%",
            "wind_speed": units.get("wind_speed_10m") or "mph",
            "precipitation": units.get("precipitation") or "inch",
        },
        "daily": {
            "max_temperature": _first(daily.get("temperature_2m_max")),
            "min_temperature": _first(daily.get("temperature_2m_min")),
            "precipitation_probability": _first(daily.get("precipitation_probability_max")),
        },
    }


def extract_weather_location(message: str) -> str:
    text = _ASSISTANT_ADDRESS_RE.sub("", str(message or "")).strip()
    match = _LOCATION_RE.search(text) or _TRAILING_LOCATION_RE.search(text)
    if not match:
        return ""
    location = match.group(1)
    location = _JUNK_LOCATION_TAIL_RE.sub("", location)
    location = re.sub(r"\b(what'?s|what is|like|today|the|weather|forecast)\b", " ", location, flags=re.I)
    location = re.sub(r"[^A-Za-z0-9 .,'-]+", " ", location)
    location = " ".join(location.split()).strip(" .,")
    return location[:80]


def format_weather_context(weather: dict[str, Any] | None) -> str:
    if not weather:
        return ""
    if not weather.get("success"):
        return f"Weather lookup for {weather.get('location') or 'the requested location'} failed: {weather.get('error')}"
    loc = weather.get("location") or {}
    current = weather.get("current") or {}
    units = weather.get("units") or {}
    daily = weather.get("daily") or {}
    name = ", ".join(part for part in [loc.get("name"), loc.get("admin1"), loc.get("country")] if part)
    temp_unit = units.get("temperature") or "F"
    wind_unit = units.get("wind_speed") or "mph"
    precip_unit = units.get("precipitation") or "inch"
    lines = [f"Live weather from Open-Meteo for {name or weather.get('requested_location', '')}:"]
    lines.append(
        "- Current: "
        + ", ".join(
            part for part in [
                str(current.get("condition") or "").strip(),
                _value("temperature", current.get("temperature"), temp_unit),
                _value("feels like", current.get("apparent_temperature"), temp_unit),
                _value("humidity", current.get("humidity"), "%"),
                _value("wind", current.get("wind_speed"), wind_unit),
                _value("gusts", current.get("wind_gusts"), wind_unit),
                _value("precipitation", current.get("precipitation"), precip_unit),
            ] if part
        )
    )
    daily_parts = [
        _value("high", daily.get("max_temperature"), temp_unit),
        _value("low", daily.get("min_temperature"), temp_unit),
        _value("precip chance", daily.get("precipitation_probability"), "%"),
    ]
    if any(daily_parts):
        lines.append("- Today: " + ", ".join(part for part in daily_parts if part))
    lines.append("Instruction: answer the user's weather question from this live weather block; do not say search failed.")
    return "\n".join(lines)


async def _geocode(client: httpx.AsyncClient, location: str) -> dict[str, Any] | None:
    url = (
        "https://geocoding-api.open-meteo.com/v1/search"
        f"?name={quote_plus(location)}&count=1&language=en&format=json"
    )
    response = await client.get(url)
    response.raise_for_status()
    results = response.json().get("results") or []
    return results[0] if results else None


async def _forecast(client: httpx.AsyncClient, geo: dict[str, Any]) -> dict[str, Any]:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={geo['latitude']}&longitude={geo['longitude']}"
        "&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,"
        "rain,showers,snowfall,weather_code,cloud_cover,wind_speed_10m,wind_gusts_10m"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        "&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch"
        "&timezone=auto&forecast_days=2"
    )
    response = await client.get(url)
    response.raise_for_status()
    return response.json()


def _weather_code_label(value: Any) -> str:
    try:
        code = int(value)
    except (TypeError, ValueError):
        return "unknown conditions"
    return _WEATHER_CODES.get(code, f"weather code {code}")


def _first(value: Any) -> Any:
    if isinstance(value, list) and value:
        return value[0]
    return None


def _value(label: str, value: Any, unit: str) -> str:
    if value is None or value == "":
        return ""
    return f"{label} {value}{unit}"
