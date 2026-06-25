"""Voice input transcription for browser/mobile microphone captures."""
from __future__ import annotations

import asyncio
import io
import logging
import re
from typing import Any

from .settings import get_settings

logger = logging.getLogger("tpg.transcription")

MAX_AUDIO_BYTES = 25 * 1024 * 1024


async def transcribe_audio(filename: str, content_type: str, audio_bytes: bytes) -> dict[str, Any]:
    """Transcribe a user microphone recording with OpenAI, returning JSON-safe data."""
    if not audio_bytes:
        return {
            "success": False,
            "provider": "openai",
            "text": "",
            "error": "No microphone audio was received.",
        }
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        return {
            "success": False,
            "provider": "openai",
            "text": "",
            "error": "Microphone audio is too large. Try a shorter recording.",
        }

    settings = get_settings()
    if not settings.openai_configured:
        return {
            "success": False,
            "provider": "openai",
            "model": settings.openai_transcribe_model,
            "text": "",
            "error": "OpenAI API key is not configured.",
        }

    try:
        text = await asyncio.to_thread(
            _openai_transcribe,
            audio_bytes,
            filename or "voice-input.webm",
            content_type or "application/octet-stream",
            settings.openai_transcribe_model,
        )
    except Exception as exc:  # pragma: no cover - network/sdk dependent
        detail = _safe_error_detail(exc)
        logger.warning("OpenAI transcription failed: %s", detail)
        return {
            "success": False,
            "provider": "openai",
            "model": settings.openai_transcribe_model,
            "text": "",
            "error": f"OpenAI transcription failed: {detail}.",
        }

    return {
        "success": True,
        "provider": "openai",
        "model": settings.openai_transcribe_model,
        "text": text.strip(),
    }


def _openai_transcribe(audio_bytes: bytes, filename: str, content_type: str, model: str) -> str:
    from openai import OpenAI

    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    file_obj = io.BytesIO(audio_bytes)
    file_obj.name = filename
    try:
        response = client.audio.transcriptions.create(
            model=model,
            file=(filename, audio_bytes, content_type),
        )
    except TypeError:
        response = client.audio.transcriptions.create(
            model=model,
            file=file_obj,
        )
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text
    if isinstance(response, dict):
        return str(response.get("text") or "")
    return str(response)


def _safe_error_detail(exc: Exception) -> str:
    text = str(exc).strip() or type(exc).__name__
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-***", text)
    text = " ".join(text.split())
    if len(text) > 220:
        text = f"{text[:217]}..."
    return f"{type(exc).__name__}: {text}"
