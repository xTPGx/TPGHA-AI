"""Discovery scanner (PART 2).

Pulls all Home Assistant states, classifies each entity, syncs results to
SQLite, applies optional auto-approval, and returns categorized buckets. It
never deletes anything and never auto-ignores unavailable entities.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from ..config_loader import get_config
from ..events import EVT_DISCOVERY_FOUND, get_event_bus
from ..homeassistant.services import safe_get_states
from . import recommendations, registry
from .classifier import (
    EntityClassification,
    _configured_entity_ids,
    _room_alias_index,
    classify,
)

logger = logging.getLogger("tpg.discovery.scanner")

# Only classify entities in supported, useful domains by default.
from .capabilities import SUPPORTED_DOMAINS  # noqa: E402

_last_scan: dict[str, Any] = {"ts": None, "summary": None}


async def scan(auto_low_risk: bool = False,
               auto_domains: Optional[list[str]] = None) -> dict[str, Any]:
    config = get_config()
    states = await safe_get_states()
    configured = _configured_entity_ids(config)
    room_idx = _room_alias_index(config)

    classifications: list[EntityClassification] = []
    for entity in states.values():
        if entity.domain not in SUPPORTED_DOMAINS:
            continue
        classifications.append(classify(entity, config, configured, room_idx))

    registry.sync_classifications(classifications)

    # Optional auto-approval (never for high/critical).
    auto_approved: list[str] = []
    for c in classifications:
        if recommendations.should_auto_approve(c, auto_low_risk, auto_domains or []):
            registry.approve(c.entity_id, mapping=c.suggested_mapping,
                             room=c.likely_room, friendly_name=c.friendly_name,
                             aliases=c.suggested_aliases)
            auto_approved.append(c.entity_id)

    summary = recommendations.summarize(classifications)
    pending = [c.to_dict() for c in classifications
               if c.status == "new" and c.entity_id not in auto_approved]

    result = {
        "ok": True,
        "ha_reachable": bool(states),
        "total_entities": len(states),
        "classified": len(classifications),
        "summary": summary,
        "auto_approved": auto_approved,
        "pending": pending,
        "entities": [c.to_dict() for c in classifications],
    }

    import time
    _last_scan["ts"] = time.time()
    _last_scan["summary"] = summary

    new_count = summary["new_entities"]["count"]
    if new_count:
        get_event_bus().emit(EVT_DISCOVERY_FOUND, {
            "new_count": new_count,
            "entities": summary["new_entities"]["entities"][:25],
            "recommended": summary["recommended_entities"]["entities"][:25],
        })
    logger.info("Discovery scan: %d entities, %d new, %d unavailable",
                len(states), new_count, summary["unavailable_entities"]["count"])
    return result


def last_scan_summary() -> dict[str, Any]:
    return _last_scan


async def summary() -> dict[str, Any]:
    """Lightweight summary derived from persisted state (no live HA call)."""
    pending = registry.get_pending()
    all_rows = registry.get_all()
    unavailable = [r for r in all_rows if not r["is_available"]]
    return {
        "pending_count": len(pending),
        "known_count": len([r for r in all_rows if r["status"] in ("known", "approved")]),
        "unavailable_count": len(unavailable),
        "unavailable": [r["entity_id"] for r in unavailable],
        "pending": pending,
        "last_scan_ts": _last_scan["ts"],
    }
