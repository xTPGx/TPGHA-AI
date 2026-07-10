"""Phase 4 stabilization checks for the HomeAI add-on/runtime.

Runs offline. It verifies readiness/diagnostics contracts, deterministic
operation without cloud AI, sensitive-action confirmation replay/expiry, direct
API auth, and version alignment.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_TMP_ROOT = _ROOT / ".tpg-codex" / "tmp"
_TMP_ROOT.mkdir(parents=True, exist_ok=True)
_TMP_NAME = f"phase4-{os.getpid()}-{time.time_ns()}"
_TMP = _TMP_ROOT / _TMP_NAME
_TMP.mkdir(parents=True)
_CFG = _TMP / "cfg"
shutil.copytree(_ROOT / "config", _CFG, dirs_exist_ok=True)

os.environ["CONFIG_DIR"] = str(_CFG)
os.environ["DATABASE_URL"] = f"sqlite:///file:{_TMP_NAME}?mode=memory&cache=shared&uri=true"
os.environ["HOME_ASSISTANT_URL"] = "http://user:ha-secret@supervisor/core?token=ha-query-secret"
os.environ["HOME_ASSISTANT_TOKEN"] = "ha-token-secret"
os.environ["OPENAI_API_KEY"] = ""
os.environ["TPG_API_TOKEN"] = "direct-api-secret"
os.environ["TPG_SECURITY_PIN"] = "123456"
os.environ["TPG_PLATFORM_AGENT_TOKEN"] = "smartops-agent-secret"
os.environ["TPG_PLATFORM_ACTIVATION_CODE"] = "activation-secret"
os.environ["TPG_PLATFORM_SYNC_ENABLED"] = "false"

sys.path.insert(0, str(_ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app import __version__  # noqa: E402
from app.actions import control  # noqa: E402
from app.bootstrap import bootstrap  # noqa: E402
from app.db.database import engine, init_db  # noqa: E402
from app.homeassistant import rest  # noqa: E402
from app.main import APP_VERSION, app  # noqa: E402
from app.models.schemas import HAEntity  # noqa: E402
from app.router import intent_router  # noqa: E402
from app.router.permissions import get_confirmation_store  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, str, str]] = []
SERVICE_CALLS: list[tuple[str, str, dict]] = []
DIRECT_API_HEADERS = {"Authorization": "Bearer direct-api-secret"}


def check(name: str, condition: bool, detail: object = "") -> None:
    status = PASS if condition else FAIL
    results.append((status, name, str(detail)))
    print(f"[{status}] {name}" + (f" -- {detail}" if detail else ""))


def called(domain: str, service: str, entity_id: str | None = None) -> bool:
    return any(
        d == domain and s == service and (entity_id is None or data.get("entity_id") == entity_id)
        for d, s, data in SERVICE_CALLS
    )


async def fake_safe_get_states() -> dict[str, HAEntity]:
    return {
        "light.office": HAEntity(
            entity_id="light.office",
            state="on",
            friendly_name="Office Light",
            domain="light",
            available=True,
        ),
        "light.office_lamp": HAEntity(
            entity_id="light.office_lamp",
            state="off",
            friendly_name="Office Lamp",
            domain="light",
            available=True,
        ),
        "light.office_ceiling": HAEntity(
            entity_id="light.office_ceiling",
            state="off",
            friendly_name="Office Ceiling",
            domain="light",
            available=True,
        ),
        "lock.front_door": HAEntity(
            entity_id="lock.front_door",
            state="locked",
            friendly_name="Front Door",
            domain="lock",
            available=True,
        ),
        "fan.garage": HAEntity(
            entity_id="fan.garage",
            state="unavailable",
            friendly_name="Garage Fan",
            domain="fan",
            available=False,
        ),
    }


async def main() -> int:
    init_db()
    intent_router.safe_get_states = fake_safe_get_states

    async def rec_call_service(self, domain, service, data=None, *, return_response=False):
        SERVICE_CALLS.append((domain, service, data or {}))
        return {"ok": True}

    async def fake_get_entity(self, entity_id):
        states = await fake_safe_get_states()
        item = states.get(entity_id)
        return {
            "entity_id": entity_id,
            "state": item.state if item else "unknown",
            "attributes": {},
        }

    async def fake_ping(self):
        return {"connected": False}

    rest.HomeAssistantREST.call_service = rec_call_service
    rest.HomeAssistantREST.get_entity = fake_get_entity
    rest.HomeAssistantREST.ping = fake_ping

    await bootstrap()
    client = TestClient(app)

    repo_config = (_ROOT / "tpg_homeai" / "config.yaml").read_text(encoding="utf-8")
    dockerfile = (_ROOT / "tpg_homeai" / "Dockerfile").read_text(encoding="utf-8")
    manifest = (_ROOT / "custom_components" / "tpg_homeai" / "manifest.json").read_text(encoding="utf-8")
    check("version metadata aligned for restart/upgrade", all(v in repo_config + dockerfile + manifest for v in [APP_VERSION]) and __version__ == APP_VERSION, APP_VERSION)

    ready = client.get("/ready")
    check("/ready is public JSON", ready.status_code == 200 and ready.headers["content-type"].startswith("application/json"))
    ready_json = ready.json()
    check("/ready reports API ready despite degraded dependencies", ready_json["ready"] is True and ready_json["degraded"] is True, ready_json)
    check("/ready declares cloud and SmartOps optional", ready_json["cloud_ai_required_for_deterministic_commands"] is False and ready_json["smartops_required_for_local_operation"] is False, ready_json)

    unauth = client.get("/diagnostics")
    check("/diagnostics requires direct API auth", unauth.status_code == 401, unauth.text)
    diagnostics = client.get("/diagnostics", headers=DIRECT_API_HEADERS)
    check("/diagnostics returns JSON with auth", diagnostics.status_code == 200 and diagnostics.headers["content-type"].startswith("application/json"), diagnostics.text)
    diag_blob = json.dumps(diagnostics.json(), sort_keys=True)
    for secret in (
        "direct-api-secret",
        "ha-token-secret",
        "ha-secret",
        "ha-query-secret",
        "smartops-agent-secret",
        "activation-secret",
        "123456",
    ):
        check(f"diagnostics redacts {secret}", secret not in diag_blob)
    check("diagnostics excludes private household streams/history", diagnostics.json()["privacy"]["includes_conversation_text"] is False and diagnostics.json()["privacy"]["includes_full_ha_event_history"] is False)

    tools = client.get("/tools", headers=DIRECT_API_HEADERS)
    check("/tools exposes fixed allowlist contract", tools.status_code == 200 and tools.json()["allowlist"]["arbitrary_home_assistant_services"] is False, tools.text)

    SERVICE_CALLS.clear()
    ordinary = await intent_router.handle_command("atlas", "shawn", "turn off office light")
    check("deterministic command works without cloud AI", ordinary.intent == "turn_off_light" and ordinary.executed is True, ordinary)
    check("ordinary command calls vetted HA service", called("light", "turn_off", "light.office"), SERVICE_CALLS)

    unavailable = await intent_router.handle_command("atlas", "shawn", "turn off garage fan")
    check("unavailable entity does not crash deterministic route", unavailable.intent in {"turn_off_fan", "control_device"} and unavailable.success in {True, False}, unavailable)

    SERVICE_CALLS.clear()
    ctx = await intent_router.build_context("atlas", "shawn")
    sensitive = await control.execute_service_plan(
        ctx,
        {
            "type": "service",
            "domain": "cover",
            "service": "open_cover",
            "data": {"entity_id": "cover.garage_door"},
            "success_message": "Opened Garage Door.",
        },
        "Garage Door",
        "control_device",
    )
    check("direct sensitive service plan requires confirmation", sensitive.requires_confirmation is True and sensitive.executed is False, sensitive)
    check("direct sensitive service plan did not execute", not called("cover", "open_cover"), SERVICE_CALLS)

    replay_token = sensitive.confirmation_token
    replay_missing_pin = await intent_router.handle_confirmation(replay_token)
    check("sensitive confirmation enforces configured PIN", replay_missing_pin.success is False and replay_missing_pin.executed is False, replay_missing_pin)

    sensitive = await control.execute_service_plan(
        ctx,
        {
            "type": "service",
            "domain": "cover",
            "service": "open_cover",
            "data": {"entity_id": "cover.garage_door"},
            "success_message": "Opened Garage Door.",
        },
        "Garage Door",
        "control_device",
    )
    replay_token = sensitive.confirmation_token
    confirmed = await intent_router.handle_confirmation(replay_token, "123456")
    check("valid confirmation executes once", confirmed.success is True and confirmed.executed is True and called("cover", "open_cover", "cover.garage_door"), confirmed)
    reused = await intent_router.handle_confirmation(replay_token, "123456")
    check("confirmation replay is rejected", reused.success is False and reused.executed is False, reused)

    pc = get_confirmation_store().create(
        intent="unlock_door",
        params={},
        message="Confirm expired",
        ttl=1,
        assistant="atlas",
        user="shawn",
        plan={"type": "service", "domain": "lock", "service": "unlock", "data": {"entity_id": "lock.front_door"}},
        risk_level="critical",
        target="Front Door",
        pin_required=True,
    )
    pc.expires_at = time.monotonic() - 1
    expired = await intent_router.handle_confirmation(pc.token, "123456")
    check("expired confirmation is rejected", expired.success is False and expired.executed is False, expired)

    denied = await intent_router.handle_command("atlas", "house_remote", "unlock the front door")
    check("unauthorized user cannot create unlock execution", denied.success is False and denied.executed is False and not called("lock", "unlock"), denied)

    print("\n--- SUMMARY ---")
    failed = [item for item in results if item[0] == FAIL]
    print(f"{len(results) - len(failed)}/{len(results)} checks passed.")
    for _status, name, detail in failed:
        print(f"FAILED: {name} ({detail})")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    finally:
        engine.dispose()
        shutil.rmtree(_TMP, ignore_errors=True)
