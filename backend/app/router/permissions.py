"""Permission gating and the pending-confirmation token store.

Sensitive actions (unlock, open garage, disarm, etc.) never execute until the
user confirms. We issue a short-lived token describing the exact action +
parameters; /confirm replays that exact action. The AI cannot bypass this.
"""
from __future__ import annotations

import secrets
import time
from typing import Any, Optional

from ..models.schemas import AppConfig


class PendingConfirmation:
    def __init__(self, token: str, intent: str, params: dict[str, Any],
                 assistant: Optional[str], user: Optional[str], expires_at: float,
                 created_at: float, message: str, plan: dict[str, Any],
                 risk_level: str = "critical", target: str = ""):
        self.token = token
        self.intent = intent
        self.params = params
        self.assistant = assistant
        self.user = user
        self.expires_at = expires_at
        self.created_at = created_at
        self.message = message
        # Fully-resolved execution plan replayed on /confirm. Keeping the plan
        # (domain/service/data) here means /command never executes anything.
        self.plan = plan
        self.risk_level = risk_level
        self.target = target

    @property
    def expired(self) -> bool:
        return time.monotonic() > self.expires_at

    @property
    def age_seconds(self) -> float:
        return time.monotonic() - self.created_at

    def public_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "intent": self.intent,
            "assistant": self.assistant,
            "user": self.user,
            "message": self.message,
            "target": self.target,
            "risk_level": self.risk_level,
            "age_seconds": round(self.age_seconds, 1),
            "expires_in": round(max(0.0, self.expires_at - time.monotonic()), 1),
        }


class ConfirmationStore:
    """In-memory store of pending confirmations (single-process backend)."""

    def __init__(self) -> None:
        self._items: dict[str, PendingConfirmation] = {}

    def create(self, intent: str, params: dict[str, Any], message: str,
               ttl: int, assistant: Optional[str], user: Optional[str],
               plan: dict[str, Any], risk_level: str = "critical",
               target: str = "") -> PendingConfirmation:
        token = secrets.token_urlsafe(16)
        now = time.monotonic()
        pc = PendingConfirmation(
            token=token, intent=intent, params=params, assistant=assistant,
            user=user, expires_at=now + ttl, created_at=now, message=message,
            plan=plan, risk_level=risk_level, target=target,
        )
        self._items[token] = pc
        return pc

    def pop(self, token: str) -> Optional[PendingConfirmation]:
        self.purge_expired()
        pc = self._items.pop(token, None)
        if pc is None or pc.expired:
            return None
        return pc

    def cancel(self, token: str) -> bool:
        return self._items.pop(token, None) is not None

    def list_pending(self) -> list[PendingConfirmation]:
        self.purge_expired()
        return list(self._items.values())

    def purge_expired(self) -> None:
        for tok in [t for t, pc in self._items.items() if pc.expired]:
            self._items.pop(tok, None)


class PermissionEngine:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.perms = config.permissions

    def is_sensitive(self, intent: str) -> bool:
        return intent in set(self.perms.sensitive_actions)

    def confirmation_message(self, intent: str, target: str = "") -> str:
        template = self.perms.confirmation_messages.get(
            intent, "Confirm: {target}?"
        )
        try:
            return template.format(target=target or intent.replace("_", " "))
        except (KeyError, IndexError):
            return template

    def user_allows(self, user_id: Optional[str], capability: str) -> bool:
        """Check a capability against per-user perms, then defaults."""
        default_val = getattr(self.perms.defaults, capability, None)
        for u in self.config.assistants.users:
            if u.id == user_id:
                val = getattr(u.permissions, capability, None)
                if val is not None:
                    return bool(val)
        return bool(default_val) if default_val is not None else True


_store: Optional[ConfirmationStore] = None


def get_confirmation_store() -> ConfirmationStore:
    global _store
    if _store is None:
        _store = ConfirmationStore()
    return _store
