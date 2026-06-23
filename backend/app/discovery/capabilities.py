"""Capability + risk + generic service mapping.

Single source of truth shared by the classifier (PART 2) and the generic
capability-based control (PART 3). Lets us stop writing one-off tool logic per
device type: a domain + action + optional value deterministically maps to a
vetted Home Assistant service, with sensitivity and risk attached.
"""
from __future__ import annotations

from typing import Any, Optional

# ---------------------------------------------------------------------------
# Capabilities advertised per domain (PART 2 spec). The `_sensitive` suffix
# marks capabilities that must be confirmation-gated.
# ---------------------------------------------------------------------------
DOMAIN_CAPABILITIES: dict[str, list[str]] = {
    "light": ["turn_on", "turn_off", "set_brightness", "set_color", "set_color_temp"],
    "switch": ["turn_on", "turn_off"],
    "fan": ["turn_on", "turn_off", "set_percentage", "set_preset_mode", "oscillate"],
    "climate": ["set_temperature", "set_hvac_mode", "get_current_temperature",
                "get_target_temperature"],
    "lock": ["lock", "unlock_sensitive", "get_status"],
    "cover": ["open_sensitive_if_garage", "close", "stop", "get_status"],
    "camera": ["view", "snapshot", "stream", "get_status"],
    "media_player": ["play", "pause", "stop", "volume", "play_media", "select_source"],
    "alarm_control_panel": ["arm_home_sensitive", "arm_away_sensitive",
                            "arm_night_sensitive", "disarm_sensitive", "get_status"],
    "binary_sensor": ["get_status"],
    "sensor": ["get_status"],
    "siren": ["turn_on_sensitive", "turn_off"],
    "vacuum": ["start", "stop", "return_to_base"],
    "button": ["press"],
    "scene": ["activate"],
    "script": ["run"],
    "automation": ["enable", "disable", "get_status"],
    "person": ["get_status"],
    "device_tracker": ["get_status"],
    "weather": ["get_status"],
    "calendar": ["get_status"],
    "todo": ["get_status"],
    "select": ["select_option"],
    "number": ["set_value"],
    "humidifier": ["turn_on", "turn_off", "set_humidity"],
    "water_heater": ["set_temperature", "set_operation_mode", "get_status"],
    "valve": ["open_sensitive", "close"],
}

SUPPORTED_DOMAINS = list(DOMAIN_CAPABILITIES.keys())

# ---------------------------------------------------------------------------
# Risk by domain (PART 2). Critical risk is action-specific (see SENSITIVE_*).
# ---------------------------------------------------------------------------
_RISK_BY_DOMAIN: dict[str, str] = {
    "light": "low", "switch": "low", "fan": "low", "scene": "low",
    "script": "low", "media_player": "low", "button": "low",
    "binary_sensor": "low", "sensor": "low", "person": "low",
    "device_tracker": "low", "weather": "low", "calendar": "low", "todo": "low",
    "climate": "medium", "vacuum": "medium", "humidifier": "medium",
    "water_heater": "medium", "valve": "medium", "number": "medium",
    "select": "medium", "automation": "medium",
    "camera": "high", "cover": "high", "lock": "high", "siren": "high",
    "alarm_control_panel": "high",
}

# Normalized sensitive action keys (match permissions.yaml sensitive_actions).
SENSITIVE_ACTION_KEYS = {
    "unlock_door", "open_garage", "disarm_alarm", "disable_camera",
    "disable_security", "change_lock_code", "disable_notifications",
    "remove_device", "delete_automation",
}


def risk_for_domain(domain: str) -> str:
    return _RISK_BY_DOMAIN.get(domain, "low")


# ---------------------------------------------------------------------------
# Action normalization. Maps loose action words to canonical actions.
# ---------------------------------------------------------------------------
_ACTION_ALIASES = {
    "on": "turn_on", "turn on": "turn_on", "enable": "turn_on",
    "off": "turn_off", "turn off": "turn_off", "disable": "turn_off",
    "open": "open", "close": "close", "shut": "close", "stop": "stop",
    "lock": "lock", "unlock": "unlock",
    "play": "play", "resume": "play", "pause": "pause",
    "volume": "set_volume", "set volume": "set_volume",
    "percentage": "set_percentage", "percent": "set_percentage",
    "speed": "set_percentage", "level": "set_percentage",
    "power": "set_percentage", "fan speed": "set_percentage",
    "fan level": "set_percentage",
    "temperature": "set_temperature", "temp": "set_temperature",
    "mode": "set_hvac_mode", "hvac": "set_hvac_mode",
    "arm": "arm_away", "arm home": "arm_home", "arm away": "arm_away",
    "arm night": "arm_night", "disarm": "disarm",
    "activate": "activate", "run": "run", "start": "start",
    "press": "press", "status": "status", "query": "status",
    "brightness": "set_brightness", "dim": "set_brightness",
}


