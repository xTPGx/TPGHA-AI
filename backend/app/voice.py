"""Assistant voice profiles and speech synthesis.

The browser microphone remains the capture layer. This module owns outbound
assistant speech: configured OpenAI TTS first, browser fallback always.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
from pathlib import Path
from typing import Any, Optional

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
        instructions=(
            "Speak like a calm, confident house intelligence. Natural, concise, "
            "capable, and warm. Avoid robotic cadence."
        ),
    ),
    "chatty": VoiceProfile(
        provider="openai",
        voice="coral",
        instructions=(
            "Speak as an intelligent female assistant: conversational, warm, "
            "quick, and composed. Keep smart-home replies brief."
        ),
    ),
    "neutral": VoiceProfile(provider="browser", voice="alloy"),
    "bright": VoiceProfile(provider="openai", voice="coral"),
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
    return {
        "voices": VOICE_CATALOG,
        "default_model": get_settings().openai_tts_model,
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
) -> dict[str, Any]:
    settings = get_settings()
    assistant = assistant_by_id(config, assistant_id)
    profile = _profile_from_assistant(assistant, assistant_id)
    data = profile.model_dump()
    data["model"] = data.get("model") or settings.openai_tts_model
    data["response_format"] = data.get("response_format") or settings.openai_tts_format
    if target_entity_id:
        data["target_entity_id"] = target_entity_id
        data["output"] = "media_player"
    data["assistant"] = {
        "id": assistant.id if assistant else assistant_id,
        "name": assistant.name if assistant else assistant_id.title(),
        "tone": assistant.tone if assistant else "neutral",
    }
    data["backend"] = {
        "openai_configured": settings.openai_configured,
        "speaker_routing_configured": bool(settings.voice_public_base_url),
    }
    data["available"] = data["provider"] == "browser" or settings.openai_configured
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
            "voice_public_base_url_configured": bool(get_settings().voice_public_base_url),
        },
    }


async def preview_voice(
    assistant_id: str,
    text: str,
    target_entity_id: Optional[str] = None,
) -> dict[str, Any]:
    cfg = get_config()
    profile = resolve_voice_profile(cfg, assistant_id, target_entity_id)
    return {
        "profile": profile,
        "text": text,
        "mode": "openai_tts" if profile["provider"] == "openai" and profile["available"] else "browser",
        "will_fallback_to_browser": profile["provider"] == "openai" and not profile["available"],
    }


async def speak_text(
    assistant_id: str,
    text: str,
    target_entity_id: Optional[str] = None,
    force_browser: bool = False,
) -> dict[str, Any]:
    cfg = get_config()
    profile = resolve_voice_profile(cfg, assistant_id, target_entity_id)
    if force_browser or profile["provider"] == "browser":
        return _browser_response(profile, text)
    if profile["provider"] != "openai":
        return _browser_response(profile, text, reason=f"Unsupported provider '{profile['provider']}'.")
    if not get_settings().openai_configured:
        return _browser_response(profile, text, reason="OpenAI API key is not configured.")

    try:
        audio_bytes = await asyncio.to_thread(_openai_speech_bytes, profile, text)
    except Exception as exc:  # pragma: no cover - network/sdk dependent
        logger.warning("OpenAI TTS failed (%s); using browser fallback.", type(exc).__name__)
        return _browser_response(profile, text, reason=f"OpenAI TTS failed: {type(exc).__name__}.")

    fmt = str(profile.get("response_format") or "mp3")
    content_type = MIME_BY_FORMAT.get(fmt, "audio/mpeg")
    audio_id = _write_audio(audio_bytes, fmt)
    response: dict[str, Any] = {
        "mode": "audio",
        "provider": "openai",
        "profile": profile,
        "text": text,
        "content_type": content_type,
        "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
        "audio_path": f"/voice/audio/{audio_id}",
        "speaker_route": {"requested": bool(profile.get("target_entity_id")), "routed": False},
    }
    if profile.get("target_entity_id"):
        response["speaker_route"] = await _route_to_speaker(
            str(profile["target_entity_id"]),
            f"/voice/audio/{audio_id}",
            content_type,
        )
    return response


def _profile_from_assistant(assistant: Optional[Assistant], assistant_id: str) -> VoiceProfile:
    settings = get_settings()
    default = DEFAULT_PROFILES.get((assistant_id or "").lower()) or DEFAULT_PROFILES["neutral"]
    if not assistant:
        return _with_runtime_defaults(default, settings.openai_tts_model, settings.openai_tts_format)
    raw = assistant.voice
    if isinstance(raw, VoiceProfile):
        merged = default.model_copy(update={k: v for k, v in raw.model_dump().items() if v not in (None, "")})
        return _with_runtime_defaults(merged, settings.openai_tts_model, settings.openai_tts_format)
    alias = str(raw or "").lower()
    mapped = DEFAULT_PROFILES.get(alias) or default
    return _with_runtime_defaults(mapped, settings.openai_tts_model, settings.openai_tts_format)


def _with_runtime_defaults(profile: VoiceProfile, model: str, response_format: str) -> VoiceProfile:
    updates: dict[str, Any] = {}
    if not profile.model:
        updates["model"] = model
    if not profile.response_format:
        updates["response_format"] = response_format
    return profile.model_copy(update=updates)


def _browser_response(profile: dict[str, Any], text: str, reason: str = "") -> dict[str, Any]:
    return {
        "mode": "browser",
        "provider": "browser",
        "profile": profile,
        "text": text,
        "speak_text": text,
        "fallback_reason": reason,
    }


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
    response = client.audio.speech.create(**kwargs)
    if hasattr(response, "read"):
        return response.read()
    content = getattr(response, "content", None)
    if isinstance(content, bytes):
        return content
    return bytes(response)


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
