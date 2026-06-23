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
  SCAN_ON_START="$(bashio::config 'scan_on_start')"
  SCAN_INTERVAL="$(bashio::config 'scan_interval_minutes')"
  NOTIFY_NEW="$(bashio::config 'notify_on_new_devices')"
  NOTIFY_UNAVAIL="$(bashio::config 'notify_on_unavailable_devices')"
  AUTO_LOW_RISK="$(bashio::config 'auto_approve_low_risk_entities')"
  AUTO_DOMAINS="$(bashio::config 'auto_approve_domains | join(",")')"
else
  HA_URL="$(jq -r '.home_assistant_url // ""' "${OPTIONS_FILE}")"
  HA_TOKEN="$(jq -r '.home_assistant_token // ""' "${OPTIONS_FILE}")"
  OPENAI_KEY="$(jq -r '.openai_api_key // ""' "${OPTIONS_FILE}")"
  CONFIG_DIR_OPT="$(jq -r '.config_dir // "/config/tpg_homeai"' "${OPTIONS_FILE}")"
  DB_URL="$(jq -r '.database_url // "sqlite:////config/tpg_homeai/tpg_homeai.db"' "${OPTIONS_FILE}")"
  LOG_LEVEL="$(jq -r '.log_level // "info"' "${OPTIONS_FILE}")"
  SCAN_ON_START="$(jq -r '.scan_on_start // true' "${OPTIONS_FILE}")"
  SCAN_INTERVAL="$(jq -r '.scan_interval_minutes // 5' "${OPTIONS_FILE}")"
  NOTIFY_NEW="$(jq -r '.notify_on_new_devices // true' "${OPTIONS_FILE}")"
  NOTIFY_UNAVAIL="$(jq -r '.notify_on_unavailable_devices // true' "${OPTIONS_FILE}")"
  AUTO_LOW_RISK="$(jq -r '.auto_approve_low_risk_entities // false' "${OPTIONS_FILE}")"
  AUTO_DOMAINS="$(jq -r '(.auto_approve_domains // []) | join(",")' "${OPTIONS_FILE}")"
fi

# bashio/jq may yield the literal "null" for empty values.
for var in HA_URL HA_TOKEN OPENAI_KEY CONFIG_DIR_OPT DB_URL LOG_LEVEL \
           SCAN_ON_START SCAN_INTERVAL NOTIFY_NEW NOTIFY_UNAVAIL \
           AUTO_LOW_RISK AUTO_DOMAINS; do
  if [ "$(eval echo \$$var)" = "null" ]; then eval "$var=''"; fi
done

CONFIG_DIR_OPT="${CONFIG_DIR_OPT:-/config/tpg_homeai}"
DB_URL="${DB_URL:-sqlite:////config/tpg_homeai/tpg_homeai.db}"
LOG_LEVEL="${LOG_LEVEL:-info}"
SCAN_ON_START="${SCAN_ON_START:-true}"
SCAN_INTERVAL="${SCAN_INTERVAL:-5}"
NOTIFY_NEW="${NOTIFY_NEW:-true}"
NOTIFY_UNAVAIL="${NOTIFY_UNAVAIL:-true}"
AUTO_LOW_RISK="${AUTO_LOW_RISK:-false}"

# Use the Supervisor proxy + token when the user leaves HA fields blank.
if [ -z "${HA_URL}" ]; then HA_URL="http://supervisor/core"; fi
if [ -z "${HA_TOKEN}" ] && [ -n "${SUPERVISOR_TOKEN}" ]; then HA_TOKEN="${SUPERVISOR_TOKEN}"; fi

export HOME_ASSISTANT_URL="${HA_URL}"
export HOME_ASSISTANT_TOKEN="${HA_TOKEN}"
export OPENAI_API_KEY="${OPENAI_KEY}"
export CONFIG_DIR="${CONFIG_DIR_OPT}"
export DATABASE_URL="${DB_URL}"
export LOG_LEVEL="${LOG_LEVEL}"
export SCAN_ON_START="${SCAN_ON_START}"
export SCAN_INTERVAL_MINUTES="${SCAN_INTERVAL}"
export NOTIFY_ON_NEW_DEVICES="${NOTIFY_NEW}"
export NOTIFY_ON_UNAVAILABLE_DEVICES="${NOTIFY_UNAVAIL}"
export AUTO_APPROVE_LOW_RISK_ENTITIES="${AUTO_LOW_RISK}"
export AUTO_APPROVE_DOMAINS="${AUTO_DOMAINS}"

# Seed starter config on first run; never overwrite the user's edits. Generated
# runtime files (discovered.yaml, ignored.yaml, the SQLite db) live in
# CONFIG_DIR, not in the container image. The backend bootstrap also ensures
# these exist, so this is just a fast-path on first boot.
mkdir -p "${CONFIG_DIR}"
for f in household.yaml assistants.yaml devices.yaml permissions.yaml; do
  if [ ! -f "${CONFIG_DIR}/${f}" ] && [ -f "/app/config_template/${f}" ]; then
    cp "/app/config_template/${f}" "${CONFIG_DIR}/${f}"
  fi
done
for f in discovered.yaml ignored.yaml; do
  if [ ! -f "${CONFIG_DIR}/${f}" ]; then
    printf '# Managed by TPG HomeAI. Auto-generated; safe to edit.\n{}\n' > "${CONFIG_DIR}/${f}"
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
