# TPG HomeAI Orchestrator

A configurable, "Jarvis-style" AI smart-home control layer that sits **on top of
Home Assistant**. Home Assistant stays the device backend; this app is the AI
brain that understands natural language and routes commands to your cameras,
locks, lights, speakers (Music Assistant), thermostats, dashboards, and future
alarm systems.

- **Backend:** Python + FastAPI, OpenAI tool/function calling, Home Assistant
  REST API.
- **Frontend:** React + Tailwind (Vite) with a Command Tester.
- **Config:** YAML-first (`config/*.yaml`), SQLite for command history and
  automation drafts.
- **Deploy:** standalone Docker Compose, a Home Assistant **Add-on**, and a
  lightweight **HACS custom integration** that wires the app into HA Assist.

The AI **never** executes anything directly and can **never** make arbitrary
Home Assistant service calls. It only selects from a fixed allowlist of tools;
the backend validates and executes them. Sensitive actions (unlock, open
garage, disarm) require explicit confirmation.

---

## 1. Architecture

```
Natural language ─▶ AI (OpenAI tool calling) ─▶ tool selection
                                                   │
                       ┌───────────────────────────┘
                       ▼
   Resolver (aliases, rooms, users, prefer-available) ─▶ Permissions gate
                       │                                       │
                       ▼                                       ▼
                  Action handler ──────────────▶ Home Assistant REST API
```

Tools: `show_camera`, `play_music`, `stop_music`, `set_volume`, `lock_door`,
`unlock_door`, `turn_on_light`, `turn_off_light`, `turn_on_fan`,
`turn_off_fan`, `set_fan_percentage`, `set_climate`, `security_check`,
`open_dashboard`, `create_simple_automation`, plus the generic
`control_device(target, action, value?)` and `query_device(target)`.

### Generic capability-based control

Rather than hand-coding a tool per device type, the AI can call
`control_device`. The resolver matches the target (alias / room / friendly name
/ entity id / live entity), prefers **available** entities, skips **ignored**
ones, and the capability layer (`backend/app/discovery/capabilities.py`) maps
the requested action to a vetted Home Assistant service. Sensitive capabilities
(unlock, garage open, alarm disarm) are gated behind confirmation no matter how
they are invoked.

A deterministic **pre-router** runs before the AI for high-value commands so
they behave identically with or without OpenAI: fans, lights, camera status
("what cameras are online"), `show_camera`, thermostat set, `play_music`, and
`unlock` (which always requires confirmation). Scheduling phrasing ("at 7am…",
"every day…") is routed to `create_simple_automation` instead.

---

## Deployment modes

There are three ways to run TPG HomeAI, plus the dev workflow. They share the
**same backend and config** — only the packaging differs.

```
                          ┌─────────────────────────────────────────┐
  HA Assist (voice/text) ─┤ custom_components/tpg_homeai             │
                          │  (Conversation Agent — forwards /command)│
                          └───────────────────┬─────────────────────┘
                                              ▼  POST /command
   ┌──────────────────────────────────────────────────────────────┐
   │  TPG HomeAI server  (FastAPI backend + React UI on :8088)      │
   │  run as:  Standalone Docker  ·  HA Add-on                      │
   └──────────────────────────────────────────────────────────────┘
                                              │ REST
                                              ▼
                                      Home Assistant
```

| Mode | What runs | Package | Use when |
| --- | --- | --- | --- |
| **Standalone Docker** | backend + UI | `docker-compose.yml` | Dev, or running on a separate box |
| **HA Add-on** | backend + UI inside HA | `tpg_homeai/` (repo root) | You want it managed by Home Assistant |
| **HACS integration** | thin Assist bridge | `custom_components/tpg_homeai` | You want to talk to it through HA Assist/voice |

> The HACS integration is **not** a copy of the backend. It only connects HA
> Assist to a running TPG HomeAI server (the add-on or a standalone instance).
> You typically install the **Add-on** (the server) **and** the **integration**
> (the Assist bridge) together.

### A. Standalone Docker mode

```bash
cp .env.example .env          # set HA url/token (+ optional OpenAI key)
docker compose up --build
```

- Backend API + docs: <http://localhost:8088/docs>
- Frontend UI: <http://localhost:5173>

