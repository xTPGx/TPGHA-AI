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
    counts = graph.get("counts", {})
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
            "id": "capability_graph",
            "title": "Real Device Capability Graph",
            "status": "ready" if controllable else "partial",
            "score": 90 if controllable else 55,
            "evidence": [
                f"{len(capabilities.DOMAIN_CAPABILITIES)} HA domains mapped.",
                f"{controllable} controllable entities and {diagnostic} diagnostic entities seen.",
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
            "status": "partial",
            "score": 65,
            "evidence": [
                "Browser mic input and speech replies are available in Chat.",
                "Home Assistant Assist can forward conversation to TPG HomeAI.",
                "Wake-word satellites and room-aware microphones are not managed here yet.",
            ],
            "next": "Add wake-word/satellite setup docs plus room-aware voice context from HA Assist devices.",
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
            "score": 86,
            "evidence": [
                "Ingress/sidebar add-on UI is enabled.",
                "Custom integration exposes services, sensors, buttons, notifications, and dashboard draft/install.",
                f"{counts.get('rooms', 0)} configured rooms can be used for dashboard generation.",
            ],
            "next": "Add a visual dashboard editor with Browser Mod tablet profiles.",
        },
        {
            "id": "ai_hybrid",
            "title": "OpenAI / Local AI Hybrid",
            "status": "ready" if ai.using_openai else "partial",
            "score": 88 if ai.using_openai else 58,
            "evidence": [
                "OpenAI tool selection is available." if ai.using_openai else "Fallback parser is active.",
                f"OpenAI configured: {settings.openai_configured}.",
                "Local Ollama routing is not configured in the add-on yet.",
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
