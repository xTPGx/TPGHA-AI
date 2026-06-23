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
    CONF_ENABLE_SIDEBAR_PANEL,
    CONF_URL,
    CONF_USER_ID,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DEFAULT_ASSISTANT_ID,
    DEFAULT_AUTO_APPROVE_LOW_RISK,
    DEFAULT_ENABLE_SIDEBAR_PANEL,
    DEFAULT_TIMEOUT,
    DEFAULT_USER_ID,
    DOMAIN,
    SERVICE_APPROVE,
    SERVICE_CANCEL_CONFIRMATION,
    SERVICE_APPROVE_AUTOMATION_DRAFT,
    SERVICE_CONFIRM_ACTION,
    SERVICE_DASHBOARD_DRAFT,
    SERVICE_DASHBOARD_INSTALL,
    SERVICE_DRAFT_MEMORY,
    SERVICE_GENERATE_SUGGESTIONS,
    SERVICE_GET_AI_PROVIDERS,
    SERVICE_GET_BRAIN_LAYERS,
    SERVICE_MONITOR_SCAN,
    SERVICE_GET_KNOWLEDGE_GRAPH,
    SERVICE_GET_PHYSICAL_DEVICES,
    SERVICE_GET_COMMANDS,
    SERVICE_GET_LAST_COMMAND,
    SERVICE_IGNORE,
    SERVICE_IGNORE_MEMORY,
    SERVICE_MAP_ENTITY,
    SERVICE_OPEN_PANEL,
    SERVICE_APPROVE_MEMORY,
    SERVICE_PREVIEW_COMMAND,
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

    async def async_knowledge_graph(self, include_registries: bool = True) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/knowledge/graph?include_registries={'true' if include_registries else 'false'}",
        )

    async def async_brain_layers(self, include_registries: bool = True) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/brain/layers?include_registries={'true' if include_registries else 'false'}",
        )

    async def async_physical_devices(self, include_registries: bool = True) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/knowledge/physical-devices?include_registries={'true' if include_registries else 'false'}",
        )

    async def async_ai_providers(self) -> dict[str, Any]:
        return await self._request("GET", "/ai/providers")

    async def async_last_command(self) -> dict[str, Any]:
        return await self._request("GET", "/debug/last-command")

    async def async_commands(self, limit: int = 25) -> dict[str, Any]:
        return await self._request("GET", f"/debug/commands?limit={limit}")

    async def async_generate_suggestions(self) -> dict[str, Any]:
        return await self._request("POST", "/suggestions/generate")

    async def async_draft_memory(self, scope: str, subject: str, key: str, value: str,
                                 owner: str | None = None,
                                 source: str = "home_assistant") -> dict[str, Any]:
        return await self._request("POST", "/memory/draft", json={
            "scope": scope,
            "owner": owner,
            "subject": subject,
            "key": key,
            "value": value,
            "source": source,
        })

    async def async_approve_memory(self, memory_id: int) -> dict[str, Any]:
        return await self._request("POST", f"/memory/{memory_id}/approve")

    async def async_ignore_memory(self, memory_id: int) -> dict[str, Any]:
        return await self._request("POST", f"/memory/{memory_id}/ignore")

    async def async_dashboard_draft(self, title: str = "TPG Home",
                                    style: str = "native",
                                    room: str | None = None,
                                    include_browser_mod: bool = True) -> dict[str, Any]:
        return await self._request("POST", "/dashboards/draft", json={
            "title": title,
            "style": style,
            "room": room,
            "include_browser_mod": include_browser_mod,
        })

    async def async_dashboard_install(self, title: str = "TPG Home",
                                      style: str = "native",
                                      room: str | None = None,
                                      include_browser_mod: bool = True) -> dict[str, Any]:
        return await self._request("POST", "/dashboards/install", json={
            "title": title,
            "style": style,
            "room": room,
            "include_browser_mod": include_browser_mod,
        })

    async def async_monitor_scan(self) -> dict[str, Any]:
        return await self._request("POST", "/monitor/scan")

    async def async_approve_automation_draft(self, draft_id: int) -> dict[str, Any]:
        return await self._request("POST", f"/automation/drafts/{draft_id}/approve")

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

    async def async_confirm(self, token: str, security_pin: str | None = None) -> dict[str, Any]:
        return await self._request("POST", "/confirm",
                                   json={"confirmation_token": token, "security_pin": security_pin})

    async def async_cancel(self, token: str) -> dict[str, Any]:
        return await self._request("POST", "/confirm/cancel",
                                   json={"confirmation_token": token})

    async def async_command(self, text: str, assistant_id: str, user_id: str | None,
                            conversation_id: str | None, room: str | None = None,
                            security_pin: str | None = None) -> dict[str, Any]:
        return await self._request("POST", "/command", json={
            "assistant_id": assistant_id, "user_id": user_id, "text": text,
            "conversation_id": conversation_id, "room": room,
            "security_pin": security_pin})

    async def async_preview_command(self, text: str, assistant_id: str,
                                    user_id: str | None,
                                    conversation_id: str | None,
                                    room: str | None = None) -> dict[str, Any]:
        return await self._request("POST", "/command/preview", json={
            "assistant_id": assistant_id, "user_id": user_id, "text": text,
            "conversation_id": conversation_id, "room": room})


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
    _register_sidebar_panel(hass, entry)
    _register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        _remove_sidebar_panel(hass)
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
    vol.Optional("room"): cv.string,
    vol.Optional("security_pin"): cv.string,
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
TOKEN_SCHEMA = vol.Schema({
    vol.Required("confirmation_token"): cv.string,
    vol.Optional("security_pin"): cv.string,
})
DASHBOARD_DRAFT_SCHEMA = vol.Schema({
    vol.Optional("title", default="TPG Home"): cv.string,
    vol.Optional("style", default="native"): vol.In(["native", "mushroom"]),
    vol.Optional("room"): cv.string,
    vol.Optional("include_browser_mod", default=True): cv.boolean,
})
OPEN_PANEL_SCHEMA = vol.Schema({
    vol.Optional("path", default="/tpg-homeai"): cv.string,
    vol.Optional("browser_id"): cv.string,
    vol.Optional("use_browser_mod", default=True): cv.boolean,
})
KNOWLEDGE_GRAPH_SCHEMA = vol.Schema({
    vol.Optional("include_registries", default=True): cv.boolean,
})
MEMORY_DRAFT_SCHEMA = vol.Schema({
    vol.Optional("scope", default="house"): vol.In(["house", "user", "room", "device"]),
    vol.Optional("owner"): cv.string,
    vol.Required("subject"): cv.string,
    vol.Required("key"): cv.string,
    vol.Required("value"): cv.string,
})
MEMORY_ID_SCHEMA = vol.Schema({vol.Required("memory_id"): vol.Coerce(int)})
AUTOMATION_DRAFT_ID_SCHEMA = vol.Schema({vol.Required("draft_id"): vol.Coerce(int)})
COMMANDS_SCHEMA = vol.Schema({
    vol.Optional("limit", default=25): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
})