This is the simplest way to run the full app on any machine (a NAS, a mini PC,
your laptop). See sections 2–7 below for token setup, `.env`, and testing.

### B. Home Assistant Add-on mode

Runs the FastAPI backend **and** the built React UI in one container inside
Home Assistant on port `8088`, with an Ingress panel in the HA sidebar.

1. **Settings → Add-ons → Add-on Store → ⋮ → Repositories**, add:

   ```
   https://github.com/your-org/tpg-homeai
   ```

2. Install **TPG HomeAI Orchestrator**, set options (`openai_api_key`,
   `home_assistant_url`, `home_assistant_token`, `log_level`, `config_path`),
   then **Start**. Leave the HA url/token blank to use the Supervisor proxy
   automatically (no manual long-lived token needed).
3. Open the UI via **Open Web UI**.

Full add-on docs: [`tpg_homeai/README.md`](tpg_homeai/README.md).

### C. HACS custom integration mode (Home Assistant Assist)

Adds a **Conversation Agent** so you can drive TPG HomeAI from HA Assist (text
or voice). It forwards each utterance to the server's `/command` API and speaks
back the response.

1. **HACS → ⋮ → Custom repositories**, add the repo URL with category
   **Integration**. (Or copy `custom_components/tpg_homeai` into your HA
   `config/custom_components/` folder manually.)
2. Install **TPG HomeAI**, restart Home Assistant.
3. **Settings → Devices & Services → Add Integration → TPG HomeAI**. Enter the
   server URL (e.g. `http://homeassistant.local:8088` for the add-on, or your
   standalone Docker host) and an optional API key.
4. **Settings → Voice assistants** → set the conversation agent to **TPG
   HomeAI** (or add it to an existing pipeline).
5. (Optional) Open the integration's **Configure** to set the default
   `assistant_id` (e.g. `atlas`) and `user_id` (e.g. `shawn`).

The integration also exposes two services:

- `tpg_homeai.reload_config` — hot-reload the server's YAML config.
- `tpg_homeai.test_command` — send a command and get the structured result back
  (great for testing from **Developer Tools → Actions**).

### Development workflow

```bash
# Backend (hot reload)
cd backend
python -m venv .venv && . .venv/Scripts/activate   # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8088

# Frontend (separate terminal)
cd frontend
npm install
npm run dev    # http://localhost:5173, proxies /api -> :8088

# Headless acceptance + smoke checks
cd backend
python verify_acceptance.py
python smoke_api.py
python smoke_integration.py     # verifies the integration's payload format
```

Iterate on the integration by copying `custom_components/tpg_homeai` into a dev
HA instance's `config/custom_components/` and enabling debug logging:

```yaml
# configuration.yaml
logger:
  logs:
    custom_components.tpg_homeai: debug
```

### Production install workflow

1. **Install the server** as a Home Assistant **Add-on** (mode B). Configure
   options and start it. Edit the seeded YAML in `config_path`, then **Reload
   config**.
2. **Install the integration** via **HACS** (mode C) and point it at the add-on
   (`http://homeassistant.local:8088`, or via Ingress/host).
3. Set TPG HomeAI as your **Assist** conversation agent.
4. Verify with `tpg_homeai.test_command` and the add-on's **Command Tester**
   page.
5. Keep secrets in add-on options / the integration config — never in YAML or
   logs.

---

## 2. Create a Home Assistant long-lived access token

1. Open Home Assistant: `http://192.168.4.232:8123`.
2. Click your **user profile** (bottom-left avatar).
3. Scroll to **Long-lived access tokens** → **Create token**.
4. Name it `tpg-homeai`, copy the token (you only see it once).
5. Put it in `.env` as `HOME_ASSISTANT_TOKEN`. **Never commit this.**

The token is only ever sent in the `Authorization` header to your local HA and
is never logged or exposed to the frontend.

---

## 3. Configure `.env`

```bash
cp .env.example .env
```

Edit `.env`:

```ini
OPENAI_API_KEY=sk-...            # optional; without it a fallback parser is used
OPENAI_MODEL=gpt-4o-mini
HOME_ASSISTANT_URL=http://192.168.4.232:8123
HOME_ASSISTANT_TOKEN=eyJ...      # your long-lived token
CONFIG_DIR=./config
DATABASE_URL=sqlite:///./tpg_homeai.db
```

