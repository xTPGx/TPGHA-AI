"""Dashboard actions: resolve a dashboard key/area and return a navigation
target. Browser Mod wiring is a placeholder for the MVP."""
from __future__ import annotations

from typing import Any

from ..models.results import ActionResult
from . import ActionContext


async def open_dashboard(ctx: ActionContext, params: dict[str, Any]) -> ActionResult:
    intent = "open_dashboard"
    household = ctx.config.household.default_household()
    dashboards = household.dashboards if household else None

    key = (params.get("dashboard") or "").strip().lower()
    target = (params.get("target") or "").strip()

    path = None
    label = key or "default"
    if dashboards:
        mapping = {
            "default": dashboards.default,
            "security": dashboards.security,
            "cameras": dashboards.cameras,
            "music": dashboards.music,
            "climate": dashboards.climate,
        }
        # Infer dashboard from a free-text target if no key was given.
        if not key and target:
            for k in mapping:
                if k in target.lower():
                    key = k
                    break
        path = mapping.get(key) or dashboards.default
        label = key or "default"

    resolved = {"dashboard": label, "path": path, "target": target or None}
    msg = (
        f"Opening the {label} dashboard"
        + (f" ({path})" if path else "")
        + (f" for {target}." if target else ".")
        + " (Browser Mod navigation is a placeholder in the MVP.)"
    )
    data = {
        "browser_mod": {
            "service": "browser_mod.navigate",
            "data": {"path": path},
        }
    }
    return ActionResult(success=True, intent=intent, executed=False,
                        message=msg, resolved=resolved, data=data)
