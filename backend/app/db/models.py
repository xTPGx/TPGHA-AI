"""SQLAlchemy ORM models for MVP persistence: command history & automations."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CommandLog(Base):
    """An audit log of natural-language commands and their resolution.

    Note: we deliberately never store secrets here.
    """

    __tablename__ = "command_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    assistant: Mapped[str] = mapped_column(String(64), default="")
    user: Mapped[str] = mapped_column(String(64), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    conversation_id: Mapped[str] = mapped_column(String(128), default="")
    intent: Mapped[str] = mapped_column(String(64), default="")
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    executed: Mapped[bool] = mapped_column(Boolean, default=False)
    response_message: Mapped[str] = mapped_column(Text, default="")
    tool_call: Mapped[str] = mapped_column(Text, default="{}")
    resolved: Mapped[str] = mapped_column(Text, default="{}")
    data: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")


class ConversationState(Base):
    """Short-term conversational context for pronouns and corrections."""

    __tablename__ = "conversation_state"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    assistant: Mapped[str] = mapped_column(String(64), default="")
    user: Mapped[str] = mapped_column(String(64), default="")
    conversation_id: Mapped[str] = mapped_column(String(128), default="")
    last_message: Mapped[str] = mapped_column(Text, default="")
    last_intent: Mapped[str] = mapped_column(String(64), default="")
    last_action: Mapped[str] = mapped_column(String(64), default="")
    last_target: Mapped[str] = mapped_column(String(255), default="")
    last_label: Mapped[str] = mapped_column(String(255), default="")
    last_entity_id: Mapped[str] = mapped_column(String(255), default="")
    last_domain: Mapped[str] = mapped_column(String(64), default="")


class DiscoveredEntity(Base):
    """Persisted discovery state for a Home Assistant entity (PART 2)."""

    __tablename__ = "discovered_entity"

    entity_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default="new")  # new|approved|ignored|known
    domain: Mapped[str] = mapped_column(String(64), default="")
    friendly_name: Mapped[str] = mapped_column(String(255), default="")
    category: Mapped[str] = mapped_column(String(64), default="")
    room: Mapped[str] = mapped_column(String(64), default="")
    risk_level: Mapped[str] = mapped_column(String(16), default="low")
    suggested_aliases: Mapped[str] = mapped_column(Text, default="")  # JSON list
    reason: Mapped[str] = mapped_column(Text, default="")
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    ignore_reason: Mapped[str] = mapped_column(String(255), default="")
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class AutomationDraft(Base):
    """A proposed automation awaiting human approval (MVP never auto-creates)."""

    __tablename__ = "automation_draft"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    trigger_description: Mapped[str] = mapped_column(Text, default="")
    action_description: Mapped[str] = mapped_column(Text, default="")
    proposed_yaml: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    installed_id: Mapped[str] = mapped_column(String(255), default="")
    installed_path: Mapped[str] = mapped_column(String(512), default="")
    installed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    install_error: Mapped[str] = mapped_column(Text, default="")


class MemoryItem(Base):
    """Approved or proposed long-term house/user memory."""

    __tablename__ = "memory_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    scope: Mapped[str] = mapped_column(String(32), default="house")  # house|user|room|device
    owner: Mapped[str] = mapped_column(String(64), default="")
    subject: Mapped[str] = mapped_column(String(255), default="")
    key: Mapped[str] = mapped_column(String(128), default="")
    value: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(64), default="user")
    status: Mapped[str] = mapped_column(String(32), default="draft")  # draft|approved|ignored


class Suggestion(Base):
    """A proactive recommendation awaiting approve/edit/ignore."""

    __tablename__ = "suggestion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    title: Mapped[str] = mapped_column(String(255), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(64), default="")
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    action_type: Mapped[str] = mapped_column(String(64), default="")
    payload: Mapped[str] = mapped_column(Text, default="{}")  # JSON object
    status: Mapped[str] = mapped_column(String(32), default="suggested")


class ConversationNote(Base):
    """User-authored notes attached to a brainstorming/chat session."""

    __tablename__ = "conversation_note"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    conversation_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    assistant: Mapped[str] = mapped_column(String(64), default="")
    user: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(String(255), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(64), default="user")
