"""Quick in-process API smoke test (no network)."""
import os
import sys
import time
from pathlib import Path

db_name = f"smoke_api_{os.getpid()}_{time.time_ns()}"
os.environ["CONFIG_DIR"] = str(Path(__file__).resolve().parents[1] / "config")
os.environ["DATABASE_URL"] = f"sqlite:///file:{db_name}?mode=memory&cache=shared&uri=true"
os.environ["TPG_API_TOKEN"] = "smoke-api-secret"
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("HOME_ASSISTANT_TOKEN", None)
sys.path.insert(0, os.path.dirname(__file__))

from fastapi.testclient import TestClient  # noqa: E402
from app.db.database import engine  # noqa: E402
from app.main import app  # noqa: E402

auth = {"Authorization": "Bearer smoke-api-secret"}

try:
    with TestClient(app) as c:
        print("GET /health ->", c.get("/health").status_code)
        h = c.get("/health").json()
        print("   openai_mode:", h["openai"]["mode"], "| ha configured:", h["home_assistant"]["configured"])

        print("GET /config ->", c.get("/config", headers=auth).status_code)
        print("GET /tools ->", c.get("/tools", headers=auth).json()["tools"][:3], "...")

        r = c.post("/test/resolve", headers=auth, json={"kind": "camera", "name": "driveway"}).json()
        print("resolve camera 'driveway' ->", r["entity_id"], f"(conf {r['confidence']})")

        r = c.post("/command", headers=auth, json={"assistant": "atlas", "user": "shawn",
                                                   "message": "show me the front door"}).json()
        print("command show front door ->", r["intent"], "|", r["resolved"].get("entity_id"))

        r = c.post("/command", headers=auth, json={"assistant": "atlas", "user": "shawn",
                                                   "message": "unlock the front door"}).json()
        print("command unlock ->", "requires_confirmation:", r["requires_confirmation"],
              "| executed:", r["executed"])

        print("ALL SMOKE CALLS OK")
finally:
    engine.dispose()
