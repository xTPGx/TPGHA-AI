"""Experience and release acceptance brains for Jarvis phases 92-103."""
from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from typing import Any

from .db.database import get_session
from .db.models import AcceptanceRun, CommandLog, ConversationNote, ConversationState, Suggestion
from .homeassistant.services import safe_get_states
from .knowledge import build_house_graph
from .models.schemas import AcceptanceResultRequest, AppConfig
from .operations_brain import (
    build_backup_recovery_readiness,
    build_capability_gap_scanner,
    build_diagnostics_support_pack,
    build_integration_readiness_matrix,
    build_onboarding_wizard_plan,
)
from .settings import get_settings
from .voice import list_voice_source_readiness


def build_interaction_quality_report(config: AppConfig) -> dict[str, Any]:
    with get_session() as session:
        commands = session.query(CommandLog).order_by(CommandLog.created_at.desc()).limit(500).all()
        conversations = session.query(ConversationState).count()
        notes = session.query(ConversationNote).count()
    total = len(commands)
    executed = sum(1 for row in commands if row.executed)
    successful = sum(1 for row in commands if row.success)
    failed = [row for row in commands if not row.success]
    confusion = [
        row for row in commands
        if any(token in (row.message or "").lower() for token in ("wrong", "not what", "nothing happened", "didn't", "doesnt", "doesn't"))
    ]
    intents = Counter(row.intent or "conversation" for row in commands)
    score = 100 if not total else int(round((successful / total) * 100))
    return {
        "status": "attention" if failed[:1] or confusion[:1] else "ready",
        "score": score,
        "counts": {
            "sample_size": total,
            "successful": successful,
            "failed": len(failed),
            "executed": executed,
            "conversations": conversations,
            "notes": notes,
            "confusion_signals": len(confusion),
        },
        "top_intents": [{"intent": intent, "count": count} for intent, count in intents.most_common(10)],
        "recent_failures": [_command_card(row) for row in failed[:15]],
        "recent_confusion": [_command_card(row) for row in confusion[:15]],
        "recommendations": _interaction_recommendations(total, failed, confusion),
    }


def build_voice_acceptance_plan(config: AppConfig) -> dict[str, Any]:
    readiness = list_voice_source_readiness(config)
    counts = readiness.get("counts", {})
    ready = counts.get("ready", 0)
    total = counts.get("total", 0)
    assistants_ready = counts.get("assistants_ready", 0)
    assistants = counts.get("assistants", 0)
    return {
        "status": "ready" if ready and assistants_ready == assistants else "setup_needed",
        "score": 100 if ready and assistants_ready == assistants else 70,
        "readiness": readiness,
        "acceptance_tests": [
            _acceptance("browser_mic", "Use Mic in Chat over HTTPS/Tailscale/Nabu Casa and verify transcription."),
            _acceptance("assistant_tts", "Test each assistant voice and confirm it uses OpenAI TTS when configured."),
            _acceptance("wake_word", "Say each assistant wake word from a real room source and verify the correct assistant/profile."),
            _acceptance("room_context", "From each panel/satellite, say 'turn on the light' and verify the room target is correct."),
            _acceptance("safe_security", "Try lock/unlock security flows and verify unlock/open/disarm requires confirmation/PIN."),
        ],
        "blockers": _voice_blockers(counts),
    }


def build_role_acceptance_matrix(config: AppConfig) -> dict[str, Any]:
    users = config.assistants.users
    assistants = config.assistants.assistants
    role_counts = Counter(user.role for user in users)
    assistant_owner_ids = {assistant.owner for assistant in assistants}
    users_without_assistant = [
        user.id for user in users
        if user.role not in {"kiosk", "guest"} and user.id not in assistant_owner_ids
    ]
    checks = [
        _role_acceptance_check(
            "owner_admin_full_access",
            "Owner/Admin full control",
            role_counts.get("admin", 0) > 0,
            "admin",
            [
                "Can use general chat and house controls.",
                "Can manage users, rooms, permissions, discovery, dashboards, and setup.",
                "Can draft and install dashboards and approved automations.",
            ],
            "At least one HA admin/owner must sync into TPG HomeAI as admin.",
        ),
        _role_acceptance_check(
            "resident_self_service",
            "Resident self-service",
            role_counts.get("resident", 0) > 0,
            "resident",
            [
                "Can use their own assistant, chat history, notes, and memory preferences.",
                "Can control allowed devices and create scheduled tasks.",
                "Cannot create dashboards, manage users, or change system settings.",
            ],
            "Sync at least one non-admin HA user as resident for household validation.",
        ),
        _role_acceptance_check(
            "kiosk_shared_remote",
            "Kiosk/shared house remote",
            role_counts.get("kiosk", 0) > 0,
            "kiosk",
            [
                "Uses the shared Jarvis/house profile instead of a personal notebook.",
                "Can act as a room remote or wall panel for allowed house actions.",
                "Cannot access owner management, dashboards, users, or permissions.",
            ],
            "Create or sync a kiosk/shared HA user for wall tablets and shared iPads.",
        ),
        _role_acceptance_check(
            "guest_limited_access",
            "Guest limited access",
            True,
            "guest",
            [
                "Guest is supported as an optional constrained role.",
                "Guest can chat and use explicitly allowed controls only.",
                "Guest cannot manage system, dashboard, memory, or security-disabling actions.",
            ],
            "",
            optional=True,
        ),
        _role_acceptance_check(
            "assistant_owner_mapping",
            "Personal assistant mapping",
            not users_without_assistant,
            "all",
            [
                f"{len(assistants)} assistant profile(s) configured.",
                "Non-kiosk household users should have a matching assistant/profile for personal history.",
                "Kiosk/shared users intentionally use the shared Jarvis profile.",
            ],
            "Create assistant profiles for: " + ", ".join(users_without_assistant),
        ),
        _role_acceptance_check(
            "ha_authority_sync",
            "Home Assistant authority sync",
            any(user.access_source == "home_assistant" for user in users),
            "all",
            [
                "Home Assistant remains the access authority.",
                "HA admins map to TPG admin/owner access.",
                "HA non-admins map to resident/kiosk/guest self-service access.",
            ],
            "Run Sync from HA users after creating or changing Home Assistant users.",
        ),
    ]
    required = [check for check in checks if check["required"]]
    ready = sum(1 for check in required if check["pass"])
    blockers = [check["blocker"] for check in required if not check["pass"] and check["blocker"]]
    return {
        "status": "ready" if ready == len(required) else "attention",
        "score": int(round((ready / max(1, len(required))) * 100)),
        "counts": {
            "users": len(users),
            "assistants": len(assistants),
            "roles": dict(role_counts),
            "ha_synced": sum(1 for user in users if user.access_source == "home_assistant"),
            "users_without_assistant": len(users_without_assistant),
        },
        "checks": checks,
        "blockers": blockers,
        "user_matrix": [_role_user_card(user, assistant_owner_ids) for user in users],
    }


