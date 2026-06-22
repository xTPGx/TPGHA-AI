"""Config and options flow for the TPG HomeAI integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import async_timeout
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_API_KEY,
    CONF_ASSISTANT_ID,
    CONF_AUTO_APPROVE_DOMAINS,
    CONF_AUTO_APPROVE_LOW_RISK,
    CONF_CREATE_REPAIRS,
    CONF_ENABLE_NOTIFICATIONS,
    CONF_SCAN_INTERVAL,
    CONF_URL,
    CONF_USER_ID,
    DEFAULT_ASSISTANT_ID,
    DEFAULT_AUTO_APPROVE_LOW_RISK,
    DEFAULT_CREATE_REPAIRS,
    DEFAULT_ENABLE_NOTIFICATIONS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DEFAULT_USER_ID,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL, default="http://homeassistant.local:8088"): str,
        vol.Optional(CONF_API_KEY): str,
    }
)


async def _validate_server(hass, url: str, api_key: str | None) -> str:
    """Probe /health. Returns the server version. Raises on failure."""
    session = async_get_clientsession(hass)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    target = f"{url.rstrip('/')}/health"
    async with async_timeout.timeout(DEFAULT_TIMEOUT):
        resp = await session.get(target, headers=headers)
    if resp.status == 401:
        raise InvalidAuth
    if resp.status >= 400:
        raise CannotConnect(f"HTTP {resp.status}")
    data = await resp.json()
    return str(data.get("version", "unknown"))


class TPGHomeAIConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup: server URL + optional API key."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input[CONF_URL].strip()
            api_key = (user_input.get(CONF_API_KEY) or "").strip() or None
            await self.async_set_unique_id(url.lower())
            self._abort_if_unique_id_configured()
            try:
                version = await _validate_server(self.hass, url, api_key)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except (aiohttp.ClientError, TimeoutError) as err:
                _LOGGER.debug("Validation failed for %s: %s", url, err)
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating TPG HomeAI server")
                errors["base"] = "unknown"
            else:
                data = {CONF_URL: url}
                if api_key:
                    data[CONF_API_KEY] = api_key
                return self.async_create_entry(
                    title=f"TPG HomeAI ({url})",
                    data=data,
                    description_placeholders={"version": version},
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return TPGHomeAIOptionsFlow(config_entry)


class TPGHomeAIOptionsFlow(OptionsFlow):
    """Defaults used when forwarding Assist messages (assistant + user)."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        # Store privately to stay compatible across HA versions (newer versions
        # expose `config_entry` as a read-only property on OptionsFlow).
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            # Normalize the comma-separated domains into a list.
            raw = user_input.get(CONF_AUTO_APPROVE_DOMAINS, "")
            if isinstance(raw, str):
                user_input[CONF_AUTO_APPROVE_DOMAINS] = [
                    d.strip() for d in raw.split(",") if d.strip()]
            return self.async_create_entry(title="", data=user_input)

        opts = self._config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_ASSISTANT_ID,
                    default=opts.get(CONF_ASSISTANT_ID, DEFAULT_ASSISTANT_ID),
                ): str,
                vol.Optional(
                    CONF_USER_ID,
                    default=opts.get(CONF_USER_ID, DEFAULT_USER_ID),
                ): str,
                vol.Optional(
                    CONF_ENABLE_NOTIFICATIONS,
                    default=opts.get(CONF_ENABLE_NOTIFICATIONS,
                                     DEFAULT_ENABLE_NOTIFICATIONS),
                ): bool,
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(int, vol.Range(min=1, max=1440)),
                vol.Optional(
                    CONF_CREATE_REPAIRS,
                    default=opts.get(CONF_CREATE_REPAIRS, DEFAULT_CREATE_REPAIRS),
                ): bool,
                vol.Optional(
                    CONF_AUTO_APPROVE_LOW_RISK,
                    default=opts.get(CONF_AUTO_APPROVE_LOW_RISK,
                                     DEFAULT_AUTO_APPROVE_LOW_RISK),
                ): bool,
                vol.Optional(
                    CONF_AUTO_APPROVE_DOMAINS,
                    default=",".join(opts.get(CONF_AUTO_APPROVE_DOMAINS, [])),
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


class CannotConnect(Exception):
    """Cannot reach the TPG HomeAI server."""


class InvalidAuth(Exception):
    """API key rejected by the server."""
