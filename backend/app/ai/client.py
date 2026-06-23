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

    def select_tool(
        self,
        message: str,
        config: AppConfig,
        assistant: Optional[Assistant],
        user: Optional[User],
    ) -> Optional[ToolCall]:
        if self._client is not None:
            try:
                return self._select_via_openai(message, config, assistant, user)
            except Exception as exc:  # pragma: no cover - network/runtime
                logger.warning("OpenAI call failed (%s); using fallback.", type(exc).__name__)
        return fallback_parse(message, user)

    def _select_via_openai(
        self,
        message: str,
        config: AppConfig,
        assistant: Optional[Assistant],
        user: Optional[User],
    ) -> Optional[ToolCall]:
        system = build_system_prompt(
            config,
            assistant,
            user,
            extra_context=approved_memory_context(),
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
    if "play" in text and ("music" in text or "song" in text or "spotify" in text):
        room = _extract_after(text, ["in the", "in", "on the", "on"]) or "everywhere"
        return ToolCall("play_music", {"room": room.strip(), "user": uid}, source="fallback")
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

    # Dashboard.
    if "dashboard" in text or "open" in text:
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
    if "play" in text and any(p in text for p in ["music", "song", "spotify", "playlist"]):
        room = _extract_after(text, ["in the", "in", "on the", "on"]) or "everywhere"
        return ToolCall("play_music", {"room": room.strip(), "user": None}, source=src)

    # Generic device power control for TVs, displays, switches, media players,
    # and other mapped devices that do not have a more specific tool.
    generic_power = _generic_power_tool_call(message, source=src)
    if generic_power is not None:
        return generic_power

    return None


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
    t = re.sub(r"\bset\b", " ", t)
    t = re.sub(r"\bto\b", " ", t)
    t = re.sub(r"\bthe\b", " ", t)
    t = re.sub(r"\b(speed|level|power)\b", " ", t)
    t = re.sub(r"\b(minimum|min|lowest|low|medium|mid|normal|high|max|maximum|full|turbo|boost)\b", " ", t)
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


_ai: Optional[AIClient] = None


def get_ai_client() -> AIClient:
    global _ai
    if _ai is None:
        _ai = AIClient()
    return _ai
