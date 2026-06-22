# TPG HomeAI Orchestrator (Home Assistant add-on)

An AI smart-home orchestration layer that runs **on top of** Home Assistant.
Home Assistant stays the device backend; this add-on is the AI brain that
understands natural language, maps friendly names / rooms / users to Home
Assistant entities, and executes safe, allowlisted actions. It exposes a REST
API and a web UI on port **8088**.

> The add-on runs only the backend (+ web UI). The matching Home Assistant
> **custom integration** lives in `custom_components/tpg_homeai/` and is what
> wires Assist, sensors, buttons, services, and notifications into Home
> Assistant. Install that separately (via HACS or by copying the folder).

## What it does

- Natural-language control of cameras, locks, lights, fans, climate, speakers
  (Music Assistant), and more.
- Device **discovery + classification** with an approval workflow.
- **Sensitive actions** (unlock, open garage, disarm…) never execute directly —
  they require a confirmation token that expires after 60 seconds.

## Configuration

| Option | Description |
| ------ | ----------- |
| `home_assistant_url` | Leave as `http://supervisor/core` to use the Supervisor proxy. |
| `home_assistant_token` | Leave **blank** to use the add-on's Supervisor token automatically. Only set a long-lived token if you run against a remote HA. |
| `openai_api_key` | **Required** for full AI understanding. Without it, the backend uses a deterministic fallback parser (fewer capabilities). |
| `config_dir` | Where YAML config + the database live. Default `/config` (the add-on's own persistent config folder). |
| `database_url` | SQLite path for command history / discovery state. Default `sqlite:////config/tpg_homeai.db`. |
| `log_level` | `debug` / `info` / `warning` / `error`. |

### Home Assistant token

In most installs you do **not** need a token: leave `home_assistant_token`
blank and the add-on uses its Supervisor token to reach the HA API via
`http://supervisor/core`. Only provide a long-lived access token if you point
`home_assistant_url` at a different Home Assistant instance.

### OpenAI API key

Create a key at <https://platform.openai.com/api-keys> and paste it into
`openai_api_key`. It is stored only in the add-on options and is never logged.

## After starting

- **Health check:** <http://homeassistant.local:8088/health>
- **Web UI:** open the add-on's *Open Web UI* button, or
  <http://homeassistant.local:8088>
- In the custom integration, set the server URL to
  `http://homeassistant.local:8088` (or `http://<HA-IP>:8088`).

## Where config is stored

Everything persists in the `config_dir` (default `/config`, the add-on's private
config folder):

- `household.yaml`, `assistants.yaml`, `devices.yaml`, `permissions.yaml`
  (starter copies are seeded on first run; your edits are never overwritten)
- `discovered.yaml` — discovery approvals/ignores (generated)
- `tpg_homeai.db` — command history + discovery state

Nothing runtime is written inside the container image.
