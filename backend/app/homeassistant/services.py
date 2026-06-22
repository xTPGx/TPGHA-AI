"""Higher-level helpers over the REST client: state caching & entity views.

Provides a normalized view of Home Assistant entities used by the resolver,
plus a short-lived cache so a single command doesn't re-fetch /states.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from ..models.schemas import HAEntity
from .rest import UNAVAILABLE_STATES, HAError, get_ha_client


class StatesCache:
    """Caches the full /states payload for a few seconds."""

    def __init__(self, ttl_seconds: float = 5.0) -> None:
        self.ttl = ttl_seconds
        self._ts: float = 0.0
        self._states: dict[str, HAEntity] = {}

    def _expired(self) -> bool:
        return (time.monotonic() - self._ts) > self.ttl

    async def get_states(self, force: bool = False) -> dict[str, HAEntity]:
        if force or self._expired() or not self._states:
            await self.refresh()
        return self._states

    async def refresh(self) -> dict[str, HAEntity]:
        client = get_ha_client()
        raw = await client.get_states()
        states: dict[str, HAEntity] = {}
        for item in raw:
            entity = normalize_entity(item)
            states[entity.entity_id] = entity
        self._states = states
        self._ts = time.monotonic()
        return states

    def get(self, entity_id: str) -> Optional[HAEntity]:
        return self._states.get(entity_id)


def normalize_entity(item: dict[str, Any]) -> HAEntity:
    entity_id = item.get("entity_id", "")
    state = item.get("state", "")
    attrs = item.get("attributes", {}) or {}
    domain = entity_id.split(".", 1)[0] if "." in entity_id else ""
    return HAEntity(
        entity_id=entity_id,
        state=state,
        friendly_name=attrs.get("friendly_name"),
        domain=domain,
        available=state not in UNAVAILABLE_STATES,
        attributes=attrs,
    )


_cache: Optional[StatesCache] = None


def get_states_cache() -> StatesCache:
    global _cache
    if _cache is None:
        _cache = StatesCache()
    return _cache


async def safe_get_states() -> dict[str, HAEntity]:
    """Return live states, or {} if HA is unreachable (resolver still works)."""
    try:
        return await get_states_cache().get_states()
    except HAError:
        return {}