def normalize_action(action: str) -> str:
    a = (action or "").strip().lower()
    if a in _ACTION_ALIASES:
        return _ACTION_ALIASES[a]
    return a.replace(" ", "_")


class ServicePlan:
    """A resolved, vetted Home Assistant service call (or query/sensitive gate)."""

    def __init__(self, ok: bool, domain: str = "", service: str = "",
                 data: Optional[dict] = None, sensitive: bool = False,
                 sensitive_key: Optional[str] = None, risk: str = "low",
                 query: bool = False, reason: str = ""):
        self.ok = ok
        self.domain = domain
        self.service = service
        self.data = data or {}
        self.sensitive = sensitive
        self.sensitive_key = sensitive_key
        self.risk = risk
        self.query = query
        self.reason = reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "domain": self.domain, "service": self.service,
            "data": self.data, "sensitive": self.sensitive,
            "sensitive_key": self.sensitive_key, "risk": self.risk,
            "query": self.query, "reason": self.reason,
        }


def _is_garage_or_gate(entity_id: str, friendly: str = "", device_class: str = "") -> bool:
    text = f"{entity_id} {friendly} {device_class}".lower()
    return any(k in text for k in ("garage", "gate"))


def plan_for(
    domain: str,
    action: str,
    value: Any = None,
    entity_id: str = "",
    friendly: str = "",
    device_class: str = "",
) -> ServicePlan:
    """Map (domain, action, value) -> a vetted ServicePlan.

    Sensitive operations set sensitive=True and a sensitive_key so the router
    gates them behind confirmation. Only allowlisted services are produced.
    """
    a = normalize_action(action)
    eid = {"entity_id": entity_id} if entity_id else {}

    # ---- queries ----
    if a in ("status", "get_status"):
        return ServicePlan(True, query=True, risk=risk_for_domain(domain),
                           reason=f"Query status of {domain}.")

    # ---- light ----
    if domain == "light":
        if a == "turn_on":
            return ServicePlan(True, "light", "turn_on", eid, risk="low")
        if a == "turn_off":
            return ServicePlan(True, "light", "turn_off", eid, risk="low")
        if a == "set_brightness":
            pct = _as_pct(value)
            return ServicePlan(True, "light", "turn_on",
                               {**eid, "brightness_pct": pct}, risk="low")
        if a in ("set_color", "set_color_temp"):
            return ServicePlan(True, "light", "turn_on", eid, risk="low",
                               reason="Color control accepted (value passthrough).")

    # ---- switch ----
    if domain == "switch":
        if a == "turn_on":
            return ServicePlan(True, "switch", "turn_on", eid, risk="low")
        if a == "turn_off":
            return ServicePlan(True, "switch", "turn_off", eid, risk="low")

    # ---- fan ----
    if domain == "fan":
        if a == "turn_on":
            return ServicePlan(True, "fan", "turn_on", eid, risk="low")
        if a == "turn_off":
            return ServicePlan(True, "fan", "turn_off", eid, risk="low")
        if a == "set_percentage":
            pct = _as_pct(value)
            return ServicePlan(True, "fan", "set_percentage",
                               {**eid, "percentage": pct}, risk="low")
        if a == "set_preset_mode":
            return ServicePlan(True, "fan", "set_preset_mode",
                               {**eid, "preset_mode": str(value)}, risk="low")
        if a == "oscillate":
            return ServicePlan(True, "fan", "oscillate",
                               {**eid, "oscillating": bool(value)}, risk="low")

    # ---- climate ----
    if domain == "climate":
        if a == "set_temperature":
            try:
                temp = float(value)
            except (TypeError, ValueError):
                return ServicePlan(False, reason="Temperature value required.")
            return ServicePlan(True, "climate", "set_temperature",
                               {**eid, "temperature": temp}, risk="medium")
        if a == "set_hvac_mode":
            return ServicePlan(True, "climate", "set_hvac_mode",
                               {**eid, "hvac_mode": str(value)}, risk="medium")

    # ---- lock ----
    if domain == "lock":
        if a == "lock":
            return ServicePlan(True, "lock", "lock", eid, risk="high")
        if a == "unlock":
            return ServicePlan(True, "lock", "unlock", eid, sensitive=True,
                               sensitive_key="unlock_door", risk="critical")

    # ---- cover ----
    if domain == "cover":
        garage = _is_garage_or_gate(entity_id, friendly, device_class)
        if a == "open":
            if garage:
                return ServicePlan(True, "cover", "open_cover", eid, sensitive=True,
                                   sensitive_key="open_garage", risk="critical")
            return ServicePlan(True, "cover", "open_cover", eid, risk="high")
        if a == "close":
            return ServicePlan(True, "cover", "close_cover", eid, risk="medium")
        if a == "stop":
            return ServicePlan(True, "cover", "stop_cover", eid, risk="medium")

    # ---- media_player ----
    if domain == "media_player":
        if a == "play":
            return ServicePlan(True, "media_player", "media_play", eid, risk="low")
        if a == "pause":
            return ServicePlan(True, "media_player", "media_pause", eid, risk="low")
        if a == "stop":
            return ServicePlan(True, "media_player", "media_stop", eid, risk="low")
        if a == "set_volume":
            lvl = _as_volume(value)
            return ServicePlan(True, "media_player", "volume_set",
                               {**eid, "volume_level": lvl}, risk="low")
        if a == "select_source":
            return ServicePlan(True, "media_player", "select_source",
                               {**eid, "source": str(value)}, risk="low")

    # ---- alarm_control_panel ----
    if domain == "alarm_control_panel":
        if a == "disarm":
            return ServicePlan(True, "alarm_control_panel", "alarm_disarm", eid,
                               sensitive=True, sensitive_key="disarm_alarm",
                               risk="critical")
        if a in ("arm_home", "arm_away", "arm_night"):
            return ServicePlan(True, "alarm_control_panel", f"alarm_{a}", eid,
                               risk="high")

    # ---- siren ----
    if domain == "siren":
        if a == "turn_on":
            return ServicePlan(True, "siren", "turn_on", eid, risk="high")
        if a == "turn_off":
            return ServicePlan(True, "siren", "turn_off", eid, risk="medium")

    # ---- vacuum ----
    if domain == "vacuum":
        if a == "start":
            return ServicePlan(True, "vacuum", "start", eid, risk="medium")
        if a == "stop":
            return ServicePlan(True, "vacuum", "stop", eid, risk="medium")
        if a == "return_to_base":
            return ServicePlan(True, "vacuum", "return_to_base", eid, risk="medium")

    # ---- scene / script / button ----
    if domain == "scene" and a in ("activate", "turn_on"):
        return ServicePlan(True, "scene", "turn_on", eid, risk="low")
    if domain == "script" and a in ("run", "turn_on"):
        return ServicePlan(True, "script", "turn_on", eid, risk="low")
    if domain == "button" and a in ("press", "turn_on"):
        return ServicePlan(True, "button", "press", eid, risk="low")

    # ---- automation ----
    if domain == "automation":
        if a in ("turn_on", "enable"):
            return ServicePlan(True, "automation", "turn_on", eid, risk="medium")
        if a in ("turn_off", "disable"):
            return ServicePlan(True, "automation", "turn_off", eid, risk="medium")

    # ---- valve ----
    if domain == "valve":
        if a == "open":
            return ServicePlan(True, "valve", "open_valve", eid, sensitive=True,
                               sensitive_key="open_garage", risk="high")
        if a == "close":
            return ServicePlan(True, "valve", "close_valve", eid, risk="medium")

    # ---- number / select / humidifier ----
    if domain == "number" and a == "set_value":
        try:
            return ServicePlan(True, "number", "set_value",
                               {**eid, "value": float(value)}, risk="medium")
        except (TypeError, ValueError):
            return ServicePlan(False, reason="Numeric value required.")
    if domain == "select" and a in ("select_option", "set"):
        return ServicePlan(True, "select", "select_option",
                           {**eid, "option": str(value)}, risk="medium")

    return ServicePlan(False, reason=f"No vetted service for {domain}.{a}.")


def _as_pct(value: Any) -> int:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 100
    if v <= 1:
        v *= 100
    return int(max(0, min(100, round(v))))


def _as_volume(value: Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.3
    if v > 1:
        v /= 100.0
    return max(0.0, min(1.0, v))
