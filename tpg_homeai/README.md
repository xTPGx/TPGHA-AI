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

## Self-initialization on startup

You do **not** need to manually run a discovery scan after every restart. When
the add-on starts it automatically:

1. Starts the backend API + serves the web UI on port 8088.
2. Validates config (degrades instead of crashing on errors).
3. Connects to Home Assistant (Supervisor proxy or long-lived token).
4. Pulls all entity states and runs an **initial discovery scan**.
5. Classifies entities by domain / capability / risk and merges
   `devices.yaml` + `discovered.yaml`.
6. Detects new, unavailable, duplicate, ignored, and risky entities.
7. Raises Home Assistant persistent notifications for anything needing review.
8. Becomes ready for commands — no manual `/discovery/scan` required.

A background scan then re-runs every `scan_interval_minutes` to stay current. If
Home Assistant is unreachable, OpenAI is missing, or config has errors, the
backend runs in **degraded** mode (surfaced in `/health`) rather than failing.

## Configuration

| Option | Description |
| ------ | ----------- |
| `home_assistant_url` | Leave as `http://supervisor/core` to use the Supervisor proxy. |
| `home_assistant_token` | Leave **blank** to use the add-on's Supervisor token automatically. Only set a long-lived token if you run against a remote HA. |
| `openai_api_key` | **Required** for full AI understanding. Without it, the backend uses a deterministic fallback parser (fewer capabilities). |
| `openai_model` | Low-cost command/tool selector model. Default `gpt-5.4-nano`. |
| `openai_chat_model` | Main AI conversation/advice/vision model. Default `gpt-5.4-mini`. |
| `api_token` | Optional bearer token guarding **direct** (non-ingress) access to port 8088. Leave blank for current behavior. When set, LAN callers must send `Authorization: Bearer <token>`; Home Assistant ingress requests stay exempt (already HA-authenticated), and `/health` + public TTS audio + static assets remain reachable. |
| `config_dir` | Where YAML config + the database live. Default `/config/tpg_homeai`. |
| `database_url` | SQLite path for command history / discovery state. Default `sqlite:////config/tpg_homeai/tpg_homeai.db`. |
| `log_level` | `debug` / `info` / `warning` / `error`. |
| `scan_on_start` | Run the initial discovery scan automatically on startup (default `true`). |
| `scan_interval_minutes` | Background re-scan interval, 1–1440 (default `5`). |
| `notify_on_new_devices` | Notify when new entities need review (default `true`). |
| `notify_on_unavailable_devices` | Notify when known devices go unavailable (default `true`). |
| `auto_approve_low_risk_entities` | Auto-approve low-risk discoveries (default `false`). |
| `auto_approve_domains` | List of domains to auto-approve, e.g. `["light", "fan"]`. |

### Home Assistant token

In most installs you do **not** need a token: leave `home_assistant_token`
blank and the add-on uses its Supervisor token to reach the HA API via
`http://supervisor/core`. Only provide a long-lived access token if you point
`home_assistant_url` at a different Home Assistant instance.

### OpenAI API key

Create a key at <https://platform.openai.com/api-keys> and paste it into
`openai_api_key`. It is stored only in the add-on options and is never logged.

## Voice & hands-free

TPG HomeAI supports three voice surfaces, all using OpenAI for the brain, STT,
and TTS:

- **Home Assistant voice satellites** (Voice PE / ESP32 / Wyoming): in
  *Settings → Voice assistants*, create an Assist pipeline that uses **TPG
  HomeAI** as the conversation agent. The satellite's `source_device_id` /
  `source_entity_id` is matched against your `voice_sources`, so each room's
  satellite automatically uses that room's assistant and voice
  (e.g. Atlas / Chatty / Jarvis) and can reply on the room speaker.
- **Tablets / old phones (always-listening panel)**: open the web UI on the
  device and toggle **Panel** in the chat header. On Chrome / Android this runs
  a continuous browser wake-word loop ("Jarvis…", "Atlas…", etc.) with a
  listening indicator and optional room context. iOS Safari cannot keep the mic
  open in the background, so iPhones/iPads stay on tap-to-talk.
- **Desktop / iOS push-to-talk**: tap the **Mic** button in the composer to
  record; audio is uploaded to OpenAI STT. MIME fallbacks cover Safari
  (`audio/mp4`) and Chrome (`audio/webm`), and the UI surfaces clear
  idle/recording/transcribing/error states plus secure-context guidance.

`voice_sources` also carry a **trust level**. `outside` sources cannot trigger
state-changing actions, and `guest` sources are blocked from sensitive actions
(locks, etc.); `trusted`/`household` sources behave normally.

## Security

- The add-on ships a dedicated **AppArmor profile** (`apparmor.txt`), so it runs
  under its own confinement instead of the unconfined default (Home Assistant
  security rating 7 → 8).
- Set `api_token` to require a bearer token on direct port-8088 access; Home
  Assistant ingress stays exempt because it is already authenticated.
- Low-confidence or ambiguous device commands are routed into a
  confirmation/clarification flow instead of executing on a guess.

## After starting

- **Health check:** <http://homeassistant.local:8088/health> — must return
  **JSON** (`status: ok` / `degraded` / `initializing`).
- **Discovery:** <http://homeassistant.local:8088/discovery/summary> — JSON with
  `pending_count`, `known_count`, `unavailable_count`, `last_scan_ts`.
- **Web UI:** open the add-on's *Open Web UI* button, or
  <http://homeassistant.local:8088>
- In the custom integration, set the server URL to
  `http://homeassistant.local:8088` (or `http://<HA-IP>:8088`).

## Where config is stored

Everything persists in the `config_dir` (default `/config/tpg_homeai`):

- `household.yaml`, `assistants.yaml`, `devices.yaml`, `permissions.yaml`
  (starter copies are seeded on first run; your edits are never overwritten)
- `discovered.yaml` — discovery approvals/ignores (generated)
- `ignored.yaml` — explicit ignore list (generated)
- `tpg_homeai.db` — command history + discovery state

Nothing runtime is written inside the container image.

## Troubleshooting

- **UI says `Unexpected token '<'` / "API routing is misconfigured":** the
  frontend received HTML instead of JSON. Make sure you're on the latest add-on
  version and that `/health` returns JSON. (Fixed in 0.1.5 — the SPA fallback
  no longer intercepts API routes, and the UI calls same-origin endpoints.)
- **`/health` returns HTML:** API routing is broken — update the add-on.
- **Counts are all zero right after start:** the initial scan may still be
  running (`/health` → `discovery.scan_in_progress: true`). It populates within
  a few seconds; the dashboard also shows "Run scan now".

## Updates

This add-on builds from the public GitHub repo. To get new code:

1. The maintainer pushes code **and bumps `version`** in `config.yaml`.
2. Home Assistant detects the new version on its periodic store refresh (or when
   you click **Check for updates**).
3. With **Auto update** enabled on the add-on, HA rebuilds automatically and the
   new code takes effect — **no need to remove/re-add the repository or
   reinstall**. The build always re-clones the latest code (the version busts
   the Docker layer cache).
