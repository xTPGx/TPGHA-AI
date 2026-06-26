"""Security check: report lock status, camera status, and security sensors."""
from __future__ import annotations

from typing import Any

from ..homeassistant.services import safe_get_states
from ..media_brain import build_camera_security_brain
from ..models.results import ActionResult
from . import ActionContext


async def security_check(ctx: ActionContext, params: dict[str, Any]) -> ActionResult:
    intent = "security_check"
    brain = await build_camera_security_brain(ctx.config)
    states = await safe_get_states()

    locks_report = []
    for lk in ctx.config.devices.locks:
        ent = states.get(lk.entity_id)
        state = ent.state if ent else "unknown"
        locks_report.append({"name": lk.name, "entity_id": lk.entity_id, "state": state})

    cameras_report = []
    for cam in ctx.config.devices.cameras:
        ent = states.get(cam.entity_id)
        online = ent.available if ent else None
        cameras_report.append({
            "name": cam.name, "entity_id": cam.entity_id,
            "state": ent.state if ent else "unknown",
            "online": online,
        })

    sensors_report = []
    for s in ctx.config.devices.security_sensors:
        ent = states.get(s.entity_id)
        sensors_report.append({
            "name": s.name, "entity_id": s.entity_id,
            "state": ent.state if ent else "unknown",
        })

    # Build a human summary.
    unlocked = [l["name"] for l in locks_report if l["state"] == "unlocked"]
    locked = [l["name"] for l in locks_report if l["state"] == "locked"]
    cams_online = [c["name"] for c in cameras_report if c["online"]]
    cams_offline = [c["name"] for c in cameras_report if c["online"] is False]

    parts = []
    if locked:
        parts.append(f"Locked: {', '.join(locked)}.")
    if unlocked:
        parts.append(f"UNLOCKED: {', '.join(unlocked)}.")
    if not locks_report:
        parts.append("No locks configured.")
    if cams_online:
        parts.append(f"Cameras online: {', '.join(cams_online)}.")
    if cams_offline:
        parts.append(f"Cameras offline: {', '.join(cams_offline)}.")
    if not states:
        parts.append("(Live Home Assistant state unavailable; showing config only.)")

    message = brain.get("briefing") or " ".join(parts) or "Security status compiled."
    return ActionResult(
        success=True, intent=intent, executed=False, message=message,
        data={
            "locks": locks_report,
            "cameras": cameras_report,
            "sensors": sensors_report,
            "briefing": brain,
        },
    )