def build_acceptance_repair_queue() -> dict[str, Any]:
    with get_session() as session:
        rows = session.query(AcceptanceRun).order_by(
            AcceptanceRun.created_at.desc()
        ).limit(100).all()
        suggestions = session.query(Suggestion).filter(
            Suggestion.category == "acceptance",
            Suggestion.action_type == "acceptance_repair",
            Suggestion.status.in_(["suggested", "draft", "edited"]),
        ).order_by(Suggestion.created_at.desc()).limit(50).all()

    latest_by_test: dict[str, AcceptanceRun] = {}
    for row in rows:
        if row.test_id and row.test_id not in latest_by_test:
            latest_by_test[row.test_id] = row
    failures = [
        _acceptance_run_card(row)
        for row in latest_by_test.values()
        if row.status in {"failed", "blocked"}
    ]
    active_repairs = [_suggestion_card(row) for row in suggestions]
    failure_ids = {row["test_id"] for row in failures}
    repair_test_ids = {
        (row.get("payload") or {}).get("test_id")
        for row in active_repairs
        if isinstance(row.get("payload"), dict)
    }
    unrepaired = sorted(test_id for test_id in failure_ids if test_id not in repair_test_ids)
    return {
        "status": "ready" if not failures or not unrepaired else "attention",
        "summary": {
            "failed_or_blocked": len(failures),
            "active_repairs": len(active_repairs),
            "unrepaired": len(unrepaired),
        },
        "failures": failures,
        "active_repairs": active_repairs,
        "unrepaired_test_ids": unrepaired,
        "guidance": [
            "Run Monitor Scan after recording failed or blocked acceptance evidence.",
            "Review or resolve the generated acceptance_repair suggestion.",
            "Rerun the live-house test and record a passed result when the issue is fixed.",
        ],
    }


def build_acceptance_resolution_summary() -> dict[str, Any]:
    with get_session() as session:
        resolved_repairs = session.query(Suggestion).filter(
            Suggestion.category == "acceptance",
            Suggestion.action_type == "acceptance_repair",
            Suggestion.status == "resolved",
        ).count()
        active_repairs = session.query(Suggestion).filter(
            Suggestion.category == "acceptance",
            Suggestion.action_type == "acceptance_repair",
            Suggestion.status.in_(["suggested", "draft", "edited"]),
        ).count()
        latest_rows = session.query(AcceptanceRun).order_by(
            AcceptanceRun.created_at.desc()
        ).limit(100).all()
    latest_by_test: dict[str, AcceptanceRun] = {}
    for row in latest_rows:
        if row.test_id and row.test_id not in latest_by_test:
            latest_by_test[row.test_id] = row
    passed = sorted(
        test_id for test_id, row in latest_by_test.items()
        if row.status == "passed"
    )
    still_failing = sorted(
        test_id for test_id, row in latest_by_test.items()
        if row.status in {"failed", "blocked"}
    )
    return {
        "status": "ready",
        "summary": {
            "resolved_repairs": resolved_repairs,
            "active_repairs": active_repairs,
            "latest_passed_tests": len(passed),
            "latest_failed_or_blocked_tests": len(still_failing),
        },
        "latest_passed_test_ids": passed,
        "latest_failed_or_blocked_test_ids": still_failing,
        "resolution_policy": [
            "A passed acceptance result resolves active repair suggestions for the same test_id.",
            "Resolved suggestions leave the audit trail intact but disappear from the active repair queue.",
            "If a later result fails again, Monitor Scan can open a fresh repair suggestion.",
        ],
    }


async def build_device_acceptance_matrix(config: AppConfig) -> dict[str, Any]:
    states = await safe_get_states()
    graph = await build_house_graph(include_registries=False)
    domains = Counter(entity.domain for entity in states.values())
    checks = [
        _domain_check("light", "Turn a known light on/off and verify final state.", domains),
        _domain_check("fan", "Turn a known fan on/off and test percentage/level fallback behavior.", domains),
        _domain_check("lock", "Lock a door directly; unlock requires confirmation/PIN.", domains),
        _domain_check("cover", "Open/close cover or garage only when policy allows.", domains),
        _domain_check("climate", "Set HVAC mode/temperature and verify state.", domains),
        _domain_check("media_player", "Turn on/off/play media on TV/speaker and verify outcome.", domains),
        _domain_check("camera", "Ask for security/camera briefing and verify camera availability.", domains),
        _domain_check("calendar", "Create a calendar-trigger draft if calendar entities exist.", domains),
        _domain_check("weather", "Ask a weather/general question and verify conversational answer.", domains),
    ]
    ready_checks = sum(1 for check in checks if check["available"])
    return {
        "status": "ready" if ready_checks >= 5 else "partial",
        "score": int(round((ready_checks / len(checks)) * 100)),
        "domain_counts": dict(domains),
        "checks": checks,
        "graph_counts": graph.get("counts", {}),
        "role_acceptance": [
            "Admin/owner can chat, control devices, draft/install automations, draft dashboards, and manage setup.",
            "Resident can chat, control allowed devices, and draft scheduled tasks without dashboard/system rights.",
            "Kiosk/shared profile can act as a house remote without exposing owner notebook/settings.",
        ],
    }