> No OpenAI key? The backend automatically falls back to a deterministic
> rule-based parser so the Command Tester and acceptance tests still work.

---

## 4. Run with Docker Compose

```bash
docker compose up --build
```

- Backend API: <http://localhost:8088> (docs at `/docs`)
- Frontend UI: <http://localhost:5173>

`./config` is mounted into the backend, so you can edit YAML and click
**Reload config** in the UI (or `POST /config/reload`).

### Run the backend without Docker

```bash
cd backend
python -m venv .venv && . .venv/Scripts/activate   # Windows
# source .venv/bin/activate                         # macOS/Linux
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8088
```

### Run the frontend without Docker

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173, proxies /api -> http://localhost:8088
```

---

## 5. Test `/command`

```bash
curl -X POST http://localhost:8088/command \
  -H "Content-Type: application/json" \
  -d '{"assistant":"atlas","user":"shawn","message":"show me the driveway"}'
```

Example response:

```json
{
  "success": true,
  "assistant": "atlas",
  "intent": "show_camera",
  "resolved": { "camera": "driveway", "entity_id": "camera.front_yard_front_yard" },
  "executed": false,
  "message": "Front Yard / Driveway camera is available. Open it from the cameras dashboard."
}
```

Sensitive actions return a confirmation token; replay it to execute:

```bash
# 1) ask to unlock -> returns confirmation_token
curl -X POST http://localhost:8088/command -H "Content-Type: application/json" \
  -d '{"assistant":"atlas","user":"shawn","message":"unlock the front door"}'

# 2) confirm
curl -X POST http://localhost:8088/confirm -H "Content-Type: application/json" \
  -d '{"confirmation_token":"<token from step 1>"}'
```

### Other endpoints

| Method | Path                   | Purpose                                  |
| ------ | ---------------------- | ---------------------------------------- |
| GET    | `/health`              | Backend / HA / OpenAI status             |
| GET    | `/config`              | Full validated config                    |
| POST   | `/config/reload`       | Hot-reload YAML from `CONFIG_DIR`        |
| GET    | `/ha/entities`         | All Home Assistant entities              |
| GET    | `/ha/entity/{id}`      | Single entity state                      |
| POST   | `/command`             | Natural-language command                 |
| POST   | `/confirm`             | Confirm a sensitive action               |
| POST   | `/test/resolve`        | Test the resolver (kind + name)          |
| POST   | `/test/action`         | Run one action handler directly          |

The **Command Tester** page in the UI exposes all of this interactively.

---

## 6. Map entities to friendly concepts

All mapping lives in `config/`:

- `household.yaml` — household name, timezone, default dashboards.
- `assistants.yaml` — users (Shawn, Jordie), assistants (Atlas, Chatty),
  personalities, per-user music account + permissions.
- `devices.yaml` — rooms, cameras, locks, speakers, displays, climate, music
  accounts, and the `avoid` list of dead/duplicate entities.
- `permissions.yaml` — which actions are sensitive and their confirmation
  prompts.

To map a new device, add an entry with an `entity_id` and a few human
`aliases`, then **Reload config**. The resolver:

1. Matches exact alias/name/id (case-insensitive).
2. Falls back to fuzzy matching.
3. **Prefers entities that are currently available** in Home Assistant over the
   `avoid` duplicates (e.g. `media_player.office` is ignored in favor of
   `media_player.office_office_speaker`).

### Music account ownership (privacy)

Each assistant is bound to its owner's Music Assistant provider:

- **Atlas → Shawn → `Spotify [xTPGx]`**
- **Chatty → Jordie → `Spotify [jordierae22]`**

Atlas can never play on Jordie's account and vice-versa, regardless of what the
request claims.

### Fan control

Fans are mapped as `device_aliases` whose `entity_id` is in the `fan.` domain
(and optionally via a room's `fans:` list). Supported commands:

| Say | Tool | Example resolution |
| --- | --- | --- |
| "turn off office fan" | `turn_off_fan` | `fan.office` → `fan.turn_off` |
| "turn on bedroom fan" | `turn_on_fan` | `fan.bedroom_fan` → `fan.turn_on` |
| "turn on living room fan" | `turn_on_fan` | `fan.living_room` → `fan.turn_on` |
| "set office fan to 50%" | `set_fan_percentage` | `fan.office` → `fan.set_percentage` (50) |

Fan phrasing is handled by a **deterministic pre-router** that runs before the
AI, so "turn off … fan", "turn on … fan", and "set … fan … %" route the same
way every time (with or without an OpenAI key). The resolver matches fan
aliases (e.g. "office fan", "living room fan"), prefers entities that are
currently available, and never selects an entity from the `avoid` list. Only
the three `fan.*` services are allowlisted — no arbitrary services are exposed.

---

## 7. Home Assistant packaging

This repo is itself a valid **Home Assistant add-on repository**. The add-on
lives at the repo **root** so the Supervisor recognizes it:

```
repository.yaml          # add-on repository manifest
tpg_homeai/              # the add-on
  config.yaml            # add-on manifest (port 8088, options, version 0.1.2)
  Dockerfile             # clones repo + builds frontend; base from BUILD_ARCH
  run.sh                 # options -> env, seeds config, starts uvicorn
  README.md
