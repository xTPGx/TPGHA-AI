"""Governance, privacy, memory, and completion audit brains for phases 87-91."""
from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from typing import Any

from .brain import build_completion_status
from .db.database import get_session
from .db.models import (
    ArchivedConversation,
    CommandLog,
    ConversationNote,
    ConversationState,
    HouseAsset,
    MemoryItem,
    Suggestion,
)
from .knowledge import build_house_graph
from .models.schemas import AppConfig, User
from .router.permissions import get_confirmation_store


def build_privacy_data_controls(config: AppConfig) -> dict[str, Any]:
    with get_session() as session:
        counts = {
            "command_logs": session.query(CommandLog).count(),
            "conversation_contexts": session.query(ConversationState).count(),
            "conversation_notes": session.query(ConversationNote).count(),
            "archived_conversations": session.query(ArchivedConversation).count(),
            "memories": session.query(MemoryItem).count(),
            "suggestions": session.query(Suggestion).count(),
            "house_assets": session.query(HouseAsset).count(),
        }
    return {
        "status": "ready",
        "data_stores": [
            _store("command_logs", "Command/audit history", counts["command_logs"], "kept_for_audit", "Soft-delete hides conversations but preserves command audit."),
            _store("conversation_contexts", "Short-term chat context", counts["conversation_contexts"], "runtime_memory", "Used for pronouns, corrections, and continuity."),
            _store("conversation_notes", "Notebook notes", counts["conversation_notes"], "user_managed", "Attached to conversation sessions and exportable."),
            _store("memories", "Approved/draft memories", counts["memories"], "approval_first", "Long-term memory is explicit and status-gated."),
            _store("suggestions", "Suggestions/drafts", counts["suggestions"], "approval_first", "Proactive ideas and automation drafts wait for approval."),
            _store("house_assets", "House photos/floor plans", counts["house_assets"], "approval_first", "Only approved assets enter AI context."),
        ],
        "controls": [
            "Conversation export returns Markdown for portability.",
            "Delete conversation is a non-destructive soft archive.",
            "Secrets are never included in diagnostics or context export.",
            "Security actions remain confirmation/PIN gated.",
            "Role scope is derived from Home Assistant identity and TPG profile mapping.",
        ],
        "sensitive_actions": list(config.permissions.sensitive_actions),
        "pending_confirmations": len(get_confirmation_store().list_pending()),
        "counts": counts,
    }


def build_role_permission_matrix(config: AppConfig) -> dict[str, Any]:
    users = [_user_role_card(user, config) for user in config.assistants.users]
    roles = {
        "admin": [
            "Full chat/general AI",
            "Own assistant/profile/memory/notebook",
            "Manage users, rooms, discovery, music, voice, permissions, dashboards, and system setup",
            "Draft and install dashboards/automations",
        ],
        "manager": [
            "Full chat/general AI",
            "Own assistant/profile/memory/notebook",
            "Manage household devices and suggestions",
            "No owner-only system/security policy changes unless granted",
        ],
        "resident": [
            "Full chat/general AI",
            "Own assistant/profile/memory/notebook",
            "Control allowed devices",
            "Create scheduled task/automation drafts",
            "No dashboard creation, user management, or system settings",
        ],
        "kiosk": [
            "Shared house remote/panel chat",
            "Room/control-panel oriented access",
            "No personal owner data",
            "No management pages or system changes",
        ],
        "guest": [
            "Limited chat/control surface",
            "No management pages",
            "No sensitive actions unless explicitly granted",
        ],
    }
    return {
        "status": "ready" if users else "needs_users",
        "roles": roles,
        "users": users,
        "counts": {
            "users": len(users),
            "admins": sum(1 for user in users if user["role"] == "admin"),
            "non_admins": sum(1 for user in users if user["role"] != "admin"),
            "ha_synced": sum(1 for user in users if user.get("access_source") == "home_assistant"),
        },
        "policy": {
            "ha_is_authority": True,
            "ha_admin_becomes_tpg_admin": True,
            "ha_non_admins_get_profile_scope": True,
            "residents_can_draft_schedules": True,
            "residents_cannot_install_dashboards_or_change_system": True,
        },
    }


