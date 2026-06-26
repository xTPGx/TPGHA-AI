"""FastAPI application: TPG HomeAI Orchestrator backend."""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc
import yaml

from .ai.client import get_ai_client
from .ai.tools import TOOL_NAMES
from .bootstrap import bootstrap, get_app_state, periodic_scan_loop
from .bootstrap.startup import refresh_degraded_reasons
from .config_loader import config_error, get_config, reload_config
from .config_editor import (
    save_permissions,
    sync_ha_users,
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
from .homeassistant.websocket import HomeAssistantWebSocket
from .models.results import CommandResponse
from .models.schemas import (
    ApproveRequest,
    AcceptanceResultRequest,
    ChatRequest,
    CommandRequest,
    ConfirmRequest,
    DashboardDraftRequest,
    DraftUpdateRequest,
    FollowupPreferenceRequest,
    ConversationNoteRequest,
    IgnoreRequest,
    MapRequest,
    MemoryDraftRequest,
    ResearchSearchRequest,
    Assistant,
    MusicAccountUpsert,
    PermissionsUpsert,
    Room,
    ResolveRequest,
    ScanRequest,
    Speaker,
    TestActionRequest,
    UISessionRequest,
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
from .outcomes import build_device_profiles, build_reliability_summary
from . import memory as memory_store
from . import notebook as notebook_store
from . import proactive as proactive_store
from . import house_assets as house_assets_store
from . import research as research_store
from .router.resolver import Resolver
from .settings import get_settings
from .transcription import transcribe_audio
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
    build_voice_runtime,
    build_wake_word_deployment,
)
from .media_brain import (
    build_camera_security_brain,
    build_jarvis_phase_66_71,
    build_media_control_brain,
    build_music_assistant_brain,
    build_room_occupancy_brain,
)
from .situational_brain import (
    build_calendar_todo_brain,
    build_daily_briefing,
    build_environment_brain,
    build_jarvis_phase_72_76,
    build_maintenance_brain,
    build_presence_zone_brain,
)
from .routine_brain import (
    build_comfort_energy_brain,
    build_jarvis_phase_77_81,
    build_media_scene_brain,
    build_proactive_action_plan,
    build_security_routine_brain,
    build_sleep_wake_brain,
)
from .operations_brain import (
    build_backup_recovery_readiness,
    build_capability_gap_scanner,
    build_diagnostics_support_pack,
    build_integration_readiness_matrix,
    build_jarvis_phase_82_86,
    build_chat_followups,
    list_chat_followup_preferences,
    build_onboarding_wizard_plan,
    build_role_prompt_insights,
    build_role_action_policy,
    build_role_dashboard_summary,
    build_role_suggested_prompts,
    save_chat_followup_preference,
    build_sidebar_access_diagnostics,
)
from .governance_brain import (
    build_completion_auditor,
    build_jarvis_phase_87_91,
    build_memory_quality_report,
    build_privacy_data_controls,
    build_redacted_context_export,
    build_role_permission_matrix,
)
from .experience_brain import (
    build_acceptance_resolution_summary,
    build_acceptance_repair_queue,
    build_device_acceptance_matrix,
    build_interaction_quality_report,
    build_jarvis_phase_92_96,
    build_jarvis_phase_97,
    build_jarvis_phase_101,
    build_jarvis_phase_103,
    build_jarvis_phase_104,
    build_jarvis_phase_105,
    build_jarvis_phase_106,
    build_jarvis_phase_107,
    build_jarvis_phase_108,
    build_jarvis_phase_109,
    build_jarvis_phase_110,
    build_jarvis_phase_111,
    build_jarvis_phase_112,
    build_jarvis_phase_113,
    build_jarvis_phase_114,
    build_jarvis_phase_115,
    build_jarvis_phase_116,
    build_jarvis_phase_117,
    build_jarvis_phase_118,
    build_jarvis_phase_119,
    build_jarvis_phase_120,
    build_jarvis_phase_121,
    build_jarvis_phase_122,
    build_jarvis_phase_123,
    build_jarvis_phase_124,
    build_jarvis_phase_125,
    build_jarvis_phase_126,
    build_jarvis_phase_127,
    build_jarvis_phase_128,
    list_live_acceptance_results,
    build_live_acceptance_report,
    build_live_acceptance_runner,
    build_operational_runbook,
    build_role_acceptance_matrix,
    record_live_acceptance_result,
    build_release_checklist,
    build_setup_action_plan,
    build_setup_support_packet,
    build_voice_acceptance_plan,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("tpg.main")

APP_VERSION = "1.2.32"

# API path prefixes that the SPA fallback must NEVER intercept (PART 1).
_API_PREFIXES = (
    "api", "health", "state", "events", "ui", "config", "discovery", "command",
    "chat", "confirm", "confirmations", "automation", "suggestions", "ha",
    "dashboards", "debug", "knowledge", "house", "memory", "conversations", "research", "brain", "ai", "voice", "test", "tools", "docs", "redoc",
    "media", "security", "rooms", "awareness", "briefings", "routines", "ops", "governance", "context", "experience", "release", "openapi.json",
)

# Paths that stay reachable without a bearer token even when TPG_API_TOKEN is
# set (health checks, public TTS audio for room speakers, static UI + docs).
_PUBLIC_NO_AUTH_PREFIXES = (
    "/health", "/voice/audio", "/assets", "/docs", "/redoc", "/openapi.json",
    "/favicon", "/logo", "/icon", "/manifest", "/robots",
)


def _request_is_ingress(request: Request) -> bool:
    """True when the request arrived through Home Assistant's Supervisor ingress.

    Ingress requests are already authenticated by Home Assistant, so the
    optional bearer guard only applies to direct LAN access on port 8088.
    """
    h = request.headers
    if h.get("x-ingress-path") or h.get("x-hass-source") or h.get("x-remote-user-id"):
        return True
    raw = request.scope.get("path", "")
    return "hassio_ingress" in raw


def _is_public_no_auth(path: str) -> bool:
    p = (path or "/").lower()
    if p == "/" or p == "":
        return True
    return any(p.startswith(prefix) for prefix in _PUBLIC_NO_AUTH_PREFIXES)


def _auth_guard_response(request: Request) -> JSONResponse | None:
    """Optional bearer-token guard for non-ingress (direct port) requests.

    No-op unless TPG_API_TOKEN is configured. Ingress + public paths are exempt.
    """
    token = (get_settings().api_token or "").strip()
    if not token:
        return None
    if request.method == "OPTIONS":
        return None
    if _request_is_ingress(request):
        return None
    if _is_public_no_auth(request.scope.get("path", "")):
        return None
    header = request.headers.get("authorization", "")
    supplied = header[7:].strip() if header[:7].lower() == "bearer " else ""
    if supplied and secrets.compare_digest(supplied, token):
        return None
    return JSONResponse(
        {"detail": "Unauthorized: missing or invalid API token."},
        status_code=401,
    )


# HA ingress normally forwards backend calls as /<addon_slug>/api/...
# Some HA/proxy paths may arrive as /<addon_slug>/health, so keep a small
# allowlist for direct ingress API compatibility. Do not include frontend route
# names such as discovery/chat/suggestions/ha; those must serve index.html.
_INGRESS_DIRECT_API_PREFIXES = (
    "health", "state", "events", "ui", "config", "command", "confirm",
    "confirmations", "automation", "dashboards", "debug", "knowledge", "house", "memory", "conversations", "research", "brain",
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
    guard = _auth_guard_response(request)
    if guard is not None:
        return guard
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


@app.get("/ui/session")
async def ui_session(request: Request):
    return await _build_ui_session(request)


@app.post("/ui/session")
async def ui_session_verified(request: Request, req: UISessionRequest):
    return await _build_ui_session(
        request,
        ha_access_token=req.ha_access_token,
        ha_client_user=req.ha_client_user,
    )


@app.get("/ui/session/debug")
async def ui_session_debug(request: Request):
    """Visible diagnostics for identity resolution in a real HA install.

    Echoes the identity-relevant request headers HA/Supervisor inject, the
    candidate identity values parsed from each source, and which TPG user each
    source resolves to. No secrets are returned.
    """
    cfg = get_config()
    users = cfg.assistants.users
    relevant_prefixes = (
        "x-remote-user", "x-hass", "x-ingress", "x-ha-", "x-tpg", "x-forwarded",
    )
    headers = {
        k: v for k, v in request.headers.items()
        if any(k.lower().startswith(p) for p in relevant_prefixes)
    }
    ingress_c = _ingress_user_candidates(request)
    header_c = _user_header_candidates(request)
    ingress_match = _detect_user_from_candidates(ingress_c, users)
    header_match = _detect_user_from_candidates(header_c, users)
    return {
        "version": APP_VERSION,
        "path": request.scope.get("path"),
        "is_ingress_request": bool(
            request.headers.get("x-ingress-path")
            or request.headers.get("x-hass-source")
            or ingress_c
        ),
        "x_ingress_path": request.headers.get("x-ingress-path", ""),
        "x_hass_source": request.headers.get("x-hass-source", ""),
        "x_hass_is_admin": request.headers.get("x-hass-is-admin", ""),
        "headers": headers,
        "candidates": {
            "ingress": sorted(ingress_c),
            "legacy_headers": sorted(header_c),
        },
        "matches": {
            "ingress": ingress_match.id if ingress_match else None,
            "legacy_headers": header_match.id if header_match else None,
        },
        "admin_from_headers": _ha_admin_from_headers(request),
        "tpg_users": [
            {
                "id": u.id,
                "name": u.name,
                "role": u.role,
                "ha_user_id": u.ha_user_id,
                "ha_username": u.ha_username,
                "aliases": u.aliases,
            }
            for u in users
        ],
    }


async def _build_ui_session(
    request: Request,
    ha_access_token: str = "",
    ha_client_user: dict[str, Any] | None = None,
):
    cfg = get_config()
    users = cfg.assistants.users
    verified_ha_user = await _verified_ha_current_user(ha_access_token)

    # Identity sources, ordered from most to least trustworthy. The HA Supervisor
    # injects X-Remote-User-* headers on every ingress request for the *active*
    # logged-in user; these are server-side and cannot be spoofed by stale
    # browser storage, so they are authoritative. The browser-supplied
    # ha_client_user (live parent hass.user) is next, then a verified access
    # token, then legacy proxy headers.
    ingress_candidates = _ingress_user_candidates(request)
    client_candidates = _ha_user_candidates_from_verified_user(ha_client_user)
    verified_candidates = _ha_user_candidates_from_verified_user(verified_ha_user)
    header_candidates = _user_header_candidates(request)
    candidate_sources: list[tuple[str, set[str]]] = [
        ("ha_ingress", ingress_candidates),
        ("ha_parent", client_candidates),
        ("ha_token", verified_candidates),
        ("ha_headers", header_candidates),
    ]
    all_candidates: set[str] = set()
    for _, cands in candidate_sources:
        all_candidates |= cands

    detected: User | None = None
    identity_source = "safe_fallback"
    for source_name, cands in candidate_sources:
        if not cands:
            continue
        match = _detect_user_from_candidates(cands, users)
        if match is not None:
            detected = match
            identity_source = source_name
            break

    ha_admin = _ha_admin_from_headers(request) or None
    if ha_admin is None and client_candidates:
        ha_admin = _ha_admin_from_verified_user(ha_client_user)
    if ha_admin is None:
        ha_admin = _ha_admin_from_verified_user(verified_ha_user)
    unknown_user = None
    if not detected and all_candidates:
        for _, cands in candidate_sources:
            if cands:
                unknown_user = sorted(cands)[0]
                break
        if unknown_user:
            memory_store.propose_user_setup_suggestion(unknown_user)
    active = detected or _safe_default_ui_user(users)
    identity_trusted = detected is not None
    effective_role = "admin" if (identity_trusted and ha_admin) else (active.role if active else "guest")
    active_payload = active.model_dump() if active else None
    if active_payload:
        active_payload["role"] = effective_role
    default_assistant = _default_assistant_for_user(active, cfg.assistants.assistants)
    return {
        "detected_user": active_payload,
        "role": effective_role,
        "default_assistant": default_assistant.model_dump() if default_assistant else None,
        "ha_user_candidates": sorted(all_candidates),
        "ha_admin": ha_admin,
        "identity_trusted": identity_trusted,
        "identity_source": identity_source,
        "identity_warning": "" if identity_trusted else (
            "Home Assistant did not pass a trusted logged-in user identity; "
            "TPG HomeAI is using the safest shared profile instead of owner access."
        ),
        "unknown_ha_user": unknown_user,
        "users": [
            {
                "id": user.id,
                "name": user.name,
                "role": user.role,
                "aliases": user.aliases,
                "ha_user_id": user.ha_user_id,
                "ha_username": user.ha_username,
                "ha_is_admin": user.ha_is_admin,
                "access_source": user.access_source,
            }
            for user in users
        ],
        "assistants": [
            {
                "id": assistant.id,
                "name": assistant.name,
                "owner": assistant.owner,
                "aliases": assistant.aliases,
            }
            for assistant in cfg.assistants.assistants
        ],
        "roles": {
            "admin": "Owner access: full setup, configuration, diagnostics, and Jarvis operation.",
            "manager": "House setup and Jarvis operation without low-level diagnostics.",
            "resident": "Jarvis operation: chat, notebook, dashboard, brain.",
            "kiosk": "Shared wall panel or house remote: dashboard and chat only.",
            "guest": "Limited chat-only access.",
        },
    }


@app.post("/ha/users/sync")
async def sync_home_assistant_users():
    try:
        auth_users = await HomeAssistantWebSocket().fetch_auth_users()
        result = sync_ha_users(auth_users)
    except Exception as exc:  # noqa: BLE001 - surface HA/token limitations
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    cfg = reload_config()
    return {
        "synced": True,
        **result,
        "counts": {
            "users": len(cfg.assistants.users),
            "assistants": len(cfg.assistants.assistants),
        },
    }


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
        # Use the room's assistant/user when the request came from a voice source.
        src_assistant, src_user = intent_router.source_identity_override(
            get_config(), _command_context(req)
        )
        general = await answer_general(
            src_assistant or req.assistant,
            req.user or src_user,
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


@app.get("/knowledge/reliability")
async def reliability_summary(limit: int = 100):
    return build_reliability_summary(limit=limit)


@app.get("/knowledge/device-adapters")
async def device_adapters(include_registries: bool = True):
    graph = await build_house_graph(include_registries=include_registries)
    return build_device_adapters(graph)


@app.get("/knowledge/voice-sources")
async def voice_sources():
    cfg = get_config()
    return list_voice_source_readiness(cfg)


# --------------------------------------------------------------- house assets
@app.get("/house/assets")
async def house_assets(status: str | None = None):
    return {"assets": house_assets_store.list_assets(status=status)}


@app.post("/house/assets")
async def house_asset_upload(
    file: UploadFile = File(...),
    title: str = Form(""),
    asset_type: str = Form("floorplan"),
    room: str = Form(""),
    uploaded_by: str = Form(""),
    description: str = Form(""),
):
    try:
        data = await file.read()
        asset = house_assets_store.upload_asset(
            data=data,
            original_filename=file.filename or "house-asset",
            content_type=file.content_type or "application/octet-stream",
            title=title,
            asset_type=asset_type,
            room=room,
            uploaded_by=uploaded_by,
            description=description,
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))
    return {"asset": asset}


@app.get("/house/assets/{asset_id}")
async def house_asset_detail(asset_id: int):
    asset = house_assets_store.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="House asset not found.")
    return {"asset": asset}


@app.get("/house/assets/{asset_id}/file")
async def house_asset_file(asset_id: int):
    asset = house_assets_store.get_asset(asset_id)
    path = house_assets_store.asset_file_path(asset_id)
    if not asset or not path:
        raise HTTPException(status_code=404, detail="House asset file not found.")
    return FileResponse(
        path,
        media_type=asset.get("content_type") or "application/octet-stream",
        filename=asset.get("original_filename") or path.name,
    )


@app.post("/house/assets/{asset_id}/approve")
async def house_asset_approve(asset_id: int):
    try:
        return {"asset": house_assets_store.approve_asset(asset_id)}
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err))