```

The base image is resolved from the `BUILD_ARCH` build-arg that the Supervisor
always passes (`ghcr.io/home-assistant/${BUILD_ARCH}-base-python:3.12`), so no
`build.yaml` is needed.

### Install as a Home Assistant add-on

1. Home Assistant → **Settings → Add-ons → Add-on Store → ⋮ → Repositories**.
2. Add `https://github.com/xTPGx/TPGHA-AI` and close.
3. Find **TPG HomeAI Orchestrator** in the store and click **Install**.
4. On the **Configuration** tab, paste your **OpenAI API key**. Leave
   `home_assistant_token` blank to use the add-on's Supervisor token; leave
   `home_assistant_url` as `http://supervisor/core`.
5. **Start** the add-on, then check the **Log** tab for
   `[tpg_homeai] starting on :8088`.
6. Open the **Web UI** (or <http://homeassistant.local:8088>), and confirm
   <http://homeassistant.local:8088/health> returns `status: ok`.
7. Install the **custom integration** from `custom_components/tpg_homeai/` (via
   HACS or by copying the folder into `/config/custom_components`), then add it
   and point the server URL at `http://homeassistant.local:8088`.

> The add-on Dockerfile fetches the app from this public repo at build time
> (Home Assistant builds with the add-on folder as context, so it can't reach
> sibling folders). After pushing code changes, **rebuild** the add-on to pick
> them up. The root-level `tpg_homeai/` is the canonical (and only) add-on.

### Startup behavior (add-on)

The add-on self-initializes on every start — no manual scan needed:

1. Starts the API + serves the UI on port 8088.
2. Validates config (degrades, never crashes, on errors).
3. Connects to Home Assistant (Supervisor proxy or token).
4. Pulls states, runs the **initial discovery scan**, classifies entities, and
   merges `devices.yaml` + `discovered.yaml`.
5. Raises persistent notifications for pending approvals / unavailable devices.
6. Re-scans every `scan_interval_minutes` in the background.

`/health` and `/discovery/summary` always return JSON; `last_scan_ts` is
populated automatically after the first startup scan. Runtime config lives under
`/config/tpg_homeai/` (devices/discovered/ignored YAML + the SQLite db).

### Automatic updates from GitHub

Enable **Auto update** on the add-on. When the maintainer pushes code **and
bumps `version` in `tpg_homeai/config.yaml`**, Home Assistant detects the new
version on its periodic store refresh (or via *Check for updates*) and rebuilds
automatically — you do **not** need to remove/re-add the repository or
reinstall. The Dockerfile re-clones the latest code on each version (the version
busts the build cache), so the running container always matches the push.

### Troubleshooting

- **UI: `Unexpected token '<'`** → the frontend got HTML instead of JSON; the
  API routing was misconfigured. Update to ≥ 0.1.5 (SPA fallback no longer
  shadows API routes; UI calls same-origin endpoints).
- **`/health` must return JSON.** If it returns HTML, the add-on is out of date.
- **`/discovery/summary` must return JSON**, even before the first scan
  (it returns a `message` until a scan completes).

**Custom integration (HACS)** — `custom_components/tpg_homeai/`

- `manifest.json` — domain `tpg_homeai`, depends on `conversation`.
- `config_flow.py` — asks for the server URL + optional API key; options flow
  sets the default assistant/user.
- `conversation.py` — a Conversation Agent that forwards Assist input to the
  server's `/command` (passing `assistant_id`, `user_id`, `text`,
  `conversation_id`) and speaks back the response. Handles connection errors
  gracefully and logs debug info without leaking secrets.
