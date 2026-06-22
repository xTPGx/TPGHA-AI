#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
# Add-on entrypoint (scaffold). Maps HA add-on options + supervisor token to
# the backend's environment, seeds default config, and starts uvicorn.
set -e

CONFIG_DIR="${CONFIG_DIR:-/config/tpg_homeai}"
mkdir -p "${CONFIG_DIR}" /data

# Seed default config on first run.
if [ -z "$(ls -A "${CONFIG_DIR}" 2>/dev/null)" ]; then
  cp -r /defaults/config/* "${CONFIG_DIR}/" || true
fi

# Read add-on options (bashio is available in HA base images).
if command -v bashio >/dev/null 2>&1; then
  export OPENAI_API_KEY="$(bashio::config 'openai_api_key')"
  export OPENAI_MODEL="$(bashio::config 'openai_model')"
  HA_URL="$(bashio::config 'home_assistant_url')"
  HA_TOKEN="$(bashio::config 'home_assistant_token')"

  # Prefer the Supervisor proxy + token when the user left fields blank.
  if [ -z "${HA_URL}" ]; then HA_URL="http://supervisor/core"; fi
  if [ -z "${HA_TOKEN}" ] && [ -n "${SUPERVISOR_TOKEN}" ]; then HA_TOKEN="${SUPERVISOR_TOKEN}"; fi

  export HOME_ASSISTANT_URL="${HA_URL}"
  export HOME_ASSISTANT_TOKEN="${HA_TOKEN}"
fi

export CONFIG_DIR
exec uvicorn app.main:app --host 0.0.0.0 --port 8088