@app.post("/house/assets/{asset_id}/ignore")
async def house_asset_ignore(asset_id: int):
    try:
        return {"asset": house_assets_store.ignore_asset(asset_id)}
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err))


@app.get("/house/spatial-brain")
async def house_spatial_brain():
    return house_assets_store.build_spatial_brain()


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


@app.get("/brain/phase-66-71")
async def brain_phase_66_71():
    return await build_jarvis_phase_66_71(get_config())


@app.get("/media/music-assistant")
async def media_music_assistant():
    return await build_music_assistant_brain(get_config())


@app.get("/media/control")
async def media_control():
    return await build_media_control_brain(get_config())


@app.get("/security/briefing")
async def security_briefing():
    return await build_camera_security_brain(get_config())


@app.get("/rooms/occupancy")
async def room_occupancy():
    return await build_room_occupancy_brain(get_config())


@app.get("/brain/phase-72-76")
async def brain_phase_72_76():
    return await build_jarvis_phase_72_76(get_config())


@app.get("/awareness/environment")
async def awareness_environment():
    return await build_environment_brain(get_config())


@app.get("/awareness/calendar-todo")
async def awareness_calendar_todo():
    return await build_calendar_todo_brain(get_config())


@app.get("/awareness/presence-zones")
async def awareness_presence_zones():
    return await build_presence_zone_brain(get_config())


