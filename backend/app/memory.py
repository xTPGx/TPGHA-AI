"""Memory and proactive suggestion store."""
from __future__ import annotations

import json
from typing import Any

from .db.database import get_session
from .db.models import CommandLog, MemoryItem, Suggestion
from .knowledge import build_house_graph


def _memory_dict(row: MemoryItem) -> dict[str, Any]:
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "scope": row.scope,
        "owner": row.owner,
        "subject": row.subject,
        "key": row.key,
        "value": row.value,
        "source": row.source,
        "status": row.status,
    }


def _suggestion_dict(row: Suggestion) -> dict[str, Any]:
    try:
        payload = json.loads(row.payload or "{}")
    except json.JSONDecodeError:
        payload = {}
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "title": row.title,
        "message": row.message,
        "category": row.category,
        "priority": row.priority,
        "action_type": row.action_type,
        "payload": payload,
        "status": row.status,
    }


def list_memories(status: str | None = None, owner: str | None = None) -> list[dict[str, Any]]:
    with get_session() as session:
        q = session.query(MemoryItem).order_by(MemoryItem.created_at.desc())
        if status:
            q = q.filter(MemoryItem.status == status)
        if owner is not None:
            q = q.filter(MemoryItem.owner == owner)
        return [_memory_dict(row) for row in q.all()]


def propose_memory(scope: str, subject: str, key: str, value: str,
                   owner: str = "", source: str = "conversation") -> dict[str, Any]:
    with get_session() as session:
        row = MemoryItem(scope=scope, owner=owner, subject=subject, key=key,
                         value=value, source=source, status="draft")
        session.add(row)
        session.commit()
        return _memory_dict(row)


def propose_correction_memory(user: str, message: str, result: Any) -> dict[str, Any] | None:
    """Draft memory from a successful correction without auto-learning it."""
    resolved = getattr(result, "resolved", {}) or {}
    subject = resolved.get("label") or resolved.get("target") or resolved.get("entity_id")
    if not subject:
        return None
    value = f"When user corrected with '{message}', resolve to {subject}."
    with get_session() as session:
        existing = session.query(MemoryItem).filter(
            MemoryItem.status.in_(["draft", "approved"]),
            MemoryItem.owner == (user or ""),
            MemoryItem.subject == str(subject),
            MemoryItem.key == "correction_routing",
            MemoryItem.value == value,
        ).first()
        if existing:
            return _memory_dict(existing)
        row = MemoryItem(
            scope="user",
            owner=user or "",
            subject=str(subject),
            key="correction_routing",
            value=value,
            source="correction",
            status="draft",
        )
        session.add(row)
        session.commit()
        return _memory_dict(row)


def approve_memory(memory_id: int) -> dict[str, Any]:
    with get_session() as session:
        row = session.get(MemoryItem, memory_id)
        if row is None:
            raise KeyError(memory_id)
        row.status = "approved"
        session.commit()
        return _memory_dict(row)


def approved_memory_value(scope: str, subject: str, key: str) -> str:
    with get_session() as session:
        row = session.query(MemoryItem).filter(
            MemoryItem.scope == scope,
            MemoryItem.subject == subject,
            MemoryItem.key == key,
            MemoryItem.status == "approved",
        ).order_by(MemoryItem.updated_at.desc(), MemoryItem.id.desc()).first()
        return row.value if row else ""


def ignore_memory(memory_id: int) -> dict[str, Any]:
    with get_session() as session:
        row = session.get(MemoryItem, memory_id)
        if row is None:
            raise KeyError(memory_id)
        row.status = "ignored"
        session.commit()
        return _memory_dict(row)


def approved_memory_context(limit: int = 30) -> str:
    memories = list_memories(status="approved")[:limit]
    if not memories:
        return "Approved memory: none yet."
    lines = ["Approved memory:"]
    for item in memories:
        who = f"{item['owner']} " if item.get("owner") else ""
        subject = item.get("subject") or item.get("scope")
        lines.append(f"- {who}{subject}: {item.get('key')} = {item.get('value')}")
    return "\n".join(lines)


def _suggestion_exists(session, category: str, action_type: str, title: str) -> bool:
    return session.query(Suggestion).filter(
        Suggestion.category == category,
        Suggestion.action_type == action_type,
        Suggestion.title == title,
        Suggestion.status.in_(["suggested", "draft", "edited"]),
    ).first() is not None


def _add_suggestion(session, *, title: str, message: str, category: str,
                    priority: str = "normal", action_type: str = "",
                    payload: dict[str, Any] | None = None) -> None:
    if _suggestion_exists(session, category, action_type, title):
        return
    session.add(Suggestion(
        title=title,
        message=message,
        category=category,
        priority=priority,
        action_type=action_type,
        payload=json.dumps(payload or {}),
        status="suggested",
    ))


def propose_user_setup_suggestion(username: str, source: str = "ha_user") -> dict[str, Any] | None:
    username = " ".join(str(username or "").split())
    if not username:
        return None
    title = f"Set up TPG AI profile for {username}"
    with get_session() as session:
        before = _suggestion_exists(session, "user_setup", "create_user_profile", title)
        _add_suggestion(
            session,
            title=title,
            message=(
                f"Home Assistant reported a user named {username}, but TPG HomeAI "
                "does not have a matching profile yet."
            ),
            category="user_setup",
            priority="high",
            action_type="create_user_profile",
            payload={"username": username, "source": source},
        )
        session.commit()
        if before:
            return None
        row = session.query(Suggestion).filter(
            Suggestion.category == "user_setup",
            Suggestion.action_type == "create_user_profile",
            Suggestion.title == title,
        ).order_by(Suggestion.created_at.desc()).first()
        return _suggestion_dict(row) if row else None


