"""Pydantic models that validate the YAML config and shape API payloads."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


# ---------------------------------------------------------------------------
# Config models (validated against config/*.yaml)
#
# Every config model ignores unknown/extra fields so a richer YAML never
# crashes the backend (PART 10). Add new fields explicitly to model them.
# ---------------------------------------------------------------------------
class _CfgBase(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Dashboards(_CfgBase):
    default: str = "lovelace"
    security: Optional[str] = None
    cameras: Optional[str] = None
    music: Optional[str] = None
    climate: Optional[str] = None


class Household(_CfgBase):
    id: str
    name: str
    timezone: str = "UTC"
    default: bool = False
    dashboards: Dashboards = Field(default_factory=Dashboards)
    default_display: Optional[str] = None


class HouseholdConfig(_CfgBase):
    households: list[Household] = Field(default_factory=list)

    def default_household(self) -> Optional[Household]:
        for h in self.households:
            if h.default:
                return h
        return self.households[0] if self.households else None


class UserPermissions(_CfgBase):
    can_unlock_doors: Optional[bool] = None
    can_open_garage: Optional[bool] = None
    can_disarm_alarm: Optional[bool] = None
    can_lock_doors: Optional[bool] = None
    can_control_lights: Optional[bool] = None
    can_control_fans: Optional[bool] = None
    can_control_climate: Optional[bool] = None
    can_control_music: Optional[bool] = None
    can_control_covers: Optional[bool] = None
    can_view_cameras: Optional[bool] = None


class User(_CfgBase):
    id: str
    name: str
    role: Literal["admin", "manager", "resident", "guest"] = "resident"
    aliases: list[str] = Field(default_factory=list)
    music_account: Optional[str] = None
    permissions: UserPermissions = Field(default_factory=UserPermissions)


class VoiceProfile(_CfgBase):
    provider: Literal["browser", "openai", "ha_tts"] = "browser"
    model: str = "gpt-4o-mini-tts"
    voice: str = "alloy"
    instructions: str = ""
    response_format: Literal["mp3", "opus", "aac", "flac", "wav", "pcm"] = "mp3"
    output: Literal["browser", "media_player"] = "browser"
    target_entity_id: Optional[str] = None
    fallback_provider: Literal["browser", "none"] = "browser"


class Assistant(_CfgBase):
    id: str
    name: str
    owner: str
    aliases: list[str] = Field(default_factory=list)
    wake_words: list[str] = Field(default_factory=list)
    listen_enabled: bool = True
    personality: str = ""
    tone: str = "neutral"
    voice: str | VoiceProfile = "neutral"


class AssistantsConfig(_CfgBase):
    users: list[User] = Field(default_factory=list)
    assistants: list[Assistant] = Field(default_factory=list)


class DefaultMedia(_CfgBase):
    """Default playable media for a user (PART 8). When media_id is null the
    music action must NOT claim playback started."""

    media_id: Optional[str] = None
    media_type: Optional[str] = "music"


class MusicAccount(_CfgBase):
    name: str
    provider: str
    account: str
    owner: str
    default_media: Optional[DefaultMedia] = None


class MusicAccountUpsert(MusicAccount):
    id: str


class Room(_CfgBase):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    speaker: Optional[str] = None
    camera: Optional[str] = None
    display: Optional[str] = None
    lock: Optional[str] = None
    lights: list[str] = Field(default_factory=list)
    fans: list[str] = Field(default_factory=list)
    climate: Optional[str] = None


class Camera(_CfgBase):
    id: str
    name: str
    entity_id: str
    aliases: list[str] = Field(default_factory=list)
    dashboard_path: Optional[str] = None


class Lock(_CfgBase):
    id: str
    name: str
    entity_id: str
    aliases: list[str] = Field(default_factory=list)
    battery_sensor: Optional[str] = None


class Speaker(_CfgBase):
    id: str
    name: str
    entity_id: str
    music_assistant_entity_id: Optional[str] = None
    room: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)


class Display(_CfgBase):
    """A surface for rendering cameras/dashboards (PART 9).

    type drives which field is required:
      - media_player  -> entity_id
      - browser_mod   -> browser_id
      - dashboard     -> dashboard_path
    """

    id: str
    name: str
    type: Literal["media_player", "browser_mod", "dashboard"] = "media_player"
    entity_id: Optional[str] = None
    browser_id: Optional[str] = None
    dashboard_path: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_type(self) -> "Display":
        if self.type == "media_player" and not self.entity_id:
            raise ValueError(f"display '{self.id}' type media_player requires entity_id")
        if self.type == "browser_mod" and not self.browser_id:
            raise ValueError(f"display '{self.id}' type browser_mod requires browser_id")
        if self.type == "dashboard" and not self.dashboard_path:
            raise ValueError(f"display '{self.id}' type dashboard requires dashboard_path")
        return self


class ClimateDevice(_CfgBase):
    id: str
    name: str
    entity_id: str
    room: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)


class DeviceAlias(_CfgBase):
    id: str
    name: str
    entity_id: str
    aliases: list[str] = Field(default_factory=list)
    domain: Optional[str] = None
    room: Optional[str] = None
    category: Optional[str] = None


class SecuritySensor(_CfgBase):
    entity_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)


class PersonalDevice(_CfgBase):
    id: str
    name: str
    entity_id: str
    owner: Optional[str] = None
    platform: Optional[str] = None
    device_type: Optional[str] = None
    room: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)


class VoiceSource(_CfgBase):
    """A microphone/panel/satellite that can provide room context.

    Assist and browser panels can send source_device_id or source_entity_id.
    This lets "turn on the light" become "turn on the office light" when the
    command came from the office panel, without training automations first.
    """

    id: str
    name: str
    room: str
    assistant: Optional[str] = None
    source_device_id: Optional[str] = None
    source_entity_id: Optional[str] = None
    user: Optional[str] = None
    trust_level: Literal["trusted", "household", "guest", "outside"] = "household"
    default_reply: Literal["browser", "room_speaker", "quiet", "none"] = "browser"
    speaker: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)


class HouseMode(_CfgBase):
    """A runtime house behavior profile.

    Modes let the assistant change reply routing, confirmation posture, and
    auto-execution behavior without hardcoding every house situation.
    """

    id: str
    name: str
    priority: int = 50
    enabled: bool = True
    aliases: list[str] = Field(default_factory=list)
    triggers: list[str] = Field(default_factory=list)
    quiet_hours: bool = False
    reply_mode: Literal["auto", "browser", "room_speaker", "media_player", "quiet", "none"] = "auto"
    requires_confirmation_for: list[str] = Field(default_factory=list)
    allow_auto_execute: bool = True
    description: str = ""


class DevicesConfig(_CfgBase):
    music_accounts: dict[str, MusicAccount] = Field(default_factory=dict)
    rooms: list[Room] = Field(default_factory=list)
    cameras: list[Camera] = Field(default_factory=list)
    locks: list[Lock] = Field(default_factory=list)
    speakers: list[Speaker] = Field(default_factory=list)
    displays: list[Display] = Field(default_factory=list)
    climate: list[ClimateDevice] = Field(default_factory=list)
    device_aliases: list[DeviceAlias] = Field(default_factory=list)
    security_sensors: list[SecuritySensor] = Field(default_factory=list)
    personal_devices: list[PersonalDevice] = Field(default_factory=list)
    voice_sources: list[VoiceSource] = Field(default_factory=list)
    modes: list[HouseMode] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    # Entities the user explicitly ignored via discovery (subset of avoid with
    # reasons), kept for UI display.
    ignored: list[str] = Field(default_factory=list)


class PermissionsConfig(_CfgBase):
    sensitive_actions: list[str] = Field(default_factory=list)
    confirmation_messages: dict[str, str] = Field(default_factory=dict)
    confirmation_ttl_seconds: int = 60
    defaults: UserPermissions = Field(default_factory=UserPermissions)
    enforce_music_account_ownership: bool = True
    security_pin: Optional[str] = None


class PermissionsUpsert(PermissionsConfig):
    pass


class AppConfig(BaseModel):
    """Aggregated, validated config from all YAML files."""

    household: HouseholdConfig
    assistants: AssistantsConfig
    devices: DevicesConfig
    permissions: PermissionsConfig


# ---------------------------------------------------------------------------
# API request / response models
# ---------------------------------------------------------------------------
class CommandRequest(BaseModel):
    # Accept both the orchestrator's native names (assistant/user/message) and
    # the Home Assistant integration's names (assistant_id/user_id/text).
    model_config = ConfigDict(populate_by_name=True)

    assistant: str = Field(validation_alias=AliasChoices("assistant", "assistant_id"))
    user: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("user", "user_id")
    )
    message: str = Field(validation_alias=AliasChoices("message", "text"))
    conversation_id: Optional[str] = None
    room: Optional[str] = Field(default=None, validation_alias=AliasChoices("room", "room_id"))
    source_device_id: Optional[str] = None
    source_entity_id: Optional[str] = None
    security_pin: Optional[str] = None


class ChatRequest(CommandRequest):
    pass


class VoicePreviewRequest(BaseModel):
    assistant: str = "atlas"
    text: str = "System voice check. I am online."
    voice_profile: Optional[VoiceProfile] = None
    target_entity_id: Optional[str] = None
    room: Optional[str] = None
    source_device_id: Optional[str] = None
    source_entity_id: Optional[str] = None
    reply_mode: Literal["auto", "browser", "room_speaker", "media_player", "quiet", "none"] = "auto"


class VoiceSpeakRequest(BaseModel):
    assistant: str = "atlas"
    text: str
    voice_profile: Optional[VoiceProfile] = None
    target_entity_id: Optional[str] = None
    force_browser: bool = False
    room: Optional[str] = None
    source_device_id: Optional[str] = None
    source_entity_id: Optional[str] = None
    reply_mode: Literal["auto", "browser", "room_speaker", "media_player", "quiet", "none"] = "auto"


class ConfirmRequest(BaseModel):
    confirmation_token: str
    security_pin: Optional[str] = None


class ScanRequest(BaseModel):
    auto_approve_low_risk: bool = False
    auto_approve_domains: list[str] = Field(default_factory=list)


class ApproveRequest(BaseModel):
    entity_id: str
    mapping: Optional[str] = None  # device_aliases|cameras|locks|speakers|displays|climate|security_sensors|personal_devices
    room: Optional[str] = None
    friendly_name: Optional[str] = None
    aliases: Optional[list[str]] = None


class IgnoreRequest(BaseModel):
    entity_id: str
    reason: Optional[str] = ""


class MapRequest(BaseModel):
    entity_id: str
    target: str  # speaker|display|camera|security_sensor|lock|climate|personal_device|device
    room: Optional[str] = None
    friendly_name: Optional[str] = None
    aliases: Optional[list[str]] = None


class ResolveRequest(BaseModel):
    kind: str = Field(description="assistant|user|room|camera|speaker|lock|display|music|device")
    name: str
    user: Optional[str] = None


class TestActionRequest(BaseModel):
    action: str
    assistant: Optional[str] = None
    user: Optional[str] = None
    params: dict[str, Any] = Field(default_factory=dict)


class DraftUpdateRequest(BaseModel):
    trigger_description: Optional[str] = None
    action_description: Optional[str] = None
    proposed_yaml: Optional[str] = None
    status: Optional[str] = None


class DashboardDraftRequest(BaseModel):
    title: str = "TPG Home"
    style: Literal["native", "mushroom"] = "native"
    room: Optional[str] = None
    include_browser_mod: bool = True
    include_unavailable: bool = False
    tablet_mode: bool = False
    voice_panel: bool = False


class MemoryDraftRequest(BaseModel):
    scope: Literal["house", "user", "room", "device"] = "house"
    owner: Optional[str] = None
    subject: str
    key: str
    value: str
    source: str = "user"


class ConversationNoteRequest(BaseModel):
    conversation_id: str
    assistant: Optional[str] = None
    user: Optional[str] = None
    title: str = "Note"
    body: str
    source: str = "web_ui"


class ResearchSearchRequest(BaseModel):
    query: str
    max_results: int = 5


class HAEntity(BaseModel):
    entity_id: str
    state: str
    friendly_name: Optional[str] = None
    domain: str
    available: bool = True
    attributes: dict[str, Any] = Field(default_factory=dict)
