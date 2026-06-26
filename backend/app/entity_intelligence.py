"""Entity naming and health hints shared by Discovery and live entity views."""
from __future__ import annotations

import re
from typing import Any, Iterable

from .models.schemas import HAEntity

UNAVAILABLE_STATES = {"unavailable", "unknown", "none", ""}

_DOMAIN_KIND = {
    "light": "light",
    "fan": "fan",
    "switch": "switch",
    "cover": "cover",
    "lock": "lock",
    "camera": "camera",
    "climate": "thermostat",
    "media_player": "speaker",
    "person": "person",
    "device_tracker": "device",
}

_BROWSER_MOD_HINT = "browser_mod"


def norm_text(value: str) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").split())


def humanize_id(value: str) -> str:
    text = re.sub(r"[_\-]+", " ", str(value or "")).strip()
    text = re.sub(r"\s+", " ", text)
    if not text:
        return ""
    words = []
    for word in text.split():
        low = word.lower()
        if low in {"iphone", "ios"}:
            words.append("iPhone" if low == "iphone" else "iOS")
        elif low == "ipad":
            words.append("iPad")
        elif low in {"tv", "usb", "id", "bssid", "ssid"}:
            words.append(low.upper())
        else:
            words.append(word[:1].upper() + word[1:])
    return " ".join(words)


def entity_slug(entity_id: str) -> str:
    return str(entity_id or "").split(".", 1)[-1]


def is_browser_mod_entity(entity_id: str, friendly_name: str = "") -> bool:
    return _BROWSER_MOD_HINT in f"{entity_id} {friendly_name}".lower()


def browser_mod_role(entity: HAEntity) -> str:
    if not is_browser_mod_entity(entity.entity_id, entity.friendly_name or ""):
        return ""
    slug = entity_slug(entity.entity_id)
    if entity.domain == "light" and slug.endswith("_screen"):
        return "panel_screen"
    if entity.domain == "media_player":
        return "panel_speaker"
    if entity.domain == "camera":
        return "panel_camera"
    if entity.domain in {"sensor", "binary_sensor"}:
        return "panel_diagnostic"
    return "panel_entity"


def same_slug_siblings(entity_id: str, all_entity_ids: Iterable[str]) -> list[str]:
    slug = entity_slug(entity_id)
    return sorted(eid for eid in all_entity_ids if eid != entity_id and entity_slug(eid) == slug)


def _room_display(room_id: str | None, fallback: str = "") -> str:
    if room_id:
        return humanize_id(room_id)
    return humanize_id(fallback)


def _has_kind(text: str, kind: str) -> bool:
    normalized = norm_text(text)
    if not normalized or not kind:
        return False
    if kind == "light":
        return bool(re.search(r"\blights?\b|\blamp\b|\bhex\b", normalized))
    if kind == "fan":
        return bool(re.search(r"\bfans?\b", normalized))
    if kind == "switch":
        return bool(re.search(r"\bswitch\b|\boutlet\b|\bplug\b", normalized))
    return kind in normalized.split()


def _friendly_is_room_only(friendly: str, room_id: str | None) -> bool:
    if not friendly:
        return False
    room = norm_text(room_id or "")
    return bool(room and norm_text(friendly) == room)


def _strip_kind_words(value: str, kind: str) -> str:
    if not value or not kind:
        return value
    text = norm_text(value)
    if kind == "light":
        text = re.sub(r"\b(lights?|lamp|lamps|hex)\b", "", text)
    elif kind == "fan":
        text = re.sub(r"\b(fans?)\b", "", text)
    else:
        text = re.sub(rf"\b{re.escape(kind)}s?\b", "", text)
    return humanize_id(text.strip())