@app.get("/awareness/maintenance")
async def awareness_maintenance():
    return await build_maintenance_brain(get_config())


@app.get("/briefings/daily")
async def briefings_daily():
    return await build_daily_briefing(get_config())


@app.get("/brain/phase-77-81")
async def brain_phase_77_81():
    return await build_jarvis_phase_77_81(get_config())


@app.get("/routines/security")
async def routines_security():
    return await build_security_routine_brain(get_config())


@app.get("/routines/comfort-energy")
async def routines_comfort_energy():
    return await build_comfort_energy_brain(get_config())


@app.get("/routines/media-scenes")
async def routines_media_scenes():
    return await build_media_scene_brain(get_config())


@app.get("/routines/sleep-wake")
async def routines_sleep_wake():
    return await build_sleep_wake_brain(get_config())


@app.get("/routines/proactive-plan")
async def routines_proactive_plan():
    return await build_proactive_action_plan(get_config())


@app.get("/brain/phase-82-86")
async def brain_phase_82_86():
    return await build_jarvis_phase_82_86(get_config(), APP_VERSION)


@app.get("/ops/capability-gaps")
async def ops_capability_gaps():
    return await build_capability_gap_scanner(get_config())


@app.get("/ops/onboarding")
async def ops_onboarding():
    return await build_onboarding_wizard_plan(get_config())


