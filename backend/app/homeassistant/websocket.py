"""Home Assistant WebSocket client (placeholder for live state streaming).

The MVP uses the REST API. This module sketches the WebSocket auth + subscribe
flow so a future iteration can stream state_changed events for real-time UI.
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Optional

from ..settings import get_settings

logger = logging.getLogger("tpg.ha.ws")


class HomeAssistantWebSocket:
    """Minimal scaffold. Not wired into the MVP request path yet."""

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

    async def stream_state_changes(self) -> AsyncIterator[dict[str, Any]]:
        """Connect, authenticate, subscribe to state_changed, yield events.

        Implemented lazily with `websockets` so the MVP has no hard dependency
        unless WebSocket streaming is actually used.
        """
        try:
            import websockets  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "websockets package not installed; WebSocket streaming is a "
                "future feature in the MVP."
            ) from exc

        async with websockets.connect(self.ws_url) as ws:
            await ws.recv()  # auth_required
            await ws.send(json.dumps({"type": "auth", "access_token": self._token}))
            await ws.recv()  # auth_ok / auth_invalid
            await ws.send(
                json.dumps({"id": 1, "type": "subscribe_events", "event_type": "state_changed"})
            )
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("type") == "event":
                    yield msg["event"]
