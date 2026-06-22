"""Verify the backend accepts the integration's payload field names."""
import os
import sys

os.environ.pop("CONFIG_DIR", None)
os.environ["CONFIG_DIR"] = os.path.join(os.path.dirname(__file__), "..", "config")
os.environ["DATABASE_URL"] = "sqlite:///./smoke_integ.db"
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("HOME_ASSISTANT_TOKEN", None)
sys.path.insert(0, os.path.dirname(__file__))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

c = TestClient(app)

# Integration-style payload: assistant_id / user_id / text / conversation_id
r = c.post("/command", json={
    "assistant_id": "atlas",
    "user_id": "shawn",
    "text": "show me the driveway",
    "conversation_id": "abc-123",
}).json()
assert r["intent"] == "show_camera", r
assert r["resolved"].get("entity_id") == "camera.front_yard_front_yard", r
assert r["conversation_id"] == "abc-123", r
print("integration payload ->", r["intent"], r["resolved"]["entity_id"], "| conv:", r["conversation_id"])

# Native payload still works.
r2 = c.post("/command", json={
    "assistant": "chatty", "user": "jordie", "message": "play my music in the kitchen",
}).json()
assert r2["resolved"].get("music_account") == "spotify_jordierae22", r2
print("native payload ->", r2["intent"], r2["resolved"]["music_account"])

print("INTEGRATION SMOKE OK")
