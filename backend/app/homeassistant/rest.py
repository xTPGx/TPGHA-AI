"""Home Assistant REST API client (httpx).

Security: the long-lived token is read from settings and sent only in the
Authorization header. It is NEVER logged. Errors are normalized into
HAError with friendly messages for 401 / 404 / timeout / connection issues.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from ..settings import get_settings

logger = logging.getLogger("tpg.ha.rest")

UNAVAILABLE_STATES = {"unavailable", "unknown", "none", ""}


class HAError(Exception):
    """Normalized Home Assistant error (never contains secrets)."""

    def __init__(self, message: str, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class HomeAssistantREST:
    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.ha_base_url).rstrip("/")
        self._token = token or settings.home_assistant_token
        self.timeout = timeout or settings.ha_timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self._token)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def _request(
        self, method: str, path: str, json: Optional[dict] = None
    ) -> Any:
        if not self.configured:
            raise HAError(
                "Home Assistant is not configured. Set HOME_ASSISTANT_URL and "
                "HOME_ASSISTANT_TOKEN."
            )
        url = f"{self.base_url}/api{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.request(
                    method, url, headers=self._headers(), json=json
                )
        except httpx.TimeoutException as exc:
            raise HAError(
                f"Timed out talking to Home Assistant after {self.timeout}s."
            ) from exc
        except httpx.ConnectError as exc:
            raise HAError(
                "Could not connect to Home Assistant. Check the URL and that "
                "Home Assistant is reachable from this host."
            ) from exc
        except httpx.HTTPError as exc:  # pragma: no cover - defensive
            raise HAError("Unexpected error talking to Home Assistant.") from exc

        if resp.status_code == 401:
            raise HAError(
                "Home Assistant rejected the token (401). Re-create the "
                "long-lived access token.",
                status=401,
            )
        if resp.status_code == 404:
            raise HAError(f"Home Assistant resource not found: {path}", status=404)
        if resp.status_code >= 400:
            raise HAError(
                f"Home Assistant returned HTTP {resp.status_code}.",
                status=resp.status_code,
            )

        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    # ----------------------------------------------------------------- reads
    async def get_states(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/states")
        return data or []

    async def get_entity(self, entity_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/states/{entity_id}")

    async def is_available(self, entity_id: str) -> bool:
        try:
            entity = await self.get_entity(entity_id)
        except HAError:
            return False
        return (entity or {}).get("state", "") not in UNAVAILABLE_STATES

    async def ping(self) -> dict[str, Any]:
        """Return API health/config without exposing secrets."""
        try:
            data = await self._request("GET", "/")
            return {"connected": True, "message": (data or {}).get("message", "ok")}
        except HAError as exc:
            return {"connected": False, "message": exc.message, "status": exc.status}

    # ---------------------------------------------------------------- writes
    async def call_service(
        self,
        domain: str,
        service: str,
        data: Optional[dict] = None,
        *,
        return_response: bool = False,
    ) -> Any:
        logger.info("HA service call %s.%s", domain, service)
        suffix = "?return_response" if return_response else ""
        return await self._request(
            "POST", f"/services/{domain}/{service}{suffix}", json=data or {}
        )

    async def turn_on(self, entity_id: str, **extra: Any) -> Any:
        domain = entity_id.split(".", 1)[0]
        return await self.call_service(domain, "turn_on", {"entity_id": entity_id, **extra})

    async def turn_off(self, entity_id: str, **extra: Any) -> Any:
        domain = entity_id.split(".", 1)[0]
        return await self.call_service(domain, "turn_off", {"entity_id": entity_id, **extra})

    async def lock(self, entity_id: str) -> Any:
        return await self.call_service("lock", "lock", {"entity_id": entity_id})

    async def unlock(self, entity_id: str) -> Any:
        return await self.call_service("lock", "unlock", {"entity_id": entity_id})

    async def set_volume(self, entity_id: str, level: float) -> Any:
        level = max(0.0, min(1.0, float(level)))
        return await self.call_service(
            "media_player",
            "volume_set",
            {"entity_id": entity_id, "volume_level": level},
        )

    async def media_stop(self, entity_id: str) -> Any:
        return await self.call_service(
            "media_player", "media_stop", {"entity_id": entity_id}
        )

    async def play_media(
        self, entity_id: str, media_content_id: str, media_content_type: str
    ) -> Any:
        return await self.call_service(
            "media_player",
            "play_media",
            {
                "entity_id": entity_id,
                "media_content_id": media_content_id,
                "media_content_type": media_content_type,
            },
        )

    async def music_assistant_play_media(
        self,
        entity_id: str,
        media_id: str | list[str],
        media_type: Optional[str] = None,
        enqueue: str = "replace",
        radio_mode: bool = False,
    ) -> Any:
        data: dict[str, Any] = {
            "entity_id": entity_id,
            "media_id": media_id,
            "enqueue": enqueue,
        }
        if media_type:
            data["media_type"] = media_type
        if radio_mode:
            data["radio_mode"] = True
        return await self.call_service("music_assistant", "play_media", data)

    async def music_assistant_search(
        self,
        name: str,
        *,
        limit: int = 8,
        media_type: Optional[str] = None,
    ) -> Any:
        data: dict[str, Any] = {"name": name, "limit": max(1, min(int(limit), 25))}
        if media_type:
            data["media_type"] = [media_type]
        return await self.call_service(
            "music_assistant", "search", data, return_response=True
        )

    async def set_climate_temperature(
        self,
        entity_id: str,
        temperature: float,
        hvac_mode: Optional[str] = None,
    ) -> Any:
        if hvac_mode:
            await self.call_service(
                "climate",
                "set_hvac_mode",
                {"entity_id": entity_id, "hvac_mode": hvac_mode},
            )
        return await self.call_service(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": float(temperature)},
        )


_client: Optional[HomeAssistantREST] = None


def get_ha_client() -> HomeAssistantREST:
    global _client
    if _client is None:
        _client = HomeAssistantREST()
    return _client


def reset_ha_client() -> None:
    global _client
    _client = None
