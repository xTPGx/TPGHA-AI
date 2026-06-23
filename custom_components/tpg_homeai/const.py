"""Constants for the TPG HomeAI custom integration."""
from __future__ import annotations

DOMAIN = "tpg_homeai"

# Config entry keys
CONF_URL = "url"
CONF_API_KEY = "api_key"

# Options keys
CONF_ASSISTANT_ID = "assistant_id"
CONF_USER_ID = "user_id"
CONF_ENABLE_NOTIFICATIONS = "enable_persistent_notifications"
CONF_SCAN_INTERVAL = "scan_interval_minutes"
CONF_CREATE_REPAIRS = "create_repairs"
CONF_AUTO_APPROVE_LOW_RISK = "auto_approve_low_risk_entities"
CONF_AUTO_APPROVE_DOMAINS = "auto_approve_domains"
CONF_ENABLE_SIDEBAR_PANEL = "enable_sidebar_panel"

DEFAULT_ASSISTANT_ID = "atlas"
DEFAULT_USER_ID = "shawn"
DEFAULT_TIMEOUT = 30
DEFAULT_SCAN_INTERVAL = 15  # minutes
DEFAULT_ENABLE_NOTIFICATIONS = True
DEFAULT_CREATE_REPAIRS = True
DEFAULT_AUTO_APPROVE_LOW_RISK = False
DEFAULT_ENABLE_SIDEBAR_PANEL = True

# Service names
SERVICE_RELOAD_CONFIG = "reload_config"
SERVICE_TEST_COMMAND = "test_command"
SERVICE_SCAN_DEVICES = "scan_devices"
SERVICE_APPROVE = "approve_discovered_entity"
SERVICE_IGNORE = "ignore_discovered_entity"
SERVICE_MAP_ENTITY = "map_entity"
SERVICE_CONFIRM_ACTION = "confirm_action"
SERVICE_CANCEL_CONFIRMATION = "cancel_confirmation"
SERVICE_DASHBOARD_DRAFT = "dashboard_draft"
SERVICE_DASHBOARD_INSTALL = "dashboard_install"
SERVICE_OPEN_PANEL = "open_panel"
SERVICE_GENERATE_SUGGESTIONS = "generate_suggestions"
SERVICE_MONITOR_SCAN = "monitor_scan"
SERVICE_APPROVE_AUTOMATION_DRAFT = "approve_automation_draft"
SERVICE_DRAFT_MEMORY = "draft_memory"
SERVICE_APPROVE_MEMORY = "approve_memory"
SERVICE_IGNORE_MEMORY = "ignore_memory"
SERVICE_GET_KNOWLEDGE_GRAPH = "get_knowledge_graph"
SERVICE_GET_LAST_COMMAND = "get_last_command"
SERVICE_GET_COMMANDS = "get_commands"

# Home Assistant events fired by this integration.
EVENT_DISCOVERY_FOUND = "tpg_homeai_discovery_found"
EVENT_APPROVAL_REQUIRED = "tpg_homeai_approval_required"
EVENT_CONFIRMATION_REQUIRED = "tpg_homeai_action_confirmation_required"
EVENT_ACTION_EXECUTED = "tpg_homeai_action_executed"
EVENT_ACTION_FAILED = "tpg_homeai_action_failed"

# Map backend event types -> HA event names (they already match, but keep a map).
BACKEND_EVENT_MAP = {
    "tpg_homeai_discovery_found": EVENT_DISCOVERY_FOUND,
    "tpg_homeai_approval_required": EVENT_APPROVAL_REQUIRED,
    "tpg_homeai_action_confirmation_required": EVENT_CONFIRMATION_REQUIRED,
    "tpg_homeai_action_executed": EVENT_ACTION_EXECUTED,
    "tpg_homeai_action_failed": EVENT_ACTION_FAILED,
}

# Persistent notification ids.
NOTIFY_DISCOVERY = "tpg_homeai_discovery"
NOTIFY_CONFIRMATION = "tpg_homeai_confirmation"
NOTIFY_UNAVAILABLE = "tpg_homeai_unavailable"
NOTIFY_CONFIG_ERROR = "tpg_homeai_config_error"
NOTIFY_OFFLINE = "tpg_homeai_offline"

# Repairs issue ids.
ISSUE_BACKEND_OFFLINE = "backend_offline"
ISSUE_CONFIG_ERROR = "config_error"
ISSUE_PENDING_APPROVALS = "pending_approvals"

# hass.data layout
DATA_CLIENT = "client"
DATA_COORDINATOR = "coordinator"

# Device identity
DEVICE_MANUFACTURER = "TPG Labs"
DEVICE_MODEL = "HomeAI Orchestrator"
DEVICE_NAME = "TPG HomeAI Orchestrator"