async def build_live_acceptance_runner(config: AppConfig) -> dict[str, Any]:
    """Build a read-only live-house acceptance plan from the current HA graph.

    The runner intentionally does not execute Home Assistant services. It gives
    an owner a concrete, live-data-driven plan for what can be safely checked
    now, what needs a human-run dry run, and which critical actions must stay
    confirmation-gated.
    """
    states = await safe_get_states()
    graph = await build_house_graph(include_registries=False)
    domains = Counter(entity.domain for entity in states.values())
    tests = [
        _live_acceptance_case(
            "ha_health_probe",
            "Home Assistant connection and entity inventory",
            "read_only_probe",
            "system",
            states,
            domains,
            "owner",
            "Ask TPG HomeAI for a house status summary.",
            "Backend can read HA state cache and return entity/domain counts.",
        ),
        _live_acceptance_case(
            "conversation_general_probe",
            "General ChatGPT-style conversation",
            "read_only_probe",
            "conversation",
            states,
            domains,
            "resident",
            "Ask for brainstorming, advice, or a weather-style question.",
            "Assistant answers conversationally without requiring a device target.",
        ),
        _live_acceptance_case(
            "light_control_dry_run",
            "Known light on/off",
            "dry_run_required",
            "light",
            states,
            domains,
            "resident",
            "Turn on a known light, then turn it back off.",
            "Resolved target matches the requested room/device and final HA state changes as expected.",
        ),
        _live_acceptance_case(
            "fan_control_dry_run",
            "Known fan on/off and speed wording",
            "dry_run_required",
            "fan",
            states,
            domains,
            "resident",
            "Turn on a fan, then try 'set fan speed to level 5'.",
            "Fan power works and unavailable percentage services produce a clear capability explanation.",
        ),
        _live_acceptance_case(
            "lock_safe_flow",
            "Door lock security policy",
            "dry_run_required",
            "lock",
            states,
            domains,
            "resident",
            "Lock a known door; then request unlock and verify PIN/confirmation is required.",
            "Locking can run when allowed; unlock/open/disarm remains protected.",
            sensitive=True,
        ),
        _live_acceptance_case(
            "climate_control_dry_run",
            "Thermostat mode and temperature",
            "dry_run_required",
            "climate",
            states,
            domains,
            "resident",
            "Set a known thermostat to a safe temperature.",
            "The target thermostat is resolved and HA service payload is correct before execution.",
        ),
        _live_acceptance_case(
            "media_music_dry_run",
            "Music Assistant / speaker playback",
            "dry_run_required",
            "media_player",
            states,
            domains,
            "resident",
            "Play a known playlist on a known speaker.",
            "Playback routes through the assistant owner's music account and speaker mapping.",
        ),
        _live_acceptance_case(
            "camera_briefing_probe",
            "Camera and security briefing",
            "read_only_probe",
            "camera",
            states,
            domains,
            "resident",
            "Ask what cameras are online.",
            "Assistant reports camera availability without exposing protected streams to the wrong role.",
        ),
        _live_acceptance_case(
            "schedule_draft_dry_run",
            "Scheduled task creation",
            "dry_run_required",
            "automation",
            states,
            domains,
            "resident",
            "Create scheduled task. Turn off all lights at 10PM.",
            "Resident can draft/install allowed schedules while dashboard/system changes stay admin-only.",
        ),
        _live_acceptance_case(
            "dashboard_admin_dry_run",
            "Dashboard generation guardrail",
            "dry_run_required",
            "dashboard",
            states,
            domains,
            "owner",
            "Build a dashboard for a room using available entities.",
            "Only owner/admin can draft or install dashboard/system UI changes.",
        ),
    ]
    evidence = list_live_acceptance_results(limit=100)
    blocked = [test for test in tests if test["status"] == "blocked"]
    ready = [test for test in tests if test["status"] == "ready"]
    return {
        "status": "ready" if not blocked else "partial",
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "policy": {
            "read_only": True,
            "executes_actions": False,
            "mutating_tests_are_human_run": True,
            "requires_human_to_run_mutating_tests": True,
            "purpose": "Build a live acceptance plan without changing real devices.",
        },
        "summary": {
            "total": len(tests),
            "ready": len(ready),
            "blocked": len(blocked),
            "read_only": sum(1 for test in tests if test["mode"] == "read_only_probe"),
            "dry_run_required": sum(1 for test in tests if test["mode"] == "dry_run_required"),
            "sensitive": sum(1 for test in tests if test["sensitive"]),
            "domains_seen": dict(domains),
        },
        "tests": tests,
        "blockers": [test["blocker"] for test in blocked],
        "evidence": evidence,
        "graph_counts": graph.get("counts", {}),
        "next_action": _next_live_acceptance_action(tests),
    }


def record_live_acceptance_result(payload: AcceptanceResultRequest, version: str) -> dict[str, Any]:
    with get_session() as session:
        test_id = payload.test_id.strip()
        row = AcceptanceRun(
            test_id=test_id,
            status=payload.status,
            assistant=payload.assistant or "",
            user=payload.user or "",
            notes=payload.notes,
            evidence=json.dumps(payload.evidence or {}, sort_keys=True),
            version=version,
        )
        session.add(row)
        resolved_repairs = 0
        if payload.status == "passed":
            resolved_repairs = _resolve_acceptance_repairs(session, test_id)
        session.commit()
        session.refresh(row)
        return {
            "recorded": True,
            "result": _acceptance_run_card(row),
            "resolved_repairs": resolved_repairs,
        }


def list_live_acceptance_results(limit: int = 100) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit or 100), 500))
    with get_session() as session:
        rows = (
            session.query(AcceptanceRun)
            .order_by(AcceptanceRun.created_at.desc())
            .limit(safe_limit)
            .all()
        )
    cards = [_acceptance_run_card(row) for row in rows]
    latest_by_test: dict[str, dict[str, Any]] = {}
    for card in cards:
        latest_by_test.setdefault(card["test_id"], card)
    status_counts = Counter(card["status"] for card in cards)
    return {
        "count": len(cards),
        "status_counts": dict(status_counts),
        "latest_by_test": latest_by_test,
        "results": cards,
    }


async def build_live_acceptance_report(config: AppConfig, version: str) -> dict[str, Any]:
    live = await build_live_acceptance_runner(config)
    role_acceptance = build_role_acceptance_matrix(config)
    repair_queue = build_acceptance_repair_queue()
    resolutions = build_acceptance_resolution_summary()
    evidence = live.get("evidence", {})
    latest_by_test = evidence.get("latest_by_test", {}) or {}
    tests = live.get("tests", []) or []
    required_passes = 5
    required_test_ids = [test["id"] for test in tests]
    passed_tests = sorted(
        test_id
        for test_id in required_test_ids
        if latest_by_test.get(test_id, {}).get("status") == "passed"
    )
    failed_or_blocked_tests = sorted(
        test_id
        for test_id in required_test_ids
        if latest_by_test.get(test_id, {}).get("status") in {"failed", "blocked"}
    )
    missing_tests = sorted(
        test_id
        for test_id in required_test_ids
        if latest_by_test.get(test_id, {}).get("status") != "passed"
    )
    blockers = list(live.get("blockers", []) or [])
    if len(passed_tests) < required_passes:
        blockers.append(f"Record at least {required_passes} passed acceptance checks.")
    if failed_or_blocked_tests:
        blockers.append(f"Resolve {len(failed_or_blocked_tests)} failed or blocked checks.")
    status = "ready" if len(passed_tests) >= required_passes and not failed_or_blocked_tests else "attention"
    report = {
        "status": status,
        "version": version,
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "policy": live.get("policy", {}),
        "summary": {
            "tests": len(tests),
            "evidence_results": evidence.get("count", 0),
            "required_passes": required_passes,
            "passed": len(passed_tests),
            "failed_or_blocked": len(failed_or_blocked_tests),
            "missing": len(missing_tests),
        },
        "passed_tests": passed_tests,
        "failed_or_blocked_tests": failed_or_blocked_tests,
        "missing_tests": missing_tests,
        "latest_by_test": latest_by_test,
        "role_acceptance": role_acceptance,
        "acceptance_repairs": repair_queue,
        "acceptance_resolutions": resolutions,
        "blockers": blockers,
        "markdown": "",
    }
    report["markdown"] = _live_acceptance_report_markdown(report, tests)
    return report


