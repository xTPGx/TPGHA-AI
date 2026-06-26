"""Classify a Home Assistant entity into a category, room, capabilities, and
risk, with suggested aliases and a config mapping target (PART 2)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from ..entity_intelligence import (
    browser_mod_role,
    is_browser_mod_entity,
    smart_entity_name,
    unavailable_diagnosis,
)
from ..models.schemas import AppConfig, HAEntity
from . import capabilities as caps

UNAVAILABLE = {"unavailable", "unknown", "none", ""}

# domain -> the devices.yaml section an approved entity should map into.
_MAPPING_BY_DOMAIN = {
    "light": "lights",
    "fan": "fans",
    "camera": "cameras",
    "lock": "locks",
    "climate": "climate",
    "media_player": "speakers",
    "binary_sensor": "security_sensors",
    "person": "person",
    "device_tracker": "personal_devices",
}
# domain -> high-level category label.
_CATEGORY_BY_DOMAIN = {
    "light": "light", "switch": "switch", "fan": "fan", "climate": "climate",
    "lock": "lock", "cover": "cover", "camera": "camera",
    "media_player": "media", "alarm_control_panel": "alarm",
    "binary_sensor": "sensor", "sensor": "sensor", "siren": "siren",
    "vacuum": "vacuum", "scene": "scene", "script": "script",
    "automation": "automation", "person": "person",
    "device_tracker": "device_tracker", "device": "device",
    "weather": "weather",
    "calendar": "calendar", "todo": "todo", "select": "control",
    "number": "control", "humidifier": "climate", "water_heater": "climate",
    "valve": "valve", "button": "button",
}

_MOBILE_HINTS = (
    "iphone", "ipad", "ios", "android", "mobile", "phone", "watch",
    "app_version", "location_permission", "audio_output", "activity",
    "battery_state", "battery_level", "storage", "ssid", "bssid",
    "geocoded_location", "sim_1", "sim_2",
)

_NO_ROOM_HINTS = (
    "backup", "app version", "app_version", "location permission",
    "location_permission", "audio output", "audio_output", "bssid", "ssid",
    "connection type", "connection_type", "geocoded location",
    "geocoded_location", "last update", "last_update", "sim 1", "sim_1",
    "sim 2", "sim_2",
)


@dataclass
class EntityClassification:
    entity_id: str
    domain: str
    friendly_name: str
    state: str
    suggested_name: str
    likely_room: Optional[str]
    likely_device_type: str
    capabilities: list[str]
    risk_level: str
    suggested_aliases: list[str]
    suggested_category: str
    suggested_mapping: str
    approval_label: str
    auto_approvable: bool
    confidence: float
    rename_recommended: bool
    rename_reason: str
    unavailable_reason: str
    recommended_action: str
    browser_mod_role: str
    is_available: bool
    is_duplicate_candidate: bool
    reason: str
    status: str = "new"  # new|known|approved|ignored

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _room_alias_index(config: AppConfig) -> dict[str, str]:
    """Map a normalized room-word -> room id, from configured room aliases."""
    idx: dict[str, str] = {}
    for r in config.devices.rooms:
        for token in [r.id, r.name, *r.aliases]:
            idx[_norm(token)] = r.id
    return idx


def _norm(s: str) -> str:
    return " ".join(str(s).strip().lower().split())


def _tokens(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(s).lower().replace("_", " "))


def _contains_phrase(tokens: list[str], phrase: str) -> bool:
    p = _tokens(phrase)
    if not p or len(p) > len(tokens):
        return False
    return any(tokens[i:i + len(p)] == p for i in range(len(tokens) - len(p) + 1))


def _guess_room(entity_id: str, friendly: str, room_idx: dict[str, str],
                domain: str = "") -> Optional[str]:
    if domain in {"person", "device_tracker", "weather", "calendar", "todo"}:
        return None
    raw_text = f"{entity_id} {friendly}".lower().replace(".", " ").replace("_", " ")
    if any(hint.replace("_", " ") in raw_text for hint in _NO_ROOM_HINTS):
        return None
    tokens = _tokens(raw_text)
    # Prefer the longest matching room phrase.
    for phrase in sorted(room_idx, key=lambda p: len(_tokens(p)), reverse=True):
        if _contains_phrase(tokens, phrase):
            return room_idx[phrase]
    return None


def _suggest_aliases(friendly: str, room_id: Optional[str], domain: str) -> list[str]:
    out: list[str] = []
    if friendly:
        out.append(_norm(friendly))
    base = re.sub(r"['\u2019]s\b", "", _norm(friendly))
    if base and base not in out:
        out.append(base)
    if room_id and domain in ("light", "fan", "switch", "media_player", "climate"):
        kind = {"media_player": "speaker"}.get(domain, domain)
        out.append(f"{room_id.replace('_', ' ')} {kind}")
    return list(dict.fromkeys([a for a in out if a]))


def _merge_aliases(*groups: list[str]) -> list[str]:
    out: list[str] = []
    for group in groups:
        for alias in group or []:
            normed = _norm(alias)
            if normed and normed not in out:
                out.append(normed)
    return out


def _mobile_signal_text(entity: HAEntity, friendly: str) -> str:
    attrs = entity.attributes or {}
    return " ".join([
        entity.entity_id,
        friendly,
        str(attrs.get("device_class") or ""),
        str(attrs.get("icon") or ""),
        str(attrs.get("source_type") or ""),
    ]).lower()


def _is_personal_device_entity(entity: HAEntity, friendly: str) -> bool:
    text = _mobile_signal_text(entity, friendly)
    if entity.domain == "device_tracker":
        return True
    return any(hint in text for hint in _MOBILE_HINTS)


def _personal_device_type(entity: HAEntity, friendly: str) -> tuple[str, str]:
    text = f"{entity.entity_id} {friendly}".lower()
    if "iphone" in text:
        return "ios", "phone"
    if "ipad" in text:
        return "ios", "tablet"
    if "watch" in text:
        return "watchos", "watch"
    if "android" in text:
        return "android", "phone"
    return "mobile", "personal_device"


def _configured_entity_ids(config: AppConfig) -> set[str]:
    d = config.devices
    ids: set[str] = set()
    for c in d.cameras:
        ids.add(c.entity_id)
    for lk in d.locks:
        ids.add(lk.entity_id)
        if lk.battery_sensor:
            ids.add(lk.battery_sensor)
    for sp in d.speakers:
        ids.add(sp.entity_id)
    for dp in d.displays:
        if dp.entity_id:
            ids.add(dp.entity_id)
    for cl in d.climate:
        ids.add(cl.entity_id)
    for da in d.device_aliases:
        ids.add(da.entity_id)
    for ss in d.security_sensors:
        ids.add(ss.entity_id)
    for pd in d.personal_devices:
        ids.add(pd.entity_id)
    for r in d.rooms:
        for v in (r.speaker, r.camera, r.display, r.lock, r.climate):
            if v:
                ids.add(v)
        ids.update(r.lights)
        ids.update(r.fans)
    return ids


def _approval_label(mapping: str, category: str, domain: str) -> str:
    labels = {
        "lights": "Approve as light",
        "fans": "Approve as fan",
        "person": "Approve as person",
        "personal_devices": "Map as personal device",
        "cameras": "Map as camera",
        "locks": "Map as lock",
        "speakers": "Map as speaker",
        "displays": "Map as display",
        "climate": "Map as climate",
        "security_sensors": "Map as security sensor",
    }
    if mapping in labels:
        return labels[mapping]
    if category in {"diagnostic_sensor", "personal_device_sensor", "network", "system_backup"}:
        return "Approve as diagnostic"
    if domain == "switch":
        return "Approve as switch"
    return "Approve as status"


def _auto_approvable(domain: str, category: str, risk: str, duplicate: bool) -> bool:
    if duplicate or risk in {"high", "critical"}:
        return False
    if category in {"browser_mod_panel", "browser_mod_diagnostic"}:
        return False
    if category in {"diagnostic_sensor", "personal_device_sensor", "network", "system_backup"}:
        return False
    return domain in {"light", "fan", "person", "device_tracker"} or category == "personal_device"


def classify(entity: HAEntity, config: AppConfig,
             configured_ids: Optional[set[str]] = None,
             room_idx: Optional[dict[str, str]] = None,
             all_states: Optional[dict[str, HAEntity]] = None) -> EntityClassification:
    if configured_ids is None:
        configured_ids = _configured_entity_ids(config)
    if room_idx is None:
        room_idx = _room_alias_index(config)

    domain = entity.domain
    friendly = entity.friendly_name or entity.entity_id
    is_available = entity.state not in UNAVAILABLE
    room = _guess_room(entity.entity_id, friendly, room_idx, domain)
    category = _CATEGORY_BY_DOMAIN.get(domain, "other")
    capability = caps.DOMAIN_CAPABILITIES.get(domain, ["get_status"])
    risk = caps.risk_for_domain(domain)
    mapping = _MAPPING_BY_DOMAIN.get(domain, "device_aliases")
    aliases = _suggest_aliases(friendly, room, domain)
    likely_type = domain
    sibling_ids = list((all_states or {}).keys())
    smart = smart_entity_name(
        entity.entity_id,
        domain,
        friendly,
        room_id=room,
        siblings=[eid for eid in sibling_ids if eid != entity.entity_id],
    )
    suggested_name = smart["name"] or friendly
    aliases = _merge_aliases(smart["aliases"], aliases)
    health = unavailable_diagnosis(entity, all_states or {})
    browser_role = browser_mod_role(entity)

    if is_browser_mod_entity(entity.entity_id, friendly):
        category = "browser_mod_panel" if browser_role in {"panel_screen", "panel_speaker"} else "browser_mod_diagnostic"
        mapping = "device_aliases"
        likely_type = browser_role or "browser_mod"
        aliases = _merge_aliases(aliases, ["browser mod panel"])

    if entity.domain in {"sensor", "binary_sensor"} and _is_personal_device_entity(entity, friendly):
        category = "personal_device_sensor"
        mapping = "device_aliases"
        likely_type = "diagnostic_sensor"
        aliases = list(dict.fromkeys([*aliases, "personal device sensor"]))
    elif _is_personal_device_entity(entity, friendly):
        platform, device_type = _personal_device_type(entity, friendly)
        category = "personal_device"
        mapping = "personal_devices"
        likely_type = device_type
        aliases = list(dict.fromkeys([*aliases, platform, device_type]))

    if domain == "light" and "domain is light" in str(smart.get("rename_reason") or ""):
        aliases = [a for a in aliases if not _contains_phrase(_tokens(a), "fan")]
    elif domain == "fan" and "domain is fan" in str(smart.get("rename_reason") or ""):
        aliases = [a for a in aliases if not _contains_phrase(_tokens(a), "light")]
    if room and domain in {"light", "fan", "switch"}:
        aliases = [a for a in aliases if a != _norm(room)]

    avoid = set(config.devices.avoid)
    is_known = entity.entity_id in configured_ids
    is_ignored = entity.entity_id in avoid

    # Duplicate heuristic: an avoided sibling exists, or a known entity shares
    # the same room+domain (likely a duplicate surface like office vs office_tv).
    dup = entity.entity_id in avoid
    if not dup and not is_known and domain in {"media_player", "sensor", "binary_sensor"}:
        prefix = entity.entity_id.split(".", 1)[0]
        for other in configured_ids:
            if other.startswith(prefix + ".") and room and room.replace("_", "") in other.replace("_", ""):
                dup = True
                break

    status = "known" if is_known else ("ignored" if is_ignored else "new")
    reason_bits = [f"domain={domain}", f"risk={risk}"]
    if category == "personal_device":
        reason_bits.append("personal/mobile device signal")
    if is_known:
        reason_bits.append("already mapped in config")
    if not is_available:
        reason_bits.append("currently unavailable (kept, not auto-ignored)")
        if health.get("reason"):
            reason_bits.append(str(health["reason"]))
    if dup:
        reason_bits.append("possible duplicate surface")
    if room:
        reason_bits.append(f"likely room {room}")
    auto_ok = is_available and _auto_approvable(domain, category, risk, dup)
    if auto_ok:
        reason_bits.append("safe obvious HA domain auto-map")

    return EntityClassification(
        entity_id=entity.entity_id,
        domain=domain,
        friendly_name=friendly,
        state=entity.state,
        suggested_name=suggested_name,
        likely_room=room,
        likely_device_type=likely_type,
        capabilities=capability,
        risk_level=risk,
        suggested_aliases=aliases,
        suggested_category=category,
        suggested_mapping=mapping,
        approval_label=_approval_label(mapping, category, domain),
        auto_approvable=auto_ok,
        confidence=1.0 if domain in _CATEGORY_BY_DOMAIN else 0.65,
        rename_recommended=bool(smart.get("rename_recommended")),
        rename_reason=str(smart.get("rename_reason") or ""),
        unavailable_reason=str(health.get("reason") or "") if not is_available else "",
        recommended_action=str(health.get("recommended_action") or ""),
        browser_mod_role=browser_role,
        is_available=is_available,
        is_duplicate_candidate=dup,
        reason="; ".join(reason_bits),
        status=status,
    )
