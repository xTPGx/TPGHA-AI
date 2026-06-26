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


class ArchivedConversation(Base):
    """Soft-hidden conversation IDs.

    CommandLog remains the audit source of truth. Archiving only hides a
    conversation from the notebook/recent-chat list.
    """

    __tablename__ = "archived_conversation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    archived_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ReleaseStatusSnapshot(Base):
    """Point-in-time release readiness history for owner review."""

    __tablename__ = "release_status_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    version: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(32), default="unknown")
    blocker_count: Mapped[int] = mapped_column(Integer, default=0)
    check_count: Mapped[int] = mapped_column(Integer, default=0)
    passed_count: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[str] = mapped_column(Text, default="{}")


class FollowupPreference(Base):
    """Per-profile follow-up prompt preference.

    These rows personalize Chat suggestion chips without changing the audit
    log or granting any new action permissions.
    """

    __tablename__ = "followup_preference"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    user: Mapped[str] = mapped_column(String(64), default="", index=True)
    assistant: Mapped[str] = mapped_column(String(64), default="", index=True)
    followup_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[str] = mapped_column(String(32), default="pinned")
    source_intent: Mapped[str] = mapped_column(String(64), default="")


class AcceptanceRun(Base):
    """Human-run live-house acceptance evidence.

    The acceptance runner stays non-mutating. These rows record what a human
    validated in the real house so release readiness can be based on evidence,
    not memory or wishful thinking.
    """

    __tablename__ = "acceptance_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    test_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    status: Mapped[str] = mapped_column(String(32), default="passed")
    assistant: Mapped[str] = mapped_column(String(64), default="")
    user: Mapped[str] = mapped_column(String(64), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[str] = mapped_column(Text, default="{}")
    version: Mapped[str] = mapped_column(String(32), default="")


class HouseAsset(Base):
    """Uploaded floor plans, room photos, blueprints, and house notes.

    These are approval-first knowledge inputs. Draft assets can be reviewed and
    analyzed, but only approved rows are injected into the conversational house
    context.
    """

    __tablename__ = "house_asset"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    title: Mapped[str] = mapped_column(String(255), default="")
    asset_type: Mapped[str] = mapped_column(String(64), default="floorplan")
    room: Mapped[str] = mapped_column(String(64), default="")
    original_filename: Mapped[str] = mapped_column(String(255), default="")
    stored_filename: Mapped[str] = mapped_column(String(255), default="")
    content_type: Mapped[str] = mapped_column(String(128), default="")
    storage_path: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    description: Mapped[str] = mapped_column(Text, default="")
    analysis: Mapped[str] = mapped_column(Text, default="{}")
    uploaded_by: Mapped[str] = mapped_column(String(64), default="")