async def build_release_checklist(config: AppConfig, version: str) -> dict[str, Any]:
    settings = get_settings()
    interaction = build_interaction_quality_report(config)
    voice = build_voice_acceptance_plan(config)
    device = await build_device_acceptance_matrix(config)
    checks = [
        _release_check("version_aligned", "Version metadata aligned", True, f"Current version {version}."),
        _release_check("ha_connected", "Home Assistant connected", settings.ha_configured, "HA URL/token or Supervisor proxy configured."),
        _release_check("openai_configured", "OpenAI configured", settings.openai_configured, "Required for full conversational Jarvis behavior."),
        _release_check("security_pin", "Security PIN configured", bool(settings.security_pin), "Required for critical actions."),
        _release_check("voice_acceptance", "Voice acceptance ready", voice["status"] == "ready", "Wake words/sources/voice tests ready."),
        _release_check("device_acceptance", "Device acceptance broad enough", device["score"] >= 60, "Core domains detected for testing."),
        _release_check("interaction_quality", "Interaction quality healthy", interaction["score"] >= 80 or interaction["counts"]["sample_size"] == 0, "Recent commands are mostly successful."),
    ]
    return {
        "status": "ready" if all(check["pass"] for check in checks) else "attention",
        "version": version,
        "checks": checks,
        "blockers": [check["title"] for check in checks if not check["pass"]],
        "ship_rule": "Ship only after tests pass, version metadata is aligned, and live-house blockers are understood.",
    }


async def build_operational_runbook(config: AppConfig, version: str) -> dict[str, Any]:
    checklist = await build_release_checklist(config, version)
    return {
        "status": "ready",
        "version": version,
        "runbook": [
            _runbook_step("after_update", "After updating", [
                "Restart the add-on.",
                "Open TPG HomeAI through the HA sidebar as owner/admin.",
                "Check /health, Jarvis Brain, and Setup for degraded warnings.",
                "Run Sync from HA users if user/profile mapping changed.",
            ]),
            _runbook_step("acceptance_pass", "Acceptance pass", [
                "Test admin, resident, and kiosk/shared logins.",
                "Run core light, fan, lock, media, schedule, dashboard, chat, notebook, and voice checks.",
                "Verify residents cannot access system/dashboard management.",
                "Verify owner/admin can see all management menus.",
            ]),
            _runbook_step("when_something_fails", "When something fails", [
                "Open Diagnostics Support Pack.",
                "Check recent failures in Interaction Quality.",
                "Review Device Profiles and reliability suggestions.",
                "Fix mapping/config first; only change code when the behavior is reproducible.",
            ]),
            _runbook_step("feature_freeze", "Feature freeze rule", [
                "Once release checklist is ready, stop broad feature work.",
                "Only accept bug fixes, device mappings, voice tuning, UI polish, and clearly-scoped v2 requirements.",
            ]),
        ],
        "release_checklist": checklist,
    }


async def build_setup_action_plan(config: AppConfig, version: str) -> dict[str, Any]:
    release = await build_release_checklist(config, version)
    gaps = await build_capability_gap_scanner(config)
    onboarding = await build_onboarding_wizard_plan(config)
    actions: list[dict[str, Any]] = []
    for check in release.get("checks", []):
        if not check.get("ok"):
            actions.append({
                "id": f"release_{check.get('id')}",
                "title": check.get("title"),
                "detail": check.get("detail") or "Release gate needs owner attention.",
                "target": _setup_target_for_check(str(check.get("id") or "")),
                "source": "release",
                "severity": "high",
            })
    for gap in gaps.get("open_gaps", []):
        actions.append({
            "id": f"gap_{gap.get('id')}",
            "title": gap.get("title"),
            "detail": gap.get("recommendation"),
            "target": _setup_target_for_gap(str(gap.get("id") or "")),
            "source": "capability_gap",
            "severity": gap.get("severity") or "normal",
        })
    next_step = onboarding.get("next_step")
    if next_step:
        actions.append({
            "id": f"next_{next_step.get('id')}",
            "title": next_step.get("title"),
            "detail": next_step.get("detail"),
            "target": _setup_target_for_step(str(next_step.get("id") or "")),
            "source": "onboarding",
            "severity": "normal",
        })
    deduped = _dedupe_setup_actions(actions)
    return {
        "status": "ready" if not deduped else "attention",
        "version": version,
        "counts": {
            "actions": len(deduped),
            "release_blockers": sum(1 for action in deduped if action["source"] == "release"),
            "capability_gaps": sum(1 for action in deduped if action["source"] == "capability_gap"),
            "onboarding": sum(1 for action in deduped if action["source"] == "onboarding"),
        },
        "actions": deduped[:12],
        "top_actions": deduped[:6],
    }


async def build_setup_support_packet(config: AppConfig, version: str) -> dict[str, Any]:
    action_plan = await build_setup_action_plan(config, version)
    diagnostics = await build_diagnostics_support_pack(config, version)
    backup = await build_backup_recovery_readiness(config)
    integrations = await build_integration_readiness_matrix(config)
    generated_at = dt.datetime.now(dt.UTC).isoformat()
    packet = {
        "status": action_plan["status"],
        "version": version,
        "generated_at": generated_at,
        "summary": {
            "actions": action_plan.get("counts", {}).get("actions", 0),
            "release_blockers": action_plan.get("counts", {}).get("release_blockers", 0),
            "capability_gaps": action_plan.get("counts", {}).get("capability_gaps", 0),
            "onboarding": action_plan.get("counts", {}).get("onboarding", 0),
            "diagnostic_status": diagnostics.get("status"),
            "backup_status": backup.get("status"),
            "integration_status": integrations.get("status"),
        },
        "actions": action_plan.get("actions", []),
        "top_actions": action_plan.get("top_actions", []),
        "diagnostics": diagnostics,
        "backup_readiness": backup,
        "integration_matrix": integrations,
        "markdown": "",
    }
    packet["markdown"] = _setup_support_packet_markdown(packet)
    return packet


async def build_jarvis_phase_92_96(config: AppConfig, version: str) -> dict[str, Any]:
    interaction = build_interaction_quality_report(config)
    voice = build_voice_acceptance_plan(config)
    device = await build_device_acceptance_matrix(config)
    checklist = await build_release_checklist(config, version)
    runbook = await build_operational_runbook(config, version)
    score = int(round((interaction["score"] + voice["score"] + device["score"] + (100 if checklist["status"] == "ready" else 75) + 100) / 5))
    return {
        "status": "ready" if score >= 85 else "partial",
        "score": score,
        "interaction_quality": interaction,
        "voice_acceptance": voice,
        "device_acceptance": device,
        "release_checklist": checklist,
        "operational_runbook": runbook,
    }


async def build_jarvis_phase_97(config: AppConfig, version: str) -> dict[str, Any]:
    live_acceptance = await build_live_acceptance_runner(config)
    return {
        "status": live_acceptance["status"],
        "version": version,
        "phase": 97,
        "live_acceptance": live_acceptance,
        "guardrail": "Phase 97 only builds read-only probes and human-run dry-run checks; it never executes real devices.",
    }


