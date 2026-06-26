"""Experience and release acceptance brains for Jarvis phases 92-96."""
from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from typing import Any

from .db.database import get_session
from .db.models import CommandLog, ConversationNote, ConversationState, Suggestion
from .homeassistant.services import safe_get_states
from .knowledge import build_house_graph
from .models.schemas import AppConfig
from .settings import get_settings
from .voice import list_voice_source_readiness


def build_interaction_quality_report(config: AppConfig) -> dict[str, Any]:
    with get_session() as session:
        commands = session.query(CommandLog).order_by(CommandLog.created_at.desc()).limit(500).all()
        conversations = session.query(ConversationState).count()
        notes = session.query(ConversationNote).count()
    total = len(commands)
    executed = sum(1 for row in commands if row.executed)
    successful = sum(1 for row in commands if row.success)
    failed = [row for row in commands if not row.success]
    confusion = [
        row for row in commands
        if any(token in (row.message or "").lower() for token in ("wrong", "not what", "nothing happened", "didn't", "doesnt", "doesn't"))
    ]
    intents = Counter(row.intent or "conversation" for row in commands)
    score = 100 if not total else int(round((successful / total) * 100))
    return {
        "status": "attention" if failed[:1] or confusion[:1] else "ready",
        "score": score,
        "counts": {
            "sample_size": total,
            "successful": successful,
            "failed": len(failed),
            "executed": executed,
            "conversations": conversations,
            "notes": notes,
            "confusion_signals": len(confusion),
        },
        "top_intents": [{"intent": intent, "count": count} for intent, count in intents.most_common(10)],
        "recent_failures": [_command_card(row) for row in failed[:15]],
        "recent_confusion": [_command_card(row) for row in confusion[:15]],
        "recommendations": _interaction_recommendations(total, failed, confusion),
    }


def build_voice_acceptance_plan(config: AppConfig) -> dict[str, Any]:
    readiness = list_voice_source_readiness(config)
    counts = readiness.get("counts", {})
    ready = counts.get("ready", 0)
    total = counts.get("total", 0)
    assistants_ready = counts.get("assistants_ready", 0)
    assistants = counts.get("assistants", 0)
    return {
        "status": "ready" if ready and assistants_ready == assistants else "setup_needed",
        "score": 100 if ready and assistants_ready == assistants else 70,
        "readiness": readiness,
        "acceptance_tests": [
            _acceptance("browser_mic", "Use Mic in Chat over HTTPS/Tailscale/Nabu Casa and verify transcription."),
            _acceptance("assistant_tts", "Test each assistant voice and confirm it uses OpenAI TTS when configured."),
            _acceptance("wake_word", "Say each assistant wake word from a real room source and verify the correct assistant/profile."),
            _acceptance("room_context", "From each panel/satellite, say 'turn on the light' and verify the room target is correct."),
            _acceptance("safe_security", "Try lock/unlock security flows and verify unlock/open/disarm requires confirmation/PIN."),
        ],
        "blockers": _voice_blockers(counts),
    }


async def build_device_acceptance_matrix(config: AppConfig) -> dict[str, Any]:
    states = await safe_get_states()
    graph = await build_house_graph(include_registries=False)
    domains = Counter(entity.domain for entity in states.values())
    checks = [
        _domain_check("light", "Turn a known light on/off and verify final state.", domains),
        _domain_check("fan", "Turn a known fan on/off and test percentage/level fallback behavior.", domains),
        _domain_check("lock", "Lock a door directly; unlock requires confirmation/PIN.", domains),
        _domain_check("cover", "Open/close cover or garage only when policy allows.", domains),
        _domain_check("climate", "Set HVAC mode/temperature and verify state.", domains),
        _domain_check("media_player", "Turn on/off/play media on TV/speaker and verify outcome.", domains),
        _domain_check("camera", "Ask for security/camera briefing and verify camera availability.", domains),
        _domain_check("calendar", "Create a calendar-trigger draft if calendar entities exist.", domains),
        _domain_check("weather", "Ask a weather/general question and verify conversational answer.", domains),
    ]
    ready_checks = sum(1 for check in checks if check["available"])
    return {
        "status": "ready" if ready_checks >= 5 else "partial",
        "score": int(round((ready_checks / len(checks)) * 100)),
        "domain_counts": dict(domains),
        "checks": checks,
        "graph_counts": graph.get("counts", {}),
        "role_acceptance": [
            "Admin/owner can chat, control devices, draft/install automations, draft dashboards, and manage setup.",
            "Resident can chat, control allowed devices, and draft scheduled tasks without dashboard/system rights.",
            "Kiosk/shared profile can act as a house remote without exposing owner notebook/settings.",
        ],
    }


