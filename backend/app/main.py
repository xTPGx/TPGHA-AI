"""FastAPI application: TPG HomeAI Orchestrator backend."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .ai.client import get_ai_client
from .ai.tools import TOOL_NAMES
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    get_config()
    logger.info("TPG HomeAI Orchestrator started.")
    yield


app = FastAPI(title="TPG HomeAI Orchestrator", version="0.1.0", lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------- health
@app.get("/health")
async def health():
    s = get_settings()
    ha = get_ha_client()
    ai = get_ai_client()
    ha_status = await ha.ping() if s.ha_configured else {"connected": False, "message": "not configured"}
    cfg_err = config_error()
    disc = await discovery_scanner.summary()
    bus = get_event_bus()
    status = "degraded" if cfg_err else "ok"
    return {
        "status": status,
        "version": app.version,
        "config_ok": cfg_err is None,
        "config_error": cfg_err,
        "openai_configured": s.openai_configured,
        "openai_mode": "openai" if ai.using_openai else "fallback",
        "home_assistant": {
            "configured": s.ha_configured,
            "url": s.home_assistant_url,
            **ha_status,
        },
        "discovery": {
            "pending_approvals": disc["pending_count"],
            "known_devices": disc["known_count"],
            "unavailable_devices": disc["unavailable_count"],
            "last_scan_ts": disc["last_scan_ts"],
        },
        "pending_confirmations": len(get_confirmation_store().list_pending()),
        "last_command": bus.last_command,
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
    disc = await discovery_scanner.summary()
    cfg_err = config_error()
    pending_conf = [pc.public_dict() for pc in get_confirmation_store().list_pending()]
    needs_attention = bool(
        cfg_err or disc["pending_count"] or pending_conf
        or disc["unavailable_count"]
    )
    return {
        "version": app.version,
        "config_ok": cfg_err is None,
        "config_error": cfg_err,
        "pending_approvals": disc["pending_count"],
        "known_devices": disc["known_count"],
        "unavailable_devices": disc["unavailable_count"],
        "unavailable": disc["unavailable"],
        "pending_confirmations": pending_conf,
        "last_command": bus.last_command,
        "last_scan_ts": disc["last_scan_ts"],
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


# --------------------------------------------------------------- static (SPA)
# When STATIC_DIR points at a built frontend (e.g. inside the Home Assistant
# add-on image), serve the React SPA. Registered last so all API routes win.
_STATIC_DIR = os.environ.get("STATIC_DIR", "")
if _STATIC_DIR and os.path.isdir(_STATIC_DIR):
    _assets = os.path.join(_STATIC_DIR, "assets")
    if os.path.isdir(_assets):
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        # Serve a real file if it exists, else index.html for client routing.
        candidate = os.path.join(_STATIC_DIR, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_STATIC_DIR, "index.html"))

    logger.info("Serving frontend from %s", _STATIC_DIR)
