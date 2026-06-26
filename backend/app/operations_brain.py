"""Operational readiness brains for Jarvis phases 82-86.

These helpers are read-only. They turn config, health, discovery, and HA state
into deployment guidance that is safe to show in the UI or hand to support.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from .actions.automation_installer import ha_config_root
from .bootstrap import get_app_state
from .config_loader import config_error
from .discovery import scanner as discovery_scanner
from .homeassistant.services import safe_get_states
from .models.schemas import AppConfig
from .settings import get_settings


async def build_capability_gap_scanner(config: AppConfig) -> dict[str, Any]:
    settings = get_settings()
    states = await safe_get_states()
    discovery = await discovery_scanner.summary()
    rooms = config.devices.rooms
    assistants = config.assistants.assistants
    voice_sources = config.devices.voice_sources
    open_gaps = [
        _gap(
            "home_assistant_connection",
            "Home Assistant connection",
            "critical",
            not settings.ha_configured,
            "Configure Home Assistant URL/token or Supervisor proxy access.",
        ),
        _gap(
            "openai_key",
            "OpenAI reasoning and TTS",
            "high",
            not settings.openai_configured,
            "Set OPENAI_API_KEY so Jarvis can reason conversationally and generate natural voice replies.",
        ),
        _gap(
            "security_pin",
            "Security PIN",
            "high",
            not bool(settings.security_pin),
            "Set TPG_SECURITY_PIN for unlock, garage, disarm, and other security-disabling confirmations.",
        ),
        _gap(
            "voice_sources",
            "Real voice source mapping",
            "high",
            not any((source.source_device_id or source.source_entity_id) for source in voice_sources),
            "Map at least one HA Assist satellite, browser panel, or microphone source ID to a room.",
        ),
        _gap(
            "wake_words",
            "Assistant wake words",
            "normal",
            not any(assistant.wake_words for assistant in assistants),
            "Add wake phrases to assistant profiles and link them to voice sources.",
        ),
        _gap(
            "rooms",
            "Room model",
            "normal",
            not rooms,
            "Create rooms and map key lights, fans, speakers, displays, locks, and climate devices.",
        ),
        _gap(
            "pending_discovery",
            "Discovery approvals",
            "normal",
            int(discovery.get("pending_count") or 0) > 0,
            f"Review {discovery.get('pending_count', 0)} pending entities so the capability graph is clean.",
        ),
        _gap(
            "music_assistant",
            "Music Assistant speaker routing",
            "normal",
            not any(speaker.music_assistant_entity_id for speaker in config.devices.speakers),
            "Map Music Assistant player entities to speakers for reliable playlist/search playback.",
        ),
        _gap(
            "weather",
            "Weather/environment source",
            "normal",
            not any(entity.domain == "weather" for entity in states.values()),
            "Expose at least one HA weather entity for daily briefings and comfort recommendations.",
        ),
        _gap(
            "dashboard_assets",
            "House photos/floor plans",
            "low",
            True,
            "Optional: upload floor plans, room photos, and tablet notes to improve dashboard generation.",
        ),
    ]
    active = [gap for gap in open_gaps if gap["open"]]
    return {
        "status": "attention" if active else "ready",
        "score": max(0, 100 - sum(_gap_penalty(gap["severity"]) for gap in active)),
        "open_gaps": active,
        "all_gates": open_gaps,
        "counts": {
            "open": len(active),
            "critical": sum(1 for gap in active if gap["severity"] == "critical"),
            "high": sum(1 for gap in active if gap["severity"] == "high"),
            "normal": sum(1 for gap in active if gap["severity"] == "normal"),
            "low": sum(1 for gap in active if gap["severity"] == "low"),
        },
    }


async def build_onboarding_wizard_plan(config: AppConfig) -> dict[str, Any]:
    gaps = await build_capability_gap_scanner(config)
    steps = [
        _step("connect_ha", "Connect Home Assistant", "Verify Supervisor proxy/token and HA reachability.", "required"),
        _step("sync_users", "Sync HA users", "Sync owner/admin and resident profiles from HA users.", "required"),
        _step("approve_discovery", "Approve useful devices", "Clear pending discovery and ignore diagnostic noise.", "required"),
        _step("map_rooms", "Map rooms", "Attach core lights, fans, speakers, displays, locks, and climate devices to rooms.", "required"),
        _step("configure_security", "Configure security policy", "Set the security PIN and review door/garage/alarm permissions.", "required"),
        _step("configure_voice", "Configure voice", "Pick assistant voices, add wake phrases, and bind real mic/source IDs.", "required"),
        _step("configure_music", "Configure music", "Map Music Assistant speakers and per-user music accounts.", "recommended"),
        _step("upload_house_assets", "Add house assets", "Upload floor plans, room photos, and dashboard notes.", "recommended"),
        _step("test_commands", "Run acceptance tests", "Test lights, fans, locks, music, schedules, dashboards, and voice from each user profile.", "required"),
    ]
    open_ids = {gap["id"] for gap in gaps["open_gaps"]}
    for step in steps:
        step["state"] = _step_state(step["id"], open_ids)
    return {
        "status": "ready" if not any(step["state"] == "blocked" for step in steps if step["required"]) else "setup_needed",
        "steps": steps,
        "next_step": next((step for step in steps if step["state"] != "complete"), None),
        "source_gaps": gaps,
    }


async def build_diagnostics_support_pack(config: AppConfig, version: str) -> dict[str, Any]:
    settings = get_settings()
    app_state = get_app_state()
    discovery = await discovery_scanner.summary()
    states = await safe_get_states()
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "safe_for_support": True,
        "secrets_redacted": True,
        "version": version,
        "mode": app_state.mode,
        "status": app_state.status,
        "degraded_reasons": list(app_state.degraded_reasons),
        "config_error": config_error(),
        "settings": settings.safe_dict(),
        "counts": {
            "households": len(config.household.households),
            "users": len(config.assistants.users),
            "assistants": len(config.assistants.assistants),
            "rooms": len(config.devices.rooms),
            "speakers": len(config.devices.speakers),
            "displays": len(config.devices.displays),
            "voice_sources": len(config.devices.voice_sources),
            "states_visible": len(states),
            "discovery_known": discovery.get("known_count", 0),
            "discovery_pending": discovery.get("pending_count", 0),
            "discovery_unavailable": discovery.get("unavailable_count", 0),
        },
        "routes": {
            "health": "/health",
            "brain_layers": "/brain/layers",
            "house_state": "/brain/house-state",
            "phase_82_86": "/brain/phase-82-86",
        },
    }


async def build_backup_recovery_readiness(config: AppConfig) -> dict[str, Any]:
    states = await safe_get_states()
    root = ha_config_root()
    automations = root / "automations.yaml"
    backup_entities = [
        _entity_card(entity)
        for entity in states.values()
        if "backup" in f"{entity.entity_id} {entity.friendly_name or ''}".lower()
    ]
    return {
        "status": "ready" if backup_entities or automations.exists() else "needs_review",
        "ha_config_root": str(root),
        "automations_yaml": {
            "path": str(automations),
            "exists": automations.exists(),
            "backup_pattern": str(automations.with_suffix(automations.suffix + ".tpg-backup-YYYYMMDDHHMMSS")),
        },
        "database": get_settings().safe_dict().get("database_url"),
        "config_dir": get_settings().safe_dict().get("config_dir"),
        "backup_entities": backup_entities[:30],
        "recommendations": [
            "Keep Home Assistant backups enabled before installing generated automations.",
            "Automation installs create timestamped automations.yaml backups before writing.",
            "Export diagnostics before major add-on upgrades or device remapping sessions.",
        ],
    }


async def build_integration_readiness_matrix(config: AppConfig) -> dict[str, Any]:
    settings = get_settings()
    states = await safe_get_states()
    entity_blob = " ".join(states.keys()).lower()
    integrations = [
        _integration("home_assistant", "Home Assistant", settings.ha_configured, "Configured" if settings.ha_configured else "Missing HA URL/token"),
        _integration("openai", "OpenAI", settings.openai_configured, settings.openai_model),
        _integration("ollama", "Ollama", bool(settings.ollama_base_url and settings.ollama_model), settings.ollama_model or "Optional local fallback"),
        _integration("music_assistant", "Music Assistant", _has_music_assistant(config, entity_blob), "Speaker mappings or MA entities detected"),
        _integration("browser_mod", "Browser Mod", "browser_mod" in entity_blob, "Detected in entity IDs" if "browser_mod" in entity_blob else "Optional panel routing"),
        _integration("frigate", "Frigate", "frigate" in entity_blob, "Detected in entity IDs" if "frigate" in entity_blob else "Optional camera events"),
        _integration("nest", "Nest/Google cameras", "nest" in entity_blob, "Detected in entity IDs" if "nest" in entity_blob else "Optional camera events"),
        _integration("tailscale", "Tailscale", "tailscale" in entity_blob, "Detected in entity IDs" if "tailscale" in entity_blob else "Optional HTTPS/access layer"),
        _integration("apple", "Apple/iCloud", any(k in entity_blob for k in ("icloud", "iphone", "ipad")), "Detected Apple device hints" if any(k in entity_blob for k in ("icloud", "iphone", "ipad")) else "Future account/calendar/contact layer"),
        _integration("nabu_casa", "Nabu Casa", "cloud" in entity_blob or "remote_ui" in entity_blob, "Detected cloud/remote UI hints" if "cloud" in entity_blob or "remote_ui" in entity_blob else "Optional HTTPS/remote voice path"),
    ]
    ready = [item for item in integrations if item["configured"]]
    return {
        "status": "ready" if len(ready) >= 3 else "partial",
        "configured": len(ready),
        "total": len(integrations),
        "integrations": integrations,
    }


async def build_jarvis_phase_82_86(config: AppConfig, version: str) -> dict[str, Any]:
    gaps = await build_capability_gap_scanner(config)
    onboarding = await build_onboarding_wizard_plan(config)
    diagnostics = await build_diagnostics_support_pack(config, version)
    backup = await build_backup_recovery_readiness(config)
    integrations = await build_integration_readiness_matrix(config)
    score = int(round((
        gaps["score"]
        + (100 if onboarding["status"] == "ready" else 75)
        + 100
        + (100 if backup["status"] == "ready" else 75)
        + int((integrations["configured"] / max(1, integrations["total"])) * 100)
    ) / 5))
    return {
        "status": "ready" if score >= 85 else "partial",
        "score": score,
        "capability_gaps": gaps,
        "onboarding": onboarding,
        "diagnostics": diagnostics,
        "backup_recovery": backup,
        "integration_matrix": integrations,
    }


def _gap(gap_id: str, title: str, severity: str, is_open: bool, fix: str) -> dict[str, Any]:
    return {"id": gap_id, "title": title, "severity": severity, "open": bool(is_open), "fix": fix}


def _gap_penalty(severity: str) -> int:
    return {"critical": 35, "high": 20, "normal": 10, "low": 4}.get(severity, 8)


def _step(step_id: str, title: str, detail: str, importance: str) -> dict[str, Any]:
    return {"id": step_id, "title": title, "detail": detail, "importance": importance, "required": importance == "required"}


def _step_state(step_id: str, open_gap_ids: set[str]) -> str:
    blockers = {
        "connect_ha": {"home_assistant_connection"},
        "sync_users": set(),
        "approve_discovery": {"pending_discovery"},
        "map_rooms": {"rooms"},
        "configure_security": {"security_pin"},
        "configure_voice": {"voice_sources", "wake_words"},
        "configure_music": {"music_assistant"},
        "upload_house_assets": {"dashboard_assets"},
        "test_commands": set(),
    }
    return "blocked" if blockers.get(step_id, set()) & open_gap_ids else "complete"


def _entity_card(entity: Any) -> dict[str, Any]:
    return {
        "entity_id": entity.entity_id,
        "name": entity.friendly_name or entity.entity_id,
        "domain": entity.domain,
        "state": entity.state,
        "available": entity.available,
    }


def _integration(integration_id: str, name: str, configured: bool, detail: str) -> dict[str, Any]:
    return {"id": integration_id, "name": name, "configured": bool(configured), "detail": detail}


def _has_music_assistant(config: AppConfig, entity_blob: str) -> bool:
    return (
        bool(config.devices.music_accounts)
        or any(speaker.music_assistant_entity_id for speaker in config.devices.speakers)
        or "music_assistant" in entity_blob
        or "mass_" in entity_blob
    )
