"""FastAPI application: TPG HomeAI Orchestrator backend."""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .ai.client import get_ai_client
from .ai.tools import TOOL_NAMES
from .bootstrap import bootstrap, get_app_state, periodic_scan_loop
from .bootstrap.startup import refresh_degraded_reasons
from .config_loader import config_error, get_config, reload_config
from .db.database import init_db
from .discovery import registry as discovery_registry
from .discovery import scanner as discovery_scanner
from .events import get_event_bus
from .homeassistant.rest import HAError, get_ha_client
from .homeassistant.services import get_states_cache, normalize_entity
from .models.results import CommandResponse
from .models.schemas import (
    ApproveRequest,
    CommandRequest,
    ConfirmRequest,
    IgnoreRequest,
    MapRequest,
    ResolveRequest,
    ScanRequest,
    TestActionRequest,
)
from .router import intent_router
from .router.permissions import get_confirmation_store
from .router.resolver import Resolver
from .settings import get_settings

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("tpg.main")

APP_VERSION = "0.1.6"

# API path prefixes that the SPA fallback must NEVER intercept (PART 1).
_API_PREFIXES = (
    "api", "health", "state", "events", "config", "discovery", "command", "confirm",
    "confirmations", "ha", "test", "tools", "docs", "redoc", "openapi.json",
)


def _iso(ts: float | None) -> str | None:
    if not ts:
        return None
    return datetime.datetime.fromtimestamp(
        ts, datetime.timezone.utc).isoformat()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    get_config()
    # Run bootstrap in the background so the server is immediately responsive
    # (/health reports "initializing" until the first scan finishes). Then keep
    # the registry fresh with a periodic scan.
    tasks = [
        asyncio.create_task(bootstrap()),
        asyncio.create_task(periodic_scan_loop()),
    ]
    logger.info("TPG HomeAI Orchestrator starting; bootstrap running in background.")
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except BaseException:  # noqa: BLE001 - best-effort shutdown
                pass