def _register_sidebar_panel(hass: HomeAssistant, entry: ConfigEntry) -> None:
    enabled = entry.options.get(CONF_ENABLE_SIDEBAR_PANEL,
                                DEFAULT_ENABLE_SIDEBAR_PANEL)
    if not enabled:
        _remove_sidebar_panel(hass)
        return
    try:
        from homeassistant.components import frontend

        frontend.async_register_built_in_panel(
            hass,
            component_name="iframe",
            sidebar_title="TPG HomeAI",
            sidebar_icon="mdi:robot-happy",
            frontend_url_path="tpg-homeai",
            config={"url": entry.data[CONF_URL], "require_admin": False},
            require_admin=False,
        )
    except Exception as err:  # noqa: BLE001 - sidebar is best-effort
        _LOGGER.debug("Could not register TPG HomeAI sidebar panel: %s", err)


def _remove_sidebar_panel(hass: HomeAssistant) -> None:
    try:
        from homeassistant.components import frontend

        frontend.async_remove_panel(hass, "tpg-homeai")
    except Exception:  # noqa: BLE001 - panel may not exist on this HA version
        pass


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
        result = await _first_client(hass).async_confirm(
            call.data["confirmation_token"], security_pin=call.data.get("security_pin"))
        await _refresh()
        return {"success": result.get("success"), "executed": result.get("executed"),
                "message": result.get("message")}

    async def _cancel_confirmation(call: ServiceCall) -> None:
        await _first_client(hass).async_cancel(call.data["confirmation_token"])
        await _refresh()

    async def _dashboard_draft(call: ServiceCall) -> ServiceResponse:
        return await _first_client(hass).async_dashboard_draft(
            title=call.data.get("title", "TPG Home"),
            style=call.data.get("style", "native"),
            room=call.data.get("room"),
            include_browser_mod=call.data.get("include_browser_mod", True),
        )

    async def _dashboard_install(call: ServiceCall) -> ServiceResponse:
        return await _first_client(hass).async_dashboard_install(
            title=call.data.get("title", "TPG Home"),
            style=call.data.get("style", "native"),
            room=call.data.get("room"),
            include_browser_mod=call.data.get("include_browser_mod", True),
        )

    async def _open_panel(call: ServiceCall) -> ServiceResponse:
        path = call.data.get("path", "/tpg-homeai")
        use_browser_mod = call.data.get("use_browser_mod", True)
        browser_id = call.data.get("browser_id")
        browser_mod_used = False
        if use_browser_mod and hass.services.has_service("browser_mod", "navigate"):
            data: dict[str, Any] = {"path": path}
            if browser_id:
                data["browser_id"] = browser_id
            await hass.services.async_call("browser_mod", "navigate", data, blocking=False)
            browser_mod_used = True
        return {
            "path": path,
            "panel": "/tpg-homeai",
            "browser_mod_used": browser_mod_used,
        }

    async def _get_knowledge_graph(call: ServiceCall) -> ServiceResponse:
        return await _first_client(hass).async_knowledge_graph(
            include_registries=call.data.get("include_registries", True))

    async def _get_brain_layers(call: ServiceCall) -> ServiceResponse:
        return await _first_client(hass).async_brain_layers(
            include_registries=call.data.get("include_registries", True))

    async def _get_physical_devices(call: ServiceCall) -> ServiceResponse:
        return await _first_client(hass).async_physical_devices(
            include_registries=call.data.get("include_registries", True))

    async def _get_ai_providers(call: ServiceCall) -> ServiceResponse:
        return await _first_client(hass).async_ai_providers()

    async def _get_last_command(call: ServiceCall) -> ServiceResponse:
        return await _first_client(hass).async_last_command()

    async def _get_commands(call: ServiceCall) -> ServiceResponse:
        return await _first_client(hass).async_commands(call.data.get("limit", 25))

    async def _generate_suggestions(call: ServiceCall) -> ServiceResponse:
        result = await _first_client(hass).async_generate_suggestions()
        await _refresh()
        return result

    async def _monitor_scan(call: ServiceCall) -> ServiceResponse:
        result = await _first_client(hass).async_monitor_scan()
        await _refresh()
        return result

    async def _approve_automation_draft(call: ServiceCall) -> ServiceResponse:
        result = await _first_client(hass).async_approve_automation_draft(call.data["draft_id"])
        await _refresh()
        return result

    async def _draft_memory(call: ServiceCall) -> ServiceResponse:
        return await _first_client(hass).async_draft_memory(
            scope=call.data.get("scope", "house"),
            owner=call.data.get("owner"),
            subject=call.data["subject"],
            key=call.data["key"],
            value=call.data["value"],
        )

    async def _approve_memory(call: ServiceCall) -> ServiceResponse:
        return await _first_client(hass).async_approve_memory(call.data["memory_id"])

    async def _ignore_memory(call: ServiceCall) -> ServiceResponse:
        return await _first_client(hass).async_ignore_memory(call.data["memory_id"])

    async def _test_command(call: ServiceCall) -> ServiceResponse:
        entry = _first_entry(hass)
        options = entry.options if entry else {}
        assistant_id = call.data.get("assistant_id") or options.get(
            CONF_ASSISTANT_ID, DEFAULT_ASSISTANT_ID)
        user_id = call.data.get("user_id") or options.get(CONF_USER_ID, DEFAULT_USER_ID)
        result = await _first_client(hass).async_command(
            text=call.data["text"], assistant_id=assistant_id, user_id=user_id,
            conversation_id=call.data.get("conversation_id"),
            room=call.data.get("room"),
            security_pin=call.data.get("security_pin"))
        return {k: result.get(k) for k in (
            "success", "intent", "message", "executed", "requires_confirmation",
            "confirmation_token", "resolved")}

    async def _preview_command(call: ServiceCall) -> ServiceResponse:
        entry = _first_entry(hass)
        options = entry.options if entry else {}
        assistant_id = call.data.get("assistant_id") or options.get(
            CONF_ASSISTANT_ID, DEFAULT_ASSISTANT_ID)
        user_id = call.data.get("user_id") or options.get(CONF_USER_ID, DEFAULT_USER_ID)
        result = await _first_client(hass).async_preview_command(
            text=call.data["text"], assistant_id=assistant_id, user_id=user_id,
            conversation_id=call.data.get("conversation_id"),
            room=call.data.get("room"))
        return {k: result.get(k) for k in (
            "success", "intent", "message", "executed", "requires_confirmation",
            "confirmation_message", "resolved", "data", "tool_call", "error")}

    reg = hass.services.async_register
    reg(DOMAIN, SERVICE_RELOAD_CONFIG, _reload_config)
    reg(DOMAIN, SERVICE_SCAN_DEVICES, _scan_devices, supports_response=SupportsResponse.OPTIONAL)
    reg(DOMAIN, SERVICE_APPROVE, _approve, schema=APPROVE_SCHEMA)
    reg(DOMAIN, SERVICE_IGNORE, _ignore, schema=IGNORE_SCHEMA)
    reg(DOMAIN, SERVICE_MAP_ENTITY, _map_entity, schema=MAP_SCHEMA)
    reg(DOMAIN, SERVICE_CONFIRM_ACTION, _confirm_action, schema=TOKEN_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL)
    reg(DOMAIN, SERVICE_CANCEL_CONFIRMATION, _cancel_confirmation, schema=TOKEN_SCHEMA)
    reg(DOMAIN, SERVICE_DASHBOARD_DRAFT, _dashboard_draft, schema=DASHBOARD_DRAFT_SCHEMA,
        supports_response=SupportsResponse.ONLY)
    reg(DOMAIN, SERVICE_DASHBOARD_INSTALL, _dashboard_install, schema=DASHBOARD_DRAFT_SCHEMA,
        supports_response=SupportsResponse.ONLY)
    reg(DOMAIN, SERVICE_OPEN_PANEL, _open_panel, schema=OPEN_PANEL_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL)
    reg(DOMAIN, SERVICE_GET_KNOWLEDGE_GRAPH, _get_knowledge_graph,
        schema=KNOWLEDGE_GRAPH_SCHEMA, supports_response=SupportsResponse.ONLY)
    reg(DOMAIN, SERVICE_GET_BRAIN_LAYERS, _get_brain_layers,
        schema=KNOWLEDGE_GRAPH_SCHEMA, supports_response=SupportsResponse.ONLY)
    reg(DOMAIN, SERVICE_GET_PHYSICAL_DEVICES, _get_physical_devices,
        schema=KNOWLEDGE_GRAPH_SCHEMA, supports_response=SupportsResponse.ONLY)
    reg(DOMAIN, SERVICE_GET_AI_PROVIDERS, _get_ai_providers,
        supports_response=SupportsResponse.ONLY)
    reg(DOMAIN, SERVICE_GET_LAST_COMMAND, _get_last_command,
        supports_response=SupportsResponse.ONLY)
    reg(DOMAIN, SERVICE_GET_COMMANDS, _get_commands, schema=COMMANDS_SCHEMA,
        supports_response=SupportsResponse.ONLY)
    reg(DOMAIN, SERVICE_GENERATE_SUGGESTIONS, _generate_suggestions,
        supports_response=SupportsResponse.ONLY)
    reg(DOMAIN, SERVICE_MONITOR_SCAN, _monitor_scan,
        supports_response=SupportsResponse.ONLY)
    reg(DOMAIN, SERVICE_APPROVE_AUTOMATION_DRAFT, _approve_automation_draft,
        schema=AUTOMATION_DRAFT_ID_SCHEMA, supports_response=SupportsResponse.ONLY)
    reg(DOMAIN, SERVICE_DRAFT_MEMORY, _draft_memory, schema=MEMORY_DRAFT_SCHEMA,
        supports_response=SupportsResponse.ONLY)
    reg(DOMAIN, SERVICE_APPROVE_MEMORY, _approve_memory, schema=MEMORY_ID_SCHEMA,
        supports_response=SupportsResponse.ONLY)
    reg(DOMAIN, SERVICE_IGNORE_MEMORY, _ignore_memory, schema=MEMORY_ID_SCHEMA,
        supports_response=SupportsResponse.ONLY)
    reg(DOMAIN, SERVICE_TEST_COMMAND, _test_command, schema=TEST_COMMAND_SCHEMA,
        supports_response=SupportsResponse.ONLY)
    reg(DOMAIN, SERVICE_PREVIEW_COMMAND, _preview_command, schema=TEST_COMMAND_SCHEMA,
        supports_response=SupportsResponse.ONLY)


