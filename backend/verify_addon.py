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

# ---- Environment MUST be set before importing the app (settings/db cache it).
_TMP = tempfile.mkdtemp(prefix="tpg_addon_test_")
_CFG = os.path.join(_TMP, "cfg")
_STATIC = os.path.join(_TMP, "static")
os.makedirs(os.path.join(_STATIC, "assets"), exist_ok=True)
with open(os.path.join(_STATIC, "index.html"), "w", encoding="utf-8") as fh:
    fh.write("<!doctype html><html><body><div id='root'></div></body></html>")
with open(os.path.join(_STATIC, "assets", "app.js"), "w", encoding="utf-8") as fh:
    fh.write("console.log('tpg');")

os.environ["CONFIG_DIR"] = _CFG
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
    manifest = (repo_root / "custom_components" / "tpg_homeai" / "manifest.json").read_text(encoding="utf-8")
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
    check("ingress sidebar enabled", "ingress: true" in addon_config and "panel_title:" in addon_config)

    print("PART 1 — API routing returns JSON, SPA never shadows API routes")
    r = client.get("/health")
    check("/health is JSON", is_json(r) and not is_html(r), r.headers.get("content-type", ""))
    check("/health has status", r.json().get("status") in ("ok", "degraded", "initializing"))

    r = client.get("/api/health")
    check("/api/health legacy prefix is JSON", is_json(r) and not is_html(r),
          r.headers.get("content-type", ""))

    ingress = "/3e5a55d6_tpg_homeai"
    r = client.get(f"{ingress}/api/health")
    check("ingress /api/health is JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    r = client.get(f"{ingress}/health")
    check("ingress /health is JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")

    r = client.post("/api/config/reload", json={})
    check("/api/config/reload legacy prefix works", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")

    r = client.get("/discovery/summary")
    check("/discovery/summary is JSON", is_json(r), r.headers.get("content-type", ""))
    check("/discovery/summary has pending_count", "pending_count" in r.json())

    r = client.get("/state")
    check("/state is JSON", is_json(r))

    r = client.get("/config")
    check("/config is JSON", is_json(r))

    r = client.post("/dashboards/draft", json={"title": "TPG Home", "style": "native"})
    check("/dashboards/draft returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    body = r.json()
    check("/dashboards/draft includes yaml", bool(body.get("yaml")) and "views:" in body["yaml"],
          str(body))

    r = client.get("/knowledge/graph?include_registries=false")
    check("/knowledge/graph returns JSON", r.status_code == 200 and is_json(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")
    check("/knowledge/graph has counts", "counts" in r.json(), str(r.json()))

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
    r = client.get(f"{ingress}/suggestions")
    check("GET ingress suggestions route is HTML", is_html(r),
          r.headers.get("content-type", ""))
    r = client.get(f"{ingress}/ha")
    check("GET ingress HA route is HTML", is_html(r),
          r.headers.get("content-type", ""))
    r = client.get(f"{ingress}/assets/app.js")
    check("GET ingress asset is JS", r.status_code == 200 and is_js(r) and not is_html(r),
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
