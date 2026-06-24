"""Home Assistant WebSocket client.

Used for registry enrichment (areas/devices/entities) and future live state
streaming. All calls degrade cleanly so the REST-only path keeps working.
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Optional

from ..settings import get_settings

logger = logging.getLogger("tpg.ha.ws")


class HomeAssistantWebSocket:
    """Minimal HA WebSocket client for authenticated command calls."""

    def __init__(
        self, base_url: Optional[str] = None, token: Optional[str] = None
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.ha_base_url).rstrip("/")
        self._token = token or settings.home_assistant_token

    @property
    def ws_url(self) -> str:
        # ws(s)://host:port/api/websocket
        url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        return f"{url}/api/websocket"

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self._token)

    async def _connect(self):
        if not self.configured:
            raise RuntimeError("Home Assistant WebSocket is not configured.")
        try:
            import websockets  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("websockets package not installed.") from exc

        ws = await websockets.connect(self.ws_url)
        greeting = json.loads(await ws.recv())
        if greeting.get("type") != "auth_required":
            await ws.close()
            raise RuntimeError("Unexpected Home Assistant WebSocket greeting.")
        await ws.send(json.dumps({"type": "auth", "access_token": self._token}))
        auth = json.loads(await ws.recv())
        if auth.get("type") != "auth_ok":
            await ws.close()
            raise RuntimeError("Home Assistant WebSocket authentication failed.")
        return ws

    async def call(self, command_type: str, **payload: Any) -> Any:
        """Execute one HA WebSocket command and return its result."""
        async with await self._connect() as ws:
            req = {"id": 1, "type": command_type, **payload}
            await ws.send(json.dumps(req))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") != 1:
                    continue
                if not msg.get("success", False):
                    err = msg.get("error") or {}
                    raise RuntimeError(err.get("message") or f"HA WS command failed: {command_type}")
                return msg.get("result")

    async def fetch_registries(self) -> dict[str, Any]:
        """Fetch HA area, device, and entity registries.

        Home Assistant's registry commands are WebSocket-only. This data lets
        HomeAI group noisy diagnostic sensors into real devices and areas.
        """
        areas = await self.call("config/area_registry/list")
        devices = await self.call("config/device_registry/list")
        entities = await self.call("config/entity_registry/list")
        return {"areas": areas or [], "devices": devices or [], "entities": entities or []}

    async def fetch_auth_users(self) -> list[dict[str, Any]]:
        """Fetch Home Assistant auth users when the active token may access it.

        HA auth-user commands have changed names across releases and may be
        restricted by token type. Try known commands and let callers degrade if
        none are available.
        """
        errors: list[str] = []
        for command_type in ("config/auth/list", "auth/list"):
            try:
                result = await self.call(command_type)
            except Exception as exc:  # noqa: BLE001 - try next HA command
                errors.append(f"{command_type}: {exc}")
                continue
            if isinstance(result, dict):
                users = result.get("users") or result.get("data") or []
            else:
                users = result or []
            if isinstance(users, list):
                return [u for u in users if isinstance(u, dict)]
        raise RuntimeError("Could not fetch Home Assistant users. " + "; ".join(errors))

    async def stream_state_changes(self) -> AsyncIterator[dict[str, Any]]:
        """Connect, authenticate, subscribe to state_changed, yield events.

        Implemented lazily with `websockets` so the MVP has no hard dependency
        unless WebSocket streaming is actually used.
        """
        async with await self._connect() as ws:
            await ws.send(
                json.dumps({"id": 1, "type": "subscribe_events", "event_type": "state_changed"})
            )
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("type") == "event":
                    yield msg["event"]
