"""Offline acceptance tests for add-on startup, API routing, and bootstrap.

Run from the backend/ directory:

    python verify_addon.py

These tests use FastAPI's TestClient and a throwaway temp CONFIG_DIR/DB. They
never require a live Home Assistant or OpenAI key — the whole point is that the
backend self-initializes and degrades gracefully (PART 11).
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

# ---- Environment MUST be set before importing the app (settings/db cache it).
_TMP = tempfile.mkdtemp(prefix="tpg_addon_test_")
_CFG = os.path.join(_TMP, "cfg")
_HA_CFG = os.path.join(_TMP, "ha")
_STATIC = os.path.join(_TMP, "static")
os.makedirs(os.path.join(_STATIC, "assets"), exist_ok=True)
os.makedirs(_HA_CFG, exist_ok=True)
with open(os.path.join(_STATIC, "index.html"), "w", encoding="utf-8") as fh:
    fh.write("<!doctype html><html><body><div id='root'></div></body></html>")
with open(os.path.join(_STATIC, "assets", "app.js"), "w", encoding="utf-8") as fh:
    fh.write("console.log('tpg');")

os.environ["CONFIG_DIR"] = _CFG
os.environ["HA_CONFIG_DIR"] = _HA_CFG
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP, 'test.db')}"
os.environ["STATIC_DIR"] = _STATIC
os.environ["HOME_ASSISTANT_URL"] = ""       # not configured -> degraded
os.environ["HOME_ASSISTANT_TOKEN"] = ""
os.environ["OPENAI_API_KEY"] = ""           # fallback parser
os.environ["SCAN_ON_START"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app import bootstrap as bootstrap_mod  # noqa: E402
from app import __version__ as backend_package_version  # noqa: E402
from app.db.database import init_db  # noqa: E402
from app.main import APP_VERSION, app  # noqa: E402

_PASS = 0
_FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  PASS  {name}")
    else:
        _FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def is_json(resp) -> bool:
    return "application/json" in (resp.headers.get("content-type") or "")


def is_html(resp) -> bool:
    return "text/html" in (resp.headers.get("content-type") or "")


def is_js(resp) -> bool:
    ctype = resp.headers.get("content-type") or ""
    return "javascript" in ctype or "application/octet-stream" in ctype


def main() -> int:
    init_db()
    # Run bootstrap deterministically (instead of the background lifespan task).
    asyncio.run(bootstrap_mod.bootstrap())
    state = bootstrap_mod.get_app_state()

    # TestClient WITHOUT a context manager => no lifespan, no double bootstrap.
    client = TestClient(app)

    print("PART 0 — add-on update metadata is internally consistent")
    repo_root = Path(__file__).resolve().parents[1]
    addon_config = (repo_root / "tpg_homeai" / "config.yaml").read_text(encoding="utf-8")
    dockerfile = (repo_root / "tpg_homeai" / "Dockerfile").read_text(encoding="utf-8")
    run_sh = (repo_root / "tpg_homeai" / "run.sh").read_text(encoding="utf-8")
    manifest = (repo_root / "custom_components" / "tpg_homeai" / "manifest.json").read_text(encoding="utf-8")
    ha_client = (repo_root / "custom_components" / "tpg_homeai" / "__init__.py").read_text(encoding="utf-8")
    ha_panel = (repo_root / "custom_components" / "tpg_homeai" / "panel.js").read_text(encoding="utf-8")
    ha_conversation = (repo_root / "custom_components" / "tpg_homeai" / "conversation.py").read_text(encoding="utf-8")
    chat_frontend = (repo_root / "frontend" / "src" / "pages" / "Chat.tsx").read_text(encoding="utf-8")
    ha_auth = (repo_root / "frontend" / "src" / "haAuth.ts").read_text(encoding="utf-8")
    setup_frontend = (repo_root / "frontend" / "src" / "pages" / "Setup.tsx").read_text(encoding="utf-8")
    dashboard_builder_frontend = (repo_root / "frontend" / "src" / "pages" / "DashboardBuilder.tsx").read_text(encoding="utf-8")
    suggestions_frontend = (repo_root / "frontend" / "src" / "pages" / "Suggestions.tsx").read_text(encoding="utf-8")
    api_frontend = (repo_root / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
    backend_main = (repo_root / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    cfg_version = re.search(r'^version:\s*"([^"]+)"', addon_config, re.M)
    docker_version = re.search(r'io\.hass\.version="([^"]+)"', dockerfile)
    manifest_version = re.search(r'"version":\s*"([^"]+)"', manifest)
    versions = {
        "config.yaml": cfg_version.group(1) if cfg_version else None,
        "Dockerfile": docker_version.group(1) if docker_version else None,
        "manifest.json": manifest_version.group(1) if manifest_version else None,
        "APP_VERSION": APP_VERSION,
        "package": backend_package_version,
    }
    check("version metadata present", all(versions.values()), str(versions))
    check("version metadata aligned", len(set(versions.values())) == 1, str(versions))
    check("add-on changelog exists", (repo_root / "tpg_homeai" / "CHANGELOG.md").is_file())
    check("add-on ingress owns the sidebar natively for all users",
          "ingress: true" in addon_config
          and "panel_title:" in addon_config
          and "panel_icon:" in addon_config
          and "panel_admin: false" in addon_config,
          "The add-on must expose a native ingress sidebar panel (visible to "
          "non-admins) so the Supervisor injects X-Remote-User-* for the active "
          "HA user on every request.")
    check("custom integration does not register a competing wrapper panel",
          "_remove_sidebar_panel(hass)" in ha_client
          and 'component_name="tpg-homeai-panel"' not in ha_client
          and "frontend.add_extra_js_url(hass, PANEL_MODULE_URL)" not in ha_client,
          "The stale-session custom-element wrapper must be retired; the native "
          "Supervisor ingress panel owns the sidebar.")
    check("backend resolves identity from Supervisor ingress headers",
          "x-remote-user-id" in backend_main
          and "x-remote-user-name" in backend_main
          and "x-remote-user-display-name" in backend_main
          and "_ingress_user_candidates" in backend_main,
          "The backend must trust X-Remote-User-* ingress headers as the "
          "authoritative active-user identity.")
    check("add-on ships custom integration files",
          "custom_components_template/tpg_homeai" in dockerfile,
          "The add-on image must include the matching custom integration.")
    check("add-on installs custom integration into HA config",
          "/config/custom_components/tpg_homeai" in run_sh
          and "custom_components_template/tpg_homeai" in run_sh,
          "The add-on must sync the custom integration so non-admin HA panels exist.")
    check("HA client exposes chat endpoint", "async def async_chat" in ha_client and '"/chat"' in ha_client)
    check("HA Assist uses chat brain, not command-only path",
          "async_chat(" in ha_conversation and "async_command(" not in ha_conversation,
          "Assist must use /chat for general conversation + guarded actions")
    check("Chat mic uses recorder upload, not Web Speech only",
          "MediaRecorder" in chat_frontend
          and "voiceTranscribe" in chat_frontend
          and "/voice/transcribe" in api_frontend,
          "Mobile mic must record audio and upload it for OpenAI transcription.")
    check("Chat mic gives actionable permission diagnostics",
          "Diagnose mic" in chat_frontend
          and "microphoneReadinessReport" in chat_frontend
          and "Localhost only works on the device running the browser" in chat_frontend,
          "Voice failures should explain HTTP/HTTPS, app permission, and localhost behavior.")
    check("Chat voice session has runtime status and cancel",
          "VoiceSessionBar" in chat_frontend
          and "recordingSeconds" in chat_frontend
          and "cancelVoiceInput" in chat_frontend
          and "discardRecordingRef" in chat_frontend,
          "Mic input should expose listening/transcribing state and a true cancel path.")
    check("frontend no longer sends stale cached HA identity",
          "clientUser: freshUser || {}" in ha_auth
          and "cachedStorageUserIgnored" in ha_auth,
          "sessionStorage can belong to a previous HA login and must not identify the active user.")
    check("custom HA panel refreshes iframe when HA user changes",
          "_maybeRefreshForUser" in ha_panel
          and "_startIdentityHeartbeat" in ha_panel
          and "_userSignature" in ha_panel,
          "The sidebar panel must repost/reload the active HA user instead of sticking to a previous iframe session.")
    check("Setup shows voice runtime and local mic readiness",
          "voiceRuntime" in setup_frontend
          and "This browser/app mic" in setup_frontend
          and "localVoiceEnvironment" in setup_frontend,
          "Setup must expose deployable voice readiness and local browser/app capture status.")
    check("Dashboard Builder has a pre-install preview",
          "DashboardPreview" in dashboard_builder_frontend
          and "Spatial assets" in dashboard_builder_frontend,
          "Dashboard drafts should show views/cards/spatial context before install.")
    check("Suggestions can edit automation drafts",
          "Edit YAML" in suggestions_frontend
          and "api.editDraft" in suggestions_frontend,
          "Automation drafts need owner-editable YAML before install.")
    check("house knowledge assets are first-class API + UI",
          "/house/assets" in backend_main
          and "houseAssets" in api_frontend
          and (repo_root / "frontend" / "src" / "pages" / "HouseKnowledge.tsx").is_file(),
          "Floor plans, blueprints, room photos, and notes need a managed upload/approval layer.")

    # Phase 0 — security rating 7 -> 8 and non-ingress API auth.
    apparmor = (repo_root / "tpg_homeai" / "apparmor.txt")
    check("add-on ships an AppArmor profile (rating 7 -> 8)",
          apparmor.is_file() and "profile tpg_homeai" in apparmor.read_text(encoding="utf-8"),
          "A named apparmor.txt profile raises the HA security rating by +1.")
    check("config.yaml enables apparmor + api_token option",
          "apparmor: true" in addon_config
          and "api_token:" in addon_config,
          "The add-on must enable its AppArmor profile and expose api_token.")
    check("run.sh exports the API token",
          "TPG_API_TOKEN" in run_sh,
          "run.sh must export the optional non-ingress API bearer token.")
    check("backend guards non-ingress API with a bearer token",
          "_auth_guard_response" in backend_main
          and "TPG_API_TOKEN" in (repo_root / "backend" / "app" / "settings.py").read_text(encoding="utf-8"),
          "Direct LAN callers must present Authorization: Bearer <token> when set.")

    # Phase 2b/2c/3 — hands-free panel mode + ChatGPT-style UI.
    tailwind = (repo_root / "frontend" / "tailwind.config.js").read_text(encoding="utf-8")
    check("frontend ships always-listening panel mode + wake word loop",
          "panelMode" in chat_frontend
          and "extractCommandAfterWakeWord" in chat_frontend
          and "getSpeechRecognition" in chat_frontend,
          "Tablets/old phones need a browser wake-word panel mode.")
    check("frontend renders markdown for assistant replies",
          "function Markdown" in chat_frontend,
          "Assistant messages should render lightweight markdown.")
    check("frontend uses the near-black ChatGPT-style theme",
          "#0a0a0a" in tailwind and "#171717" in tailwind,
          "The theme tokens should use near-black surfaces, not navy/sky.")

    print("PART 1 — API routing returns JSON, SPA never shadows API routes")
    r = client.get("/health")
    check("/health is JSON", is_json(r) and not is_html(r), r.headers.get("content-type", ""))
    check("/health has status", r.json().get("status") in ("ok", "degraded", "initializing"))

    r = client.get("/api/health")
    check("/api/health legacy prefix is JSON", is_json(r) and not is_html(r),
          r.headers.get("content-type", ""))

    ingress = "/3e5a55d6_tpg_homeai"
    hassio_ingress = "/api/hassio_ingress/3e5a55d6_tpg_homeai"
    r = client.get(f"{ingress}/api/health")
    check("ingress /api/health is JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    r = client.get(f"{ingress}/health")
    check("ingress /health is JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    r = client.get(f"{hassio_ingress}/api/health")
    check("hassio ingress /api/health is JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    r = client.get(f"{hassio_ingress}/health")
    check("hassio ingress /health is JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")

    r = client.post("/api/config/reload", json={})
    check("/api/config/reload legacy prefix works", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")

    r = client.post("/config/rooms", json={
        "id": "test_room",
        "name": "Test Room",
        "aliases": ["test room"],
        "lights": ["light.test_room"],
        "fans": [],
    })
    check("/config/rooms upserts room", r.status_code == 200 and r.json().get("saved") is True,
          r.text)
    check("/config/rooms reloads runtime",
          any(room.get("id") == "test_room" for room in client.get("/config").json().get("devices", {}).get("rooms", [])),
          client.get("/config").text)

    r = client.post("/config/assistants", json={
        "id": "test_assistant",
        "name": "Test Assistant",
        "owner": "shawn",
        "aliases": ["test assistant"],
        "wake_words": ["test assistant", "hey test"],
        "listen_enabled": True,
        "personality": "A concise test assistant.",
        "tone": "calm",
        "voice": {"provider": "openai", "model": "gpt-4o-mini-tts", "voice": "coral"},
    })
    check("/config/assistants upserts assistant",
          r.status_code == 200 and r.json().get("saved") is True,
          r.text)
    config_after_assistant = client.get("/config").json()
    test_assistant = next((a for a in config_after_assistant.get("assistants", {}).get("assistants", [])
                           if a.get("id") == "test_assistant"), {})
    check("/config/assistants saves wake words",
          test_assistant.get("wake_words") == ["test assistant", "hey test"],
          str(test_assistant))

    r = client.post("/config/users", json={
        "id": "shawn",
        "name": "Shawn",
        "role": "resident",
        "aliases": ["shawn", "boss", "owner"],
        "music_account": "spotify_xtpgx",
    })
    check("/config/users blocks demoting last owner",
          r.status_code == 400 and "no Owner/Admin" in r.text,
          r.text)

    r = client.post("/config/users", json={
        "id": "test_user",
        "name": "Test User",
        "aliases": ["tester"],
        "music_account": "spotify_xtpgx",
        "permissions": {"can_control_lights": True, "can_unlock_doors": False},
    })
    check("/config/users upserts user",
          r.status_code == 200 and r.json().get("saved") is True,
          r.text)

    r = client.post("/config/music-accounts", json={
        "id": "spotify_test",
        "name": "Spotify [test]",
        "provider": "spotify",
        "account": "test",
        "owner": "test_user",
        "default_media": {"media_id": "Daily Mix", "media_type": "playlist"},
    })
    check("/config/music-accounts upserts account",
          r.status_code == 200 and r.json().get("saved") is True,
          r.text)

    r = client.post("/config/speakers", json={
        "id": "test_speaker",
        "name": "Test Speaker",
        "entity_id": "media_player.test_speaker",
        "room": "test_room",
        "aliases": ["test speaker"],
    })
    check("/config/speakers upserts speaker",
          r.status_code == 200 and r.json().get("saved") is True,
          r.text)

    permissions = client.get("/config").json().get("permissions", {})
    permissions["confirmation_ttl_seconds"] = 90
    permissions.setdefault("sensitive_actions", ["unlock_door"])
    permissions.setdefault("confirmation_messages", {"unlock_door": "Confirm: unlock the {target}?"})
    r = client.post("/config/permissions", json=permissions)
    check("/config/permissions saves policy",
          r.status_code == 200 and r.json().get("saved") is True,
          r.text)

    r = client.post("/config/voice-sources", json={
        "id": "test_voice_source",
        "name": "Test Voice Source",
        "room": "test_room",
        "assistant": "test_assistant",
        "trust_level": "household",
        "default_reply": "browser",
        "aliases": ["test mic"],
    })
    check("/config/voice-sources upserts source",
          r.status_code == 200 and r.json().get("saved") is True,
          r.text)

    r = client.get("/discovery/summary")
    check("/discovery/summary is JSON", is_json(r), r.headers.get("content-type", ""))
    check("/discovery/summary has pending_count", "pending_count" in r.json())

    r = client.get("/state")
    check("/state is JSON", is_json(r))

    r = client.get("/ui/session")
    check("/ui/session is JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    ui = r.json()
    check("/ui/session has roles",
          ui.get("roles", {}).get("admin") and ui.get("roles", {}).get("resident")
          and ui.get("roles", {}).get("kiosk"),
          str(ui))
    check("/ui/session does not default to owner/admin without trusted HA identity",
          ui.get("detected_user", {}).get("id") == "house_remote"
          and ui.get("detected_user", {}).get("role") == "kiosk"
          and ui.get("role") == "kiosk"
          and ui.get("identity_trusted") is False
          and ui.get("identity_source") == "safe_fallback",
          str(ui))
    check("/ui/session defaults missing identity to shared Jarvis",
          ui.get("default_assistant", {}).get("id") == "jarvis",
          str(ui))
    r = client.get("/ui/session", headers={"x-ha-user-name": "Jordie"})
    check("/ui/session maps HA header to resident user",
          r.status_code == 200
          and r.json().get("detected_user", {}).get("id") == "jordie"
          and r.json().get("detected_user", {}).get("role") == "resident",
          str(r.json()))
    r = client.get("/ui/session", headers={"x-ha-user-id": "jordie"})
    check("/ui/session maps HA user-id header to resident user",
          r.status_code == 200
          and r.json().get("detected_user", {}).get("id") == "jordie"
          and r.json().get("identity_trusted") is True,
          str(r.json()))
    r = client.get("/ui/session", headers={"x-forwarded-user": "Jordie"})
    check("/ui/session ignores generic forwarded-user identity",
          r.status_code == 200
          and r.json().get("detected_user", {}).get("id") == "house_remote"
          and r.json().get("identity_source") == "safe_fallback",
          str(r.json()))
    r = client.get("/ui/session", headers={
        "x-ha-user-name": "Jordie",
        "x-ha-user-is-admin": "true",
    })
    check("/ui/session honors HA admin authority",
          r.status_code == 200
          and r.json().get("detected_user", {}).get("id") == "jordie"
          and r.json().get("detected_user", {}).get("role") == "admin"
          and r.json().get("role") == "admin"
          and r.json().get("ha_admin") is True,
          str(r.json()))
    r = client.get("/ui/session", headers={"x-ha-user-name": "jordie-rae"})
    check("/ui/session normalizes HA usernames",
          r.status_code == 200
          and r.json().get("detected_user", {}).get("id") == "jordie",
          str(r.json()))
    r = client.get("/ui/session", headers={"x-ha-user-name": "kiosk"})
    check("/ui/session maps HA header to kiosk user",
          r.status_code == 200
          and r.json().get("detected_user", {}).get("id") == "house_remote"
          and r.json().get("detected_user", {}).get("role") == "kiosk",
          str(r.json()))
    check("/ui/session defaults kiosk to Jarvis",
          r.json().get("default_assistant", {}).get("id") == "jarvis",
          str(r.json()))
    r = client.get("/ui/session", headers={"x-ha-user-name": "New HA User"})
    check("/ui/session reports unknown HA user",
          r.status_code == 200 and r.json().get("unknown_ha_user") == "new ha user",
          str(r.json()))
    r = client.get("/suggestions/proactive")
    check("unknown HA user creates setup suggestion",
          any(s.get("action_type") == "create_user_profile"
              and s.get("payload", {}).get("username") == "new ha user"
              for s in r.json().get("suggestions", [])),
          str(r.json()))

    # HA Supervisor ingress headers are the authoritative identity source.
    r = client.get("/ui/session", headers={"x-remote-user-name": "Shawn"})
    check("/ui/session maps ingress X-Remote-User-Name to owner",
          r.status_code == 200
          and r.json().get("detected_user", {}).get("id") == "shawn"
          and r.json().get("detected_user", {}).get("role") == "admin"
          and r.json().get("identity_trusted") is True
          and r.json().get("identity_source") == "ha_ingress",
          str(r.json()))
    r = client.get("/ui/session", headers={"x-remote-user-name": "Jordie"})
    check("/ui/session maps ingress X-Remote-User-Name to resident",
          r.status_code == 200
          and r.json().get("detected_user", {}).get("id") == "jordie"
          and r.json().get("detected_user", {}).get("role") == "resident"
          and r.json().get("identity_source") == "ha_ingress",
          str(r.json()))
    r = client.get("/ui/session", headers={"x-remote-user-display-name": "Jordie"})
    check("/ui/session maps ingress X-Remote-User-Display-Name",
          r.status_code == 200
          and r.json().get("detected_user", {}).get("id") == "jordie"
          and r.json().get("identity_source") == "ha_ingress",
          str(r.json()))
    r = client.get("/ui/session", headers={
        "x-remote-user-name": "Shawn",
        "x-ha-user-name": "Jordie",
    })
    check("/ui/session ingress header wins over legacy/stale header",
          r.status_code == 200
          and r.json().get("detected_user", {}).get("id") == "shawn"
          and r.json().get("identity_source") == "ha_ingress",
          str(r.json()))
    r = client.get("/ui/session/debug", headers={"x-remote-user-name": "Shawn"})
    dbg = r.json()
    check("/ui/session/debug reports ingress candidate + match",
          r.status_code == 200
          and "shawn" in dbg.get("candidates", {}).get("ingress", [])
          and dbg.get("matches", {}).get("ingress") == "shawn"
          and dbg.get("version"),
          str(dbg))

    current_user_payload = {"id": "ha-shawn-verified", "name": "Shawn", "username": "thatpalmerguy", "is_admin": True}

    async def fake_current_user(_self):
        return current_user_payload

    with patch("app.main.HomeAssistantWebSocket.fetch_current_user", fake_current_user):
        r = client.post("/ui/session", json={"ha_access_token": "verified-token"})
        check("/ui/session verified HA token maps Shawn owner",
              r.status_code == 200
              and r.json().get("detected_user", {}).get("id") == "shawn"
              and r.json().get("detected_user", {}).get("role") == "admin"
              and r.json().get("identity_source") == "ha_token",
              str(r.json()))
        current_user_payload = {"id": "ha-jordie-verified", "name": "Jordie", "username": "jordie", "is_admin": False}
        r = client.post("/ui/session", json={"ha_access_token": "verified-token"})
        check("/ui/session verified HA token maps Jordie resident",
              r.status_code == 200
              and r.json().get("detected_user", {}).get("id") == "jordie"
              and r.json().get("detected_user", {}).get("role") == "resident"
              and r.json().get("identity_source") == "ha_token",
              str(r.json()))
        r = client.post("/ui/session", json={
            "ha_access_token": "verified-token",
            "ha_client_user": {
                "id": "ha-shawn-live",
                "name": "Shawn",
                "username": "thatpalmerguy",
                "is_admin": True,
            },
        })
        check("/ui/session live HA parent user overrides stale token",
              r.status_code == 200
              and r.json().get("detected_user", {}).get("id") == "shawn"
              and r.json().get("detected_user", {}).get("role") == "admin"
              and r.json().get("identity_source") == "ha_parent",
              str(r.json()))
        r = client.post("/ui/session", json={
            "ha_client_user": {
                "id": "ha-kiosk-live",
                "name": "Kiosk",
                "username": "kiosk",
                "is_admin": False,
            },
        })
        check("/ui/session live HA parent user maps Kiosk to Jarvis",
              r.status_code == 200
              and r.json().get("detected_user", {}).get("id") == "house_remote"
              and r.json().get("default_assistant", {}).get("id") == "jarvis"
              and r.json().get("identity_source") == "ha_parent",
              str(r.json()))
        current_user_payload = {"id": "ha-kiosk-verified", "name": "Kiosk", "username": "kiosk", "is_admin": False}
        r = client.post("/ui/session", json={"ha_access_token": "verified-token"})
        check("/ui/session verified HA token maps Kiosk shared profile",
              r.status_code == 200
              and r.json().get("detected_user", {}).get("id") == "house_remote"
              and r.json().get("default_assistant", {}).get("id") == "jarvis"
              and r.json().get("identity_source") == "ha_token",
              str(r.json()))

    async def fake_auth_users(_self):
        return [
            {
                "id": "ha-admin-1",
                "name": "That Palmer Guy",
                "username": "thatpalmerguy",
                "is_admin": True,
            },
            {
                "id": "ha-resident-1",
                "name": "Resident Person",
                "username": "residentperson",
                "is_admin": False,
            },
            {
                "id": "ha-kiosk-1",
                "name": "Kiosk",
                "username": "kiosk",
                "is_admin": False,
            },
        ]

    with patch("app.main.HomeAssistantWebSocket.fetch_auth_users", fake_auth_users):
        r = client.post("/ha/users/sync")
    check("/ha/users/sync returns JSON",
          r.status_code == 200 and is_json(r) and r.json().get("synced") is True,
          f"status={r.status_code} body={r.text}")
    synced = r.json()
    check("/ha/users/sync creates HA-owned profiles",
          synced.get("created", 0) >= 2 and synced.get("counts", {}).get("users", 0) >= 4,
          str(synced))
    r = client.get("/config")
    synced_cfg = r.json().get("assistants", {})
    synced_users = synced_cfg.get("users", [])
    admin_profile = next((u for u in synced_users if u.get("ha_username") == "thatpalmerguy"), {})
    resident_profile = next((u for u in synced_users if u.get("ha_username") == "residentperson"), {})
    kiosk_profile = next((u for u in synced_users if u.get("ha_username") == "kiosk"), {})
    check("HA admin sync grants TPG admin access",
          admin_profile.get("role") == "admin"
          and admin_profile.get("access_source") == "home_assistant"
          and admin_profile.get("ha_is_admin") is True,
          str(admin_profile))
    check("HA non-admin sync grants resident self-service access",
          resident_profile.get("role") == "resident"
          and resident_profile.get("access_source") == "home_assistant"
          and resident_profile.get("ha_is_admin") is False,
          str(resident_profile))
    check("HA kiosk sync preserves shared kiosk profile",
          kiosk_profile.get("id") == "house_remote"
          and kiosk_profile.get("role") == "kiosk"
          and kiosk_profile.get("access_source") == "home_assistant"
          and kiosk_profile.get("ha_is_admin") is False,
          str(kiosk_profile))
    check("HA sync creates a personal assistant for resident users",
          any(a.get("owner") == resident_profile.get("id") for a in synced_cfg.get("assistants", [])),
          str(synced_cfg.get("assistants", [])))

    r = client.get("/config")
    check("/config is JSON", is_json(r))

    r = client.post("/dashboards/draft", json={"title": "TPG Home", "style": "native"})
    check("/dashboards/draft returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    body = r.json()
    check("/dashboards/draft includes yaml", bool(body.get("yaml")) and "views:" in body["yaml"],
          str(body))

    r = client.post("/dashboards/draft", json={
        "title": "TPG Home",
        "style": "native",
        "tablet_mode": True,
        "voice_panel": True,
    })
    check("/dashboards/draft supports tablet and voice views",
          r.status_code == 200 and "tpg-tablets" in r.json().get("yaml", "")
          and "tpg-voice" in r.json().get("yaml", ""),
          str(r.json()))

    r = client.post("/dashboards/install", json={"title": "TPG Home", "style": "native"})
    check("/dashboards/install returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    install_path = r.json().get("install", {}).get("path")
    check("/dashboards/install writes file", bool(install_path) and os.path.isfile(install_path),
          str(r.json()))

    r = client.get("/knowledge/graph?include_registries=false")
    check("/knowledge/graph returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/knowledge/graph has counts", "counts" in r.json(), str(r.json()))

    r = client.get("/brain/layers?include_registries=false")
    check("/brain/layers returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    brain = r.json()
    check("/brain/layers has Jarvis layers", len(brain.get("layers", [])) >= 7,
          str(brain))

    r = client.get("/brain/completion?include_registries=false")
    check("/brain/completion returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/brain/completion has stop criteria",
          "gates" in r.json() and "complete_spot" in r.json(),
          str(r.json()))

    r = client.get("/brain/house-state?include_registries=false")
    check("/brain/house-state returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/brain/house-state has modes", isinstance(r.json().get("modes"), list),
          str(r.json()))
    check("/brain/house-state includes mode brain and wake word",
          "mode_brain" in r.json() and "wake_word" in r.json(),
          str(r.json()))
    wake_word = r.json().get("wake_word", {})
    check("/brain/house-state wake word has assistants",
          bool(wake_word.get("assistants")) and "assistants_ready" in wake_word.get("counts", {}),
          str(wake_word))

    r = client.get("/brain/modes")
    check("/brain/modes returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/brain/modes has active policy",
          "active_modes" in r.json() and "policy" in r.json(),
          str(r.json()))

    r = client.get("/brain/assistants")
    check("/brain/assistants returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/brain/assistants includes assistant intelligence",
          len(r.json().get("assistants", [])) >= 2,
          str(r.json()))

    r = client.get("/knowledge/physical-devices?include_registries=false")
    check("/knowledge/physical-devices returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/knowledge/physical-devices has devices list", isinstance(r.json().get("devices"), list),
          str(r.json()))

    r = client.get("/knowledge/device-profiles?include_registries=false")
    check("/knowledge/device-profiles returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/knowledge/device-profiles has counts", "counts" in r.json(), str(r.json()))

    r = client.get("/knowledge/device-adapters?include_registries=false")
    check("/knowledge/device-adapters returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/knowledge/device-adapters has counts", "counts" in r.json(), str(r.json()))

    r = client.get("/knowledge/voice-sources")
    check("/knowledge/voice-sources returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/knowledge/voice-sources has list", "voice_sources" in r.json(), str(r.json()))
    check("/knowledge/voice-sources includes route readiness",
          "counts" in r.json() and r.json()["counts"].get("total", 0) >= 1,
          str(r.json()))

    r = client.get("/house/assets")
    check("/house/assets returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    r = client.post(
        "/house/assets",
        data={
            "title": "Office floor plan",
            "asset_type": "floorplan",
            "room": "Office",
            "uploaded_by": "shawn",
            "description": "Office layout note with desk, speaker, display, and light switch.",
        },
        files={"file": ("office-floorplan.txt", b"Office floor plan: desk, speaker, display, light switch.", "text/plain")},
    )
    check("/house/assets uploads draft asset",
          r.status_code == 200 and is_json(r) and r.json().get("asset", {}).get("status") == "draft",
          r.text)
    house_asset_id = r.json().get("asset", {}).get("id")
    check("/house/assets analyzes uploaded asset",
          bool(r.json().get("asset", {}).get("analysis", {}).get("summary")),
          str(r.json()))
    r = client.post(f"/house/assets/{house_asset_id}/approve")
    check("/house/assets/{id}/approve activates asset",
          r.status_code == 200 and r.json().get("asset", {}).get("status") == "approved",
          r.text)
    r = client.get("/house/assets?status=approved")
    check("/house/assets lists approved assets",
          any(a.get("id") == house_asset_id for a in r.json().get("assets", [])),
          str(r.json()))
    r = client.get(f"/house/assets/{house_asset_id}/file")
    check("/house/assets/{id}/file returns original file",
          r.status_code == 200 and b"Office floor plan" in r.content,
          f"status={r.status_code} body={r.text[:100] if hasattr(r, 'text') else ''}")
    r = client.get("/house/spatial-brain")
    check("/house/spatial-brain returns approved room context",
          r.status_code == 200
          and r.json().get("summary", {}).get("approved_assets", 0) >= 1
          and any(room.get("display_name") == "Office" for room in r.json().get("rooms", [])),
          str(r.json()))
    r = client.post("/dashboards/draft", json={"title": "TPG Office Spatial", "style": "native", "room": "Office"})
    check("/dashboards/draft includes spatial layout notes",
          r.status_code == 200
          and "AI Layout Notes" in r.json().get("yaml", "")
          and r.json().get("spatial_brain", {}).get("summary", {}).get("approved_assets", 0) >= 1,
          str(r.json()))
    r = client.post("/chat", json={
        "assistant": "atlas",
        "user": "shawn",
        "conversation_id": "house-asset-context",
        "message": "What room candidates are in my approved office floorplan asset?",
    })
    check("/chat includes approved house assets in context",
          "Approved house knowledge assets" in r.json().get("data", {}).get("house_context", ""),
          str(r.json()))

    r = client.get("/voice/deployment")
    check("/voice/deployment returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/voice/deployment has readiness counts",
          "counts" in r.json() and "sources" in r.json(),
          str(r.json()))
    voice_counts = r.json().get("counts", {})
    check("/voice/deployment separates wake words from source deployment",
          "assistants_with_wake_words" in voice_counts
          and "assistants_with_linked_sources" in voice_counts,
          str(voice_counts))
    r = client.get("/voice/runtime")
    check("/voice/runtime returns deployable assistant/source map",
          r.status_code == 200
          and "assistants" in r.json()
          and "room_routes" in r.json()
          and "runtime_sources" in r.json().get("counts", {}),
          str(r.json()))

    r = client.get("/dashboards/tablet-profiles")
    check("/dashboards/tablet-profiles returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/dashboards/tablet-profiles has counts", "counts" in r.json(), str(r.json()))

    r = client.get("/ai/providers")
    check("/ai/providers returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/ai/providers has fallback parser",
          r.json().get("providers", {}).get("fallback_parser", {}).get("available") is True,
          str(r.json()))

    r = client.get("/voice/profiles")
    check("/voice/profiles returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    voice_profiles = r.json()
    check("/voice/profiles has assistants",
          len(voice_profiles.get("profiles", [])) >= 2,
          str(voice_profiles))
    atlas_profile = next((p for p in voice_profiles.get("profiles", [])
                          if p.get("assistant", {}).get("id") == "atlas"), {})
    chatty_profile = next((p for p in voice_profiles.get("profiles", [])
                           if p.get("assistant", {}).get("id") == "chatty"), {})
    check("/voice/profiles atlas uses OpenAI Cedar",
          atlas_profile.get("provider") == "openai" and atlas_profile.get("voice") == "cedar",
          str(atlas_profile))
    check("/voice/profiles chatty uses OpenAI Coral",
          chatty_profile.get("provider") == "openai" and chatty_profile.get("voice") == "coral",
          str(chatty_profile))
    r = client.post("/config/assistants", json={
        "id": "atlas",
        "name": "Atlas",
        "owner": "shawn",
        "aliases": ["atlas"],
        "wake_words": ["atlas", "hey atlas"],
        "listen_enabled": True,
        "personality": "Legacy browser voice upgrade check.",
        "tone": "confident",
        "voice": {"provider": "browser", "voice": "neutral", "fallback_provider": "browser"},
    })
    check("/config/assistants accepts legacy browser voice", r.status_code == 200, r.text)
    r = client.get("/voice/profiles")
    legacy_atlas_profile = next((p for p in r.json().get("profiles", [])
                                 if p.get("assistant", {}).get("id") == "atlas"), {})
    check("/voice/profiles upgrades legacy atlas browser voice",
          legacy_atlas_profile.get("provider") == "openai"
          and legacy_atlas_profile.get("voice") == "cedar",
          str(legacy_atlas_profile))

    r = client.get("/voice/voices")
    check("/voice/voices returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/voice/voices includes catalog",
          any(v.get("id") == "coral" for v in r.json().get("voices", [])),
          str(r.json()))

    r = client.post("/voice/preview", json={
        "assistant": "chatty",
        "text": "Voice check.",
        "room": "office",
        "reply_mode": "room_speaker",
    })
    check("/voice/preview returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/voice/preview reports fallback when OpenAI absent",
          r.json().get("will_fallback_to_browser") is True,
          str(r.json()))
    check("/voice/preview resolves speaker route",
          r.json().get("profile", {}).get("route", {}).get("target_entity_id") == "media_player.office_speaker",
          str(r.json()))

    r = client.post("/voice/speak", json={
        "assistant": "atlas",
        "text": "Voice check.",
    })
    check("/voice/speak returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/voice/speak falls back to browser without key",
          r.json().get("mode") == "browser" and r.json().get("provider") == "browser",
          str(r.json()))
    check("/voice/speak fallback preserves atlas voice profile",
          r.json().get("profile", {}).get("provider") == "openai"
          and r.json().get("profile", {}).get("voice") == "cedar",
          str(r.json()))
    r = client.post("/voice/speak", json={
        "assistant": "atlas",
        "text": "Voice override check.",
        "voice_profile": {"provider": "openai", "model": "gpt-4o-mini-tts", "voice": "onyx"},
    })
    check("/voice/speak preserves editor voice override",
          r.status_code == 200
          and r.json().get("profile", {}).get("provider") == "openai"
          and r.json().get("profile", {}).get("voice") == "onyx",
          str(r.json()))
    r = client.post("/voice/transcribe", files={"file": ("voice-input.webm", b"fake-audio", "audio/webm")})
    check("/voice/transcribe returns JSON without OpenAI key", r.status_code == 200 and is_json(r), r.text)
    check("/voice/transcribe explains missing OpenAI key",
          r.json().get("success") is False
          and "OpenAI API key" in r.json().get("error", ""),
          str(r.json()))
    from app.voice import _openai_speech_bytes, _safe_error_detail  # noqa: E402

    class FakeSpeech:
        def __init__(self):
            self.calls: list[dict[str, object]] = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            if "instructions" in kwargs:
                raise TypeError("Speech.create() got an unexpected keyword argument 'instructions'")
            return type("FakeAudio", (), {"read": lambda self: b"audio-bytes"})()

    fake_speech = FakeSpeech()
    fake_client = type("FakeClient", (), {
        "audio": type("FakeAudioRoot", (), {
            "speech": fake_speech,
        })(),
    })()
    with patch("openai.OpenAI", return_value=fake_client):
        audio = _openai_speech_bytes({
            "model": "gpt-4o-mini-tts",
            "voice": "cedar",
            "response_format": "mp3",
            "instructions": "sound natural",
        }, "hello")
    check("OpenAI TTS retries old SDK without instructions",
          audio == b"audio-bytes"
          and len(fake_speech.calls) == 2
          and "instructions" in fake_speech.calls[0]
          and "instructions" not in fake_speech.calls[1],
          str(fake_speech.calls))
    check("OpenAI TTS error detail redacts API keys",
          "sk-***" in _safe_error_detail(Exception("bad key sk-abc123SECRET")),
          _safe_error_detail(Exception("bad key sk-abc123SECRET")))

    r = client.post("/memory/draft", json={
        "scope": "user",
        "owner": "shawn",
        "subject": "office",
        "key": "fan_preference",
        "value": "prefers high while gaming",
    })
    check("/memory/draft returns JSON", r.status_code == 200 and is_json(r), r.text)
    memory_id = r.json().get("memory", {}).get("id")
    check("/memory/draft creates id", bool(memory_id), str(r.json()))
    if memory_id:
        r = client.post(f"/memory/{memory_id}/approve")
        check("/memory/{id}/approve works",
              r.status_code == 200 and r.json().get("memory", {}).get("status") == "approved",
              r.text)

    r = client.post("/suggestions/generate")
    check("/suggestions/generate returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    r = client.post("/monitor/scan")
    check("/monitor/scan returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    r = client.get("/suggestions/proactive")
    check("/suggestions/proactive returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code}")

    r = client.post("/chat", json={
        "assistant": "atlas",
        "user": "shawn",
        "message": "Set a sleep timer on the office TV in 30 minutes.",
    })
    check("/chat returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    body = r.json()
    check("/chat creates proposal mode", body.get("mode") == "proposal", str(body))

    r = client.post("/chat", json={
        "assistant": "atlas",
        "user": "shawn",
        "message": "What is the weather like?",
    })
    check("/chat general weather returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    body = r.json()
    check("/chat general weather uses conversation mode",
          body.get("mode") == "conversation" and body.get("success") is True,
          str(body))

    r = client.post("/chat", json={
        "assistant": "atlas",
        "user": "shawn",
        "message": "Build a dashboard for the office with voice controls.",
    })
    check("/chat dashboard draft returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    body = r.json()
    check("/chat dashboard draft creates draft intent",
          body.get("command", {}).get("intent") == "draft_dashboard",
          str(body))
    check("/chat dashboard draft uses proposal mode",
          body.get("mode") == "proposal",
          str(body))
    check("/chat dashboard draft includes yaml",
          "yaml" in body.get("command", {}).get("data", {}).get("dashboard_draft", {}),
          str(body))
    check("/chat dashboard draft is proposal-gated",
          body.get("command", {}).get("data", {}).get("policy", {}).get("decision") == "proposal_required",
          str(body))

    r = client.post("/chat", json={
        "assistant": "chatty",
        "user": "jordie",
        "message": "Create scheduled task. Turn off all lights at 10 PM.",
    })
    check("/chat resident can draft scheduled automations",
          r.status_code == 200
          and r.json().get("mode") == "proposal"
          and r.json().get("command", {}).get("intent") == "create_simple_automation",
          str(r.json()))
    r = client.post("/test/action", json={
        "action": "create_simple_automation",
        "assistant": "atlas",
        "user": "shawn",
        "params": {
            "trigger_description": "at sunset when someone is home",
            "action_description": "turn on office light and turn off office fan",
            "original_request": "At sunset when someone is home, turn on office light and turn off office fan.",
        },
    })
    automation_yaml = r.json().get("data", {}).get("proposed_yaml", "")
    check("automation builder v2 supports sun, presence, and multi-action YAML",
          r.status_code == 200
          and "platform: sun" in automation_yaml
          and "Someone is home" in automation_yaml
          and automation_yaml.count("service:") >= 2,
          automation_yaml or str(r.json()))

    r = client.post("/chat", json={
        "assistant": "chatty",
        "user": "jordie",
        "message": "Build a dashboard for the office with voice controls.",
    })
    check("/chat resident cannot draft dashboards",
          r.status_code == 200
          and r.json().get("success") is False
          and r.json().get("command", {}).get("intent") == "draft_dashboard"
          and r.json().get("command", {}).get("error") == "role_not_allowed",
          str(r.json()))
    check("/chat resident dashboard denial is role policy",
          r.json().get("command", {}).get("data", {}).get("policy", {}).get("decision") == "denied",
          str(r.json()))

    r = client.post("/chat", json={
        "assistant": "atlas",
        "user": "shawn",
        "conversation_id": "verify-notebook-session",
        "message": "Let's brainstorm a cleaner office dashboard layout.",
    })
    check("/chat notebook seed returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")

    r = client.get("/conversations")
    check("/conversations returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/conversations includes seeded session",
          any(c.get("conversation_id") == "verify-notebook-session" for c in r.json().get("conversations", [])),
          str(r.json()))
    r = client.get("/conversations?assistant=atlas&user=shawn")
    check("/conversations filters by assistant and user",
          r.status_code == 200
          and all(c.get("assistant") == "atlas" and c.get("user") == "shawn"
                  for c in r.json().get("conversations", [])),
          str(r.json()))

    r = client.post("/conversations/verify-notebook-session/notes", json={
        "conversation_id": "verify-notebook-session",
        "assistant": "atlas",
        "user": "shawn",
        "title": "Office dashboard",
        "body": "Keep lighting, fan, camera, and music controls together.",
    })
    check("/conversations/{id}/notes creates note",
          r.status_code == 200 and r.json().get("note", {}).get("title") == "Office dashboard",
          r.text)

    r = client.get("/conversations/verify-notebook-session")
    check("/conversations/{id} returns transcript",
          r.status_code == 200 and len(r.json().get("messages", [])) >= 1,
          r.text)
    check("/conversations/{id} includes notes",
          len(r.json().get("notes", [])) >= 1,
          r.text)

    r = client.get("/conversations/verify-notebook-session/export")
    check("/conversations/{id}/export returns markdown JSON",
          r.status_code == 200 and "# " in r.json().get("markdown", ""),
          r.text)
    r = client.delete("/conversations/verify-notebook-session")
    check("/conversations/{id} DELETE soft-archives conversation",
          r.status_code == 200
          and r.json().get("archived") is True
          and r.json().get("conversation_id") == "verify-notebook-session",
          r.text)
    r = client.get("/conversations")
    check("archived conversation is hidden from list",
          r.status_code == 200
          and all(c.get("conversation_id") != "verify-notebook-session" for c in r.json().get("conversations", [])),
          str(r.json()))
    r = client.get("/conversations/verify-notebook-session")
    check("archived conversation detail preserves audit transcript",
          r.status_code == 200 and len(r.json().get("messages", [])) >= 1,
          r.text)

    r = client.post("/research/search", json={"query": "", "max_results": 3})
    check("/research/search returns structured JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/research/search validates query without crashing",
          r.json().get("error") == "Query is required.",
          str(r.json()))

    r = client.get("/debug/last-command")
    check("/debug/last-command returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/debug/last-command has command audit",
          r.json().get("command", {}).get("intent") in {"create_simple_automation", "draft_dashboard", "conversation"},
          str(r.json()))

    r = client.get("/debug/commands?limit=5")
    check("/debug/commands returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/debug/commands includes parsed tool call",
          isinstance(r.json().get("commands", [{}])[0].get("tool_call"), dict),
          str(r.json()))

    r = client.post("/command/preview", json={
        "assistant": "atlas",
        "user": "shawn",
        "message": "turn off office fan",
    })
    check("/command/preview returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    preview = r.json()
    check("/command/preview does not execute", preview.get("executed") is False,
          str(preview))
    check("/command/preview has dry-run data",
          preview.get("data", {}).get("preview", {}).get("dry_run") is True,
          str(preview))
    check("/command/preview safe action policy execute_now",
          preview.get("data", {}).get("policy", {}).get("decision") == "execute_now",
          str(preview))

    r = client.post("/chat/preview", json={
        "assistant": "atlas",
        "user": "shawn",
        "message": "unlock the front door",
    })
    check("/chat/preview returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    body = r.json()
    check("/chat/preview marks confirmation preview",
          body.get("mode") == "preview_confirmation_required",
          str(body))
    check("/chat/preview does not return live token",
          body.get("command", {}).get("confirmation_token") is None,
          str(body))
    check("/chat/preview unlock policy requires confirmation",
          body.get("command", {}).get("data", {}).get("policy", {}).get("decision")
          == "confirmation_required",
          str(body))

    before_preview_drafts = len(client.get("/suggestions").json().get("suggestions", []))
    r = client.post("/command/preview", json={
        "assistant": "atlas",
        "user": "shawn",
        "message": "set a sleep timer on the office TV in 20 minutes",
    })
    check("/command/preview timer returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    after_preview_drafts = len(client.get("/suggestions").json().get("suggestions", []))
    check("/command/preview timer does not create draft",
          before_preview_drafts == after_preview_drafts,
          f"{before_preview_drafts}->{after_preview_drafts}")

    r = client.get("/suggestions")
    check("/suggestions is JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code}")
    suggestions = r.json().get("suggestions", [])
    check("/suggestions includes draft", len(suggestions) >= 1, str(suggestions))
    if suggestions:
        draft_id = suggestions[0]["id"]
        r = client.post(f"/automation/drafts/{draft_id}/approve")
        check("/automation/drafts/{id}/approve works",
              r.status_code == 200 and r.json().get("approved") is True,
              r.text)
        check("/automation/drafts/{id}/approve installs",
              r.json().get("installed") is True,
              r.text)
        check("automations.yaml written",
              os.path.isfile(os.path.join(_HA_CFG, "automations.yaml")))

    # Unknown API route under a known prefix => JSON 404, not HTML.
    r = client.get("/discovery/does-not-exist")
    check("unknown API route is JSON 404", r.status_code == 404 and is_json(r) and not is_html(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    r = client.get("/dashboards/does-not-exist")
    check("unknown dashboard API route is JSON 404",
          r.status_code == 404 and is_json(r) and not is_html(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    r = client.get("/memory/does-not-exist")
    check("unknown memory API route is JSON 404",
          r.status_code == 404 and is_json(r) and not is_html(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    r = client.get("/conversations/does-not-exist/extra")
    check("unknown conversations API route is JSON 404",
          r.status_code == 404 and is_json(r) and not is_html(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")

    print("Frontend routes return HTML")
    r = client.get("/")
    check("GET / is HTML", is_html(r), r.headers.get("content-type", ""))
    r = client.get(f"{ingress}")
    check("GET ingress root is HTML", is_html(r), r.headers.get("content-type", ""))
    r = client.get("/dashboard")
    check("GET /dashboard is HTML", is_html(r))
    r = client.get(f"{ingress}/discovery")
    check("GET ingress discovery route is HTML", is_html(r),
          r.headers.get("content-type", ""))
    r = client.get(f"{ingress}/chat")
    check("GET ingress chat route is HTML", is_html(r),
          r.headers.get("content-type", ""))
    r = client.get(f"{ingress}/notebook")
    check("GET ingress notebook route is HTML", is_html(r),
          r.headers.get("content-type", ""))
    r = client.get(f"{ingress}/suggestions")
    check("GET ingress suggestions route is HTML", is_html(r),
          r.headers.get("content-type", ""))
    r = client.get(f"{ingress}/setup")
    check("GET ingress setup route is HTML", is_html(r),
          r.headers.get("content-type", ""))
    r = client.get(f"{ingress}/profiles")
    check("GET ingress profiles route is HTML", is_html(r),
          r.headers.get("content-type", ""))
    r = client.get(f"{ingress}/memory-center")
    check("GET ingress memory center route is HTML", is_html(r),
          r.headers.get("content-type", ""))
    r = client.get(f"{ingress}/dashboard-builder")
    check("GET ingress dashboard builder route is HTML", is_html(r),
          r.headers.get("content-type", ""))
    r = client.get(f"{ingress}/voice-settings")
    check("GET ingress voice settings route is HTML", is_html(r),
          r.headers.get("content-type", ""))
    r = client.get(f"{ingress}/house-brain")
    check("GET ingress house brain route is HTML", is_html(r),
          r.headers.get("content-type", ""))
    r = client.get(f"{ingress}/voice-sources")
    check("GET ingress voice sources route is HTML", is_html(r),
          r.headers.get("content-type", ""))
    r = client.get(f"{ingress}/ha")
    check("GET ingress HA route is HTML", is_html(r),
          r.headers.get("content-type", ""))
    r = client.get(f"{ingress}/assets/app.js")
    check("GET ingress asset is JS", r.status_code == 200 and is_js(r) and not is_html(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')} body={r.text[:40]}")
    r = client.get(f"{hassio_ingress}/assets/app.js")
    check("GET hassio ingress asset is JS", r.status_code == 200 and is_js(r) and not is_html(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')} body={r.text[:40]}")
    r = client.get("/ha-integration")
    check("GET /ha-integration is HTML", is_html(r))
    r = client.get("/some/unknown/spa/route")
    check("unknown frontend route is HTML", is_html(r))

    print("PART 2/4 — bootstrap + degraded health")
    check("bootstrap marked ready", state.ready is True)
    check("config dir created", os.path.isdir(_CFG))
    check("devices.yaml seeded", os.path.isfile(os.path.join(_CFG, "devices.yaml")),
          "(requires repo ./config template)")
    check("discovered.yaml created", os.path.isfile(os.path.join(_CFG, "discovered.yaml")))
    check("ignored.yaml created", os.path.isfile(os.path.join(_CFG, "ignored.yaml")))

    h = client.get("/health").json()
    check("HA unreachable -> degraded (not crashed)", h["status"] == "degraded",
          str(h.get("reasons")))
    check("openai fallback mode", h["openai"]["mode"] == "fallback_parser")
    check("openai not configured", h["openai"]["configured"] is False)

    print("PART 5 — discovery summary after startup scan")
    s = client.get("/discovery/summary").json()
    check("last_scan_ts populated after scan", s["last_scan_ts"] is not None,
          "scan_on_start should have run")
    check("summary message cleared after scan", s["message"] is None)

    print(f"\n{_PASS} passed, {_FAIL} failed")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
