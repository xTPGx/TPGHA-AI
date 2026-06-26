"""Offline acceptance tests for add-on startup, API routing, and bootstrap.

Run from the backend/ directory:

    python verify_addon.py

These tests use FastAPI's TestClient and a throwaway temp CONFIG_DIR/DB. They
never require a live Home Assistant or OpenAI key — the whole point is that the
backend self-initializes and degrades gracefully (PART 11).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

# ---- Environment MUST be set before importing the app (settings/db cache it).
_TMP = tempfile.mkdtemp(prefix="tpg_addon_test_")
_CFG = os.path.join(_TMP, "cfg")
_HA_CFG = os.path.join(_TMP, "ha")
_STATIC = os.path.join(_TMP, "static")
os.makedirs(os.path.join(_STATIC, "assets"), exist_ok=True)
os.makedirs(_HA_CFG, exist_ok=True)
with open(os.path.join(_STATIC, "index.html"), "w", encoding="utf-8") as fh:
    fh.write("<!doctype html><html><body><div id='root'></div></body></html>")
with open(os.path.join(_STATIC, "assets", "app.js"), "w", encoding="utf-8") as fh:
    fh.write("console.log('tpg');")

os.environ["CONFIG_DIR"] = _CFG
os.environ["HA_CONFIG_DIR"] = _HA_CFG
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP, 'test.db')}"
os.environ["STATIC_DIR"] = _STATIC
os.environ["HOME_ASSISTANT_URL"] = ""       # not configured -> degraded
os.environ["HOME_ASSISTANT_TOKEN"] = ""
os.environ["OPENAI_API_KEY"] = ""           # fallback parser
os.environ["SCAN_ON_START"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app import bootstrap as bootstrap_mod  # noqa: E402
from app import __version__ as backend_package_version  # noqa: E402
from app.db.database import get_session, init_db  # noqa: E402
from app.db.models import MemoryItem, Suggestion  # noqa: E402
from app.main import APP_VERSION, app  # noqa: E402

_PASS = 0
_FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  PASS  {name}")
    else:
        _FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def is_json(resp) -> bool:
    return "application/json" in (resp.headers.get("content-type") or "")


def is_html(resp) -> bool:
    return "text/html" in (resp.headers.get("content-type") or "")


def is_js(resp) -> bool:
    ctype = resp.headers.get("content-type") or ""
    return "javascript" in ctype or "application/octet-stream" in ctype


def main() -> int:
    init_db()
    # Run bootstrap deterministically (instead of the background lifespan task).
    asyncio.run(bootstrap_mod.bootstrap())
    state = bootstrap_mod.get_app_state()

    # TestClient WITHOUT a context manager => no lifespan, no double bootstrap.
    client = TestClient(app)

    print("PART 0 — add-on update metadata is internally consistent")
    repo_root = Path(__file__).resolve().parents[1]
    addon_config = (repo_root / "tpg_homeai" / "config.yaml").read_text(encoding="utf-8")
    dockerfile = (repo_root / "tpg_homeai" / "Dockerfile").read_text(encoding="utf-8")
    run_sh = (repo_root / "tpg_homeai" / "run.sh").read_text(encoding="utf-8")
    manifest = (repo_root / "custom_components" / "tpg_homeai" / "manifest.json").read_text(encoding="utf-8")
    ha_client = (repo_root / "custom_components" / "tpg_homeai" / "__init__.py").read_text(encoding="utf-8")
    ha_panel = (repo_root / "custom_components" / "tpg_homeai" / "panel.js").read_text(encoding="utf-8")
    ha_conversation = (repo_root / "custom_components" / "tpg_homeai" / "conversation.py").read_text(encoding="utf-8")
    chat_frontend = (repo_root / "frontend" / "src" / "pages" / "Chat.tsx").read_text(encoding="utf-8")
    ha_auth = (repo_root / "frontend" / "src" / "haAuth.ts").read_text(encoding="utf-8")
    setup_frontend = (repo_root / "frontend" / "src" / "pages" / "Setup.tsx").read_text(encoding="utf-8")
    dashboard_builder_frontend = (repo_root / "frontend" / "src" / "pages" / "DashboardBuilder.tsx").read_text(encoding="utf-8")
    suggestions_frontend = (repo_root / "frontend" / "src" / "pages" / "Suggestions.tsx").read_text(encoding="utf-8")
    device_profiles_frontend = (repo_root / "frontend" / "src" / "pages" / "DeviceProfiles.tsx").read_text(encoding="utf-8")
    api_frontend = (repo_root / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
    backend_main = (repo_root / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    control_actions = (repo_root / "backend" / "app" / "actions" / "control.py").read_text(encoding="utf-8")
    climate_actions = (repo_root / "backend" / "app" / "actions" / "climate.py").read_text(encoding="utf-8")
    device_adapters = (repo_root / "backend" / "app" / "device_adapters.py").read_text(encoding="utf-8")
    outcomes_source = (repo_root / "backend" / "app" / "outcomes.py").read_text(encoding="utf-8")
    media_brain = (repo_root / "backend" / "app" / "media_brain.py").read_text(encoding="utf-8")
    situational_brain = (repo_root / "backend" / "app" / "situational_brain.py").read_text(encoding="utf-8")
    routine_brain = (repo_root / "backend" / "app" / "routine_brain.py").read_text(encoding="utf-8")
    operations_brain = (repo_root / "backend" / "app" / "operations_brain.py").read_text(encoding="utf-8")
    governance_brain = (repo_root / "backend" / "app" / "governance_brain.py").read_text(encoding="utf-8")
    experience_brain = (repo_root / "backend" / "app" / "experience_brain.py").read_text(encoding="utf-8")
    house_state_source = (repo_root / "backend" / "app" / "house_state.py").read_text(encoding="utf-8")
    security_action = (repo_root / "backend" / "app" / "actions" / "security.py").read_text(encoding="utf-8")
    cfg_version = re.search(r'^version:\s*"([^"]+)"', addon_config, re.M)
    docker_version = re.search(r'io\.hass\.version="([^"]+)"', dockerfile)
    manifest_version = re.search(r'"version":\s*"([^"]+)"', manifest)
    versions = {
        "config.yaml": cfg_version.group(1) if cfg_version else None,
        "Dockerfile": docker_version.group(1) if docker_version else None,
        "manifest.json": manifest_version.group(1) if manifest_version else None,
        "APP_VERSION": APP_VERSION,
        "package": backend_package_version,
    }
    check("version metadata present", all(versions.values()), str(versions))
    check("version metadata aligned", len(set(versions.values())) == 1, str(versions))
    check("add-on changelog exists", (repo_root / "tpg_homeai" / "CHANGELOG.md").is_file())
    check("add-on ingress owns the sidebar natively for all users",
          "ingress: true" in addon_config
          and "panel_title:" in addon_config
          and "panel_icon:" in addon_config
          and "panel_admin: false" in addon_config,
          "The add-on must expose a native ingress sidebar panel (visible to "
          "non-admins) so the Supervisor injects X-Remote-User-* for the active "
          "HA user on every request.")
    check("custom integration does not register a competing wrapper panel",
          "_remove_sidebar_panel(hass)" in ha_client
          and 'component_name="tpg-homeai-panel"' not in ha_client
          and "frontend.add_extra_js_url(hass, PANEL_MODULE_URL)" not in ha_client,
          "The stale-session custom-element wrapper must be retired; the native "
          "Supervisor ingress panel owns the sidebar.")
    check("backend resolves identity from Supervisor ingress headers",
          "x-remote-user-id" in backend_main
          and "x-remote-user-name" in backend_main
          and "x-remote-user-display-name" in backend_main
          and "_ingress_user_candidates" in backend_main,
          "The backend must trust X-Remote-User-* ingress headers as the "
          "authoritative active-user identity.")
    check("add-on ships custom integration files",
          "custom_components_template/tpg_homeai" in dockerfile,
          "The add-on image must include the matching custom integration.")
    check("add-on installs custom integration into HA config",
          "/config/custom_components/tpg_homeai" in run_sh
          and "custom_components_template/tpg_homeai" in run_sh,
          "The add-on must sync the custom integration so non-admin HA panels exist.")
    check("HA client exposes chat endpoint", "async def async_chat" in ha_client and '"/chat"' in ha_client)
    check("HA Assist uses chat brain, not command-only path",
          "async_chat(" in ha_conversation and "async_command(" not in ha_conversation,
          "Assist must use /chat for general conversation + guarded actions")
    check("Chat mic uses recorder upload, not Web Speech only",
          "MediaRecorder" in chat_frontend
          and "voiceTranscribe" in chat_frontend
          and "/voice/transcribe" in api_frontend,
          "Mobile mic must record audio and upload it for OpenAI transcription.")
    check("Chat mic gives actionable permission diagnostics",
          "Diagnose mic" in chat_frontend
          and "microphoneReadinessReport" in chat_frontend
          and "Localhost only works on the device running the browser" in chat_frontend,
          "Voice failures should explain HTTP/HTTPS, app permission, and localhost behavior.")
    check("Chat voice session has runtime status and cancel",
          "VoiceSessionBar" in chat_frontend
          and "recordingSeconds" in chat_frontend
          and "cancelVoiceInput" in chat_frontend
          and "discardRecordingRef" in chat_frontend,
          "Mic input should expose listening/transcribing state and a true cancel path.")
    check("frontend no longer sends stale cached HA identity",
          "clientUser: freshUser || {}" in ha_auth
          and "cachedStorageUserIgnored" in ha_auth,
          "sessionStorage can belong to a previous HA login and must not identify the active user.")
    check("custom HA panel refreshes iframe when HA user changes",
          "_maybeRefreshForUser" in ha_panel
          and "_startIdentityHeartbeat" in ha_panel
          and "_userSignature" in ha_panel,
          "The sidebar panel must repost/reload the active HA user instead of sticking to a previous iframe session.")
    check("Setup shows voice runtime and local mic readiness",
          "voiceRuntime" in setup_frontend
          and "This browser/app mic" in setup_frontend
          and "localVoiceEnvironment" in setup_frontend,
          "Setup must expose deployable voice readiness and local browser/app capture status.")
    check("Dashboard Builder has a pre-install preview",
          "DashboardPreview" in dashboard_builder_frontend
          and "Spatial assets" in dashboard_builder_frontend,
          "Dashboard drafts should show views/cards/spatial context before install.")
    check("Dashboard Builder has natural-language architect controls",
          "Describe the dashboard" in dashboard_builder_frontend
          and "Auto template" in dashboard_builder_frontend
          and "Architect summary" in dashboard_builder_frontend,
          "Dashboard Builder should accept a plain-English goal and show template/card summary.")
    check("Suggestions can edit automation drafts",
          "Edit YAML" in suggestions_frontend
          and "api.editDraft" in suggestions_frontend,
          "Automation drafts need owner-editable YAML before install.")
    check("Suggestions shows parsed automation preview",
          "Draft preview" in suggestions_frontend
          and "ready_to_install" in suggestions_frontend,
          "Automation suggestions should show triggers/actions/warnings before approval.")
    check("Suggestions surfaces device strategy learning approvals",
          "Device learning approval" in suggestions_frontend
          and "proposed_memory" in suggestions_frontend,
          "Repair suggestions should make learned device strategy obvious before approval.")
    check("Device Profiles renders learned nested strategies cleanly",
          "formatStrategyValue" in device_profiles_frontend
          and 'typeof value === "object"' in device_profiles_frontend,
          "Learned service strategy objects must not render as [object Object].")
    check("generic media actions honor approved strategy memory",
          "preferred_media_control" in control_actions
          and "approved_memory_value" in control_actions
          and "media_play_wake" in control_actions
          and "media_stop_sleep" in control_actions
          and "service_attempts" in control_actions,
          "TV/media commands must learn and retry safe fallback services.")
    check("repair suggestions are scoped by target device",
          "target_label" in outcomes_source
          and "outcome for {target_label}" in outcomes_source
          and "_repair_target_label" in outcomes_source,
          "One generic repair title must not suppress repairs for other devices.")
    check("cover and climate reliability strategies are wired",
          "preferred_cover_control" in outcomes_source
          and "preferred_climate_control" in outcomes_source
          and "open_cover" in outcomes_source
          and "close_cover" in outcomes_source
          and "set_hvac_mode" in outcomes_source,
          "Reliability brain should verify and learn cover/climate behavior.")
    check("generic controls surface cover/climate learned strategy",
          "preferred_cover_control" in control_actions
          and "preferred_climate_control" in control_actions
          and "_approved_generic_strategy" in control_actions,
          "Generic cover/climate controls should report approved device strategy.")
    check("direct climate action records attempts and learned strategy",
          "preferred_climate_control" in climate_actions
          and "service_attempts" in climate_actions
          and "temperature_only" in climate_actions,
          "Thermostat commands should expose mode/temperature service attempts.")
    check("device adapters include cover and climate hints",
          "cover_state_or_position" in device_adapters
          and "climate_mode_temperature" in device_adapters,
          "Device Profiles should explain cover/climate capabilities and recovery hints.")
    check("vacuum/helper/appliance reliability strategies are wired",
          "preferred_vacuum_control" in outcomes_source
          and "preferred_number_control" in outcomes_source
          and "preferred_select_control" in outcomes_source
          and "preferred_humidifier_control" in outcomes_source
          and "preferred_water_heater_control" in outcomes_source
          and "preferred_valve_control" in outcomes_source,
          "Reliability brain should verify and learn vacuum/helper/appliance behavior.")
    check("generic controls surface vacuum/helper/appliance learned strategy",
          "preferred_vacuum_control" in control_actions
          and "preferred_number_control" in control_actions
          and "preferred_select_control" in control_actions
          and "preferred_humidifier_control" in control_actions
          and "preferred_water_heater_control" in control_actions
          and "preferred_valve_control" in control_actions,
          "Generic controls should report approved device strategy for phases 61-65 domains.")
    check("device adapters include vacuum/helper/appliance hints",
          "vacuum_state_family" in device_adapters
          and "number_range_value" in device_adapters
          and "select_option_state" in device_adapters
          and "humidifier_power_humidity" in device_adapters
          and "water_heater_mode_temperature" in device_adapters
          and "valve_open_close" in device_adapters,
          "Device Profiles should explain phases 61-65 capabilities and recovery hints.")
    check("capability planner supports phases 61-65 services",
          "dock" in (repo_root / "backend" / "app" / "discovery" / "capabilities.py").read_text(encoding="utf-8")
          and "set_humidity" in (repo_root / "backend" / "app" / "discovery" / "capabilities.py").read_text(encoding="utf-8")
          and "set_operation_mode" in (repo_root / "backend" / "app" / "discovery" / "capabilities.py").read_text(encoding="utf-8"),
          "Natural language aliases and service plans should cover vacuums, humidifiers, and water heaters.")
    check("house knowledge assets are first-class API + UI",
          "/house/assets" in backend_main
          and "houseAssets" in api_frontend
          and (repo_root / "frontend" / "src" / "pages" / "HouseKnowledge.tsx").is_file(),
          "Floor plans, blueprints, room photos, and notes need a managed upload/approval layer.")
    check("phases 66-71 media brain module exists",
          "build_music_assistant_brain" in media_brain
          and "build_media_control_brain" in media_brain
          and "build_camera_security_brain" in media_brain
          and "build_room_occupancy_brain" in media_brain,
          "Media, security, and occupancy intelligence must live in a reusable backend module.")
    check("Music Assistant brain tracks accounts and playback services",
          "music_assistant_entity_id" in media_brain
          and "music_assistant.search" in media_brain
          and "music_assistant.play_media" in media_brain
          and "Keep per-user music account privacy boundaries" in media_brain,
          "Music Assistant readiness must include speaker mappings, search/play services, and account boundaries.")
    check("media control brain tracks display state and sleep candidates",
          "sleep_timer_candidate" in media_brain
          and "source_list" in media_brain
          and "app_name" in media_brain
          and "media_title" in media_brain,
          "TV/display brain must expose source/app/title/volume state and sleep-timer candidates.")
    check("camera security brain detects event sensors",
          "doorbell" in media_brain
          and "package" in media_brain
          and "vehicle" in media_brain
          and "briefing" in media_brain,
          "Security briefing must include camera/event keywords and a human-readable briefing.")
    check("room occupancy brain uses room activity signals",
          "occupied_likelihood" in media_brain
          and "voice_sources" in media_brain
          and "motion" in media_brain
          and "active_entities" in media_brain,
          "Occupancy should use activity signals and voice-source room context.")
    check("phases 66-71 endpoints are exposed",
          "/media/music-assistant" in backend_main
          and "/media/control" in backend_main
          and "/security/briefing" in backend_main
          and "/rooms/occupancy" in backend_main
          and "/brain/phase-66-71" in backend_main,
          "Backend must expose phase 66-71 brains as API endpoints.")
    check("house state includes media/security/occupancy brains",
          "media_control" in house_state_source
          and "camera_security" in house_state_source
          and "room_occupancy" in house_state_source,
          "House State should include the new situational intelligence layers.")
    check("security action uses security briefing brain",
          "build_camera_security_brain" in security_action
          and '"briefing": brain' in security_action,
          "Security check responses should include the richer camera/security briefing.")
    check("phases 72-76 situational brain module exists",
          "build_environment_brain" in situational_brain
          and "build_calendar_todo_brain" in situational_brain
          and "build_presence_zone_brain" in situational_brain
          and "build_maintenance_brain" in situational_brain
          and "build_daily_briefing" in situational_brain,
          "Environment, schedule, presence, maintenance, and daily briefing brains must be reusable.")
    check("situational brain tracks real Jarvis daily context",
          "weather" in situational_brain
          and "calendar" in situational_brain
          and "todo" in situational_brain
          and "device_tracker" in situational_brain
          and "low_batteries" in situational_brain
          and "spoken" in situational_brain,
          "Daily awareness must include weather, schedule, presence, maintenance, and spoken summary fields.")
    check("phases 72-76 endpoints are exposed",
          "/awareness/environment" in backend_main
          and "/awareness/calendar-todo" in backend_main
          and "/awareness/presence-zones" in backend_main
          and "/awareness/maintenance" in backend_main
          and "/briefings/daily" in backend_main
          and "/brain/phase-72-76" in backend_main,
          "Backend must expose phase 72-76 brains as API endpoints.")
    check("house state includes daily briefing brain",
          "daily_briefing" in house_state_source,
          "House State should include the daily briefing composer.")
    check("phases 77-81 routine brain module exists",
          "build_security_routine_brain" in routine_brain
          and "build_comfort_energy_brain" in routine_brain
          and "build_media_scene_brain" in routine_brain
          and "build_sleep_wake_brain" in routine_brain
          and "build_proactive_action_plan" in routine_brain,
          "Routine, scene, sleep/wake, and proactive plan brains must be reusable.")
    check("routine brain stays approval-first",
          "approval_required" in routine_brain
          and '"auto_execute": False' in routine_brain
          and "automation_draft" in routine_brain,
          "Routine intelligence must propose and draft, not silently execute.")
    check("phases 77-81 endpoints are exposed",
          "/routines/security" in backend_main
          and "/routines/comfort-energy" in backend_main
          and "/routines/media-scenes" in backend_main
          and "/routines/sleep-wake" in backend_main
          and "/routines/proactive-plan" in backend_main
          and "/brain/phase-77-81" in backend_main,
          "Backend must expose phase 77-81 brains as API endpoints.")
    check("house state includes proactive action plan",
          "proactive_action_plan" in house_state_source,
          "House State should include the approval-first proactive action plan.")
    check("phases 82-86 operations brain module exists",
          "build_capability_gap_scanner" in operations_brain
          and "build_onboarding_wizard_plan" in operations_brain
          and "build_diagnostics_support_pack" in operations_brain
          and "build_backup_recovery_readiness" in operations_brain
          and "build_integration_readiness_matrix" in operations_brain,
          "Capability gaps, onboarding, diagnostics, backup, and integration readiness must be reusable.")
    check("operations brain is read-only and support-safe",
          "safe_for_support" in operations_brain
          and "secrets_redacted" in operations_brain
          and "safe_dict()" in operations_brain
          and "await safe_get_states()" in operations_brain,
          "Operations intelligence must expose safe diagnostics without secrets or mutations.")
    check("phases 82-86 endpoints are exposed",
          "/ops/capability-gaps" in backend_main
          and "/ops/onboarding" in backend_main
          and "/ops/diagnostics" in backend_main
          and "/ops/backup-readiness" in backend_main
          and "/ops/integration-matrix" in backend_main
          and "/brain/phase-82-86" in backend_main,
          "Backend must expose phase 82-86 operations brains as API endpoints.")
    check("Jarvis Brain includes operations readiness layers",
          "capability_gap_scanner" in (repo_root / "backend" / "app" / "brain.py").read_text(encoding="utf-8")
          and "onboarding_wizard" in (repo_root / "backend" / "app" / "brain.py").read_text(encoding="utf-8")
          and "diagnostics_support_pack" in (repo_root / "backend" / "app" / "brain.py").read_text(encoding="utf-8")
          and "backup_recovery_readiness" in (repo_root / "backend" / "app" / "brain.py").read_text(encoding="utf-8")
          and "integration_matrix" in (repo_root / "backend" / "app" / "brain.py").read_text(encoding="utf-8"),
          "Readiness UI must show the operational deployment layers.")
    check("phases 87-91 governance brain module exists",
          "build_privacy_data_controls" in governance_brain
          and "build_role_permission_matrix" in governance_brain
          and "build_memory_quality_report" in governance_brain
          and "build_redacted_context_export" in governance_brain
          and "build_completion_auditor" in governance_brain,
          "Privacy, roles, memory quality, context export, and completion audit must be reusable.")
    check("governance brain keeps exports redacted",
          "safe_for_export" in governance_brain
          and "secrets_redacted" in governance_brain
          and "Secrets redacted" in governance_brain
          and "context_markdown" in governance_brain,
          "Context exports must be explicit about redaction and portability.")
    check("phases 87-91 endpoints are exposed",
          "/governance/privacy" in backend_main
          and "/governance/roles" in backend_main
          and "/governance/memory-quality" in backend_main
          and "/context/export" in backend_main
          and "/governance/completion-audit" in backend_main
          and "/brain/phase-87-91" in backend_main,
          "Backend must expose phase 87-91 governance brains as API endpoints.")
    check("Jarvis Brain includes governance readiness layers",
          "privacy_data_controls" in (repo_root / "backend" / "app" / "brain.py").read_text(encoding="utf-8")
          and "role_permission_matrix" in (repo_root / "backend" / "app" / "brain.py").read_text(encoding="utf-8")
          and "memory_quality_recall" in (repo_root / "backend" / "app" / "brain.py").read_text(encoding="utf-8")
          and "redacted_context_export" in (repo_root / "backend" / "app" / "brain.py").read_text(encoding="utf-8")
          and "completion_auditor" in (repo_root / "backend" / "app" / "brain.py").read_text(encoding="utf-8"),
          "Readiness UI must show privacy, roles, memory, export, and completion audit layers.")
    check("phases 92-96 experience brain module exists",
          "build_interaction_quality_report" in experience_brain
          and "build_voice_acceptance_plan" in experience_brain
          and "build_device_acceptance_matrix" in experience_brain
          and "build_release_checklist" in experience_brain
          and "build_operational_runbook" in experience_brain,
          "Interaction quality, voice acceptance, device acceptance, release checklist, and runbook must be reusable.")
    check("experience brain defines acceptance/runbook discipline",
          "acceptance_tests" in experience_brain
          and "role_acceptance" in experience_brain
          and "feature_freeze" in experience_brain
          and "ship_rule" in experience_brain,
          "Release readiness must include real-house acceptance and feature-freeze guidance.")
    check("phases 92-96 endpoints are exposed",
          "/experience/interaction-quality" in backend_main
          and "/experience/voice-acceptance" in backend_main
          and "/experience/device-acceptance" in backend_main
          and "/release/checklist" in backend_main
          and "/release/runbook" in backend_main
          and "/brain/phase-92-96" in backend_main,
          "Backend must expose phase 92-96 experience/release brains as API endpoints.")
    check("Jarvis Brain includes experience/release readiness layers",
          "interaction_quality_report" in (repo_root / "backend" / "app" / "brain.py").read_text(encoding="utf-8")
          and "voice_acceptance_plan" in (repo_root / "backend" / "app" / "brain.py").read_text(encoding="utf-8")
          and "device_acceptance_matrix" in (repo_root / "backend" / "app" / "brain.py").read_text(encoding="utf-8")
          and "release_checklist" in (repo_root / "backend" / "app" / "brain.py").read_text(encoding="utf-8")
          and "operational_runbook" in (repo_root / "backend" / "app" / "brain.py").read_text(encoding="utf-8"),
          "Readiness UI must show interaction, voice, device, release, and runbook layers.")
    check("phase 97 live acceptance runner exists",
          "build_live_acceptance_runner" in experience_brain
          and "build_jarvis_phase_97" in experience_brain
          and "read_only" in experience_brain
          and "executes_actions" in experience_brain
          and "requires_human_to_run_mutating_tests" in experience_brain,
          "Live acceptance must generate a safe, non-mutating acceptance plan.")
    check("phase 97 endpoints are exposed",
          "/experience/live-acceptance" in backend_main
          and "/brain/phase-97" in backend_main,
          "Backend must expose the live HA acceptance runner.")
    check("Jarvis Brain includes live acceptance readiness layer",
          "live_acceptance_runner" in (repo_root / "backend" / "app" / "brain.py").read_text(encoding="utf-8"),
          "Readiness UI must show the live HA acceptance runner layer.")
    check("phase 98 acceptance evidence journal exists",
          "class AcceptanceRun" in (repo_root / "backend" / "app" / "db" / "models.py").read_text(encoding="utf-8")
          and "AcceptanceResultRequest" in (repo_root / "backend" / "app" / "models" / "schemas.py").read_text(encoding="utf-8")
          and "record_live_acceptance_result" in experience_brain
          and "list_live_acceptance_results" in experience_brain,
          "Live acceptance results must be persisted as evidence.")
    check("phase 98 acceptance evidence endpoints are exposed",
          "/experience/live-acceptance/results" in backend_main
          and "record_live_acceptance_result" in backend_main,
          "Backend must expose acceptance evidence record/list endpoints.")
    check("Jarvis Brain includes acceptance evidence readiness layer",
          "acceptance_evidence_journal" in (repo_root / "backend" / "app" / "brain.py").read_text(encoding="utf-8"),
          "Readiness UI must show whether real-house acceptance evidence exists.")
    check("phase 99 frontend live acceptance panel is wired",
          "liveAcceptance" in api_frontend
          and "recordLiveAcceptanceResult" in api_frontend
          and "LiveAcceptancePanel" in (repo_root / "frontend" / "src" / "pages" / "Brain.tsx").read_text(encoding="utf-8")
          and "Latest evidence" in (repo_root / "frontend" / "src" / "pages" / "Brain.tsx").read_text(encoding="utf-8"),
          "Brain UI must expose the live acceptance plan and evidence recording.")
    check("phase 100 completion gates use acceptance evidence",
          "live_acceptance_evidence" in (repo_root / "backend" / "app" / "brain.py").read_text(encoding="utf-8")
          and "required_acceptance_passes" in (repo_root / "backend" / "app" / "brain.py").read_text(encoding="utf-8")
          and "failed_or_blocked" in (repo_root / "backend" / "app" / "brain.py").read_text(encoding="utf-8"),
          "Jarvis completion must require recorded live-house acceptance evidence.")
    check("phase 101 live acceptance report exists",
          "build_live_acceptance_report" in experience_brain
          and "build_jarvis_phase_101" in experience_brain
          and "# TPG HomeAI Live Acceptance Report" in experience_brain
          and "acceptance_release_report" in (repo_root / "backend" / "app" / "brain.py").read_text(encoding="utf-8"),
          "Live acceptance evidence must be exportable as structured JSON and Markdown.")
    check("phase 101 endpoints are exposed",
          "/experience/live-acceptance/report" in backend_main
          and "/brain/phase-101" in backend_main,
          "Backend must expose the live acceptance report and phase 101 summary.")
    check("phase 102 frontend acceptance report export is wired",
          "liveAcceptanceReport" in api_frontend
          and "Copy report" in (repo_root / "frontend" / "src" / "pages" / "Brain.tsx").read_text(encoding="utf-8")
          and "Download Markdown" in (repo_root / "frontend" / "src" / "pages" / "Brain.tsx").read_text(encoding="utf-8"),
          "Brain UI must let owners copy or download the live acceptance report.")

    # Phase 0 — security rating 7 -> 8 and non-ingress API auth.
    apparmor = (repo_root / "tpg_homeai" / "apparmor.txt")
    check("add-on ships an AppArmor profile (rating 7 -> 8)",
          apparmor.is_file() and "profile tpg_homeai" in apparmor.read_text(encoding="utf-8"),
          "A named apparmor.txt profile raises the HA security rating by +1.")
    check("config.yaml enables apparmor + api_token option",
          "apparmor: true" in addon_config
          and "api_token:" in addon_config,
          "The add-on must enable its AppArmor profile and expose api_token.")
    check("run.sh exports the API token",
          "TPG_API_TOKEN" in run_sh,
          "run.sh must export the optional non-ingress API bearer token.")
    check("backend guards non-ingress API with a bearer token",
          "_auth_guard_response" in backend_main
          and "TPG_API_TOKEN" in (repo_root / "backend" / "app" / "settings.py").read_text(encoding="utf-8"),
          "Direct LAN callers must present Authorization: Bearer <token> when set.")

    # Phase 2b/2c/3 — hands-free panel mode + ChatGPT-style UI.
    tailwind = (repo_root / "frontend" / "tailwind.config.js").read_text(encoding="utf-8")
    check("frontend ships always-listening panel mode + wake word loop",
          "panelMode" in chat_frontend
          and "extractCommandAfterWakeWord" in chat_frontend
          and "getSpeechRecognition" in chat_frontend,
          "Tablets/old phones need a browser wake-word panel mode.")
    check("frontend renders markdown for assistant replies",
          "function Markdown" in chat_frontend,
          "Assistant messages should render lightweight markdown.")
    check("frontend uses the near-black ChatGPT-style theme",
          "#0a0a0a" in tailwind and "#171717" in tailwind,
          "The theme tokens should use near-black surfaces, not navy/sky.")

    print("PART 1 — API routing returns JSON, SPA never shadows API routes")
    r = client.get("/health")
    check("/health is JSON", is_json(r) and not is_html(r), r.headers.get("content-type", ""))
    check("/health has status", r.json().get("status") in ("ok", "degraded", "initializing"))

    r = client.get("/api/health")
    check("/api/health legacy prefix is JSON", is_json(r) and not is_html(r),
          r.headers.get("content-type", ""))

    ingress = "/3e5a55d6_tpg_homeai"
    hassio_ingress = "/api/hassio_ingress/3e5a55d6_tpg_homeai"
    r = client.get(f"{ingress}/api/health")
    check("ingress /api/health is JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    r = client.get(f"{ingress}/health")
    check("ingress /health is JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    r = client.get(f"{hassio_ingress}/api/health")
    check("hassio ingress /api/health is JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    r = client.get(f"{hassio_ingress}/health")
    check("hassio ingress /health is JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")

    r = client.post("/api/config/reload", json={})
    check("/api/config/reload legacy prefix works", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")

    r = client.post("/config/rooms", json={
        "id": "test_room",
        "name": "Test Room",
        "aliases": ["test room"],
        "lights": ["light.test_room"],
        "fans": [],
    })
    check("/config/rooms upserts room", r.status_code == 200 and r.json().get("saved") is True,
          r.text)
    check("/config/rooms reloads runtime",
          any(room.get("id") == "test_room" for room in client.get("/config").json().get("devices", {}).get("rooms", [])),
          client.get("/config").text)

    r = client.post("/config/assistants", json={
        "id": "test_assistant",
        "name": "Test Assistant",
        "owner": "shawn",
        "aliases": ["test assistant"],
        "wake_words": ["test assistant", "hey test"],
        "listen_enabled": True,
        "personality": "A concise test assistant.",
        "tone": "calm",
        "voice": {"provider": "openai", "model": "gpt-4o-mini-tts", "voice": "coral"},
    })
    check("/config/assistants upserts assistant",
          r.status_code == 200 and r.json().get("saved") is True,
          r.text)
    config_after_assistant = client.get("/config").json()
    test_assistant = next((a for a in config_after_assistant.get("assistants", {}).get("assistants", [])
                           if a.get("id") == "test_assistant"), {})
    check("/config/assistants saves wake words",
          test_assistant.get("wake_words") == ["test assistant", "hey test"],
          str(test_assistant))

    r = client.post("/config/users", json={
        "id": "shawn",
        "name": "Shawn",
        "role": "resident",
        "aliases": ["shawn", "boss", "owner"],
        "music_account": "spotify_xtpgx",
    })
    check("/config/users blocks demoting last owner",
          r.status_code == 400 and "no Owner/Admin" in r.text,
          r.text)

    r = client.post("/config/users", json={
        "id": "test_user",
        "name": "Test User",
        "aliases": ["tester"],
        "music_account": "spotify_xtpgx",
        "permissions": {"can_control_lights": True, "can_unlock_doors": False},
    })
    check("/config/users upserts user",
          r.status_code == 200 and r.json().get("saved") is True,
          r.text)

    r = client.post("/config/music-accounts", json={
        "id": "spotify_test",
        "name": "Spotify [test]",
        "provider": "spotify",
        "account": "test",
        "owner": "test_user",
        "default_media": {"media_id": "Daily Mix", "media_type": "playlist"},
    })
    check("/config/music-accounts upserts account",
          r.status_code == 200 and r.json().get("saved") is True,
          r.text)

    r = client.post("/config/speakers", json={
        "id": "test_speaker",
        "name": "Test Speaker",
        "entity_id": "media_player.test_speaker",
        "room": "test_room",
        "aliases": ["test speaker"],
    })
    check("/config/speakers upserts speaker",
          r.status_code == 200 and r.json().get("saved") is True,
          r.text)

    permissions = client.get("/config").json().get("permissions", {})
    permissions["confirmation_ttl_seconds"] = 90
    permissions.setdefault("sensitive_actions", ["unlock_door"])
    permissions.setdefault("confirmation_messages", {"unlock_door": "Confirm: unlock the {target}?"})
    r = client.post("/config/permissions", json=permissions)
    check("/config/permissions saves policy",
          r.status_code == 200 and r.json().get("saved") is True,
          r.text)

    r = client.post("/config/voice-sources", json={
        "id": "test_voice_source",
        "name": "Test Voice Source",
        "room": "test_room",
        "assistant": "test_assistant",
        "trust_level": "household",
        "default_reply": "browser",
        "aliases": ["test mic"],
    })
    check("/config/voice-sources upserts source",
          r.status_code == 200 and r.json().get("saved") is True,
          r.text)

    r = client.get("/discovery/summary")
    check("/discovery/summary is JSON", is_json(r), r.headers.get("content-type", ""))
    check("/discovery/summary has pending_count", "pending_count" in r.json())

    r = client.get("/state")
    check("/state is JSON", is_json(r))

    r = client.get("/ui/session")
    check("/ui/session is JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    ui = r.json()
    check("/ui/session has roles",
          ui.get("roles", {}).get("admin") and ui.get("roles", {}).get("resident")
          and ui.get("roles", {}).get("kiosk"),
          str(ui))
    check("/ui/session does not default to owner/admin without trusted HA identity",
          ui.get("detected_user", {}).get("id") == "house_remote"
          and ui.get("detected_user", {}).get("role") == "kiosk"
          and ui.get("role") == "kiosk"
          and ui.get("identity_trusted") is False
          and ui.get("identity_source") == "safe_fallback",
          str(ui))
    check("/ui/session defaults missing identity to shared Jarvis",
          ui.get("default_assistant", {}).get("id") == "jarvis",
          str(ui))
    r = client.get("/ui/session", headers={"x-ha-user-name": "Jordie"})
    check("/ui/session maps HA header to resident user",
          r.status_code == 200
          and r.json().get("detected_user", {}).get("id") == "jordie"
          and r.json().get("detected_user", {}).get("role") == "resident",
          str(r.json()))
    r = client.get("/ui/session", headers={"x-ha-user-id": "jordie"})
    check("/ui/session maps HA user-id header to resident user",
          r.status_code == 200
          and r.json().get("detected_user", {}).get("id") == "jordie"
          and r.json().get("identity_trusted") is True,
          str(r.json()))
    r = client.get("/ui/session", headers={"x-forwarded-user": "Jordie"})
    check("/ui/session ignores generic forwarded-user identity",
          r.status_code == 200
          and r.json().get("detected_user", {}).get("id") == "house_remote"
          and r.json().get("identity_source") == "safe_fallback",
          str(r.json()))
    r = client.get("/ui/session", headers={
        "x-ha-user-name": "Jordie",
        "x-ha-user-is-admin": "true",
    })
    check("/ui/session honors HA admin authority",
          r.status_code == 200
          and r.json().get("detected_user", {}).get("id") == "jordie"
          and r.json().get("detected_user", {}).get("role") == "admin"
          and r.json().get("role") == "admin"
          and r.json().get("ha_admin") is True,
          str(r.json()))
    r = client.get("/ui/session", headers={"x-ha-user-name": "jordie-rae"})
    check("/ui/session normalizes HA usernames",
          r.status_code == 200
          and r.json().get("detected_user", {}).get("id") == "jordie",
          str(r.json()))
    r = client.get("/ui/session", headers={"x-ha-user-name": "kiosk"})
    check("/ui/session maps HA header to kiosk user",
          r.status_code == 200
          and r.json().get("detected_user", {}).get("id") == "house_remote"
          and r.json().get("detected_user", {}).get("role") == "kiosk",
          str(r.json()))
    check("/ui/session defaults kiosk to Jarvis",
          r.json().get("default_assistant", {}).get("id") == "jarvis",
          str(r.json()))
    r = client.get("/ui/session", headers={"x-ha-user-name": "New HA User"})
    check("/ui/session reports unknown HA user",
          r.status_code == 200 and r.json().get("unknown_ha_user") == "new ha user",
          str(r.json()))
    r = client.get("/suggestions/proactive")
    check("unknown HA user creates setup suggestion",
          any(s.get("action_type") == "create_user_profile"
              and s.get("payload", {}).get("username") == "new ha user"
              for s in r.json().get("suggestions", [])),
          str(r.json()))

    # HA Supervisor ingress headers are the authoritative identity source.
    r = client.get("/ui/session", headers={"x-remote-user-name": "Shawn"})
    check("/ui/session maps ingress X-Remote-User-Name to owner",
          r.status_code == 200
          and r.json().get("detected_user", {}).get("id") == "shawn"
          and r.json().get("detected_user", {}).get("role") == "admin"
          and r.json().get("identity_trusted") is True
          and r.json().get("identity_source") == "ha_ingress",
          str(r.json()))
    r = client.get("/ui/session", headers={"x-remote-user-name": "Jordie"})
    check("/ui/session maps ingress X-Remote-User-Name to resident",
          r.status_code == 200
          and r.json().get("detected_user", {}).get("id") == "jordie"
          and r.json().get("detected_user", {}).get("role") == "resident"
          and r.json().get("identity_source") == "ha_ingress",
          str(r.json()))
    r = client.get("/ui/session", headers={"x-remote-user-display-name": "Jordie"})
    check("/ui/session maps ingress X-Remote-User-Display-Name",
          r.status_code == 200
          and r.json().get("detected_user", {}).get("id") == "jordie"
          and r.json().get("identity_source") == "ha_ingress",
          str(r.json()))
    r = client.get("/ui/session", headers={
        "x-remote-user-name": "Shawn",
        "x-ha-user-name": "Jordie",
    })
    check("/ui/session ingress header wins over legacy/stale header",
          r.status_code == 200
          and r.json().get("detected_user", {}).get("id") == "shawn"
          and r.json().get("identity_source") == "ha_ingress",
          str(r.json()))
    r = client.get("/ui/session/debug", headers={"x-remote-user-name": "Shawn"})
    dbg = r.json()
    check("/ui/session/debug reports ingress candidate + match",
          r.status_code == 200
          and "shawn" in dbg.get("candidates", {}).get("ingress", [])
          and dbg.get("matches", {}).get("ingress") == "shawn"
          and dbg.get("version"),
          str(dbg))

    current_user_payload = {"id": "ha-shawn-verified", "name": "Shawn", "username": "thatpalmerguy", "is_admin": True}

    async def fake_current_user(_self):
        return current_user_payload

    with patch("app.main.HomeAssistantWebSocket.fetch_current_user", fake_current_user):
        r = client.post("/ui/session", json={"ha_access_token": "verified-token"})
        check("/ui/session verified HA token maps Shawn owner",
              r.status_code == 200
              and r.json().get("detected_user", {}).get("id") == "shawn"
              and r.json().get("detected_user", {}).get("role") == "admin"
              and r.json().get("identity_source") == "ha_token",
              str(r.json()))
        current_user_payload = {"id": "ha-jordie-verified", "name": "Jordie", "username": "jordie", "is_admin": False}
        r = client.post("/ui/session", json={"ha_access_token": "verified-token"})
        check("/ui/session verified HA token maps Jordie resident",
              r.status_code == 200
              and r.json().get("detected_user", {}).get("id") == "jordie"
              and r.json().get("detected_user", {}).get("role") == "resident"
              and r.json().get("identity_source") == "ha_token",
              str(r.json()))
        r = client.post("/ui/session", json={
            "ha_access_token": "verified-token",
            "ha_client_user": {
                "id": "ha-shawn-live",
                "name": "Shawn",
                "username": "thatpalmerguy",
                "is_admin": True,
            },
        })
        check("/ui/session live HA parent user overrides stale token",
              r.status_code == 200
              and r.json().get("detected_user", {}).get("id") == "shawn"
              and r.json().get("detected_user", {}).get("role") == "admin"
              and r.json().get("identity_source") == "ha_parent",
              str(r.json()))
        r = client.post("/ui/session", json={
            "ha_client_user": {
                "id": "ha-kiosk-live",
                "name": "Kiosk",
                "username": "kiosk",
                "is_admin": False,
            },
        })
        check("/ui/session live HA parent user maps Kiosk to Jarvis",
              r.status_code == 200
              and r.json().get("detected_user", {}).get("id") == "house_remote"
              and r.json().get("default_assistant", {}).get("id") == "jarvis"
              and r.json().get("identity_source") == "ha_parent",
              str(r.json()))
        current_user_payload = {"id": "ha-kiosk-verified", "name": "Kiosk", "username": "kiosk", "is_admin": False}
        r = client.post("/ui/session", json={"ha_access_token": "verified-token"})
        check("/ui/session verified HA token maps Kiosk shared profile",
              r.status_code == 200
              and r.json().get("detected_user", {}).get("id") == "house_remote"
              and r.json().get("default_assistant", {}).get("id") == "jarvis"
              and r.json().get("identity_source") == "ha_token",
              str(r.json()))

    async def fake_auth_users(_self):
        return [
            {
                "id": "ha-admin-1",
                "name": "That Palmer Guy",
                "username": "thatpalmerguy",
                "is_admin": True,
            },
            {
                "id": "ha-resident-1",
                "name": "Resident Person",
                "username": "residentperson",
                "is_admin": False,
            },
            {
                "id": "ha-kiosk-1",
                "name": "Kiosk",
                "username": "kiosk",
                "is_admin": False,
            },
        ]

    with patch("app.main.HomeAssistantWebSocket.fetch_auth_users", fake_auth_users):
        r = client.post("/ha/users/sync")
    check("/ha/users/sync returns JSON",
          r.status_code == 200 and is_json(r) and r.json().get("synced") is True,
          f"status={r.status_code} body={r.text}")
    synced = r.json()
    check("/ha/users/sync creates HA-owned profiles",
          synced.get("created", 0) >= 2 and synced.get("counts", {}).get("users", 0) >= 4,
          str(synced))
    r = client.get("/config")
    synced_cfg = r.json().get("assistants", {})
    synced_users = synced_cfg.get("users", [])
    admin_profile = next((u for u in synced_users if u.get("ha_username") == "thatpalmerguy"), {})
    resident_profile = next((u for u in synced_users if u.get("ha_username") == "residentperson"), {})
    kiosk_profile = next((u for u in synced_users if u.get("ha_username") == "kiosk"), {})
    check("HA admin sync grants TPG admin access",
          admin_profile.get("role") == "admin"
          and admin_profile.get("access_source") == "home_assistant"
          and admin_profile.get("ha_is_admin") is True,
          str(admin_profile))
    check("HA non-admin sync grants resident self-service access",
          resident_profile.get("role") == "resident"
          and resident_profile.get("access_source") == "home_assistant"
          and resident_profile.get("ha_is_admin") is False,
          str(resident_profile))
    check("HA kiosk sync preserves shared kiosk profile",
          kiosk_profile.get("id") == "house_remote"
          and kiosk_profile.get("role") == "kiosk"
          and kiosk_profile.get("access_source") == "home_assistant"
          and kiosk_profile.get("ha_is_admin") is False,
          str(kiosk_profile))
    check("HA sync creates a personal assistant for resident users",
          any(a.get("owner") == resident_profile.get("id") for a in synced_cfg.get("assistants", [])),
          str(synced_cfg.get("assistants", [])))

    r = client.get("/config")
    check("/config is JSON", is_json(r))

    r = client.post("/dashboards/draft", json={"title": "TPG Home", "style": "native"})
    check("/dashboards/draft returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    body = r.json()
    check("/dashboards/draft includes yaml", bool(body.get("yaml")) and "views:" in body["yaml"],
          str(body))

    r = client.post("/dashboards/draft", json={
        "title": "TPG Home",
        "style": "native",
        "tablet_mode": True,
        "voice_panel": True,
    })
    check("/dashboards/draft supports tablet and voice views",
          r.status_code == 200 and "tpg-tablets" in r.json().get("yaml", "")
          and "tpg-voice" in r.json().get("yaml", ""),
          str(r.json()))
    r = client.post("/dashboards/draft", json={
        "title": "TPG Home",
        "style": "native",
        "template": "auto",
        "intent": "Build an office control dashboard for lights, fan, camera, music, and voice.",
    })
    body = r.json()
    check("/dashboards/draft infers template and room from natural language",
          r.status_code == 200
          and body.get("template") == "room"
          and body.get("room") == "office",
          str(body))
    check("/dashboards/draft returns architect summary",
          body.get("summary", {}).get("view_count", 0) >= 1
          and body.get("summary", {}).get("card_count", 0) >= 1
          and body.get("summary", {}).get("install_review_required") is True,
          str(body))

    r = client.post("/dashboards/install", json={"title": "TPG Home", "style": "native"})
    check("/dashboards/install returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    install_path = r.json().get("install", {}).get("path")
    check("/dashboards/install writes file", bool(install_path) and os.path.isfile(install_path),
          str(r.json()))

    r = client.get("/knowledge/graph?include_registries=false")
    check("/knowledge/graph returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/knowledge/graph has counts", "counts" in r.json(), str(r.json()))

    r = client.get("/brain/layers?include_registries=false")
    check("/brain/layers returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    brain = r.json()
    check("/brain/layers has Jarvis layers", len(brain.get("layers", [])) >= 7,
          str(brain))
    check("/brain/layers includes reliability brain",
          any(layer.get("id") == "reliability_brain" for layer in brain.get("layers", [])),
          str(brain))

    r = client.get("/brain/completion?include_registries=false")
    check("/brain/completion returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/brain/completion has stop criteria",
          "gates" in r.json() and "complete_spot" in r.json(),
          str(r.json()))
    completion = r.json()
    check("/brain/completion includes acceptance evidence gate",
          any(gate.get("id") == "live_acceptance_evidence" for gate in completion.get("gates", []))
          and completion.get("acceptance", {}).get("required_passed", 0) >= 5,
          str(completion))

    r = client.get("/brain/house-state?include_registries=false")
    check("/brain/house-state returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/brain/house-state has modes", isinstance(r.json().get("modes"), list),
          str(r.json()))
    check("/brain/house-state includes mode brain and wake word",
          "mode_brain" in r.json() and "wake_word" in r.json(),
          str(r.json()))
    wake_word = r.json().get("wake_word", {})
    check("/brain/house-state wake word has assistants",
          bool(wake_word.get("assistants")) and "assistants_ready" in wake_word.get("counts", {}),
          str(wake_word))
    check("/brain/house-state includes media/security/occupancy brain",
          "media_control" in r.json()
          and "camera_security" in r.json()
          and "room_occupancy" in r.json(),
          str(r.json()))
    check("/brain/house-state includes daily briefing",
          "daily_briefing" in r.json() and "headline" in r.json().get("daily_briefing", {}),
          str(r.json()))
    check("/brain/house-state includes proactive action plan",
          "proactive_action_plan" in r.json()
          and "policy" in r.json().get("proactive_action_plan", {}),
          str(r.json()))

    r = client.get("/brain/modes")
    check("/brain/modes returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/brain/modes has active policy",
          "active_modes" in r.json() and "policy" in r.json(),
          str(r.json()))

    r = client.get("/brain/assistants")
    check("/brain/assistants returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/brain/assistants includes assistant intelligence",
          len(r.json().get("assistants", [])) >= 2,
          str(r.json()))

    r = client.get("/brain/phase-66-71")
    check("/brain/phase-66-71 returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/brain/phase-66-71 has media/security/occupancy sections",
          "music_assistant" in r.json()
          and "media_control" in r.json()
          and "camera_security" in r.json()
          and "room_occupancy" in r.json(),
          str(r.json()))

    r = client.get("/media/music-assistant")
    check("/media/music-assistant returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/media/music-assistant exposes accounts and speakers",
          "accounts" in r.json() and "speakers" in r.json() and "counts" in r.json(),
          str(r.json()))

    r = client.get("/media/control")
    check("/media/control returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/media/control exposes player and display routes",
          "media_players" in r.json() and "display_routes" in r.json() and "counts" in r.json(),
          str(r.json()))

    r = client.get("/security/briefing")
    check("/security/briefing returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/security/briefing exposes briefing and configured security devices",
          "briefing" in r.json() and "cameras" in r.json() and "locks" in r.json(),
          str(r.json()))

    r = client.get("/rooms/occupancy")
    check("/rooms/occupancy returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/rooms/occupancy exposes room likelihoods",
          "rooms" in r.json() and "counts" in r.json(),
          str(r.json()))

    r = client.get("/brain/phase-72-76")
    check("/brain/phase-72-76 returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/brain/phase-72-76 has situational sections",
          "environment" in r.json()
          and "calendar_todo" in r.json()
          and "presence_zones" in r.json()
          and "maintenance" in r.json()
          and "daily_briefing" in r.json(),
          str(r.json()))

    r = client.get("/awareness/environment")
    check("/awareness/environment returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/awareness/environment exposes weather/sensor counts",
          "weather" in r.json() and "environment_sensors" in r.json() and "counts" in r.json(),
          str(r.json()))

    r = client.get("/awareness/calendar-todo")
    check("/awareness/calendar-todo returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/awareness/calendar-todo exposes calendars and todos",
          "calendars" in r.json() and "todos" in r.json() and "counts" in r.json(),
          str(r.json()))

    r = client.get("/awareness/presence-zones")
    check("/awareness/presence-zones returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/awareness/presence-zones exposes presence context",
          "people" in r.json() and "zones" in r.json() and "personal_devices" in r.json(),
          str(r.json()))

    r = client.get("/awareness/maintenance")
    check("/awareness/maintenance returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/awareness/maintenance exposes health attention",
          "unavailable" in r.json() and "low_batteries" in r.json() and "counts" in r.json(),
          str(r.json()))

    r = client.get("/briefings/daily")
    check("/briefings/daily returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/briefings/daily exposes spoken briefing and source brains",
          "headline" in r.json() and "spoken" in r.json() and "brains" in r.json(),
          str(r.json()))

    r = client.get("/brain/phase-77-81")
    check("/brain/phase-77-81 returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/brain/phase-77-81 has routine sections",
          "security_routines" in r.json()
          and "comfort_energy" in r.json()
          and "media_scenes" in r.json()
          and "sleep_wake" in r.json()
          and "proactive_action_plan" in r.json(),
          str(r.json()))

    r = client.get("/routines/security")
    check("/routines/security returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/routines/security exposes templates and guardrails",
          "routine_templates" in r.json() and "guardrails" in r.json(),
          str(r.json()))

    r = client.get("/routines/comfort-energy")
    check("/routines/comfort-energy returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/routines/comfort-energy exposes optimizer context",
          "recommendations" in r.json() and "routine_templates" in r.json(),
          str(r.json()))

    r = client.get("/routines/media-scenes")
    check("/routines/media-scenes returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/routines/media-scenes exposes scene templates",
          "scene_templates" in r.json() and "display_routes" in r.json(),
          str(r.json()))

    r = client.get("/routines/sleep-wake")
    check("/routines/sleep-wake returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/routines/sleep-wake exposes sleep/wake templates",
          "routine_templates" in r.json() and "guardrails" in r.json(),
          str(r.json()))

    r = client.get("/routines/proactive-plan")
    check("/routines/proactive-plan returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/routines/proactive-plan is approval-first",
          r.json().get("policy", {}).get("approval_first") is True
          and r.json().get("policy", {}).get("auto_execute") is False,
          str(r.json()))

    r = client.get("/brain/phase-82-86")
    check("/brain/phase-82-86 returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/brain/phase-82-86 has operations sections",
          "capability_gaps" in r.json()
          and "onboarding" in r.json()
          and "diagnostics" in r.json()
          and "backup_recovery" in r.json()
          and "integration_matrix" in r.json(),
          str(r.json()))

    r = client.get("/ops/capability-gaps")
    check("/ops/capability-gaps returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/ops/capability-gaps exposes open gaps and gates",
          "open_gaps" in r.json() and "all_gates" in r.json() and "counts" in r.json(),
          str(r.json()))

    r = client.get("/ops/onboarding")
    check("/ops/onboarding returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/ops/onboarding exposes ordered setup steps",
          "steps" in r.json() and "next_step" in r.json(),
          str(r.json()))

    r = client.get("/ops/diagnostics")
    check("/ops/diagnostics returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/ops/diagnostics is support-safe",
          r.json().get("safe_for_support") is True
          and r.json().get("secrets_redacted") is True
          and "settings" in r.json()
          and "counts" in r.json(),
          str(r.json()))

    r = client.get("/ops/backup-readiness")
    check("/ops/backup-readiness returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/ops/backup-readiness exposes recovery paths",
          "automations_yaml" in r.json()
          and "config_dir" in r.json()
          and "recommendations" in r.json(),
          str(r.json()))

    r = client.get("/ops/integration-matrix")
    check("/ops/integration-matrix returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/ops/integration-matrix lists major integrations",
          "integrations" in r.json()
          and any(item.get("id") == "home_assistant" for item in r.json().get("integrations", []))
          and any(item.get("id") == "openai" for item in r.json().get("integrations", [])),
          str(r.json()))

    r = client.get("/brain/phase-87-91")
    check("/brain/phase-87-91 returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/brain/phase-87-91 has governance sections",
          "privacy" in r.json()
          and "roles" in r.json()
          and "memory_quality" in r.json()
          and "context_export" in r.json()
          and "completion_audit" in r.json(),
          str(r.json()))

    r = client.get("/governance/privacy")
    check("/governance/privacy returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/governance/privacy exposes data controls",
          "data_stores" in r.json()
          and "controls" in r.json()
          and "counts" in r.json(),
          str(r.json()))

    r = client.get("/governance/roles")
    check("/governance/roles returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/governance/roles exposes HA authority policy",
          r.json().get("policy", {}).get("ha_is_authority") is True
          and "users" in r.json()
          and "roles" in r.json(),
          str(r.json()))

    r = client.get("/governance/memory-quality")
    check("/governance/memory-quality returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/governance/memory-quality exposes memory health",
          "counts" in r.json()
          and "recommendations" in r.json()
          and "duplicate_keys" in r.json(),
          str(r.json()))

    r = client.get("/context/export")
    check("/context/export returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/context/export is redacted and portable",
          r.json().get("payload", {}).get("safe_for_export") is True
          and r.json().get("payload", {}).get("secrets_redacted") is True
          and "markdown" in r.json(),
          str(r.json()))

    r = client.get("/governance/completion-audit")
    check("/governance/completion-audit returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/governance/completion-audit exposes stop line",
          "completion" in r.json()
          and "stop_line" in r.json()
          and "blockers" in r.json(),
          str(r.json()))

    r = client.get("/brain/phase-92-96")
    check("/brain/phase-92-96 returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/brain/phase-92-96 has experience/release sections",
          "interaction_quality" in r.json()
          and "voice_acceptance" in r.json()
          and "device_acceptance" in r.json()
          and "release_checklist" in r.json()
          and "operational_runbook" in r.json(),
          str(r.json()))

    r = client.get("/experience/interaction-quality")
    check("/experience/interaction-quality returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/experience/interaction-quality exposes quality signals",
          "counts" in r.json()
          and "recent_failures" in r.json()
          and "recommendations" in r.json(),
          str(r.json()))

    r = client.get("/experience/voice-acceptance")
    check("/experience/voice-acceptance returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/experience/voice-acceptance exposes required tests",
          "acceptance_tests" in r.json()
          and "blockers" in r.json()
          and "readiness" in r.json(),
          str(r.json()))

    r = client.get("/experience/device-acceptance")
    check("/experience/device-acceptance returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/experience/device-acceptance exposes domain checks",
          "checks" in r.json()
          and "role_acceptance" in r.json()
          and "domain_counts" in r.json(),
          str(r.json()))

    r = client.get("/release/checklist")
    check("/release/checklist returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/release/checklist exposes ship rule",
          "checks" in r.json()
          and "ship_rule" in r.json()
          and "blockers" in r.json(),
          str(r.json()))

    r = client.get("/release/runbook")
    check("/release/runbook returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/release/runbook exposes operational steps",
          "runbook" in r.json()
          and "release_checklist" in r.json()
          and any(step.get("id") == "feature_freeze" for step in r.json().get("runbook", [])),
          str(r.json()))

    r = client.get("/brain/phase-97")
    check("/brain/phase-97 returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/brain/phase-97 has live acceptance section",
          "live_acceptance" in r.json()
          and r.json().get("phase") == 97,
          str(r.json()))

    r = client.get("/experience/live-acceptance")
    check("/experience/live-acceptance returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    live_acceptance = r.json()
    check("/experience/live-acceptance is non-mutating",
          live_acceptance.get("policy", {}).get("read_only") is True
          and live_acceptance.get("policy", {}).get("executes_actions") is False
          and live_acceptance.get("policy", {}).get("requires_human_to_run_mutating_tests") is True,
          str(live_acceptance))
    check("/experience/live-acceptance exposes tests and blockers",
          "tests" in live_acceptance
          and "summary" in live_acceptance
          and "blockers" in live_acceptance
          and any(test.get("mode") == "dry_run_required" for test in live_acceptance.get("tests", [])),
          str(live_acceptance))

    r = client.post("/experience/live-acceptance/results", json={
        "test_id": "ha_health_probe",
        "status": "passed",
        "assistant": "atlas",
        "user": "shawn",
        "notes": "Verifier recorded read-only acceptance evidence.",
        "evidence": {"source": "verify_addon", "mutating": False},
    })
    check("/experience/live-acceptance/results records evidence",
          r.status_code == 200 and is_json(r) and r.json().get("recorded") is True,
          f"status={r.status_code} payload={r.text}")

    r = client.get("/experience/live-acceptance/results")
    check("/experience/live-acceptance/results lists evidence",
          r.status_code == 200
          and is_json(r)
          and r.json().get("count", 0) >= 1
          and "latest_by_test" in r.json(),
          str(r.json()))

    r = client.get("/experience/live-acceptance")
    check("/experience/live-acceptance includes evidence summary",
          r.status_code == 200
          and is_json(r)
          and r.json().get("evidence", {}).get("count", 0) >= 1,
          str(r.json()))

    r = client.get("/experience/live-acceptance/report")
    check("/experience/live-acceptance/report returns JSON",
          r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/experience/live-acceptance/report exports markdown",
          "# TPG HomeAI Live Acceptance Report" in r.json().get("markdown", "")
          and r.json().get("summary", {}).get("evidence_results", 0) >= 1
          and "blockers" in r.json(),
          str(r.json()))

    r = client.get("/brain/phase-101")
    check("/brain/phase-101 returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/brain/phase-101 has acceptance report section",
          r.json().get("phase") == 101
          and "acceptance_report" in r.json()
          and "markdown" in r.json().get("acceptance_report", {}),
          str(r.json()))

    r = client.get("/brain/completion?include_registries=false")
    check("/brain/completion counts recorded acceptance evidence",
          r.status_code == 200
          and is_json(r)
          and r.json().get("acceptance", {}).get("unique_passed", 0) >= 1,
          str(r.json()))

    r = client.get("/knowledge/physical-devices?include_registries=false")
    check("/knowledge/physical-devices returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/knowledge/physical-devices has devices list", isinstance(r.json().get("devices"), list),
          str(r.json()))

    r = client.get("/knowledge/device-profiles?include_registries=false")
    check("/knowledge/device-profiles returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/knowledge/device-profiles has counts", "counts" in r.json(), str(r.json()))
    profiles_payload = r.json()
    first_profile = (profiles_payload.get("profiles") or [{}])[0]
    check("/knowledge/device-profiles includes reliability",
          profiles_payload.get("counts", {}).get("profiles", 0) == 0
          or ("reliability" in first_profile and "service_strategy" in first_profile),
          str(profiles_payload))

    r = client.get("/knowledge/reliability")
    check("/knowledge/reliability returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/knowledge/reliability has live score",
          "score" in r.json() and "status_counts" in r.json(),
          str(r.json()))

    r = client.get("/knowledge/device-adapters?include_registries=false")
    check("/knowledge/device-adapters returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/knowledge/device-adapters has counts", "counts" in r.json(), str(r.json()))

    r = client.get("/knowledge/voice-sources")
    check("/knowledge/voice-sources returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/knowledge/voice-sources has list", "voice_sources" in r.json(), str(r.json()))
    check("/knowledge/voice-sources includes route readiness",
          "counts" in r.json() and r.json()["counts"].get("total", 0) >= 1,
          str(r.json()))

    r = client.get("/house/assets")
    check("/house/assets returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    r = client.post(
        "/house/assets",
        data={
            "title": "Office floor plan",
            "asset_type": "floorplan",
            "room": "Office",
            "uploaded_by": "shawn",
            "description": "Office layout note with desk, speaker, display, and light switch.",
        },
        files={"file": ("office-floorplan.txt", b"Office floor plan: desk, speaker, display, light switch.", "text/plain")},
    )
    check("/house/assets uploads draft asset",
          r.status_code == 200 and is_json(r) and r.json().get("asset", {}).get("status") == "draft",
          r.text)
    house_asset_id = r.json().get("asset", {}).get("id")
    check("/house/assets analyzes uploaded asset",
          bool(r.json().get("asset", {}).get("analysis", {}).get("summary")),
          str(r.json()))
    r = client.post(f"/house/assets/{house_asset_id}/approve")
    check("/house/assets/{id}/approve activates asset",
          r.status_code == 200 and r.json().get("asset", {}).get("status") == "approved",
          r.text)
    r = client.get("/house/assets?status=approved")
    check("/house/assets lists approved assets",
          any(a.get("id") == house_asset_id for a in r.json().get("assets", [])),
          str(r.json()))
    r = client.get(f"/house/assets/{house_asset_id}/file")
    check("/house/assets/{id}/file returns original file",
          r.status_code == 200 and b"Office floor plan" in r.content,
          f"status={r.status_code} body={r.text[:100] if hasattr(r, 'text') else ''}")
    r = client.get("/house/spatial-brain")
    check("/house/spatial-brain returns approved room context",
          r.status_code == 200
          and r.json().get("summary", {}).get("approved_assets", 0) >= 1
          and any(room.get("display_name") == "Office" for room in r.json().get("rooms", [])),
          str(r.json()))
    r = client.post("/dashboards/draft", json={"title": "TPG Office Spatial", "style": "native", "room": "Office"})
    check("/dashboards/draft includes spatial layout notes",
          r.status_code == 200
          and "AI Layout Notes" in r.json().get("yaml", "")
          and r.json().get("spatial_brain", {}).get("summary", {}).get("approved_assets", 0) >= 1,
          str(r.json()))
    r = client.post("/chat", json={
        "assistant": "atlas",
        "user": "shawn",
        "conversation_id": "house-asset-context",
        "message": "What room candidates are in my approved office floorplan asset?",
    })
    check("/chat includes approved house assets in context",
          "Approved house knowledge assets" in r.json().get("data", {}).get("house_context", ""),
          str(r.json()))

    r = client.get("/voice/deployment")
    check("/voice/deployment returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/voice/deployment has readiness counts",
          "counts" in r.json() and "sources" in r.json(),
          str(r.json()))
    voice_counts = r.json().get("counts", {})
    check("/voice/deployment separates wake words from source deployment",
          "assistants_with_wake_words" in voice_counts
          and "assistants_with_linked_sources" in voice_counts,
          str(voice_counts))
    r = client.get("/voice/runtime")
    check("/voice/runtime returns deployable assistant/source map",
          r.status_code == 200
          and "assistants" in r.json()
          and "room_routes" in r.json()
          and "runtime_sources" in r.json().get("counts", {}),
          str(r.json()))

    r = client.get("/dashboards/tablet-profiles")
    check("/dashboards/tablet-profiles returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/dashboards/tablet-profiles has counts", "counts" in r.json(), str(r.json()))

    r = client.get("/ai/providers")
    check("/ai/providers returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/ai/providers has fallback parser",
          r.json().get("providers", {}).get("fallback_parser", {}).get("available") is True,
          str(r.json()))

    r = client.get("/voice/profiles")
    check("/voice/profiles returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    voice_profiles = r.json()
    check("/voice/profiles has assistants",
          len(voice_profiles.get("profiles", [])) >= 2,
          str(voice_profiles))
    atlas_profile = next((p for p in voice_profiles.get("profiles", [])
                          if p.get("assistant", {}).get("id") == "atlas"), {})
    chatty_profile = next((p for p in voice_profiles.get("profiles", [])
                           if p.get("assistant", {}).get("id") == "chatty"), {})
    check("/voice/profiles atlas uses OpenAI Cedar",
          atlas_profile.get("provider") == "openai" and atlas_profile.get("voice") == "cedar",
          str(atlas_profile))
    check("/voice/profiles chatty uses OpenAI Coral",
          chatty_profile.get("provider") == "openai" and chatty_profile.get("voice") == "coral",
          str(chatty_profile))
    r = client.post("/config/assistants", json={
        "id": "atlas",
        "name": "Atlas",
        "owner": "shawn",
        "aliases": ["atlas"],
        "wake_words": ["atlas", "hey atlas"],
        "listen_enabled": True,
        "personality": "Legacy browser voice upgrade check.",
        "tone": "confident",
        "voice": {"provider": "browser", "voice": "neutral", "fallback_provider": "browser"},
    })
    check("/config/assistants accepts legacy browser voice", r.status_code == 200, r.text)
    r = client.get("/voice/profiles")
    legacy_atlas_profile = next((p for p in r.json().get("profiles", [])
                                 if p.get("assistant", {}).get("id") == "atlas"), {})
    check("/voice/profiles upgrades legacy atlas browser voice",
          legacy_atlas_profile.get("provider") == "openai"
          and legacy_atlas_profile.get("voice") == "cedar",
          str(legacy_atlas_profile))

    r = client.get("/voice/voices")
    check("/voice/voices returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/voice/voices includes catalog",
          any(v.get("id") == "coral" for v in r.json().get("voices", [])),
          str(r.json()))

    r = client.post("/voice/preview", json={
        "assistant": "chatty",
        "text": "Voice check.",
        "room": "office",
        "reply_mode": "room_speaker",
    })
    check("/voice/preview returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/voice/preview reports fallback when OpenAI absent",
          r.json().get("will_fallback_to_browser") is True,
          str(r.json()))
    check("/voice/preview resolves speaker route",
          r.json().get("profile", {}).get("route", {}).get("target_entity_id") == "media_player.office_speaker",
          str(r.json()))

    r = client.post("/voice/speak", json={
        "assistant": "atlas",
        "text": "Voice check.",
    })
    check("/voice/speak returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/voice/speak falls back to browser without key",
          r.json().get("mode") == "browser" and r.json().get("provider") == "browser",
          str(r.json()))
    check("/voice/speak fallback preserves atlas voice profile",
          r.json().get("profile", {}).get("provider") == "openai"
          and r.json().get("profile", {}).get("voice") == "cedar",
          str(r.json()))
    r = client.post("/voice/speak", json={
        "assistant": "atlas",
        "text": "Voice override check.",
        "voice_profile": {"provider": "openai", "model": "gpt-4o-mini-tts", "voice": "onyx"},
    })
    check("/voice/speak preserves editor voice override",
          r.status_code == 200
          and r.json().get("profile", {}).get("provider") == "openai"
          and r.json().get("profile", {}).get("voice") == "onyx",
          str(r.json()))
    r = client.post("/voice/transcribe", files={"file": ("voice-input.webm", b"fake-audio", "audio/webm")})
    check("/voice/transcribe returns JSON without OpenAI key", r.status_code == 200 and is_json(r), r.text)
    check("/voice/transcribe explains missing OpenAI key",
          r.json().get("success") is False
          and "OpenAI API key" in r.json().get("error", ""),
          str(r.json()))
    from app.voice import _openai_speech_bytes, _safe_error_detail  # noqa: E402

    class FakeSpeech:
        def __init__(self):
            self.calls: list[dict[str, object]] = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            if "instructions" in kwargs:
                raise TypeError("Speech.create() got an unexpected keyword argument 'instructions'")
            return type("FakeAudio", (), {"read": lambda self: b"audio-bytes"})()

    fake_speech = FakeSpeech()
    fake_client = type("FakeClient", (), {
        "audio": type("FakeAudioRoot", (), {
            "speech": fake_speech,
        })(),
    })()
    with patch("openai.OpenAI", return_value=fake_client):
        audio = _openai_speech_bytes({
            "model": "gpt-4o-mini-tts",
            "voice": "cedar",
            "response_format": "mp3",
            "instructions": "sound natural",
        }, "hello")
    check("OpenAI TTS retries old SDK without instructions",
          audio == b"audio-bytes"
          and len(fake_speech.calls) == 2
          and "instructions" in fake_speech.calls[0]
          and "instructions" not in fake_speech.calls[1],
          str(fake_speech.calls))
    check("OpenAI TTS error detail redacts API keys",
          "sk-***" in _safe_error_detail(Exception("bad key sk-abc123SECRET")),
          _safe_error_detail(Exception("bad key sk-abc123SECRET")))

    r = client.post("/memory/draft", json={
        "scope": "user",
        "owner": "shawn",
        "subject": "office",
        "key": "fan_preference",
        "value": "prefers high while gaming",
    })
    check("/memory/draft returns JSON", r.status_code == 200 and is_json(r), r.text)
    memory_id = r.json().get("memory", {}).get("id")
    check("/memory/draft creates id", bool(memory_id), str(r.json()))
    if memory_id:
        r = client.post(f"/memory/{memory_id}/approve")
        check("/memory/{id}/approve works",
              r.status_code == 200 and r.json().get("memory", {}).get("status") == "approved",
              r.text)

    with get_session() as session:
        suggestion = Suggestion(
            title="Teach office fan preset strategy",
            message="Approve this to teach TPG HomeAI the preferred service strategy for this device.",
            category="repair",
            priority="high",
            action_type="device_profile_fix",
            payload=json.dumps({
                "proposed_memory": {
                    "scope": "device",
                    "subject": "fan.office",
                    "key": "preferred_fan_speed_control",
                    "value": {"strategy": "preset_mode", "preset_modes": ["low", "medium", "high"]},
                }
            }),
            status="suggested",
        )
        session.add(suggestion)
        session.commit()
        repair_suggestion_id = suggestion.id
    r = client.post(f"/suggestions/proactive/{repair_suggestion_id}/approve")
    with get_session() as session:
        learned = session.query(MemoryItem).filter(
            MemoryItem.scope == "device",
            MemoryItem.subject == "fan.office",
            MemoryItem.key == "preferred_fan_speed_control",
            MemoryItem.status == "approved",
        ).first()
    check("repair suggestion approval creates device strategy memory",
          r.status_code == 200 and learned is not None and "preset_mode" in learned.value,
          r.text)

    with get_session() as session:
        media_suggestion = Suggestion(
            title="Teach office TV media wake strategy",
            message="Approve this to teach TPG HomeAI the preferred service strategy for this device.",
            category="repair",
            priority="high",
            action_type="device_profile_fix",
            payload=json.dumps({
                "proposed_memory": {
                    "scope": "device",
                    "subject": "media_player.office_tv",
                    "key": "preferred_media_control",
                    "value": {"strategy": "media_play_wake", "last_service": "turn_on"},
                }
            }),
            status="suggested",
        )
        session.add(media_suggestion)
        session.commit()
        media_suggestion_id = media_suggestion.id
    r = client.post(f"/suggestions/proactive/{media_suggestion_id}/approve")
    with get_session() as session:
        learned_media = session.query(MemoryItem).filter(
            MemoryItem.scope == "device",
            MemoryItem.subject == "media_player.office_tv",
            MemoryItem.key == "preferred_media_control",
            MemoryItem.status == "approved",
        ).first()
    check("media repair approval creates media strategy memory",
          r.status_code == 200 and learned_media is not None and "media_play_wake" in learned_media.value,
          r.text)

    with get_session() as session:
        cover_suggestion = Suggestion(
            title="Teach patio shade cover strategy",
            message="Approve this to teach TPG HomeAI the preferred service strategy for this device.",
            category="repair",
            priority="high",
            action_type="device_profile_fix",
            payload=json.dumps({
                "proposed_memory": {
                    "scope": "device",
                    "subject": "cover.patio_shade",
                    "key": "preferred_cover_control",
                    "value": {"strategy": "position_or_state_verify", "last_service": "close_cover"},
                }
            }),
            status="suggested",
        )
        climate_suggestion = Suggestion(
            title="Teach office thermostat strategy",
            message="Approve this to teach TPG HomeAI the preferred service strategy for this device.",
            category="repair",
            priority="high",
            action_type="device_profile_fix",
            payload=json.dumps({
                "proposed_memory": {
                    "scope": "device",
                    "subject": "climate.office",
                    "key": "preferred_climate_control",
                    "value": {"strategy": "mode_then_temperature", "last_service": "set_temperature"},
                }
            }),
            status="suggested",
        )
        session.add_all([cover_suggestion, climate_suggestion])
        session.commit()
        cover_suggestion_id = cover_suggestion.id
        climate_suggestion_id = climate_suggestion.id
    r_cover = client.post(f"/suggestions/proactive/{cover_suggestion_id}/approve")
    r_climate = client.post(f"/suggestions/proactive/{climate_suggestion_id}/approve")
    with get_session() as session:
        learned_cover = session.query(MemoryItem).filter(
            MemoryItem.scope == "device",
            MemoryItem.subject == "cover.patio_shade",
            MemoryItem.key == "preferred_cover_control",
            MemoryItem.status == "approved",
        ).first()
        learned_climate = session.query(MemoryItem).filter(
            MemoryItem.scope == "device",
            MemoryItem.subject == "climate.office",
            MemoryItem.key == "preferred_climate_control",
            MemoryItem.status == "approved",
        ).first()
    check("cover repair approval creates cover strategy memory",
          r_cover.status_code == 200 and learned_cover is not None and "position_or_state_verify" in learned_cover.value,
          r_cover.text)
    check("climate repair approval creates climate strategy memory",
          r_climate.status_code == 200 and learned_climate is not None and "mode_then_temperature" in learned_climate.value,
          r_climate.text)

    phase_61_65_memories = [
        ("vacuum.living_room", "preferred_vacuum_control", "state_family_verify"),
        ("number.office_airflow", "preferred_number_control", "value_attribute_verify"),
        ("select.office_mode", "preferred_select_control", "state_or_option_verify"),
        ("humidifier.bedroom", "preferred_humidifier_control", "turn_on_then_humidity"),
        ("water_heater.main", "preferred_water_heater_control", "mode_then_temperature"),
        ("valve.irrigation", "preferred_valve_control", "delayed_state_verify"),
    ]
    phase_61_65_ids: list[int] = []
    with get_session() as session:
        for subject, key, strategy in phase_61_65_memories:
            row = Suggestion(
                title=f"Teach {subject} {strategy}",
                message="Approve this to teach TPG HomeAI the preferred service strategy for this device.",
                category="repair",
                priority="high",
                action_type="device_profile_fix",
                payload=json.dumps({
                    "proposed_memory": {
                        "scope": "device",
                        "subject": subject,
                        "key": key,
                        "value": {"strategy": strategy, "last_service": "verify"},
                    }
                }),
                status="suggested",
            )
            session.add(row)
            session.flush()
            phase_61_65_ids.append(row.id)
        session.commit()
    phase_61_65_responses = [
        client.post(f"/suggestions/proactive/{suggestion_id}/approve")
        for suggestion_id in phase_61_65_ids
    ]
    with get_session() as session:
        learned_61_65 = [
            session.query(MemoryItem).filter(
                MemoryItem.scope == "device",
                MemoryItem.subject == subject,
                MemoryItem.key == key,
                MemoryItem.status == "approved",
            ).first()
            for subject, key, _strategy in phase_61_65_memories
        ]
    check("phases 61-65 repair approvals create learned strategy memories",
          all(resp.status_code == 200 for resp in phase_61_65_responses)
          and all(row is not None and strategy in row.value for row, (_subject, _key, strategy) in zip(learned_61_65, phase_61_65_memories)),
          str([resp.text for resp in phase_61_65_responses]))

    r = client.post("/suggestions/generate")
    check("/suggestions/generate returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    r = client.post("/monitor/scan")
    check("/monitor/scan returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    r = client.get("/suggestions/proactive")
    check("/suggestions/proactive returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code}")

    r = client.post("/chat", json={
        "assistant": "atlas",
        "user": "shawn",
        "message": "Set a sleep timer on the office TV in 30 minutes.",
    })
    check("/chat returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    body = r.json()
    check("/chat creates proposal mode", body.get("mode") == "proposal", str(body))

    r = client.post("/chat", json={
        "assistant": "atlas",
        "user": "shawn",
        "message": "What is the weather like?",
    })
    check("/chat general weather returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    body = r.json()
    check("/chat general weather uses conversation mode",
          body.get("mode") == "conversation" and body.get("success") is True,
          str(body))

    r = client.post("/chat", json={
        "assistant": "atlas",
        "user": "shawn",
        "message": "Build a dashboard for the office with voice controls.",
    })
    check("/chat dashboard draft returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    body = r.json()
    check("/chat dashboard draft creates draft intent",
          body.get("command", {}).get("intent") == "draft_dashboard",
          str(body))
    check("/chat dashboard draft uses proposal mode",
          body.get("mode") == "proposal",
          str(body))
    check("/chat dashboard draft includes yaml",
          "yaml" in body.get("command", {}).get("data", {}).get("dashboard_draft", {}),
          str(body))
    check("/chat dashboard draft is proposal-gated",
          body.get("command", {}).get("data", {}).get("policy", {}).get("decision") == "proposal_required",
          str(body))

    r = client.post("/chat", json={
        "assistant": "chatty",
        "user": "jordie",
        "message": "Create scheduled task. Turn off all lights at 10 PM.",
    })
    check("/chat resident can draft scheduled automations",
          r.status_code == 200
          and r.json().get("mode") == "proposal"
          and r.json().get("command", {}).get("intent") == "create_simple_automation",
          str(r.json()))
    r = client.post("/test/action", json={
        "action": "create_simple_automation",
        "assistant": "atlas",
        "user": "shawn",
        "params": {
            "trigger_description": "at sunset when someone is home",
            "action_description": "turn on office light and turn off office fan",
            "original_request": "At sunset when someone is home, turn on office light and turn off office fan.",
        },
    })
    automation_yaml = r.json().get("data", {}).get("proposed_yaml", "")
    check("automation builder v2 supports sun, presence, and multi-action YAML",
          r.status_code == 200
          and "platform: sun" in automation_yaml
          and "Someone is home" in automation_yaml
          and automation_yaml.count("service:") >= 2,
          automation_yaml or str(r.json()))
    r = client.post("/test/action", json={
        "action": "create_simple_automation",
        "assistant": "atlas",
        "user": "shawn",
        "params": {
            "trigger_description": "weekdays at 9 PM",
            "action_description": "set office fan speed to level 5 and set office thermostat to 75",
            "original_request": "Create scheduled task weekdays at 9 PM: set office fan speed to level 5 and set office thermostat to 75.",
        },
    })
    automation_body = r.json()
    automation_yaml = automation_body.get("data", {}).get("proposed_yaml", "")
    check("automation builder v3 supports weekday, fan level, and climate temperature",
          r.status_code == 200
          and "weekday:" in automation_yaml
          and "fan.set_percentage" in automation_yaml
          and "percentage: 50" in automation_yaml
          and "climate.set_temperature" in automation_yaml
          and "temperature: 75" in automation_yaml,
          automation_yaml or str(automation_body))
    check("automation builder v3 returns summary and readiness warnings",
          "summary" in automation_body.get("data", {})
          and "warnings" in automation_body.get("data", {})
          and automation_body.get("data", {}).get("summary", {}).get("action_count", 0) >= 2,
          str(automation_body))
    r = client.post("/test/action", json={
        "action": "create_simple_automation",
        "assistant": "atlas",
        "user": "shawn",
        "params": {
            "trigger_description": "when the front door unlocks",
            "action_description": "turn on office light",
            "original_request": "Create automation: when the front door unlocks, turn on office light.",
        },
    })
    automation_body = r.json()
    automation_yaml = automation_body.get("data", {}).get("proposed_yaml", "")
    check("automation builder v4 supports lock state triggers",
          r.status_code == 200
          and "platform: state" in automation_yaml
          and "entity_id: lock.front_door" in automation_yaml
          and "to: unlocked" in automation_yaml
          and "light.turn_on" in automation_yaml,
          automation_yaml or str(automation_body))
    check("automation builder v4 labels state trigger previews",
          "When lock.front_door becomes unlocked" in automation_body.get("data", {}).get("summary", {}).get("trigger", ""),
          str(automation_body))
    r = client.post("/test/action", json={
        "action": "create_simple_automation",
        "assistant": "atlas",
        "user": "shawn",
        "params": {
            "trigger_description": "when the front door battery drops below 20",
            "action_description": "turn on office light",
            "original_request": "Create automation: when the front door battery drops below 20, turn on office light.",
        },
    })
    automation_body = r.json()
    automation_yaml = automation_body.get("data", {}).get("proposed_yaml", "")
    check("automation builder v4 supports numeric sensor triggers",
          r.status_code == 200
          and "platform: numeric_state" in automation_yaml
          and "entity_id: sensor.front_door_battery" in automation_yaml
          and "below: 20" in automation_yaml
          and "light.turn_on" in automation_yaml,
          automation_yaml or str(automation_body))
    r = client.post("/test/action", json={
        "action": "create_simple_automation",
        "assistant": "atlas",
        "user": "shawn",
        "params": {
            "trigger_description": "when the front door unlocks between 10 PM and 6 AM",
            "action_description": "turn on office light",
            "original_request": "Create automation: when the front door unlocks between 10 PM and 6 AM, turn on office light.",
        },
    })
    automation_body = r.json()
    automation_yaml = automation_body.get("data", {}).get("proposed_yaml", "")
    check("automation builder v5 supports overnight time window conditions",
          r.status_code == 200
          and "platform: state" in automation_yaml
          and "entity_id: lock.front_door" in automation_yaml
          and "condition: time" in automation_yaml
          and "after: '22:00:00'" in automation_yaml
          and "before: 06:00:00" in automation_yaml,
          automation_yaml or str(automation_body))
    r = client.post("/test/action", json={
        "action": "create_simple_automation",
        "assistant": "atlas",
        "user": "shawn",
        "params": {
            "trigger_description": "at 9 PM only if office light is off",
            "action_description": "turn on office fan",
            "original_request": "Create scheduled task at 9 PM only if office light is off: turn on office fan.",
        },
    })
    automation_body = r.json()
    automation_yaml = automation_body.get("data", {}).get("proposed_yaml", "")
    check("automation builder v5 supports entity state guard conditions",
          r.status_code == 200
          and "platform: time" in automation_yaml
          and "at: '21:00:00'" in automation_yaml
          and "condition: state" in automation_yaml
          and "entity_id: light.office" in automation_yaml
          and "state: 'off'" in automation_yaml
          and "fan.turn_on" in automation_yaml,
          automation_yaml or str(automation_body))
    r = client.post("/test/action", json={
        "action": "create_simple_automation",
        "assistant": "atlas",
        "user": "shawn",
        "params": {
            "trigger_description": "when the front door unlocks",
            "action_description": "notify me",
            "original_request": "Create automation: when the front door unlocks, notify me.",
        },
    })
    automation_body = r.json()
    automation_yaml = automation_body.get("data", {}).get("proposed_yaml", "")
    check("automation builder v6 supports notification actions",
          r.status_code == 200
          and "platform: state" in automation_yaml
          and "entity_id: lock.front_door" in automation_yaml
          and "persistent_notification.create" in automation_yaml
          and "notification_id: tpg_homeai_automation" in automation_yaml,
          automation_yaml or str(automation_body))
    r = client.post("/test/action", json={
        "action": "create_simple_automation",
        "assistant": "atlas",
        "user": "shawn",
        "params": {
            "trigger_description": "at 9 PM",
            "action_description": "turn on office fan for 10 minutes",
            "original_request": "Create scheduled task at 9 PM: turn on office fan for 10 minutes.",
        },
    })
    automation_body = r.json()
    automation_yaml = automation_body.get("data", {}).get("proposed_yaml", "")
    check("automation builder v7 supports temporary timed actions",
          r.status_code == 200
          and "platform: time" in automation_yaml
          and "at: '21:00:00'" in automation_yaml
          and "fan.turn_on" in automation_yaml
          and "delay: 00:10:00" in automation_yaml
          and "fan.turn_off" in automation_yaml,
          automation_yaml or str(automation_body))
    r = client.post("/test/action", json={
        "action": "create_simple_automation",
        "assistant": "atlas",
        "user": "shawn",
        "params": {
            "trigger_description": "every 15 minutes",
            "action_description": "notify me",
            "original_request": "Create automation: every 15 minutes notify me.",
        },
    })
    automation_body = r.json()
    automation_yaml = automation_body.get("data", {}).get("proposed_yaml", "")
    check("automation builder v8 supports interval time-pattern triggers",
          r.status_code == 200
          and "platform: time_pattern" in automation_yaml
          and "minutes: /15" in automation_yaml
          and "persistent_notification.create" in automation_yaml
          and "platform: time\n" not in automation_yaml,
          automation_yaml or str(automation_body))
    r = client.post("/test/action", json={
        "action": "create_simple_automation",
        "assistant": "atlas",
        "user": "shawn",
        "params": {
            "trigger_description": "tomorrow at 7 PM",
            "action_description": "turn off all lights",
            "original_request": "Create scheduled task tomorrow at 7 PM turn off all lights.",
        },
    })
    automation_body = r.json()
    automation_yaml = automation_body.get("data", {}).get("proposed_yaml", "")
    check("automation builder v9 supports one-off date conditions",
          r.status_code == 200
          and "platform: time" in automation_yaml
          and "at: '19:00:00'" in automation_yaml
          and "condition: template" in automation_yaml
          and "now().date().isoformat()" in automation_yaml
          and "light.turn_off" in automation_yaml,
          automation_yaml or str(automation_body))
    r = client.post("/test/action", json={
        "action": "create_simple_automation",
        "assistant": "atlas",
        "user": "shawn",
        "params": {
            "trigger_description": "weekdays during summer at 6 PM",
            "action_description": "turn on office light",
            "original_request": "Create schedule weekdays during summer at 6 PM turn on office light.",
        },
    })
    automation_body = r.json()
    automation_yaml = automation_body.get("data", {}).get("proposed_yaml", "")
    check("automation builder v10 supports season-aware schedule conditions",
          r.status_code == 200
          and "platform: time" in automation_yaml
          and "at: '18:00:00'" in automation_yaml
          and "During Summer" in automation_yaml
          and "now().month in [6, 7, 8]" in automation_yaml
          and "Weekdays only" in automation_yaml
          and "light.turn_on" in automation_yaml,
          automation_yaml or str(automation_body))
    r = client.post("/test/action", json={
        "action": "create_simple_automation",
        "assistant": "atlas",
        "user": "shawn",
        "params": {
            "trigger_description": "on Christmas at 6 PM",
            "action_description": "turn on office light",
            "original_request": "Create schedule on Christmas at 6 PM turn on office light.",
        },
    })
    automation_body = r.json()
    automation_yaml = automation_body.get("data", {}).get("proposed_yaml", "")
    check("automation builder v10 supports holiday-aware schedule conditions",
          r.status_code == 200
          and "platform: time" in automation_yaml
          and "at: '18:00:00'" in automation_yaml
          and "On Christmas" in automation_yaml
          and "now().month == 12 and now().day == 25" in automation_yaml
          and "light.turn_on" in automation_yaml,
          automation_yaml or str(automation_body))
    r = client.post("/test/action", json={
        "action": "create_simple_automation",
        "assistant": "atlas",
        "user": "shawn",
        "params": {
            "trigger_description": "when my calendar event starts",
            "action_description": "notify me",
            "original_request": "Create automation when my calendar event starts notify me.",
        },
    })
    automation_body = r.json()
    automation_yaml = automation_body.get("data", {}).get("proposed_yaml", "")
    check("automation builder v11 supports calendar event triggers",
          r.status_code == 200
          and "platform: calendar" in automation_yaml
          and "entity_id: <<< choose calendar entity >>>" in automation_yaml
          and "event: start" in automation_yaml
          and "persistent_notification.create" in automation_yaml
          and "The trigger entity needs mapping" in str(automation_body.get("data", {}).get("warnings", [])),
          automation_yaml or str(automation_body))

    r = client.post("/chat", json={
        "assistant": "chatty",
        "user": "jordie",
        "message": "Build a dashboard for the office with voice controls.",
    })
    check("/chat resident cannot draft dashboards",
          r.status_code == 200
          and r.json().get("success") is False
          and r.json().get("command", {}).get("intent") == "draft_dashboard"
          and r.json().get("command", {}).get("error") == "role_not_allowed",
          str(r.json()))
    check("/chat resident dashboard denial is role policy",
          r.json().get("command", {}).get("data", {}).get("policy", {}).get("decision") == "denied",
          str(r.json()))

    r = client.post("/chat", json={
        "assistant": "atlas",
        "user": "shawn",
        "conversation_id": "verify-notebook-session",
        "message": "Let's brainstorm a cleaner office dashboard layout.",
    })
    check("/chat notebook seed returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")

    r = client.get("/conversations")
    check("/conversations returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/conversations includes seeded session",
          any(c.get("conversation_id") == "verify-notebook-session" for c in r.json().get("conversations", [])),
          str(r.json()))
    r = client.get("/conversations?assistant=atlas&user=shawn")
    check("/conversations filters by assistant and user",
          r.status_code == 200
          and all(c.get("assistant") == "atlas" and c.get("user") == "shawn"
                  for c in r.json().get("conversations", [])),
          str(r.json()))

    r = client.post("/conversations/verify-notebook-session/notes", json={
        "conversation_id": "verify-notebook-session",
        "assistant": "atlas",
        "user": "shawn",
        "title": "Office dashboard",
        "body": "Keep lighting, fan, camera, and music controls together.",
    })
    check("/conversations/{id}/notes creates note",
          r.status_code == 200 and r.json().get("note", {}).get("title") == "Office dashboard",
          r.text)

    r = client.get("/conversations/verify-notebook-session")
    check("/conversations/{id} returns transcript",
          r.status_code == 200 and len(r.json().get("messages", [])) >= 1,
          r.text)
    check("/conversations/{id} includes notes",
          len(r.json().get("notes", [])) >= 1,
          r.text)

    r = client.get("/conversations/verify-notebook-session/export")
    check("/conversations/{id}/export returns markdown JSON",
          r.status_code == 200 and "# " in r.json().get("markdown", ""),
          r.text)
    r = client.delete("/conversations/verify-notebook-session")
    check("/conversations/{id} DELETE soft-archives conversation",
          r.status_code == 200
          and r.json().get("archived") is True
          and r.json().get("conversation_id") == "verify-notebook-session",
          r.text)
    r = client.get("/conversations")
    check("archived conversation is hidden from list",
          r.status_code == 200
          and all(c.get("conversation_id") != "verify-notebook-session" for c in r.json().get("conversations", [])),
          str(r.json()))
    r = client.get("/conversations/verify-notebook-session")
    check("archived conversation detail preserves audit transcript",
          r.status_code == 200 and len(r.json().get("messages", [])) >= 1,
          r.text)

    r = client.post("/research/search", json={"query": "", "max_results": 3})
    check("/research/search returns structured JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/research/search validates query without crashing",
          r.json().get("error") == "Query is required.",
          str(r.json()))

    r = client.get("/debug/last-command")
    check("/debug/last-command returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/debug/last-command has command audit",
          r.json().get("command", {}).get("intent") in {"create_simple_automation", "draft_dashboard", "conversation"},
          str(r.json()))

    r = client.get("/debug/commands?limit=5")
    check("/debug/commands returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/debug/commands includes parsed tool call",
          isinstance(r.json().get("commands", [{}])[0].get("tool_call"), dict),
          str(r.json()))

    r = client.post("/command/preview", json={
        "assistant": "atlas",
        "user": "shawn",
        "message": "turn off office fan",
    })
    check("/command/preview returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    preview = r.json()
    check("/command/preview does not execute", preview.get("executed") is False,
          str(preview))
    check("/command/preview has dry-run data",
          preview.get("data", {}).get("preview", {}).get("dry_run") is True,
          str(preview))
    check("/command/preview safe action policy execute_now",
          preview.get("data", {}).get("policy", {}).get("decision") == "execute_now",
          str(preview))

    r = client.post("/chat/preview", json={
        "assistant": "atlas",
        "user": "shawn",
        "message": "unlock the front door",
    })
    check("/chat/preview returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    body = r.json()
    check("/chat/preview marks confirmation preview",
          body.get("mode") == "preview_confirmation_required",
          str(body))
    check("/chat/preview does not return live token",
          body.get("command", {}).get("confirmation_token") is None,
          str(body))
    check("/chat/preview unlock policy requires confirmation",
          body.get("command", {}).get("data", {}).get("policy", {}).get("decision")
          == "confirmation_required",
          str(body))

    before_preview_drafts = len(client.get("/suggestions").json().get("suggestions", []))
    r = client.post("/command/preview", json={
        "assistant": "atlas",
        "user": "shawn",
        "message": "set a sleep timer on the office TV in 20 minutes",
    })
    check("/command/preview timer returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    after_preview_drafts = len(client.get("/suggestions").json().get("suggestions", []))
    check("/command/preview timer does not create draft",
          before_preview_drafts == after_preview_drafts,
          f"{before_preview_drafts}->{after_preview_drafts}")

    r = client.get("/suggestions")
    check("/suggestions is JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code}")
    suggestions = r.json().get("suggestions", [])
    check("/suggestions includes draft", len(suggestions) >= 1, str(suggestions))
    if suggestions:
        draft_id = suggestions[0]["id"]
        r = client.post(f"/automation/drafts/{draft_id}/approve")
        check("/automation/drafts/{id}/approve works",
              r.status_code == 200 and r.json().get("approved") is True,
              r.text)
        check("/automation/drafts/{id}/approve installs",
              r.json().get("installed") is True,
              r.text)
        check("automations.yaml written",
              os.path.isfile(os.path.join(_HA_CFG, "automations.yaml")))

    # Unknown API route under a known prefix => JSON 404, not HTML.
    r = client.get("/discovery/does-not-exist")
    check("unknown API route is JSON 404", r.status_code == 404 and is_json(r) and not is_html(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    r = client.get("/dashboards/does-not-exist")
    check("unknown dashboard API route is JSON 404",
          r.status_code == 404 and is_json(r) and not is_html(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    r = client.get("/memory/does-not-exist")
    check("unknown memory API route is JSON 404",
          r.status_code == 404 and is_json(r) and not is_html(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    r = client.get("/conversations/does-not-exist/extra")
    check("unknown conversations API route is JSON 404",
          r.status_code == 404 and is_json(r) and not is_html(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")

    print("Frontend routes return HTML")
    r = client.get("/")
    check("GET / is HTML", is_html(r), r.headers.get("content-type", ""))
    r = client.get(f"{ingress}")
    check("GET ingress root is HTML", is_html(r), r.headers.get("content-type", ""))
    r = client.get("/dashboard")
    check("GET /dashboard is HTML", is_html(r))
    r = client.get(f"{ingress}/discovery")
    check("GET ingress discovery route is HTML", is_html(r),
          r.headers.get("content-type", ""))
    r = client.get(f"{ingress}/chat")
    check("GET ingress chat route is HTML", is_html(r),
          r.headers.get("content-type", ""))
    r = client.get(f"{ingress}/notebook")
    check("GET ingress notebook route is HTML", is_html(r),
          r.headers.get("content-type", ""))
    r = client.get(f"{ingress}/suggestions")
    check("GET ingress suggestions route is HTML", is_html(r),
          r.headers.get("content-type", ""))
    r = client.get(f"{ingress}/setup")
    check("GET ingress setup route is HTML", is_html(r),
          r.headers.get("content-type", ""))
    r = client.get(f"{ingress}/profiles")
    check("GET ingress profiles route is HTML", is_html(r),
          r.headers.get("content-type", ""))
    r = client.get(f"{ingress}/memory-center")
    check("GET ingress memory center route is HTML", is_html(r),
          r.headers.get("content-type", ""))
    r = client.get(f"{ingress}/dashboard-builder")
    check("GET ingress dashboard builder route is HTML", is_html(r),
          r.headers.get("content-type", ""))
    r = client.get(f"{ingress}/voice-settings")
    check("GET ingress voice settings route is HTML", is_html(r),
          r.headers.get("content-type", ""))
    r = client.get(f"{ingress}/house-brain")
    check("GET ingress house brain route is HTML", is_html(r),
          r.headers.get("content-type", ""))
    r = client.get(f"{ingress}/voice-sources")
    check("GET ingress voice sources route is HTML", is_html(r),
          r.headers.get("content-type", ""))
    r = client.get(f"{ingress}/ha")
    check("GET ingress HA route is HTML", is_html(r),
          r.headers.get("content-type", ""))
    r = client.get(f"{ingress}/assets/app.js")
    check("GET ingress asset is JS", r.status_code == 200 and is_js(r) and not is_html(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')} body={r.text[:40]}")
    r = client.get(f"{hassio_ingress}/assets/app.js")
    check("GET hassio ingress asset is JS", r.status_code == 200 and is_js(r) and not is_html(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')} body={r.text[:40]}")
    r = client.get("/ha-integration")
    check("GET /ha-integration is HTML", is_html(r))
    r = client.get("/some/unknown/spa/route")
    check("unknown frontend route is HTML", is_html(r))

    print("PART 2/4 — bootstrap + degraded health")
    check("bootstrap marked ready", state.ready is True)
    check("config dir created", os.path.isdir(_CFG))
    check("devices.yaml seeded", os.path.isfile(os.path.join(_CFG, "devices.yaml")),
          "(requires repo ./config template)")
    check("discovered.yaml created", os.path.isfile(os.path.join(_CFG, "discovered.yaml")))
    check("ignored.yaml created", os.path.isfile(os.path.join(_CFG, "ignored.yaml")))

    h = client.get("/health").json()
    check("HA unreachable -> degraded (not crashed)", h["status"] == "degraded",
          str(h.get("reasons")))
    check("openai fallback mode", h["openai"]["mode"] == "fallback_parser")
    check("openai not configured", h["openai"]["configured"] is False)

    print("PART 5 — discovery summary after startup scan")
    s = client.get("/discovery/summary").json()
    check("last_scan_ts populated after scan", s["last_scan_ts"] is not None,
          "scan_on_start should have run")
    check("summary message cleared after scan", s["message"] is None)

    print(f"\n{_PASS} passed, {_FAIL} failed")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
