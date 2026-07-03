"""Optional SmartOps heartbeat and Home Assistant inventory sync worker.

The agent token is sent only as an Authorization header to the configured
SmartOps URL. Status returned by this module is safe for /health and /state.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
from copy import deepcopy
from typing import Any

import httpx

from .discovery import scanner as discovery_scanner
from .homeassistant.rest import HAError, get_ha_client
from .settings import get_settings

logger = logging.getLogger("tpg.platform_sync")

_STATUS: dict[str, Any] = {
    "configured": False,
    "enabled": False,
    "licensed": False,
    "lastHeartbeatAt": None,
    "lastSyncAt": None,
    "lastError": None,
    "reasonCode": None,
    "portalUrl": "https://portal.tpgsmarthomes.com/portal/install",
    "subscribeUrl": "https://tpgsmarthomes.com/packages",
}
_LOCK = asyncio.Lock()
_SECRET_KEYS = (
    "token",
    "secret",
    "password",
    "authorization",
    "auth",
    "api_key",
    "apikey",
    "bearer",
    "cookie",
    "session",
    "credential",
    "pin",
)


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "SmartOps request timed out."
    if isinstance(exc, httpx.ConnectError):
        return "SmartOps is not reachable."
    if isinstance(exc, HAError):
        return exc.message
    return f"{type(exc).__name__}: sync attempt failed."


async def _set_status(**updates: Any) -> None:
    async with _LOCK:
        _STATUS.update(updates)


async def get_platform_sync_status() -> dict[str, Any]:
    settings = get_settings()
    async with _LOCK:
        status = deepcopy(_STATUS)
    status["configured"] = settings.tpg_platform_configured
    status["enabled"] = bool(settings.tpg_platform_sync_enabled)
    status["portalUrl"] = settings.tpg_platform_portal_url
    status["subscribeUrl"] = settings.tpg_platform_subscribe_url
    return status


def _platform_base_url() -> str:
    return get_settings().tpg_platform_url.rstrip("/")


def _auth_headers() -> dict[str, str]:
    token = get_settings().tpg_platform_agent_token
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "TPG-HomeAI-Agent",
    }


async def _post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    timeout = httpx.Timeout(15.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{_platform_base_url()}{path}",
            headers=_auth_headers(),
            json=payload,
        )
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code >= 400 and not isinstance(body, dict):
        body = {}
    if response.status_code >= 500:
        raise httpx.HTTPStatusError(
            "SmartOps returned a server error.",
            request=response.request,
            response=response,
        )
    return body if isinstance(body, dict) else {}


async def heartbeat_once(app_version: str) -> dict[str, Any]:
    settings = get_settings()
    discovery = await discovery_scanner.summary()
    payload = {
        "version": app_version,
        "homeAssistant": {
            "configured": settings.ha_configured,
            "authMode": settings.ha_auth_mode,
            "supervisorMode": settings.supervisor_mode,
        },
        "discovery": {
            "knownCount": discovery.get("known_count", 0),
            "pendingCount": discovery.get("pending_count", 0),
            "unavailableCount": discovery.get("unavailable_count", 0),
            "lastScanTs": discovery.get("last_scan_ts"),
            "lastSuccessfulScanTs": discovery.get("last_successful_scan_ts"),
        },
    }
    result = await _post_json("/api/platform/agents/heartbeat", payload)
    allowed = bool(result.get("allowed"))
    await _set_status(
        configured=settings.tpg_platform_configured,
        enabled=bool(settings.tpg_platform_sync_enabled),
        licensed=allowed,
        lastHeartbeatAt=_now_iso(),
        lastError=None if allowed else result.get("message") or "Sync is not licensed.",
        reasonCode=result.get("reasonCode"),
        portalUrl=settings.tpg_platform_portal_url,
        subscribeUrl=settings.tpg_platform_subscribe_url,
    )
    return result


def _redact_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if any(marker in lowered for marker in _SECRET_KEYS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(key, item) for item in value[:50]]
    return value


def _integration_hint(attrs: dict[str, Any]) -> Any:
    if attrs.get("integration"):
        return attrs.get("integration")
    if attrs.get("platform"):
        return attrs.get("platform")
    device_info = attrs.get("device_info")
    if isinstance(device_info, dict):
        return device_info.get("manufacturer")
    return None


def _entity_payload(item: dict[str, Any]) -> dict[str, Any] | None:
    entity_id = str(item.get("entity_id") or "").strip()
    if not entity_id or "." not in entity_id:
        return None
    domain = entity_id.split(".", 1)[0]
    attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
    state = str(item.get("state") or "")
    return {
        "entity_id": entity_id,
        "domain": domain,
        "friendly_name": attrs.get("friendly_name") or entity_id,
        "state": state,
        "available": state not in {"unavailable", "unknown", "none", ""},
        "area": attrs.get("area_id") or attrs.get("area") or attrs.get("room"),
        "roomHint": attrs.get("room") or attrs.get("area") or attrs.get("area_id"),
        "deviceClass": attrs.get("device_class"),
        "integration": _integration_hint(attrs),
        "last_changed": item.get("last_changed"),
        "last_updated": item.get("last_updated"),
        "raw": _redact_value(
            "raw",
            {
                "entity_id": entity_id,
                "state": state,
                "attributes": {
                    "friendly_name": attrs.get("friendly_name"),
                    "device_class": attrs.get("device_class"),
                    "unit_of_measurement": attrs.get("unit_of_measurement"),
                    "area_id": attrs.get("area_id"),
                    "room": attrs.get("room"),
                    "integration": attrs.get("integration") or attrs.get("platform"),
                },
                "last_changed": item.get("last_changed"),
                "last_updated": item.get("last_updated"),
            },
        ),
    }


async def build_sync_entities() -> list[dict[str, Any]]:
    raw_states = await get_ha_client().get_states()
    entities: list[dict[str, Any]] = []
    for item in raw_states:
        if not isinstance(item, dict):
            continue
        payload = _entity_payload(item)
        if payload is not None:
            entities.append(payload)
    return entities


async def sync_once(app_version: str) -> dict[str, Any]:
    entities = await build_sync_entities()
    payload = {
        "version": app_version,
        "summary": {"count": len(entities)},
        "entities": entities,
    }
    result = await _post_json("/api/platform/agents/home-assistant/sync", payload)
    allowed = bool(result.get("allowed", True))
    await _set_status(
        licensed=allowed,
        lastSyncAt=_now_iso() if allowed else _STATUS.get("lastSyncAt"),
        lastError=None if allowed else result.get("message") or "Sync is not licensed.",
        reasonCode=result.get("reasonCode", "SYNC_ALLOWED" if allowed else None),
    )
    return result


def _settings_ready() -> bool:
    settings = get_settings()
    return bool(
        settings.tpg_platform_sync_enabled
        and settings.tpg_platform_url
        and settings.tpg_platform_agent_token
    )


async def platform_sync_loop(app_version: str) -> None:
    while True:
        settings = get_settings()
        await _set_status(
            configured=settings.tpg_platform_configured,
            enabled=bool(settings.tpg_platform_sync_enabled),
            portalUrl=settings.tpg_platform_portal_url,
            subscribeUrl=settings.tpg_platform_subscribe_url,
        )
        if not _settings_ready():
            reason = "TOKEN_MISSING" if settings.tpg_platform_sync_enabled else "SYNC_DISABLED"
            await _set_status(licensed=False, reasonCode=reason, lastError=None)
            await asyncio.sleep(60)
            continue

        try:
            heartbeat = await heartbeat_once(app_version)
            if heartbeat.get("allowed"):
                await sync_once(app_version)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - never crash local HA control
            logger.warning("SmartOps sync skipped: %s", _safe_error(exc))
            await _set_status(
                licensed=False,
                lastError=_safe_error(exc),
                reasonCode="SMARTOPS_UNAVAILABLE",
            )

        interval = max(1, min(int(settings.tpg_platform_sync_interval_minutes or 5), 1440))
        await asyncio.sleep(interval * 60)
