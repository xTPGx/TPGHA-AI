"""FastAPI application: TPG HomeAI Orchestrator backend."""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc

from .ai.client import get_ai_client
from .ai.tools import TOOL_NAMES
from .bootstrap import bootstrap, get_app_state, periodic_scan_loop
from .bootstrap.startup import refresh_degraded_reasons
from .config_loader import config_error, get_config, reload_config
from .config_editor import (
    save_permissions,
    upsert_assistant,
    upsert_devices_item,
    upsert_music_account,
    upsert_user,
)
from .conversation import answer_general
from .db.database import get_session, init_db
from .db.models import CommandLog
from .discovery import registry as discovery_registry
from .discovery import scanner as discovery_scanner
from .events import get_event_bus
from .homeassistant.rest import HAError, get_ha_client
from .homeassistant.services import get_states_cache, normalize_entity
from .models.results import CommandResponse
from .models.schemas import (
    ApproveRequest,
    ChatRequest,
    CommandRequest,
    ConfirmRequest,
    DashboardDraftRequest,
    DraftUpdateRequest,
    IgnoreRequest,
    MapRequest,
    MemoryDraftRequest,
    Assistant,
    MusicAccountUpsert,
    PermissionsUpsert,
    Room,
    ResolveRequest,
    ScanRequest,
    Speaker,
    TestActionRequest,
    User,
    VoiceSource,
    VoicePreviewRequest,
    VoiceSpeakRequest,
)
from .router import intent_router
from .router.action_policy import evaluate_action_policy
from .router.permissions import get_confirmation_store
from .actions.dashboards import build_dashboard_draft, install_dashboard_yaml
from .actions.automation_installer import install_automation_yaml
from .knowledge import build_house_graph
from .brain import build_brain_layers, build_completion_status
from .device_adapters import build_device_adapters
from .outcomes import build_device_profiles
from . import memory as memory_store
from . import proactive as proactive_store
from .router.resolver import Resolver
from .settings import get_settings
from .voice import (
    list_voice_profiles,
    list_voice_source_readiness,
    list_voices,
    preview_voice,
    speak_text,
    voice_audio_path,
)
from .house_state import (
    build_assistant_intelligence,
    build_house_state,
    build_mode_brain,
    build_tablet_profiles,
    build_wake_word_deployment,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("tpg.main")

APP_VERSION = "1.0.11"

# API path prefixes that the SPA fallback must NEVER intercept (PART 1).
_API_PREFIXES = (
    "api", "health", "state", "events", "config", "discovery", "command",
    "chat", "confirm", "confirmations", "automation", "suggestions", "ha",
    "dashboards", "debug", "knowledge", "memory", "brain", "ai", "voice", "test", "tools", "docs", "redoc",
    "openapi.json",
)

# HA ingress normally forwards backend calls as /<addon_slug>/api/...
# Some HA/proxy paths may arrive as /<addon_slug>/health, so keep a small
# allowlist for direct ingress API compatibility. Do not include frontend route
# names such as discovery/chat/suggestions/ha; those must serve index.html.
_INGRESS_DIRECT_API_PREFIXES = (
    "health", "state", "events", "config", "command", "confirm",
    "confirmations", "automation", "dashboards", "debug", "knowledge", "memory", "brain",
    "ai", "voice", "test", "tools", "docs", "redoc", "openapi.json",
)


def _iso(ts: float | None) -> str | None:
    if not ts:
        return None
    return datetime.datetime.fromtimestamp(
        ts, datetime.timezone.utc).isoformat()


def _command_context(req: CommandRequest) -> dict:
    return {
        "room": req.room,
        "source_device_id": req.source_device_id,
        "source_entity_id": req.source_entity_id,
    }


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
    """Accept /api and HA ingress /<addon_slug>/api calls."""
    path = request.scope.get("path", "")
    parts = path.lstrip("/").split("/", 2)
    if len(parts) >= 3 and parts[0] == "api" and parts[1] == "hassio_ingress":
        # HA ingress path: /api/hassio_ingress/<token>/api/health -> /api/health.
        token_rest = parts[2].split("/", 1)
        path = "/" + (token_rest[1] if len(token_rest) == 2 else "")
        request.scope["path"] = path
    elif len(parts) >= 2 and parts[1] == "api":
        # HA ingress path: /3e5a55d6_tpg_homeai/api/health -> /api/health.
        path = "/" + "/".join(parts[1:])
        request.scope["path"] = path
    elif len(parts) >= 2 and parts[0].lower() not in _API_PREFIXES:
        # HA ingress path forwarded without /api:
        # /3e5a55d6_tpg_homeai/health -> /health.
        rest_head = parts[1].split("/", 1)[0].lower()
        if rest_head in _INGRESS_DIRECT_API_PREFIXES:
            path = "/" + "/".join(parts[1:])
            request.scope["path"] = path
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


@app.post("/config/rooms")
async def upsert_room_endpoint(req: Room):
    try:
        result = upsert_devices_item("rooms", req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    cfg = reload_config()
    return {"saved": True, **result, "counts": {"rooms": len(cfg.devices.rooms)}}


@app.post("/config/assistants")
async def upsert_assistant_endpoint(req: Assistant):
    try:
        result = upsert_assistant(req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    cfg = reload_config()
    return {"saved": True, **result, "counts": {"assistants": len(cfg.assistants.assistants)}}


@app.post("/config/users")
async def upsert_user_endpoint(req: User):
    try:
        result = upsert_user(req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    cfg = reload_config()
    return {"saved": True, **result, "counts": {"users": len(cfg.assistants.users)}}


@app.post("/config/music-accounts")
async def upsert_music_account_endpoint(req: MusicAccountUpsert):
    try:
        result = upsert_music_account(req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    cfg = reload_config()
    return {"saved": True, **result, "counts": {"music_accounts": len(cfg.devices.music_accounts)}}


@app.post("/config/speakers")
async def upsert_speaker_endpoint(req: Speaker):
    try:
        result = upsert_devices_item("speakers", req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    cfg = reload_config()
    return {"saved": True, **result, "counts": {"speakers": len(cfg.devices.speakers)}}


@app.post("/config/permissions")
async def save_permissions_endpoint(req: PermissionsUpsert):
    try:
        result = save_permissions(req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    cfg = reload_config()
    return {"saved": True, **result, "counts": {"sensitive_actions": len(cfg.permissions.sensitive_actions)}}


@app.post("/config/voice-sources")
async def upsert_voice_source_endpoint(req: VoiceSource):
    try:
        result = upsert_devices_item("voice_sources", req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    cfg = reload_config()
    return {"saved": True, **result, "counts": {"voice_sources": len(cfg.devices.voice_sources)}}


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
    resp = await intent_router.handle_command(
        req.assistant, req.user, req.message, conversation_id=req.conversation_id,
        command_context=_command_context(req),
    )
    resp.conversation_id = req.conversation_id
    return resp


@app.post("/command/preview", response_model=CommandResponse)
async def command_preview(req: CommandRequest):
    resp = await intent_router.handle_preview(
        req.assistant, req.user, req.message, conversation_id=req.conversation_id,
        command_context=_command_context(req),
    )
    resp.conversation_id = req.conversation_id
    return resp


@app.post("/chat")
async def chat(req: ChatRequest):
    """Conversational entrypoint.

    This wraps the same guarded command path, but classifies no-tool OpenAI
    replies as normal conversation instead of a failed device command.
    """
    resp = await intent_router.handle_command(
        req.assistant, req.user, req.message, conversation_id=req.conversation_id,
        command_context=_command_context(req),
    )
    resp.conversation_id = req.conversation_id
    if resp.error == "no_tool_selected":
        general = await answer_general(
            req.assistant,
            req.user,
            req.message,
            conversation_id=req.conversation_id,
        )
        return {
            "success": True,
            "mode": general.get("mode", "conversation"),
            "response": general.get("response") or resp.message,
            "command": resp.model_dump(),
            "data": general.get("data", {}),
            "provider": general.get("provider"),
        }
    policy = evaluate_action_policy(resp)
    mode = "conversation"
    if resp.requires_confirmation:
        mode = "confirmation_required"
    elif policy.get("decision") == "proposal_required":
        mode = "proposal"
    elif resp.executed:
        mode = "action"
    elif resp.intent:
        mode = "action_result"
    success = resp.success
    return {
        "success": success,
        "mode": mode,
        "response": resp.message,
        "command": resp.model_dump(),
    }


@app.post("/chat/preview")
async def chat_preview(req: ChatRequest):
    resp = await intent_router.handle_preview(
        req.assistant, req.user, req.message, conversation_id=req.conversation_id,
        command_context=_command_context(req),
    )
    resp.conversation_id = req.conversation_id
    mode = "preview_confirmation_required" if resp.requires_confirmation else "preview"
    return {
        "success": resp.success,
        "mode": mode,
        "response": resp.message,
        "command": resp.model_dump(),
    }


@app.post("/confirm", response_model=CommandResponse)
async def confirm(req: ConfirmRequest):
    return await intent_router.handle_confirmation(req.confirmation_token, req.security_pin)


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
    "climate": "climate", "personal_device": "personal_devices",
    "device": "device_aliases",
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


# --------------------------------------------------------------- debug/audit
def _command_log_dict(row: CommandLog) -> dict:
    def _json_obj(value: str | None) -> dict:
        if not value:
            return {}
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    return {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "assistant": row.assistant,
        "user": row.user,
        "conversation_id": row.conversation_id,
        "message": row.message,
        "intent": row.intent,
        "success": row.success,
        "executed": row.executed,
        "response_message": row.response_message,
        "tool_call": _json_obj(row.tool_call),
        "resolved": _json_obj(row.resolved),
        "data": _json_obj(row.data),
        "error": row.error,
    }


@app.get("/debug/commands")
async def debug_commands(limit: int = 25):
    limit = max(1, min(100, limit))
    with get_session() as session:
        rows = session.query(CommandLog).order_by(
            desc(CommandLog.created_at), desc(CommandLog.id)
        ).limit(limit).all()
        return {"commands": [_command_log_dict(row) for row in rows]}


@app.get("/debug/last-command")
async def debug_last_command():
    with get_session() as session:
        row = session.query(CommandLog).order_by(
            desc(CommandLog.created_at), desc(CommandLog.id)
        ).first()
        return {"command": _command_log_dict(row) if row else None}


# --------------------------------------------------------------- knowledge
@app.get("/knowledge/graph")
async def knowledge_graph(include_registries: bool = True):
    return await build_house_graph(include_registries=include_registries)


@app.get("/knowledge/physical-devices")
async def physical_devices(include_registries: bool = True):
    graph = await build_house_graph(include_registries=include_registries)
    return {"devices": graph.get("physical_devices", [])}


@app.get("/knowledge/device-profiles")
async def device_profiles(include_registries: bool = True):
    graph = await build_house_graph(include_registries=include_registries)
    return build_device_profiles(graph)


@app.get("/knowledge/device-adapters")
async def device_adapters(include_registries: bool = True):
    graph = await build_house_graph(include_registries=include_registries)
    return build_device_adapters(graph)


@app.get("/knowledge/voice-sources")
async def voice_sources():
    cfg = get_config()
    return list_voice_source_readiness(cfg)


@app.get("/brain/layers")
async def brain_layers(include_registries: bool = True):
    graph = await build_house_graph(include_registries=include_registries)
    return build_brain_layers(graph)


@app.get("/brain/completion")
async def brain_completion(include_registries: bool = True):
    graph = await build_house_graph(include_registries=include_registries)
    return build_completion_status(graph, await health())


@app.get("/brain/house-state")
async def brain_house_state(include_registries: bool = True):
    cfg = get_config()
    graph = await build_house_graph(include_registries=include_registries)
    return await build_house_state(cfg, graph)


@app.get("/brain/modes")
async def brain_modes():
    return build_mode_brain(get_config())


@app.get("/brain/assistants")
async def brain_assistants():
    return build_assistant_intelligence(get_config())


@app.get("/ai/providers")
async def ai_providers():
    return get_ai_client().provider_status()


# ------------------------------------------------------------------- voice
@app.get("/voice/profiles")
async def voice_profiles():
    return list_voice_profiles(get_config())


@app.get("/voice/voices")
async def voice_voices():
    return list_voices()


@app.get("/voice/deployment")
async def voice_deployment():
    return build_wake_word_deployment(get_config())


@app.post("/voice/preview")
async def voice_preview(req: VoicePreviewRequest):
    return await preview_voice(
        req.assistant,
        req.text,
        voice_profile=req.voice_profile,
        target_entity_id=req.target_entity_id,
        room=req.room,
        source_device_id=req.source_device_id,
        source_entity_id=req.source_entity_id,
        reply_mode=req.reply_mode,
    )


@app.post("/voice/speak")
async def voice_speak(req: VoiceSpeakRequest):
    return await speak_text(
        req.assistant,
        req.text,
        voice_profile=req.voice_profile,
        target_entity_id=req.target_entity_id,
        force_browser=req.force_browser,
        room=req.room,
        source_device_id=req.source_device_id,
        source_entity_id=req.source_entity_id,
        reply_mode=req.reply_mode,
    )


@app.get("/voice/audio/{audio_id}")
async def voice_audio(audio_id: str):
    try:
        path = voice_audio_path(audio_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Voice audio not found")
    suffix = path.suffix.lower().lstrip(".") or "mp3"
    media_type = {
        "mp3": "audio/mpeg",
        "opus": "audio/ogg",
        "aac": "audio/aac",
        "flac": "audio/flac",
        "wav": "audio/wav",
        "pcm": "audio/pcm",
    }.get(suffix, "application/octet-stream")
    return FileResponse(path, media_type=media_type)


# ------------------------------------------------------------------ memory
@app.get("/memory")
async def memory_list(status: str | None = None):
    return {"memories": memory_store.list_memories(status=status)}


@app.post("/memory/draft")
async def memory_draft(req: MemoryDraftRequest):
    return {"memory": memory_store.propose_memory(
        scope=req.scope,
        owner=req.owner or "",
        subject=req.subject,
        key=req.key,
        value=req.value,
        source=req.source,
    )}


@app.post("/memory/{memory_id}/approve")
async def memory_approve(memory_id: int):
    try:
        return {"memory": memory_store.approve_memory(memory_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="Memory not found")


@app.post("/memory/{memory_id}/ignore")
async def memory_ignore(memory_id: int):
    try:
        return {"memory": memory_store.ignore_memory(memory_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="Memory not found")


# ------------------------------------------------------------ dashboards
@app.post("/dashboards/draft")
async def dashboard_draft(req: DashboardDraftRequest):
    cfg = get_config()
    return build_dashboard_draft(
        cfg,
        title=req.title,
        style=req.style,
        room=req.room,
        include_browser_mod=req.include_browser_mod,
        include_unavailable=req.include_unavailable,
        tablet_mode=req.tablet_mode,
        voice_panel=req.voice_panel,
    )


@app.get("/dashboards/draft")
async def dashboard_draft_get(
    title: str = "TPG Home",
    style: str = "native",
    room: str | None = None,
    include_browser_mod: bool = True,
    include_unavailable: bool = False,
    tablet_mode: bool = False,
    voice_panel: bool = False,
):
    cfg = get_config()
    return build_dashboard_draft(
        cfg,
        title=title,
        style=style,
        room=room,
        include_browser_mod=include_browser_mod,
        include_unavailable=include_unavailable,
        tablet_mode=tablet_mode,
        voice_panel=voice_panel,
    )


@app.get("/dashboards/tablet-profiles")
async def dashboard_tablet_profiles():
    return build_tablet_profiles(get_config())


@app.post("/dashboards/install")
async def dashboard_install(req: DashboardDraftRequest):
    cfg = get_config()
    draft = build_dashboard_draft(
        cfg,
        title=req.title,
        style=req.style,
        room=req.room,
        include_browser_mod=req.include_browser_mod,
        include_unavailable=req.include_unavailable,
        tablet_mode=req.tablet_mode,
        voice_panel=req.voice_panel,
    )
    install = install_dashboard_yaml(draft["yaml"], req.title)
    return {"draft": draft, "install": install}


# -------------------------------------------------------------- draft inbox
def _draft_dict(draft) -> dict:
    return {
        "id": draft.id,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
        "trigger_description": draft.trigger_description,
        "action_description": draft.action_description,
        "proposed_yaml": draft.proposed_yaml,
        "status": draft.status,
        "installed_id": getattr(draft, "installed_id", ""),
        "installed_path": getattr(draft, "installed_path", ""),
        "installed_at": draft.installed_at.isoformat() if getattr(draft, "installed_at", None) else None,
        "install_error": getattr(draft, "install_error", ""),
    }


@app.get("/automation/drafts")
async def automation_drafts(status: str | None = None):
    from .db.database import get_session
    from .db.models import AutomationDraft

    with get_session() as session:
        q = session.query(AutomationDraft).order_by(AutomationDraft.created_at.desc())
        if status:
            q = q.filter(AutomationDraft.status == status)
        return {"drafts": [_draft_dict(d) for d in q.all()]}


@app.get("/suggestions")
async def suggestions():
    from .db.database import get_session
    from .db.models import AutomationDraft

    with get_session() as session:
        rows = session.query(AutomationDraft).filter(
            AutomationDraft.status.in_(["draft", "suggested", "edited"])
        ).order_by(AutomationDraft.created_at.desc()).all()
        return {"suggestions": [_draft_dict(d) for d in rows]}


@app.post("/suggestions/generate")
async def suggestions_generate():
    return await memory_store.generate_suggestions()


@app.get("/suggestions/proactive")
async def proactive_suggestions(status: str | None = None):
    return {"suggestions": memory_store.list_suggestions(status=status)}


@app.post("/monitor/scan")
async def monitor_scan():
    generated = await memory_store.generate_suggestions()
    proactive = await proactive_store.scan_proactive()
    return {"suggestions": generated, "proactive": proactive}


@app.post("/suggestions/proactive/{suggestion_id}/approve")
async def proactive_suggestion_approve(suggestion_id: int):
    try:
        return {"suggestion": memory_store.update_suggestion(suggestion_id, "approved")}
    except KeyError:
        raise HTTPException(status_code=404, detail="Suggestion not found")


@app.post("/suggestions/proactive/{suggestion_id}/ignore")
async def proactive_suggestion_ignore(suggestion_id: int):
    try:
        return {"suggestion": memory_store.update_suggestion(suggestion_id, "ignored")}
    except KeyError:
        raise HTTPException(status_code=404, detail="Suggestion not found")


@app.post("/automation/drafts/{draft_id}/edit")
async def automation_draft_edit(draft_id: int, req: DraftUpdateRequest):
    from .db.database import get_session
    from .db.models import AutomationDraft

    with get_session() as session:
        draft = session.get(AutomationDraft, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft not found")
        if req.trigger_description is not None:
            draft.trigger_description = req.trigger_description
        if req.action_description is not None:
            draft.action_description = req.action_description
        if req.proposed_yaml is not None:
            draft.proposed_yaml = req.proposed_yaml
        draft.status = req.status or "edited"
        session.commit()
        return {"draft": _draft_dict(draft)}


@app.post("/automation/drafts/{draft_id}/approve")
async def automation_draft_approve(draft_id: int):
    """Approve and install an automation draft into Home Assistant."""
    from datetime import datetime, timezone
    from .db.database import get_session
    from .db.models import AutomationDraft

    with get_session() as session:
        draft = session.get(AutomationDraft, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft not found")
        try:
            installed = await install_automation_yaml(
                proposed_yaml=draft.proposed_yaml,
                draft_id=draft.id,
                ha=get_ha_client(),
            )
        except Exception as exc:  # noqa: BLE001 - surface install failure in UI
            draft.status = "approved_install_failed"
            draft.install_error = str(exc)
            session.commit()
            return {
                "approved": True,
                "installed": False,
                "message": f"Approved, but install failed: {exc}",
                "draft": _draft_dict(draft),
            }

        draft.status = "installed"
        draft.installed_id = installed["installed_id"]
        draft.installed_path = installed["path"]
        draft.installed_at = datetime.now(timezone.utc)
        draft.install_error = installed.get("reload_error") or ""
        session.commit()
        return {
            "approved": True,
            "installed": True,
            "message": (
                "Automation installed in Home Assistant."
                if installed.get("reload_ok")
                else "Automation file installed, but Home Assistant reload failed."
            ),
            "install": installed,
            "draft": _draft_dict(draft),
        }


@app.post("/automation/drafts/{draft_id}/ignore")
async def automation_draft_ignore(draft_id: int):
    from .db.database import get_session
    from .db.models import AutomationDraft

    with get_session() as session:
        draft = session.get(AutomationDraft, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft not found")
        draft.status = "ignored"
        session.commit()
        return {"ignored": True, "draft": _draft_dict(draft)}


@app.get("/")
async def root():
    if _STATIC_DIR:
        return FileResponse(os.path.join(_STATIC_DIR, "index.html"))
    return {"name": "TPG HomeAI Orchestrator", "docs": "/docs", "health": "/health"}


def _is_api_path(full_path: str) -> bool:
    head = full_path.split("/", 1)[0].lower()
    return head in _API_PREFIXES


def _strip_ingress_prefix(full_path: str) -> str:
    """Normalize HA add-on ingress paths.

    Supervisor ingress mounts the add-on at /<slug>, e.g.
    /3e5a55d6_tpg_homeai. Static assets then arrive as
    /3e5a55d6_tpg_homeai/assets/app.js. The backend itself only has an
    /assets mount, so strip the unknown first segment for static assets.
    API calls use /<slug>/api/... and are normalized by middleware.
    """
    hassio_prefix = "api/hassio_ingress/"
    if full_path.startswith(hassio_prefix):
        remainder = full_path[len(hassio_prefix):]
        token_rest = remainder.split("/", 1)
        if len(token_rest) == 2:
            rest = token_rest[1]
            if rest.split("/", 1)[0].lower() == "assets":
                return rest
        return full_path

    parts = full_path.split("/", 1)
    if len(parts) != 2:
        return full_path
    first, rest = parts[0].lower(), parts[1]
    rest_head = rest.split("/", 1)[0].lower()
    if first not in _API_PREFIXES and rest_head == "assets":
        return rest
    return full_path


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
        normalized_path = _strip_ingress_prefix(full_path)
        # Never let the SPA shadow an API route: unknown API paths get JSON 404.
        if _is_api_path(normalized_path):
            return JSONResponse({"detail": f"Not found: /{normalized_path}"}, status_code=404)
        # Serve a real static file if it exists, else index.html for routing.
        candidate = os.path.join(_STATIC_DIR, normalized_path)
        if normalized_path and os.path.isfile(candidate) and os.path.abspath(
                candidate).startswith(os.path.abspath(_STATIC_DIR)):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_STATIC_DIR, "index.html"))

    logger.info("Serving frontend from %s", _STATIC_DIR)
