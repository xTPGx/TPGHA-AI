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
    intent: Mapped[str] = mapped_column(String(64), default="")
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    executed: Mapped[bool] = mapped_column(Boolean, default=False)
    response_message: Mapped[str] = mapped_column(Text, default="")


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