@app.get("/ops/diagnostics")
async def ops_diagnostics():
    return await build_diagnostics_support_pack(get_config(), APP_VERSION)


@app.get("/ops/backup-readiness")
async def ops_backup_readiness():
    return await build_backup_recovery_readiness(get_config())


@app.get("/ops/integration-matrix")
async def ops_integration_matrix():
    return await build_integration_readiness_matrix(get_config())


@app.get("/ops/setup-action-plan")
async def ops_setup_action_plan():
    return await build_setup_action_plan(get_config(), APP_VERSION)


@app.get("/ops/setup-support-packet")
async def ops_setup_support_packet():
    return await build_setup_support_packet(get_config(), APP_VERSION)


@app.get("/ops/sidebar-access")
async def ops_sidebar_access():
    return build_sidebar_access_diagnostics(get_config())


@app.get("/ops/role-dashboard")
async def ops_role_dashboard(role: str = "guest", user: str = ""):
    return await build_role_dashboard_summary(get_config(), role, user)


@app.get("/ops/role-action-policy")
async def ops_role_action_policy(role: str = "guest"):
    return build_role_action_policy(role)


@app.get("/ops/role-suggested-prompts")
async def ops_role_suggested_prompts(role: str = "guest"):
    return build_role_suggested_prompts(role)


