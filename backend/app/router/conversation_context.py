"""Short-term conversation context for pronouns, corrections, and follow-ups."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from ..ai.client import ToolCall
from ..db.database import get_session
from ..db.models import ConversationState
from ..models.results import ActionResult

_PRONOUN_RE = re.compile(r"\b(it|that|this|them|those|there)\b", re.I)
_CORRECTION_RE = re.compile(
    r"\b(no|actually|correction|i meant|i said|not that|not the)\b", re.I
)
_ON_RE = re.compile(r"\b(turn|switch|power)\s+on\b|\bon\b|\benable\b", re.I)
_OFF_RE = re.compile(r"\b(turn|switch|power|shut)\s+off\b|\boff\b|\bdisable\b", re.I)
_PCT_RE = re.compile(r"\b(\d{1,3})\s*%?\b")
_FAN_WORDS = re.compile(r"\bfan\b", re.I)
_LIGHT_WORDS = re.compile(r"\blight(s)?\b|\blamp\b", re.I)
_SPEED_WORDS = re.compile(r"\b(speed|level|power|faster|slower|up|down|higher|lower)\b", re.I)
_FAN_LEVEL_WORDS = {
    "minimum": 10, "min": 10, "lowest": 10, "low": 25,
    "medium": 50, "mid": 50, "normal": 50,
    "high": 75, "max": 100, "maximum": 100, "full": 100,
    "turbo": 100, "boost": 100,
}
_FAN_LEVEL_NUMBER_WORDS = {
    "one": 20, "two": 40, "three": 60, "four": 80, "five": 100,
}


def context_key(assistant: str, user: Optional[str], conversation_id: Optional[str]) -> str:
    conv = conversation_id or "default"
    return f"{assistant or 'assistant'}:{user or 'user'}:{conv}"


def load_context(assistant: str, user: Optional[str],
                 conversation_id: Optional[str]) -> Optional[ConversationState]:
    with get_session() as session:
        return session.get(ConversationState, context_key(assistant, user, conversation_id))


def save_context(
    *,
    assistant: str,
    user: Optional[str],
    conversation_id: Optional[str],
    message: str,
    result: ActionResult,
) -> None:
    target = _target_from_result(result)
    if not target:
        return
    with get_session() as session:
        key = context_key(assistant, user, conversation_id)
        row = session.get(ConversationState, key)
        if row is None:
            row = ConversationState(key=key)
            session.add(row)
        row.updated_at = datetime.now(timezone.utc)
        row.assistant = assistant or ""
        row.user = user or ""
        row.conversation_id = conversation_id or "default"
        row.last_message = message
        row.last_intent = result.intent or ""
        row.last_action = _action_from_result(result)
        row.last_target = target
        row.last_label = str(result.resolved.get("label") or target)
        row.last_entity_id = _entity_from_result(result)
        row.last_domain = _domain_from_result(result)
        session.commit()


def context_tool_call(message: str, ctx: Optional[ConversationState]) -> Optional[ToolCall]:
    """Return a context-resolved tool call for follow-ups like "turn it off"."""
    if ctx is None or not ctx.last_target:
        return None

    text = message.lower().strip()
    if _is_explicit_music_request(text):
        return None
    has_pronoun = bool(_PRONOUN_RE.search(text))
    correction = bool(_CORRECTION_RE.search(text))
    fan_speed_followup = (
        not has_pronoun
        and not correction
        and ctx.last_domain == "fan"
        and bool(_FAN_WORDS.search(text))
        and bool(_SPEED_WORDS.search(text))
    )
    if not has_pronoun and not correction and not fan_speed_followup:
        return None

    target = _corrected_target(text, ctx) if correction else ctx.last_target
    domain = _domain_hint(text, ctx)
    action = _action_hint(text) or (ctx.last_action if correction else "")
    percentage = _fan_percentage(text) if domain == "fan" else _percentage(text)

    if percentage is not None:
        if domain == "fan":
            return ToolCall("set_fan_percentage", {
                "target": target,
                "percentage": percentage,
            }, source="conversation_context")
        if domain == "light":
            return ToolCall("control_device", {
                "target": target,
                "action": "set_brightness",
                "value": percentage,
            }, source="conversation_context")

    if action == "turn_on":
        if domain == "fan":
            return ToolCall("turn_on_fan", {"target": target}, source="conversation_context")
        if domain == "light":
            return ToolCall("turn_on_light", {"target": target}, source="conversation_context")
        return ToolCall("control_device", {"target": target, "action": "turn_on"},
                        source="conversation_context")
    if action == "turn_off":
        if domain == "fan":
            return ToolCall("turn_off_fan", {"target": target}, source="conversation_context")
        if domain == "light":
            return ToolCall("turn_off_light", {"target": target}, source="conversation_context")
        return ToolCall("control_device", {"target": target, "action": "turn_off"},
                        source="conversation_context")

    return None


def _is_explicit_music_request(text: str) -> bool:
    return text.startswith("play ") and any(
        word in text
        for word in ("music", "song", "track", "album", "artist", "playlist", "spotify")
    )


def _target_from_result(result: ActionResult) -> str:
    resolved = result.resolved or {}
    return str(
        resolved.get("target")
        or resolved.get("label")
        or resolved.get("name")
        or resolved.get("entity_id")
        or ""
    ).strip()


def _entity_from_result(result: ActionResult) -> str:
    resolved = result.resolved or {}
    entity = resolved.get("entity_id")
    if entity:
        return str(entity)
    entities = resolved.get("entity_ids") or []
    return str(entities[0]) if entities else ""


def _domain_from_result(result: ActionResult) -> str:
    resolved = result.resolved or {}
    domain = resolved.get("domain")
    if domain:
        return str(domain)
    entity = _entity_from_result(result)
    if "." in entity:
        return entity.split(".", 1)[0]
    if result.intent.endswith("_light"):
        return "light"
    if result.intent.endswith("_fan") or result.intent == "set_fan_percentage":
        return "fan"
    return ""


def _action_from_result(result: ActionResult) -> str:
    if result.intent in {"turn_on_light", "turn_on_fan"}:
        return "turn_on"
    if result.intent in {"turn_off_light", "turn_off_fan"}:
        return "turn_off"
    action = result.resolved.get("action")
    return str(action or result.intent or "")


def _corrected_target(text: str, ctx: ConversationState) -> str:
    base = ctx.last_target
    if _FAN_WORDS.search(text):
        return _swap_device_word(base, "fan")
    if _LIGHT_WORDS.search(text):
        return _swap_device_word(base, "light")
    cleaned = re.sub(
        r"\b(no|actually|correction|i meant|i said|not that|not the|the)\b",
        " ",
        text,
    )
    cleaned = re.sub(r"[?.!,]", " ", cleaned)
    cleaned = " ".join(cleaned.split()).strip()
    return cleaned or base


def _swap_device_word(target: str, device_word: str) -> str:
    words = target.split()
    if not words:
        return device_word
    if words[-1].lower() in {"light", "lights", "lamp", "fan"}:
        words[-1] = device_word
        return " ".join(words)
    return f"{target} {device_word}"


def _domain_hint(text: str, ctx: ConversationState) -> str:
    if _FAN_WORDS.search(text):
        return "fan"
    if _LIGHT_WORDS.search(text):
        return "light"
    return ctx.last_domain or ""


def _action_hint(text: str) -> str:
    wants_on = bool(_ON_RE.search(text))
    wants_off = bool(_OFF_RE.search(text))
    if wants_on and not wants_off:
        return "turn_on"
    if wants_off and not wants_on:
        return "turn_off"
    if re.search(r"\b(dim|brightness|bright|level|speed|set)\b", text):
        return "set"
    return ""


def _percentage(text: str) -> Optional[int]:
    match = _PCT_RE.search(text)
    if not match:
        return None
    value = int(match.group(1))
    return max(0, min(100, value))


def _fan_percentage(text: str) -> Optional[int]:
    match = _PCT_RE.search(text)
    if match:
        value = int(match.group(1))
        if re.search(r"\b(speed|level|power)\s+(to\s+)?[1-5]\b", text):
            value = int(round(value / 5 * 100))
        return max(0, min(100, value))
    for word, value in _FAN_LEVEL_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", text):
            return value
    for word, value in _FAN_LEVEL_NUMBER_WORDS.items():
        if re.search(rf"\b(speed|level|power)\s+(to\s+)?{word}\b", text):
            return value
    if re.search(r"\b(down|lower|slower|decrease|reduce)\b", text):
        return 25
    if re.search(r"\b(up|higher|faster|increase|boost|max|level 5|speed 5)\b", text):
        return 100
    if re.search(r"\b(speed|level|power)\b", text):
        return 50
    return None
