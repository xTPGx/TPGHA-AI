"""Polling coordinator: mirrors the orchestrator's /state + /events into Home
Assistant. Drives sensors, fires HA events, raises persistent notifications, and
(optionally) opens Repairs issues."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    BACKEND_EVENT_MAP,
    CONF_CREATE_REPAIRS,
    CONF_ENABLE_NOTIFICATIONS,
    CONF_SCAN_INTERVAL,
    DEFAULT_CREATE_REPAIRS,
    DEFAULT_ENABLE_NOTIFICATIONS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ISSUE_BACKEND_OFFLINE,
    ISSUE_CONFIG_ERROR,
    ISSUE_PENDING_APPROVALS,
    NOTIFY_CONFIG_ERROR,
    NOTIFY_CONFIRMATION,
    NOTIFY_DISCOVERY,
    NOTIFY_OFFLINE,
    NOTIFY_UNAVAILABLE,
)

_LOGGER = logging.getLogger(__name__)


class TPGHomeAICoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch /state on an interval; stream /events between polls."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client) -> None:
        minutes = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        try:
            minutes = max(1, int(minutes))
        except (TypeError, ValueError):
            minutes = DEFAULT_SCAN_INTERVAL
        super().__init__(
            hass, _LOGGER, name="TPG HomeAI",
            update_interval=timedelta(minutes=minutes),
        )
        self.entry = entry
        self.client = client
        self._last_event_id = 0
        self._backend_online = True

    @property
    def _notify_enabled(self) -> bool:
        return self.entry.options.get(CONF_ENABLE_NOTIFICATIONS,
                                      DEFAULT_ENABLE_NOTIFICATIONS)

    @property
    def _repairs_enabled(self) -> bool:
        return self.entry.options.get(CONF_CREATE_REPAIRS, DEFAULT_CREATE_REPAIRS)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            state = await self.client.async_state()
        except Exception as err:  # noqa: BLE001 - surface as offline, not crash
            self._handle_offline(err)
            raise UpdateFailed(str(err)) from err

        self._clear_offline()
        await self._drain_events()
        self._reconcile_notifications(state)
        self._reconcile_repairs(state)
        return state

    # ------------------------------------------------------------- events
    async def _drain_events(self) -> None:
        try:
            payload = await self.client.async_events(since=self._last_event_id)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Could not fetch events: %s", err)
            return
        for evt in payload.get("events", []):
            self._last_event_id = max(self._last_event_id, evt.get("id", 0))
            ha_event = BACKEND_EVENT_MAP.get(evt.get("type"))
            if ha_event:
                self.hass.bus.async_fire(ha_event, evt.get("data", {}))

    # ------------------------------------------------- persistent notifications
    def _notify(self, notification_id: str, title: str, message: str) -> None:
        if not self._notify_enabled:
            return
        self.hass.async_create_task(
            self.hass.services.async_call(
                "persistent_notification", "create",
                {"notification_id": f"{DOMAIN}_{notification_id}",
                 "title": title, "message": message},
                blocking=False,
            )
        )

    def _dismiss(self, notification_id: str) -> None:
        self.hass.async_create_task(
            self.hass.services.async_call(
                "persistent_notification", "dismiss",
                {"notification_id": f"{DOMAIN}_{notification_id}"}, blocking=False,
            )
        )

    def _reconcile_notifications(self, state: dict[str, Any]) -> None:
        # New discovered devices needing review.
        pending = state.get("pending_approvals", 0)
        if pending:
            self._notify(
                NOTIFY_DISCOVERY, "TPG HomeAI found new devices",
                f"{pending} new entit{'y' if pending == 1 else 'ies'} need review. "
                "Open the TPG HomeAI device page, or call "
                "tpg_homeai.approve_discovered_entity / ignore_discovered_entity.",
            )
        else:
            self._dismiss(NOTIFY_DISCOVERY)

        # Pending sensitive-action confirmations.
        confs = state.get("pending_confirmations", []) or []
        if confs:
            lines = "\n".join(
                f"- {c.get('message')} (token expires in {c.get('expires_in')}s)"
                for c in confs)
            self._notify(
                NOTIFY_CONFIRMATION, "TPG HomeAI confirmation required",
                "A sensitive action is awaiting confirmation:\n" + lines +
                "\n\nConfirm with tpg_homeai.confirm_action or cancel with "
                "tpg_homeai.cancel_confirmation.",
            )
        else:
            self._dismiss(NOTIFY_CONFIRMATION)

        # Unavailable devices.
        unavailable = state.get("unavailable", []) or []
        if unavailable:
            names = ", ".join(unavailable[:15])
            self._notify(
                NOTIFY_UNAVAILABLE, "TPG HomeAI device unavailable",
                f"{len(unavailable)} device(s) unavailable: {names}.",
            )
        else:
            self._dismiss(NOTIFY_UNAVAILABLE)

        # Config error (degraded backend).
        if not state.get("config_ok", True):
            self._notify(
                NOTIFY_CONFIG_ERROR, "TPG HomeAI config error",
                f"The orchestrator config failed to load: {state.get('config_error')}. "
                "Running in degraded mode. Fix config/*.yaml and reload.",
            )
        else:
            self._dismiss(NOTIFY_CONFIG_ERROR)

    def _handle_offline(self, err: Exception) -> None:
        if self._backend_online:
            self._backend_online = False
            self._notify(
                NOTIFY_OFFLINE, "TPG HomeAI backend offline",
                f"The TPG HomeAI Orchestrator backend is unreachable: {err}.",
            )
            if self._repairs_enabled:
                self._create_issue(ISSUE_BACKEND_OFFLINE,
                                   "TPG HomeAI backend offline")

    def _clear_offline(self) -> None:
        if not self._backend_online:
            self._backend_online = True
            self._dismiss(NOTIFY_OFFLINE)
            self._delete_issue(ISSUE_BACKEND_OFFLINE)

    # ------------------------------------------------------------- repairs
    def _reconcile_repairs(self, state: dict[str, Any]) -> None:
        if not self._repairs_enabled:
            return
        if not state.get("config_ok", True):
            self._create_issue(ISSUE_CONFIG_ERROR, "TPG HomeAI configuration error")
        else:
            self._delete_issue(ISSUE_CONFIG_ERROR)
        if state.get("pending_approvals", 0):
            self._create_issue(ISSUE_PENDING_APPROVALS,
                               "TPG HomeAI has devices pending approval")
        else:
            self._delete_issue(ISSUE_PENDING_APPROVALS)

    def _create_issue(self, issue_id: str, summary: str) -> None:
        try:
            from homeassistant.helpers import issue_registry as ir
            ir.async_create_issue(
                self.hass, DOMAIN, issue_id, is_fixable=False,
                severity=ir.IssueSeverity.WARNING, translation_key=issue_id,
                translation_placeholders={"summary": summary},
            )
        except Exception as err:  # noqa: BLE001 - repairs are best-effort
            _LOGGER.debug("Could not create repair issue %s: %s", issue_id, err)

    def _delete_issue(self, issue_id: str) -> None:
        try:
            from homeassistant.helpers import issue_registry as ir
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        except Exception:  # noqa: BLE001
            pass