@app.get("/ops/role-prompt-insights")
async def ops_role_prompt_insights(role: str = "guest"):
    return build_role_prompt_insights(role)


@app.get("/ops/chat-followups")
async def ops_chat_followups(role: str = "guest", user: str = "", assistant: str = ""):
    return build_chat_followups(role, user=user, assistant=assistant)


@app.get("/ops/chat-followups/preferences")
async def ops_chat_followup_preferences(user: str = "", assistant: str = ""):
    return list_chat_followup_preferences(user=user, assistant=assistant)


@app.post("/ops/chat-followups/preferences")
async def ops_save_chat_followup_preference(payload: FollowupPreferenceRequest):
    return save_chat_followup_preference(
        user=payload.user,
        assistant=payload.assistant,
        followup_id=payload.followup_id,
        text=payload.text,
        state=payload.state,
        source_intent=payload.source_intent,
    )


@app.get("/brain/phase-87-91")
async def brain_phase_87_91():
    return await build_jarvis_phase_87_91(get_config())


@app.get("/governance/privacy")
async def governance_privacy():
    return build_privacy_data_controls(get_config())


@app.get("/governance/roles")
async def governance_roles():
    return build_role_permission_matrix(get_config())


@app.get("/governance/memory-quality")
async def governance_memory_quality():
    return build_memory_quality_report(get_config())


@app.get("/context/export")
async def context_export():
    return await build_redacted_context_export(get_config())


@app.get("/governance/completion-audit")
async def governance_completion_audit():
    return await build_completion_auditor(get_config())


@app.get("/brain/phase-92-96")
async def brain_phase_92_96():
    return await build_jarvis_phase_92_96(get_config(), APP_VERSION)


@app.get("/brain/phase-97")
async def brain_phase_97():
    return await build_jarvis_phase_97(get_config(), APP_VERSION)


@app.get("/brain/phase-101")
async def brain_phase_101():
    return await build_jarvis_phase_101(get_config(), APP_VERSION)


@app.get("/brain/phase-103")
async def brain_phase_103():
    return await build_jarvis_phase_103(get_config(), APP_VERSION)


@app.get("/brain/phase-104")
async def brain_phase_104():
    return await build_jarvis_phase_104(APP_VERSION)


@app.get("/brain/phase-105")
async def brain_phase_105():
    return await build_jarvis_phase_105(APP_VERSION)


@app.get("/brain/phase-106")
async def brain_phase_106():
    return await build_jarvis_phase_106(get_config(), APP_VERSION)


@app.get("/brain/phase-107")
async def brain_phase_107():
    return await build_jarvis_phase_107(APP_VERSION)


@app.get("/brain/phase-108")
async def brain_phase_108():
    return await build_jarvis_phase_108(APP_VERSION)


@app.get("/brain/phase-109")
async def brain_phase_109():
    return await build_jarvis_phase_109(get_config(), APP_VERSION)


@app.get("/brain/phase-110")
async def brain_phase_110():
    return await build_jarvis_phase_110(get_config(), APP_VERSION)


