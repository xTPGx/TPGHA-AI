"""TPG HomeAI custom integration.

Bridges Home Assistant to a running TPG HomeAI Orchestrator. It forwards Assist
conversation input, exposes operational entities (status, approvals, last
command, attention), buttons (scan/reload/test), services (scan/approve/ignore/
map/confirm/cancel), and mirrors backend events + notifications into HA so the
orchestrator is managed from Home Assistant rather than only the React UI.
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import async_timeout
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_API_KEY,
    CONF_ASSISTANT_ID,
    CONF_AUTO_APPROVE_DOMAINS,
    CONF_AUTO_APPROVE_LOW_RISK,
    CONF_URL,
    CONF_USER_ID,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DEFAULT_ASSISTANT_ID,
    DEFAULT_AUTO_APPROVE_LOW_RISK,
    DEFAULT_TIMEOUT,
    DEFAULT_USER_ID,
    DOMAIN,
    SERVICE_APPROVE,
    SERVICE_CANCEL_CONFIRMATION,
    SERVICE_CONFIRM_ACTION,
    SERVICE_IGNORE,
    SERVICE_MAP_ENTITY,
    SERVICE_RELOAD_CONFIG,
    SERVICE_SCAN_DEVICES,
    SERVICE_TEST_COMMAND,
)
from .coordinator import TPGHomeAICoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.CONVERSATION,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
]


class TPGHomeAIError(HomeAssistantError):
    """Raised when the TPG HomeAI server cannot be reached or errors."""


class TPGHomeAIClient:
    """Thin async HTTP client for the TPG HomeAI Orchestrator server."""

    def __init__(self, session: aiohttp.ClientSession, base_url: str,
                 api_key: str | None = None) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key or None

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def _request(self, method: str, path: str, json: dict | None = None) -> Any:
        url = f"{self._base_url}{path}"
        try:
            async with async_timeout.timeout(DEFAULT_TIMEOUT):
                resp = await self._session.request(
                    method, url, json=json, headers=self._headers())
        except aiohttp.ClientError as err:
            _LOGGER.debug("Request to %s failed: %s", path, err)
            raise TPGHomeAIError(f"Could not reach TPG HomeAI server at {url}") from err
        except TimeoutError as err:
            raise TPGHomeAIError(f"Timed out contacting TPG HomeAI server at {url}") from err

        if resp.status == 401:
            raise TPGHomeAIError("TPG HomeAI server rejected the API key (401).")
        if resp.status >= 400:
            raise TPGHomeAIError(f"TPG HomeAI server returned HTTP {resp.status}.")
        try:
            return await resp.json()
        except (aiohttp.ContentTypeError, ValueError):
            return {"message": await resp.text()}

    async def async_health(self) -> dict[str, Any]:
        return await self._request("GET", "/health")

    async def async_state(self) -> dict[str, Any]:
        return await self._request("GET", "/state")

    async def async_events(self, since: int = 0) -> dict[str, Any]:
        return await self._request("GET", f"/events?since={since}")

    async def async_summary(self) -> dict[str, Any]:
        return await self._request("GET", "/discovery/summary")

    async def async_pending(self) -> dict[str, Any]:
        return await self._request("GET", "/discovery/pending")

    async def async_reload_config(self) -> dict[str, Any]:
        return await self._request("POST", "/config/reload")

    async def async_scan(self, auto_low_risk: bool = False,
                         auto_domains: list[str] | None = None) -> dict[str, Any]:
        return await self._request("POST", "/discovery/scan", json={
            "auto_approve_low_risk": auto_low_risk,
            "auto_approve_domains": auto_domains or [],
        })

    async def async_approve(self, entity_id: str, mapping: str | None = None,
                            room: str | None = None, friendly_name: str | None = None,
                            aliases: list[str] | None = None) -> dict[str, Any]:
        return await self._request("POST", "/discovery/approve", json={
            "entity_id": entity_id, "mapping": mapping, "room": room,
            "friendly_name": friendly_name, "aliases": aliases})

    async def async_ignore(self, entity_id: str, reason: str = "") -> dict[str, Any]:
        return await self._request("POST", "/discovery/ignore", json={
            "entity_id": entity_id, "reason": reason})

    async def async_map(self, entity_id: str, target: str, room: str | None = None,
                        friendly_name: str | None = None,
                        aliases: list[str] | None = None) -> dict[str, Any]:
        return await self._request("POST", "/discovery/map", json={
            "entity_id": entity_id, "target": target, "room": room,
            "friendly_name": friendly_name, "aliases": aliases})

    async def async_confirm(self, token: str) -> dict[str, Any]:
        return await self._request("POST", "/confirm",
                                   json={"confirmation_token": token})

    async def async_cancel(self, token: str) -> dict[str, Any]:
        return await self._request("POST", "/confirm/cancel",
                                   json={"confirmation_token": token})

    async def async_command(self, text: str, assistant_id: str, user_id: str | None,
                            conversation_id: str | None) -> dict[str, Any]:
        return await self._request("POST", "/command", json={
            "assistant_id": assistant_id, "user_id": user_id, "text": text,
            "conversation_id": conversation_id})


def _build_client(hass: HomeAssistant, entry: ConfigEntry) -> TPGHomeAIClient:
    session = async_get_clientsession(hass)
    return TPGHomeAIClient(session, entry.data[CONF_URL], entry.data.get(CONF_API_KEY))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client = _build_client(hass, entry)
    try:
        health = await client.async_health()
        _LOGGER.debug("Connected to TPG HomeAI (status=%s)", health.get("status"))
    except TPGHomeAIError as err:
        _LOGGER.warning("TPG HomeAI server not reachable yet: %s", err)

    coordinator = TPGHomeAICoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        DATA_CLIENT: client,
        DATA_COORDINATOR: coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    _register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            _unregister_services(hass)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _first_client(hass: HomeAssistant) -> TPGHomeAIClient:
    for entry_data in hass.data.get(DOMAIN, {}).values():
        client = entry_data.get(DATA_CLIENT)
        if client is not None:
            return client
    raise TPGHomeAIError("TPG HomeAI is not configured.")


def _first_entry(hass: HomeAssistant) -> ConfigEntry | None:
    entries = hass.config_entries.async_entries(DOMAIN)
    return entries[0] if entries else None


def _coordinator(hass: HomeAssistant) -> TPGHomeAICoordinator | None:
    for entry_data in hass.data.get(DOMAIN, {}).values():
        coord = entry_data.get(DATA_COORDINATOR)
        if coord is not None:
            return coord
    return None


# --------------------------------------------------------------------- schemas
TEST_COMMAND_SCHEMA = vol.Schema({
    vol.Required("text"): cv.string,
    vol.Optional("assistant_id"): cv.string,
    vol.Optional("user_id"): cv.string,
    vol.Optional("conversation_id"): cv.string,
})
APPROVE_SCHEMA = vol.Schema({
    vol.Required("entity_id"): cv.string,
    vol.Optional("mapping"): cv.string,
    vol.Optional("room"): cv.string,
    vol.Optional("friendly_name"): cv.string,
    vol.Optional("aliases"): vol.All(cv.ensure_list, [cv.string]),
})
IGNORE_SCHEMA = vol.Schema({
    vol.Required("entity_id"): cv.string,
    vol.Optional("reason", default=""): cv.string,
})
MAP_SCHEMA = vol.Schema({
    vol.Required("entity_id"): cv.string,
    vol.Required("target"): cv.string,
    vol.Optional("room"): cv.string,
    vol.Optional("friendly_name"): cv.string,
    vol.Optional("aliases"): vol.All(cv.ensure_list, [cv.string]),
})
TOKEN_SCHEMA = vol.Schema({vol.Required("confirmation_token"): cv.string})


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_RELOAD_CONFIG):
        return

    async def _refresh() -> None:
        coord = _coordinator(hass)
        if coord is not None:
            await coord.async_request_refresh()

    async def _reload_config(call: ServiceCall) -> None:
        await _first_client(hass).async_reload_config()
        await _refresh()

    async def _scan_devices(call: ServiceCall) -> ServiceResponse:
        entry = _first_entry(hass)
        opts = entry.options if entry else {}
        result = await _first_client(hass).async_scan(
            auto_low_risk=opts.get(CONF_AUTO_APPROVE_LOW_RISK,
                                   DEFAULT_AUTO_APPROVE_LOW_RISK),
            auto_domains=opts.get(CONF_AUTO_APPROVE_DOMAINS, []),
        )
        await _refresh()
        return {"summary": result.get("summary"),
                "auto_approved": result.get("auto_approved")}

    async def _approve(call: ServiceCall) -> None:
        await _first_client(hass).async_approve(
            call.data["entity_id"], mapping=call.data.get("mapping"),
            room=call.data.get("room"), friendly_name=call.data.get("friendly_name"),
            aliases=call.data.get("aliases"))
        await _refresh()

    async def _ignore(call: ServiceCall) -> None:
        await _first_client(hass).async_ignore(
            call.data["entity_id"], reason=call.data.get("reason", ""))
        await _refresh()

    async def _map_entity(call: ServiceCall) -> None:
        await _first_client(hass).async_map(
            call.data["entity_id"], target=call.data["target"],
            room=call.data.get("room"), friendly_name=call.data.get("friendly_name"),
            aliases=call.data.get("aliases"))
        await _refresh()

    async def _confirm_action(call: ServiceCall) -> ServiceResponse:
        result = await _first_client(hass).async_confirm(call.data["confirmation_token"])
        await _refresh()
        return {"success": result.get("success"), "executed": result.get("executed"),
                "message": result.get("message")}

    async def _cancel_confirmation(call: ServiceCall) -> None:
        await _first_client(hass).async_cancel(call.data["confirmation_token"])
        await _refresh()

    async def _test_command(call: ServiceCall) -> ServiceResponse:
        entry = _first_entry(hass)
        options = entry.options if entry else {}
        assistant_id = call.data.get("assistant_id") or options.get(
            CONF_ASSISTANT_ID, DEFAULT_ASSISTANT_ID)
        user_id = call.data.get("user_id") or options.get(CONF_USER_ID, DEFAULT_USER_ID)
        result = await _first_client(hass).async_command(
            text=call.data["text"], assistant_id=assistant_id, user_id=user_id,
            conversation_id=call.data.get("conversation_id"))
        return {k: result.get(k) for k in (
            "success", "intent", "message", "executed", "requires_confirmation",
            "confirmation_token", "resolved")}

    reg = hass.services.async_register
    reg(DOMAIN, SERVICE_RELOAD_CONFIG, _reload_config)
    reg(DOMAIN, SERVICE_SCAN_DEVICES, _scan_devices, supports_response=SupportsResponse.OPTIONAL)
    reg(DOMAIN, SERVICE_APPROVE, _approve, schema=APPROVE_SCHEMA)
    reg(DOMAIN, SERVICE_IGNORE, _ignore, schema=IGNORE_SCHEMA)
    reg(DOMAIN, SERVICE_MAP_ENTITY, _map_entity, schema=MAP_SCHEMA)
    reg(DOMAIN, SERVICE_CONFIRM_ACTION, _confirm_action, schema=TOKEN_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL)
    reg(DOMAIN, SERVICE_CANCEL_CONFIRMATION, _cancel_confirmation, schema=TOKEN_SCHEMA)
    reg(DOMAIN, SERVICE_TEST_COMMAND, _test_command, schema=TEST_COMMAND_SCHEMA,
        supports_response=SupportsResponse.ONLY)


def _unregister_services(hass: HomeAssistant) -> None:
    for service in (SERVICE_RELOAD_CONFIG, SERVICE_SCAN_DEVICES, SERVICE_APPROVE,
                    SERVICE_IGNORE, SERVICE_MAP_ENTITY, SERVICE_CONFIRM_ACTION,
                    SERVICE_CANCEL_CONFIRMATION, SERVICE_TEST_COMMAND):
        hass.services.async_remove(DOMAIN, service)
