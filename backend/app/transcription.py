"""Voice input transcription for browser/mobile microphone captures."""
from __future__ import annotations

import asyncio
import io
import logging
import re
import time
from typing import Any

from .settings import get_settings

logger = logging.getLogger("tpg.transcription")

MAX_AUDIO_BYTES = 25 * 1024 * 1024


async def transcribe_audio(filename: str, content_type: str, audio_bytes: bytes) -> dict[str, Any]:
    """Transcribe a user microphone recording with OpenAI, returning JSON-safe data."""
    started = time.perf_counter()
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
            "audio_bytes": len(audio_bytes),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }

    try:
        text = await asyncio.to_thread(
            _openai_transcribe,
            audio_bytes,
            filename or "voice-input.webm",
            content_type or "application/octet-stream",
            settings.openai_transcribe_model,
            settings.openai_transcribe_language,
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
            "audio_bytes": len(audio_bytes),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }

    return {
        "success": True,
        "provider": "openai",
        "model": settings.openai_transcribe_model,
        "language": settings.openai_transcribe_language,
        "audio_bytes": len(audio_bytes),
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "text": text.strip(),
    }


def _openai_transcribe(audio_bytes: bytes, filename: str, content_type: str, model: str, language: str = "") -> str:
    from openai import OpenAI

    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    file_obj = io.BytesIO(audio_bytes)
    file_obj.name = filename
    kwargs: dict[str, Any] = {
        "model": model,
        "file": (filename, audio_bytes, content_type),
        "response_format": "json",
    }
    if language.strip():
        kwargs["language"] = language.strip()
    try:
        response = client.audio.transcriptions.create(**kwargs)
    except TypeError as exc:
        retry_kwargs = dict(kwargs)
        error_text = str(exc)
        removed = False
        for key in ("response_format", "language"):
            if key in retry_kwargs and (key in error_text or "unexpected keyword" in error_text):
                retry_kwargs.pop(key, None)
                removed = True
        if removed:
            response = client.audio.transcriptions.create(**retry_kwargs)
        else:
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