@app.get("/brain/phase-111")
async def brain_phase_111():
    return await build_jarvis_phase_111(get_config(), APP_VERSION)


@app.get("/brain/phase-112")
async def brain_phase_112():
    return await build_jarvis_phase_112(APP_VERSION)


@app.get("/brain/phase-113")
async def brain_phase_113():
    return await build_jarvis_phase_113(APP_VERSION)


@app.get("/brain/phase-114")
async def brain_phase_114():
    return await build_jarvis_phase_114(APP_VERSION)


@app.get("/brain/phase-115")
async def brain_phase_115():
    return await build_jarvis_phase_115(APP_VERSION)


@app.get("/brain/phase-116")
async def brain_phase_116():
    return await build_jarvis_phase_116(APP_VERSION)


@app.get("/brain/phase-117")
async def brain_phase_117():
    return await build_jarvis_phase_117(APP_VERSION)


@app.get("/brain/phase-118")
async def brain_phase_118():
    return await build_jarvis_phase_118(APP_VERSION)


@app.get("/brain/phase-119")
async def brain_phase_119():
    return await build_jarvis_phase_119(APP_VERSION)


@app.get("/brain/phase-120")
async def brain_phase_120():
    return await build_jarvis_phase_120(APP_VERSION)


@app.get("/brain/phase-121")
async def brain_phase_121():
    return await build_jarvis_phase_121(APP_VERSION)


@app.get("/brain/phase-122")
async def brain_phase_122():
    return await build_jarvis_phase_122(APP_VERSION)


@app.get("/brain/phase-123")
async def brain_phase_123():
    return await build_jarvis_phase_123(APP_VERSION)


@app.get("/brain/phase-124")
async def brain_phase_124():
    return await build_jarvis_phase_124(APP_VERSION)


@app.get("/brain/phase-125")
async def brain_phase_125():
    return await build_jarvis_phase_125(APP_VERSION)


@app.get("/brain/phase-126")
async def brain_phase_126():
    return await build_jarvis_phase_126(APP_VERSION)


@app.get("/brain/phase-127")
async def brain_phase_127():
    return await build_jarvis_phase_127(APP_VERSION)


@app.get("/brain/phase-128")
async def brain_phase_128():
    return await build_jarvis_phase_128(APP_VERSION)


@app.get("/experience/interaction-quality")
async def experience_interaction_quality():
    return build_interaction_quality_report(get_config())


@app.get("/experience/voice-acceptance")
async def experience_voice_acceptance():
    return build_voice_acceptance_plan(get_config())


@app.get("/experience/device-acceptance")
async def experience_device_acceptance():
    return await build_device_acceptance_matrix(get_config())


@app.get("/experience/role-acceptance")
async def experience_role_acceptance():
    return build_role_acceptance_matrix(get_config())


@app.get("/experience/acceptance-repairs")
async def experience_acceptance_repairs():
    return build_acceptance_repair_queue()


@app.get("/experience/acceptance-resolutions")
async def experience_acceptance_resolutions():
    return build_acceptance_resolution_summary()


@app.get("/experience/live-acceptance")
async def experience_live_acceptance():
    return await build_live_acceptance_runner(get_config())


@app.get("/experience/live-acceptance/report")
async def experience_live_acceptance_report():
    return await build_live_acceptance_report(get_config(), APP_VERSION)


@app.get("/experience/live-acceptance/results")
async def experience_live_acceptance_results(limit: int = 100):
    return list_live_acceptance_results(limit=limit)


@app.post("/experience/live-acceptance/results")
async def experience_record_live_acceptance_result(payload: AcceptanceResultRequest):
    return record_live_acceptance_result(payload, APP_VERSION)


@app.get("/release/checklist")
async def release_checklist():
    return await build_release_checklist(get_config(), APP_VERSION)


@app.get("/release/runbook")
async def release_runbook():
    return await build_operational_runbook(get_config(), APP_VERSION)


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


@app.get("/voice/runtime")
async def voice_runtime():
    return build_voice_runtime(get_config())


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


@app.post("/voice/transcribe")
async def voice_transcribe(file: UploadFile = File(...)):
    audio_bytes = await file.read()
    return await transcribe_audio(
        file.filename or "voice-input.webm",
        file.content_type or "application/octet-stream",
        audio_bytes,
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
async def memory_list(status: str | None = None, owner: str | None = None):
    return {"memories": memory_store.list_memories(status=status, owner=owner)}


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


# --------------------------------------------------------------- notebook
@app.get("/conversations")
async def conversations(limit: int = 50, assistant: str | None = None, user: str | None = None):
    return {"conversations": notebook_store.list_conversations(
        limit=limit, assistant=assistant, user=user,
    )}


@app.get("/conversations/{conversation_id}")
async def conversation_detail(conversation_id: str):
    return notebook_store.conversation_detail(conversation_id)


@app.delete("/conversations/{conversation_id}")
async def conversation_archive(conversation_id: str):
    try:
        archived = notebook_store.archive_conversation(conversation_id)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))
    return {
        "archived": True,
        "conversation_id": archived["conversation_id"],
        "already_archived": archived["already_archived"],
    }


