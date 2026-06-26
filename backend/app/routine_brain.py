"""Routine and scene intelligence for Jarvis phases 77-81.

These brains draft recommendations and plans. They do not execute or install
automations directly; guarded actions and approval workflows still own changes.
"""
from __future__ import annotations

from typing import Any

from .homeassistant.services import HAEntity, safe_get_states
from .media_brain import build_media_control_brain
from .models.schemas import AppConfig
from .situational_brain import (
    build_environment_brain,
    build_maintenance_brain,
    build_presence_zone_brain,
)


async def build_security_routine_brain(config: AppConfig) -> dict[str, Any]:
    states = await safe_get_states()
    locks = [_entity_card(e) for e in states.values() if e.domain == "lock"]
    covers = [_entity_card(e) for e in states.values() if e.domain in {"cover", "garage_door"}]
    sensors = [
        _entity_card(e) for e in states.values()
        if e.domain == "binary_sensor" and _matches(e, ("door", "window", "motion", "occupancy", "glass", "tamper"))
    ]
    unlocked = [item for item in locks if item["state"] == "unlocked"]
    open_covers = [item for item in covers if item["state"] in {"open", "opening"}]
    active_sensors = [item for item in sensors if item["state"] in {"on", "open", "detected"}]
    routines = [
        _routine("secure_house", "Secure the house", "Lock doors, close covers, and report active sensors.", "security"),
        _routine("arrival_check", "Arrival check", "Summarize doors, cameras, and active motion when someone arrives.", "security"),
        _routine("night_lockup", "Night lockup", "Review unlocked doors, open covers, active media, and remaining lights.", "security"),
    ]
    return {
        "status": "attention" if unlocked or open_covers else "ready",
        "locks": locks,
        "covers": covers,
        "sensors": sensors[:80],
        "attention": [*unlocked, *open_covers, *active_sensors[:10]],
        "routine_templates": routines,
        "guardrails": [
            "Locking/closing can be one-step when target confidence is high.",
            "Unlocking/opening/disarming remains confirmation and PIN gated.",
            "Outside/guest voice sources should only receive security summaries unless explicitly trusted.",
        ],
        "counts": {
            "locks": len(locks),
            "covers": len(covers),
            "sensors": len(sensors),
            "attention": len(unlocked) + len(open_covers) + len(active_sensors),
        },
    }


async def build_comfort_energy_brain(config: AppConfig) -> dict[str, Any]:
    states = await safe_get_states()
    environment = await build_environment_brain(config)
    lights_on = [_entity_card(e) for e in states.values() if e.domain == "light" and e.state == "on"]
    fans_on = [_entity_card(e) for e in states.values() if e.domain == "fan" and e.state == "on"]
    climate_active = [
        _entity_card(e) for e in states.values()
        if e.domain == "climate" and str(e.state).lower() not in {"off", "unavailable", "unknown"}
    ]
    helper_controls = [
        _entity_card(e) for e in states.values()
        if e.domain in {"humidifier", "water_heater", "number", "select", "switch"}
        and _matches(e, ("humidity", "heater", "energy", "mode", "temperature", "comfort"))
    ]
    recommendations = []
    if lights_on:
        recommendations.append("Review lights that are on when rooms appear empty or the house is away.")
    if climate_active:
        recommendations.append("Compare active climate devices with presence and weather before suggesting away/sleep temperatures.")
    if environment.get("counts", {}).get("attention", 0):
        recommendations.append("Environment sensors show comfort attention; consider humidity, air quality, or UV guidance.")
    return {
        "status": "optimize" if lights_on or climate_active or environment.get("attention") else "ready",
        "lights_on": lights_on[:80],
        "fans_on": fans_on[:80],
        "climate_active": climate_active[:40],
        "helper_controls": helper_controls[:40],
        "environment": environment,
        "recommendations": recommendations or ["Comfort and energy posture looks calm from available sources."],
        "routine_templates": [
            _routine("away_energy_review", "Away energy review", "Suggest turning off lights/fans and adjusting climate when nobody is home.", "energy"),
            _routine("comfort_balance", "Comfort balance", "Use temperature/humidity/weather context before changing fans or climate.", "comfort"),
            _routine("air_quality_check", "Air quality check", "Summarize humidity, CO2/VOC/PM sensors, and suggest ventilation only for review.", "comfort"),
        ],
        "counts": {
            "lights_on": len(lights_on),
            "fans_on": len(fans_on),
            "climate_active": len(climate_active),
            "helper_controls": len(helper_controls),
        },
    }


async def build_media_scene_brain(config: AppConfig) -> dict[str, Any]:
    media = await build_media_control_brain(config)
    active = media.get("active", [])
    scenes = [
        {
            "id": "movie_mode",
            "name": "Movie mode",
            "uses": ["display", "speakers", "lights", "quiet replies"],
            "approval_required": True,
            "notes": "Draft a scene using the active/selected TV, dimmable lights, and room speaker routing.",
        },
        {
            "id": "music_everywhere",
            "name": "Music everywhere",
            "uses": ["Music Assistant", "speakers", "user music account"],
            "approval_required": True,
            "notes": "Route music through approved speakers while preserving the assistant owner's music account.",
        },
        {
            "id": "focus_mode",
            "name": "Focus mode",
            "uses": ["lights", "speaker", "notifications"],
            "approval_required": True,
            "notes": "Keep replies quiet, set useful lighting, and avoid disruptive media changes.",
        },
    ]
    return {
        "status": "active" if active else "ready",
        "active_media": active,
        "display_routes": media.get("display_routes", []),
        "scene_templates": scenes,
        "counts": {
            "active_media": len(active),
            "display_routes": len(media.get("display_routes", [])),
            "scene_templates": len(scenes),
        },
        "capabilities": [
            "Draft media scenes from known displays, speakers, lights, and assistant reply policy.",
            "Keep scene installation approval-first.",
            "Use Music Assistant account boundaries when media scenes include music.",
        ],
    }


