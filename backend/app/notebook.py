"""Conversation notebook: sessions, notes, and exportable transcripts."""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from sqlalchemy import desc, func

from .db.database import get_session
from .db.models import ArchivedConversation, CommandLog, ConversationNote


def list_conversations(limit: int = 50, assistant: str | None = None,
                       user: str | None = None) -> list[dict[str, Any]]:
    limit = max(1, min(200, int(limit or 50)))
    with get_session() as session:
        archived_ids = {
            row.conversation_id
            for row in session.query(ArchivedConversation.conversation_id).all()
        }
        query = session.query(CommandLog).filter(CommandLog.conversation_id != "")
        if archived_ids:
            query = query.filter(~CommandLog.conversation_id.in_(archived_ids))
        if assistant:
            query = query.filter(CommandLog.assistant == assistant)
        if user:
            query = query.filter(CommandLog.user == user)
        rows = query.order_by(desc(CommandLog.created_at), desc(CommandLog.id)).limit(1000).all()
        note_counts = {
            row.conversation_id: row.count
            for row in session.query(
                ConversationNote.conversation_id,
                func.count(ConversationNote.id).label("count"),
            ).group_by(ConversationNote.conversation_id).all()
        }

    grouped: dict[str, list[CommandLog]] = defaultdict(list)
    for row in rows:
        grouped[row.conversation_id].append(row)

    conversations = []
    for conversation_id, items in grouped.items():
        ordered = sorted(items, key=lambda item: (item.created_at, item.id))
        first = ordered[0]
        last = ordered[-1]
        conversations.append({
            "conversation_id": conversation_id,
            "assistant": last.assistant,
            "user": last.user,
            "started_at": first.created_at.isoformat() if first.created_at else None,
            "updated_at": last.created_at.isoformat() if last.created_at else None,
            "message_count": len(ordered),
            "note_count": int(note_counts.get(conversation_id, 0)),
            "title": _title_for(ordered),
            "last_message": last.response_message or last.message,
        })
    return sorted(conversations, key=lambda item: item.get("updated_at") or "", reverse=True)[:limit]


def archive_conversation(conversation_id: str) -> dict[str, Any]:
    conversation_id = (conversation_id or "").strip()
    if not conversation_id:
        raise ValueError("Conversation ID is required.")
    with get_session() as session:
        existing = session.query(ArchivedConversation).filter(
            ArchivedConversation.conversation_id == conversation_id
        ).first()
        if existing:
            return {
                "conversation_id": conversation_id,
                "archived_at": existing.archived_at.isoformat() if existing.archived_at else None,
                "already_archived": True,
            }
        archived = ArchivedConversation(conversation_id=conversation_id)
        session.add(archived)
        session.commit()
        session.refresh(archived)
        return {
            "conversation_id": conversation_id,
            "archived_at": archived.archived_at.isoformat() if archived.archived_at else None,
            "already_archived": False,
        }


def unarchive_conversation(conversation_id: str) -> bool:
    conversation_id = (conversation_id or "").strip()
    if not conversation_id:
        return False
    with get_session() as session:
        row = session.query(ArchivedConversation).filter(
            ArchivedConversation.conversation_id == conversation_id
        ).first()
        if not row:
            return False
        session.delete(row)
        session.commit()
        return True


def conversation_detail(conversation_id: str) -> dict[str, Any]:
    with get_session() as session:
        rows = session.query(CommandLog).filter(
            CommandLog.conversation_id == conversation_id
        ).order_by(CommandLog.created_at, CommandLog.id).all()
        notes = session.query(ConversationNote).filter(
            ConversationNote.conversation_id == conversation_id
        ).order_by(ConversationNote.created_at, ConversationNote.id).all()
    return {
        "conversation_id": conversation_id,
        "messages": [_command_log_dict(row) for row in rows],
        "notes": [_note_dict(note) for note in notes],
        "export": export_markdown(conversation_id, rows=rows, notes=notes),
    }


def add_note(conversation_id: str, assistant: str, user: str, title: str,
             body: str, source: str = "web_ui") -> dict[str, Any]:
    with get_session() as session:
        note = ConversationNote(
            conversation_id=conversation_id,
            assistant=assistant or "",
            user=user or "",
            title=(title or "Note").strip(),
            body=(body or "").strip(),
            source=source or "web_ui",
        )
        session.add(note)
        session.commit()
        session.refresh(note)
        return _note_dict(note)


def export_markdown(conversation_id: str, *,
                    rows: list[CommandLog] | None = None,
                    notes: list[ConversationNote] | None = None) -> str:
    if rows is None or notes is None:
        with get_session() as session:
            rows = session.query(CommandLog).filter(
                CommandLog.conversation_id == conversation_id
            ).order_by(CommandLog.created_at, CommandLog.id).all()
            notes = session.query(ConversationNote).filter(
                ConversationNote.conversation_id == conversation_id
            ).order_by(ConversationNote.created_at, ConversationNote.id).all()

    title = _title_for(rows) if rows else conversation_id
    lines = [
        f"# {title}",
        "",
        f"- Conversation ID: `{conversation_id}`",
    ]
    if rows:
        lines.append(f"- Assistant: `{rows[-1].assistant}`")
        lines.append(f"- User: `{rows[-1].user}`")
    lines.append("")

    if notes:
        lines.extend(["## Notes", ""])
        for note in notes:
            lines.extend([
                f"### {note.title or 'Note'}",
                "",
                note.body or "",
                "",
            ])

    lines.extend(["## Transcript", ""])
    for row in rows or []:
        ts = row.created_at.isoformat() if row.created_at else ""
        lines.extend([
            f"### {ts}",
            "",
            f"**User:** {row.message}",
            "",
            f"**Assistant:** {row.response_message}",
            "",
        ])
        if row.intent and row.intent != "conversation":
            lines.extend([f"- Intent: `{row.intent}`", f"- Executed: `{row.executed}`", ""])
    return "\n".join(lines).strip() + "\n"


def _title_for(rows: list[CommandLog]) -> str:
    for row in rows:
        if row.message:
            clean = " ".join(row.message.split())
            return clean[:80]
    return rows[0].conversation_id if rows else "Conversation"


def _command_log_dict(row: CommandLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "assistant": row.assistant,
        "user": row.user,
        "message": row.message,
        "response": row.response_message,
        "intent": row.intent,
        "success": row.success,
        "executed": row.executed,
        "tool_call": _json_obj(row.tool_call),
        "resolved": _json_obj(row.resolved),
        "data": _json_obj(row.data),
        "error": row.error,
    }


def _note_dict(note: ConversationNote) -> dict[str, Any]:
    return {
        "id": note.id,
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "updated_at": note.updated_at.isoformat() if note.updated_at else None,
        "conversation_id": note.conversation_id,
        "assistant": note.assistant,
        "user": note.user,
        "title": note.title,
        "body": note.body,
        "source": note.source,
    }


def _json_obj(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