- `coordinator.py` — polls `/state` + `/events`, fires HA events, and reconciles
  persistent notifications + Repairs.
- `sensor.py` / `binary_sensor.py` / `button.py` / `entity.py` — operational
  entities grouped under the single **TPG HomeAI Orchestrator** device.
- `services.yaml` — `reload_config`, `scan_devices`, `approve_discovered_entity`,
  `ignore_discovered_entity`, `map_entity`, `confirm_action`,
  `cancel_confirmation`, `test_command`.

The integration is intentionally lightweight: it does **not** duplicate the
backend AI logic, it bridges HA Assist to a running TPG HomeAI server and
surfaces management (entities, buttons, services, notifications, Repairs) in
Home Assistant. `hacs.json` at the repo root makes it installable via HACS. See
sections 9–12 for discovery, approvals, notifications, and the security model.

When run as the add-on, the server can use the Supervisor proxy
(`http://supervisor/core`) + `SUPERVISOR_TOKEN` instead of a manual long-lived
token.

---

## 8. Acceptance scenarios

The following all work in the Command Tester (`backend/verify_acceptance.py`
runs them headless):

| Command                              | Result                                                      |
| ------------------------------------ | ----------------------------------------------------------- |
| "Is the front door locked?"          | `security_check`, reads `lock.front_door`                   |
| "Show me the driveway."              | `camera.front_yard_front_yard`                              |
| "Show me the front door."            | `camera.front_door_front_door_doorbell`                     |
| "Play my music in the office." (Atlas) | shawn / `spotify_xtpgx` / `media_player.office_office_speaker` |
| "Play my music in the kitchen." (Chatty) | jordie / `spotify_jordierae22` / `media_player.kitchen_display` |
| "Unlock the front door."             | requires confirmation, does not execute immediately         |
| "Set the thermostat to cool 75."     | `set_climate` → the mapped thermostat (`climate.set_temperature`) |
| "Turn off office fan."               | `turn_off_fan` → `fan.office` (`fan.turn_off`)              |
| "Turn on living room fan."           | `turn_on_fan` → `fan.living_room` (`fan.turn_on`)          |
| "Turn off bedroom fan."              | `turn_off_fan` → `fan.bedroom_fan` (`fan.turn_off`)        |
| "Set office fan to 50%."             | `set_fan_percentage` → `fan.office` (`fan.set_percentage`, 50) |

Run them (plus the extended suite for discovery/confirmation/control/music):

```bash
cd backend
python verify_acceptance.py     # routing + resolution (43 checks)
python verify_extended.py       # confirmation, discovery, control, music (31 checks)
```

---

## 9. Device discovery & approval

You should not have to hand-edit YAML for every new device. The discovery engine
(`backend/app/discovery/`) pulls all Home Assistant states, classifies each
entity, and queues new ones for approval.

- **Endpoints:** `GET /discovery/scan`, `POST /discovery/scan`,
  `GET /discovery/pending`, `GET /discovery/summary`, `POST /discovery/approve`,
  `POST /discovery/ignore`, `POST /discovery/map`, `POST /discovery/reload`.
- **Classification:** domain, friendly name, state, likely room, device type,
  capabilities, risk level, suggested aliases/category/mapping, availability,
  duplicate heuristic, and a human-readable reason.
- **Buckets:** known, new, unavailable, duplicate candidates, ignored,
  recommended, risky. **Unavailable entities are never auto-ignored**, nothing is
  ever auto-deleted, and entities only join the avoid list when you explicitly
  ignore them.
- **Persistence:** discovery state lives in SQLite. Approvals are written to a
  generated `config/discovered.yaml` overlay that is merged into `devices.yaml`
  at load time — your hand-written `devices.yaml` (and its comments) is never
  rewritten.

**Approval workflow (from Home Assistant):**

1. A scan finds e.g. `light.new_lamp` → classified `light`, room `office`, low
   risk, with suggested aliases.
2. `sensor.tpg_homeai_pending_approvals` increments and a persistent
   notification appears.
