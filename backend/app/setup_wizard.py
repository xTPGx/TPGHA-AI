"""First-run SmartOps setup and local service detection helpers.

Secrets are written only to the local runtime settings file and are never
returned by status endpoints.
"""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from .homeassistant.rest import HAError, get_ha_client
from .platform_sync import activate_once, get_platform_sync_status, push_setup_status
from .settings import get_settings

RUNTIME_SETTINGS_NAME = "runtime_settings.yaml"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def runtime_settings_path() -> Path:
    path = get_settings().config_path
    path.mkdir(parents=True, exist_ok=True)
    return path / RUNTIME_SETTINGS_NAME


def load_runtime_settings() -> dict[str, Any]:
    path = runtime_settings_path()
    if not path.exists():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - status should fail soft
        return {}
    return loaded if isinstance(loaded, dict) else {}


def save_runtime_settings(updates: dict[str, Any]) -> dict[str, Any]:
    current = load_runtime_settings()
    merged = {**current, **updates, "updated_at": _now_iso()}
    runtime_settings_path().write_text(yaml.safe_dump(merged, sort_keys=True), encoding="utf-8")
    return merged


def save_runtime_settings_safe(updates: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "tpg_platform_url",
        "tpg_platform_sync_enabled",
        "tpg_platform_sync_interval_minutes",
        "tpg_platform_portal_url",
        "tpg_platform_subscribe_url",
        "profile_code",
        "profile_name",
        "kokoro_tts_base_url",
        "ollama_base_url",
        "ollama_model",
        "piper_tts_entity_id",
    }
    clean: dict[str, Any] = {}
    for key, value in updates.items():
        if key in allowed_keys:
            clean[key] = value
    return safe_runtime_settings_from(save_runtime_settings(clean)) if clean else safe_runtime_settings()


