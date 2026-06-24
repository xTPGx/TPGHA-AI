"""Central action policy for conversational execution.

This is the backend contract for the "Jarvis" behavior:

- confident low-risk actions can run immediately
- sensitive actions require confirmation
- ambiguous actions pause for review/clarification
- proposals stay approval-first

The frontend may use this to decide whether to show an Execute card, but the
policy is intentionally backend-owned so HA Assist, dashboards, services, and
API clients can share one risk decision.
"""
from __future__ import annotations

from typing import Any

from ..models.results import ActionResult, CommandResponse

PROPOSAL_INTENTS = {
    "create_simple_automation",
    "create_routine",
    "draft_dashboard",
}

SENSITIVE_INTENTS = {
    "unlock_door",
    "open_garage",
    "open_cover",
    "disarm_alarm",
    "disable_alarm",
    "disable_security",
    "disable_camera",
    "change_lock_code",
    "delete_automation",
    "remove_device",
}

SENSITIVE_ACTIONS = {
    "unlock",
    "open",
    "disarm",
    "disable",
    "delete",
    "remove",
}

SENSITIVE_SERVICES = {
    "lock.unlock",
    "cover.open_cover",
    "cover.open_garage_door",
    "alarm_control_panel.alarm_disarm",
}

LOW_RISK_DOMAINS = {
    "light",
    "fan",
    "media_player",
    "switch",
    "scene",
    "script",
    "button",
}

CONFIDENCE_REVIEW_THRESHOLD = 0.80


def evaluate_action_policy(
    result: ActionResult | CommandResponse,
    tool_call: dict[str, Any] | None = None,
    *,
    preview: bool = False,
) -> dict[str, Any]:
    """Return the action policy decision for a command result."""
    intent = result.intent or ""
    resolved = result.resolved or {}
    data = result.data or {}
    confidence = _confidence(resolved)
    service_names = _service_names(data, tool_call)
    risk = _risk(intent, resolved, service_names, tool_call)
    reasons: list[str] = []

    if result.requires_confirmation:
        reasons.append("handler_requires_confirmation")
        return _decision(
            "confirmation_required", risk, confidence, reasons, preview=preview
        )

    if intent in PROPOSAL_INTENTS:
        reasons.append("creates_or_changes_future_behavior")
        return _decision("proposal_required", "medium", confidence, reasons, preview=preview)

    if _is_sensitive(intent, resolved, service_names, tool_call):
        reasons.append("sensitive_security_or_access_action")
        return _decision(
            "confirmation_required", "critical", confidence, reasons, preview=preview
        )

    if not result.success:
        reasons.append(result.error or "command_failed")
        decision = "clarify" if not result.executed else "review_required"
        return _decision(decision, risk, confidence, reasons, preview=preview)

    if _would_execute(result, data, tool_call):
        if confidence < CONFIDENCE_REVIEW_THRESHOLD:
            reasons.append("low_target_confidence")
            return _decision("review_required", risk, confidence, reasons, preview=preview)
        if not _has_target(resolved) and service_names:
            reasons.append("missing_resolved_target")
            return _decision("review_required", risk, confidence, reasons, preview=preview)
        reasons.append("confident_low_risk_or_allowed_action")
        return _decision("execute_now", risk, confidence, reasons, preview=preview)

    reasons.append("conversation_or_status_only")
    return _decision("answer_only", risk, confidence, reasons, preview=preview)


def should_pause_for_review(policy: dict[str, Any]) -> bool:
    return bool(policy.get("requires_review"))


def _decision(
    decision: str,
    risk: str,
    confidence: float,
    reasons: list[str],
    *,
    preview: bool,
) -> dict[str, Any]:
    return {
        "decision": decision,
        "risk": risk,
        "confidence": confidence,
        "requires_review": decision in {
            "confirmation_required",
            "proposal_required",
            "review_required",
            "clarify",
        },
        "can_auto_execute": decision == "execute_now",
        "preview": preview,
        "reasons": reasons,
    }


def _confidence(resolved: dict[str, Any]) -> float:
    value = resolved.get("confidence")
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 1.0


def _service_names(data: dict[str, Any], tool_call: dict[str, Any] | None) -> list[str]:
    preview = data.get("preview") if isinstance(data, dict) else None
    calls = (preview or {}).get("service_calls") if isinstance(preview, dict) else None
    names: list[str] = []
    if isinstance(calls, list):
        for call in calls:
            if isinstance(call, dict):
                domain = str(call.get("domain") or "").lower()
                service = str(call.get("service") or "").lower()
                if domain and service:
                    names.append(f"{domain}.{service}")

    for key in ("service_call", "music_assistant", "media_player", "browser_mod"):
        call = data.get(key) if isinstance(data, dict) else None
        if isinstance(call, dict):
            domain = str(call.get("domain") or "").lower()
            service = str(call.get("service") or "").lower()
            if domain and service:
                names.append(f"{domain}.{service}")
            elif service and "." in service:
                names.append(service.lower())

    if tool_call:
        args = tool_call.get("arguments") or {}
        if isinstance(args, dict):
            domain = str(args.get("domain") or "").lower()
            service = str(args.get("service") or "").lower()
            if domain and service:
                names.append(f"{domain}.{service}")
        name = str(tool_call.get("name") or "").lower()
        if name:
            names.append(name)
    return [n for n in names if n]


def _risk(
    intent: str,
    resolved: dict[str, Any],
    service_names: list[str],
    tool_call: dict[str, Any] | None,
) -> str:
    if _is_sensitive(intent, resolved, service_names, tool_call):
        return "critical"
    domain = str(resolved.get("domain") or "").lower()
    entity_id = str(resolved.get("entity_id") or "").lower()
    if not domain and "." in entity_id:
        domain = entity_id.split(".", 1)[0]
    if domain in LOW_RISK_DOMAINS:
        return "low"
    if domain in {"climate", "vacuum", "automation", "number", "select"}:
        return "medium"
    if domain in {"camera", "cover", "lock", "siren", "alarm_control_panel"}:
        return "high"
    if intent.startswith(("turn_on_", "turn_off_", "set_fan_")):
        return "low"
    return "low"


def _is_sensitive(
    intent: str,
    resolved: dict[str, Any],
    service_names: list[str],
    tool_call: dict[str, Any] | None,
) -> bool:
    if intent in SENSITIVE_INTENTS:
        return True
    if any(name in SENSITIVE_SERVICES for name in service_names):
        return True
    args = (tool_call or {}).get("arguments") or {}
    action = str(args.get("action") or args.get("service") or "").lower() if isinstance(args, dict) else ""
    domain = str(
        (args.get("domain") if isinstance(args, dict) else "")
        or resolved.get("domain")
        or resolved.get("entity_id")
        or ""
    ).lower()
    return action in SENSITIVE_ACTIONS and any(
        word in domain for word in ("lock", "cover", "garage", "alarm", "security", "camera")
    )


def _would_execute(
    result: ActionResult | CommandResponse,
    data: dict[str, Any],
    tool_call: dict[str, Any] | None,
) -> bool:
    preview = data.get("preview") if isinstance(data, dict) else None
    if isinstance(preview, dict) and preview.get("would_execute"):
        return True
    return bool(result.executed or tool_call)


def _has_target(resolved: dict[str, Any]) -> bool:
    return bool(
        resolved.get("entity_id")
        or resolved.get("entity_ids")
        or resolved.get("label")
        or resolved.get("target")
        or resolved.get("door")
        or resolved.get("routine")
        or resolved.get("title")
        or resolved.get("dashboard")
    )
