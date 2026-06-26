"""Operational readiness brains for Jarvis phases 82-86.

These helpers are read-only. They turn config, health, discovery, and HA state
into deployment guidance that is safe to show in the UI or hand to support.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter
from pathlib import Path
from typing import Any

from .actions.automation_installer import ha_config_root
from .bootstrap import get_app_state
from .config_loader import config_error
from .db.database import get_session
from .db.models import AcceptanceRun, CommandLog, FollowupPreference, MemoryItem
from .discovery import scanner as discovery_scanner
from .homeassistant.services import safe_get_states
from .models.schemas import AppConfig
from .settings import get_settings


async def build_capability_gap_scanner(config: AppConfig) -> dict[str, Any]:
    settings = get_settings()
    states = await safe_get_states()
    discovery = await discovery_scanner.summary()
    rooms = config.devices.rooms
    assistants = config.assistants.assistants
    voice_sources = config.devices.voice_sources
    open_gaps = [
        _gap(
            "home_assistant_connection",
            "Home Assistant connection",
            "critical",
            not settings.ha_configured,
            "Configure Home Assistant URL/token or Supervisor proxy access.",
        ),
        _gap(
            "openai_key",
            "OpenAI reasoning and TTS",
            "high",
            not settings.openai_configured,
            "Set OPENAI_API_KEY so Jarvis can reason conversationally and generate natural voice replies.",
        ),
        _gap(
            "security_pin",
            "Security PIN",
            "high",
            not bool(settings.security_pin),
            "Set TPG_SECURITY_PIN for unlock, garage, disarm, and other security-disabling confirmations.",
        ),
        _gap(
            "voice_sources",
            "Real voice source mapping",
            "high",
            not any((source.source_device_id or source.source_entity_id) for source in voice_sources),
            "Map at least one HA Assist satellite, browser panel, or microphone source ID to a room.",
        ),
        _gap(
            "wake_words",
            "Assistant wake words",
            "normal",
            not any(assistant.wake_words for assistant in assistants),
            "Add wake phrases to assistant profiles and link them to voice sources.",
        ),
        _gap(
            "rooms",
            "Room model",
            "normal",
            not rooms,
            "Create rooms and map key lights, fans, speakers, displays, locks, and climate devices.",
        ),
        _gap(
            "pending_discovery",
            "Discovery approvals",
            "normal",
            int(discovery.get("pending_count") or 0) > 0,
            f"Review {discovery.get('pending_count', 0)} pending entities so the capability graph is clean.",
        ),
        _gap(
            "music_assistant",
            "Music Assistant speaker routing",
            "normal",
            not any(speaker.music_assistant_entity_id for speaker in config.devices.speakers),
            "Map Music Assistant player entities to speakers for reliable playlist/search playback.",
        ),
        _gap(
            "weather",
            "Weather/environment source",
            "normal",
            not any(entity.domain == "weather" for entity in states.values()),
            "Expose at least one HA weather entity for daily briefings and comfort recommendations.",
        ),
        _gap(
            "dashboard_assets",
            "House photos/floor plans",
            "low",
            True,
            "Optional: upload floor plans, room photos, and tablet notes to improve dashboard generation.",
        ),
    ]
    active = [gap for gap in open_gaps if gap["open"]]
    return {
        "status": "attention" if active else "ready",
        "score": max(0, 100 - sum(_gap_penalty(gap["severity"]) for gap in active)),
        "open_gaps": active,
        "all_gates": open_gaps,
        "counts": {
            "open": len(active),
            "critical": sum(1 for gap in active if gap["severity"] == "critical"),
            "high": sum(1 for gap in active if gap["severity"] == "high"),
            "normal": sum(1 for gap in active if gap["severity"] == "normal"),
            "low": sum(1 for gap in active if gap["severity"] == "low"),
        },
    }


async def build_onboarding_wizard_plan(config: AppConfig) -> dict[str, Any]:
    gaps = await build_capability_gap_scanner(config)
    steps = [
        _step("connect_ha", "Connect Home Assistant", "Verify Supervisor proxy/token and HA reachability.", "required"),
        _step("sync_users", "Sync HA users", "Sync owner/admin and resident profiles from HA users.", "required"),
        _step("approve_discovery", "Approve useful devices", "Clear pending discovery and ignore diagnostic noise.", "required"),
        _step("map_rooms", "Map rooms", "Attach core lights, fans, speakers, displays, locks, and climate devices to rooms.", "required"),
        _step("configure_security", "Configure security policy", "Set the security PIN and review door/garage/alarm permissions.", "required"),
        _step("configure_voice", "Configure voice", "Pick assistant voices, add wake phrases, and bind real mic/source IDs.", "required"),
        _step("configure_music", "Configure music", "Map Music Assistant speakers and per-user music accounts.", "recommended"),
        _step("upload_house_assets", "Add house assets", "Upload floor plans, room photos, and dashboard notes.", "recommended"),
        _step("test_commands", "Run acceptance tests", "Test lights, fans, locks, music, schedules, dashboards, and voice from each user profile.", "required"),
    ]
    open_ids = {gap["id"] for gap in gaps["open_gaps"]}
    for step in steps:
        step["state"] = _step_state(step["id"], open_ids)
    return {
        "status": "ready" if not any(step["state"] == "blocked" for step in steps if step["required"]) else "setup_needed",
        "steps": steps,
        "next_step": next((step for step in steps if step["state"] != "complete"), None),
        "source_gaps": gaps,
    }


async def build_diagnostics_support_pack(config: AppConfig, version: str) -> dict[str, Any]:
    settings = get_settings()
    app_state = get_app_state()
    discovery = await discovery_scanner.summary()
    states = await safe_get_states()
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "safe_for_support": True,
        "secrets_redacted": True,
        "version": version,
        "mode": app_state.mode,
        "status": app_state.status,
        "degraded_reasons": list(app_state.degraded_reasons),
        "config_error": config_error(),
        "settings": settings.safe_dict(),
        "counts": {
            "households": len(config.household.households),
            "users": len(config.assistants.users),
            "assistants": len(config.assistants.assistants),
            "rooms": len(config.devices.rooms),
            "speakers": len(config.devices.speakers),
            "displays": len(config.devices.displays),
            "voice_sources": len(config.devices.voice_sources),
            "states_visible": len(states),
            "discovery_known": discovery.get("known_count", 0),
            "discovery_pending": discovery.get("pending_count", 0),
            "discovery_unavailable": discovery.get("unavailable_count", 0),
        },
        "routes": {
            "health": "/health",
            "brain_layers": "/brain/layers",
            "house_state": "/brain/house-state",
            "phase_82_86": "/brain/phase-82-86",
        },
    }


async def build_backup_recovery_readiness(config: AppConfig) -> dict[str, Any]:
    states = await safe_get_states()
    root = ha_config_root()
    automations = root / "automations.yaml"
    backup_entities = [
        _entity_card(entity)
        for entity in states.values()
        if "backup" in f"{entity.entity_id} {entity.friendly_name or ''}".lower()
    ]
    return {
        "status": "ready" if backup_entities or automations.exists() else "needs_review",
        "ha_config_root": str(root),
        "automations_yaml": {
            "path": str(automations),
            "exists": automations.exists(),
            "backup_pattern": str(automations.with_suffix(automations.suffix + ".tpg-backup-YYYYMMDDHHMMSS")),
        },
        "database": get_settings().safe_dict().get("database_url"),
        "config_dir": get_settings().safe_dict().get("config_dir"),
        "backup_entities": backup_entities[:30],
        "recommendations": [
            "Keep Home Assistant backups enabled before installing generated automations.",
            "Automation installs create timestamped automations.yaml backups before writing.",
            "Export diagnostics before major add-on upgrades or device remapping sessions.",
        ],
    }


async def build_integration_readiness_matrix(config: AppConfig) -> dict[str, Any]:
    settings = get_settings()
    states = await safe_get_states()
    entity_blob = " ".join(states.keys()).lower()
    integrations = [
        _integration("home_assistant", "Home Assistant", settings.ha_configured, "Configured" if settings.ha_configured else "Missing HA URL/token"),
        _integration("openai", "OpenAI", settings.openai_configured, settings.openai_model),
        _integration("ollama", "Ollama", bool(settings.ollama_base_url and settings.ollama_model), settings.ollama_model or "Optional local fallback"),
        _integration("music_assistant", "Music Assistant", _has_music_assistant(config, entity_blob), "Speaker mappings or MA entities detected"),
        _integration("browser_mod", "Browser Mod", "browser_mod" in entity_blob, "Detected in entity IDs" if "browser_mod" in entity_blob else "Optional panel routing"),
        _integration("frigate", "Frigate", "frigate" in entity_blob, "Detected in entity IDs" if "frigate" in entity_blob else "Optional camera events"),
        _integration("nest", "Nest/Google cameras", "nest" in entity_blob, "Detected in entity IDs" if "nest" in entity_blob else "Optional camera events"),
        _integration("tailscale", "Tailscale", "tailscale" in entity_blob, "Detected in entity IDs" if "tailscale" in entity_blob else "Optional HTTPS/access layer"),
        _integration("apple", "Apple/iCloud", any(k in entity_blob for k in ("icloud", "iphone", "ipad")), "Detected Apple device hints" if any(k in entity_blob for k in ("icloud", "iphone", "ipad")) else "Future account/calendar/contact layer"),
        _integration("nabu_casa", "Nabu Casa", "cloud" in entity_blob or "remote_ui" in entity_blob, "Detected cloud/remote UI hints" if "cloud" in entity_blob or "remote_ui" in entity_blob else "Optional HTTPS/remote voice path"),
    ]
    ready = [item for item in integrations if item["configured"]]
    return {
        "status": "ready" if len(ready) >= 3 else "partial",
        "configured": len(ready),
        "total": len(integrations),
        "integrations": integrations,
    }


def build_sidebar_access_diagnostics(config: AppConfig) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[2]
    addon_config = repo_root / "tpg_homeai" / "config.yaml"
    integration_init = repo_root / "custom_components" / "tpg_homeai" / "__init__.py"
    addon_text = addon_config.read_text(encoding="utf-8") if addon_config.exists() else ""
    integration_text = integration_init.read_text(encoding="utf-8") if integration_init.exists() else ""
    checks = [
        _sidebar_check(
            "ingress_enabled",
            "Supervisor ingress enabled",
            "ingress: true" in addon_text,
            "The add-on must use Supervisor ingress so Home Assistant owns authentication.",
        ),
        _sidebar_check(
            "panel_admin_false",
            "Visible to non-admin HA users",
            "panel_admin: false" in addon_text,
            "Set panel_admin: false so HA Users group logins can see the sidebar entry.",
        ),
        _sidebar_check(
            "panel_title",
            "Native panel title configured",
            'panel_title: "TPG HomeAI"' in addon_text,
            "Set panel_title so Supervisor publishes the sidebar entry.",
        ),
        _sidebar_check(
            "wrapper_removed",
            "Legacy wrapper panel removed",
            "_remove_sidebar_panel" in integration_text and "Supervisor ingress" in integration_text and "panel remains" in integration_text,
            "The custom integration should remove old iframe wrapper panels to avoid stale-user sessions.",
        ),
    ]
    users = config.assistants.users
    admins = [user for user in users if user.role == "admin"]
    non_admins = [user for user in users if user.role != "admin"]
    ready = all(check["ok"] for check in checks)
    return {
        "status": "ready" if ready else "attention",
        "visible_to_ha_non_admins": ready,
        "entry": {
            "title": "TPG HomeAI",
            "path": "/api/hassio_ingress/3e5a55d6_tpg_homeai",
            "auth_source": "Home Assistant Supervisor ingress",
            "raw_port": 8088,
            "raw_port_requires_api_token_when_configured": True,
        },
        "checks": checks,
        "role_expectations": [
            {
                "ha_group": "Owner/Administrators",
                "tpg_role": "admin",
                "expected_sidebar": True,
                "expected_scope": "Full TPG HomeAI management.",
                "configured_users": [user.name for user in admins],
            },
            {
                "ha_group": "Users",
                "tpg_role": "resident/kiosk/guest",
                "expected_sidebar": ready,
                "expected_scope": "Chat, own assistant/profile, memory/notebook, and allowed house controls.",
                "configured_users": [user.name for user in non_admins],
            },
        ],
        "remediation": [
            "Update/reinstall the add-on after config.yaml changes so Supervisor rebuilds sidebar metadata.",
            "Restart Home Assistant after installing/updating the custom integration so stale wrapper panels are removed.",
            "For mobile/iPad, force-close the HA app after add-on update because the sidebar cache can persist per account.",
            "Use Identity Debug inside TPG HomeAI to verify the resolved HA user after the panel opens.",
        ],
    }


async def build_role_dashboard_summary(config: AppConfig, role: str = "guest", user_id: str = "") -> dict[str, Any]:
    """Return the safe dashboard summary for the current HA/TPG role.

    This is deliberately read-only: it tells the UI what to show without
    granting permissions or exposing owner setup tasks to resident/shared views.
    """
    normalized_role = (role or "guest").strip().lower()
    if normalized_role not in {"admin", "manager", "resident", "kiosk", "guest"}:
        normalized_role = "guest"
    user = _find_user(config, user_id)
    assistant = _assistant_for_user(config, user.id if user else user_id)
    discovery = await discovery_scanner.summary()
    is_owner_scope = normalized_role in {"admin", "manager"}
    is_shared = normalized_role in {"kiosk", "guest"}
    acceptance = _dashboard_acceptance_evidence(normalized_role, user)
    action_policy = build_role_action_policy(normalized_role)
    cards = (
        _owner_dashboard_cards(discovery, acceptance)
        if is_owner_scope
        else _resident_dashboard_cards(normalized_role, user, assistant, acceptance)
    )
    return {
        "status": "ready",
        "role": normalized_role,
        "mode": "owner_management" if is_owner_scope else ("shared_panel" if is_shared else "personal_jarvis"),
        "user": {
            "id": user.id if user else user_id,
            "name": user.name if user else (user_id or "House"),
            "role": normalized_role,
        },
        "assistant": {
            "id": assistant.id if assistant else ("jarvis" if is_shared else ""),
            "name": assistant.name if assistant else ("Jarvis" if is_shared else "Assistant"),
        },
        "permissions": {
            "admin_actions_visible": is_owner_scope,
            "can_open_setup": is_owner_scope,
            "can_manage_dashboards": is_owner_scope,
            "can_manage_users": normalized_role == "admin",
            "can_create_scheduled_tasks": normalized_role in {"admin", "manager", "resident", "kiosk"},
            "can_chat": True,
            "can_use_house_controls": normalized_role in {"admin", "manager", "resident", "kiosk"},
        },
        "acceptance": acceptance,
        "action_policy": action_policy,
        "cards": cards,
        "guardrails": [
            "Dashboard owner setup actions are hidden unless the resolved HA user is admin/manager.",
            "Residents and shared panels can chat, use approved controls, and create scheduled-task requests.",
            "Dashboard creation, user management, discovery mapping, and system setup remain owner/manager scope.",
        ],
    }


def build_role_action_policy(role: str = "guest") -> dict[str, Any]:
    normalized_role = (role or "guest").strip().lower()
    if normalized_role not in {"admin", "manager", "resident", "kiosk", "guest"}:
        normalized_role = "guest"
    can_operate_house = normalized_role in {"admin", "manager", "resident", "kiosk"}
    can_manage = normalized_role in {"admin", "manager"}
    capabilities = [
        _role_capability("general_conversation", "Ask questions and brainstorm", True, "ChatGPT-style conversation is available to every role."),
        _role_capability("web_research", "Ask for current information", True, "Search/research stays conversational and does not change Home Assistant."),
        _role_capability("safe_device_control", "Control approved lights, fans, climate, covers, and music", can_operate_house, "Allowed for household users; critical/security actions still follow policy."),
        _role_capability("scheduled_tasks", "Create scheduled-task requests", can_operate_house, "Residents and shared panels can ask Jarvis to draft/install safe HA schedules through guarded automation flow."),
        _role_capability("security_disable", "Unlock, open garage, or disarm", can_operate_house, "Requires confirmation/PIN and per-user permission even when the role can operate house devices."),
        _role_capability("dashboard_authoring", "Create or edit HA dashboards", can_manage, "Owner/manager scope only because dashboards change the shared HA experience."),
        _role_capability("discovery_mapping", "Approve/map discovered entities", can_manage, "Owner/manager scope only to protect the house capability graph."),
        _role_capability("system_setup", "Change setup, integrations, users, permissions, or diagnostics", normalized_role == "admin", "Owner/admin scope only."),
    ]
    denied = [item for item in capabilities if not item["allowed"]]
    return {
        "role": normalized_role,
        "status": "ready",
        "capabilities": capabilities,
        "counts": {
            "allowed": len(capabilities) - len(denied),
            "denied": len(denied),
        },
        "highlights": _role_policy_highlights(normalized_role, capabilities),
        "guardrail": "Home Assistant remains the access authority; TPG HomeAI never upgrades a non-admin HA user into owner/admin scope.",
    }


def build_role_suggested_prompts(role: str = "guest") -> dict[str, Any]:
    policy = build_role_action_policy(role)
    by_id = {item["id"]: item for item in policy.get("capabilities", [])}
    can_schedule = bool(by_id.get("scheduled_tasks", {}).get("allowed"))
    can_control = bool(by_id.get("safe_device_control", {}).get("allowed"))
    can_manage_dashboards = bool(by_id.get("dashboard_authoring", {}).get("allowed"))
    can_manage_system = bool(by_id.get("system_setup", {}).get("allowed"))
    prompts = [
        _role_prompt("conversation", "Help me think through a project I am working on."),
        _role_prompt("advice", "What should I improve in my smart home next?"),
    ]
    if can_schedule:
        prompts.append(_role_prompt("schedule", "Create scheduled task. Turn off all lights at 10PM."))
    else:
        prompts.append(_role_prompt("schedule", "Explain what scheduled tasks this login can request."))
    if can_control:
        prompts.append(_role_prompt("control", "Turn off the office lights."))
    if can_manage_dashboards:
        prompts.append(_role_prompt("dashboard", "Build a dashboard for the office."))
    else:
        prompts.append(_role_prompt("owner_boundary", "Which changes need owner approval?"))
    if can_manage_system:
        prompts.append(_role_prompt("setup", "Show me the next setup blockers for full Jarvis mode."))
    return {
        "status": "ready",
        "role": policy["role"],
        "prompts": prompts[:6],
        "policy_counts": policy.get("counts", {}),
        "guardrail": "Starter prompts reflect the resolved role; they do not grant access beyond server-side policy.",
    }


def build_role_prompt_insights(role: str = "guest") -> dict[str, Any]:
    starter = build_role_suggested_prompts(role)
    prompts = starter["prompts"]
    by_key = {_prompt_key(prompt["text"]): prompt for prompt in prompts}
    stats = {
        prompt["id"]: {
            "attempts": 0,
            "successes": 0,
            "executions": 0,
            "last_used": None,
        }
        for prompt in prompts
    }
    with get_session() as session:
        rows = session.query(CommandLog).order_by(CommandLog.created_at.desc(), CommandLog.id.desc()).limit(500).all()
        for row in rows:
            prompt = by_key.get(_prompt_key(row.message))
            if not prompt:
                continue
            item = stats[prompt["id"]]
            item["attempts"] += 1
            if row.success:
                item["successes"] += 1
            if row.executed:
                item["executions"] += 1
            if item["last_used"] is None and row.created_at:
                item["last_used"] = row.created_at.isoformat()
    ranked = []
    for index, prompt in enumerate(prompts):
        item = stats[prompt["id"]]
        score = (item["executions"] * 5) + (item["successes"] * 2) + item["attempts"]
        ranked.append({
            **prompt,
            "rank_score": score,
            "attempts": item["attempts"],
            "successes": item["successes"],
            "executions": item["executions"],
            "last_used": item["last_used"],
            "fresh": item["attempts"] == 0,
            "_index": index,
        })
    ranked.sort(key=lambda prompt: (-prompt["rank_score"], prompt["_index"]))
    for prompt in ranked:
        prompt.pop("_index", None)
    return {
        "status": "ready",
        "role": starter["role"],
        "prompts": ranked,
        "observed_prompts": sum(1 for item in ranked if item["attempts"] > 0),
        "guardrail": "Prompt insights are read from CommandLog only; they do not store new private data or change permissions.",
    }


def build_chat_followups(role: str = "guest", user: str = "", assistant: str = "") -> dict[str, Any]:
    policy = build_role_action_policy(role)
    can_manage = any(c.get("id") == "dashboard_authoring" and c.get("allowed") for c in policy.get("capabilities", []))
    can_schedule = any(c.get("id") == "scheduled_tasks" and c.get("allowed") for c in policy.get("capabilities", []))
    preferences = _load_followup_preferences(user, assistant)
    pinned = [_followup_preference_to_followup(row) for row in preferences if row.state == "pinned"]
    dismissed_keys = {
        _followup_preference_key(row.followup_id, row.text)
        for row in preferences
        if row.state == "dismissed"
    }
    rows: list[CommandLog] = []
    with get_session() as session:
        query = session.query(CommandLog)
        if user:
            query = query.filter(CommandLog.user == user)
        if assistant:
            query = query.filter(CommandLog.assistant == assistant)
        rows = query.order_by(CommandLog.created_at.desc(), CommandLog.id.desc()).limit(20).all()
    followups: list[dict[str, str]] = []
    latest = rows[0] if rows else None
    if latest:
        intent = (latest.intent or "").lower()
        message = (latest.message or "").lower()
        if can_schedule and ("automation" in intent or "routine" in intent or "scheduled task" in message or "schedule" in message):
            followups.append(_followup("review_drafts", "Show me the automation draft before it runs.", intent))
            followups.append(_followup("another_schedule", "Create another scheduled task for bedtime.", intent))
        if "dashboard" in intent or "dashboard" in message:
            if can_manage:
                followups.append(_followup("refine_dashboard", "Refine that dashboard for a wall tablet.", intent))
                followups.append(_followup("install_dashboard", "Install the dashboard draft in Home Assistant.", intent))
            else:
                followups.append(_followup("dashboard_owner_review", "Explain what an owner needs to approve for that dashboard.", intent))
        if latest.executed:
            followups.append(_followup("verify_action", "Check whether Home Assistant shows that action worked.", intent))
        if latest.success and latest.intent and latest.intent != "conversation":
            followups.append(_followup("save_preference", "Remember this preference for next time.", intent))
    if not followups and can_schedule:
        followups.append(_followup("safe_schedule", "Create scheduled task. Turn off all lights at 10PM.", "starter"))
    if not followups:
        followups.append(_followup("brainstorm", "Help me brainstorm what to automate next.", "starter"))
    followups = [
        item for item in followups
        if _followup_preference_key(item.get("id", ""), item.get("text", "")) not in dismissed_keys
    ]
    return {
        "status": "ready",
        "role": policy["role"],
        "user": user,
        "assistant": assistant,
        "followups": _dedupe_followups(pinned + followups)[:4],
        "preferences": {
            "pinned": sum(1 for row in preferences if row.state == "pinned"),
            "dismissed": sum(1 for row in preferences if row.state == "dismissed"),
        },
        "source": "CommandLog+FollowupPreference",
        "guardrail": "Follow-ups are suggestions only; preferences change visibility, not permissions or execution policy.",
    }


def list_chat_followup_preferences(user: str = "", assistant: str = "") -> dict[str, Any]:
    rows = _load_followup_preferences(user, assistant)
    preferences = [_followup_preference_dict(row) for row in rows]
    return {
        "status": "ready",
        "user": user,
        "assistant": assistant,
        "preferences": preferences,
        "counts": {
            "total": len(preferences),
            "pinned": sum(1 for item in preferences if item["state"] == "pinned"),
            "dismissed": sum(1 for item in preferences if item["state"] == "dismissed"),
        },
        "guardrail": "Follow-up preferences are profile-scoped UI hints. Server-side role policy still controls every action.",
    }


def save_chat_followup_preference(
    *,
    user: str = "",
    assistant: str = "",
    followup_id: str = "",
    text: str = "",
    state: str = "pinned",
    source_intent: str = "",
) -> dict[str, Any]:
    normalized_state = state if state in {"pinned", "dismissed"} else "pinned"
    normalized_id = (followup_id or _prompt_key(text) or "followup").strip()[:128]
    with get_session() as session:
        row = (
            session.query(FollowupPreference)
            .filter(
                FollowupPreference.user == (user or ""),
                FollowupPreference.assistant == (assistant or ""),
                FollowupPreference.followup_id == normalized_id,
            )
            .first()
        )
        now = dt.datetime.now(dt.timezone.utc)
        if row is None:
            row = FollowupPreference(
                user=user or "",
                assistant=assistant or "",
                followup_id=normalized_id,
                created_at=now,
            )
            session.add(row)
        row.updated_at = now
        row.text = text or row.text or normalized_id.replace("_", " ")
        row.state = normalized_state
        row.source_intent = source_intent or row.source_intent or "manual"
        session.commit()
        session.refresh(row)
        item = _followup_preference_dict(row)
    return {
        "status": "ready",
        "saved": True,
        "preference": item,
        "guardrail": "Saved follow-up preferences only personalize suggestion chips.",
    }


def build_profile_tuning_export(config: AppConfig, user: str = "", assistant: str = "") -> dict[str, Any]:
    users_by_id = {item.id: item for item in config.assistants.users}
    assistants = [
        item for item in config.assistants.assistants
        if (not assistant or item.id == assistant)
        and (not user or item.owner == user or item.id == assistant)
    ]
    if assistant and not assistants:
        assistants = [item for item in config.assistants.assistants if item.id == assistant]
    assistant_ids = {item.id for item in assistants}
    with get_session() as session:
        preference_query = session.query(FollowupPreference)
        if user:
            preference_query = preference_query.filter(FollowupPreference.user == user)
        if assistant:
            preference_query = preference_query.filter(FollowupPreference.assistant == assistant)
        preferences = preference_query.order_by(FollowupPreference.updated_at.desc(), FollowupPreference.id.desc()).limit(250).all()

        memory_query = session.query(MemoryItem)
        if user:
            memory_query = memory_query.filter(MemoryItem.owner == user)
        memories = memory_query.order_by(MemoryItem.updated_at.desc(), MemoryItem.id.desc()).limit(250).all()

        command_query = session.query(CommandLog)
        if user:
            command_query = command_query.filter(CommandLog.user == user)
        if assistant_ids:
            command_query = command_query.filter(CommandLog.assistant.in_(assistant_ids))
        elif assistant:
            command_query = command_query.filter(CommandLog.assistant == assistant)
        commands = command_query.order_by(CommandLog.created_at.desc(), CommandLog.id.desc()).limit(250).all()

    intent_counts = Counter(row.intent or "unknown" for row in commands)
    command_summary = {
        "total": len(commands),
        "successes": sum(1 for row in commands if row.success),
        "executions": sum(1 for row in commands if row.executed),
        "top_intents": [{"intent": intent, "count": count} for intent, count in intent_counts.most_common(8)],
        "latest": [_profile_command_dict(row) for row in commands[:10]],
    }
    payload = {
        "status": "ready",
        "scope": {"user": user, "assistant": assistant},
        "profile": _profile_user_dict(users_by_id.get(user)) if user else None,
        "assistants": [
            {
                "id": item.id,
                "name": item.name,
                "owner": item.owner,
                "tone": item.tone,
                "wake_words": item.wake_words,
                "voice": item.voice.voice if item.voice else "",
            }
            for item in assistants
        ],
        "followup_preferences": [_followup_preference_dict(row) for row in preferences],
        "memories": [_profile_memory_dict(row) for row in memories],
        "command_summary": command_summary,
        "guardrail": "Profile tuning export is read-only and excludes secrets. It documents personalization without granting permissions.",
    }
    payload["markdown"] = _profile_tuning_markdown(payload)
    return payload


def cleanup_chat_followup_preferences(
    *,
    user: str = "",
    assistant: str = "",
    max_age_days: int = 90,
    apply: bool = False,
) -> dict[str, Any]:
    safe_days = max(0, int(max_age_days))
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=safe_days)
    with get_session() as session:
        query = session.query(FollowupPreference).filter(
            FollowupPreference.state == "dismissed",
            FollowupPreference.updated_at <= cutoff,
        )
        if user:
            query = query.filter(FollowupPreference.user == user)
        if assistant:
            query = query.filter(FollowupPreference.assistant == assistant)
        rows = query.order_by(FollowupPreference.updated_at.asc(), FollowupPreference.id.asc()).limit(500).all()
        candidates = [_followup_preference_dict(row) for row in rows]
        removed = 0
        if apply:
            for row in rows:
                session.delete(row)
            session.commit()
            removed = len(rows)
    return {
        "status": "ready",
        "dry_run": not apply,
        "applied": bool(apply),
        "removed": removed,
        "candidate_count": len(candidates),
        "max_age_days": safe_days,
        "cutoff": cutoff.isoformat(),
        "candidates": candidates,
        "guardrail": "Only dismissed follow-up preferences are cleanup candidates. Pinned preferences are never removed by this task.",
    }


async def build_jarvis_phase_82_86(config: AppConfig, version: str) -> dict[str, Any]:
    gaps = await build_capability_gap_scanner(config)
    onboarding = await build_onboarding_wizard_plan(config)
    diagnostics = await build_diagnostics_support_pack(config, version)
    backup = await build_backup_recovery_readiness(config)
    integrations = await build_integration_readiness_matrix(config)
    score = int(round((
        gaps["score"]
        + (100 if onboarding["status"] == "ready" else 75)
        + 100
        + (100 if backup["status"] == "ready" else 75)
        + int((integrations["configured"] / max(1, integrations["total"])) * 100)
    ) / 5))
    return {
        "status": "ready" if score >= 85 else "partial",
        "score": score,
        "capability_gaps": gaps,
        "onboarding": onboarding,
        "diagnostics": diagnostics,
        "backup_recovery": backup,
        "integration_matrix": integrations,
    }


def _gap(gap_id: str, title: str, severity: str, is_open: bool, fix: str) -> dict[str, Any]:
    return {"id": gap_id, "title": title, "severity": severity, "open": bool(is_open), "fix": fix}


def _gap_penalty(severity: str) -> int:
    return {"critical": 35, "high": 20, "normal": 10, "low": 4}.get(severity, 8)


def _step(step_id: str, title: str, detail: str, importance: str) -> dict[str, Any]:
    return {"id": step_id, "title": title, "detail": detail, "importance": importance, "required": importance == "required"}


def _step_state(step_id: str, open_gap_ids: set[str]) -> str:
    blockers = {
        "connect_ha": {"home_assistant_connection"},
        "sync_users": set(),
        "approve_discovery": {"pending_discovery"},
        "map_rooms": {"rooms"},
        "configure_security": {"security_pin"},
        "configure_voice": {"voice_sources", "wake_words"},
        "configure_music": {"music_assistant"},
        "upload_house_assets": {"dashboard_assets"},
        "test_commands": set(),
    }
    return "blocked" if blockers.get(step_id, set()) & open_gap_ids else "complete"


def _entity_card(entity: Any) -> dict[str, Any]:
    return {
        "entity_id": entity.entity_id,
        "name": entity.friendly_name or entity.entity_id,
        "domain": entity.domain,
        "state": entity.state,
        "available": entity.available,
    }


def _integration(integration_id: str, name: str, configured: bool, detail: str) -> dict[str, Any]:
    return {"id": integration_id, "name": name, "configured": bool(configured), "detail": detail}


def _role_capability(capability_id: str, title: str, allowed: bool, detail: str) -> dict[str, Any]:
    return {
        "id": capability_id,
        "title": title,
        "allowed": bool(allowed),
        "detail": detail,
    }


def _role_prompt(prompt_id: str, text: str) -> dict[str, str]:
    return {"id": prompt_id, "text": text}


def _prompt_key(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _followup(followup_id: str, text: str, source_intent: str) -> dict[str, str]:
    return {"id": followup_id, "text": text, "source_intent": source_intent or "conversation"}


def _dedupe_followups(followups: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for followup in followups:
        key = _prompt_key(followup.get("text", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(followup)
    return out


def _load_followup_preferences(user: str = "", assistant: str = "") -> list[FollowupPreference]:
    with get_session() as session:
        return (
            session.query(FollowupPreference)
            .filter(
                FollowupPreference.user == (user or ""),
                FollowupPreference.assistant == (assistant or ""),
            )
            .order_by(FollowupPreference.updated_at.desc(), FollowupPreference.id.desc())
            .limit(100)
            .all()
        )


def _followup_preference_dict(row: FollowupPreference) -> dict[str, Any]:
    return {
        "id": row.id,
        "user": row.user,
        "assistant": row.assistant,
        "followup_id": row.followup_id,
        "text": row.text,
        "state": row.state,
        "source_intent": row.source_intent,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _followup_preference_to_followup(row: FollowupPreference) -> dict[str, str]:
    return {
        "id": row.followup_id,
        "text": row.text,
        "source_intent": row.source_intent or "pinned",
        "preference": row.state,
    }


def _followup_preference_key(followup_id: str, text: str) -> tuple[str, str]:
    return ((followup_id or "").strip().lower(), _prompt_key(text))


def _profile_user_dict(user: Any | None) -> dict[str, Any] | None:
    if not user:
        return None
    return {
        "id": user.id,
        "name": user.name,
        "role": user.role,
        "ha_username": user.ha_username,
        "ha_is_admin": user.ha_is_admin,
        "access_source": user.access_source,
        "music_account": user.music_account,
        "aliases": user.aliases,
    }


def _profile_memory_dict(row: MemoryItem) -> dict[str, Any]:
    return {
        "id": row.id,
        "scope": row.scope,
        "owner": row.owner,
        "subject": row.subject,
        "key": row.key,
        "value": row.value,
        "source": row.source,
        "status": row.status,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _profile_command_dict(row: CommandLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "assistant": row.assistant,
        "user": row.user,
        "intent": row.intent,
        "success": row.success,
        "executed": row.executed,
        "message": row.message,
        "response": row.response_message,
    }


def _profile_tuning_markdown(payload: dict[str, Any]) -> str:
    scope = payload.get("scope", {})
    lines = [
        "# TPG HomeAI Profile Tuning Export",
        "",
        f"- User: {scope.get('user') or 'all'}",
        f"- Assistant: {scope.get('assistant') or 'all'}",
        f"- Assistants: {len(payload.get('assistants') or [])}",
        f"- Follow-up preferences: {len(payload.get('followup_preferences') or [])}",
        f"- Memories: {len(payload.get('memories') or [])}",
        f"- Commands sampled: {payload.get('command_summary', {}).get('total', 0)}",
        "",
        "## Assistants",
    ]
    for assistant in payload.get("assistants") or []:
        lines.append(f"- {assistant.get('name')} (`{assistant.get('id')}`): tone={assistant.get('tone')}, voice={assistant.get('voice') or 'default'}")
    lines.extend(["", "## Follow-Up Preferences"])
    for pref in payload.get("followup_preferences") or []:
        lines.append(f"- {pref.get('state')}: {pref.get('text')} (`{pref.get('followup_id')}`)")
    lines.extend(["", "## Memories"])
    for memory in payload.get("memories") or []:
        lines.append(f"- {memory.get('status')} {memory.get('scope')}/{memory.get('subject')}: {memory.get('key')} = {memory.get('value')}")
    lines.extend(["", "## Top Intents"])
    for item in payload.get("command_summary", {}).get("top_intents", []):
        lines.append(f"- {item.get('intent')}: {item.get('count')}")
    lines.extend(["", "## Latest Commands"])
    for command in payload.get("command_summary", {}).get("latest", []):
        lines.append(f"- {command.get('created_at')}: {command.get('intent')} | success={command.get('success')} | `{command.get('message')}`")
    return "\n".join(lines).strip() + "\n"


def _role_policy_highlights(role: str, capabilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {item["id"]: item for item in capabilities}
    highlights = [
        {
            "id": "chat",
            "label": "Chat + advice",
            "allowed": True,
            "detail": "Conversational Jarvis stays available.",
        },
        {
            "id": "scheduled_tasks",
            "label": "Scheduled tasks",
            "allowed": bool(by_id.get("scheduled_tasks", {}).get("allowed")),
            "detail": "Create safe schedule requests through Jarvis.",
        },
        {
            "id": "dashboards",
            "label": "Dashboards",
            "allowed": bool(by_id.get("dashboard_authoring", {}).get("allowed")),
            "detail": "Shared HA dashboard editing is owner/manager scope.",
        },
        {
            "id": "system",
            "label": "System setup",
            "allowed": bool(by_id.get("system_setup", {}).get("allowed")),
            "detail": "Users, permissions, integrations, and diagnostics are owner scope.",
        },
    ]
    if role == "guest":
        highlights[1]["detail"] = "Guests can chat but cannot schedule house changes."
    return highlights


def _sidebar_check(check_id: str, title: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"id": check_id, "title": title, "ok": bool(ok), "detail": detail}


def _has_music_assistant(config: AppConfig, entity_blob: str) -> bool:
    return (
        bool(config.devices.music_accounts)
        or any(speaker.music_assistant_entity_id for speaker in config.devices.speakers)
        or "music_assistant" in entity_blob
        or "mass_" in entity_blob
    )


def _find_user(config: AppConfig, user_id: str) -> Any | None:
    wanted = (user_id or "").strip().lower()
    if not wanted:
        return None
    for user in config.assistants.users:
        aliases = {str(alias).strip().lower() for alias in (user.aliases or [])}
        if wanted in {user.id.lower(), user.name.lower(), str(user.ha_username or "").lower(), str(user.ha_user_id or "").lower()} | aliases:
            return user
    return None


def _assistant_for_user(config: AppConfig, user_id: str) -> Any | None:
    wanted = (user_id or "").strip().lower()
    if not wanted:
        return None
    return next((assistant for assistant in config.assistants.assistants if assistant.owner.lower() == wanted), None)


def _dashboard_acceptance_evidence(role: str, user: Any | None) -> dict[str, Any]:
    with get_session() as session:
        rows = (
            session.query(AcceptanceRun)
            .order_by(AcceptanceRun.created_at.desc())
            .limit(200)
            .all()
        )
    aliases = _user_match_values(user)
    scoped_rows = rows if role in {"admin", "manager"} else [
        row for row in rows
        if (row.user or "").strip().lower() in aliases
    ]
    counts = Counter(row.status for row in scoped_rows)
    latest = scoped_rows[0] if scoped_rows else None
    failed_or_blocked = counts.get("failed", 0) + counts.get("blocked", 0)
    return {
        "scope": "house" if role in {"admin", "manager"} else "profile",
        "recorded": len(scoped_rows),
        "passed": counts.get("passed", 0),
        "failed_or_blocked": failed_or_blocked,
        "status_counts": dict(counts),
        "latest": {
            "test_id": latest.test_id,
            "status": latest.status,
            "user": latest.user,
            "assistant": latest.assistant,
            "created_at": latest.created_at.isoformat() if latest.created_at else None,
        } if latest else None,
        "needs_evidence": len(scoped_rows) == 0,
    }


def _user_match_values(user: Any | None) -> set[str]:
    if not user:
        return set()
    values = {
        user.id,
        user.name,
        str(user.ha_username or ""),
        str(user.ha_user_id or ""),
    }
    values.update(str(alias) for alias in (user.aliases or []))
    return {value.strip().lower() for value in values if value and value.strip()}


def _owner_dashboard_cards(discovery: dict[str, Any], acceptance: dict[str, Any]) -> list[dict[str, Any]]:
    pending = int(discovery.get("pending_count") or 0)
    unavailable = int(discovery.get("unavailable_count") or 0)
    return [
        {
            "id": "owner_action_plan",
            "title": "Owner action plan",
            "detail": "Setup, release blockers, diagnostics, and capability gaps are available from this dashboard.",
            "target": "/setup",
            "tone": "brand",
        },
        {
            "id": "device_discovery",
            "title": "Device discovery",
            "detail": f"{pending} pending approvals and {unavailable} unavailable entities need owner review.",
            "target": "/discovery",
            "tone": "warn" if pending or unavailable else "good",
        },
        {
            "id": "brain_readiness",
            "title": "Jarvis readiness",
            "detail": f"{acceptance['passed']} passed and {acceptance['failed_or_blocked']} failed/blocked acceptance checks are recorded.",
            "target": "/jarvis",
            "tone": "good" if acceptance["passed"] and not acceptance["failed_or_blocked"] else "warn",
        },
    ]


def _resident_dashboard_cards(role: str, user: Any | None, assistant: Any | None, acceptance: dict[str, Any]) -> list[dict[str, Any]]:
    assistant_name = assistant.name if assistant else ("Jarvis" if role in {"kiosk", "guest"} else "your assistant")
    owner = user.name if user else ("shared panel" if role in {"kiosk", "guest"} else "this profile")
    return [
        {
            "id": "personal_assistant",
            "title": f"{assistant_name} is ready",
            "detail": f"Signed in as {owner}. Ask questions, brainstorm, or control approved house devices.",
            "target": "/chat",
            "tone": "brand",
        },
        {
            "id": "scheduled_tasks",
            "title": "Scheduled tasks",
            "detail": "You can ask Jarvis to create safe schedules like turning lights off at 10 PM.",
            "target": "/chat",
            "tone": "good",
        },
        {
            "id": "acceptance_evidence",
            "title": "Profile acceptance",
            "detail": f"{acceptance['passed']} passed and {acceptance['failed_or_blocked']} failed/blocked checks recorded for this profile scope.",
            "target": "/jarvis" if role == "resident" else "/chat",
            "tone": "good" if acceptance["passed"] and not acceptance["failed_or_blocked"] else "slate",
        },
        {
            "id": "protected_changes",
            "title": "Protected changes",
            "detail": "Dashboards, users, discovery mapping, and system setup stay hidden unless HA grants owner access.",
            "target": "/chat",
            "tone": "slate",
        },
    ]