def _unregister_services(hass: HomeAssistant) -> None:
    for service in (SERVICE_RELOAD_CONFIG, SERVICE_SCAN_DEVICES, SERVICE_APPROVE,
                    SERVICE_IGNORE, SERVICE_MAP_ENTITY, SERVICE_CONFIRM_ACTION,
                    SERVICE_CANCEL_CONFIRMATION, SERVICE_DASHBOARD_DRAFT,
                    SERVICE_DASHBOARD_INSTALL, SERVICE_OPEN_PANEL,
                    SERVICE_GET_KNOWLEDGE_GRAPH, SERVICE_GET_BRAIN_LAYERS,
                    SERVICE_GET_PHYSICAL_DEVICES, SERVICE_GET_AI_PROVIDERS,
                    SERVICE_GET_LAST_COMMAND,
                    SERVICE_GET_COMMANDS, SERVICE_GENERATE_SUGGESTIONS,
                    SERVICE_MONITOR_SCAN, SERVICE_APPROVE_AUTOMATION_DRAFT,
                    SERVICE_DRAFT_MEMORY,
                    SERVICE_APPROVE_MEMORY, SERVICE_IGNORE_MEMORY,
                    SERVICE_TEST_COMMAND, SERVICE_PREVIEW_COMMAND):
        hass.services.async_remove(DOMAIN, service)