@app.post("/conversations/{conversation_id}/notes")
async def conversation_note(conversation_id: str, req: ConversationNoteRequest):
    if req.conversation_id and req.conversation_id != conversation_id:
        raise HTTPException(status_code=400, detail="Conversation ID mismatch.")
    if not req.body.strip():
        raise HTTPException(status_code=400, detail="Note body is required.")
    return {"note": notebook_store.add_note(
        conversation_id,
        assistant=req.assistant or "",
        user=req.user or "",
        title=req.title,
        body=req.body,
        source=req.source,
    )}


@app.get("/conversations/{conversation_id}/export")
async def conversation_export(conversation_id: str):
    return {
        "conversation_id": conversation_id,
        "filename": f"tpg-homeai-{conversation_id}.md",
        "markdown": notebook_store.export_markdown(conversation_id),
    }


# --------------------------------------------------------------- research
@app.post("/research/search")
async def research_search(req: ResearchSearchRequest):
    return await research_store.search_web(req.query, req.max_results)


# ------------------------------------------------------------ dashboards
@app.post("/dashboards/draft")
async def dashboard_draft(req: DashboardDraftRequest):
    cfg = get_config()
    return build_dashboard_draft(
        cfg,
        title=req.title,
        style=req.style,
        template=req.template,
        intent=req.intent,
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
    template: str = "auto",
    intent: str | None = None,
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
        template=template,
        intent=intent,
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
        template=req.template,
        intent=req.intent,
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
    summary = _automation_draft_summary(draft.proposed_yaml)
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
        "summary": summary,
    }


def _automation_draft_summary(proposed_yaml: str) -> dict[str, Any]:
    try:
        parsed = yaml.safe_load(proposed_yaml or "") or {}
    except Exception as exc:  # noqa: BLE001 - draft may be manually edited
        return {
            "valid_yaml": False,
            "warnings": [f"YAML parse failed: {exc}"],
            "ready_to_install": False,
        }
    triggers = parsed.get("trigger") or []
    conditions = parsed.get("condition") or []
    actions = parsed.get("action") or []
    if isinstance(triggers, dict):
        triggers = [triggers]
    if isinstance(conditions, dict):
        conditions = [conditions]
    if isinstance(actions, dict):
        actions = [actions]
    blob = proposed_yaml or ""
    warnings = []
    if "<<<" in blob:
        warnings.append("Contains placeholders that need mapping before install.")
    if not triggers:
        warnings.append("No trigger configured.")
    if not actions:
        warnings.append("No actions configured.")
    return {
        "valid_yaml": True,
        "alias": parsed.get("alias", ""),
        "trigger_count": len(triggers),
        "condition_count": len(conditions),
        "action_count": len(actions),
        "trigger_labels": [_automation_trigger_label(t) for t in triggers[:4]],
        "action_labels": [_automation_action_label(a) for a in actions[:8]],
        "warnings": warnings,
        "ready_to_install": not warnings,
    }


def _automation_trigger_label(trigger: dict[str, Any]) -> str:
    platform = trigger.get("platform", "trigger")
    if platform == "time":
        return f"At {trigger.get('at')}"
    if platform == "sun":
        return f"At {trigger.get('event')}"
    if platform == "time_pattern":
        if trigger.get("minutes"):
            return f"Every {str(trigger.get('minutes')).lstrip('/')} minute(s)"
        if trigger.get("hours"):
            return f"Every {str(trigger.get('hours')).lstrip('/')} hour(s)"
    if platform == "calendar":
        return f"When {trigger.get('entity_id')} event {trigger.get('event')}"
    if platform == "state":
        return f"When {trigger.get('entity_id')} becomes {trigger.get('to')}"
    if platform == "numeric_state":
        if "below" in trigger:
            return f"When {trigger.get('entity_id')} is below {trigger.get('below')}"
        if "above" in trigger:
            return f"When {trigger.get('entity_id')} is above {trigger.get('above')}"
    return str(platform)


def _automation_action_label(action: dict[str, Any]) -> str:
    if "delay" in action:
        return f"Wait {action['delay']}"
    service = action.get("service", "service")
    target = (action.get("target") or {}).get("entity_id", "")
    if isinstance(target, list):
        target = f"{len(target)} entities"
    return f"{service} -> {target or 'target'}"


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


