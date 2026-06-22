"""TPG HomeAI sensors: status, pending approvals, unavailable devices, last
command."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN
from .entity import TPGHomeAIEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities([
        StatusSensor(coordinator, entry),
        PendingApprovalsSensor(coordinator, entry),
        UnavailableDevicesSensor(coordinator, entry),
        LastCommandSensor(coordinator, entry),
    ])


class StatusSensor(TPGHomeAIEntity, SensorEntity):
    _attr_name = "Status"
    _attr_icon = "mdi:robot-happy"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "status")

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> str:
        if not self.coordinator.last_update_success:
            return "offline"
        return "ok" if self._state.get("config_ok", True) else "degraded"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._state
        return {
            "version": s.get("version"),
            "config_ok": s.get("config_ok"),
            "config_error": s.get("config_error"),
            "pending_approvals": s.get("pending_approvals"),
            "known_devices": s.get("known_devices"),
            "unavailable_devices": s.get("unavailable_devices"),
            "pending_confirmations": len(s.get("pending_confirmations", []) or []),
            "last_scan_ts": s.get("last_scan_ts"),
        }


class PendingApprovalsSensor(TPGHomeAIEntity, SensorEntity):
    _attr_name = "Pending approvals"
    _attr_icon = "mdi:clipboard-alert"
    _attr_native_unit_of_measurement = "devices"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "pending_approvals")

    @property
    def native_value(self) -> int:
        return int(self._state.get("pending_approvals", 0) or 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"pending_confirmations": self._state.get("pending_confirmations", [])}


class UnavailableDevicesSensor(TPGHomeAIEntity, SensorEntity):
    _attr_name = "Unavailable devices"
    _attr_icon = "mdi:lan-disconnect"
    _attr_native_unit_of_measurement = "devices"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "unavailable_devices")

    @property
    def native_value(self) -> int:
        return int(self._state.get("unavailable_devices", 0) or 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"entities": self._state.get("unavailable", [])}


class LastCommandSensor(TPGHomeAIEntity, SensorEntity):
    _attr_name = "Last command"
    _attr_icon = "mdi:message-text"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "last_command")

    @property
    def native_value(self) -> str | None:
        last = self._state.get("last_command") or {}
        msg = last.get("message")
        return (msg[:255] if msg else "none")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        last = self._state.get("last_command") or {}
        return {
            "assistant": last.get("assistant"),
            "user": last.get("user"),
            "intent": last.get("intent"),
            "success": last.get("success"),
            "executed": last.get("executed"),
            "requires_confirmation": last.get("requires_confirmation"),
            "response": last.get("response_message"),
        }
