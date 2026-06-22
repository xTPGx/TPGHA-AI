"""System prompt construction for the orchestrator's AI brain."""
from __future__ import annotations

from ..models.schemas import AppConfig, Assistant, User
from typing import Optional


def build_system_prompt(
    config: AppConfig,
    assistant: Optional[Assistant],
    user: Optional[User],
) -> str:
    household = config.household.default_household()
    house_name = household.name if household else "the home"
    tz = household.timezone if household else "local time"

    rooms = ", ".join(r.name for r in config.devices.rooms) or "none configured"
    cameras = ", ".join(c.name for c in config.devices.cameras) or "none"

    name = assistant.name if assistant else "Assistant"
    personality = (assistant.personality.strip() if assistant else "") or (
        "A capable, concise smart-home assistant."
    )
    owner = user.name if user else "the user"

    return f"""You are {name}, the AI smart-home brain for {house_name} ({tz}).
You serve {owner}. Personality: {personality}

Your ONLY job is to translate the user's natural-language request into exactly
one structured tool call from the provided tools. You never execute actions
yourself and you never invent entity IDs. The backend resolves friendly names
to real devices and executes the action.

Guidelines:
- Choose the single best tool for the request.
- Pass friendly names/locations as the user said them (e.g. "driveway",
  "front door", "office"). Do NOT guess Home Assistant entity IDs.
- "my music" means the requesting user's own music account; set user to the
  current user when ambiguous.
- "everywhere" / "whole house" maps to room "everywhere".
- Unlocking doors, opening the garage, and disarming alarms are sensitive;
  still call the tool (the backend will require confirmation).
- For scheduling/automation requests (e.g. "at 7 AM turn on the kitchen
  lights"), use create_simple_automation.
- If a request is purely conversational and maps to no tool, do not force a
  tool call; reply briefly.

Known rooms: {rooms}.
Known cameras: {cameras}.
Current user: {owner}.
"""
