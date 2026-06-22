"""TPG HomeAI buttons: scan devices, reload config, test connection."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_AUTO_APPROVE_DOMAINS,
    CONF_AUTO_APPROVE_LOW_RISK,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DEFAULT_AUTO_APPROVE_LOW_RISK,
    DOMAIN,
)
from .entity import TPGHomeAIEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data[DATA_COORDINATOR]
    client = data[DATA_CLIENT]
    async_add_entities([
        ScanDevicesButton(coordinator, entry, client),
        ReloadConfigButton(coordinator, entry, client),
        TestConnectionButton(coordinator, entry, client),
    ])


class _BaseButton(TPGHomeAIEntity, ButtonEntity):
    def __init__(self, coordinator, entry, client, key: str) -> None:
        super().__init__(coordinator, entry, key)
        self._client = client


class ScanDevicesButton(_BaseButton):
    _attr_name = "Scan devices"
    _attr_icon = "mdi:radar"

    def __init__(self, coordinator, entry, client) -> None:
        super().__init__(coordinator, entry, client, "scan_devices")

    async def async_press(self) -> None:
        opts = self._entry.options
        await self._client.async_scan(
            auto_low_risk=opts.get(CONF_AUTO_APPROVE_LOW_RISK,
                                   DEFAULT_AUTO_APPROVE_LOW_RISK),
            auto_domains=opts.get(CONF_AUTO_APPROVE_DOMAINS, []))
        await self.coordinator.async_request_refresh()


class ReloadConfigButton(_BaseButton):
    _attr_name = "Reload config"
    _attr_icon = "mdi:reload"

    def __init__(self, coordinator, entry, client) -> None:
        super().__init__(coordinator, entry, client, "reload_config")

    async def async_press(self) -> None:
        await self._client.async_reload_config()
        await self.coordinator.async_request_refresh()


class TestConnectionButton(_BaseButton):
    _attr_name = "Test connection"
    _attr_icon = "mdi:lan-connect"

    def __init__(self, coordinator, entry, client) -> None:
        super().__init__(coordinator, entry, client, "test_connection")

    async def async_press(self) -> None:
        health = await self._client.async_health()
        _LOGGER.info("TPG HomeAI health: status=%s version=%s",
                     health.get("status"), health.get("version"))
        await self.coordinator.async_request_refresh()
