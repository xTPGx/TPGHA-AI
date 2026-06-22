"""Recommendation helpers: which discovered entities to surface/auto-approve."""
from __future__ import annotations

from typing import Any

from .classifier import EntityClassification

# Domains we recommend mapping for AI control (actionable, useful).
_RECOMMENDED_DOMAINS = {
    "light", "switch", "fan", "climate", "lock", "cover", "camera",
    "media_player", "scene", "script", "alarm_control_panel", "siren", "vacuum",
}
# Domains that are usually informational only (lower priority to map).
_INFO_DOMAINS = {"sensor", "binary_sensor", "weather", "person",
                 "device_tracker", "calendar", "todo", "button"}


def is_recommended(c: EntityClassification) -> bool:
    """Recommend mapping if it's a controllable domain and not a duplicate."""
    return c.domain in _RECOMMENDED_DOMAINS and not c.is_duplicate_candidate


def is_risky(c: EntityClassification) -> bool:
    return c.risk_level in ("high", "critical")


def should_auto_approve(c: EntityClassification, auto_low_risk: bool,
                        auto_domains: list[str]) -> bool:
    """Auto-approve only low-risk entities when explicitly enabled, or domains
    the user opted into. Never auto-approves risky/critical entities."""
    if c.status != "new" or c.is_duplicate_candidate:
        return False
    if c.risk_level in ("high", "critical"):
        return False
    if c.domain in set(auto_domains or []):
        return True
    return bool(auto_low_risk) and c.risk_level == "low"


def summarize(classifications: list[EntityClassification]) -> dict[str, Any]:
    buckets = {
        "known_entities": [],
        "new_entities": [],
        "unavailable_entities": [],
        "duplicate_candidates": [],
        "ignored_entities": [],
        "recommended_entities": [],
        "risky_entities": [],
    }
    for c in classifications:
        if c.status == "known":
            buckets["known_entities"].append(c.entity_id)
        elif c.status == "ignored":
            buckets["ignored_entities"].append(c.entity_id)
        else:
            buckets["new_entities"].append(c.entity_id)
        if not c.is_available:
            buckets["unavailable_entities"].append(c.entity_id)
        if c.is_duplicate_candidate:
            buckets["duplicate_candidates"].append(c.entity_id)
        if c.status == "new" and is_recommended(c):
            buckets["recommended_entities"].append(c.entity_id)
        if is_risky(c):
            buckets["risky_entities"].append(c.entity_id)
    return {k: {"count": len(v), "entities": v} for k, v in buckets.items()}