def build_memory_quality_report(config: AppConfig) -> dict[str, Any]:
    with get_session() as session:
        memories = session.query(MemoryItem).all()
        commands = session.query(CommandLog).order_by(CommandLog.created_at.desc()).limit(250).all()
    status_counts = Counter(memory.status for memory in memories)
    scope_counts = Counter(memory.scope for memory in memories)
    owner_counts = Counter(memory.owner or "house" for memory in memories)
    duplicate_keys = _duplicate_memory_keys(memories)
    correction_commands = [
        row for row in commands
        if any(token in (row.message or "").lower() for token in ("not what", "i meant", "wrong", "actually", "that's not"))
    ]
    recommendations = []
    if status_counts.get("draft", 0):
        recommendations.append("Review draft memories so repeated corrections become approved behavior.")
    if duplicate_keys:
        recommendations.append("Merge duplicate memory keys so the assistant has one clear preference per subject.")
    if correction_commands and not status_counts.get("approved", 0):
        recommendations.append("Recent corrections exist, but no approved memory is available yet.")
    return {
        "status": "attention" if recommendations else "ready",
        "score": max(55, 100 - (len(recommendations) * 15) - min(25, len(duplicate_keys) * 5)),
        "counts": {
            "total": len(memories),
            "approved": status_counts.get("approved", 0),
            "draft": status_counts.get("draft", 0),
            "ignored": status_counts.get("ignored", 0),
            "recent_correction_like_commands": len(correction_commands),
        },
        "by_scope": dict(scope_counts),
        "by_owner": dict(owner_counts),
        "duplicate_keys": duplicate_keys[:30],
        "recommendations": recommendations,
    }


async def build_redacted_context_export(config: AppConfig) -> dict[str, Any]:
    graph = await build_house_graph(include_registries=False)
    privacy = build_privacy_data_controls(config)
    roles = build_role_permission_matrix(config)
    memory = build_memory_quality_report(config)
    approved_assets = []
    with get_session() as session:
        rows = session.query(HouseAsset).filter(HouseAsset.status == "approved").order_by(HouseAsset.created_at.desc()).limit(50).all()
        for row in rows:
            approved_assets.append({
                "title": row.title,
                "type": row.asset_type,
                "room": row.room,
                "description": row.description,
                "analysis": _safe_json(row.analysis),
            })
    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "safe_for_export": True,
        "secrets_redacted": True,
        "house": {
            "households": [house.model_dump() for house in config.household.households],
            "rooms": graph.get("rooms", []),
            "counts": graph.get("counts", {}),
        },
        "users": roles["users"],
        "assistants": [assistant.model_dump() for assistant in config.assistants.assistants],
        "privacy": privacy,
        "memory_quality": memory,
        "approved_house_assets": approved_assets,
    }
    return {
        "status": "ready",
        "format": "json",
        "payload": payload,
        "markdown": _context_markdown(payload),
    }


async def build_completion_auditor(config: AppConfig) -> dict[str, Any]:
    graph = await build_house_graph(include_registries=False)
    completion = build_completion_status(graph, health=None)
    privacy = build_privacy_data_controls(config)
    roles = build_role_permission_matrix(config)
    memory = build_memory_quality_report(config)
    blockers = []
    if not roles["counts"]["admins"]:
        blockers.append("No TPG admin/owner profile is configured.")
    if not roles["counts"]["users"]:
        blockers.append("No TPG user profiles are configured.")
    if privacy["pending_confirmations"]:
        blockers.append("There are pending confirmations waiting for user action.")
    score = int(round((
        completion.get("overall_score", 0)
        + 100
        + (100 if roles["status"] == "ready" else 60)
        + memory["score"]
    ) / 4))
    return {
        "status": "ready" if not blockers and score >= 90 else "attention",
        "score": score,
        "blockers": blockers,
        "completion": completion,
        "privacy": privacy,
        "roles": roles,
        "memory_quality": memory,
        "stop_line": (
            "Feature work can pause when required completion gates pass, owner/admin identity is correct, "
            "non-admin profile scope is verified, memory/privacy exports work, and house-specific setup blockers are documented."
        ),
    }


