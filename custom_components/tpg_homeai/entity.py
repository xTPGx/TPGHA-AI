"""Shared base entity: groups everything under one TPG HomeAI device."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.device_info import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEVICE_MANUFACTURER, DEVICE_MODEL, DEVICE_NAME, DOMAIN
from .coordinator import TPGHomeAICoordinator


class TPGHomeAIEntity(CoordinatorEntity[TPGHomeAICoordinator]):
    """Base entity attached to the single TPG HomeAI Orchestrator device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TPGHomeAICoordinator, entry: ConfigEntry,
                 key: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=DEVICE_NAME,
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
            entry_type=DeviceEntryType.SERVICE,
            sw_version=str((coordinator.data or {}).get("version", "")),
        )

    @property
    def _state(self) -> dict:
        return self.coordinator.data or {}
