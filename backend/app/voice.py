"""Assistant voice profiles and speech synthesis.

The browser microphone remains the capture layer. This module owns outbound
assistant speech: configured OpenAI TTS first, browser fallback always.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from .config_loader import get_config
from .homeassistant.rest import HAError, get_ha_client
from .models.schemas import AppConfig, Assistant, VoiceProfile
from .settings import get_settings

logger = logging.getLogger("tpg.voice")

VOICE_CATALOG = [
    {"id": "alloy", "label": "Alloy", "style": "balanced neutral"},
    {"id": "ash", "label": "Ash", "style": "clear and grounded"},
    {"id": "ballad", "label": "Ballad", "style": "smooth and expressive"},
    {"id": "cedar", "label": "Cedar", "style": "warm, calm, masculine"},
    {"id": "coral", "label": "Coral", "style": "intelligent, warm, feminine"},
    {"id": "echo", "label": "Echo", "style": "direct and crisp"},
    {"id": "fable", "label": "Fable", "style": "expressive storyteller"},
    {"id": "marin", "label": "Marin", "style": "natural and composed"},
    {"id": "nova", "label": "Nova", "style": "bright, friendly, feminine"},
    {"id": "onyx", "label": "Onyx", "style": "deep and authoritative"},
    {"id": "sage", "label": "Sage", "style": "steady and thoughtful"},
    {"id": "shimmer", "label": "Shimmer", "style": "bright and energetic"},
    {"id": "verse", "label": "Verse", "style": "polished and dynamic"},
]

KOKORO_VOICE_CATALOG = [
    {"id": "af_heart", "label": "Heart", "style": "warm natural female", "provider": "kokoro"},
    {"id": "af_bella", "label": "Bella", "style": "friendly natural female", "provider": "kokoro"},
    {"id": "af_sarah", "label": "Sarah", "style": "clear conversational female", "provider": "kokoro"},
    {"id": "am_adam", "label": "Adam", "style": "steady natural male", "provider": "kokoro"},
    {"id": "am_michael", "label": "Michael", "style": "confident natural male", "provider": "kokoro"},
    {"id": "bf_emma", "label": "Emma", "style": "polished British female", "provider": "kokoro"},
    {"id": "bm_george", "label": "George", "style": "grounded British male", "provider": "kokoro"},
]

PROVIDERS = [
    {
        "id": "openai",
        "label": "OpenAI TTS",
        "kind": "cloud",
        "description": "Premium steerable voice using the configured OpenAI API key.",
    },
    {
        "id": "kokoro",
        "label": "Kokoro local",
        "kind": "local",
        "description": "Free/open local TTS through a Kokoro OpenAI-compatible endpoint.",
    },
    {
        "id": "custom",
        "label": "Custom private endpoint",
        "kind": "private",
        "description": "Personal/licensed TTS endpoint. Do not ship cloned voices without consent.",
    },
    {
        "id": "piper",
        "label": "Home Assistant Piper",
        "kind": "local",
        "description": "HA/Piper TTS routed to a media player or room speaker.",
    },
    {
        "id": "browser",
        "label": "Browser fallback",
        "kind": "fallback",
        "description": "Built-in browser speech when no real TTS provider is available.",
    },
]

MIME_BY_FORMAT = {
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "wav": "audio/wav",
    "pcm": "audio/pcm",
}

DEFAULT_PROFILES = {
    "atlas": VoiceProfile(
        provider="openai",
        voice="cedar",
        speed=1.12,
        instructions=(
            "Speak like a calm, confident house intelligence. Natural, concise, "
            "capable, warm, and lightly witty. Use contractions. Avoid robotic "
            "cadence and over-explaining."
        ),
    ),
    "chatty": VoiceProfile(
        provider="openai",
        voice="coral",
        speed=1.13,
        instructions=(
            "Speak as an intelligent female assistant: conversational, warm, "
            "quick, and composed. Keep smart-home replies brief."
        ),
    ),
    "neutral": VoiceProfile(provider="browser", voice="alloy", speed=1.08),
    "bright": VoiceProfile(provider="openai", voice="coral", speed=1.14),
}


def voice_audio_dir() -> Path:
    path = get_settings().config_path / "voice_audio"
    path.mkdir(parents=True, exist_ok=True)
    return path


def voice_audio_path(audio_id: str) -> Path:
    safe_id = "".join(ch for ch in audio_id if ch.isalnum() or ch in "._-")
    if safe_id != audio_id or not safe_id:
        raise FileNotFoundError(audio_id)
    path = voice_audio_dir() / safe_id
    if not path.is_file():
        raise FileNotFoundError(audio_id)
    return path


def list_voices() -> dict[str, Any]:
    settings = get_settings()
    return {
        "voices": [
            *[dict(voice, provider="openai") for voice in VOICE_CATALOG],
            *KOKORO_VOICE_CATALOG,
            {"id": settings.piper_tts_entity_id, "label": "Piper", "style": "Home Assistant local TTS", "provider": "piper"},
            {"id": "custom", "label": "Custom licensed voice", "style": "Private endpoint voice id", "provider": "custom"},
            {"id": "browser", "label": "Browser default", "style": "Emergency fallback", "provider": "browser"},
        ],
        "providers": PROVIDERS,
        "default_model": settings.openai_tts_model,
        "default_kokoro_model": "kokoro",
        "formats": list(MIME_BY_FORMAT.keys()),
    }


def assistant_by_id(config: AppConfig, assistant_id: str) -> Optional[Assistant]:
    needle = (assistant_id or "").lower()
    for assistant in config.assistants.assistants:
        names = [assistant.id, assistant.name, *assistant.aliases]
        if any(str(name).lower() == needle for name in names):
            return assistant
    return None


def resolve_voice_profile(
    config: AppConfig,
    assistant_id: str,
    target_entity_id: Optional[str] = None,
    room: Optional[str] = None,
    source_device_id: Optional[str] = None,
    source_entity_id: Optional[str] = None,
    reply_mode: str = "auto",
) -> dict[str, Any]:
    settings = get_settings()
    assistant = assistant_by_id(config, assistant_id)
    profile = _profile_from_assistant(assistant, assistant_id)
    data = profile.model_dump()
    data["model"] = data.get("model") or settings.openai_tts_model
    data["response_format"] = data.get("response_format") or settings.openai_tts_format
    route = resolve_reply_route(
        config,
        target_entity_id=target_entity_id,
        room=room,
        source_device_id=source_device_id,
        source_entity_id=source_entity_id,
        reply_mode=reply_mode,
    )
    if route.get("target_entity_id"):
        data["target_entity_id"] = route["target_entity_id"]
    data["output"] = route.get("output", data.get("output", "browser"))
    data["route"] = route
    data["assistant"] = {
        "id": assistant.id if assistant else assistant_id,
        "name": assistant.name if assistant else assistant_id.title(),
        "tone": assistant.tone if assistant else "neutral",
        "wake_words": assistant.wake_words if assistant else [],
        "listen_enabled": assistant.listen_enabled if assistant else False,
    }
    data["backend"] = {
        "openai_configured": settings.openai_configured,
        "kokoro_configured": bool(settings.kokoro_tts_base_url),
        "custom_tts_configured": bool(settings.custom_tts_base_url),
        "piper_configured": settings.ha_configured,
        "speaker_routing_configured": bool(settings.voice_public_base_url),
    }
    data["available"] = _provider_available(data, settings)
    return data


def list_voice_profiles(config: Optional[AppConfig] = None) -> dict[str, Any]:
    cfg = config or get_config()
    return {
        "profiles": [
            resolve_voice_profile(cfg, assistant.id)
            for assistant in cfg.assistants.assistants
        ],
        "voices": VOICE_CATALOG,
        "settings": {
            "openai_tts_model": get_settings().openai_tts_model,
            "openai_configured": get_settings().openai_configured,
            "kokoro_tts_configured": bool(get_settings().kokoro_tts_base_url),
            "custom_tts_configured": bool(get_settings().custom_tts_base_url),
            "piper_tts_configured": get_settings().ha_configured,
            "piper_tts_entity_id": get_settings().piper_tts_entity_id,
            "voice_public_base_url_configured": bool(get_settings().voice_public_base_url),
        },
    }


def list_voice_source_readiness(config: Optional[AppConfig] = None) -> dict[str, Any]:
    cfg = config or get_config()
    sources = []
    for source in cfg.devices.voice_sources:
        route = resolve_reply_route(
            cfg,
            room=source.room,
            source_device_id=source.source_device_id,
            source_entity_id=source.source_entity_id,
            reply_mode=source.default_reply,
        )
        sources.append({
            **source.model_dump(),
            "resolved_reply_route": route,
            "has_room": bool(source.room),
            "has_source_identity": bool(source.source_device_id or source.source_entity_id),
            "trusted_for_sensitive": source.trust_level == "trusted",
        })
    return {
        "voice_sources": sources,
        "counts": {
            "total": len(sources),
            "trusted": sum(1 for s in sources if s.get("trust_level") == "trusted"),
            "with_room": sum(1 for s in sources if s.get("has_room")),
            "with_speaker_route": sum(1 for s in sources if s.get("resolved_reply_route", {}).get("target_entity_id")),
        },
    }


async def preview_voice(
    assistant_id: str,
    text: str,
    voice_profile: Optional[VoiceProfile] = None,
    target_entity_id: Optional[str] = None,
    room: Optional[str] = None,
    source_device_id: Optional[str] = None,
    source_entity_id: Optional[str] = None,
    reply_mode: str = "auto",
) -> dict[str, Any]:
    cfg = get_config()
    profile = resolve_voice_profile(
        cfg, assistant_id, target_entity_id, room, source_device_id, source_entity_id, reply_mode
    )
    profile = _apply_profile_override(profile, voice_profile)
    return {
        "profile": profile,
        "text": text,
        "speak_text": _normalize_tts_text(text, profile),
        "mode": f"{profile['provider']}_tts" if profile["provider"] != "browser" and profile["available"] else "browser",
        "will_fallback_to_browser": profile["provider"] != "browser" and not profile["available"],
    }


async def speak_text(
    assistant_id: str,
    text: str,
    voice_profile: Optional[VoiceProfile] = None,
    target_entity_id: Optional[str] = None,
    force_browser: bool = False,
    include_audio_base64: bool = True,
    room: Optional[str] = None,
    source_device_id: Optional[str] = None,
    source_entity_id: Optional[str] = None,
    reply_mode: str = "auto",
) -> dict[str, Any]:
    cfg = get_config()
    profile = resolve_voice_profile(
        cfg, assistant_id, target_entity_id, room, source_device_id, source_entity_id, reply_mode
    )
    profile = _apply_profile_override(profile, voice_profile)
    speak_text_value = _normalize_tts_text(text, profile)
    if profile.get("route", {}).get("mode") == "none":
        return {
            "mode": "silent",
            "provider": "none",
            "profile": profile,
            "text": text,
            "speak_text": speak_text_value,
            "speaker_route": profile.get("route"),
        }
    if force_browser or profile["provider"] == "browser":
        return _browser_response(profile, text, speak_text_value)
    if profile["provider"] in {"ha_tts", "piper"}:
        return await _ha_tts_response(profile, text, speak_text_value)
    if profile["provider"] in {"kokoro", "custom"}:
        return await _endpoint_tts_response(
            profile,
            text,
            speak_text_value,
            include_audio_base64=include_audio_base64,
        )
    if profile["provider"] != "openai":
        return _browser_response(profile, text, speak_text_value, reason=f"Unsupported provider '{profile['provider']}'.")
    if not get_settings().openai_configured:
        return _browser_response(profile, text, speak_text_value, reason="OpenAI API key is not configured.")

    started = time.perf_counter()
    try:
        audio_bytes = await asyncio.to_thread(_openai_speech_bytes, profile, speak_text_value)
    except Exception as exc:  # pragma: no cover - network/sdk dependent
        detail = _safe_error_detail(exc)
        logger.warning("OpenAI TTS failed (%s); using browser fallback.", detail)
        return _browser_response(profile, text, speak_text_value, reason=f"OpenAI TTS failed: {detail}.")
    latency_ms = int((time.perf_counter() - started) * 1000)

    fmt = str(profile.get("response_format") or "mp3")
    content_type = MIME_BY_FORMAT.get(fmt, "audio/mpeg")
    audio_id = _write_audio(audio_bytes, fmt)
    response: dict[str, Any] = {
        "mode": "audio",
        "provider": "openai",
        "profile": profile,
        "text": text,
        "speak_text": speak_text_value,
        "content_type": content_type,
        "audio_path": f"/voice/audio/{audio_id}",
        "latency_ms": latency_ms,
        "audio_bytes": len(audio_bytes),
        "speaker_route": {"requested": bool(profile.get("target_entity_id")), "routed": False},
    }
    if include_audio_base64:
        response["audio_base64"] = base64.b64encode(audio_bytes).decode("ascii")
    if profile.get("target_entity_id"):
        response["speaker_route"] = await _route_to_speaker(
            str(profile["target_entity_id"]),
            f"/voice/audio/{audio_id}",
            content_type,
        )
    return response


def _profile_from_assistant(assistant: Optional[Assistant], assistant_id: str) -> VoiceProfile:
    settings = get_settings()
    key = (assistant_id or "").lower()
    default = DEFAULT_PROFILES.get(key) or DEFAULT_PROFILES["neutral"]
    if not assistant:
        return _with_runtime_defaults(default, settings.openai_tts_model, settings.openai_tts_format)
    raw = assistant.voice
    if isinstance(raw, VoiceProfile):
        raw_data = raw.model_dump()
        if _is_legacy_browser_profile(raw_data) and key in DEFAULT_PROFILES:
            return _with_runtime_defaults(default, settings.openai_tts_model, settings.openai_tts_format)
        if raw_data.get("voice") in {"neutral", "default", ""}:
            raw_data.pop("voice", None)
        merged = default.model_copy(update={k: v for k, v in raw_data.items() if v not in (None, "")})
        return _with_runtime_defaults(merged, settings.openai_tts_model, settings.openai_tts_format)
    alias = str(raw or "").lower()
    if alias in {"", "neutral", "default"} and key in DEFAULT_PROFILES:
        return _with_runtime_defaults(default, settings.openai_tts_model, settings.openai_tts_format)
    mapped = DEFAULT_PROFILES.get(alias) or default
    return _with_runtime_defaults(mapped, settings.openai_tts_model, settings.openai_tts_format)


def _is_legacy_browser_profile(data: dict[str, Any]) -> bool:
    provider = str(data.get("provider") or "").lower()
    voice = str(data.get("voice") or "").lower()
    return provider == "browser" and voice in {"", "neutral", "default", "alloy"}


def _apply_profile_override(profile: dict[str, Any], override: Optional[VoiceProfile]) -> dict[str, Any]:
    if not override:
        return profile
    settings = get_settings()
    data = dict(profile)
    for key, value in override.model_dump().items():
        if value not in (None, ""):
            data[key] = value
    data["available"] = _provider_available(data, settings)
    return data


def _provider_available(profile: dict[str, Any], settings: Any) -> bool:
    provider = str(profile.get("provider") or "browser").lower()
    if provider == "browser":
        return True
    if provider == "openai":
        return settings.openai_configured
    if provider == "kokoro":
        return bool(profile.get("endpoint_url") or settings.kokoro_tts_base_url)
    if provider == "custom":
        return bool(profile.get("endpoint_url") or settings.custom_tts_base_url)
    if provider in {"ha_tts", "piper"}:
        return settings.ha_configured
    return False


def resolve_reply_route(
    config: AppConfig,
    target_entity_id: Optional[str] = None,
    room: Optional[str] = None,
    source_device_id: Optional[str] = None,
    source_entity_id: Optional[str] = None,
    reply_mode: str = "auto",
) -> dict[str, Any]:
    source = _match_voice_source(config, source_device_id, source_entity_id)
    resolved_room = room or (source.room if source else None)
    mode = reply_mode if reply_mode != "auto" else (source.default_reply if source else "browser")
    if target_entity_id:
        return {
            "mode": "media_player",
            "output": "media_player",
            "target_entity_id": target_entity_id,
            "room": resolved_room,
            "source": source.model_dump() if source else None,
            "reason": "explicit_target",
        }
    if mode in {"none", "quiet"}:
        return {
            "mode": mode,
            "output": "browser" if mode == "quiet" else "none",
            "room": resolved_room,
            "source": source.model_dump() if source else None,
            "reason": f"reply_mode_{mode}",
        }
    if mode in {"room_speaker", "media_player"} and resolved_room:
        speaker = _speaker_for_room(config, resolved_room, preferred_id=source.speaker if source else None)
        if speaker:
            return {
                "mode": "room_speaker",
                "output": "media_player",
                "target_entity_id": speaker.entity_id,
                "room": resolved_room,
                "speaker": speaker.model_dump(),
                "source": source.model_dump() if source else None,
                "reason": "room_speaker",
            }
    return {
        "mode": "browser",
        "output": "browser",
        "room": resolved_room,
        "source": source.model_dump() if source else None,
        "reason": "browser_fallback",
    }


def _match_voice_source(config: AppConfig, source_device_id: Optional[str], source_entity_id: Optional[str]):
    for source in config.devices.voice_sources:
        if source_device_id and source.source_device_id == source_device_id:
            return source
        if source_entity_id and source.source_entity_id == source_entity_id:
            return source
    return None


def _speaker_for_room(config: AppConfig, room: str, preferred_id: Optional[str] = None):
    if preferred_id:
        for speaker in config.devices.speakers:
            if preferred_id in {speaker.id, speaker.entity_id, speaker.name}:
                return speaker
    needle = room.lower().replace(" ", "_")
    for speaker in config.devices.speakers:
        if (speaker.room or "").lower().replace(" ", "_") == needle:
            return speaker
    for room_cfg in config.devices.rooms:
        if needle in {room_cfg.id.lower(), room_cfg.name.lower().replace(" ", "_")} and room_cfg.speaker:
            for speaker in config.devices.speakers:
                if speaker.entity_id == room_cfg.speaker or speaker.id == room_cfg.speaker:
                    return speaker
    return None


def _with_runtime_defaults(profile: VoiceProfile, model: str, response_format: str) -> VoiceProfile:
    updates: dict[str, Any] = {}
    if not profile.model:
        updates["model"] = model
    if not profile.response_format:
        updates["response_format"] = response_format
    return profile.model_copy(update=updates)


def _browser_response(profile: dict[str, Any], text: str, speak_text: Optional[str] = None, reason: str = "") -> dict[str, Any]:
    return {
        "mode": "browser",
        "provider": "browser",
        "profile": profile,
        "text": text,
        "speak_text": speak_text or text,
        "fallback_reason": reason,
    }


async def _endpoint_tts_response(
    profile: dict[str, Any],
    text: str,
    speak_text: str,
    include_audio_base64: bool = True,
) -> dict[str, Any]:
    settings = get_settings()
    provider = str(profile.get("provider") or "custom")
    base_url = str(profile.get("endpoint_url") or "").strip()
    if not base_url:
        base_url = settings.kokoro_tts_base_url if provider == "kokoro" else settings.custom_tts_base_url
    if not base_url:
        return _browser_response(profile, text, speak_text, reason=f"{provider} TTS endpoint is not configured.")
    started = time.perf_counter()
    try:
        audio_bytes = await _openai_compatible_tts_bytes(profile, speak_text, base_url, settings.custom_tts_api_key if provider == "custom" else "")
    except Exception as exc:  # pragma: no cover - depends on external local service
        detail = _safe_error_detail(exc)
        logger.warning("%s TTS failed (%s); using browser fallback.", provider, detail)
        return _browser_response(profile, text, speak_text, reason=f"{provider} TTS failed: {detail}.")
    latency_ms = int((time.perf_counter() - started) * 1000)

    fmt = str(profile.get("response_format") or "mp3")
    content_type = MIME_BY_FORMAT.get(fmt, "audio/mpeg")
    audio_id = _write_audio(audio_bytes, fmt)
    response: dict[str, Any] = {
        "mode": "audio",
        "provider": provider,
        "profile": profile,
        "text": text,
        "speak_text": speak_text,
        "content_type": content_type,
        "audio_path": f"/voice/audio/{audio_id}",
        "latency_ms": latency_ms,
        "audio_bytes": len(audio_bytes),
        "speaker_route": {"requested": bool(profile.get("target_entity_id")), "routed": False},
    }
    if include_audio_base64:
        response["audio_base64"] = base64.b64encode(audio_bytes).decode("ascii")
    if profile.get("target_entity_id"):
        response["speaker_route"] = await _route_to_speaker(
            str(profile["target_entity_id"]),
            f"/voice/audio/{audio_id}",
            content_type,
        )
    return response


async def _ha_tts_response(profile: dict[str, Any], text: str, speak_text: str) -> dict[str, Any]:
    route = profile.get("route") or {}
    target_entity_id = profile.get("target_entity_id") or route.get("target_entity_id")
    if not target_entity_id:
        return _browser_response(profile, text, speak_text, reason="Home Assistant TTS needs a media player target.")
    settings = get_settings()
    tts_entity = _tts_entity_for_profile(profile, settings.piper_tts_entity_id)
    try:
        await get_ha_client().speak_tts(tts_entity, str(target_entity_id), speak_text)
    except HAError as exc:
        return _browser_response(profile, text, speak_text, reason=f"Home Assistant TTS failed: {exc.message}.")
    return {
        "mode": "ha_tts",
        "provider": str(profile.get("provider") or "ha_tts"),
        "profile": profile,
        "text": text,
        "speak_text": speak_text,
        "speaker_route": {
            "requested": True,
            "routed": True,
            "entity_id": target_entity_id,
            "tts_entity_id": tts_entity,
        },
    }


def _tts_entity_for_profile(profile: dict[str, Any], fallback: str) -> str:
    for value in (profile.get("voice"), profile.get("model")):
        text = str(value or "").strip()
        if text.startswith("tts."):
            return text
    return fallback or "tts.piper"


async def _openai_compatible_tts_bytes(
    profile: dict[str, Any],
    text: str,
    base_url: str,
    api_key: str = "",
) -> bytes:
    url = _speech_endpoint_url(base_url)
    provider = str(profile.get("provider") or "custom").lower()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload: dict[str, Any] = {
        "model": str(profile.get("model") or ("kokoro" if provider == "kokoro" else "tts")),
        "voice": str(profile.get("voice") or ("af_heart" if provider == "kokoro" else "default")),
        "input": text,
        "response_format": str(profile.get("response_format") or "mp3"),
        "speed": _coerce_speed(profile.get("speed"), 1.1),
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.content


def _speech_endpoint_url(base_url: str) -> str:
    cleaned = str(base_url or "").strip().rstrip("/")
    if not cleaned:
        raise ValueError("TTS endpoint URL is empty")
    if cleaned.endswith("/v1/audio/speech") or cleaned.endswith("/audio/speech"):
        return cleaned
    if cleaned.endswith("/v1"):
        return f"{cleaned}/audio/speech"
    return f"{cleaned}/v1/audio/speech"


def _normalize_tts_text(text: str, profile: dict[str, Any]) -> str:
    if profile.get("normalize_text") is False:
        return str(text or "")
    value = str(text or "").strip()
    if not value:
        return ""
    value = re.sub(r"```.*?```", " ", value, flags=re.S)
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", value)
    value = re.sub(r"\*([^*]+)\*", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"^\s*[-*]\s+", "", value, flags=re.M)
    value = re.sub(r"^\s*\d+\.\s+", "", value, flags=re.M)
    value = re.sub(
        r"\b(?:light|fan|switch|sensor|binary_sensor|media_player|device_tracker|person|lock|cover|climate|camera)\.([a-z0-9_]+)\b",
        lambda match: match.group(1).replace("_", " "),
        value,
    )
    replacements = {
        "HA": "Home Assistant",
        "TPG": "T P G",
        "API": "A P I",
        "UI": "U I",
        "TV": "T V",
        "LED": "L E D",
        "UUID": "U U I D",
    }
    for source, target in replacements.items():
        value = re.sub(rf"\b{re.escape(source)}\b", target, value)
    value = value.replace("_", " ")
    value = re.sub(r"\s+", " ", value).strip()
    max_chars = _coerce_max_spoken_chars(profile.get("max_spoken_chars"), 1200)
    if len(value) <= max_chars:
        return value
    clipped = value[:max_chars].rstrip()
    sentence = max(clipped.rfind("."), clipped.rfind("?"), clipped.rfind("!"))
    if sentence > max_chars * 0.55:
        clipped = clipped[: sentence + 1]
    return f"{clipped.rstrip()}."


def _coerce_max_spoken_chars(value: Any, default: int = 1200) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(120, min(4000, parsed))


def _openai_speech_bytes(profile: dict[str, Any], text: str) -> bytes:
    from openai import OpenAI

    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    model = str(profile.get("model") or settings.openai_tts_model)
    kwargs: dict[str, Any] = {
        "model": model,
        "voice": str(profile.get("voice") or "alloy"),
        "input": text,
        "response_format": str(profile.get("response_format") or settings.openai_tts_format),
    }
    instructions = str(profile.get("instructions") or "").strip()
    if instructions and model not in {"tts-1", "tts-1-hd"}:
        kwargs["instructions"] = instructions
    kwargs["speed"] = _coerce_speed(profile.get("speed"), 1.1)
    try:
        response = _create_openai_speech(client, kwargs)
    except TypeError as exc:
        retry_kwargs = dict(kwargs)
        removed: list[str] = []
        error_text = str(exc)
        for key in ("instructions", "speed"):
            if key in retry_kwargs and (key in error_text or "unexpected keyword" in error_text):
                retry_kwargs.pop(key, None)
                removed.append(key)
        if not removed:
            raise
        logger.warning("OpenAI SDK rejected TTS args %s; retrying speech without them.", ", ".join(removed))
        response = _create_openai_speech(client, retry_kwargs)
    return _speech_response_bytes(response)


def _coerce_speed(value: Any, default: float = 1.1) -> float:
    try:
        speed = float(value)
    except (TypeError, ValueError):
        speed = default
    return max(0.75, min(1.35, speed))


def _create_openai_speech(client: Any, kwargs: dict[str, Any]) -> Any:
    return client.audio.speech.create(**kwargs)


def _speech_response_bytes(response: Any) -> bytes:
    if hasattr(response, "read"):
        return response.read()
    content = getattr(response, "content", None)
    if isinstance(content, bytes):
        return content
    return bytes(response)


def _safe_error_detail(exc: Exception) -> str:
    text = str(exc).strip()
    if not text:
        return type(exc).__name__
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-***", text)
    text = " ".join(text.split())
    if len(text) > 220:
        text = f"{text[:217]}..."
    return f"{type(exc).__name__}: {text}"


def _write_audio(audio_bytes: bytes, fmt: str) -> str:
    suffix = fmt if fmt in MIME_BY_FORMAT else "mp3"
    digest = hashlib.sha256(audio_bytes).hexdigest()[:20]
    audio_id = f"{digest}.{suffix}"
    path = voice_audio_dir() / audio_id
    if not path.exists():
        path.write_bytes(audio_bytes)
    return audio_id


async def _route_to_speaker(entity_id: str, audio_path: str, content_type: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.voice_public_base_url:
        return {
            "requested": True,
            "routed": False,
            "entity_id": entity_id,
            "reason": "VOICE_PUBLIC_BASE_URL is not configured.",
        }
    media_url = f"{settings.voice_public_base_url.rstrip('/')}{audio_path}"
    try:
        await get_ha_client().play_media(entity_id, media_url, content_type)
    except HAError as exc:
        return {
            "requested": True,
            "routed": False,
            "entity_id": entity_id,
            "media_content_id": media_url,
            "reason": exc.message,
        }
    return {
        "requested": True,
        "routed": True,
        "entity_id": entity_id,
        "media_content_id": media_url,
        "media_content_type": content_type,
    }
