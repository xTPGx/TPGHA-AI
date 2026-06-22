#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
# Add-on entrypoint. Reads add-on options, seeds default config, and starts the
# FastAPI backend (which also serves the built React UI on port 8088).
set -e

# --- Resolve options (bashio is provided by the HA base image) ---
if command -v bashio >/dev/null 2>&1; then
  CONFIG_PATH="$(bashio::config 'config_path')"
  LOG_LEVEL="$(bashio::config 'log_level')"
  export OPENAI_API_KEY="$(bashio::config 'openai_api_key')"
  HA_URL="$(bashio::config 'home_assistant_url')"
  HA_TOKEN="$(bashio::config 'home_assistant_token')"
else
  CONFIG_PATH="${config_path:-/config/tpg_homeai}"
  LOG_LEVEL="${log_level:-info}"
  HA_URL="${home_assistant_url:-}"
  HA_TOKEN="${home_assistant_token:-}"
fi

CONFIG_PATH="${CONFIG_PATH:-/config/tpg_homeai}"
LOG_LEVEL="${LOG_LEVEL:-info}"

# Prefer the Supervisor proxy + token when the user leaves HA fields blank.
if [ -z "${HA_URL}" ]; then HA_URL="http://supervisor/core"; fi
if [ -z "${HA_TOKEN}" ] && [ -n "${SUPERVISOR_TOKEN}" ]; then HA_TOKEN="${SUPERVISOR_TOKEN}"; fi

export HOME_ASSISTANT_URL="${HA_URL}"
export HOME_ASSISTANT_TOKEN="${HA_TOKEN}"
export CONFIG_DIR="${CONFIG_PATH}"

# --- Seed default config on first run (never overwrite user edits) ---
mkdir -p "${CONFIG_DIR}" /data
if [ -z "$(ls -A "${CONFIG_DIR}" 2>/dev/null)" ]; then
  cp -r /defaults/config/* "${CONFIG_DIR}/" 2>/dev/null || true
fi

# Map HA log level -> uvicorn log level.
case "${LOG_LEVEL}" in
  trace|debug) UVICORN_LOG="debug" ;;
  notice|info) UVICORN_LOG="info" ;;
  warning) UVICORN_LOG="warning" ;;
  error|fatal) UVICORN_LOG="error" ;;
  *) UVICORN_LOG="info" ;;
esac

# Never echo secrets. Only log non-sensitive startup info.
echo "[tpg_homeai] starting on :8088 | config=${CONFIG_DIR} | ha_url=${HOME_ASSISTANT_URL}"

exec uvicorn app.main:app --host 0.0.0.0 --port 8088 --log-level "${UVICORN_LOG}"
