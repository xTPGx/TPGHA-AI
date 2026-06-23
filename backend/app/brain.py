"""Jarvis-style brain readiness map.

This module turns the system's current capabilities into a live layer map. It
does not claim the house is magically finished; it shows which brain layers are
usable now, which are partial, and what the next build target is.
"""
from __future__ import annotations

from typing import Any

from .ai.client import get_ai_client
from .db.database import get_session
from .db.models import CommandLog, ConversationState, MemoryItem, Suggestion
from .discovery import capabilities
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
            "status": "ready" if counts.get("rooms", 0) and voice_sources else "partial",
            "score": 90 if counts.get("rooms", 0) and voice_sources else 64,
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
            "status": "ready" if settings.security_pin else "partial",
            "score": 86 if settings.security_pin else 70,
            "evidence": [
                "Critical confirmations can require a configured security PIN.",
                "User permission checks still run before confirmation tokens are created.",
                f"Security PIN configured: {bool(settings.security_pin)}.",
            ],
            "next": "Add trusted-device and outside/guest voice policies.",
        },
        {
            "id": "capability_graph",
            "title": "Real Device Capability Graph",
            "status": "ready" if controllable else "partial",
            "score": 90 if controllable else 55,
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
            "status": "ready" if conversation_count or command_count else "partial",
            "score": 82 if conversation_count or command_count else 60,
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
            "status": "ready" if settings.openai_configured else "partial",
            "score": 92 if settings.openai_configured else 78,
            "evidence": [
                "Browser mic input is available in Chat.",
                "Configured assistant voice profiles can use OpenAI TTS with browser fallback.",
                "Reply routing can target browser, quiet mode, explicit media player, or room speaker.",
                "Voice Settings exposes profile readiness, catalog, preview, and test playback.",
                "Home Assistant Assist can forward conversation to TPG HomeAI.",
                f"OpenAI TTS configured: {settings.openai_configured}.",
            ],
            "next": "Connect real wake-word satellites and assign each a source_device_id.",
        },
        {
            "id": "proactive_suggestions",
            "title": "Proactive Suggestions + Approval Inbox",
            "status": "ready" if pending_suggestions else "partial",
            "score": 80 if pending_suggestions else 68,
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
            "score": 91,
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
            "score": 84,
            "evidence": [
                "House-state endpoint summarizes presence, modes, room activity, and attention items.",
                "House Brain UI shows security, energy, media, maintenance, rooms, assistants, and tablet panels.",
                "Recommendations are generated from live HA state without directly executing actions.",
            ],
            "next": "Persist learned house modes and add per-mode policies.",
        },
        {
            "id": "ai_hybrid",
            "title": "OpenAI / Local AI Hybrid",
            "status": "ready" if ai.using_openai else "partial",
            "score": 88 if ai.using_openai else 58,
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


def _controllable_count(graph: dict[str, Any]) -> int:
    return sum(len(d.get("controllable_entities", [])) for d in graph.get("devices", []))


def _diagnostic_count(graph: dict[str, Any]) -> int:
    return sum(len(d.get("diagnostic_entities", [])) for d in graph.get("devices", []))
