"""Startup bootstrap + periodic scan (PART 2 & PART 3).

On launch the backend self-initializes so the user never has to manually hit
/discovery/scan after a restart:

  1. Ensure the config dir + starter files exist.
  2. Validate config (degrade, never crash, on error).
  3. Connect to Home Assistant (Supervisor proxy or long-lived token).
  4. Pull states + run the initial discovery scan (classify/merge/categorize).
  5. Emit notification payloads for anything needing review.
  6. Mark the backend ready.

Everything is time-boxed so startup can never block forever, and a periodic
background task keeps the discovery registry current.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from ..config_loader import config_error, reload_config
from ..discovery import scanner
from ..events import get_event_bus
from ..settings import get_settings

logger = logging.getLogger("tpg.bootstrap")

# Notification event type emitted to the in-process bus; the HA integration
# turns these (plus /state) into persistent notifications.
EVT_NOTIFICATION = "tpg_homeai_notification"
EVT_BOOTSTRAP_READY = "tpg_homeai_ready"

_STARTER_FILES = ("household.yaml", "assistants.yaml", "devices.yaml",
                  "permissions.yaml")


@dataclass
class AppState:
    """Live operational state, surfaced by /health and /state."""

    started_at: float = field(default_factory=time.time)
    ready: bool = False
    initializing: bool = True
    mode: str = "standalone"
    ha_reachable: bool = False
    ha_auth_mode: str = "none"
    scan_in_progress: bool = False
    degraded_reasons: list[str] = field(default_factory=list)
    # Dedupe key -> signature, so we only notify on change (PART 3).
    _notified: dict[str, str] = field(default_factory=dict)

    @property
    def uptime_seconds(self) -> int:
        return int(time.time() - self.started_at)

    @property
    def status(self) -> str:
        if self.degraded_reasons:
            return "degraded"
        if self.initializing:
            return "initializing"
        return "ok"

    def notify_once(self, key: str, signature: str) -> bool:
        """Return True only when this key's signature changed (anti-spam)."""
        if self._notified.get(key) == signature:
            return False
        self._notified[key] = signature
        return True


_state: Optional[AppState] = None


def get_app_state() -> AppState:
    global _state
    if _state is None:
        _state = AppState()
    return _state


# --------------------------------------------------------------------------
# Config dir + starter files
# --------------------------------------------------------------------------
def ensure_config_dir() -> Path:
    """Create the config dir and ensure the runtime YAML files exist (PART 9).

    Never writes into the container image; everything lives under CONFIG_DIR
    (e.g. /config/tpg_homeai in add-on mode).
    """
    settings = get_settings()
    base = settings.config_path
    base.mkdir(parents=True, exist_ok=True)

    # Seed hand-written config from a bundled template if present and missing.
    template_dir = _find_template_dir()
    if template_dir:
        for name in _STARTER_FILES:
            dest = base / name
            src = template_dir / name
            if not dest.exists() and src.exists():
                dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
                logger.info("Seeded starter config: %s", name)

    # Generated overlays must always exist as valid (possibly empty) YAML.
    for name in ("discovered.yaml", "ignored.yaml"):
        path = base / name
        if not path.exists():
            path.write_text(
                "# Managed by TPG HomeAI. Auto-generated; safe to edit.\n{}\n",
                encoding="utf-8",
            )
    return base


