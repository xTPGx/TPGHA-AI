"""AI-first chat routing for the Jarvis-style assistant runtime.

The chat surface should feel like a normal AI agent first, with Home Assistant
available as a guarded tool. This module decides whether a chat turn should go
straight to the conversational model or through the home-action router.
"""
from __future__ import annotations

import re
from typing import Any


_CONTROL_VERBS = (
    "turn", "switch", "power", "set", "dim", "brighten", "lock", "unlock",
    "open", "close", "shut", "start", "stop", "pause", "resume", "mute",
    "unmute", "arm", "disarm", "raise", "lower", "increase", "decrease",
    "show", "pull up", "play",
)

_HOME_NOUNS = (
    "light", "lights", "fan", "fans", "switch", "switches", "tv", "television",
    "display", "screen", "speaker", "music", "spotify", "playlist", "camera",
    "door", "lock", "garage", "alarm", "thermostat", "climate", "ac", "heat",
    "cover", "blind", "shade", "vacuum",
)

_SCHEDULE_RE = re.compile(
    r"\b("
    r"schedule|scheduled task|automation|automate|routine|timer|sleep timer|"
    r"remind|reminder|every|each|when|whenever|sunset|sunrise"
    r")\b|"
    r"\bat\s+\d{1,2}(:\d{2})?\s*(am|pm)?\b|"
    r"\bin\s+\d+\s*(minutes?|mins?|hours?|hrs?)\b"
)

_DASHBOARD_ACTIONS = (
    "build a dashboard", "create a dashboard", "make a dashboard",
    "generate a dashboard", "draft a dashboard", "edit dashboard",
    "redesign dashboard", "install dashboard",
)

_CONVERSATIONAL_MARKERS = (
    "what do you think", "what should", "where should", "should i", "should we",
    "can you review", "review what", "review my", "give me advice", "advice",
    "brainstorm", "help me think", "think through", "recommend", "recommendation",
    "input on", "opinion", "why", "how do", "how should", "explain",
    "tell me about", "what is", "what are", "weather", "forecast",
    "good morning", "good night", "how are you", "let's chat", "lets chat",
)


def chat_route_decision(message: str, *, has_attachments: bool = False) -> dict[str, Any]:
    """Return the intended runtime path for a chat turn.

    ``agent_first`` means the user is talking to the AI as an advisor/assistant.
    ``home_action`` means the user is asking TPG HomeAI to change/query the
    house, create automation, or draft/install dashboards.
    """

    raw = (message or "").strip()
    text = _normalize(raw)
    if not text:
        return _decision("agent_first", "empty_or_attachment", confidence=0.9)
    if has_attachments:
        return _decision("agent_first", "image_or_file_context", confidence=1.0)

    if _has_dashboard_action(text):
        return _decision("home_action", "dashboard_creation_or_edit", confidence=0.92)
    if _has_schedule_action(text):
        return _decision("home_action", "schedule_or_automation_request", confidence=0.92)
    if _is_direct_home_command(text):
        return _decision("home_action", "direct_home_control_or_status", confidence=0.95)

    # Questions and design/advice turns should reach the GPT-style agent even
    # when they mention home devices. Example: "where should I put smart
    # switches?" must be advice, not a failed switch command.
    if _has_conversational_marker(text) or raw.endswith("?"):
        return _decision("agent_first", "question_or_advice_turn", confidence=0.9)

    return _decision("agent_first", "default_conversation", confidence=0.8)


def _decision(path: str, reason: str, *, confidence: float) -> dict[str, Any]:
    return {
        "runtime": "ai_first",
        "path": path,
        "reason": reason,
        "confidence": confidence,
    }


def _normalize(message: str) -> str:
    return re.sub(r"\s+", " ", message.lower().replace("’", "'")).strip()


def _has_conversational_marker(text: str) -> bool:
    return any(marker in text for marker in _CONVERSATIONAL_MARKERS)


def _has_dashboard_action(text: str) -> bool:
    return "dashboard" in text and any(marker in text for marker in _DASHBOARD_ACTIONS)


def _has_schedule_action(text: str) -> bool:
    if not _SCHEDULE_RE.search(text):
        return False
    return any(verb in text for verb in _CONTROL_VERBS) or any(noun in text for noun in _HOME_NOUNS)


def _is_direct_home_command(text: str) -> bool:
    has_verb = any(re.search(rf"\b{re.escape(verb)}\b", text) for verb in _CONTROL_VERBS)
    if not has_verb:
        return False
    has_home_noun = any(re.search(rf"\b{re.escape(noun)}\b", text) for noun in _HOME_NOUNS)
    if not has_home_noun:
        return False
    # Let advice questions win unless they explicitly say to create/change/run.
    if _has_conversational_marker(text) and not re.search(r"\b(create|build|make|set|turn|switch|lock|unlock|open|close|play|stop|show)\b", text):
        return False
    return True