async def generate_suggestions() -> dict[str, Any]:
    graph = await build_house_graph(include_registries=True)
    created = 0
    with get_session() as session:
        if graph.get("pending_approvals", 0):
            _add_suggestion(
                session,
                title="Review discovered Home Assistant entities",
                message=f"{graph['pending_approvals']} entities need approval, mapping, or ignore.",
                category="discovery",
                priority="normal",
                action_type="open_discovery",
                payload={"pending": graph["pending_approvals"]},
            )
            created += 1
        if graph.get("unavailable_devices", 0):
            _add_suggestion(
                session,
                title="Review unavailable devices",
                message=f"{graph['unavailable_devices']} known entities are unavailable.",
                category="maintenance",
                priority="normal",
                action_type="review_unavailable",
                payload={"unavailable": graph["unavailable_devices"]},
            )
            created += 1

        mobile_devices = [
            d for d in graph.get("devices", [])
            if any(k in (d.get("name") or "").lower() for k in ("iphone", "ipad", "watch", "android"))
        ]
        for d in mobile_devices[:10]:
            diagnostics = d.get("diagnostic_entities", [])
            if len(diagnostics) >= 3:
                _add_suggestion(
                    session,
                    title=f"Group {d['name']} as a personal device",
                    message=(
                        f"{d['name']} has {len(diagnostics)} diagnostic entities. "
                        "Treat it as one personal device instead of many devices."
                    ),
                    category="personal_device",
                    priority="normal",
                    action_type="group_personal_device",
                    payload={"device": d},
                )
                created += 1

        if graph.get("rooms"):
            _add_suggestion(
                session,
                title="Create a TPG Home dashboard",
                message="Generate a clean Lovelace dashboard from approved rooms and devices.",
                category="dashboard",
                priority="normal",
                action_type="dashboard_draft",
                payload={"style": "native"},
            )
            created += 1

        created += _mine_command_routines(session)
        session.commit()

    return {"created_candidates": created, "suggestions": list_suggestions()}


def _mine_command_routines(session) -> int:
    rows = session.query(CommandLog).filter(
        CommandLog.success.is_(True),
        CommandLog.executed.is_(True),
    ).order_by(CommandLog.created_at.desc()).limit(250).all()
    buckets: dict[tuple[str, str], list[CommandLog]] = {}
    for row in rows:
        target = ""
        try:
            resolved = json.loads(row.resolved or "{}")
            target = (
                resolved.get("label")
                or resolved.get("target")
                or resolved.get("entity_id")
                or resolved.get("door")
                or ""
            )
        except json.JSONDecodeError:
            target = ""
        if not row.intent or row.intent in {"unlock_door", "explain_last_action"}:
            continue
        key = (row.intent, str(target))
        buckets.setdefault(key, []).append(row)

    created = 0
    for (intent, target), items in buckets.items():
        if len(items) < 3:
            continue
        hours = [i.created_at.hour for i in items if i.created_at]
        if not hours:
            continue
        common_hour = max(set(hours), key=hours.count)
        if hours.count(common_hour) < 2:
            continue
        title = f"Consider automating {intent.replace('_', ' ')} for {target or 'this device'}"
        _add_suggestion(
            session,
            title=title,
            message=(
                f"You have run {intent.replace('_', ' ')} for {target or 'this target'} "
                f"{len(items)} times recently, often around {common_hour:02d}:00."
            ),
            category="routine_mining",
            priority="normal",
            action_type="automation_draft",
            payload={
                "intent": intent,
                "target": target,
                "observed_count": len(items),
                "suggested_hour": common_hour,
            },
        )
        created += 1
    return created


def list_suggestions(status: str | None = None) -> list[dict[str, Any]]:
    with get_session() as session:
        q = session.query(Suggestion).order_by(Suggestion.created_at.desc())
        if status:
            q = q.filter(Suggestion.status == status)
        return [_suggestion_dict(row) for row in q.all()]


def update_suggestion(suggestion_id: int, status: str) -> dict[str, Any]:
    with get_session() as session:
        row = session.get(Suggestion, suggestion_id)
        if row is None:
            raise KeyError(suggestion_id)
        row.status = status
        if status == "approved":
            _apply_suggestion_approval(session, row)
        session.commit()
        return _suggestion_dict(row)


def _apply_suggestion_approval(session, row: Suggestion) -> None:
    if row.category != "repair" or row.action_type != "device_profile_fix":
        return
    try:
        payload = json.loads(row.payload or "{}")
    except json.JSONDecodeError:
        payload = {}
    memory = payload.get("proposed_memory") or {}
    if not memory:
        return
    scope = str(memory.get("scope") or "device")
    subject = str(memory.get("subject") or "")
    key = str(memory.get("key") or "")
    value = memory.get("value")
    if not subject or not key or value is None:
        return
    value_text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    existing = session.query(MemoryItem).filter(
        MemoryItem.scope == scope,
        MemoryItem.subject == subject,
        MemoryItem.key == key,
        MemoryItem.status == "approved",
    ).first()
    if existing:
        existing.value = value_text
        existing.source = "reliability_brain"
        existing.updated_at = row.created_at
        return
    session.add(MemoryItem(
        scope=scope,
        owner=str(memory.get("owner") or ""),
        subject=subject,
        key=key,
        value=value_text,
        source="reliability_brain",
        status="approved",
    ))
