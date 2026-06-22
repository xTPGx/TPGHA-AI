"""In-process event bus + last-command/state tracking.

The Home Assistant integration polls these (GET /events, GET /state) to fire
HA events, update sensors, and raise persistent notifications. Keeping it in
memory is fine for the single-process backend; restarts simply reset history.
"""
from __future__ import annotations

import itertools
import time
from collections import deque
from typing import Any, Optional

# Event type names (mirror the HA integration's event names).
EVT_DISCOVERY_FOUND = "tpg_homeai_discovery_found"
EVT_APPROVAL_REQUIRED = "tpg_homeai_approval_required"
EVT_CONFIRMATION_REQUIRED = "tpg_homeai_action_confirmation_required"
EVT_ACTION_EXECUTED = "tpg_homeai_action_executed"
EVT_ACTION_FAILED = "tpg_homeai_action_failed"


class EventBus:
    def __init__(self, maxlen: int = 300) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._seq = itertools.count(1)
        self.last_command: Optional[dict[str, Any]] = None

    def emit(self, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        evt = {
            "id": next(self._seq),
            "type": event_type,
            "ts": time.time(),
            "data": data,
        }
        self._events.append(evt)
        return evt

    def set_last_command(self, payload: dict[str, Any]) -> None:
        self.last_command = {**payload, "ts": time.time()}

    def recent(self, since_id: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        out = [e for e in self._events if e["id"] > since_id]
        return out[-limit:]

    def latest_id(self) -> int:
        return self._events[-1]["id"] if self._events else 0


_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