async def build_jarvis_phase_101(config: AppConfig, version: str) -> dict[str, Any]:
    report = await build_live_acceptance_report(config, version)
    return {
        "status": report["status"],
        "version": version,
        "phase": 101,
        "acceptance_report": report,
        "guardrail": "Phase 101 exports live-house acceptance evidence without changing real devices.",
    }


async def build_jarvis_phase_103(config: AppConfig, version: str) -> dict[str, Any]:
    role_acceptance = build_role_acceptance_matrix(config)
    return {
        "status": role_acceptance["status"],
        "version": version,
        "phase": 103,
        "role_acceptance": role_acceptance,
        "guardrail": "Phase 103 validates role boundaries without granting permissions outside Home Assistant authority.",
    }


async def build_jarvis_phase_104(version: str) -> dict[str, Any]:
    repairs = build_acceptance_repair_queue()
    return {
        "status": repairs["status"],
        "version": version,
        "phase": 104,
        "acceptance_repairs": repairs,
        "guardrail": "Phase 104 creates owner-visible repair suggestions for failed acceptance evidence; it never auto-fixes devices.",
    }


async def build_jarvis_phase_105(version: str) -> dict[str, Any]:
    resolutions = build_acceptance_resolution_summary()
    return {
        "status": resolutions["status"],
        "version": version,
        "phase": 105,
        "acceptance_resolutions": resolutions,
        "guardrail": "Phase 105 only resolves repair suggestions after a human records passed acceptance evidence.",
    }


async def build_jarvis_phase_106(config: AppConfig, version: str) -> dict[str, Any]:
    report = await build_live_acceptance_report(config, version)
    return {
        "status": report["status"],
        "version": version,
        "phase": 106,
        "acceptance_packet": {
            "summary": report["summary"],
            "blockers": report["blockers"],
            "role_acceptance": report["role_acceptance"],
            "acceptance_repairs": report["acceptance_repairs"],
            "acceptance_resolutions": report["acceptance_resolutions"],
            "markdown": report["markdown"],
        },
        "guardrail": "Phase 106 exports one combined acceptance packet without executing real devices.",
    }


async def build_jarvis_phase_107(version: str) -> dict[str, Any]:
    return {
        "status": "ready",
        "version": version,
        "phase": 107,
        "ui_acceptance_packet": {
            "surface": "Brain Live Acceptance panel",
            "shows_role_acceptance": True,
            "shows_active_repairs": True,
            "shows_unrepaired_blockers": True,
            "shows_resolved_repairs": True,
            "copy_download_available": True,
        },
        "guardrail": "Phase 107 only improves owner visibility for acceptance evidence; it does not execute device actions.",
    }


async def build_jarvis_phase_108(version: str) -> dict[str, Any]:
    return {
        "status": "ready",
        "version": version,
        "phase": 108,
        "acceptance_triage_filters": {
            "surface": "Brain Live Acceptance panel",
            "default_filter": "attention",
            "filters": [
                "all",
                "attention",
                "missing_evidence",
                "passed",
                "owner",
                "resident",
                "dry_run",
                "read_only",
            ],
            "shows_match_count": True,
            "keeps_copy_download_available": True,
        },
        "guardrail": "Phase 108 only filters release acceptance evidence for owner triage; it never executes device actions.",
    }


async def build_jarvis_phase_109(config: AppConfig, version: str) -> dict[str, Any]:
    checklist = await build_release_checklist(config, version)
    return {
        "status": checklist["status"],
        "version": version,
        "phase": 109,
        "setup_release_blockers": {
            "surface": "Setup page",
            "release_status": checklist["status"],
            "failed_gates": checklist["blockers"],
            "ship_rule": checklist["ship_rule"],
            "links_to_management_pages": True,
            "uses_formal_release_checklist": True,
        },
        "guardrail": "Phase 109 only surfaces release blockers in Setup; it never changes Home Assistant or device state.",
    }


async def build_jarvis_phase_110(config: AppConfig, version: str) -> dict[str, Any]:
    runbook = await build_operational_runbook(config, version)
    return {
        "status": "ready",
        "version": version,
        "phase": 110,
        "setup_owner_runbook": {
            "surface": "Setup page",
            "sections": [step["id"] for step in runbook.get("runbook", [])],
            "uses_release_runbook": True,
            "includes_feature_freeze": any(step.get("id") == "feature_freeze" for step in runbook.get("runbook", [])),
        },
        "guardrail": "Phase 110 surfaces operational guidance only; it does not execute updates, tests, or device actions.",
    }


async def build_jarvis_phase_111(config: AppConfig, version: str) -> dict[str, Any]:
    return {
        "status": "ready",
        "version": version,
        "phase": 111,
        "setup_support_diagnostics": {
            "surface": "Setup page",
            "source_endpoint": "/ops/diagnostics",
            "safe_for_support": True,
            "secrets_redacted": True,
            "shows_counts": True,
            "shows_degraded_reasons": True,
            "copy_json_available": True,
        },
        "guardrail": "Phase 111 only exposes redacted diagnostics in Setup; it does not expose secrets or execute device actions.",
    }


async def build_jarvis_phase_112(version: str) -> dict[str, Any]:
    return {
        "status": "ready",
        "version": version,
        "phase": 112,
        "setup_backup_recovery": {
            "surface": "Setup page",
            "source_endpoint": "/ops/backup-readiness",
            "shows_automation_path": True,
            "shows_backup_pattern": True,
            "shows_config_database_paths": True,
            "shows_recommendations": True,
        },
        "guardrail": "Phase 112 only surfaces backup and recovery readiness; it does not write Home Assistant configuration.",
    }


async def build_jarvis_phase_113(version: str) -> dict[str, Any]:
    return {
        "status": "ready",
        "version": version,
        "phase": 113,
        "setup_integration_matrix": {
            "surface": "Setup page",
            "source_endpoint": "/ops/integration-matrix",
            "groups_configured_and_missing": True,
            "covers_home_assistant_ai_media_voice_camera_access": True,
            "keeps_optional_integrations_non_blocking": True,
        },
        "guardrail": "Phase 113 only reports integration readiness; it does not install integrations or modify Home Assistant.",
    }


async def build_jarvis_phase_114(version: str) -> dict[str, Any]:
    return {
        "status": "ready",
        "version": version,
        "phase": 114,
        "setup_capability_gaps": {
            "surface": "Setup page",
            "source_endpoint": "/ops/capability-gaps",
            "shows_score": True,
            "groups_by_severity": True,
            "includes_fix_hints": True,
        },
        "guardrail": "Phase 114 only surfaces readiness gaps and fix hints; it does not install integrations or change HA config.",
    }


async def build_jarvis_phase_115(version: str) -> dict[str, Any]:
    return {
        "status": "ready",
        "version": version,
        "phase": 115,
        "setup_onboarding_path": {
            "surface": "Setup page",
            "source_endpoint": "/ops/onboarding",
            "shows_next_step": True,
            "shows_required_and_recommended_steps": True,
            "keeps_steps_read_only": True,
        },
        "guardrail": "Phase 115 only surfaces ordered setup guidance; it does not auto-complete setup steps.",
    }


