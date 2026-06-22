"""Camera actions: resolve a camera and surface it via the configured display.

Display routing (PART 9) supports three target types:
  - dashboard    -> return the dashboard path (no live navigation)
  - browser_mod  -> call browser_mod.navigate on a browser_id
  - media_player -> attempt to cast/show on a media_player (if supported)
If no display is configured we just report the camera status + dashboard path.
"""
from __future__ import annotations

from typing import Any, Optional

from ..homeassistant.rest import HAError
from ..models.results import ActionResult
from ..models.schemas import Camera, Display
from . import ActionContext


def _norm(s: str) -> str:
    return " ".join(str(s).strip().lower().split())


def _find_camera(ctx: ActionContext, entity_id: str) -> Optional[Camera]:
    for c in ctx.config.devices.cameras:
        if c.entity_id == entity_id:
            return c
    return None


def _find_display(ctx: ActionContext, name: Optional[str]) -> Optional[Display]:
    if not name:
        return None
    q = _norm(name)
    for d in ctx.config.devices.displays:
        names = {_norm(x) for x in [d.id, d.name, *d.aliases] if x}
        if q in names or q == _norm(d.entity_id or ""):
            return d
    return None


async def show_camera(ctx: ActionContext, params: dict[str, Any]) -> ActionResult:
    intent = "show_camera"
    name = (params.get("camera") or params.get("target") or "").strip()
    if not name:
        return ActionResult.fail(intent, "Which camera would you like to see?")

    res = ctx.resolver.resolve_camera(name)
    if not res.matched:
        return ActionResult.fail(intent, f"I couldn't find a camera for '{name}'. {res.reason}")

    entity_id = res.entity_id or res.data.get("entity_id")
    cam_name = res.name or name
    resolved = {"camera": name, "entity_id": entity_id, "confidence": res.confidence,
                "reason": res.reason}

    # Live state (best effort).
    state_text = ""
    online: Optional[bool] = None
    try:
        state = await ctx.ha.get_entity(entity_id)
        if state:
            online = state.get("state") not in ("unavailable", "unknown")
            state_text = f" Status: {state.get('state')}."
            resolved["state"] = state.get("state")
    except HAError as exc:
        state_text = f" (Could not read live state: {exc.message})"

    household = ctx.config.household.default_household()
    cameras_dash = (household.dashboards.cameras if household else None) or (
        household.dashboards.security if household else None)
    cam_cfg = _find_camera(ctx, entity_id)
    cam_dash = (cam_cfg.dashboard_path if cam_cfg else None) or cameras_dash

    display_name = params.get("display") or params.get("target") or (
        household.default_display if household else None)
    display = _find_display(ctx, display_name)

    onoff = "online" if online else ("offline" if online is False else "available")

    # No display configured -> report status + dashboard path.
    if display is None:
        message = (f"{cam_name} camera is {onoff}. Open it from "
                   f"{cam_dash or 'the Security dashboard'}.{state_text}")
        return ActionResult(success=True, intent=intent, executed=False,
                            message=message, resolved=resolved,
                            data={"display": None, "dashboard_path": cam_dash})

    resolved["display"] = display.id
    resolved["display_type"] = display.type

    # dashboard -> just hand back the path.
    if display.type == "dashboard":
        path = display.dashboard_path or cam_dash
        return ActionResult(success=True, intent=intent, executed=False,
                            message=f"{cam_name} is {onoff}. Open {path} on {display.name}.{state_text}",
                            resolved=resolved, data={"dashboard_path": path})

    # browser_mod -> navigate a browser to the camera dashboard.
    if display.type == "browser_mod":
        path = display.dashboard_path or cam_dash or "/lovelace/cameras"
        call = {"service": "browser_mod.navigate",
                "data": {"browser_id": display.browser_id, "path": path}}
        try:
            await ctx.ha.call_service("browser_mod", "navigate",
                                      {"browser_id": display.browser_id, "path": path})
            return ActionResult(success=True, intent=intent, executed=True,
                                message=f"Navigated {display.name} to {cam_name} ({path}).",
                                resolved=resolved, data={"browser_mod": call})
        except HAError as exc:
            return ActionResult(success=False, intent=intent, executed=False,
                                message=(f"Couldn't navigate {display.name} (Browser Mod): "
                                         f"{exc.message}. Camera is {onoff} at {path}."),
                                resolved=resolved, data={"browser_mod": call},
                                error="browser_mod_failed")

    # media_player -> attempt to cast the camera stream.
    if display.type == "media_player":
        call = {"service": "media_player.play_media",
                "data": {"entity_id": display.entity_id,
                         "media_content_id": entity_id, "media_content_type": "image"}}
        try:
            await ctx.ha.play_media(display.entity_id, media_content_id=entity_id,
                                    media_content_type="image")
            return ActionResult(success=True, intent=intent, executed=True,
                                message=f"Showing {cam_name} on {display.name}.{state_text}",
                                resolved=resolved, data={"media_player": call})
        except HAError as exc:
            return ActionResult(success=False, intent=intent, executed=False,
                                message=(f"{display.name} couldn't show {cam_name}: "
                                         f"{exc.message}. The camera is {onoff}."),
                                resolved=resolved, data={"media_player": call},
                                error="cast_failed")

    return ActionResult(success=True, intent=intent, executed=False,
                        message=f"{cam_name} is {onoff}.{state_text}", resolved=resolved)
