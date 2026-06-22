"""Structured result objects returned by the resolver and actions."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ResolveResult(BaseModel):
    """The outcome of resolving a friendly name to a concrete config object."""

    matched: bool = False
    kind: str = ""
    id: Optional[str] = None
    entity_id: Optional[str] = None
    name: Optional[str] = None
    confidence: float = 0.0
    reason: str = ""
    # Full resolved object payload (room, camera, etc.) for downstream use.
    data: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def miss(cls, kind: str, reason: str) -> "ResolveResult":
        return cls(matched=False, kind=kind, confidence=0.0, reason=reason)


class ActionResult(BaseModel):
    """The outcome of executing (or proposing) an action."""

    success: bool = False
    intent: str = ""
    executed: bool = False
    message: str = ""
    requires_confirmation: bool = False
    confirmation_message: Optional[str] = None
    confirmation_token: Optional[str] = None
    resolved: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None

    @classmethod
    def fail(cls, intent: str, message: str, **kwargs: Any) -> "ActionResult":
        return cls(success=False, intent=intent, executed=False, message=message,
                   error=message, **kwargs)

    @classmethod
    def needs_confirmation(
        cls,
        intent: str,
        confirmation_message: str,
        confirmation_token: str,
        resolved: dict[str, Any],
    ) -> "ActionResult":
        return cls(
            success=True,
            intent=intent,
            executed=False,
            requires_confirmation=True,
            confirmation_message=confirmation_message,
            confirmation_token=confirmation_token,
            resolved=resolved,
            message=confirmation_message,
        )


class CommandResponse(BaseModel):
    """Top-level response for POST /command and /confirm."""

    success: bool
    assistant: Optional[str] = None
    user: Optional[str] = None
    conversation_id: Optional[str] = None
    intent: Optional[str] = None
    resolved: dict[str, Any] = Field(default_factory=dict)
    executed: bool = False
    requires_confirmation: bool = False
    confirmation_message: Optional[str] = None
    confirmation_token: Optional[str] = None
    message: str = ""
    tool_call: Optional[dict[str, Any]] = None
    data: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