async def build_jarvis_phase_116(version: str) -> dict[str, Any]:
    return {
        "status": "ready",
        "version": version,
        "phase": 116,
        "setup_owner_action_checklist": {
            "surface": "Setup page",
            "sources": ["release/checklist", "ops/capability-gaps", "ops/onboarding"],
            "deduplicates_actions": True,
            "links_to_management_pages": True,
            "limits_to_top_actions": 6,
        },
        "guardrail": "Phase 116 only links owners to existing management pages; it does not perform setup actions automatically.",
    }


async def build_jarvis_phase_117(version: str) -> dict[str, Any]:
    return {
        "status": "ready",
        "version": version,
        "phase": 117,
        "setup_action_plan_api": {
            "source_endpoint": "/ops/setup-action-plan",
            "combines_release_gaps_onboarding": True,
            "deduplicates_actions": True,
            "returns_top_actions": True,
            "links_to_management_pages": True,
        },
        "guardrail": "Phase 117 creates a read-only setup action plan API; it does not execute setup actions.",
    }


async def build_jarvis_phase_118(version: str) -> dict[str, Any]:
    return {
        "status": "ready",
        "version": version,
        "phase": 118,
        "setup_support_packet": {
            "source_endpoint": "/ops/setup-support-packet",
            "formats": ["json", "markdown"],
            "includes_action_plan": True,
            "includes_support_diagnostics": True,
            "includes_backup_and_integration_readiness": True,
            "redaction_policy": "uses existing support-safe diagnostics only",
        },
        "guardrail": "Phase 118 only exports setup/readiness evidence; it does not expose secrets or execute setup actions.",
    }


async def build_jarvis_phase_119(version: str) -> dict[str, Any]:
    return {
        "status": "ready",
        "version": version,
        "phase": 119,
        "sidebar_access_diagnostics": {
            "source_endpoint": "/ops/sidebar-access",
            "validates_supervisor_ingress": True,
            "validates_panel_admin_false": True,
            "documents_admin_and_non_admin_expectations": True,
            "includes_mobile_cache_remediation": True,
        },
        "guardrail": "Phase 119 diagnoses HA sidebar access only; it does not change Home Assistant users or permissions.",
    }


async def build_jarvis_phase_120(version: str) -> dict[str, Any]:
    return {
        "status": "ready",
        "version": version,
        "phase": 120,
        "dashboard_action_plan_summary": {
            "surface": "Dashboard",
            "source_endpoint": "/ops/setup-action-plan",
            "shows_top_actions": True,
            "links_to_setup_and_management_pages": True,
            "keeps_actions_read_only": True,
        },
        "guardrail": "Phase 120 only summarizes owner actions on the dashboard; it does not execute setup or management actions.",
    }


async def build_jarvis_phase_121(version: str) -> dict[str, Any]:
    return {
        "status": "ready",
        "version": version,
        "phase": 121,
        "role_scoped_dashboard": {
            "source_endpoint": "/ops/role-dashboard",
            "owner_scope": "admin/manager users see setup and release actions.",
            "resident_scope": "resident/kiosk/guest users see personal Jarvis status and allowed actions only.",
            "admin_actions_visible_only_to_owner_scope": True,
            "scheduled_task_self_service_visible": True,
        },
        "guardrail": "Phase 121 separates dashboard visibility by resolved HA/TPG role; it does not grant permissions or run actions.",
    }


async def build_jarvis_phase_122(version: str) -> dict[str, Any]:
    return {
        "status": "ready",
        "version": version,
        "phase": 122,
        "role_dashboard_acceptance_evidence": {
            "surface": "Dashboard",
            "source_endpoint": "/ops/role-dashboard",
            "owner_scope": "admin/manager sees house-wide acceptance evidence.",
            "resident_scope": "resident/kiosk/guest sees profile-scoped acceptance evidence.",
            "shows_passed_and_failed_blocked_counts": True,
            "keeps_evidence_read_only": True,
        },
        "guardrail": "Phase 122 reports acceptance evidence on the dashboard without allowing dashboard users to mutate evidence.",
    }


async def build_jarvis_phase_123(version: str) -> dict[str, Any]:
    return {
        "status": "ready",
        "version": version,
        "phase": 123,
        "role_action_policy": {
            "source_endpoint": "/ops/role-action-policy",
            "resident_can_chat": True,
            "resident_can_create_scheduled_tasks": True,
            "resident_cannot_manage_dashboards": True,
            "resident_cannot_manage_system": True,
            "admin_can_manage_all": True,
        },
        "guardrail": "Phase 123 documents and exposes the role action policy; enforcement remains server-side in the command router.",
    }


async def build_jarvis_phase_124(version: str) -> dict[str, Any]:
    return {
        "status": "ready",
        "version": version,
        "phase": 124,
        "chat_role_policy_guidance": {
            "surface": "Chat",
            "uses_endpoint": "/ops/role-action-policy",
            "shows_allowed_actions": True,
            "shows_owner_only_denials": True,
            "resident_can_continue_conversation": True,
        },
        "guardrail": "Phase 124 makes role limits visible in Chat while keeping action enforcement server-side.",
    }


async def build_jarvis_phase_125(version: str) -> dict[str, Any]:
    return {
        "status": "ready",
        "version": version,
        "phase": 125,
        "role_aware_chat_prompts": {
            "surface": "Chat",
            "source_endpoint": "/ops/role-suggested-prompts",
            "resident_safe_examples": True,
            "owner_management_examples": True,
            "uses_role_policy": True,
        },
        "guardrail": "Phase 125 personalizes starter prompts by role without weakening server-side action policy.",
    }


async def build_jarvis_phase_126(version: str) -> dict[str, Any]:
    return {
        "status": "ready",
        "version": version,
        "phase": 126,
        "prompt_outcome_insights": {
            "source_endpoint": "/ops/role-prompt-insights",
            "source_data": "CommandLog",
            "ranks_prompts_by_success": True,
            "adds_no_new_private_storage": True,
        },
        "guardrail": "Phase 126 ranks starter prompts from existing audit history only; permissions remain unchanged.",
    }


async def build_jarvis_phase_127(version: str) -> dict[str, Any]:
    return {
        "status": "ready",
        "version": version,
        "phase": 127,
        "contextual_chat_followups": {
            "source_endpoint": "/ops/chat-followups",
            "source_data": "CommandLog",
            "role_aware": True,
            "action_safe": True,
        },
        "guardrail": "Phase 127 suggests next-step prompts only; execution still flows through policy and confirmations.",
    }


async def build_jarvis_phase_128(version: str) -> dict[str, Any]:
    return {
        "status": "ready",
        "version": version,
        "phase": 128,
        "chat_followup_preferences": {
            "source_endpoint": "/ops/chat-followups/preferences",
            "source_table": "FollowupPreference",
            "profile_scoped": True,
            "supports_pin": True,
            "supports_dismiss": True,
        },
        "guardrail": "Phase 128 personalizes Chat suggestion chips per user and assistant without changing action permissions.",
    }