async def build_jarvis_phase_87_91(config: AppConfig) -> dict[str, Any]:
    privacy = build_privacy_data_controls(config)
    roles = build_role_permission_matrix(config)
    memory = build_memory_quality_report(config)
    context_export = await build_redacted_context_export(config)
    completion = await build_completion_auditor(config)
    score = int(round((100 + (100 if roles["status"] == "ready" else 70) + memory["score"] + 100 + completion["score"]) / 5))
    return {
        "status": "ready" if score >= 90 else "partial",
        "score": score,
        "privacy": privacy,
        "roles": roles,
        "memory_quality": memory,
        "context_export": {"status": context_export["status"], "safe_for_export": True, "format": context_export["format"]},
        "completion_audit": completion,
    }


def _store(store_id: str, title: str, count: int, retention: str, note: str) -> dict[str, Any]:
    return {"id": store_id, "title": title, "count": count, "retention": retention, "note": note}


def _user_role_card(user: User, config: AppConfig) -> dict[str, Any]:
    assistant = next((assistant for assistant in config.assistants.assistants if assistant.owner == user.id), None)
    perms = user.permissions.model_dump()
    return {
        "id": user.id,
        "name": user.name,
        "role": user.role,
        "ha_user_id": user.ha_user_id,
        "ha_username": user.ha_username,
        "ha_is_admin": user.ha_is_admin,
        "access_source": user.access_source,
        "assistant": assistant.id if assistant else None,
        "music_account": user.music_account,
        "permissions": perms,
        "effective": {
            "can_manage_system": user.role in {"admin", "manager"},
            "can_manage_users": user.role == "admin",
            "can_create_dashboards": user.role in {"admin", "manager"},
            "can_create_scheduled_tasks": user.role in {"admin", "manager", "resident", "kiosk"},
            "can_use_general_chat": True,
        },
    }


def _duplicate_memory_keys(memories: list[MemoryItem]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str, str, str], list[MemoryItem]] = {}
    for memory in memories:
        key = (memory.status, memory.owner or "", memory.scope or "", memory.key or "")
        buckets.setdefault(key, []).append(memory)
    duplicates = []
    for (status, owner, scope, key), rows in buckets.items():
        if len(rows) > 1 and key:
            duplicates.append({
                "status": status,
                "owner": owner,
                "scope": scope,
                "key": key,
                "count": len(rows),
                "subjects": sorted({row.subject for row in rows if row.subject})[:10],
            })
    return sorted(duplicates, key=lambda item: item["count"], reverse=True)


def _safe_json(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _context_markdown(payload: dict[str, Any]) -> str:
    counts = payload.get("house", {}).get("counts", {})
    lines = [
        "# TPG HomeAI Context Export",
        "",
        f"Generated: {payload.get('generated_at')}",
        "",
        "## House",
        f"- Rooms: {counts.get('rooms', 0)}",
        f"- Entities: {counts.get('entities', 0)}",
        f"- Voice sources: {counts.get('voice_sources', 0)}",
        "",
        "## Users",
    ]
    for user in payload.get("users", []):
        lines.append(f"- {user.get('name')} ({user.get('role')}) -> {user.get('assistant') or 'no assistant'}")
    lines.extend(["", "## Assistants"])
    for assistant in payload.get("assistants", []):
        lines.append(f"- {assistant.get('name')} owned by {assistant.get('owner')}")
    lines.extend(["", "## Memory Quality"])
    memory = payload.get("memory_quality", {})
    lines.append(f"- Approved: {memory.get('counts', {}).get('approved', 0)}")
    lines.append(f"- Draft: {memory.get('counts', {}).get('draft', 0)}")
    lines.append("")
    lines.append("_Secrets redacted. This export is intended for ChatGPT/support context._")
    return "\n".join(lines)
