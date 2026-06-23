"""Explainability and audit helpers for house commands."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import desc

from ..db.database import get_session
from ..db.models import CommandLog
from ..models.results import ActionResult
from . import ActionContext


def _loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _friendly_target(resolved: dict[str, Any], tool_call: dict[str, Any]) -> str:
    args = tool_call.get("arguments") if isinstance(tool_call.get("arguments"), dict) else {}
    target = (
        resolved.get("target")
        or resolved.get("friendly_name")
        or resolved.get("entity_id")
        or args.get("target")
        or args.get("door")
        or args.get("camera")
        or args.get("room")
        or ""
    )
    return str(target).strip()


def _decision_summary(row: CommandLog) -> dict[str, Any]:
    tool_call = _loads(row.tool_call)
    resolved = _loads(row.resolved)
    data = _loads(row.data)
    target = _friendly_target(resolved, tool_call)
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "assistant": row.assistant,
        "user": row.user,
        "conversation_id": row.conversation_id,
        "message": row.message,
        "intent": row.intent,
        "target": target,
        "tool_call": tool_call,
        "resolved": resolved,
        "data": data,
        "success": row.success,
        "executed": row.executed,
        "response_message": row.response_message,
        "error": row.error,
    }


async def explain_last_action(ctx: ActionContext, params: dict[str, Any]) -> ActionResult:
    """Explain the most recent command for this assistant/user/conversation."""
    conversation_id = str(params.get("conversation_id") or "").strip()
    include_failed = bool(params.get("include_failed", True))

    with get_session() as session:
        q = session.query(CommandLog).filter(CommandLog.assistant == (ctx.assistant.id if ctx.assistant else ""))
        if ctx.user is not None:
            q = q.filter(CommandLog.user == ctx.user.id)
        if conversation_id:
            q = q.filter(CommandLog.conversation_id == conversation_id)
        q = q.filter(CommandLog.intent != "explain_last_action")
        if not include_failed:
            q = q.filter(CommandLog.success.is_(True))
        row = q.order_by(desc(CommandLog.created_at), desc(CommandLog.id)).first()

    if row is None:
        return ActionResult(
            success=True,
            intent="explain_last_action",
            executed=False,
            message="I do not have a previous action to explain yet.",
            data={"found": False},
        )

    summary = _decision_summary(row)
    tool = summary["tool_call"].get("name") or summary["intent"] or "unknown"
    target = summary["target"] or "no specific target"
    source = summary["tool_call"].get("source") or "unknown"
    status = "executed" if summary["executed"] else "did not execute"
    if summary["error"]:
        status = f"failed with {summary['error']}"

    message = (
        f"I interpreted '{summary['message']}' as {tool}, targeted {target}, "
        f"and it {status}. Router source: {source}."
    )
    if summary["response_message"]:
        message += f" Result: {summary['response_message']}"

    return ActionResult(
        success=True,
        intent="explain_last_action",
        executed=False,
        message=message,
        resolved={"target": target, "previous_intent": summary["intent"]},
        data={"found": True, "command": summary},
    )
