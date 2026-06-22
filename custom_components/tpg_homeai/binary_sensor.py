"""TPG HomeAI binary sensor: needs attention."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN
from .entity import TPGHomeAIEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities([NeedsAttentionBinarySensor(coordinator, entry)])


class NeedsAttentionBinarySensor(TPGHomeAIEntity, BinarySensorEntity):
    _attr_name = "Needs attention"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:alert-circle"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "needs_attention")

    @property
    def is_on(self) -> bool:
        if not self.coordinator.last_update_success:
            return True  # backend offline
        s = self._state
        return bool(
            s.get("needs_attention")
            or not s.get("config_ok", True)
            or s.get("pending_approvals", 0)
            or (s.get("pending_confirmations") or [])
            or s.get("unavailable_devices", 0)
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._state
        return {
            "backend_online": self.coordinator.last_update_success,
            "config_ok": s.get("config_ok"),
            "pending_approvals": s.get("pending_approvals"),
            "pending_confirmations": len(s.get("pending_confirmations", []) or []),
            "unavailable_devices": s.get("unavailable_devices"),
        }
