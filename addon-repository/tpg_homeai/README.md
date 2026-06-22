# TPG HomeAI Orchestrator — Home Assistant Add-on

Runs the TPG HomeAI Orchestrator (FastAPI backend + React UI) directly inside
Home Assistant on port **8088**, with an Ingress panel in the HA sidebar.

This add-on is the **server**. To wire it into Home Assistant **Assist** (voice
/ conversation), also install the companion **TPG HomeAI** custom integration
(see `custom_components/tpg_homeai`), which forwards Assist messages to this
add-on's `/command` API.

---

## Install

### 1. Add the add-on repository

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store**.
2. Click the **⋮** menu (top-right) → **Repositories**.
3. Add the repository URL:

   ```
   https://github.com/your-org/tpg-homeai
   ```

4. Close the dialog. The **TPG HomeAI Orchestrator** add-on appears in the store.

### 2. Install and configure

1. Open the add-on → **Install**.
2. On the **Configuration** tab, set options:

   | Option | Description |
   | --- | --- |
   | `openai_api_key` | OpenAI key (optional; without it a fallback parser is used) |
   | `home_assistant_url` | Leave blank to use the Supervisor proxy automatically |
   | `home_assistant_token` | Leave blank to use the add-on's Supervisor token automatically |
   | `log_level` | `info`, `debug`, etc. |
   | `config_path` | Where YAML config lives (default `/config/tpg_homeai`) |

   > Leave `home_assistant_url` / `home_assistant_token` empty to let the add-on
   > talk to Home Assistant through the built-in Supervisor proxy
   > (`http://supervisor/core` + the add-on's `SUPERVISOR_TOKEN`). No manual
   > long-lived token needed.

3. **Start** the add-on. On first run it seeds default config into
   `config_path`. Edit those YAML files (via the File editor / Samba add-ons)
   and use the UI's **Reload config** button to apply changes.

### 3. Open the UI

Use **Open Web UI** (Ingress) or browse to `http://<home-assistant>:8088`.

---

## How it serves the frontend

The add-on image is a two-stage build: the React app is compiled to static
assets, then the FastAPI backend serves them via `STATIC_DIR`. So a single
container provides both the API (`/health`, `/command`, …) and the UI.

## Security

- Secrets (`openai_api_key`, `home_assistant_token`) are add-on options stored
  by the Supervisor and passed as backend-only environment variables. They are
  never written to logs and never sent to the browser.
- The AI can only select from a fixed tool allowlist; it cannot issue arbitrary
  Home Assistant service calls.

## Building locally (for development of the add-on image)

The Dockerfile expects the **repository root** as the build context:

```bash
docker build -f addon-repository/tpg_homeai/Dockerfile \
  --build-arg BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12 \
  -t local/tpg_homeai .
docker run --rm -p 8088:8088 \
  -e HOME_ASSISTANT_URL=http://192.168.4.232:8123 \
  -e HOME_ASSISTANT_TOKEN=... \
  local/tpg_homeai
```