def _find_template_dir() -> Optional[Path]:
    candidates = [
        Path("/app/config_template"),           # add-on image
        Path(__file__).resolve().parents[3] / "config",  # repo ./config
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return None


# --------------------------------------------------------------------------
# Home Assistant connectivity
# --------------------------------------------------------------------------
async def _connect_ha(timeout: float) -> tuple[bool, str]:
    from ..homeassistant.rest import get_ha_client, reset_ha_client

    settings = get_settings()
    reset_ha_client()  # pick up any env changes since import
    if not settings.ha_configured:
        return False, settings.ha_auth_mode
    client = get_ha_client()
    try:
        ping = await asyncio.wait_for(client.ping(), timeout=timeout)
    except (asyncio.TimeoutError, Exception):  # noqa: BLE001
        return False, settings.ha_auth_mode
    return bool(ping.get("connected")), settings.ha_auth_mode


# --------------------------------------------------------------------------
# Bootstrap
# --------------------------------------------------------------------------
async def bootstrap() -> AppState:
    """Run the full startup sequence. Safe to call once per process."""
    state = get_app_state()
    settings = get_settings()
    state.mode = settings.app_mode

    # 1-2. Config dir + validate.
    try:
        ensure_config_dir()
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not prepare config dir: %s", exc)
    reload_config()

    # 3. Connect to Home Assistant (time-boxed).
    reachable, auth_mode = await _connect_ha(settings.ha_connect_timeout_seconds)
    state.ha_reachable = reachable
    state.ha_auth_mode = auth_mode

    # 4. Initial discovery scan (time-boxed). Degrade on failure.
    if settings.scan_on_start:
        await _run_scan_guarded(settings.initial_scan_timeout_seconds)

    # 5. Recompute degraded reasons + raise notifications.
    refresh_degraded_reasons(state)
    await emit_review_notifications(state)

    # 6. Ready.
    state.initializing = False
    state.ready = True
    get_event_bus().emit(EVT_BOOTSTRAP_READY, {"mode": state.mode,
                                               "ha_reachable": state.ha_reachable})
    logger.info("Bootstrap complete: status=%s mode=%s ha_reachable=%s",
                state.status, state.mode, state.ha_reachable)
    return state


async def _run_scan_guarded(timeout: float) -> Optional[dict[str, Any]]:
    state = get_app_state()
    state.scan_in_progress = True
    try:
        return await asyncio.wait_for(
            scanner.scan(
                auto_low_risk=get_settings().auto_approve_low_risk_entities,
                auto_domains=get_settings().auto_approve_domain_list,
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("Initial scan timed out after %ss; continuing degraded.", timeout)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Initial scan failed (%s); continuing degraded.", exc)
        return None
    finally:
        state.scan_in_progress = False


def refresh_degraded_reasons(state: AppState) -> list[str]:
    settings = get_settings()
    reasons: list[str] = []
    if config_error():
        reasons.append(f"Config error: {config_error()}")
    if not settings.ha_configured:
        reasons.append("Home Assistant not configured")
    elif not state.ha_reachable:
        reasons.append("Home Assistant API unreachable or unauthorized")
    if not settings.openai_configured:
        reasons.append("OpenAI API key missing (using fallback parser)")
    state.degraded_reasons = reasons
    return reasons


# --------------------------------------------------------------------------
# Notifications (PART 6) — emitted as events; integration renders them.
# --------------------------------------------------------------------------
async def emit_review_notifications(state: AppState) -> None:
    settings = get_settings()
    bus = get_event_bus()
    summary = await scanner.summary()

    def push(key: str, signature: str, title: str, message: str, severity: str) -> None:
        if state.notify_once(key, signature):
            bus.emit(EVT_NOTIFICATION, {"key": key, "title": title,
                                        "message": message, "severity": severity})

    pending = summary["pending_count"]
    if pending and settings.notify_on_new_devices:
        push("pending_approvals", f"n={pending}",
             "TPG HomeAI found new devices",
             f"{pending} new Home Assistant entit"
             f"{'y' if pending == 1 else 'ies'} need review. Open TPG HomeAI "
             "Discovery or use the tpg_homeai.approve_discovered_entity service.",
             "info")
    else:
        push("pending_approvals", "n=0", "", "", "info")

    unavailable = summary["unavailable"]
    if unavailable and settings.notify_on_unavailable_devices:
        names = ", ".join(unavailable[:10])
        push("unavailable", f"n={len(unavailable)}",
             "TPG HomeAI devices unavailable",
             f"{names} {'is' if len(unavailable) == 1 else 'are'} unavailable. "
             "They were not ignored.", "warning")
    else:
        push("unavailable", "n=0", "", "", "warning")

    if state.degraded_reasons:
        sig = "|".join(state.degraded_reasons)
        push("degraded", sig, "TPG HomeAI degraded",
             "Backend is running but needs attention: "
             + "; ".join(state.degraded_reasons), "warning")
    else:
        push("degraded", "ok", "", "", "warning")


# --------------------------------------------------------------------------
# Periodic background scan (PART 3)
# --------------------------------------------------------------------------
async def periodic_scan_loop() -> None:
    settings = get_settings()
    interval = max(1, int(settings.scan_interval_minutes)) * 60
    logger.info("Periodic discovery scan every %s minute(s).",
                settings.scan_interval_minutes)
    while True:
        try:
            await asyncio.sleep(interval)
            state = get_app_state()
            await _run_scan_guarded(settings.initial_scan_timeout_seconds)
            # Re-check HA reachability cheaply via last scan result.
            last = scanner.last_scan_summary()
            state.ha_reachable = bool(last.get("ha_reachable"))
            refresh_degraded_reasons(state)
            await emit_review_notifications(state)
        except asyncio.CancelledError:
            logger.info("Periodic scan loop cancelled.")
            raise
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            logger.warning("Periodic scan iteration errored: %s", exc)