async def _verified_ha_current_user(ha_access_token: str = "") -> dict | None:
    token = str(ha_access_token or "").strip()
    if not token:
        return None
    try:
        user = await HomeAssistantWebSocket(token=token).fetch_current_user()
    except Exception as exc:  # noqa: BLE001 - browser can fall back safely
        logger.warning("Could not verify Home Assistant current user token: %s", type(exc).__name__)
        return None
    return user if isinstance(user, dict) else None


def _detect_user_from_candidates(candidates: set[str], users: list[User]) -> User | None:
    if not candidates:
        return None
    normalized_candidates = {_normalize_identity(candidate) for candidate in candidates}
    for user in users:
        names = _user_identity_values(user)
        if candidates & names or normalized_candidates & names:
            return user
    return None


def _ingress_user_candidates(request: Request) -> set[str]:
    """Identity injected by the HA Supervisor ingress proxy.

    On every ingress request, the Supervisor adds X-Remote-User-Id,
    X-Remote-User-Name and X-Remote-User-Display-Name for the active logged-in
    HA user (see supervisor/api/ingress.py). HA core also adds X-Hass-User-ID
    on some paths. These are server-side, per-request, and cannot be forged by
    stale browser storage, so they are the authoritative identity source.
    """
    header_names = (
        "x-remote-user-id",
        "x-remote-user-name",
        "x-remote-user-display-name",
        "x-hass-user-id",
    )
    values = [request.headers.get(name, "") for name in header_names]
    return {v.strip().lower() for v in values if v and v.strip()}


def _user_header_candidates(request: Request) -> set[str]:
    header_names = (
        "x-ha-user",
        "x-ha-user-name",
        "x-ha-user-id",
        "x-hass-user",
        "x-hass-user-id",
        "x-home-assistant-user",
        "x-home-assistant-user-id",
        "x-tpg-ha-user",
        "x-tpg-ha-user-name",
        "x-tpg-ha-user-id",
    )
    values = [request.headers.get(name, "") for name in header_names]
    return {v.strip().lower() for v in values if v and v.strip()}


def _ha_user_candidates_from_verified_user(user: dict | None) -> set[str]:
    if not user:
        return set()
    values = [
        user.get("id"),
        user.get("name"),
        user.get("username"),
        user.get("display_name"),
    ]
    credentials = user.get("credentials")
    if isinstance(credentials, list):
        for credential in credentials:
            if isinstance(credential, dict):
                values.append(credential.get("auth_provider_id"))
                values.append(credential.get("auth_provider_type"))
    return {str(value).strip().lower() for value in values if value and str(value).strip()}


def _ha_admin_from_headers(request: Request) -> bool:
    """Honor HA/proxy admin signals when available.

    Standard HA ingress may not expose this today, but custom panels/proxies can.
    When present, HA is the source of truth for UI access level.
    """
    header_names = (
        "x-ha-user-is-admin",
        "x-ha-is-admin",
        "x-hass-user-is-admin",
        "x-hass-is-admin",
        "x-home-assistant-user-is-admin",
        "x-tpg-ha-user-is-admin",
    )
    truthy = {"1", "true", "yes", "on", "admin", "administrator"}
    return any(
        str(request.headers.get(name, "")).strip().lower() in truthy
        for name in header_names
    )


def _ha_admin_from_verified_user(user: dict | None) -> bool | None:
    if not user:
        return None
    truthy = {True, "1", "true", "yes", "on", "admin", "administrator"}
    values = [
        user.get("is_admin"),
        user.get("is_owner"),
        user.get("local_only") is False and user.get("group") == "system-admin",
    ]
    return any(str(value).strip().lower() in truthy or value is True for value in values)


def _user_identity_values(user: User) -> set[str]:
    values = {user.id, user.name, user.ha_user_id, user.ha_username, *user.aliases}
    result: set[str] = set()
    for value in values:
        raw = str(value or "").strip().lower()
        if raw:
            result.add(raw)
            result.add(_normalize_identity(raw))
    return result


def _normalize_identity(value: str) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _default_assistant_for_user(user: User | None, assistants: list[Assistant]) -> Assistant | None:
    if user is None:
        return assistants[0] if assistants else None
    for assistant in assistants:
        if assistant.owner == user.id:
            return assistant
    return assistants[0] if assistants else None


def _safe_default_ui_user(users: list[User]) -> User | None:
    """Choose a non-privileged profile when HA has not identified the session.

    Missing HA identity must never silently become owner/admin. Shared panels
    and cross-origin iframes should land on the house/kiosk profile until a
    trusted HA header or bridge identifies the real logged-in user.
    """
    for role in ("kiosk", "guest", "resident", "manager", "admin"):
        for user in users:
            if user.role == role:
                return user
    return users[0] if users else None


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
