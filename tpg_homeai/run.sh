#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
#
# TPG HomeAI add-on entrypoint.
#   - reads /data/options.json (via bashio, or jq as a fallback)
#   - exports backend env vars
#   - falls back to the Supervisor proxy + token when HA fields are blank
#   - seeds starter config into CONFIG_DIR on first run (never overwrites)
#   - starts the FastAPI backend on 0.0.0.0:8088 (also serves the web UI)
set -e

OPTIONS_FILE="/data/options.json"

if command -v bashio >/dev/null 2>&1; then
  HA_URL="$(bashio::config 'home_assistant_url')"
  HA_TOKEN="$(bashio::config 'home_assistant_token')"
  OPENAI_KEY="$(bashio::config 'openai_api_key')"
  CONFIG_DIR_OPT="$(bashio::config 'config_dir')"
  DB_URL="$(bashio::config 'database_url')"
  LOG_LEVEL="$(bashio::config 'log_level')"
else
  HA_URL="$(jq -r '.home_assistant_url // ""' "${OPTIONS_FILE}")"
  HA_TOKEN="$(jq -r '.home_assistant_token // ""' "${OPTIONS_FILE}")"
  OPENAI_KEY="$(jq -r '.openai_api_key // ""' "${OPTIONS_FILE}")"
  CONFIG_DIR_OPT="$(jq -r '.config_dir // "/config"' "${OPTIONS_FILE}")"
  DB_URL="$(jq -r '.database_url // "sqlite:////config/tpg_homeai.db"' "${OPTIONS_FILE}")"
  LOG_LEVEL="$(jq -r '.log_level // "info"' "${OPTIONS_FILE}")"
fi

# bashio/jq may yield the literal "null" for empty values.
for var in HA_URL HA_TOKEN OPENAI_KEY CONFIG_DIR_OPT DB_URL LOG_LEVEL; do
  if [ "$(eval echo \$$var)" = "null" ]; then eval "$var=''"; fi
done

CONFIG_DIR_OPT="${CONFIG_DIR_OPT:-/config}"
DB_URL="${DB_URL:-sqlite:////config/tpg_homeai.db}"
LOG_LEVEL="${LOG_LEVEL:-info}"

# Use the Supervisor proxy + token when the user leaves HA fields blank.
if [ -z "${HA_URL}" ]; then HA_URL="http://supervisor/core"; fi
if [ -z "${HA_TOKEN}" ] && [ -n "${SUPERVISOR_TOKEN}" ]; then HA_TOKEN="${SUPERVISOR_TOKEN}"; fi

export HOME_ASSISTANT_URL="${HA_URL}"
export HOME_ASSISTANT_TOKEN="${HA_TOKEN}"
export OPENAI_API_KEY="${OPENAI_KEY}"
export CONFIG_DIR="${CONFIG_DIR_OPT}"
export DATABASE_URL="${DB_URL}"
export LOG_LEVEL="${LOG_LEVEL}"

# Seed starter config on first run; never overwrite the user's edits. Generated
# runtime files (discovered.yaml, the SQLite db) live in CONFIG_DIR, not in the
# container image.
mkdir -p "${CONFIG_DIR}"
for f in household.yaml assistants.yaml devices.yaml permissions.yaml; do
  if [ ! -f "${CONFIG_DIR}/${f}" ] && [ -f "/app/config_template/${f}" ]; then
    cp "/app/config_template/${f}" "${CONFIG_DIR}/${f}"
  fi
done

# Map HA log level -> uvicorn log level.
case "${LOG_LEVEL}" in
  trace|debug) UVICORN_LOG="debug" ;;
  notice|info) UVICORN_LOG="info" ;;
  warning) UVICORN_LOG="warning" ;;
  error|fatal) UVICORN_LOG="error" ;;
  *) UVICORN_LOG="info" ;;
esac

# Never echo secrets; only non-sensitive startup info.
echo "[tpg_homeai] starting on :8088 | config=${CONFIG_DIR} | ha_url=${HOME_ASSISTANT_URL}"

cd /app
exec uvicorn app.main:app --host 0.0.0.0 --port 8088 --log-level "${UVICORN_LOG}"