async def build_sleep_wake_brain(config: AppConfig) -> dict[str, Any]:
    states = await safe_get_states()
    media_active = [_entity_card(e) for e in states.values() if e.domain == "media_player" and e.state in {"on", "playing", "paused", "idle"}]
    lights_on = [_entity_card(e) for e in states.values() if e.domain == "light" and e.state == "on"]
    quiet_modes = [mode for mode in config.devices.modes if mode.quiet_hours or "sleep" in f"{mode.id} {mode.name}".lower()]
    templates = [
        _routine("sleep_timer", "Sleep timer", "Turn off selected media/lights after a chosen delay.", "routine"),
        _routine("bedtime_shutdown", "Bedtime shutdown", "Lock up, turn off common lights, and quiet replies after review.", "routine"),
        _routine("morning_wakeup", "Morning wakeup", "Brief weather/schedule, raise selected lights, and keep security summary read-only.", "routine"),
    ]
    return {
        "status": "ready",
        "media_sleep_candidates": media_active[:40],
        "lights_sleep_candidates": lights_on[:80],
        "quiet_modes": [
            {"id": mode.id, "name": mode.name, "reply_mode": mode.reply_mode, "priority": mode.priority}
            for mode in quiet_modes
        ],
        "routine_templates": templates,
        "counts": {
            "media_sleep_candidates": len(media_active),
            "lights_sleep_candidates": len(lights_on),
            "quiet_modes": len(quiet_modes),
        },
        "guardrails": [
            "Future/scheduled changes become automation drafts for approval.",
            "Sleep timers should verify final media/light state after execution.",
            "Wake routines should avoid unlocking/opening security devices automatically.",
        ],
    }


async def build_proactive_action_plan(config: AppConfig) -> dict[str, Any]:
    security = await build_security_routine_brain(config)
    comfort = await build_comfort_energy_brain(config)
    scenes = await build_media_scene_brain(config)
    sleep = await build_sleep_wake_brain(config)
    maintenance = await build_maintenance_brain(config)
    proposals = []
    if security.get("attention"):
        proposals.append(_proposal("security_review", "Review security attention", "security", security["attention"][:5]))
    if comfort.get("lights_on") or comfort.get("climate_active"):
        proposals.append(_proposal("comfort_energy_review", "Review comfort and energy posture", "energy", comfort.get("recommendations", [])))
    if scenes.get("active_media"):
        proposals.append(_proposal("media_sleep_timer", "Offer a media sleep timer", "routine", scenes["active_media"][:5]))
    if maintenance.get("low_batteries") or maintenance.get("unavailable"):
        proposals.append(_proposal("maintenance_review", "Review device maintenance", "maintenance", maintenance.get("low_batteries", [])[:5]))
    return {
        "status": "has_proposals" if proposals else "ready",
        "proposals": proposals,
        "brains": {
            "security_routines": security,
            "comfort_energy": comfort,
            "media_scenes": scenes,
            "sleep_wake": sleep,
            "maintenance": maintenance,
        },
        "counts": {
            "proposals": len(proposals),
            "security_attention": security.get("counts", {}).get("attention", 0),
            "lights_on": comfort.get("counts", {}).get("lights_on", 0),
            "active_media": scenes.get("counts", {}).get("active_media", 0),
        },
        "policy": {
            "approval_first": True,
            "auto_execute": False,
            "reason": "This endpoint drafts what Jarvis should suggest next; action execution stays in guarded command flows.",
        },
    }


async def build_jarvis_phase_77_81(config: AppConfig) -> dict[str, Any]:
    plan = await build_proactive_action_plan(config)
    brains = plan["brains"]
    score = int(round((
        _readiness(brains["security_routines"], "locks", "covers", "sensors")
        + 100
        + 100
        + 100
        + 100
    ) / 5))
    return {
        "status": "ready" if score >= 85 else "partial",
        "score": score,
        "security_routines": brains["security_routines"],
        "comfort_energy": brains["comfort_energy"],
        "media_scenes": brains["media_scenes"],
        "sleep_wake": brains["sleep_wake"],
        "proactive_action_plan": plan,
    }


def _entity_card(entity: HAEntity) -> dict[str, Any]:
    return {
        "entity_id": entity.entity_id,
        "name": entity.friendly_name or entity.entity_id,
        "state": str(entity.state or "").lower(),
        "available": entity.available,
    }


def _matches(entity: HAEntity, keywords: tuple[str, ...]) -> bool:
    blob = f"{entity.entity_id} {entity.friendly_name or ''} {(entity.attributes or {}).get('device_class', '')}".lower()
    return any(keyword in blob for keyword in keywords)


def _routine(identifier: str, name: str, description: str, category: str) -> dict[str, Any]:
    return {
        "id": identifier,
        "name": name,
        "description": description,
        "category": category,
        "approval_required": True,
        "install_path": "automation_draft",
    }


def _proposal(identifier: str, title: str, category: str, evidence: list[Any]) -> dict[str, Any]:
    return {
        "id": identifier,
        "title": title,
        "category": category,
        "approval_required": True,
        "evidence": evidence,
    }


def _readiness(brain: dict[str, Any], *keys: str) -> int:
    counts = brain.get("counts", {})
    return 100 if any(int(counts.get(key, 0) or 0) > 0 for key in keys) else 75