def smart_entity_name(
    entity_id: str,
    domain: str,
    friendly_name: str = "",
    room_id: str | None = None,
    siblings: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Return a Jarvis-friendly name/alias set without renaming HA itself."""
    friendly = str(friendly_name or "").strip()
    slug = entity_slug(entity_id)
    slug_name = humanize_id(slug)
    base_name = friendly or slug_name or entity_id
    kind = _DOMAIN_KIND.get(domain, domain or "device")
    sibling_ids = list(siblings or [])
    sibling_domains = {eid.split(".", 1)[0] for eid in sibling_ids if "." in eid}
    rename_reason = ""
    room_display = _room_display(room_id, slug)
    suggested = base_name

    if is_browser_mod_entity(entity_id, friendly):
        role = browser_mod_role(HAEntity(
            entity_id=entity_id,
            state="unknown",
            friendly_name=friendly,
            domain=domain,
            available=False,
        ))
        role_name = {
            "panel_screen": "Panel Screen",
            "panel_speaker": "Panel Speaker",
            "panel_camera": "Panel Camera",
            "panel_diagnostic": "Panel Diagnostic",
        }.get(role, "Panel")
        suffix = re.sub(r"^browser mod\s*", "", humanize_id(slug)).strip()
        suggested = f"{suffix} {role_name}".strip() if suffix else role_name
        rename_reason = "Browser Mod entity is a panel capability, not a house device."
    elif domain in {"light", "fan", "switch"}:
        wrong_kind = "fan" if domain == "light" else ("light" if domain == "fan" else "")
        sibling_with_correct_domain = domain in sibling_domains
        friendly_has_wrong_kind = bool(wrong_kind and _has_kind(base_name, wrong_kind))
        slug_has_wrong_kind = bool(wrong_kind and _has_kind(slug_name, wrong_kind))
        if friendly_has_wrong_kind or (slug_has_wrong_kind and sibling_with_correct_domain):
            room_base = _strip_kind_words(room_id or friendly or slug_name, wrong_kind) or room_display
            suggested = f"{room_base} {kind.title()}".strip()
            rename_reason = (
                f"HA name looks like a {wrong_kind}, but the entity domain is {domain}; "
                f"use the domain-specific name for Jarvis."
            )
        elif _friendly_is_room_only(base_name, room_id) or not _has_kind(base_name, kind):
            suggested = f"{base_name} {kind.title()}".strip()
            rename_reason = f"HA friendly name omits the {kind} type."

    aliases = _smart_aliases(
        entity_id=entity_id,
        domain=domain,
        friendly=friendly,
        suggested=suggested,
        room_id=room_id,
        kind=kind,
        rename_reason=rename_reason,
    )
    return {
        "name": suggested,
        "aliases": aliases,
        "rename_recommended": bool(rename_reason and norm_text(suggested) != norm_text(base_name)),
        "rename_reason": rename_reason,
        "device_kind": kind,
    }


def _smart_aliases(
    entity_id: str,
    domain: str,
    friendly: str,
    suggested: str,
    room_id: str | None,
    kind: str,
    rename_reason: str,
) -> list[str]:
    aliases: list[str] = []
    for item in (suggested,):
        if item:
            aliases.append(norm_text(item))

    # Avoid poisoning the resolver with aliases like "den fan" for a light
    # entity. The raw HA friendly name stays visible in the UI, but Jarvis
    # should prefer the corrected domain-aware alias.
    raw_is_wrong_kind = (
        (domain == "light" and _has_kind(friendly, "fan"))
        or (domain == "fan" and _has_kind(friendly, "light"))
    )
    if friendly and not raw_is_wrong_kind:
        normalized_friendly = norm_text(friendly)
        # A bare room alias such as "garage" is too ambiguous when both
        # garage fan and garage light exist.
        if not (room_id and normalized_friendly == norm_text(room_id) and domain in {"light", "fan"}):
            aliases.append(normalized_friendly)

    if room_id and domain in {"light", "fan", "switch"}:
        aliases.append(f"{norm_text(room_id)} {kind}")
    if is_browser_mod_entity(entity_id, friendly):
        aliases.append("browser mod panel")
    return list(dict.fromkeys(a for a in aliases if a))


def unavailable_diagnosis(entity: HAEntity, all_states: dict[str, HAEntity] | None = None) -> dict[str, Any]:
    state = str(entity.state or "").lower()
    available = state not in UNAVAILABLE_STATES
    siblings = same_slug_siblings(entity.entity_id, (all_states or {}).keys())
    sibling_states = {
        eid: {
            "domain": (all_states or {}).get(eid).domain,
            "state": (all_states or {}).get(eid).state,
            "available": (all_states or {}).get(eid).available,
        }
        for eid in siblings
        if (all_states or {}).get(eid)
    }
    if available:
        return {
            "status": "online",
            "severity": "ok",
            "reason": "Home Assistant is reporting a live state.",
            "recommended_action": "",
            "siblings": sibling_states,
        }

    attrs = entity.attributes or {}
    text = f"{entity.entity_id} {entity.friendly_name or ''}".lower()
    if is_browser_mod_entity(entity.entity_id, entity.friendly_name or ""):
        reason = (
            "Browser Mod entity is unavailable because that browser/panel is not currently "
            "registered or connected to Home Assistant."
        )
        action = "Open Home Assistant on that tablet/browser, verify Browser Mod sees it, then reload Browser Mod if needed."
    elif attrs.get("restored") is True:
        reason = "Home Assistant restored this entity from history, but the integration has not provided a current state."
        action = "Reload or repair the owning integration and confirm the physical device is powered and online."
    elif entity.domain in {"fan", "light", "select", "number", "sensor"} and (
        "tuya" in text or "smart life" in text or "fan" in text or siblings
    ):
        reason = "This looks like a split device surface from an integration such as Tuya/Smart Life, and HA is not receiving live state for this entity."
        action = "Check the device in Smart Life/Tuya, confirm power/Wi-Fi, reload the Tuya integration, then rescan TPG HomeAI."
    elif state == "unknown":
        reason = "Home Assistant knows the entity but does not currently know its value."
        action = "Wait for the integration to publish a value or reload the integration if it stays unknown."
    else:
        reason = "Home Assistant reports this entity as unavailable."
        action = "Check device power/network, reload the integration, and remove stale entities in HA if this device was replaced."

    if sibling_states:
        action += " Sibling entities with the same base id were found, so keep the working sibling and avoid mapping stale duplicates."
    return {
        "status": state or "unavailable",
        "severity": "warn",
        "reason": reason,
        "recommended_action": action,
        "siblings": sibling_states,
    }


def enrich_entity(entity: HAEntity, all_states: dict[str, HAEntity] | None = None,
                  room_id: str | None = None) -> dict[str, Any]:
    siblings = same_slug_siblings(entity.entity_id, (all_states or {}).keys())
    naming = smart_entity_name(
        entity.entity_id,
        entity.domain,
        entity.friendly_name or "",
        room_id=room_id,
        siblings=siblings,
    )
    role = browser_mod_role(entity)
    health = unavailable_diagnosis(entity, all_states)
    return {
        **entity.model_dump(),
        "smart_name": naming["name"],
        "smart_aliases": naming["aliases"],
        "rename_recommended": naming["rename_recommended"],
        "rename_reason": naming["rename_reason"],
        "device_kind": naming["device_kind"],
        "browser_mod_role": role,
        "jarvis_use": _jarvis_use(entity, role),
        "health": health,
        "unavailable_reason": health["reason"] if health["severity"] != "ok" else "",
        "recommended_action": health["recommended_action"],
    }


def _jarvis_use(entity: HAEntity, browser_role: str) -> str:
    if browser_role:
        if browser_role in {"panel_screen", "panel_speaker"}:
            return "panel_control"
        return "panel_diagnostic"
    if entity.domain in {"light", "fan", "lock", "cover", "climate", "media_player", "camera"}:
        return "house_control"
    if entity.domain in {"person", "device_tracker"}:
        return "presence"
    if entity.domain in {"sensor", "binary_sensor"}:
        return "status"
    return "support"