def safe_runtime_settings_from(data: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    return {
        "profile_code": data.get("profile_code") or "unknown",
        "profile_name": data.get("profile_name") or "",
        "agent_token_configured": bool(data.get("tpg_platform_agent_token") or settings.tpg_platform_agent_token),
        "activation_code_stored": False,
        "platform_url": data.get("tpg_platform_url") or settings.tpg_platform_url,
        "portal_url": data.get("tpg_platform_portal_url") or settings.tpg_platform_portal_url,
        "subscribe_url": data.get("tpg_platform_subscribe_url") or settings.tpg_platform_subscribe_url,
        "sync_enabled": data.get("tpg_platform_sync_enabled", settings.tpg_platform_sync_enabled),
        "sync_interval_minutes": data.get("tpg_platform_sync_interval_minutes", settings.tpg_platform_sync_interval_minutes),
        "kokoro_tts_base_url": data.get("kokoro_tts_base_url") or settings.kokoro_tts_base_url,
        "ollama_base_url": data.get("ollama_base_url") or settings.ollama_base_url,
        "ollama_model": data.get("ollama_model") or settings.ollama_model,
        "piper_tts_entity_id": data.get("piper_tts_entity_id") or settings.piper_tts_entity_id,
        "feature_flags": data.get("feature_flags") if isinstance(data.get("feature_flags"), dict) else {},
        "setup_checklist": data.get("setup_checklist") if isinstance(data.get("setup_checklist"), list) else [],
        "generated_hints": data.get("generated_hints") if isinstance(data.get("generated_hints"), dict) else {},
        "agent_id": data.get("agent_id") or "",
        "updated_at": data.get("updated_at"),
    }


def runtime_secret_value(name: str) -> str:
    value = load_runtime_settings().get(name)
    return str(value or "").strip()


def safe_runtime_settings() -> dict[str, Any]:
    return safe_runtime_settings_from(load_runtime_settings())


async def activate_setup(activation_code: str, agent_name: str = "TPG HomeAI add-on") -> dict[str, Any]:
    result = await activate_once(activation_code=activation_code, agent_name=agent_name)
    config = result.get("config") if isinstance(result.get("config"), dict) else {}
    expected_services = result.get("expectedServices") if isinstance(result.get("expectedServices"), dict) else {}
    feature_flags = result.get("featureFlags") if isinstance(result.get("featureFlags"), dict) else config.get("featureFlags") if isinstance(config.get("featureFlags"), dict) else {}
    generated_hints = result.get("generatedHints") if isinstance(result.get("generatedHints"), dict) else config.get("generatedHints") if isinstance(config.get("generatedHints"), dict) else {}
    service_hints = config.get("serviceUrlHints") if isinstance(config.get("serviceUrlHints"), dict) else {}
    token = str(result.get("agentToken") or "").strip()
    profile_code = str(result.get("profileCode") or config.get("profileCode") or "basic_ha_green")
    updates = {
        "tpg_platform_url": result.get("platformUrl") or config.get("platformUrl") or get_settings().tpg_platform_url,
        "tpg_platform_sync_enabled": bool(result.get("syncEnabledRecommended", config.get("syncEnabled", True))),
        "tpg_platform_sync_interval_minutes": int(result.get("syncIntervalMinutes") or config.get("syncIntervalMinutes") or (5 if profile_code == "local_ai_pro" else 15)),
        "tpg_platform_portal_url": result.get("portalUrl") or config.get("portalUrl") or get_settings().tpg_platform_portal_url,
        "tpg_platform_subscribe_url": result.get("subscribeUrl") or config.get("subscribeUrl") or get_settings().tpg_platform_subscribe_url,
        "profile_code": profile_code,
        "profile_name": result.get("profileName") or config.get("profileName") or ((result.get("package") or {}).get("profileName", "") if isinstance(result.get("package"), dict) else ""),
        "kokoro_tts_base_url": expected_services.get("kokoroBaseUrl") or service_hints.get("kokoroTtsBaseUrl") or service_hints.get("kokoro_tts_base_url") or "",
        "ollama_base_url": expected_services.get("ollamaBaseUrl") or service_hints.get("ollamaBaseUrl") or service_hints.get("ollama_base_url") or "",
        "piper_tts_entity_id": expected_services.get("piperEntityId") or service_hints.get("piperTtsEntityId") or service_hints.get("piper_tts_entity_id") or "",
        "setup_checklist": result.get("setupChecklist") or config.get("setupChecklist") or [],
        "feature_flags": feature_flags,
        "generated_hints": generated_hints,
        "agent_id": result.get("agentId") or ((result.get("agent") or {}).get("id") if isinstance(result.get("agent"), dict) else ""),
    }
    if token:
        updates["tpg_platform_agent_token"] = token
    save_runtime_settings(updates)
    safe = dict(result)
    if "agentToken" in safe:
        safe["agentToken"] = "[stored_locally_once]"
    push_result = await push_setup_status(
        "activation_succeeded",
        milestones={
            "add_on_installed": True,
            "agent_activated": True,
            "profile_config_pulled": True,
        },
    )
    save_runtime_settings({"last_setup_status_push": push_result})
    safe["runtimeSettings"] = safe_runtime_settings()
    safe["setupStatusPush"] = push_result
    return safe


async def _probe_url(url: str, path: str = "", timeout_seconds: float = 2.0) -> dict[str, Any]:
    base = str(url or "").rstrip("/")
    if not base:
        return {"url": url, "configured": False, "reachable": False, "reason": "missing"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds)) as client:
            response = await client.get(f"{base}{path}")
        return {
            "url": base,
            "configured": True,
            "reachable": response.status_code < 500,
            "status_code": response.status_code,
        }
    except httpx.TimeoutException:
        return {"url": base, "configured": True, "reachable": False, "reason": "timeout"}
    except httpx.HTTPError:
        return {"url": base, "configured": True, "reachable": False, "reason": "unreachable"}


