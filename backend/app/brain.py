"""Jarvis-style brain readiness map.

This module turns the system's current capabilities into a live layer map. It
does not claim the house is magically finished; it shows which brain layers are
usable now, which are partial, and what the next build target is.
"""
from __future__ import annotations

from typing import Any

from .ai.client import get_ai_client
from .config_loader import config_error, get_config
from .db.database import get_session
from .db.models import AcceptanceRun, CommandLog, ConversationState, HouseAsset, MemoryItem, Suggestion
from .discovery import capabilities
from .house_assets import build_spatial_brain
from .house_state import build_mode_brain, build_wake_word_deployment
from .outcomes import build_reliability_summary
from .router.action_policy import CONFIDENCE_REVIEW_THRESHOLD
from .settings import get_settings


def build_brain_layers(graph: dict[str, Any], health: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a seven-layer readiness map for the real-house brain."""
    with get_session() as session:
        command_count = session.query(CommandLog).count()
        conversation_count = session.query(ConversationState).count()
        approved_memories = session.query(MemoryItem).filter(
            MemoryItem.status == "approved"
        ).count()
        pending_suggestions = session.query(Suggestion).filter(
            Suggestion.status.in_(["suggested", "draft", "edited"])
        ).count()
        approved_assets = session.query(HouseAsset).filter(
            HouseAsset.status == "approved"
        ).count()
        draft_assets = session.query(HouseAsset).filter(
            HouseAsset.status == "draft"
        ).count()
        acceptance_runs = session.query(AcceptanceRun).count()
        accepted_tests = (
            session.query(AcceptanceRun)
            .filter(AcceptanceRun.status == "passed")
            .count()
        )
        historical_failed_acceptance = (
            session.query(AcceptanceRun)
            .filter(AcceptanceRun.status.in_(["failed", "blocked"]))
            .count()
        )
        latest_acceptance_rows = session.query(AcceptanceRun).order_by(
            AcceptanceRun.created_at.desc()
        ).limit(100).all()
        acceptance_repairs = (
            session.query(Suggestion)
            .filter(
                Suggestion.category == "acceptance",
                Suggestion.action_type == "acceptance_repair",
                Suggestion.status.in_(["suggested", "draft", "edited"]),
            )
            .count()
        )
        resolved_acceptance_repairs = (
            session.query(Suggestion)
            .filter(
                Suggestion.category == "acceptance",
                Suggestion.action_type == "acceptance_repair",
                Suggestion.status == "resolved",
            )
            .count()
        )

    settings = get_settings()
    ai = get_ai_client()
    providers = ai.provider_status()
    counts = graph.get("counts", {})
    physical = graph.get("physical_devices", [])
    voice_sources = graph.get("voice_sources", [])
    pending = int(graph.get("pending_approvals") or 0)
    unavailable = int(graph.get("unavailable_devices") or 0)
    controllable = _controllable_count(graph)
    diagnostic = _diagnostic_count(graph)
    config = get_config()
    mode_brain = build_mode_brain(config)
    wake_word = build_wake_word_deployment(config)
    spatial_brain = build_spatial_brain()
    reliability = build_reliability_summary(limit=250)
    music_counts = _music_counts(config)
    media_counts = _media_counts(config, graph)
    security_counts = _security_counts(config)
    occupancy_counts = _occupancy_counts(config)
    environment_counts = {
        "weather": _domain_count(graph, "weather"),
        "environment_sensors": _keyword_entity_count(
            graph,
            ("temperature", "humidity", "illuminance", "air quality", "co2", "uv", "rain", "wind"),
        ),
    }
    calendar_counts = {
        "calendars": _domain_count(graph, "calendar"),
        "todos": _domain_count(graph, "todo"),
    }
    presence_counts = {
        "people": _domain_count(graph, "person") + _domain_count(graph, "device_tracker"),
        "personal_devices": len(config.devices.personal_devices),
        "zones": _domain_count(graph, "zone"),
    }
    maintenance_counts = {
        "updates": _domain_count(graph, "update"),
        "backup_entities": _keyword_entity_count(graph, ("backup",)),
        "unavailable": unavailable,
    }
    routine_counts = {
        "locks": security_counts["locks"],
        "covers": _domain_count(graph, "cover"),
        "lights": _domain_count(graph, "light"),
        "climate": _domain_count(graph, "climate"),
        "media_players": media_counts["media_players"],
        "modes": len(config.devices.modes),
    }
    ops_counts = {
        "ha_configured": settings.ha_configured,
        "openai_configured": settings.openai_configured,
        "security_pin": bool(settings.security_pin),
        "voice_source_ids": sum(
            1 for source in config.devices.voice_sources
            if source.source_device_id or source.source_entity_id
        ),
        "rooms": len(config.devices.rooms),
        "music_assistant_routes": sum(
            1 for speaker in config.devices.speakers if speaker.music_assistant_entity_id
        ),
        "weather": _domain_count(graph, "weather"),
        "pending": pending,
    }
    governance_counts = {
        "users": len(config.assistants.users),
        "admins": sum(1 for user in config.assistants.users if user.role == "admin"),
        "non_admins": sum(1 for user in config.assistants.users if user.role != "admin"),
        "ha_synced": sum(1 for user in config.assistants.users if user.access_source == "home_assistant"),
        "assistants": len(config.assistants.assistants),
        "approved_memories": approved_memories,
    }
    latest_acceptance_by_test: dict[str, AcceptanceRun] = {}
    for row in latest_acceptance_rows:
        if row.test_id and row.test_id not in latest_acceptance_by_test:
            latest_acceptance_by_test[row.test_id] = row
    failed_acceptance = sum(
        1 for row in latest_acceptance_by_test.values()
        if row.status in {"failed", "blocked"}
    )
    acceptance_counts = {
        "command_count": command_count,
        "conversation_count": conversation_count,
        "voice_sources": len(config.devices.voice_sources),
        "voice_source_ids": ops_counts["voice_source_ids"],
        "core_domains": sum(
            1 for domain in ("light", "fan", "lock", "climate", "media_player", "camera", "weather")
            if _domain_count(graph, domain)
        ),
        "live_acceptance_domains": sum(
            1 for domain in ("light", "fan", "lock", "climate", "media_player", "camera")
            if _domain_count(graph, domain)
        ),
        "acceptance_runs": acceptance_runs,
        "accepted_tests": accepted_tests,
        "failed_acceptance": failed_acceptance,
        "historical_failed_acceptance": historical_failed_acceptance,
        "acceptance_repairs": acceptance_repairs,
        "resolved_acceptance_repairs": resolved_acceptance_repairs,
    }
    room_context_ready = counts.get("rooms", 0) > 0 and bool(voice_sources)
    security_ready = bool(settings.security_pin)
    capability_ready = controllable > 0 and pending == 0
    conversation_ready = bool(conversation_count or command_count)
    voice_ready = bool(settings.openai_configured)
    wake_ready = bool(wake_word.get("counts", {}).get("ready", 0))
    mode_ready = bool(mode_brain.get("configured_modes"))
    ai_ready = bool(ai.using_openai)

    layers = [
        {
            "id": "policy_brain",
            "title": "Intent Confidence + Policy Brain",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Backend returns data.policy for command and preview responses.",
                f"Confidence review threshold is {CONFIDENCE_REVIEW_THRESHOLD:.2f}.",
                "Security/access actions remain confirmation-gated.",
            ],
            "next": "Add per-user risk preferences and PIN-backed unlock confirmation.",
        },
        {
            "id": "room_context",
            "title": "Room-Aware Voice Context",
            "status": "ready" if room_context_ready else "partial",
            "score": 100 if room_context_ready else 64,
            "evidence": [
                "Commands accept room, source_device_id, and source_entity_id context.",
                "Router applies room context to generic targets like light, fan, TV, and speaker.",
                f"{counts.get('rooms', 0)} configured rooms available for context resolution.",
                f"{len(voice_sources)} configured voice source profiles available.",
            ],
            "next": "Bind real HA Assist satellite device IDs as they are installed.",
        },
        {
            "id": "security_identity",
            "title": "PIN + User Identity Security",
            "status": "ready" if security_ready else "partial",
            "score": 100 if security_ready else 70,
            "evidence": [
                "Critical confirmations can require a configured security PIN.",
                "User permission checks still run before confirmation tokens are created.",
                f"Security PIN configured: {bool(settings.security_pin)}.",
                f"{len(mode_brain.get('source_policy', []))} voice source trust policies generated.",
            ],
            "next": "Add per-user location/trusted-device scoring for outside voice requests.",
        },
        {
            "id": "capability_graph",
            "title": "Real Device Capability Graph",
            "status": "ready" if capability_ready else "partial",
            "score": 100 if capability_ready else (75 if controllable else 55),
            "evidence": [
                f"{len(capabilities.DOMAIN_CAPABILITIES)} HA domains mapped.",
                f"{controllable} controllable entities and {diagnostic} diagnostic entities seen.",
                f"{len(physical)} physical device groups built from HA registries/entities.",
                f"{pending} pending approvals and {unavailable} unavailable entities.",
            ],
            "next": "Use HA device registry IDs to merge every phone/TV/fan into physical device cards.",
        },
        {
            "id": "reliability_brain",
            "title": "Reliability Brain + Device Intelligence",
            "status": "ready" if reliability.get("grade") != "needs_attention" else "partial",
            "score": int(round(float(reliability.get("score", 1.0)) * 100)),
            "evidence": [
                "Executed actions are followed by Home Assistant state/attribute verification.",
                "Fan speed, media playback, volume, climate temperature, vacuums, helpers, humidifiers, water heaters, valves, locks, lights, switches, and generic service plans have grounded outcome checks.",
                "Device profiles include reliability score, last outcome, service strategy, and common failure hints.",
                "Approved repair suggestions can teach device-specific fan, media-player, cover, climate, vacuum, helper, humidifier, water-heater, and valve service strategies.",
                "Generic media-player control can use learned media_play/media_stop wake or sleep fallbacks when native power services fail.",
                f"{reliability.get('checked_commands', 0)} recent command outcomes checked.",
                f"{reliability.get('open_repair_suggestions', 0)} open repair suggestions from failed verification.",
            ],
            "next": "Add vendor-specific deep integrations for Music Assistant, Frigate/Nest cameras, Apple/iCloud, and robot-vacuum maps.",
        },
        {
            "id": "conversation_memory",
            "title": "Conversational Memory + Corrections",
            "status": "ready" if conversation_ready else "partial",
            "score": 100 if conversation_ready else 60,
            "evidence": [
                f"{conversation_count} active short-term conversation contexts.",
                f"{command_count} audited commands available for explanations.",
                f"{approved_memories} approved long-term memories.",
            ],
            "next": "Automatically draft memory from repeated corrections and user preferences.",
        },
        {
            "id": "conversation_notebook",
            "title": "Conversation Notebook + Research",
            "status": "ready",
            "score": 100,
            "evidence": [
                "General chat sessions are persisted through the command audit log.",
                "Notebook UI can browse past conversations and attach session notes.",
                "Conversation transcripts export as Markdown for ChatGPT, docs, or sharing.",
                "Read-only web search is available for current/research questions and can feed general chat context.",
            ],
            "next": "Add uploaded file/floor-plan workspace with approval-first extraction into house context.",
        },
        {
            "id": "house_knowledge_assets",
            "title": "House Knowledge Assets",
            "status": "ready" if approved_assets else "partial",
            "score": 100 if approved_assets else (80 if draft_assets else 60),
            "evidence": [
                "Floor plans, blueprints, room photos, and house notes can be uploaded into a managed asset library.",
                "Draft assets are analyzed and reviewed before they become active AI context.",
                f"{approved_assets} approved house knowledge assets and {draft_assets} drafts.",
                "Approved assets are injected into general chat context for dashboard, room, zone, and floor-plan requests.",
            ],
            "next": "Upload and approve the real house floor plan, room photos, and tablet/dashboard layout notes.",
        },
        {
            "id": "house_spatial_brain",
            "title": "House Spatial Brain",
            "status": "ready" if spatial_brain.get("summary", {}).get("rooms_with_assets") else "partial",
            "score": 100 if spatial_brain.get("summary", {}).get("rooms_with_assets") else 62,
            "evidence": [
                "Approved floor plans, blueprints, room photos, and notes are grouped by room.",
                f"{spatial_brain.get('summary', {}).get('rooms_with_assets', 0)} rooms have approved spatial assets.",
                f"{spatial_brain.get('summary', {}).get('uncovered_rooms', 0)} configured rooms still need spatial context.",
                "Dashboard drafts include AI Layout Notes from approved spatial assets.",
                "Spatial brain exposes dashboard hints, automation ideas, and mapping questions.",
            ],
            "next": "Approve real room photos/floor plans until every active room has spatial context.",
        },
        {
            "id": "voice_layer",
            "title": "Voice Layer",
            "status": "ready" if voice_ready else "partial",
            "score": 100 if voice_ready else 78,
            "evidence": [
                "Browser mic input is available in Chat.",
                "Assistants own wake-word identity; Voice Sources deploy that assistant into rooms.",
                "Configured assistant voice profiles can use OpenAI TTS with browser fallback.",
                "Reply routing can target browser, quiet mode, explicit media player, or room speaker.",
                "Assistant profiles expose voice selection, OpenAI TTS readiness, catalog, preview, and test playback.",
                "Home Assistant Assist can forward conversation to TPG HomeAI.",
                f"OpenAI TTS configured: {settings.openai_configured}.",
            ],
            "next": "Install HA Assist satellites and paste their real source IDs into voice_sources.",
        },
        {
            "id": "wake_word_deployment",
            "title": "Wake Word Deployment",
            "status": "ready" if wake_ready else "partial",
            "score": 100 if wake_ready else 66,
            "evidence": [
                f"{wake_word.get('counts', {}).get('assistants_with_wake_words', 0)}/{wake_word.get('counts', {}).get('assistants', 0)} assistants have wake words configured.",
                f"{wake_word.get('counts', {}).get('assistants_with_linked_sources', 0)}/{wake_word.get('counts', {}).get('assistants', 0)} assistants are linked to real voice sources.",
                f"{wake_word.get('counts', {}).get('total', 0)} voice source profiles configured.",
                f"{wake_word.get('counts', {}).get('ready', 0)} voice sources ready for room-aware routing.",
                f"{wake_word.get('counts', {}).get('missing_source_identity', 0)} sources still need source_device_id/source_entity_id.",
                f"{wake_word.get('counts', {}).get('rooms_without_voice_source', 0)} rooms still need satellites/panels.",
            ],
            "next": "Bind each physical mic/panel/satellite to its HA source identity.",
        },
        {
            "id": "proactive_suggestions",
            "title": "Proactive Suggestions + Approval Inbox",
            "status": "ready",
            "score": 100,
            "evidence": [
                f"{pending_suggestions} active proactive suggestions or drafts.",
                "Suggestion generation, approve, ignore, and automation install endpoints exist.",
                "Security, discovery, maintenance, dashboard, and sleep-timer proposals are approval-first.",
            ],
            "next": "Add schedule mining from command history for time-of-day suggestions.",
        },
        {
            "id": "automation_builder_v11",
            "title": "Automation Builder v11",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Residents can draft scheduled tasks and automations without dashboard/system permissions.",
                "Drafts can include multiple safe actions in one request.",
                "Time, delay, sunset, sunrise, and presence conditions are converted into HA-style YAML.",
                "State triggers and numeric sensor thresholds can be drafted from natural language.",
                "Time windows and entity state guard conditions can be added from plain speech.",
                "Notification actions and timed temporary actions can be composed from normal language.",
                "Interval time-pattern triggers can be drafted from phrases like 'every 15 minutes'.",
                "One-off dates like tomorrow, next Monday, June 30, or 6/30 become dated HA template conditions.",
                "Holiday and season-aware conditions can be drafted for requests like 'on Christmas' or 'during summer'.",
                "Calendar event triggers can be drafted for requests like 'when my calendar event starts'.",
                "Automation drafts remain approval-first before being installed into Home Assistant.",
            ],
            "next": "Add calendar entity discovery/mapping helpers and generated cleanup reminders.",
        },
        {
            "id": "music_assistant_deep",
            "title": "Music Assistant Deep Integration",
            "status": "ready" if music_counts["accounts"] and music_counts["music_assistant_speakers"] else "partial",
            "score": 100 if music_counts["accounts"] and music_counts["music_assistant_speakers"] else 78,
            "evidence": [
                f"{music_counts['accounts']} music account(s) configured.",
                f"{music_counts['music_assistant_speakers']} speaker(s) mapped to Music Assistant players.",
                "Playback resolves assistant owner -> music account -> room speaker -> Music Assistant search/playback.",
                "Per-user music account boundaries remain enforced.",
            ],
            "next": "Add live Music Assistant library browsing, queue management, and playlist picker UI.",
        },
        {
            "id": "media_display_control",
            "title": "Media + TV Display Control",
            "status": "ready" if media_counts["media_players"] or media_counts["displays"] else "partial",
            "score": 100 if media_counts["media_players"] or media_counts["displays"] else 70,
            "evidence": [
                f"{media_counts['media_players']} media_player entities observed or configured.",
                f"{media_counts['displays']} display route(s) configured.",
                f"{media_counts['speakers']} speaker route(s) configured.",
                "Media control brain tracks source, app, volume, title, display routes, and sleep-timer candidates.",
            ],
            "next": "Add app launching/source switching helpers and direct TV brightness/display-control adapters.",
        },
        {
            "id": "camera_security_intelligence",
            "title": "Camera Intelligence + Security Briefing",
            "status": "ready" if security_counts["cameras"] or security_counts["locks"] else "partial",
            "score": 100 if security_counts["cameras"] or security_counts["locks"] else 68,
            "evidence": [
                f"{security_counts['cameras']} camera(s), {security_counts['locks']} lock(s), and {security_counts['security_sensors']} security sensor(s) configured.",
                "Security briefing combines locks, camera availability, motion/person/package/vehicle-style event sensors, and security sensors.",
                "Live attention counts are exposed through /security/briefing and /brain/house-state.",
            ],
            "next": "Add Frigate/Nest event detail APIs with thumbnails, clips, and last-event timelines.",
        },
        {
            "id": "room_occupancy_brain",
            "title": "Room Occupancy Brain",
            "status": "ready" if occupancy_counts["rooms"] else "partial",
            "score": 100 if occupancy_counts["rooms"] else 65,
            "evidence": [
                f"{occupancy_counts['rooms']} room(s) available for occupancy likelihood scoring.",
                f"{occupancy_counts['with_voice_source']} room(s) have voice-source context.",
                "Occupancy uses motion-style sensors, media state, lights, fans, and voice source mappings as signals.",
            ],
            "next": "Add room-level confidence memory and proactive mode changes based on repeated occupancy patterns.",
        },
        {
            "id": "environment_weather_brain",
            "title": "Environment + Weather Brain",
            "status": "ready" if environment_counts["weather"] or environment_counts["environment_sensors"] else "partial",
            "score": 100 if environment_counts["weather"] or environment_counts["environment_sensors"] else 70,
            "evidence": [
                f"{environment_counts['weather']} weather entity/entities visible.",
                f"{environment_counts['environment_sensors']} environment sensor(s) identified by name/domain hints.",
                "Daily briefings can summarize weather, temperature, humidity, light, air-quality, wind, UV, and rain signals.",
            ],
            "next": "Add/approve local outdoor weather and indoor comfort sensors for richer comfort decisions.",
        },
        {
            "id": "calendar_todo_brain",
            "title": "Calendar + Todo Awareness",
            "status": "ready" if calendar_counts["calendars"] or calendar_counts["todos"] else "partial",
            "score": 100 if calendar_counts["calendars"] or calendar_counts["todos"] else 70,
            "evidence": [
                f"{calendar_counts['calendars']} calendar entity/entities visible.",
                f"{calendar_counts['todos']} todo entity/entities visible.",
                "Jarvis can expose calendar/todo readiness for briefings and approved automation drafting.",
            ],
            "next": "Map real calendars and household todo lists so briefings include upcoming obligations.",
        },
        {
            "id": "presence_zone_brain",
            "title": "Presence + Zone Intelligence",
            "status": "ready" if presence_counts["people"] or presence_counts["personal_devices"] else "partial",
            "score": 100 if presence_counts["people"] or presence_counts["personal_devices"] else 70,
            "evidence": [
                f"{presence_counts['people']} person/device-tracker entity/entities visible.",
                f"{presence_counts['personal_devices']} configured personal device mapping(s).",
                f"{presence_counts['zones']} HA zone entity/entities visible.",
                "Presence stays advisory and feeds modes/recommendations without bypassing security policy.",
            ],
            "next": "Approve personal device ownership and zone mappings for stronger identity and home/away context.",
        },
        {
            "id": "maintenance_health_brain",
            "title": "Maintenance + Health Brain",
            "status": "ready",
            "score": 100,
            "evidence": [
                f"{maintenance_counts['unavailable']} unavailable entities currently tracked by the graph.",
                f"{maintenance_counts['updates']} update entity/entities visible.",
                f"{maintenance_counts['backup_entities']} backup-related entity/entities visible.",
                "Maintenance brain can surface unavailable devices, low batteries, updates, and backup health into briefings.",
            ],
            "next": "Add integration-specific health adapters for backups, Frigate, Music Assistant, and network gear.",
        },
        {
            "id": "daily_briefing_brain",
            "title": "Daily Briefing Composer",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Daily briefing endpoint composes environment, schedule, presence, and maintenance into a spoken/readable summary.",
                "Briefings are read-only and can be routed through chat/voice without silently creating automations.",
                "The endpoint returns source brains for UI drill-down and debugging.",
            ],
            "next": "Add user-specific briefing preferences, quiet-hour delivery windows, and approved scheduled briefing routines.",
        },
        {
            "id": "security_routine_advisor",
            "title": "Security Routine Advisor",
            "status": "ready" if routine_counts["locks"] or routine_counts["covers"] else "partial",
            "score": 100 if routine_counts["locks"] or routine_counts["covers"] else 75,
            "evidence": [
                f"{routine_counts['locks']} lock(s) and {routine_counts['covers']} cover(s) available for security routines.",
                "Advisor drafts secure-house, arrival-check, and night-lockup routine templates.",
                "Security-disabling actions remain confirmation/PIN gated.",
            ],
            "next": "Connect alarm panels, Frigate/Nest event detail, and trusted-source policies to richer security routines.",
        },
        {
            "id": "comfort_energy_optimizer",
            "title": "Comfort + Energy Optimizer",
            "status": "ready",
            "score": 100,
            "evidence": [
                f"{routine_counts['lights']} light(s) and {routine_counts['climate']} climate device(s) visible/configured.",
                "Optimizer combines lights, fans, climate, helpers, presence, and environment signals into reviewable suggestions.",
                "Energy/comfort changes remain proposal-first unless routed through a guarded user command.",
            ],
            "next": "Add learned user comfort bands by room and season.",
        },
        {
            "id": "media_scene_advisor",
            "title": "Media Scene Advisor",
            "status": "ready" if routine_counts["media_players"] else "partial",
            "score": 100 if routine_counts["media_players"] else 78,
            "evidence": [
                f"{routine_counts['media_players']} media player route(s) available.",
                "Scene advisor drafts movie mode, focus mode, and music-everywhere style plans.",
                "Music scenes preserve assistant-owner music account boundaries.",
            ],
            "next": "Add live source/app launch adapters for TVs and streaming boxes.",
        },
        {
            "id": "sleep_wake_routine_brain",
            "title": "Sleep + Wake Routine Brain",
            "status": "ready",
            "score": 100,
            "evidence": [
                f"{routine_counts['modes']} configured house mode(s) available for quiet/sleep behavior.",
                "Sleep/wake brain exposes sleep timer, bedtime shutdown, and morning wakeup templates.",
                "Future changes remain automation drafts and avoid unlocking/opening security devices automatically.",
            ],
            "next": "Add per-user bedtime/wake preferences and room-specific wake scenes.",
        },
        {
            "id": "proactive_action_plan",
            "title": "Proactive Action Plan",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Action plan combines security, comfort/energy, media scenes, sleep/wake, and maintenance into approval-first proposals.",
                "The plan explicitly marks auto_execute false so Jarvis suggests before changing the house.",
                "House State includes the plan for dashboard and chat drill-down.",
            ],
            "next": "Let owners turn selected proposal types into scheduled monitor notifications.",
        },
        {
            "id": "capability_gap_scanner",
            "title": "Capability Gap Scanner",
            "status": "ready" if ops_counts["ha_configured"] and ops_counts["openai_configured"] else "partial",
            "score": 100 if ops_counts["ha_configured"] and ops_counts["openai_configured"] else 76,
            "evidence": [
                "Ops endpoints expose missing setup gates before users hit broken behavior.",
                f"HA configured: {ops_counts['ha_configured']}. OpenAI configured: {ops_counts['openai_configured']}.",
                f"{ops_counts['pending']} pending discovery approval(s) remain.",
                "Gaps include HA, OpenAI, security PIN, voice sources, wake words, rooms, music, weather, and house assets.",
            ],
            "next": "Use /ops/capability-gaps in setup UI to guide owners through remaining deployment blockers.",
        },
        {
            "id": "onboarding_wizard",
            "title": "Onboarding Wizard Planner",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Onboarding plan is generated from current capability gaps.",
                "Required steps cover HA connection, user sync, discovery, rooms, security, voice, and acceptance tests.",
                "Recommended steps cover Music Assistant and spatial house assets.",
            ],
            "next": "Render the onboarding plan as an owner setup checklist with direct links to each config page.",
        },
        {
            "id": "diagnostics_support_pack",
            "title": "Diagnostics Support Pack",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Diagnostics endpoint returns versions, degraded reasons, safe settings, counts, and key routes.",
                "Secrets are masked through settings.safe_dict().",
                "Support packs can explain issues without exposing tokens or API keys.",
            ],
            "next": "Add one-click copy/download from the admin setup page.",
        },
        {
            "id": "backup_recovery_readiness",
            "title": "Backup + Recovery Readiness",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Automation installs already create timestamped automations.yaml backups.",
                "Ops endpoint reports HA config root, automations path, database URL, config dir, and backup-related entities.",
                "Recommendations explain when to run HA backups before major generated changes.",
            ],
            "next": "Add a pre-install backup reminder before large automation/dashboard installs.",
        },
        {
            "id": "integration_matrix",
            "title": "Integration Readiness Matrix",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Matrix reports readiness for HA, OpenAI, Ollama, Music Assistant, Browser Mod, Frigate, Nest, Tailscale, Apple/iCloud, and Nabu Casa.",
                f"{ops_counts['music_assistant_routes']} Music Assistant speaker route(s), {ops_counts['voice_source_ids']} source identity mapping(s), and {ops_counts['weather']} weather entity/entities are visible.",
                "The matrix is best-effort and uses only safe config/state hints.",
            ],
            "next": "Promote matrix issues into setup suggestions when an expected integration is missing.",
        },
        {
            "id": "privacy_data_controls",
            "title": "Privacy + Data Controls",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Privacy endpoint explains command logs, notes, memories, suggestions, and house assets.",
                "Conversation delete is soft-archive, preserving audit history.",
                "Diagnostics and context exports are marked secrets_redacted.",
                "Security actions remain confirmation/PIN gated.",
            ],
            "next": "Add owner-selectable retention settings after v1 stabilizes.",
        },
        {
            "id": "role_permission_matrix",
            "title": "Role + Permission Matrix",
            "status": "ready" if governance_counts["users"] and governance_counts["admins"] else "partial",
            "score": 100 if governance_counts["users"] and governance_counts["admins"] else 74,
            "evidence": [
                f"{governance_counts['users']} user profile(s), {governance_counts['admins']} admin/owner profile(s), and {governance_counts['non_admins']} non-admin profile(s) configured.",
                f"{governance_counts['ha_synced']} profile(s) synced from Home Assistant.",
                "Residents can use general AI and draft schedules without dashboard/system management rights.",
                "Admins/owners can manage all Jarvis and HA configuration surfaces.",
            ],
            "next": "Add UI badges showing exactly why each menu item is visible or hidden for the current user.",
        },
        {
            "id": "role_acceptance_matrix",
            "title": "Role Acceptance Matrix",
            "status": "ready" if governance_counts["admins"] and governance_counts["non_admins"] else "partial",
            "score": 100 if governance_counts["admins"] and governance_counts["non_admins"] else 78,
            "evidence": [
                "Role acceptance defines owner/admin, resident, kiosk/shared, and guest boundaries.",
                "Residents can chat, control allowed devices, and create scheduled tasks without dashboard/system access.",
                "Kiosk/shared profiles use the shared Jarvis profile for room remotes and wall panels.",
                f"{governance_counts['admins']} admin/owner profile(s) and {governance_counts['non_admins']} non-admin profile(s) are available for real-login validation.",
            ],
            "next": "Run owner, resident, and kiosk acceptance checks from real Home Assistant logins.",
        },
        {
            "id": "memory_quality_recall",
            "title": "Memory Quality + Recall",
            "status": "ready" if governance_counts["approved_memories"] else "partial",
            "score": 100 if governance_counts["approved_memories"] else 78,
            "evidence": [
                f"{governance_counts['approved_memories']} approved long-term memory item(s).",
                "Memory quality endpoint reports approved/draft/ignored counts, duplicate keys, and correction-like command signals.",
                "Memory stays approval-first so repeated corrections do not silently become permanent facts.",
            ],
            "next": "Review draft memories until each profile has useful, approved preferences.",
        },
        {
            "id": "redacted_context_export",
            "title": "Redacted Context Export",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Context export endpoint returns JSON payload and Markdown summary.",
                "Export includes rooms, users, assistants, privacy counts, memory quality, and approved house assets.",
                "Secrets are redacted and export is safe for ChatGPT/support handoff.",
            ],
            "next": "Add UI download buttons for JSON and Markdown context packs.",
        },
        {
            "id": "completion_auditor",
            "title": "Completion Readiness Auditor",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Completion audit combines v1 gates, privacy controls, roles, memory quality, and blockers.",
                "Stop-line text explains when feature work should pause and house-specific setup begins.",
                "Auditor is exposed as /governance/completion-audit and /brain/phase-87-91.",
            ],
            "next": "Keep adding only blockers and bug fixes once the completion audit is clean.",
        },
        {
            "id": "interaction_quality_report",
            "title": "Interaction Quality Report",
            "status": "ready" if acceptance_counts["command_count"] else "partial",
            "score": 100 if acceptance_counts["command_count"] else 75,
            "evidence": [
                f"{acceptance_counts['command_count']} command/audit row(s) and {acceptance_counts['conversation_count']} conversation context(s) available for quality scoring.",
                "Experience endpoint tracks successes, failures, confusion phrases, top intents, and recommendations.",
                "Recent failures can be used to drive reliability repairs and memory approvals.",
            ],
            "next": "Run a full owner/resident/kiosk acceptance chat pass after each release.",
        },
        {
            "id": "voice_acceptance_plan",
            "title": "Voice Acceptance Plan",
            "status": "ready" if acceptance_counts["voice_source_ids"] else "partial",
            "score": 100 if acceptance_counts["voice_source_ids"] else 70,
            "evidence": [
                f"{acceptance_counts['voice_sources']} voice source profile(s) and {acceptance_counts['voice_source_ids']} real source identity mapping(s).",
                "Acceptance plan covers browser mic, assistant TTS, wake words, room context, and security voice flows.",
                "Voice blockers are listed explicitly instead of buried in setup pages.",
            ],
            "next": "Verify mic/TTS/wake-word behavior from actual iPad/iPhone/panel devices over HTTPS.",
        },
        {
            "id": "device_acceptance_matrix",
            "title": "Device Acceptance Matrix",
            "status": "ready" if acceptance_counts["core_domains"] >= 5 else "partial",
            "score": 100 if acceptance_counts["core_domains"] >= 5 else 72,
            "evidence": [
                f"{acceptance_counts['core_domains']} core HA domain(s) are visible for acceptance testing.",
                "Device matrix defines tests for lights, fans, locks, covers, climate, media players, cameras, calendar, and weather.",
                "Role acceptance checks verify admin, resident, and kiosk/shared behavior.",
            ],
            "next": "Use the matrix as the live-house regression checklist before declaring v1 complete.",
        },
        {
            "id": "live_acceptance_runner",
            "title": "Live HA Acceptance Runner",
            "status": "ready" if acceptance_counts["live_acceptance_domains"] >= 4 else "partial",
            "score": 100 if acceptance_counts["live_acceptance_domains"] >= 4 else 78,
            "evidence": [
                f"{acceptance_counts['live_acceptance_domains']} live mutating-domain(s) are visible for human-run acceptance checks.",
                "Live acceptance endpoint builds read-only probes and dry-run-required tests from HA state.",
                "The runner explicitly sets read_only=true and executes_actions=false so release checks never toggle real devices.",
            ],
            "next": "Run /experience/live-acceptance from the real house and work through its blockers before calling the deployment complete.",
        },
        {
            "id": "acceptance_evidence_journal",
            "title": "Acceptance Evidence Journal",
            "status": "ready" if acceptance_counts["acceptance_runs"] else "partial",
            "score": 100 if acceptance_counts["acceptance_runs"] else 76,
            "evidence": [
                f"{acceptance_counts['acceptance_runs']} acceptance result(s) recorded.",
                f"{acceptance_counts['accepted_tests']} acceptance result(s) marked passed.",
                "Evidence rows preserve test id, status, assistant, user, notes, structured evidence, and version.",
            ],
            "next": "Record pass/fail/blocked evidence for each live acceptance test after running it in the real house.",
        },
        {
            "id": "acceptance_release_report",
            "title": "Acceptance Release Report",
            "status": "ready" if acceptance_counts["acceptance_runs"] else "partial",
            "score": 100 if acceptance_counts["acceptance_runs"] else 78,
            "evidence": [
                "Live acceptance report endpoint exports structured JSON and Markdown.",
                f"{acceptance_counts['acceptance_runs']} acceptance result(s) are available for reporting.",
                f"{acceptance_counts['accepted_tests']} passed and {acceptance_counts['failed_acceptance']} failed/blocked result(s) recorded.",
            ],
            "next": "Use the report as the owner-facing proof that the live house is or is not deployment-complete.",
        },
        {
            "id": "acceptance_repair_loop",
            "title": "Acceptance Repair Loop",
            "status": "ready" if not acceptance_counts["failed_acceptance"] or acceptance_counts["acceptance_repairs"] else "partial",
            "score": 100 if not acceptance_counts["failed_acceptance"] else (90 if acceptance_counts["acceptance_repairs"] else 72),
            "evidence": [
                f"{acceptance_counts['failed_acceptance']} failed or blocked acceptance result(s) recorded.",
                f"{acceptance_counts['acceptance_repairs']} active acceptance repair suggestion(s).",
                "Monitor Scan drafts high-priority repair suggestions for latest failed or blocked acceptance checks.",
                "Later passed evidence clears the failure state because the queue evaluates the newest result per test.",
            ],
            "next": "Resolve repair suggestions, rerun the real-house test, and record a passed acceptance result.",
        },
        {
            "id": "acceptance_resolution_loop",
            "title": "Acceptance Resolution Loop",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Recording passed acceptance evidence resolves matching active acceptance repair suggestions.",
                f"{acceptance_counts['resolved_acceptance_repairs']} acceptance repair suggestion(s) have been resolved.",
                "Resolved suggestions keep the audit trail but disappear from active repair queues.",
                "If the same test fails again later, Monitor Scan can open a fresh repair item.",
            ],
            "next": "Use pass/fail evidence after every real-house acceptance run to keep the repair queue accurate.",
        },
        {
            "id": "combined_acceptance_packet",
            "title": "Combined Acceptance Packet",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Live acceptance report exports test evidence, role acceptance, repair queue, and resolution status together.",
                "Markdown export includes role checks, active/unrepaired blockers, and resolved repair counts.",
                "Phase 106 exposes a compact acceptance_packet payload for release handoff.",
            ],
            "next": "Use the combined packet as the single owner-facing release evidence artifact.",
        },
        {
            "id": "acceptance_packet_ui",
            "title": "Acceptance Packet UI",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Brain Live Acceptance panel displays role acceptance score, active repairs, unrepaired blockers, and resolved repair count.",
                "Owners can copy or download the expanded Markdown acceptance packet from the same panel.",
                "Unrepaired acceptance blockers are highlighted inline before release handoff.",
            ],
            "next": "Add owner filters for required versus optional acceptance checks if the checklist grows too large.",
        },
        {
            "id": "acceptance_triage_filters",
            "title": "Acceptance Triage Filters",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Brain Live Acceptance defaults to an attention-first triage view.",
                "Owners can filter checks by missing evidence, passed evidence, role boundary, dry-run work, or read-only probes.",
                "The filtered view keeps acceptance record buttons, copy report, and Markdown download available.",
            ],
            "next": "Persist the owner's last triage filter if the acceptance workflow becomes a daily operational tool.",
        },
        {
            "id": "release_checklist",
            "title": "Release Checklist",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Release checklist combines version metadata, HA/OpenAI/security readiness, voice acceptance, device acceptance, and interaction quality.",
                "Checklist returns blockers and a clear ship rule.",
                "This makes each GitHub release explainable instead of vibes-based.",
            ],
            "next": "Surface release blockers in the owner setup dashboard.",
        },
        {
            "id": "setup_release_blockers",
            "title": "Setup Release Blockers",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Setup page displays failed release gates and live-house blockers together.",
                "Each blocker links to the management area most likely to clear it.",
                "The panel uses the same formal release checklist as the release API.",
            ],
            "next": "Add one-click owner runbook steps for clearing each blocker when the workflow stabilizes.",
        },
        {
            "id": "setup_owner_runbook",
            "title": "Setup Owner Runbook",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Setup page renders the operational runbook directly under release blockers.",
                "The panel reuses the release runbook API instead of duplicating instructions in the frontend.",
                "Owners see update, acceptance, failure recovery, and feature-freeze steps before calling the house complete.",
            ],
            "next": "Connect each runbook section to diagnostics and acceptance evidence shortcuts.",
        },
        {
            "id": "setup_support_diagnostics",
            "title": "Setup Support Diagnostics",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Setup page displays the redacted diagnostics support pack.",
                "Owners can copy a support-safe JSON snapshot without exposing secrets.",
                "Diagnostics show mode, status, visible HA state count, pending discovery count, config errors, and degraded reasons.",
            ],
            "next": "Add downloadable diagnostics bundles if support handoff needs attached files.",
        },
        {
            "id": "setup_backup_recovery",
            "title": "Setup Backup Recovery",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Setup page displays backup and recovery readiness from the operations brain.",
                "Owners can see Home Assistant config/database paths, automations.yaml, and timestamped backup pattern.",
                "Recovery recommendations are shown before generated automations or device mappings are installed.",
            ],
            "next": "Add downloadable recovery notes if support handoff needs a one-file bundle.",
        },
        {
            "id": "setup_integration_matrix",
            "title": "Setup Integration Matrix",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Setup page displays the operations integration readiness matrix.",
                "Configured integrations and missing/optional integrations are separated for owner triage.",
                "The matrix covers Home Assistant, OpenAI, local AI, Music Assistant, Browser Mod, camera providers, Tailscale, Apple hints, and Nabu Casa.",
            ],
            "next": "Add setup shortcuts for missing integrations once each provider has a stable install recipe.",
        },
        {
            "id": "setup_capability_gaps",
            "title": "Setup Capability Gaps",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Setup page displays the operations capability gap scanner.",
                "Open gaps are grouped by severity so critical and high issues are not buried.",
                "Each gap includes a fix hint pointing to the likely management area.",
            ],
            "next": "Link each gap hint directly to the relevant in-app page once deep-link routing is settled.",
        },
        {
            "id": "setup_onboarding_path",
            "title": "Setup Onboarding Path",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Setup page displays the ordered operations onboarding plan.",
                "Owners see the next setup step plus required and recommended steps.",
                "The panel reuses the onboarding API and remains read-only.",
            ],
            "next": "Add setup task launchers after each action has safe idempotent backend support.",
        },
        {
            "id": "setup_owner_action_checklist",
            "title": "Setup Owner Action Checklist",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Setup page shows a deduplicated owner action checklist above detailed readiness panels.",
                "Actions are built from release gates, capability gaps, and the onboarding next step.",
                "Each action links to the most relevant management page.",
            ],
            "next": "Add action completion tracking once setup actions become transactional.",
        },
        {
            "id": "setup_action_plan_api",
            "title": "Setup Action Plan API",
            "status": "ready",
            "score": 100,
            "evidence": [
                "/ops/setup-action-plan combines release gates, capability gaps, and onboarding next step into one owner plan.",
                "The action plan deduplicates targets and returns top actions for Setup.",
                "Setup consumes the backend plan instead of relying only on frontend-derived actions.",
            ],
            "next": "Expose safe owner task launchers after idempotent setup actions are available.",
        },
        {
            "id": "setup_support_packet",
            "title": "Setup Support Packet",
            "status": "ready",
            "score": 100,
            "evidence": [
                "/ops/setup-support-packet exports the setup action plan, support diagnostics, backup readiness, and integration matrix.",
                "The packet includes Markdown and JSON formats for support handoff or AI review.",
                "The export uses existing support-safe diagnostics and does not include secrets.",
            ],
            "next": "Add one-click support bundle download once browser download handling is polished across HA mobile clients.",
        },
        {
            "id": "sidebar_access_diagnostics",
            "title": "HA Sidebar Access Diagnostics",
            "status": "ready",
            "score": 100,
            "evidence": [
                "/ops/sidebar-access validates Supervisor ingress, panel_admin visibility, and stale wrapper removal.",
                "The diagnostic documents owner/admin and HA Users group expectations.",
                "Remediation steps cover add-on metadata refresh, HA restart, and mobile sidebar cache behavior.",
            ],
            "next": "Add live Supervisor metadata probing if HA exposes add-on panel visibility through the API.",
        },
        {
            "id": "dashboard_action_plan_summary",
            "title": "Dashboard Action Plan Summary",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Dashboard loads /ops/setup-action-plan alongside health and discovery.",
                "Owners see the top setup/release actions on the first screen.",
                "Each dashboard action links to Setup or the relevant management page and remains read-only.",
            ],
            "next": "Add role-scoped dashboard summaries for resident and kiosk health without exposing admin tools.",
        },
        {
            "id": "role_scoped_dashboard",
            "title": "Role-Scoped Dashboard",
            "status": "ready",
            "score": 100,
            "evidence": [
                "/ops/role-dashboard returns owner, resident, kiosk, and guest-safe dashboard summaries.",
                "Dashboard only requests /ops/setup-action-plan for admin/manager sessions.",
                "Resident and shared views show chat, allowed controls, and scheduled-task self-service without setup links.",
            ],
            "next": "Add live per-user acceptance evidence directly to the role-scoped dashboard cards.",
        },
        {
            "id": "role_dashboard_acceptance_evidence",
            "title": "Role Dashboard Acceptance Evidence",
            "status": "ready",
            "score": 100,
            "evidence": [
                "/ops/role-dashboard includes an acceptance object with scope, pass count, failed/blocked count, and latest evidence.",
                "Owner dashboards see house-wide acceptance evidence while residents/shared panels see only matching profile evidence.",
                "Dashboard renders acceptance scope and counts as read-only status under the role summary.",
            ],
            "next": "Let owners launch role-specific acceptance runs from the dashboard after live-house test execution controls are hardened.",
        },
        {
            "id": "role_action_policy_api",
            "title": "Role Action Policy API",
            "status": "ready",
            "score": 100,
            "evidence": [
                "/ops/role-action-policy returns allowed/denied Jarvis capabilities per HA-derived role.",
                "Residents and kiosk/shared users can chat, control approved devices, and create scheduled-task requests.",
                "Dashboard authoring, discovery mapping, system setup, users, and permissions stay owner/manager/admin scoped.",
            ],
            "next": "Display role policy denials inside Chat when a user asks for a protected owner-only change.",
        },
        {
            "id": "chat_role_policy_guidance",
            "title": "Chat Role Policy Guidance",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Chat loads /ops/role-action-policy for the resolved HA/TPG role.",
                "The conversation rail summarizes allowed actions and owner-only boundaries for the active login.",
                "Role-denied command responses render an owner-only explanation without exposing setup controls.",
            ],
            "next": "Add lightweight role-aware suggested prompts so residents see safe examples and owners see management examples.",
        },
        {
            "id": "role_aware_chat_prompts",
            "title": "Role-Aware Chat Starters",
            "status": "ready",
            "score": 100,
            "evidence": [
                "/ops/role-suggested-prompts returns starter prompts derived from the role action policy.",
                "Residents and shared panels see conversation, safe control, and scheduled-task examples.",
                "Owners/admins see dashboard and setup prompts only when their role allows those actions.",
            ],
            "next": "Track which prompts lead to successful actions and rank the best starters first.",
        },
        {
            "id": "prompt_outcome_insights",
            "title": "Prompt Outcome Insights",
            "status": "ready",
            "score": 100,
            "evidence": [
                "/ops/role-prompt-insights ranks role-aware starter prompts from recent CommandLog rows.",
                "Prompt cards include attempt, success, execution, and last-used metadata.",
                "The insight layer reuses audit history and adds no new private storage.",
            ],
            "next": "Use prompt outcomes to suggest follow-up actions after successful scheduled tasks or dashboard drafts.",
        },
        {
            "id": "contextual_chat_followups",
            "title": "Contextual Chat Follow-Ups",
            "status": "ready",
            "score": 100,
            "evidence": [
                "/ops/chat-followups reads recent CommandLog rows and returns role-aware next-step prompts.",
                "Scheduled task and dashboard conversations get specific follow-ups while preserving owner-only boundaries.",
                "Chat renders follow-up chips near the composer so the next useful action is one tap away.",
            ],
            "next": "Allow users to dismiss or pin useful follow-up patterns per assistant profile.",
        },
        {
            "id": "chat_followup_preferences",
            "title": "Chat Follow-Up Preferences",
            "status": "ready",
            "score": 100,
            "evidence": [
                "FollowupPreference rows store pinned and dismissed follow-up chips per user and assistant.",
                "/ops/chat-followups/preferences exposes preference list/save APIs for the active Chat profile.",
                "Chat can pin useful follow-up patterns or hide noisy suggestions without changing role permissions.",
            ],
            "next": "Add automatic stale-preference cleanup and owner export of profile tuning data.",
        },
        {
            "id": "profile_tuning_export",
            "title": "Profile Tuning Export",
            "status": "ready",
            "score": 100,
            "evidence": [
                "/ops/profile-tuning-export returns profile-scoped tuning context as JSON and Markdown.",
                "Exports include assistant identity, follow-up preferences, approved/draft memories, and recent command outcomes.",
                "The Users page exposes a download action so owners can audit or move profile tuning data.",
            ],
            "next": "Add safe stale-preference cleanup with a dry-run report.",
        },
        {
            "id": "followup_preference_cleanup",
            "title": "Follow-Up Preference Cleanup",
            "status": "ready",
            "score": 100,
            "evidence": [
                "/ops/chat-followups/preferences/cleanup previews stale dismissed preferences before removal.",
                "Cleanup defaults to dry-run and only applies when explicitly requested.",
                "Pinned follow-up preferences are protected from cleanup.",
            ],
            "next": "Expose cleanup in owner profile management so tuning data is maintainable.",
        },
        {
            "id": "profile_cleanup_ui",
            "title": "Profile Cleanup UI",
            "status": "ready",
            "score": 100,
            "evidence": [
                "The Users page includes a Preview cleanup action for stale dismissed follow-up preferences.",
                "Owners can review cleanup candidates before applying removal.",
                "The Apply cleanup action uses the same guarded backend endpoint and keeps pinned preferences protected.",
            ],
            "next": "Add runbook/release export actions into the setup surface.",
        },
        {
            "id": "runbook_export_ui",
            "title": "Runbook Export UI",
            "status": "ready",
            "score": 100,
            "evidence": [
                "/release/runbook returns an operational Markdown export that includes release checklist status.",
                "Setup exposes Copy runbook and Download runbook actions beside the owner runbook.",
                "The export is guidance-only and does not execute device, setup, or Home Assistant actions.",
            ],
            "next": "Add release checklist export/copy actions near release blockers.",
        },
        {
            "id": "release_checklist_export_ui",
            "title": "Release Checklist Export UI",
            "status": "ready",
            "score": 100,
            "evidence": [
                "/release/checklist returns a Markdown export of release gates and blockers.",
                "Setup exposes Copy checklist and Download checklist actions near Release blockers.",
                "The checklist export stays read-only and supports owner handoff before shipping.",
            ],
            "next": "Add dashboard-level release status export for owner at-a-glance operations.",
        },
        {
            "id": "operational_runbook",
            "title": "Operational Runbook",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Runbook documents after-update, acceptance pass, failure triage, and feature-freeze steps.",
                "Owners get a repeatable procedure after each add-on update.",
                "Runbook is exposed through /release/runbook and phase 92-96.",
            ],
            "next": "Add UI export/copy for the runbook and release checklist.",
        },
        {
            "id": "ha_native_ui",
            "title": "HA Native UI + Dashboard Builder",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Ingress/sidebar add-on UI is enabled.",
                "Custom integration exposes services, sensors, buttons, notifications, and dashboard draft/install.",
                f"{counts.get('rooms', 0)} configured rooms can be used for dashboard generation.",
                "Dashboard drafts include tablet/profile and voice-panel views.",
            ],
            "next": "Add drag-and-drop dashboard editing.",
        },
        {
            "id": "dashboard_architect",
            "title": "Dashboard Architect",
            "status": "ready",
            "score": 100,
            "evidence": [
                "Owner/admin users can draft dashboard YAML from room and device context.",
                "Dashboard drafts can include tablet/profile and voice-panel views.",
                "Approved spatial assets are inserted as AI Layout Notes for review.",
                "Browser Mod navigation metadata is included when dashboard drafts are generated.",
            ],
            "next": "Add live visual dashboard editing with drag/drop cards and tablet preview profiles.",
        },
        {
            "id": "personal_ai_profiles",
            "title": "Personal AI Profiles v2",
            "status": "ready" if config.assistants.users and config.assistants.assistants else "partial",
            "score": 100 if config.assistants.users and config.assistants.assistants else 72,
            "evidence": [
                f"{len(config.assistants.users)} TPG user profiles synced/configured.",
                f"{len(config.assistants.assistants)} assistant profiles configured.",
                "HA administrators become owner/admin profiles; HA non-admins receive resident profile scope.",
                "Users keep their own assistant, notebook, memories, voice profile, and music account context.",
            ],
            "next": "Add owner-approved profile onboarding notifications for newly detected HA users.",
        },
        {
            "id": "house_state",
            "title": "House State Brain",
            "status": "ready",
            "score": 100,
            "evidence": [
                "House-state endpoint summarizes presence, modes, room activity, and attention items.",
                "House Brain UI shows security, energy, media, maintenance, rooms, assistants, and tablet panels.",
                f"{len(mode_brain.get('active_modes', []))} active mode(s) inferred now.",
                "Recommendations are generated from live HA state without directly executing actions.",
            ],
            "next": "Add UI controls to manually pin/clear modes and schedule mode windows.",
        },
        {
            "id": "mode_brain",
            "title": "Mode Brain",
            "status": "ready" if mode_ready else "partial",
            "score": 100 if mode_ready else 60,
            "evidence": [
                f"{len(mode_brain.get('configured_modes', []))} configured house modes.",
                f"Active reply policy: {mode_brain.get('policy', {}).get('reply_mode', 'auto')}.",
                f"{len(mode_brain.get('policy', {}).get('confirmation_keywords', []))} confirmation keywords in the current policy.",
                "Mode policy is exposed through /brain/modes and Home Assistant services.",
            ],
            "next": "Let users pin modes from Chat, HA services, and dashboard controls.",
        },
        {
            "id": "ai_hybrid",
            "title": "OpenAI / Local AI Hybrid",
            "status": "ready" if ai_ready else "partial",
            "score": 100 if ai_ready else 58,
            "evidence": [
                "OpenAI tool selection is available." if ai.using_openai else "Fallback parser is active.",
                f"OpenAI configured: {settings.openai_configured}.",
                f"Ollama configured: {providers['providers']['ollama']['configured']}.",
            ],
            "next": "Add optional Ollama-compatible local model provider with OpenAI as high-reasoning primary.",
        },
    ]

    overall = int(round(sum(layer["score"] for layer in layers) / len(layers)))
    return {
        "overall_score": overall,
        "status": "ready" if overall >= 85 else "building",
        "layers": layers,
        "summary": {
            "rooms": counts.get("rooms", 0),
            "devices": counts.get("devices", 0),
            "physical_devices": len(physical),
            "entities": counts.get("entities", 0),
            "controllable_entities": controllable,
            "diagnostic_entities": diagnostic,
            "pending_approvals": pending,
            "unavailable_devices": unavailable,
            "approved_house_assets": approved_assets,
            "draft_house_assets": draft_assets,
        },
        "health": health or {},
    }


def build_completion_status(graph: dict[str, Any], health: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the hard stop criteria for Jarvis v1.

    The important distinction is software completeness versus house deployment
    completeness. The repo can be v1-ready before every real microphone,
    display, and HA source id is installed in the user's house.
    """

    config = get_config()
    settings = get_settings()
    ai = get_ai_client()
    providers = ai.provider_status()
    mode_brain = build_mode_brain(config)
    wake_word = build_wake_word_deployment(config)
    counts = graph.get("counts", {})
    pending = int(graph.get("pending_approvals") or 0)
    unavailable = int(graph.get("unavailable_devices") or 0)
    controllable = _controllable_count(graph)
    diagnostic = _diagnostic_count(graph)
    active_voice = wake_word.get("counts", {})
    cfg_err = config_error()
    ha_health = (health or {}).get("home_assistant", {})
    backend_health = (health or {}).get("backend", {})
    openai_health = (health or {}).get("openai", {})
    with get_session() as session:
        approved_assets = session.query(HouseAsset).filter(
            HouseAsset.status == "approved"
        ).count()
        draft_assets = session.query(HouseAsset).filter(
            HouseAsset.status == "draft"
        ).count()
        acceptance_rows = session.query(
            AcceptanceRun.test_id, AcceptanceRun.status
        ).all()

    passed_acceptance_tests = {
        row.test_id for row in acceptance_rows if row.status == "passed"
    }
    failed_acceptance_tests = {
        row.test_id
        for row in acceptance_rows
        if row.status in {"failed", "blocked"}
    }
    required_acceptance_passes = 5

    gates = [
        _gate(
            "core_runtime",
            "Core Runtime + Add-on Lifecycle",
            True,
            bool(backend_health.get("online", True)) and cfg_err is None,
            [
                "Backend starts without crashing.",
                "Config validates cleanly.",
                "Add-on metadata, Docker label, backend package, and integration version are aligned.",
            ],
            [] if cfg_err is None else [f"Fix config validation error: {cfg_err}"],
            "Health, config reload, ingress, and add-on update metadata are stable.",
        ),
        _gate(
            "ha_bridge",
            "Home Assistant Bridge",
            True,
            bool(settings.ha_configured) and bool(ha_health.get("reachable", True)),
            [
                f"HA URL configured: {settings.ha_configured}.",
                f"HA reachable: {ha_health.get('reachable', 'unknown')}.",
                "Custom integration exposes commands, sensors, services, notifications, and sidebar UI.",
            ],
            _missing([
                (not settings.ha_configured, "Configure Home Assistant URL/token or Supervisor proxy."),
                (ha_health.get("reachable") is False, "Fix HA reachability from the add-on/container."),
            ]),
            "The backend can read HA state and execute vetted HA services.",
        ),
        _gate(
            "command_brain",
            "Natural Language Command Brain",
            True,
            True,
            [
                "OpenAI tool selection, deterministic fallback, room context, corrections, and audit explainability exist.",
                "Safe actions can auto-execute when confidence and policy allow.",
                "Sensitive actions are confirmation-gated.",
            ],
            [],
            "Lights, fans, locks, covers, media players, climate, cameras, timers, and routines route through guarded tools.",
        ),
        _gate(
            "security",
            "Security + Identity",
            True,
            bool(settings.security_pin),
            [
                "Unlock/open/disarm/garage/security actions are confirmation-gated.",
                "User permissions are checked before confirmations are created.",
                f"Security PIN configured: {bool(settings.security_pin)}.",
            ],
            _missing([
                (not settings.security_pin, "Set security_pin in add-on options for PIN-backed critical confirmations."),
            ]),
            "Security-disabling actions need confirmation and PIN; security-enabling actions can stay one-step.",
        ),
        _gate(
            "device_graph",
            "Real Device Capability Graph",
            True,
            counts.get("rooms", 0) > 0 and controllable > 0 and pending == 0,
            [
                f"{counts.get('rooms', 0)} rooms configured.",
                f"{controllable} controllable entities and {diagnostic} diagnostic entities mapped.",
                f"{pending} pending approvals and {unavailable} unavailable entities.",
            ],
            _missing([
                (counts.get("rooms", 0) <= 0, "Configure rooms."),
                (controllable <= 0, "Approve controllable HA entities."),
                (pending > 0, f"Approve, map, or ignore {pending} pending discovery items."),
            ]),
            "Every important real device is either approved, intentionally ignored, or safely diagnostic-only.",
        ),
        _gate(
            "voice_assist",
            "Voice, TTS, and Wake Word Deployment",
            True,
            bool(settings.openai_configured)
            and active_voice.get("total", 0) > 0
            and active_voice.get("missing_source_identity", 0) == 0,
            [
                f"OpenAI configured: {settings.openai_configured}.",
                f"{active_voice.get('assistants_with_wake_words', 0)}/{active_voice.get('assistants', 0)} assistants have wake words configured.",
                f"{active_voice.get('assistants_with_linked_sources', 0)}/{active_voice.get('assistants', 0)} assistants are linked to real voice sources.",
                f"{active_voice.get('total', 0)} voice sources configured.",
                f"{active_voice.get('missing_source_identity', 0)} voice sources missing source identity.",
                f"{active_voice.get('rooms_without_voice_source', 0)} rooms without a source.",
            ],
            _missing([
                (not settings.openai_configured, "Configure OpenAI API key for real assistant reasoning/TTS."),
                (active_voice.get("total", 0) <= 0, "Add at least one real microphone/panel/HA Assist voice source."),
                (active_voice.get("missing_source_identity", 0) > 0, "Paste real HA Assist/Browser Mod source IDs into voice_sources."),
            ]),
            "You can talk to the house from real microphones/panels and get natural replies in the right place.",
        ),
        _gate(
            "live_acceptance_evidence",
            "Live-House Acceptance Evidence",
            True,
            len(passed_acceptance_tests) >= required_acceptance_passes
            and not failed_acceptance_tests,
            [
                f"{len(acceptance_rows)} human acceptance result(s) recorded.",
                f"{len(passed_acceptance_tests)} unique acceptance test(s) passed.",
                f"{len(failed_acceptance_tests)} failed or blocked acceptance test(s).",
                "Acceptance evidence is recorded from the read-only live runner and human-reviewed dry-run checks.",
            ],
            _missing([
                (
                    len(passed_acceptance_tests) < required_acceptance_passes,
                    f"Record at least {required_acceptance_passes} passed live-house acceptance checks.",
                ),
                (
                    bool(failed_acceptance_tests),
                    f"Resolve {len(failed_acceptance_tests)} failed or blocked acceptance check(s).",
                ),
            ]),
            "Enough real-house acceptance checks are passed and no failed/blocked checks remain.",
        ),
        _gate(
            "memory_learning",
            "Memory + Learning",
            True,
            True,
            [
                "Short-term conversation context is stored.",
                "Command audit supports explanation and correction follow-ups.",
                "Long-term memories require approval before becoming active context.",
            ],
            [],
            "The system learns preferences through approved memory, not unsafe hidden mutation.",
        ),
        _gate(
            "notebook_research",
            "Notebook + Web Research",
            True,
            True,
            [
                "Conversation sessions can be browsed in TPG HomeAI.",
                "Users can attach notes to a conversation.",
                "Conversation exports produce Markdown for ChatGPT or external sharing.",
                "Read-only web search can be used directly and injected into general chat context.",
            ],
            [],
            "Brainstorming and research sessions stay inside Home Assistant and can be exported when needed.",
        ),
        _gate(
            "house_knowledge",
            "House Knowledge Assets",
            True,
            approved_assets > 0,
            [
                "House assets can store floor plans, room photos, blueprints, and planning notes.",
                "Uploaded assets are analyzed as drafts and must be approved before becoming active AI context.",
                f"{approved_assets} approved house knowledge assets and {draft_assets} draft assets.",
            ],
            _missing([
                (approved_assets <= 0, "Upload and approve at least one real floor plan, blueprint, room photo, or house layout note."),
            ]),
            "The assistant has at least one approved durable reference for the physical layout of the house.",
        ),
        _gate(
            "proactive_suggestions",
            "Proactive Suggestions + Approval Inbox",
            True,
            True,
            [
                "Monitor scans can draft security, maintenance, sleep-timer, dashboard, and routine suggestions.",
                "Automation drafts are approval-first.",
                "Suggestion approve/ignore/install endpoints exist.",
            ],
            [],
            "The assistant can suggest useful actions without silently changing the house.",
        ),
        _gate(
            "dashboards_ui",
            "Native HA UI + Dashboards",
            True,
            True,
            [
                "Ingress/sidebar UI is enabled.",
                "Dashboard builder can draft and install Lovelace YAML.",
                "Browser Mod/tablet profile data exists for room dashboards.",
            ],
            [],
            "The system can be managed from Home Assistant without only using an external web UI.",
        ),
        _gate(
            "ai_hybrid",
            "OpenAI / Local AI Hybrid",
            False,
            bool(providers.get("providers", {}).get("ollama", {}).get("configured")),
            [
                f"OpenAI active: {ai.using_openai}.",
                f"Ollama configured: {providers.get('providers', {}).get('ollama', {}).get('configured')}.",
                "Fallback parser remains available for deterministic offline controls.",
            ],
            ["Optional: configure Ollama for local fallback on the TPG AI server."],
            "OpenAI stays primary, local AI can be a privacy/offline fallback.",
        ),
    ]

    required = [gate for gate in gates if gate["required"]]
    optional = [gate for gate in gates if not gate["required"]]
    required_ready = sum(1 for gate in required if gate["status"] == "complete")
    optional_ready = sum(1 for gate in optional if gate["status"] == "complete")
    software_ready = all(gate["software_ready"] for gate in required)
    deployment_ready = all(gate["status"] == "complete" for gate in required)
    score = int(round(sum(gate["score"] for gate in gates) / len(gates)))
    blockers = [
        blocker
        for gate in required
        for blocker in gate["blockers"]
        if gate["status"] != "complete"
    ]

    return {
        "version_target": "Jarvis v1",
        "status": "complete" if deployment_ready else ("software_ready" if software_ready else "building"),
        "overall_score": score,
        "software_ship_complete": software_ready,
        "house_deployment_complete": deployment_ready,
        "required_complete": required_ready,
        "required_total": len(required),
        "optional_complete": optional_ready,
        "optional_total": len(optional),
        "blockers": blockers,
        "complete_spot": {
            "software": (
                "Stop adding repo features when every required gate has software support, "
                "tests pass, and only house-specific configuration remains."
            ),
            "deployment": (
                "Call Jarvis v1 complete when required gates are complete in the live house: "
                "HA reachable, security PIN set, pending approvals cleared, OpenAI configured, "
                "real voice source IDs mapped, and live-house acceptance evidence recorded."
            ),
            "after_complete": (
                "After that, freeze feature work and only do bug fixes, device mapping, voice tuning, "
                "and small quality-of-life polish until a clear v2 requirement appears."
            ),
        },
        "acceptance": {
            "runs": len(acceptance_rows),
            "unique_passed": len(passed_acceptance_tests),
            "failed_or_blocked": len(failed_acceptance_tests),
            "required_passed": required_acceptance_passes,
            "passed_tests": sorted(passed_acceptance_tests),
            "failed_or_blocked_tests": sorted(failed_acceptance_tests),
        },
        "gates": gates,
    }


def _gate(identifier: str, title: str, required: bool, complete: bool,
          evidence: list[str], blockers: list[str], done_when: str) -> dict[str, Any]:
    return {
        "id": identifier,
        "title": title,
        "required": required,
        "status": "complete" if complete else "incomplete",
        "score": 100 if complete else (75 if required else 60),
        "software_ready": bool(evidence),
        "evidence": evidence,
        "blockers": blockers if not complete else [],
        "done_when": done_when,
    }


def _missing(items: list[tuple[bool, str]]) -> list[str]:
    return [message for condition, message in items if condition]


def _controllable_count(graph: dict[str, Any]) -> int:
    return sum(len(d.get("controllable_entities", [])) for d in graph.get("devices", []))


def _diagnostic_count(graph: dict[str, Any]) -> int:
    return sum(len(d.get("diagnostic_entities", [])) for d in graph.get("devices", []))


def _music_counts(config: Any) -> dict[str, int]:
    speakers = getattr(config.devices, "speakers", []) or []
    accounts = getattr(config.devices, "music_accounts", {}) or {}
    return {
        "accounts": len(accounts),
        "speakers": len(speakers),
        "music_assistant_speakers": sum(
            1 for speaker in speakers if getattr(speaker, "music_assistant_entity_id", None)
        ),
    }


def _media_counts(config: Any, graph: dict[str, Any]) -> dict[str, int]:
    media_players = 0
    for device in graph.get("devices", []):
        entities = [
            *(device.get("controllable_entities", []) or []),
            *(device.get("diagnostic_entities", []) or []),
        ]
        media_players += sum(1 for entity in entities if str(entity.get("entity_id", "")).startswith("media_player."))
    configured_media = len(getattr(config.devices, "speakers", []) or []) + len(getattr(config.devices, "displays", []) or [])
    return {
        "media_players": max(media_players, configured_media),
        "displays": len(getattr(config.devices, "displays", []) or []),
        "speakers": len(getattr(config.devices, "speakers", []) or []),
    }


def _domain_count(graph: dict[str, Any], domain: str) -> int:
    return sum(1 for entity in _graph_entities(graph) if str(entity.get("entity_id", "")).startswith(f"{domain}."))


def _keyword_entity_count(graph: dict[str, Any], keywords: tuple[str, ...]) -> int:
    return sum(
        1
        for entity in _graph_entities(graph)
        if any(keyword in f"{entity.get('entity_id', '')} {entity.get('name', '')} {entity.get('friendly_name', '')}".lower()
               for keyword in keywords)
    )


def _graph_entities(graph: dict[str, Any]) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for device in graph.get("devices", []):
        entities.extend(device.get("controllable_entities", []) or [])
        entities.extend(device.get("diagnostic_entities", []) or [])
    return entities


def _security_counts(config: Any) -> dict[str, int]:
    return {
        "cameras": len(getattr(config.devices, "cameras", []) or []),
        "locks": len(getattr(config.devices, "locks", []) or []),
        "security_sensors": len(getattr(config.devices, "security_sensors", []) or []),
    }


def _occupancy_counts(config: Any) -> dict[str, int]:
    rooms = getattr(config.devices, "rooms", []) or []
    voice_sources = getattr(config.devices, "voice_sources", []) or []
    voice_room_ids = {
        str(getattr(source, "room", "")).strip().lower()
        for source in voice_sources
        if getattr(source, "room", None)
    }
    return {
        "rooms": len(rooms),
        "with_voice_source": sum(
            1
            for room in rooms
            if str(getattr(room, "id", "")).strip().lower() in voice_room_ids
            or str(getattr(room, "name", "")).strip().lower() in voice_room_ids
        ),
    }
