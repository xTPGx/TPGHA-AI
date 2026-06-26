"""OpenAI client wrapper for tool/function-calling intent extraction.

If OPENAI_API_KEY is not set, we fall back to a deterministic rule-based
parser so the Command Tester and acceptance tests still work offline. The AI
only ever SELECTS a tool; the backend executes it.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

import httpx

from ..models.schemas import AppConfig, Assistant, User
from ..settings import get_settings
from ..memory import approved_memory_context
from .prompts import build_system_prompt
from .tools import TOOLS, TOOL_NAMES

logger = logging.getLogger("tpg.ai")


class ToolCall:
    def __init__(self, name: str, arguments: dict[str, Any], source: str = "openai",
                 assistant_text: str = ""):
        self.name = name
        self.arguments = arguments
        self.source = source
        self.assistant_text = assistant_text

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "arguments": self.arguments,
            "source": self.source,
            "assistant_text": self.assistant_text,
        }


class AIClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None
        if self.settings.openai_configured:
            try:
                from openai import OpenAI

                self._client = OpenAI(api_key=self.settings.openai_api_key)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("OpenAI SDK unavailable; using fallback parser.")
                self._client = None

    @property
    def using_openai(self) -> bool:
        return self._client is not None

    def provider_status(self) -> dict[str, Any]:
        ollama_configured = bool(self.settings.ollama_base_url and self.settings.ollama_model)
        return {
            "active": "openai" if self.using_openai else ("ollama" if ollama_configured else "fallback_parser"),
            "providers": {
                "openai": {
                    "configured": self.settings.openai_configured,
                    "available": self.using_openai,
                    "model": self.settings.openai_model,
                    "chat_model": self.settings.openai_chat_model,
                    "role": "primary_reasoning",
                },
                "ollama": {
                    "configured": ollama_configured,
                    "available": ollama_configured,
                    "model": self.settings.ollama_model,
                    "base_url": self.settings.ollama_base_url,
                    "role": "planned_local_fallback",
                },
                "fallback_parser": {
                    "configured": True,
                    "available": True,
                    "model": "deterministic_rules",
                    "role": "safety_and_offline_control",
                },
            },
        }

    def select_tool(
        self,
        message: str,
        config: AppConfig,
        assistant: Optional[Assistant],
        user: Optional[User],
        *,
        house_context: str = "",
        conversation_context: str = "",
    ) -> Optional[ToolCall]:
        if self._client is not None:
            try:
                return self._select_via_openai(
                    message, config, assistant, user,
                    house_context=house_context,
                    conversation_context=conversation_context,
                )
            except Exception as exc:  # pragma: no cover - network/runtime
                logger.warning("OpenAI call failed (%s); using fallback.", type(exc).__name__)
        if self.settings.ollama_base_url and self.settings.ollama_model:
            try:
                return self._select_via_ollama(message, config, assistant, user)
            except Exception as exc:  # pragma: no cover - network/runtime
                logger.warning("Ollama call failed (%s); using deterministic fallback.", type(exc).__name__)
        return fallback_parse(message, user)

    def general_chat(
        self,
        message: str,
        config: AppConfig,
        assistant: Optional[Assistant],
        user: Optional[User],
        *,
        conversation_context: str = "",
        house_context: str = "",
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """General conversational assistant response.

        This is intentionally separate from select_tool: home actions stay in
        the guarded tool router, while advice, brainstorming, explanations, and
        general Q&A can use the model normally.
        """

        if self._client is not None:
            try:
                return self._general_via_openai(
                    message,
                    config,
                    assistant,
                    user,
                    conversation_context=conversation_context,
                    house_context=house_context,
                    attachments=attachments or [],
                )
            except Exception as exc:  # pragma: no cover - network/runtime
                logger.warning("OpenAI general chat failed (%s); using fallback.", type(exc).__name__)
        return {
            "mode": "conversation",
            "provider": "fallback_parser",
            "message": _fallback_general_reply(message, house_context),
        }

    def _select_via_openai(
        self,
        message: str,
        config: AppConfig,
        assistant: Optional[Assistant],
        user: Optional[User],
        *,
        house_context: str = "",
        conversation_context: str = "",
    ) -> Optional[ToolCall]:
        extra = approved_memory_context()
        if house_context:
            extra = f"{extra}\n\nLive house state (for grounding device/room references):\n{house_context}"
        if conversation_context:
            extra = f"{extra}\n\nRecent conversation (most recent last):\n{conversation_context}"
        system = build_system_prompt(
            config,
            assistant,
            user,
            extra_context=extra,
        )
        resp = self._client.chat.completions.create(  # type: ignore[union-attr]
            model=self.settings.openai_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": message},
            ],
            tools=TOOLS,
            tool_choice="auto",
            temperature=0,
        )
        choice = resp.choices[0]
        msg = choice.message
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            tc = tool_calls[0]
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            return ToolCall(tc.function.name, args, source="openai",
                            assistant_text=msg.content or "")
        # No tool selected: conversational reply.
        return ToolCall("", {}, source="openai", assistant_text=msg.content or "")

    def _general_via_openai(
        self,
        message: str,
        config: AppConfig,
        assistant: Optional[Assistant],
        user: Optional[User],
        *,
        conversation_context: str = "",
        house_context: str = "",
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        household = config.household.default_household()
        house_name = household.name if household else "the home"
        tz = household.timezone if household else "local time"
        name = assistant.name if assistant else "TPG HomeAI"
        owner = user.name if user else "the user"
        personality = (assistant.personality.strip() if assistant else "") or (
            "Warm, sharp, practical, conversational, and concise."
        )
        memory_context = approved_memory_context()
        system = (
            f"You are {name}, the conversational AI brain for {house_name} ({tz}). "
            f"You are speaking with {owner}. Personality: {personality}\n\n"
            "You are an AI agent first, with Home Assistant as one of your tools. "
            "You can answer normal questions, brainstorm, advise, explain, plan, "
            "analyze images, and help with smart-home design without forcing every "
            "turn into a device command. "
            "You have persistent TPG Notebook history and approved Memory context across "
            "devices for the same HA/TPG profile. "
            "Never claim you cannot retain or access conversation history when Notebook/Memory context is provided. "
            "If asked what "
            "you remember, distinguish clearly: current conversation context, saved Notebook "
            "history, and approved long-term Memory. If no approved memory exists for a fact, "
            "say it is not approved long-term memory yet, but do not deny that Notebook stores "
            "the conversation. "
            "When the user asks for your opinion or asks where something should go, lead "
            "with the recommendation first. Give the answer like a capable advisor, not a "
            "generic options list. Use short paragraphs by default; only use bullets when "
            "they genuinely make the answer clearer. "
            "For voice/chat, be human and direct. Use short replies for quick turns, "
            "but give deeper reasoning when the user asks for analysis, design help, "
            "or troubleshooting. Do not end every response with a generic question. "
            "Do not say 'How can I assist you today?' unless the user asks for that "
            "exact phrasing. Stay in English unless the user clearly asks for another "
            "language; ignore accidental one-word or one-character foreign transcripts as likely "
            "speech-recognition noise and ask for a retry if needed. "
            "When the user asks for physical home changes, do not claim you changed the "
            "house unless a backend tool result says so. Suggest safe next steps or ask "
            "for missing specifics. If the user asks for dashboards, rooms, zones, entity "
            "mapping, blueprints, or floor plans, explain how TPG HomeAI can use approved "
            "entities/config and what data is still needed. When house inventory is provided, "
            "reason from it directly and name the specific rooms, entities, weak spots, and "
            "unknowns you see. Do not ask the user to list devices already shown in context. "
            "For smart-home design advice, call out rooms that are already covered, weak rooms, "
            "unavailable devices, missing room mappings, non-smart circuits, and missing voice "
            "sources. Avoid recommending obvious high-traffic rooms if the inventory shows they "
            "are already smart; explain why another location is more useful. "
            "If the user is frustrated, do not apologize at length. Acknowledge it briefly, "
            "state the corrected understanding, and move forward. "
            "If context is incomplete, identify the exact missing mapping instead of giving "
            "generic advice. Be natural, useful, and direct.\n\n"
            f"{memory_context}\n\n"
            f"House context:\n{house_context or 'No live house context available.'}\n\n"
            f"Recent conversation/action context:\n{conversation_context or 'None.'}"
        )
        user_content: Any = message
        if attachments:
            content_parts: list[dict[str, Any]] = [{"type": "text", "text": message}]
            for attachment in attachments:
                content_type = str(attachment.get("content_type") or "image/jpeg")
                data = str(attachment.get("data_base64") or "")
                if not data or not content_type.startswith("image/"):
                    continue
                name = str(attachment.get("filename") or "image")
                content_parts.append({"type": "text", "text": f"Attached image: {name}"})
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{content_type};base64,{data}"},
                })
            user_content = content_parts

        resp = self._client.chat.completions.create(  # type: ignore[union-attr]
            model=self.settings.openai_chat_model or self.settings.openai_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            temperature=0.5,
        )
        content = resp.choices[0].message.content or ""
        return {
            "mode": "conversation",
            "provider": "openai",
            "message": content.strip() or "I’m here. What do you want to work through?",
        }

    def _select_via_ollama(
        self,
        message: str,
        config: AppConfig,
        assistant: Optional[Assistant],
        user: Optional[User],
    ) -> Optional[ToolCall]:
        prompt = (
            "You select exactly one smart-home tool. Return ONLY compact JSON with "
            "keys: name, arguments, assistant_text. If no tool applies, set name to ''.\n"
            f"Allowed tools: {', '.join(TOOL_NAMES)}\n"
            f"Assistant: {(assistant.name if assistant else 'unknown')}\n"
            f"User: {(user.name if user else 'unknown')}\n"
            "Important: unlock/open garage/disarm are allowed tool selections but "
            "the backend will require confirmation. Do not invent arbitrary services.\n"
            f"Command: {message}"
        )
        url = f"{self.settings.ollama_base_url.rstrip('/')}/api/chat"
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(url, json={
                "model": self.settings.ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0},
            })
            resp.raise_for_status()
            body = resp.json()
        content = ((body.get("message") or {}).get("content") or "").strip()
        parsed = _parse_tool_json(content)
        name = str(parsed.get("name") or parsed.get("tool") or "")
        arguments = parsed.get("arguments") if isinstance(parsed.get("arguments"), dict) else {}
        if name and name not in TOOL_NAMES:
            return ToolCall("", {}, source="ollama", assistant_text=f"Ollama selected unsupported tool '{name}'.")
        return ToolCall(name, arguments, source="ollama",
                        assistant_text=str(parsed.get("assistant_text") or ""))


# ---------------------------------------------------------------------------
# Deterministic fallback parser (used when OpenAI is unavailable)
# ---------------------------------------------------------------------------
_TIME_RE = re.compile(
    r"\b(at\s+\d{1,2}(:\d{2})?\s*(am|pm)?|in\s+\d+\s*(minutes?|mins?|hours?|hrs?)|"
    r"sleep timer|timer|every|each\b|when\b|schedule|suggest|recommend)\b",
    re.I,
)


def fallback_parse(message: str, user: Optional[User]) -> Optional[ToolCall]:
    text = message.lower().strip()
    uid = user.id if user else None

    if _looks_like_explain_request(text):
        return ToolCall("explain_last_action", {"include_failed": True}, source="fallback")

    # Automation / scheduling first (so "turn on lights at 7am" -> automation).
    if any(k in text for k in ["movie mode", "bedtime routine", "morning routine",
                               "leaving routine", "away routine", "security routine",
                               "make a routine", "build a routine"]):
        return ToolCall("create_routine", {
            "routine": message,
            "room": _extract_after(text, ["in the", "for the", "for"]) or "",
        }, source="fallback")

    if _TIME_RE.search(text) and any(k in text for k in [
        "turn", "lock", "play", "set", "light", "on", "off", "tv", "display",
        "screen", "brightness", "dim", "sleep", "suggest", "recommend",
        "notify", "notification", "alert", "remind",
    ]):
        return ToolCall("create_simple_automation", {
            "trigger_description": message,
            "action_description": message,
        }, source="fallback")

    # Cameras.
    if any(k in text for k in ["show", "pull up", "see", "view", "camera", "look at"]) and \
       any(k in text for k in ["camera", "driveway", "front door", "door", "yard", "back", "front", "east", "west", "porch"]):
        cam = _extract_after(text, ["show me the", "show me", "show the", "show", "pull up the", "pull up", "view the", "view", "see the", "see"]) or text
        return ToolCall("show_camera", {"camera": cam.strip()}, source="fallback")

    # Locks.
    if "unlock" in text:
        door = _extract_after(text, ["unlock the", "unlock"]) or "front door"
        return ToolCall("unlock_door", {"door": door.strip()}, source="fallback")
    if "lock" in text and "unlock" not in text:
        if any(k in text for k in ["is", "are", "status", "?"]) and "lock up" not in text:
            return ToolCall("security_check", {}, source="fallback")
        door = _extract_after(text, ["lock up the", "lock up", "lock the", "lock"]) or "front door"
        if door.strip() in ("up", "house", "up the house", ""):
            door = "front door"
        return ToolCall("lock_door", {"door": door.strip()}, source="fallback")

    # Music.
    if "stop" in text and ("music" in text or "playing" in text):
        room = _extract_after(text, ["in the", "in"]) or "everywhere"
        return ToolCall("stop_music", {"room": room.strip()}, source="fallback")
    if "play" in text and any(p in text for p in ["music", "song", "spotify", "playlist", "album", "artist", "track"]):
        args = _music_request_args(message, user=uid)
        return ToolCall("play_music", args, source="fallback")
    if "volume" in text:
        m = re.search(r"(\d{1,3})", text)
        level = int(m.group(1)) if m else 50
        room = _extract_after(text, ["in the", "in", "on the", "on"]) or "everywhere"
        return ToolCall("set_volume", {"room": room.strip(), "level": level}, source="fallback")

    # Climate.
    if any(k in text for k in ["thermostat", "temperature", "climate", "ac", "heat", "cool"]):
        mode = "cool" if "cool" in text or "ac" in text else ("heat" if "heat" in text else "auto")
        m = re.search(r"(\d{2,3})", text)
        temp = int(m.group(1)) if m else 72
        room = _extract_after(text, ["in the", "in"]) or ""
        return ToolCall("set_climate", {"room": room.strip(), "mode": mode, "temperature": temp}, source="fallback")

    # Fans (before lights; "fan light" entries are handled by lights below).
    if "fan" in text and "light" not in text:
        fan_tc = _fan_tool_call(message, source="fallback")
        if fan_tc is not None:
            return fan_tc

    # Lights.
    if "light" in text:
        target = _extract_after(text, ["turn on the", "turn off the", "the"]) or "lights"
        if "off" in text:
            return ToolCall("turn_off_light", {"target": target.strip()}, source="fallback")
        return ToolCall("turn_on_light", {"target": target.strip()}, source="fallback")

    # Security.
    if any(k in text for k in ["security", "what cameras", "cameras online", "doors unlocked", "is everything", "all locked"]):
        return ToolCall("security_check", {}, source="fallback")

    # Dashboard drafts and navigation.
    if _looks_like_dashboard_draft(text):
        return ToolCall("draft_dashboard", {
            "title": _dashboard_title(message),
            "room": _extract_after(text, ["for the", "for", "in the", "in"]) or "",
            "style": "mushroom" if "mushroom" in text else "native",
            "target": message,
            "include_tablets": any(k in text for k in ["tablet", "wall panel", "display"]),
            "include_voice": any(k in text for k in ["voice", "assistant", "mic", "microphone"]),
        }, source="fallback")

    if "dashboard" in text and re.search(r"\b(open|show|pull up|navigate|go to|display|launch)\b", text):
        return ToolCall("open_dashboard", {"target": text}, source="fallback")

    return ToolCall("", {}, source="fallback", assistant_text="I'm not sure which action you meant.")


# ---------------------------------------------------------------------------
# Deterministic pre-router. Runs BEFORE the AI so fan commands route the same
# way every time, regardless of whether OpenAI is configured.
# ---------------------------------------------------------------------------
_FAN_PCT_RE = re.compile(r"(\d{1,3})")
_FAN_LEVEL_WORDS = {
    "minimum": 10, "min": 10, "lowest": 10, "low": 25,
    "medium": 50, "mid": 50, "normal": 50,
    "high": 75, "max": 100, "maximum": 100, "full": 100,
    "turbo": 100, "boost": 100,
}
_FAN_LEVEL_NUMBER_WORDS = {
    "one": 20, "two": 40, "three": 60, "four": 80, "five": 100,
}


_CAM_WORDS = ["camera", "driveway", "front door", "yard", "backyard", "back yard",
              "east", "west", "porch", "doorbell"]


def pre_route(message: str) -> Optional["ToolCall"]:
    """Deterministic router (PART 3). Runs before the AI so common, high-value
    commands route identically every time, with or without OpenAI.

    Covered: fans, lights, camera status, show camera, climate set, unlock,
    play music.
    """
    text = message.lower().strip()
    src = "pre-router"

    if _looks_like_explain_request(text):
        return ToolCall("explain_last_action", {"include_failed": True}, source=src)

    # Scheduling / automation phrasing must reach the AI (create_simple_automation),
    # so don't deterministically execute it as a direct command.
    if any(k in text for k in ["movie mode", "bedtime routine", "morning routine",
                               "leaving routine", "away routine", "security routine"]):
        return ToolCall("create_routine", {
            "routine": message,
            "room": _extract_after(text, ["in the", "for the", "for"]) or "",
        }, source=src)

    if _looks_scheduled(text):
        return None

    # Fans (skip if it's a fan *light*).
    if "fan" in text and "light" not in text:
        fc = _fan_tool_call(message, source=src)
        if fc is not None:
            return fc

    # Camera status / what's online.
    if any(p in text for p in ["what cameras", "cameras online", "camera status",
                               "which cameras", "are the cameras", "cameras up",
                               "what's online", "cameras working"]):
        return ToolCall("security_check", {}, source=src)

    # Show a camera.
    if any(p in text for p in ["show", "pull up", "view", "see", "look at"]) and \
       any(p in text for p in _CAM_WORDS):
        cam = _extract_after(text, ["show me the", "show me", "show the", "show",
                                    "pull up the", "pull up", "view the", "view",
                                    "see the", "see", "look at the", "look at"]) or text
        return ToolCall("show_camera", {"camera": cam.strip()}, source=src)

    # Lights (explicit on/off).
    if "light" in text and any(p in text for p in ["turn on", "turn off",
                                                   "switch on", "switch off"]):
        target = _light_target(message)
        if "off" in text:
            return ToolCall("turn_off_light", {"target": target}, source=src)
        return ToolCall("turn_on_light", {"target": target}, source=src)

    # Climate / thermostat set.
    if "thermostat" in text or (("cool" in text or "heat" in text)
                                and re.search(r"\b\d{2,3}\b", text)):
        mode = "cool" if "cool" in text or "ac" in text else (
            "heat" if "heat" in text else "auto")
        m = re.search(r"\b(\d{2,3})\b", text)
        temp = int(m.group(1)) if m else 72
        room = _extract_after(text, ["in the", "in"]) or ""
        return ToolCall("set_climate", {"room": room.strip(), "mode": mode,
                                        "temperature": temp}, source=src)

    # Unlock (sensitive — router will require confirmation).
    if "unlock" in text:
        door = _extract_after(text, ["unlock the", "unlock"]) or "front door"
        return ToolCall("unlock_door", {"door": door.strip()}, source=src)

    # Play music.
    if "play" in text and any(p in text for p in ["music", "song", "spotify", "playlist", "album", "artist", "track"]):
        return ToolCall("play_music", _music_request_args(message, user=None), source=src)

    # Generic device power control for TVs, displays, switches, media players,
    # and other mapped devices that do not have a more specific tool.
    generic_power = _generic_power_tool_call(message, source=src)
    if generic_power is not None:
        return generic_power

    return None


# Verbs that mark a clause as an actionable device command. Used to decide
# whether a conjunction ("and"/"then") joins two real commands worth splitting.
_ACTION_VERBS = (
    "turn", "switch", "power", "set", "dim", "brighten", "play", "stop", "pause",
    "resume", "lock", "unlock", "open", "close", "show", "pull up", "start",
    "raise", "lower", "increase", "decrease", "mute", "unmute", "arm", "disarm",
    "shut", "activate", "run", "make it",
)

# Schedule-ish phrasing must stay whole so it routes to automation creation.
_COMPOUND_SPLIT_RE = re.compile(
    r"\s*(?:,?\s+then\s+|,?\s+and\s+also\s+|,?\s+and\s+|\s*;\s*)", re.I
)


def _clause_is_actionable(clause: str) -> bool:
    c = clause.strip().lower()
    if not c:
        return False
    return any(re.search(rf"\b{re.escape(v)}\b", c) for v in _ACTION_VERBS)


def split_compound_command(message: str) -> list[str]:
    """Split "dim the lights and play jazz" into independent sub-commands.

    Returns a single-element list when the message is not a clear compound of
    two or more actionable clauses, so normal single-command routing is
    unaffected. Scheduling/automation phrasing is never split.
    """
    text = (message or "").strip()
    if not text:
        return [text]
    if _looks_scheduled(text.lower()):
        return [text]
    # Avoid splitting when "and"/"then" is clearly inside one target list with a
    # single trailing verb (e.g. "turn on the kitchen and dining lights").
    parts = [p.strip(" ,.") for p in _COMPOUND_SPLIT_RE.split(text) if p.strip(" ,.")]
    if len(parts) < 2:
        return [text]
    actionable = [p for p in parts if _clause_is_actionable(p)]
    if len(actionable) < 2:
        return [text]
    return actionable


def _looks_like_dashboard_draft(text: str) -> bool:
    return (
        "dashboard" in text
        and any(k in text for k in ["create", "build", "make", "generate", "draft", "design", "edit", "redesign"])
    )


def _music_request_args(message: str, user: Optional[str]) -> dict[str, Any]:
    raw = message.strip()
    text = raw.lower().strip()
    body = re.sub(r"^\s*(please\s+)?play\s+", "", raw, flags=re.I).strip()
    room = "everywhere"
    query = body

    marker = re.search(r"\s(?:on|in|through|to)\s+(?:the\s+)?(.+)$", body, flags=re.I)
    if marker:
        room = marker.group(1).strip()
        query = body[:marker.start()].strip()

    room = re.sub(r"\s+(?:speaker|speakers|display|screen|music)$", "", room, flags=re.I).strip() or "everywhere"
    query = _clean_music_query(query)
    media_type = _music_media_type(text)
    args: dict[str, Any] = {"room": room, "user": user}
    if query:
        args["query"] = query
        args["media_type"] = media_type
        args["raw"] = raw
    return args


def _clean_music_query(query: str) -> str:
    q = query.strip().strip("\"'")
    q = re.sub(r"\s+", " ", q)
    q = re.sub(r"^(?:my|some)\s+music$", "", q, flags=re.I)
    q = re.sub(r"^(?:the\s+)?", "", q, flags=re.I)
    q = re.sub(r"\s+(?:playlist|song|track|album|artist)$", "", q, flags=re.I)
    return q.strip()


def _music_media_type(text: str) -> str:
    if "playlist" in text:
        return "playlist"
    if "album" in text:
        return "album"
    if "artist" in text:
        return "artist"
    if "radio" in text or "station" in text:
        return "radio"
    if "song" in text or "track" in text:
        return "track"
    return "music"


def _dashboard_title(message: str) -> str:
    text = message.strip()
    m = re.search(r"(?:called|named|title[d]?)\s+['\"]?([^'\"]+)['\"]?", text, re.I)
    if m:
        return m.group(1).strip()[:80]
    room = _extract_after(text.lower(), ["for the", "for", "in the", "in"])
    if room:
        room = re.sub(r"\bdashboard\b.*$", "", room, flags=re.I).strip()
        if room:
            return f"TPG {room.title()} Dashboard"
    return "TPG Home Dashboard"


_SCHEDULE_RE = re.compile(
    r"\b(\d{1,2}\s*(am|pm)|at \d|in\s+\d+\s*(minutes?|mins?|hours?|hrs?)|"
    r"sleep timer|timer|sunset|sunrise|every|each|when |whenever|"
    r"schedule|automation|automate|remind|suggest|recommend|if .* then|"
    r"create an? rule)\b")


def _looks_scheduled(text: str) -> bool:
    return bool(_SCHEDULE_RE.search(text))


def _looks_like_explain_request(text: str) -> bool:
    patterns = (
        "why did you",
        "what did you just",
        "what did you do",
        "explain that",
        "explain the last",
        "why did that happen",
        "what happened",
        "show your work",
        "what was the last action",
    )
    return any(p in text for p in patterns)


def _generic_power_tool_call(message: str, source: str) -> Optional["ToolCall"]:
    text = message.lower().strip()
    on = re.search(r"\b(turn|switch|power)\s+on\b", text)
    off = re.search(r"\b(turn|switch|power|shut)\s+off\b", text)
    if bool(on) == bool(off):
        return None
    target = re.sub(r"\b(turn|switch|power|shut)\s+(on|off)\b", " ", text)
    target = re.sub(r"\bthe\b", " ", target)
    target = re.sub(r"[?.!,]", " ", target)
    target = " ".join(target.split()).strip()
    if not target or target in {"light", "lights", "fan", "fans"}:
        return None
    return ToolCall(
        "control_device",
        {"target": target, "action": "turn_on" if on else "turn_off"},
        source=source,
    )


def _light_target(message: str) -> str:
    t = message.lower()
    t = re.sub(r"\b(turn|switch)\s+(on|off)\b", " ", t)
    t = re.sub(r"\bthe\b", " ", t)
    t = re.sub(r"[?.!,]", " ", t)
    t = " ".join(t.split()).strip()
    return t or "lights"


def _fan_tool_call(message: str, source: str) -> Optional["ToolCall"]:
    text = message.lower()
    if "fan" not in text:
        return None
    percentage = _fan_level_value(text)
    if percentage is None and re.search(r"\b(speed|level|power|faster|slower|up|down|higher|lower)\b", text):
        percentage = _relative_fan_percentage(text)
    if any(k in text for k in ("set", "speed", "level", "power")) and percentage is not None:
        return ToolCall("set_fan_percentage",
                        {"target": _fan_target(message), "percentage": percentage},
                        source=source)
    if any(k in text for k in ("turn up", "speed up", "increase", "boost", "higher", "faster",
                               "turn down", "slow down", "decrease", "lower", "slower")) and \
            percentage is not None:
        return ToolCall("set_fan_percentage",
                        {"target": _fan_target(message), "percentage": percentage},
                        source=source)
    if any(p in text for p in ("turn off", "switch off", "shut off")) or (
        "off" in text and "set" not in text
    ):
        return ToolCall("turn_off_fan", {"target": _fan_target(message)}, source=source)
    if any(p in text for p in ("turn on", "switch on")) or ("on" in text and "set" not in text):
        return ToolCall("turn_on_fan", {"target": _fan_target(message)}, source=source)
    return None


def _fan_target(message: str) -> str:
    """Strip command words, leaving the fan/room phrase (keeps the word 'fan')."""
    t = message.lower()
    t = re.sub(r"\b(turn|switch|shut)\s+(on|off)\b", " ", t)
    t = re.sub(r"\b(turn\s+up|speed\s+up|turn\s+down|slow\s+down|increase|decrease|boost|higher|lower|faster|slower|reduce)\b", " ", t)
    t = re.sub(r"\b(can|could|would|will|you|please|hey|ok|okay|i|want|wanted|need|needs|to|me|for)\b", " ", t)
    t = re.sub(r"\bset\b", " ", t)
    t = re.sub(r"\bto\b", " ", t)
    t = re.sub(r"\bthe\b", " ", t)
    t = re.sub(r"\boff\b", " ", t)
    t = re.sub(r"\b(speed|level|power)\b", " ", t)
    t = re.sub(r"\b(minimum|min|lowest|low|medium|mid|normal|high|max|maximum|full|turbo|boost|one|two|three|four|five)\b", " ", t)
    t = re.sub(r"\bpercent(age)?\b", " ", t)
    t = re.sub(r"\d+\s*%?", " ", t)
    t = re.sub(r"[?.!,]", " ", t)
    t = " ".join(t.split()).strip()
    return t or "fan"


def _fan_level_value(text: str) -> Optional[int]:
    pct = _FAN_PCT_RE.search(text)
    if pct:
        value = int(pct.group(1))
        if re.search(r"\b(speed|level|power)\s+(to\s+)?[1-5]\b", text):
            value = int(round(value / 5 * 100))
        return max(0, min(100, value))
    for word, value in _FAN_LEVEL_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", text):
            return value
    for word, value in _FAN_LEVEL_NUMBER_WORDS.items():
        if re.search(rf"\b(speed|level|power)\s+(to\s+)?{word}\b", text):
            return value
    return None


def _relative_fan_percentage(text: str) -> int:
    if re.search(r"\b(turn down|slow down|decrease|lower|slower|reduce)\b", text):
        return 25
    if re.search(r"\b(turn up|speed up|increase|boost|higher|faster|max)\b", text):
        return 100
    return 50


def _extract_after(text: str, markers: list[str]) -> Optional[str]:
    for marker in markers:
        idx = text.find(marker)
        if idx != -1:
            rest = text[idx + len(marker):].strip()
            rest = re.sub(r"[?.!,]+$", "", rest).strip()
            if rest:
                return rest
    return None


def _parse_tool_json(content: str) -> dict[str, Any]:
    if not content:
        return {}
    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", content, re.S)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _fallback_general_reply(message: str, house_context: str) -> str:
    text = message.lower()
    if "weather" in text:
        if house_context:
            return house_context
        return "I do not have a live weather source yet. Add a Home Assistant weather entity or ask through OpenAI with location context."
    if any(k in text for k in ["dashboard", "room", "zone", "blueprint", "floor plan", "floorplan"]):
        return (
            "Yes. TPG HomeAI can use approved Home Assistant entities, rooms, voice sources, "
            "and dashboard profiles to draft dashboards and room/zone maps. For floor plans, "
            "the next layer is an upload/review workflow that stores a house layout as approved "
            "context before using it for automations or dashboards."
        )
    return (
        "I can talk through that, but OpenAI is not configured right now, so I’m in fallback mode. "
        "Configure OpenAI for full brainstorming, advice, and normal conversation."
    )


_ai: Optional[AIClient] = None


def get_ai_client() -> AIClient:
    global _ai
    if _ai is None:
        _ai = AIClient()
    return _ai