def _dedupe_setup_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for action in actions:
        key = (str(action.get("title") or ""), str(action.get("target") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    return sorted(deduped, key=lambda action: _setup_severity_rank(str(action.get("severity") or "normal")))


def _setup_severity_rank(severity: str) -> int:
    return {"critical": 0, "high": 1, "normal": 2, "low": 3}.get(severity, 2)


def _setup_target_for_check(check_id: str) -> str:
    return {
        "ha_connected": "/ha",
        "openai_configured": "/assistants",
        "security_pin": "/permissions",
        "voice_acceptance": "/assistants",
        "device_acceptance": "/discovery",
        "interaction_quality": "/",
        "version_aligned": "/",
    }.get(check_id, "/jarvis")


def _setup_target_for_gap(gap_id: str) -> str:
    return {
        "home_assistant_connection": "/ha",
        "openai_key": "/assistants",
        "security_pin": "/permissions",
        "voice_sources": "/assistants",
        "wake_words": "/assistants",
        "rooms": "/rooms",
        "pending_discovery": "/discovery",
        "music_assistant": "/music",
        "weather": "/entities",
        "dashboard_assets": "/house-knowledge",
    }.get(gap_id, "/setup")


def _setup_target_for_step(step_id: str) -> str:
    return {
        "connect_ha": "/ha",
        "sync_users": "/users",
        "approve_discovery": "/discovery",
        "map_rooms": "/rooms",
        "configure_security": "/permissions",
        "configure_voice": "/assistants",
        "configure_music": "/music",
        "upload_house_assets": "/house-knowledge",
        "test_commands": "/tester",
    }.get(step_id, "/setup")


def _setup_support_packet_markdown(packet: dict[str, Any]) -> str:
    summary = packet.get("summary", {}) or {}
    lines = [
        "# TPG HomeAI Setup Support Packet",
        "",
        f"- Version: {packet.get('version')}",
        f"- Generated: {packet.get('generated_at')}",
        f"- Status: {packet.get('status')}",
        f"- Actions: {summary.get('actions', 0)}",
        f"- Release blockers: {summary.get('release_blockers', 0)}",
        f"- Capability gaps: {summary.get('capability_gaps', 0)}",
        f"- Onboarding items: {summary.get('onboarding', 0)}",
        f"- Diagnostics: {summary.get('diagnostic_status', 'unknown')}",
        f"- Backup readiness: {summary.get('backup_status', 'unknown')}",
        f"- Integration readiness: {summary.get('integration_status', 'unknown')}",
        "",
        "## Top Actions",
        "",
    ]
    top_actions = packet.get("top_actions", []) or []
    if top_actions:
        for action in top_actions:
            lines.append(f"- [{str(action.get('severity') or 'normal').upper()}] {action.get('title')}")
            lines.append(f"  - Detail: {action.get('detail')}")
            lines.append(f"  - Source: {action.get('source')}")
            lines.append(f"  - Target: {action.get('target')}")
    else:
        lines.append("- None")
    lines.extend(["", "## Integration Matrix", ""])
    integrations = packet.get("integration_matrix", {}).get("integrations", []) or []
    if integrations:
        for item in integrations:
            lines.append(f"- [{str(item.get('status') or 'unknown').upper()}] {item.get('name')}")
            lines.append(f"  - Detail: {item.get('detail')}")
    else:
        lines.append("- No integrations reported")
    lines.extend(["", "## Backup Readiness", ""])
    backup = packet.get("backup_readiness", {}) or {}
    for check in backup.get("checks", []) or []:
        marker = "PASS" if check.get("ok") else "ATTENTION"
        lines.append(f"- [{marker}] {check.get('title')}: {check.get('detail')}")
    lines.extend(["", "## Support Diagnostics", ""])
    diagnostics = packet.get("diagnostics", {}) or {}
    diag_summary = diagnostics.get("summary", {}) or {}
    for key, value in diag_summary.items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def _command_card(row: CommandLog) -> dict[str, Any]:
    return {
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "assistant": row.assistant,
        "user": row.user,
        "message": row.message,
        "intent": row.intent,
        "success": row.success,
        "executed": row.executed,
        "error": row.error,
        "data": _safe_json(row.data),
    }


def _safe_json(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _acceptance_run_card(row: AcceptanceRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "test_id": row.test_id,
        "status": row.status,
        "assistant": row.assistant,
        "user": row.user,
        "notes": row.notes,
        "evidence": _safe_json(row.evidence),
        "version": row.version,
    }


def _suggestion_card(row: Suggestion) -> dict[str, Any]:
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "title": row.title,
        "message": row.message,
        "category": row.category,
        "priority": row.priority,
        "action_type": row.action_type,
        "payload": _safe_json(row.payload),
        "status": row.status,
    }


def _resolve_acceptance_repairs(session, test_id: str) -> int:
    if not test_id:
        return 0
    rows = session.query(Suggestion).filter(
        Suggestion.category == "acceptance",
        Suggestion.action_type == "acceptance_repair",
        Suggestion.status.in_(["suggested", "draft", "edited"]),
    ).all()
    resolved = 0
    for row in rows:
        payload = _safe_json(row.payload)
        if payload.get("test_id") != test_id:
            continue
        row.status = "resolved"
        resolved += 1
    return resolved


def _live_acceptance_report_markdown(report: dict[str, Any], tests: list[dict[str, Any]]) -> str:
    latest_by_test = report.get("latest_by_test", {}) or {}
    summary = report.get("summary", {}) or {}
    role_acceptance = report.get("role_acceptance", {}) or {}
    repairs = report.get("acceptance_repairs", {}) or {}
    resolutions = report.get("acceptance_resolutions", {}) or {}
    lines = [
        "# TPG HomeAI Live Acceptance Report",
        "",
        f"- Version: {report.get('version')}",
        f"- Generated: {report.get('generated_at')}",
        f"- Status: {report.get('status')}",
        f"- Evidence results: {summary.get('evidence_results', 0)}",
        f"- Passed checks: {summary.get('passed', 0)}/{summary.get('required_passes', 0)} required",
        f"- Failed or blocked checks: {summary.get('failed_or_blocked', 0)}",
        "",
        "## Policy",
        "",
        f"- Read-only runner: {report.get('policy', {}).get('read_only')}",
        f"- Executes actions: {report.get('policy', {}).get('executes_actions')}",
        f"- Human-run mutating tests required: {report.get('policy', {}).get('requires_human_to_run_mutating_tests')}",
        "",
        "## Blockers",
        "",
    ]
    blockers = report.get("blockers", []) or []
    if blockers:
        lines.extend(f"- {blocker}" for blocker in blockers)
    else:
        lines.append("- None")
    lines.extend(["", "## Tests", ""])
    for test in tests:
        result = latest_by_test.get(test["id"], {})
        status = result.get("status", "not_recorded")
        notes = result.get("notes") or test.get("expected_result") or ""
        lines.append(f"- [{status.upper()}] {test.get('title')} (`{test.get('id')}`)")
        lines.append(f"  - Mode: {test.get('mode')}")
        lines.append(f"  - Domain: {test.get('domain')}")
        lines.append(f"  - Notes: {notes}")
    lines.extend([
        "",
        "## Role Acceptance",
        "",
        f"- Status: {role_acceptance.get('status', 'unknown')}",
        f"- Score: {role_acceptance.get('score', 0)}%",
    ])
    for check_item in role_acceptance.get("checks", []) or []:
        marker = "PASS" if check_item.get("pass") else ("OPTIONAL" if not check_item.get("required") else "ATTENTION")
        lines.append(f"- [{marker}] {check_item.get('title')} (`{check_item.get('role')}`)")
    repair_summary = repairs.get("summary", {}) or {}
    resolution_summary = resolutions.get("summary", {}) or {}
    lines.extend([
        "",
        "## Repair Queue",
        "",
        f"- Failed or blocked checks: {repair_summary.get('failed_or_blocked', 0)}",
        f"- Active repairs: {repair_summary.get('active_repairs', 0)}",
        f"- Unrepaired checks: {repair_summary.get('unrepaired', 0)}",
    ])
    for test_id in repairs.get("unrepaired_test_ids", []) or []:
        lines.append(f"- Unrepaired: `{test_id}`")
    lines.extend([
        "",
        "## Resolution Loop",
        "",
        f"- Resolved repairs: {resolution_summary.get('resolved_repairs', 0)}",
        f"- Latest passed checks: {resolution_summary.get('latest_passed_tests', 0)}",
        f"- Latest failed or blocked checks: {resolution_summary.get('latest_failed_or_blocked_tests', 0)}",
    ])
    lines.extend([
        "",
        "## Stop Line",
        "",
        "Call live-house deployment complete only after enough required checks pass and no failed or blocked checks remain.",
    ])
    return "\n".join(lines)


def _role_acceptance_check(
    identifier: str,
    title: str,
    passed: bool,
    role: str,
    expectations: list[str],
    blocker: str,
    optional: bool = False,
) -> dict[str, Any]:
    return {
        "id": identifier,
        "title": title,
        "role": role,
        "required": not optional,
        "pass": bool(passed),
        "status": "pass" if passed else ("optional" if optional else "attention"),
        "expectations": expectations,
        "blocker": "" if passed or optional else blocker,
    }


def _role_user_card(user: Any, assistant_owner_ids: set[str]) -> dict[str, Any]:
    return {
        "id": user.id,
        "name": user.name,
        "role": user.role,
        "ha_username": user.ha_username,
        "ha_is_admin": user.ha_is_admin,
        "access_source": user.access_source,
        "has_personal_assistant": user.id in assistant_owner_ids,
        "can_use_general_chat": True,
        "can_create_scheduled_tasks": user.role in {"admin", "manager", "resident", "kiosk"},
        "can_create_dashboards": user.role in {"admin", "manager"},
        "can_manage_users": user.role == "admin",
        "can_manage_system": user.role in {"admin", "manager"},
    }


def _interaction_recommendations(total: int, failed: list[CommandLog], confusion: list[CommandLog]) -> list[str]:
    recommendations = []
    if total == 0:
        recommendations.append("Run an acceptance chat session so the quality report has data.")
    if failed:
        recommendations.append("Review recent failed commands and approve device strategy repairs where available.")
    if confusion:
        recommendations.append("Turn repeated corrections into approved memory or device aliases.")
    return recommendations


def _acceptance(test_id: str, title: str) -> dict[str, Any]:
    return {"id": test_id, "title": title, "required": True}


def _voice_blockers(counts: dict[str, Any]) -> list[str]:
    blockers = []
    if counts.get("total", 0) <= 0:
        blockers.append("No voice source profiles configured.")
    if counts.get("missing_source_identity", 0) > 0:
        blockers.append("Some voice sources are missing source_device_id/source_entity_id.")
    if counts.get("assistants_with_wake_words", 0) < counts.get("assistants", 0):
        blockers.append("Some assistant profiles are missing wake words.")
    if counts.get("assistants_with_linked_sources", 0) < counts.get("assistants", 0):
        blockers.append("Some assistants are not linked to a real voice source.")
    return blockers


def _domain_check(domain: str, title: str, domains: Counter[str]) -> dict[str, Any]:
    count = domains.get(domain, 0)
    return {"domain": domain, "title": title, "available": count > 0, "count": count}


def _live_acceptance_case(
    test_id: str,
    title: str,
    mode: str,
    domain: str,
    states: dict[str, Any],
    domains: Counter[str],
    required_role: str,
    command_example: str,
    expected_verification: str,
    *,
    sensitive: bool = False,
) -> dict[str, Any]:
    sample = _sample_entity(domain, states)
    available = domain in ("system", "conversation", "automation", "dashboard") or domains.get(domain, 0) > 0
    status = "ready" if available else "blocked"
    return {
        "id": test_id,
        "title": title,
        "mode": mode,
        "domain": domain,
        "status": status,
        "available": available,
        "sensitive": sensitive,
        "required_role": required_role,
        "sample_entity_id": sample.get("entity_id"),
        "sample_name": sample.get("name"),
        "command_example": command_example,
        "expected_verification": expected_verification,
        "requires_confirmation": sensitive or domain in ("dashboard", "automation"),
        "executes_actions": False,
        "blocker": None if available else f"No available {domain} entity was found for live acceptance.",
    }


def _sample_entity(domain: str, states: dict[str, Any]) -> dict[str, Any]:
    if domain in ("system", "conversation", "automation", "dashboard"):
        return {}
    for entity_id, state in sorted(states.items()):
        if getattr(state, "domain", "") != domain:
            continue
        attrs = getattr(state, "attributes", {}) or {}
        return {
            "entity_id": entity_id,
            "name": attrs.get("friendly_name") or getattr(state, "name", None) or entity_id,
        }
    return {}


def _next_live_acceptance_action(tests: list[dict[str, Any]]) -> str:
    blocked = next((test for test in tests if test["status"] == "blocked"), None)
    if blocked:
        return f"Map or enable a {blocked['domain']} entity, then rerun live acceptance."
    dry_run = next((test for test in tests if test["mode"] == "dry_run_required"), None)
    if dry_run:
        return f"Human-run acceptance next: {dry_run['command_example']}"
    return "All live acceptance probes are ready; run the checklist from real owner/resident/kiosk sessions."


def _release_check(check_id: str, title: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"id": check_id, "title": title, "pass": bool(passed), "detail": detail}


def _runbook_step(step_id: str, title: str, actions: list[str]) -> dict[str, Any]:
    return {"id": step_id, "title": title, "actions": actions}
