"""Quick in-process API smoke test (no network)."""
import os
import sys

os.environ.setdefault("CONFIG_DIR", os.path.join(os.path.dirname(__file__), "..", "config"))
os.environ.setdefault("DATABASE_URL", "sqlite:///./smoke_api.db")
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("HOME_ASSISTANT_TOKEN", None)
sys.path.insert(0, os.path.dirname(__file__))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

c = TestClient(app)

print("GET /health ->", c.get("/health").status_code)
h = c.get("/health").json()
print("   openai_mode:", h["openai_mode"], "| ha configured:", h["home_assistant"]["configured"])

print("GET /config ->", c.get("/config").status_code)
print("GET /tools ->", c.get("/tools").json()["tools"][:3], "...")

r = c.post("/test/resolve", json={"kind": "camera", "name": "driveway"}).json()
print("resolve camera 'driveway' ->", r["entity_id"], f"(conf {r['confidence']})")

r = c.post("/command", json={"assistant": "atlas", "user": "shawn",
                             "message": "show me the front door"}).json()
print("command show front door ->", r["intent"], "|", r["resolved"].get("entity_id"))

r = c.post("/command", json={"assistant": "atlas", "user": "shawn",
                             "message": "unlock the front door"}).json()
print("command unlock ->", "requires_confirmation:", r["requires_confirmation"],
      "| executed:", r["executed"])

print("ALL SMOKE CALLS OK")
