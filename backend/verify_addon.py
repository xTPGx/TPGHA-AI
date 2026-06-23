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
import sys
import tempfile

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
from app.db.database import init_db  # noqa: E402
from app.main import app  # noqa: E402

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


def main() -> int:
    init_db()
    # Run bootstrap deterministically (instead of the background lifespan task).
    asyncio.run(bootstrap_mod.bootstrap())
    state = bootstrap_mod.get_app_state()

    # TestClient WITHOUT a context manager => no lifespan, no double bootstrap.
    client = TestClient(app)

    print("PART 1 — API routing returns JSON, SPA never shadows API routes")
    r = client.get("/health")
    check("/health is JSON", is_json(r) and not is_html(r), r.headers.get("content-type", ""))
    check("/health has status", r.json().get("status") in ("ok", "degraded", "initializing"))

    r = client.get("/discovery/summary")
    check("/discovery/summary is JSON", is_json(r), r.headers.get("content-type", ""))
    check("/discovery/summary has pending_count", "pending_count" in r.json())

    r = client.get("/state")
    check("/state is JSON", is_json(r))

    r = client.get("/config")
    check("/config is JSON", is_json(r))

    # Unknown API route under a known prefix => JSON 404, not HTML.
    r = client.get("/discovery/does-not-exist")
    check("unknown API route is JSON 404", r.status_code == 404 and is_json(r) and not is_html(r),
          f"status={r.status_code} ctype={r.headers.get('content-type')}")

    print("Frontend routes return HTML")
    r = client.get("/")
    check("GET / is HTML", is_html(r), r.headers.get("content-type", ""))
    r = client.get("/dashboard")
    check("GET /dashboard is HTML", is_html(r))
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
