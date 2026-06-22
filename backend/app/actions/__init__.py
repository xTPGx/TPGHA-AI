"""Action handlers. Each handler validates, resolves, and executes (or
proposes) a single vetted intent and returns an ActionResult."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..homeassistant.rest import HomeAssistantREST
from ..models.schemas import AppConfig, Assistant, User
from ..router.permissions import ConfirmationStore, PermissionEngine
from ..router.resolver import Resolver


@dataclass
class ActionContext:
    """Everything an action handler needs to do its job."""

    config: AppConfig
    resolver: Resolver
    ha: HomeAssistantREST
    permissions: PermissionEngine
    confirmations: ConfirmationStore
    assistant: Optional[Assistant] = None
    user: Optional[User] = None