def _candidate_urls(*values: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = str(value or "").strip().rstrip("/")
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


async def detect_local_services() -> dict[str, Any]:
    settings = get_settings()
    runtime = safe_runtime_settings()
    kokoro_candidates = _candidate_urls(
        str(runtime.get("kokoro_tts_base_url") or ""),
        settings.kokoro_tts_base_url,
        "http://kokoro:8880",
        "http://homeassistant.local:8880",
        "http://127.0.0.1:8880",
    )
    ollama_candidates = _candidate_urls(
        str(runtime.get("ollama_base_url") or ""),
        settings.ollama_base_url,
        "http://ollama:11434",
        "http://homeassistant.local:11434",
        "http://127.0.0.1:11434",
    )
    kokoro_results = [await _probe_url(url, "/health") for url in kokoro_candidates]
    ollama_results = [await _probe_url(url, "/api/tags") for url in ollama_candidates]

    ha_summary: dict[str, Any] = {
        "configured": settings.ha_configured,
        "supervisor_mode": settings.supervisor_mode,
        "reachable": False,
        "entity_count": 0,
        "piper_ready": False,
        "music_assistant_ready": False,
        "areas_devices_entities_detected": False,
    }
    try:
        states = await get_ha_client().get_states()
        piper_entity = str(runtime.get("piper_tts_entity_id") or settings.piper_tts_entity_id or "tts.piper")
        ha_summary.update(
            {
                "reachable": True,
                "entity_count": len(states),
                "piper_ready": any(str(item.get("entity_id", "")) == piper_entity for item in states if isinstance(item, dict)),
                "music_assistant_ready": any(
                    "music_assistant" in str(item.get("entity_id", "")).lower()
                    or "mass" in str((item.get("attributes") or {}).get("integration", "")).lower()
                    for item in states
                    if isinstance(item, dict)
                ),
                "areas_devices_entities_detected": len(states) > 0,
            }
        )
    except HAError as exc:
        ha_summary["reason"] = exc.message

    detection = {
        "detected_at": _now_iso(),
        "kokoro": {
            "configured_url": runtime.get("kokoro_tts_base_url") or settings.kokoro_tts_base_url,
            "candidates": kokoro_results,
            "reachable": any(item.get("reachable") for item in kokoro_results),
        },
        "ollama": {
            "configured_url": runtime.get("ollama_base_url") or settings.ollama_base_url,
            "model": settings.ollama_model,
            "candidates": ollama_results,
            "reachable": any(item.get("reachable") for item in ollama_results),
        },
        "piper": {
            "entity_id": runtime.get("piper_tts_entity_id") or settings.piper_tts_entity_id,
            "ready": ha_summary["piper_ready"],
        },
        "music_assistant": {
            "ready": ha_summary["music_assistant_ready"],
        },
        "home_assistant": ha_summary,
        "openai": {
            "ready": settings.openai_configured,
            "mode": "openai" if settings.openai_configured else "fallback_parser",
        },
    }
    save_runtime_settings({"last_detection": detection})
    push_result = await push_setup_status(
        "detection_results",
        milestones={
            "ha_connected": bool(ha_summary.get("reachable")),
            "piper_detected": bool(detection["piper"]["ready"]),
            "kokoro_detected": bool(detection["kokoro"]["reachable"]),
            "ollama_detected": bool(detection["ollama"]["reachable"]),
        },
        detection=detection,
        health_reasons=[str(ha_summary.get("reason"))] if ha_summary.get("reason") else [],
    )
    save_runtime_settings({"last_setup_status_push": push_result})
    return detection


async def test_smartops_connection() -> dict[str, Any]:
    runtime = safe_runtime_settings()
    base = str(runtime.get("platform_url") or "").rstrip("/")
    if not base:
        return {"configured": False, "reachable": False, "reason": "platform_url_missing"}
    result = await _probe_url(base, "/health", timeout_seconds=3.0)
    return {
        "configured": True,
        "reachable": bool(result.get("reachable")),
        "platform_url": base,
        "status_code": result.get("status_code"),
        "reason": result.get("reason"),
        "token_configured": bool(runtime.get("agent_token_configured") or get_settings().tpg_platform_agent_token),
    }


async def test_openai_readiness() -> dict[str, Any]:
    settings = get_settings()
    return {
        "configured": bool(settings.openai_configured),
        "ready": bool(settings.openai_configured),
        "mode": "openai" if settings.openai_configured else "fallback_parser",
    }


async def test_tts_readiness() -> dict[str, Any]:
    detection = await detect_local_services()
    return {
        "kokoro": detection.get("kokoro", {}),
        "piper": detection.get("piper", {}),
        "openai_tts": {
            "configured": bool(get_settings().openai_configured),
            "ready": bool(get_settings().openai_configured),
        },
    }


async def complete_setup() -> dict[str, Any]:
    push_result = await push_setup_status(
        "setup_completed",
        milestones={"setup_completed": True},
        setup_completed=True,
    )
    saved = save_runtime_settings({"setup_completed": True, "setup_completed_at": _now_iso()})
    save_runtime_settings({"last_setup_status_push": push_result})
    return {
        "setup_completed": True,
        "runtime_settings": safe_runtime_settings_from(saved),
        "setupStatusPush": push_result,
    }


async def push_setup_event(payload: dict[str, Any]) -> dict[str, Any]:
    event = str(payload.get("event") or "status_push")
    milestones = payload.get("milestones") if isinstance(payload.get("milestones"), dict) else {}
    detection = payload.get("detection") if isinstance(payload.get("detection"), dict) else {}
    health_reasons = payload.get("healthReasons") if isinstance(payload.get("healthReasons"), list) else []
    result = await push_setup_status(
        event,
        milestones={str(key): bool(value) for key, value in milestones.items()},
        detection=detection,
        health_reasons=[str(item) for item in health_reasons],
        setup_completed=payload.get("setupCompleted") is True,
    )
    save_runtime_settings({"last_setup_status_push": result})
    return result


async def setup_status() -> dict[str, Any]:
    runtime = safe_runtime_settings()
    sync = await get_platform_sync_status()
    last_detection = load_runtime_settings().get("last_detection") or {}
    last_push = load_runtime_settings().get("last_setup_status_push") or sync.get("lastSetupStatusPush")
    profile_code = str(runtime.get("profile_code") or "unknown")
    kokoro = last_detection.get("kokoro") if isinstance(last_detection.get("kokoro"), dict) else {}
    ollama = last_detection.get("ollama") if isinstance(last_detection.get("ollama"), dict) else {}
    piper = last_detection.get("piper") if isinstance(last_detection.get("piper"), dict) else {}
    openai = last_detection.get("openai") if isinstance(last_detection.get("openai"), dict) else {}
    ha = last_detection.get("home_assistant") if isinstance(last_detection.get("home_assistant"), dict) else {}
    missing_required: list[str] = []
    missing_recommended: list[str] = []
    if not runtime["agent_token_configured"]:
        missing_required.append("SmartOps activation")
    if runtime["agent_token_configured"] and not sync.get("lastHeartbeatAt"):
        missing_recommended.append("SmartOps heartbeat")
    if profile_code in {"voice_plus", "local_ai_pro"} and not kokoro.get("reachable"):
        missing_required.append("Kokoro voice service")
    if profile_code == "local_ai_pro" and not ollama.get("reachable"):
        missing_required.append("Ollama local AI service")
    if not ha.get("areas_devices_entities_detected"):
        missing_recommended.append("Home Assistant entity scan")
    if profile_code == "basic_ha_green" and not (openai.get("ready") or get_settings().openai_configured):
        missing_recommended.append("OpenAI key or fallback parser review")
    stored_completed = bool(load_runtime_settings().get("setup_completed"))
    setup_completed = stored_completed or not missing_required
    return {
        "setup_completed": setup_completed,
        "runtime_settings": runtime,
        "activation_status": "activated" if runtime["agent_token_configured"] else "not_activated",
        "install_profile_code": profile_code,
        "install_profile_name": runtime.get("profile_name") or _profile_display_name(profile_code),
        "smartops_configured": bool(runtime["agent_token_configured"]),
        "smartops_enabled": bool(runtime.get("sync_enabled")),
        "smartops_licensed": bool(sync.get("licensed")),
        "lastHeartbeatAt": sync.get("lastHeartbeatAt"),
        "lastSyncAt": sync.get("lastSyncAt"),
        "kokoro_detected": bool(kokoro.get("reachable")),
        "kokoro_configured": bool(runtime.get("kokoro_tts_base_url")),
        "ollama_detected": bool(ollama.get("reachable")),
        "ollama_configured": bool(runtime.get("ollama_base_url")),
        "piper_detected": bool(piper.get("ready")),
        "piper_configured": bool(runtime.get("piper_tts_entity_id")),
        "openai_configured": bool(get_settings().openai_configured),
        "missing_required_items": missing_required,
        "missing_recommended_items": missing_recommended,
        "portalUrl": runtime.get("portal_url"),
        "subscribeUrl": runtime.get("subscribe_url"),
        "smartops_sync": sync,
        "lastSmartOpsStatusPush": last_push,
        "detection": last_detection,
        "missing_setup_items": [*missing_required, *missing_recommended],
    }


def _profile_display_name(code: str) -> str:
    return {
        "basic_ha_green": "Basic / HA Green",
        "voice_plus": "Voice Plus",
        "local_ai_pro": "Local AI Pro",
    }.get(code, "")