3. Call `tpg_homeai.approve_discovered_entity` with `entity_id`, `room`,
   `friendly_name` (or `tpg_homeai.map_entity` to map as speaker/display/camera/
   etc.). The backend writes config and reloads, and the device becomes
   available to the AI.
4. To suppress a dead/duplicate entity, call `tpg_homeai.ignore_discovered_entity`
   with a reason.

Optional auto-approval (off by default) can approve **low-risk** entities or
specific domains; high/critical risk is never auto-approved.

---

## 10. Home Assistant-native management

The custom integration exposes the orchestrator inside Home Assistant under a
single device (**TPG HomeAI Orchestrator**, manufacturer *TPG Labs*):

- **Sensors:** `sensor.tpg_homeai_status`, `..._pending_approvals`,
  `..._unavailable_devices`, `..._last_command`.
- **Binary sensor:** `binary_sensor.tpg_homeai_needs_attention` (on for pending
  approvals, config error, offline backend, pending confirmation, or
  unavailable devices).
- **Buttons:** `button.tpg_homeai_scan_devices`, `..._reload_config`,
  `..._test_connection`.
- **Services:** `scan_devices`, `reload_config`, `approve_discovered_entity`,
  `ignore_discovered_entity`, `map_entity`, `test_command`, `confirm_action`,
  `cancel_confirmation`.
- **Events:** `tpg_homeai_discovery_found`, `tpg_homeai_approval_required`,
  `tpg_homeai_action_confirmation_required`, `tpg_homeai_action_executed`,
  `tpg_homeai_action_failed`.

A coordinator polls `/state` + `/events`, fires those events, and reconciles
**persistent notifications** (new devices, confirmation required, unavailable
devices, config error, backend offline) and **Repairs** issues (backend offline,
config error, pending approvals). Integration options: `server_url`, `api_key`,
`default_assistant`, `default_user`, `enable_persistent_notifications`,
`scan_interval_minutes`, `create_repairs`, `auto_approve_low_risk_entities`,
`auto_approve_domains`.

The React UI remains for advanced admin (**HA Integration**, **Discovery**,
**Capability Map** pages), but Home Assistant is the primary operational
interface.

---

## 11. Music Assistant, displays, and config

- **Music Assistant:** playback only happens with a real `media_id`. Configure
  `music_accounts[].default_media: {media_id, media_type}` per account. With no
  media_id the orchestrator resolves the account + speaker but replies
  *"…no default playable media is configured"* and reports `executed: false` —
  it never falsely claims playback. Assistant→owner account ownership is enforced.
- **Display routing:** `displays[].type` is `media_player` (needs `entity_id`),
  `browser_mod` (needs `browser_id`), or `dashboard` (needs `dashboard_path`).
  `show_camera` reports status + dashboard path when no display is set, navigates
  via `browser_mod.navigate`, or attempts a cast on a `media_player`, returning a
  clear message when unsupported. Browser Mod is optional.
- **Config schema:** all config models ignore unknown fields, so a richer YAML
  never crashes the backend. On a validation error the backend stays up in a
  **degraded** state — `/health` reports `status: degraded` with the error, the
  integration raises a notification/Repair, and nothing else breaks.

---

## 12. Security model & confirmation flow

- Secrets (`OPENAI_API_KEY`, `HOME_ASSISTANT_TOKEN`) are backend-only env vars,
  never logged and never sent to the frontend.
- The AI can only pick from the fixed tool allowlist — no arbitrary HA service
  calls. Every service call is validated/resolved before execution.
- **Sensitive actions never execute from the initial `/command`.** They return a
  pending confirmation:

  ```json
  { "success": true, "executed": false, "requires_confirmation": true,
    "confirmation_token": "…", "confirmation_message": "Confirm: unlock the Front Door?" }
  ```

  Execution only happens via `POST /confirm` (or the
  `tpg_homeai.confirm_action` service) with a valid token. Tokens **expire after
  60 seconds**; expired, invalid, reused, or cancelled tokens fail safely without
  executing anything. The resolved execution plan is stored server-side, so the
  side effect happens in exactly one place.
- Sensitive actions: `unlock_door`, `open_garage`, `disarm_alarm`,
  `disable_camera`, `disable_security`, `change_lock_code`,
  `disable_notifications`, `remove_device`, `delete_automation`.