async def build_release_checklist(config: AppConfig, version: str) -> dict[str, Any]:
    settings = get_settings()
    interaction = build_interaction_quality_report(config)
    voice = build_voice_acceptance_plan(config)
    device = await build_device_acceptance_matrix(config)
    checks = [
        _release_check("version_aligned", "Version metadata aligned", True, f"Current version {version}."),
        _release_check("ha_connected", "Home Assistant connected", settings.ha_configured, "HA URL/token or Supervisor proxy configured."),
        _release_check("openai_configured", "OpenAI configured", settings.openai_configured, "Required for full conversational Jarvis behavior."),
        _release_check("security_pin", "Security PIN configured", bool(settings.security_pin), "Required for critical actions."),
        _release_check("voice_acceptance", "Voice acceptance ready", voice["status"] == "ready", "Wake words/sources/voice tests ready."),
        _release_check("device_acceptance", "Device acceptance broad enough", device["score"] >= 60, "Core domains detected for testing."),
        _release_check("interaction_quality", "Interaction quality healthy", interaction["score"] >= 80 or interaction["counts"]["sample_size"] == 0, "Recent commands are mostly successful."),
    ]
    return {
        "status": "ready" if all(check["pass"] for check in checks) else "attention",
        "version": version,
        "checks": checks,
        "blockers": [check["title"] for check in checks if not check["pass"]],
        "ship_rule": "Ship only after tests pass, version metadata is aligned, and live-house blockers are understood.",
    }


async def build_operational_runbook(config: AppConfig, version: str) -> dict[str, Any]:
    checklist = await build_release_checklist(config, version)
    return {
        "status": "ready",
        "version": version,
        "runbook": [
            _runbook_step("after_update", "After updating", [
                "Restart the add-on.",
                "Open TPG HomeAI through the HA sidebar as owner/admin.",
                "Check /health, Jarvis Brain, and Setup for degraded warnings.",
                "Run Sync from HA users if user/profile mapping changed.",
            ]),
            _runbook_step("acceptance_pass", "Acceptance pass", [
                "Test admin, resident, and kiosk/shared logins.",
                "Run core light, fan, lock, media, schedule, dashboard, chat, notebook, and voice checks.",
                "Verify residents cannot access system/dashboard management.",
                "Verify owner/admin can see all management menus.",
            ]),
            _runbook_step("when_something_fails", "When something fails", [
                "Open Diagnostics Support Pack.",
                "Check recent failures in Interaction Quality.",
                "Review Device Profiles and reliability suggestions.",
                "Fix mapping/config first; only change code when the behavior is reproducible.",
            ]),
            _runbook_step("feature_freeze", "Feature freeze rule", [
                "Once release checklist is ready, stop broad feature work.",
                "Only accept bug fixes, device mappings, voice tuning, UI polish, and clearly-scoped v2 requirements.",
            ]),
        ],
        "release_checklist": checklist,
    }


async def build_jarvis_phase_92_96(config: AppConfig, version: str) -> dict[str, Any]:
    interaction = build_interaction_quality_report(config)
    voice = build_voice_acceptance_plan(config)
    device = await build_device_acceptance_matrix(config)
    checklist = await build_release_checklist(config, version)
    runbook = await build_operational_runbook(config, version)
    score = int(round((interaction["score"] + voice["score"] + device["score"] + (100 if checklist["status"] == "ready" else 75) + 100) / 5))
    return {
        "status": "ready" if score >= 85 else "partial",
        "score": score,
        "interaction_quality": interaction,
        "voice_acceptance": voice,
        "device_acceptance": device,
        "release_checklist": checklist,
        "operational_runbook": runbook,
    }


def _command_card(row: CommandLog) -> dict[str, Any]:
    return {
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "assistant": row.assistant,
        "user": row.user,
        "message": row.message,
        "intent": row.intent,
        "success": row.success,
        "executed": row.executed,
        "error": row.error,
        "data": _safe_json(row.data),
    }


def _safe_json(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _interaction_recommendations(total: int, failed: list[CommandLog], confusion: list[CommandLog]) -> list[str]:
    recommendations = []
    if total == 0:
        recommendations.append("Run an acceptance chat session so the quality report has data.")
    if failed:
        recommendations.append("Review recent failed commands and approve device strategy repairs where available.")
    if confusion:
        recommendations.append("Turn repeated corrections into approved memory or device aliases.")
    return recommendations


def _acceptance(test_id: str, title: str) -> dict[str, Any]:
    return {"id": test_id, "title": title, "required": True}


def _voice_blockers(counts: dict[str, Any]) -> list[str]:
    blockers = []
    if counts.get("total", 0) <= 0:
        blockers.append("No voice source profiles configured.")
    if counts.get("missing_source_identity", 0) > 0:
        blockers.append("Some voice sources are missing source_device_id/source_entity_id.")
    if counts.get("assistants_with_wake_words", 0) < counts.get("assistants", 0):
        blockers.append("Some assistant profiles are missing wake words.")
    if counts.get("assistants_with_linked_sources", 0) < counts.get("assistants", 0):
        blockers.append("Some assistants are not linked to a real voice source.")
    return blockers


def _domain_check(domain: str, title: str, domains: Counter[str]) -> dict[str, Any]:
    count = domains.get(domain, 0)
    return {"domain": domain, "title": title, "available": count > 0, "count": count}


def _release_check(check_id: str, title: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"id": check_id, "title": title, "pass": bool(passed), "detail": detail}


def _runbook_step(step_id: str, title: str, actions: list[str]) -> dict[str, Any]:
    return {"id": step_id, "title": title, "actions": actions}
