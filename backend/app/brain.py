"""Jarvis-style brain readiness map.

This module turns the system's current capabilities into a live layer map. It
does not claim the house is magically finished; it shows which brain layers are
usable now, which are partial, and what the next build target is.
"""
from __future__ import annotations

from typing import Any

from .ai.client import get_ai_client
from .config_loader import config_error, get_config
from .db.database import get_session
from .db.models import CommandLog, ConversationState, MemoryItem, Suggestion
from .discovery import capabilities
from .house_state import build_mode_brain, build_wake_word_deployment
from .router.action_policy import CONFIDENCE_REVIEW_THRESHOLD
from .settings import get_settings


def build_brain_layers(graph: dict[str, Any], health: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a seven-layer readiness map for the real-house brain."""
    with get_session() as session:
        command_count = session.query(CommandLog).count()
        conversation_count = session.query(ConversationState).count()
        approved_memories = session.query(MemoryItem).filter(
            MemoryItem.status == "approved"
        ).count()
        pending_suggestions = session.query(Suggestion).filter(
            Suggestion.status.in_(["suggested", "draft", "edited"])
        ).count()

    settings = get_settings()
    ai = get_ai_client()
    providers = ai.provider_status()
    counts = graph.get("counts", {})
    physical = graph.get("physical_devices", [])
    voice_sources = graph.get("voice_sources", [])
    pending = int(graph.get("pending_approvals") or 0)
    unavailable = int(graph.get("unavailable_devices") or 0)
    controllable = _controllable_count(graph)
    diagnostic = _diagnostic_count(graph)
    config = get_config()
    mode_brain = build_mode_brain(config)
    wake_word = build_wake_word_deployment(config)
    room_context_ready = counts.get("rooms", 0) > 0 and bool(voice_sources)
    security_ready = bool(settings.security_pin)
    capability_ready = controllable > 0 and pending == 0
    conversation_ready = bool(conversation_count or command_count)
    voice_ready = bool(settings.openai_configured)
    wake_ready = bool(wake_word.get("counts", {}).get("ready", 0))
    mode_ready = bool(mode_brain.get("configured_modes"))
    ai_ready = bool(ai.using_openai)

    layers = [
        {
            "id": "policy_brain",
            "title": "Intent Confidence + Policy Brain",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Backend returns data.policy for command and preview responses.",
                f"Confidence review threshold is {CONFIDENCE_REVIEW_THRESHOLD:.2f}.",
                "Security/access actions remain confirmation-gated.",
            ],
            "next": "Add per-user risk preferences and PIN-backed unlock confirmation.",
        },
        {
            "id": "room_context",
            "title": "Room-Aware Voice Context",
            "status": "ready" if room_context_ready else "partial",
            "score": 100 if room_context_ready else 64,
            "evidence": [
                "Commands accept room, source_device_id, and source_entity_id context.",
                "Router applies room context to generic targets like light, fan, TV, and speaker.",
                f"{counts.get('rooms', 0)} configured rooms available for context resolution.",
                f"{len(voice_sources)} configured voice source profiles available.",
            ],
            "next": "Bind real HA Assist satellite device IDs as they are installed.",
        },
        {
            "id": "security_identity",
            "title": "PIN + User Identity Security",
            "status": "ready" if security_ready else "partial",
            "score": 100 if security_ready else 70,
            "evidence": [
                "Critical confirmations can require a configured security PIN.",
                "User permission checks still run before confirmation tokens are created.",
                f"Security PIN configured: {bool(settings.security_pin)}.",
                f"{len(mode_brain.get('source_policy', []))} voice source trust policies generated.",
            ],
            "next": "Add per-user location/trusted-device scoring for outside voice requests.",
        },
        {
            "id": "capability_graph",
            "title": "Real Device Capability Graph",
            "status": "ready" if capability_ready else "partial",
            "score": 100 if capability_ready else (75 if controllable else 55),
            "evidence": [
                f"{len(capabilities.DOMAIN_CAPABILITIES)} HA domains mapped.",
                f"{controllable} controllable entities and {diagnostic} diagnostic entities seen.",
                f"{len(physical)} physical device groups built from HA registries/entities.",
                f"{pending} pending approvals and {unavailable} unavailable entities.",
            ],
            "next": "Use HA device registry IDs to merge every phone/TV/fan into physical device cards.",
        },
        {
            "id": "conversation_memory",
            "title": "Conversational Memory + Corrections",
            "status": "ready" if conversation_ready else "partial",
            "score": 100 if conversation_ready else 60,
            "evidence": [
                f"{conversation_count} active short-term conversation contexts.",
                f"{command_count} audited commands available for explanations.",
                f"{approved_memories} approved long-term memories.",
            ],
            "next": "Automatically draft memory from repeated corrections and user preferences.",
        },
        {
            "id": "voice_layer",
            "title": "Voice Layer",
            "status": "ready" if voice_ready else "partial",
            "score": 100 if voice_ready else 78,
            "evidence": [
                "Browser mic input is available in Chat.",
                "Assistants own wake-word identity; Voice Sources deploy that assistant into rooms.",
                "Configured assistant voice profiles can use OpenAI TTS with browser fallback.",
                "Reply routing can target browser, quiet mode, explicit media player, or room speaker.",
                "Assistant profiles expose voice selection, OpenAI TTS readiness, catalog, preview, and test playback.",
                "Home Assistant Assist can forward conversation to TPG HomeAI.",
                f"OpenAI TTS configured: {settings.openai_configured}.",
            ],
            "next": "Install HA Assist satellites and paste their real source IDs into voice_sources.",
        },
        {
            "id": "wake_word_deployment",
            "title": "Wake Word Deployment",
            "status": "ready" if wake_ready else "partial",
            "score": 100 if wake_ready else 66,
            "evidence": [
                f"{wake_word.get('counts', {}).get('assistants_with_wake_words', 0)}/{wake_word.get('counts', {}).get('assistants', 0)} assistants have wake words configured.",
                f"{wake_word.get('counts', {}).get('assistants_with_linked_sources', 0)}/{wake_word.get('counts', {}).get('assistants', 0)} assistants are linked to real voice sources.",
                f"{wake_word.get('counts', {}).get('total', 0)} voice source profiles configured.",
                f"{wake_word.get('counts', {}).get('ready', 0)} voice sources ready for room-aware routing.",
                f"{wake_word.get('counts', {}).get('missing_source_identity', 0)} sources still need source_device_id/source_entity_id.",
                f"{wake_word.get('counts', {}).get('rooms_without_voice_source', 0)} rooms still need satellites/panels.",
            ],
            "next": "Bind each physical mic/panel/satellite to its HA source identity.",
        },
        {
            "id": "proactive_suggestions",
            "title": "Proactive Suggestions + Approval Inbox",
            "status": "ready",
            "score": 100,
            "evidence": [
                f"{pending_suggestions} active proactive suggestions or drafts.",
                "Suggestion generation, approve, ignore, and automation install endpoints exist.",
                "Security, discovery, maintenance, dashboard, and sleep-timer proposals are approval-first.",
            ],
            "next": "Add schedule mining from command history for time-of-day suggestions.",
        },
        {
            "id": "ha_native_ui",
            "title": "HA Native UI + Dashboard Builder",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Ingress/sidebar add-on UI is enabled.",
                "Custom integration exposes services, sensors, buttons, notifications, and dashboard draft/install.",
                f"{counts.get('rooms', 0)} configured rooms can be used for dashboard generation.",
                "Dashboard drafts include tablet/profile and voice-panel views.",
            ],
            "next": "Add drag-and-drop dashboard editing.",
        },
        {
            "id": "house_state",
            "title": "House State Brain",
            "status": "ready",
            "score": 100,
            "evidence": [
                "House-state endpoint summarizes presence, modes, room activity, and attention items.",
                "House Brain UI shows security, energy, media, maintenance, rooms, assistants, and tablet panels.",
                f"{len(mode_brain.get('active_modes', []))} active mode(s) inferred now.",
                "Recommendations are generated from live HA state without directly executing actions.",
            ],
            "next": "Add UI controls to manually pin/clear modes and schedule mode windows.",
        },
        {
            "id": "mode_brain",
            "title": "Mode Brain",
            "status": "ready" if mode_ready else "partial",
            "score": 100 if mode_ready else 60,
            "evidence": [
                f"{len(mode_brain.get('configured_modes', []))} configured house modes.",
                f"Active reply policy: {mode_brain.get('policy', {}).get('reply_mode', 'auto')}.",
                f"{len(mode_brain.get('policy', {}).get('confirmation_keywords', []))} confirmation keywords in the current policy.",
                "Mode policy is exposed through /brain/modes and Home Assistant services.",
            ],
            "next": "Let users pin modes from Chat, HA services, and dashboard controls.",
        },
        {
            "id": "ai_hybrid",
            "title": "OpenAI / Local AI Hybrid",
            "status": "ready" if ai_ready else "partial",
            "score": 100 if ai_ready else 58,
            "evidence": [
                "OpenAI tool selection is available." if ai.using_openai else "Fallback parser is active.",
                f"OpenAI configured: {settings.openai_configured}.",
                f"Ollama configured: {providers['providers']['ollama']['configured']}.",
            ],
            "next": "Add optional Ollama-compatible local model provider with OpenAI as high-reasoning primary.",
        },
    ]

    overall = int(round(sum(layer["score"] for layer in layers) / len(layers)))
    return {
        "overall_score": overall,
        "status": "ready" if overall >= 85 else "building",
        "layers": layers,
        "summary": {
            "rooms": counts.get("rooms", 0),
            "devices": counts.get("devices", 0),
            "physical_devices": len(physical),
            "entities": counts.get("entities", 0),
            "controllable_entities": controllable,
            "diagnostic_entities": diagnostic,
            "pending_approvals": pending,
            "unavailable_devices": unavailable,
        },
        "health": health or {},
    }


def build_completion_status(graph: dict[str, Any], health: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the hard stop criteria for Jarvis v1.

    The important distinction is software completeness versus house deployment
    completeness. The repo can be v1-ready before every real microphone,
    display, and HA source id is installed in the user's house.
    """

    config = get_config()
    settings = get_settings()
    ai = get_ai_client()
    providers = ai.provider_status()
    mode_brain = build_mode_brain(config)
    wake_word = build_wake_word_deployment(config)
    counts = graph.get("counts", {})
    pending = int(graph.get("pending_approvals") or 0)
    unavailable = int(graph.get("unavailable_devices") or 0)
    controllable = _controllable_count(graph)
    diagnostic = _diagnostic_count(graph)
    active_voice = wake_word.get("counts", {})
    cfg_err = config_error()
    ha_health = (health or {}).get("home_assistant", {})
    backend_health = (health or {}).get("backend", {})
    openai_health = (health or {}).get("openai", {})

    gates = [
        _gate(
            "core_runtime",
            "Core Runtime + Add-on Lifecycle",
            True,
            bool(backend_health.get("online", True)) and cfg_err is None,
            [
                "Backend starts without crashing.",
                "Config validates cleanly.",
                "Add-on metadata, Docker label, backend package, and integration version are aligned.",
            ],
            [] if cfg_err is None else [f"Fix config validation error: {cfg_err}"],
            "Health, config reload, ingress, and add-on update metadata are stable.",
        ),
        _gate(
            "ha_bridge",
            "Home Assistant Bridge",
            True,
            bool(settings.ha_configured) and bool(ha_health.get("reachable", True)),
            [
                f"HA URL configured: {settings.ha_configured}.",
                f"HA reachable: {ha_health.get('reachable', 'unknown')}.",
                "Custom integration exposes commands, sensors, services, notifications, and sidebar UI.",
            ],
            _missing([
                (not settings.ha_configured, "Configure Home Assistant URL/token or Supervisor proxy."),
                (ha_health.get("reachable") is False, "Fix HA reachability from the add-on/container."),
            ]),
            "The backend can read HA state and execute vetted HA services.",
        ),
        _gate(
            "command_brain",
            "Natural Language Command Brain",
            True,
            True,
            [
                "OpenAI tool selection, deterministic fallback, room context, corrections, and audit explainability exist.",
                "Safe actions can auto-execute when confidence and policy allow.",
                "Sensitive actions are confirmation-gated.",
            ],
            [],
            "Lights, fans, locks, covers, media players, climate, cameras, timers, and routines route through guarded tools.",
        ),
        _gate(
            "security",
            "Security + Identity",
            True,
            bool(settings.security_pin),
            [
                "Unlock/open/disarm/garage/security actions are confirmation-gated.",
                "User permissions are checked before confirmations are created.",
                f"Security PIN configured: {bool(settings.security_pin)}.",
            ],
            _missing([
                (not settings.security_pin, "Set security_pin in add-on options for PIN-backed critical confirmations."),
            ]),
            "Security-disabling actions need confirmation and PIN; security-enabling actions can stay one-step.",
        ),
        _gate(
            "device_graph",
            "Real Device Capability Graph",
            True,
            counts.get("rooms", 0) > 0 and controllable > 0 and pending == 0,
            [
                f"{counts.get('rooms', 0)} rooms configured.",
                f"{controllable} controllable entities and {diagnostic} diagnostic entities mapped.",
                f"{pending} pending approvals and {unavailable} unavailable entities.",
            ],
            _missing([
                (counts.get("rooms", 0) <= 0, "Configure rooms."),
                (controllable <= 0, "Approve controllable HA entities."),
                (pending > 0, f"Approve, map, or ignore {pending} pending discovery items."),
            ]),
            "Every important real device is either approved, intentionally ignored, or safely diagnostic-only.",
        ),
        _gate(
            "voice_assist",
            "Voice, TTS, and Wake Word Deployment",
            True,
            bool(settings.openai_configured)
            and active_voice.get("total", 0) > 0
            and active_voice.get("missing_source_identity", 0) == 0,
            [
                f"OpenAI configured: {settings.openai_configured}.",
                f"{active_voice.get('assistants_with_wake_words', 0)}/{active_voice.get('assistants', 0)} assistants have wake words configured.",
                f"{active_voice.get('assistants_with_linked_sources', 0)}/{active_voice.get('assistants', 0)} assistants are linked to real voice sources.",
                f"{active_voice.get('total', 0)} voice sources configured.",
                f"{active_voice.get('missing_source_identity', 0)} voice sources missing source identity.",
                f"{active_voice.get('rooms_without_voice_source', 0)} rooms without a source.",
            ],
            _missing([
                (not settings.openai_configured, "Configure OpenAI API key for real assistant reasoning/TTS."),
                (active_voice.get("total", 0) <= 0, "Add at least one real microphone/panel/HA Assist voice source."),
                (active_voice.get("missing_source_identity", 0) > 0, "Paste real HA Assist/Browser Mod source IDs into voice_sources."),
            ]),
            "You can talk to the house from real microphones/panels and get natural replies in the right place.",
        ),
        _gate(
            "memory_learning",
            "Memory + Learning",
            True,
            True,
            [
                "Short-term conversation context is stored.",
                "Command audit supports explanation and correction follow-ups.",
                "Long-term memories require approval before becoming active context.",
            ],
            [],
            "The system learns preferences through approved memory, not unsafe hidden mutation.",
        ),
        _gate(
            "proactive_suggestions",
            "Proactive Suggestions + Approval Inbox",
            True,
            True,
            [
                "Monitor scans can draft security, maintenance, sleep-timer, dashboard, and routine suggestions.",
                "Automation drafts are approval-first.",
                "Suggestion approve/ignore/install endpoints exist.",
            ],
            [],
            "The assistant can suggest useful actions without silently changing the house.",
        ),
        _gate(
            "dashboards_ui",
            "Native HA UI + Dashboards",
            True,
            True,
            [
                "Ingress/sidebar UI is enabled.",
                "Dashboard builder can draft and install Lovelace YAML.",
                "Browser Mod/tablet profile data exists for room dashboards.",
            ],
            [],
            "The system can be managed from Home Assistant without only using an external web UI.",
        ),
        _gate(
            "ai_hybrid",
            "OpenAI / Local AI Hybrid",
            False,
            bool(providers.get("providers", {}).get("ollama", {}).get("configured")),
            [
                f"OpenAI active: {ai.using_openai}.",
                f"Ollama configured: {providers.get('providers', {}).get('ollama', {}).get('configured')}.",
                "Fallback parser remains available for deterministic offline controls.",
            ],
            ["Optional: configure Ollama for local fallback on the TPG AI server."],
            "OpenAI stays primary, local AI can be a privacy/offline fallback.",
        ),
    ]

    required = [gate for gate in gates if gate["required"]]
    optional = [gate for gate in gates if not gate["required"]]
    required_ready = sum(1 for gate in required if gate["status"] == "complete")
    optional_ready = sum(1 for gate in optional if gate["status"] == "complete")
    software_ready = all(gate["software_ready"] for gate in required)
    deployment_ready = all(gate["status"] == "complete" for gate in required)
    score = int(round(sum(gate["score"] for gate in gates) / len(gates)))
    blockers = [
        blocker
        for gate in required
        for blocker in gate["blockers"]
        if gate["status"] != "complete"
    ]

    return {
        "version_target": "Jarvis v1",
        "status": "complete" if deployment_ready else ("software_ready" if software_ready else "building"),
        "overall_score": score,
        "software_ship_complete": software_ready,
        "house_deployment_complete": deployment_ready,
        "required_complete": required_ready,
        "required_total": len(required),
        "optional_complete": optional_ready,
        "optional_total": len(optional),
        "blockers": blockers,
        "complete_spot": {
            "software": (
                "Stop adding repo features when every required gate has software support, "
                "tests pass, and only house-specific configuration remains."
            ),
            "deployment": (
                "Call Jarvis v1 complete when required gates are complete in the live house: "
                "HA reachable, security PIN set, pending approvals cleared, OpenAI configured, "
                "and real voice source IDs mapped."
            ),
            "after_complete": (
                "After that, freeze feature work and only do bug fixes, device mapping, voice tuning, "
                "and small quality-of-life polish until a clear v2 requirement appears."
            ),
        },
        "gates": gates,
    }


def _gate(identifier: str, title: str, required: bool, complete: bool,
          evidence: list[str], blockers: list[str], done_when: str) -> dict[str, Any]:
    return {
        "id": identifier,
        "title": title,
        "required": required,
        "status": "complete" if complete else "incomplete",
        "score": 100 if complete else (75 if required else 60),
        "software_ready": bool(evidence),
        "evidence": evidence,
        "blockers": blockers if not complete else [],
        "done_when": done_when,
    }


def _missing(items: list[tuple[bool, str]]) -> list[str]:
    return [message for condition, message in items if condition]


def _controllable_count(graph: dict[str, Any]) -> int:
    return sum(len(d.get("controllable_entities", [])) for d in graph.get("devices", []))


def _diagnostic_count(graph: dict[str, Any]) -> int:
    return sum(len(d.get("diagnostic_entities", [])) for d in graph.get("devices", []))