app = FastAPI(title="TPG HomeAI Orchestrator", version=APP_VERSION, lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def api_prefix_compatibility(request: Request, call_next):
    """Accept legacy frontend calls built with VITE_API_BASE=/api."""
    path = request.scope.get("path", "")
    if path == "/api":
        request.scope["path"] = "/"
    elif path.startswith("/api/"):
        request.scope["path"] = path[4:]
    return await call_next(request)


# --------------------------------------------------------------------- health
@app.get("/health")
async def health():
    """Always-JSON health snapshot (PART 4). Never blocks on a live HA call;
    Home Assistant reachability reflects the last bootstrap/periodic scan."""
    s = get_settings()
    ai = get_ai_client()
    state = get_app_state()
    cfg_err = config_error()
    disc = await discovery_scanner.summary()
    refresh_degraded_reasons(state)
    reasons = state.degraded_reasons
    status = "degraded" if reasons else ("initializing" if state.initializing else "ok")
    return {
        "status": status,
        "reasons": reasons,
        "backend": {
            "online": True,
            "version": app.version,
            "mode": state.mode,
            "ready": state.ready,
            "initializing": state.initializing,
            "started_at": _iso(state.started_at),
            "uptime_seconds": state.uptime_seconds,
        },
        "home_assistant": {
            "configured": s.ha_configured,
            "reachable": state.ha_reachable,
            "url": s.home_assistant_url,
            "auth_mode": s.ha_auth_mode,
        },
        "openai": {
            "configured": s.openai_configured,
            "mode": "openai" if ai.using_openai else "fallback_parser",
        },
        "discovery": {
            "last_scan_ts": disc["last_scan_ts"],
            "last_successful_scan_ts": disc["last_successful_scan_ts"],
            "scan_in_progress": state.scan_in_progress,
            "known_count": disc["known_count"],
            "pending_count": disc["pending_count"],
            "unavailable_count": disc["unavailable_count"],
        },
        "config": {
            "config_dir": s.config_dir,
            "valid": cfg_err is None,
            "error": cfg_err,
        },
        "pending_confirmations": len(get_confirmation_store().list_pending()),
        "last_command": get_event_bus().last_command,
        "settings": s.safe_dict(),
    }


# --------------------------------------------------------------------- config
@app.get("/config")
async def get_config_endpoint():
    cfg = get_config()
    return cfg.model_dump()


@app.post("/config/reload")
async def reload_config_endpoint():
    cfg = reload_config()
    return {"reloaded": True, "summary": {
        "households": len(cfg.household.households),
        "users": len(cfg.assistants.users),
        "assistants": len(cfg.assistants.assistants),
        "rooms": len(cfg.devices.rooms),
        "cameras": len(cfg.devices.cameras),
        "locks": len(cfg.devices.locks),
        "speakers": len(cfg.devices.speakers),
    }}


# --------------------------------------------------------- home assistant data
@app.get("/ha/entities")
async def ha_entities():
    ha = get_ha_client()
    try:
        raw = await ha.get_states()
    except HAError as exc:
        raise HTTPException(status_code=502, detail=exc.message)
    return [normalize_entity(item).model_dump() for item in raw]


@app.get("/ha/entity/{entity_id}")
async def ha_entity(entity_id: str):
    ha = get_ha_client()
    try:
        item = await ha.get_entity(entity_id)
    except HAError as exc:
        status = 404 if exc.status == 404 else 502
        raise HTTPException(status_code=status, detail=exc.message)
    if not item:
        raise HTTPException(status_code=404, detail="Entity not found")
    return normalize_entity(item).model_dump()


# -------------------------------------------------------------------- commands
@app.post("/command", response_model=CommandResponse)
async def command(req: CommandRequest):
    resp = await intent_router.handle_command(req.assistant, req.user, req.message)
    resp.conversation_id = req.conversation_id
    return resp


@app.post("/confirm", response_model=CommandResponse)
async def confirm(req: ConfirmRequest):
    return await intent_router.handle_confirmation(req.confirmation_token)


@app.post("/confirm/cancel", response_model=CommandResponse)
async def confirm_cancel(req: ConfirmRequest):
    return intent_router.cancel_confirmation(req.confirmation_token)


@app.get("/confirmations/pending")
async def confirmations_pending():
    store = get_confirmation_store()
    return {"pending": [pc.public_dict() for pc in store.list_pending()]}


# ------------------------------------------------------------------- discovery
@app.get("/discovery/scan")
async def discovery_scan():
    cfg = get_config()
    return await discovery_scanner.scan(
        auto_low_risk=False,
        auto_domains=[],
    )


@app.post("/discovery/scan")
async def discovery_scan_post(req: ScanRequest):
    return await discovery_scanner.scan(
        auto_low_risk=req.auto_approve_low_risk,
        auto_domains=req.auto_approve_domains,
    )


@app.get("/discovery/pending")
async def discovery_pending():
    return {"pending": discovery_registry.get_pending()}


@app.get("/discovery/summary")
async def discovery_summary():
    return await discovery_scanner.summary()


@app.post("/discovery/approve")
async def discovery_approve(req: ApproveRequest):
    mapping = req.mapping or "device_aliases"
    result = discovery_registry.approve(
        req.entity_id, mapping=mapping, room=req.room,
        friendly_name=req.friendly_name, aliases=req.aliases,
    )
    reload_config()
    return {"approved": True, **result}


@app.post("/discovery/ignore")
async def discovery_ignore(req: IgnoreRequest):
    result = discovery_registry.ignore(req.entity_id, reason=req.reason or "")
    reload_config()
    return {"ignored": True, **result}


_MAP_TO_SECTION = {
    "speaker": "speakers", "display": "displays", "camera": "cameras",
    "security_sensor": "security_sensors", "lock": "locks",
    "climate": "climate", "device": "device_aliases",
}


@app.post("/discovery/map")
async def discovery_map(req: MapRequest):
    section = _MAP_TO_SECTION.get(req.target)
    if section is None:
        raise HTTPException(status_code=400, detail=f"Unknown map target '{req.target}'.")
    result = discovery_registry.approve(
        req.entity_id, mapping=section, room=req.room,
        friendly_name=req.friendly_name, aliases=req.aliases,
    )
    reload_config()
    return {"mapped": True, **result}


@app.post("/discovery/reload")
async def discovery_reload():
    cfg = reload_config()
    return {"reloaded": True, "rooms": len(cfg.devices.rooms),
            "device_aliases": len(cfg.devices.device_aliases)}


# ----------------------------------------------------------------- events/state
@app.get("/events")
async def events(since: int = 0, limit: int = 100):
    bus = get_event_bus()
    return {"latest_id": bus.latest_id(), "events": bus.recent(since, limit)}


@app.get("/state")
async def state():
    """Compact operational snapshot used by the HA integration sensors."""
    bus = get_event_bus()
    st = get_app_state()
    disc = await discovery_scanner.summary()
    cfg_err = config_error()
    refresh_degraded_reasons(st)
    pending_conf = [pc.public_dict() for pc in get_confirmation_store().list_pending()]
    needs_attention = bool(
        cfg_err or disc["pending_count"] or pending_conf
        or disc["unavailable_count"] or st.degraded_reasons
    )
    return {
        "version": app.version,
        "status": st.status,
        "reasons": st.degraded_reasons,
        "mode": st.mode,
        "ready": st.ready,
        "initializing": st.initializing,
        "scan_in_progress": st.scan_in_progress,
        "ha_reachable": st.ha_reachable,
        "config_ok": cfg_err is None,
        "config_error": cfg_err,
        "pending_approvals": disc["pending_count"],
        "known_devices": disc["known_count"],
        "unavailable_devices": disc["unavailable_count"],
        "unavailable": disc["unavailable"],
        "pending_confirmations": pending_conf,
        "last_command": bus.last_command,
        "last_scan_ts": disc["last_scan_ts"],
        "last_successful_scan_ts": disc["last_successful_scan_ts"],
        "needs_attention": needs_attention,
    }


# ----------------------------------------------------------------------- tests
@app.post("/test/resolve")
async def test_resolve(req: ResolveRequest):
    cfg = get_config()
    from .homeassistant.services import safe_get_states

    live = await safe_get_states()
    resolver = Resolver(cfg, live)
    kind = req.kind.lower()
    dispatch = {
        "assistant": resolver.resolve_assistant,
        "user": resolver.resolve_user,
        "room": resolver.resolve_room,
        "camera": resolver.resolve_camera,
        "lock": resolver.resolve_lock,
        "speaker": resolver.resolve_speaker,
        "display": resolver.resolve_display,
        "device": resolver.resolve_device_alias,
    }
    if kind == "music":
        result = resolver.resolve_music_account(req.user or req.name)
    elif kind in dispatch:
        result = dispatch[kind](req.name)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown resolve kind '{req.kind}'.")
    return result.model_dump()


@app.post("/test/action")
async def test_action(req: TestActionRequest):
    """Run a single action handler directly with explicit params (bypasses AI)."""
    if req.action not in TOOL_NAMES:
        raise HTTPException(status_code=400, detail=f"Unknown action '{req.action}'.")
    ctx = await intent_router.build_context(req.assistant, req.user)
    handler = intent_router._HANDLERS.get(req.action)
    if handler is None:
        raise HTTPException(status_code=400, detail="No handler for action.")
    result = await handler(ctx, req.params)
    return intent_router._to_response(ctx, result, {"name": req.action, "arguments": req.params,
                                                     "source": "test"}).model_dump()


@app.get("/tools")
async def list_tools():
    return {"tools": TOOL_NAMES}


@app.get("/")
async def root():
    if _STATIC_DIR:
        return FileResponse(os.path.join(_STATIC_DIR, "index.html"))
    return {"name": "TPG HomeAI Orchestrator", "docs": "/docs", "health": "/health"}


def _is_api_path(full_path: str) -> bool:
    head = full_path.split("/", 1)[0].lower()
    return head in _API_PREFIXES


# --------------------------------------------------------------- static (SPA)
# When STATIC_DIR points at a built frontend (e.g. inside the Home Assistant
# add-on image), serve the React SPA. Registered last so all API routes win.
# The catch-all explicitly refuses API prefixes so it can NEVER return HTML for
# an API call (the cause of the "Unexpected token '<'" error) — PART 1.
_STATIC_DIR = os.environ.get("STATIC_DIR", "")
if _STATIC_DIR and os.path.isdir(_STATIC_DIR):
    _assets = os.path.join(_STATIC_DIR, "assets")
    if os.path.isdir(_assets):
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        # Never let the SPA shadow an API route: unknown API paths get JSON 404.
        if _is_api_path(full_path):
            return JSONResponse({"detail": f"Not found: /{full_path}"}, status_code=404)
        # Serve a real static file if it exists, else index.html for routing.
        candidate = os.path.join(_STATIC_DIR, full_path)
        if full_path and os.path.isfile(candidate) and os.path.abspath(
                candidate).startswith(os.path.abspath(_STATIC_DIR)):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_STATIC_DIR, "index.html"))

    logger.info("Serving frontend from %s", _STATIC_DIR)
