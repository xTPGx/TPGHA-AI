"""Extended acceptance checks for the Home Assistant-native refactor.

Covers PART 1 (confirmation security), PART 2 (discovery/classification),
PART 3 (generic capability control), PART 8 (music media_id), PART 9/10
(display schema + degraded config). Runs fully offline: HA service calls are
recorded, states are injected, no OpenAI.
"""
import asyncio
import os
import shutil
import sys
import tempfile
import time

_SRC_CONFIG = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config"))
_TMP_CONFIG = tempfile.mkdtemp(prefix="tpg_ext_cfg_")
shutil.copytree(_SRC_CONFIG, _TMP_CONFIG, dirs_exist_ok=True)
for _overlay in ("discovered.yaml", "ignored.yaml"):
    with open(os.path.join(_TMP_CONFIG, _overlay), "w", encoding="utf-8") as _fh:
        _fh.write("{}\n")

os.environ["CONFIG_DIR"] = _TMP_CONFIG
os.environ["DATABASE_URL"] = "sqlite:///./verify_ext_tmp.db"
os.environ.pop("OPENAI_API_KEY", None)
sys.path.insert(0, os.path.dirname(__file__))

from app.db.database import init_db  # noqa: E402
from app.homeassistant import rest, services as ha_services  # noqa: E402
from app.models.schemas import HAEntity  # noqa: E402
from app.router import intent_router  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
results = []
SERVICE_CALLS: list[tuple[str, str, dict]] = []


def check(name, condition, detail=""):
    status = PASS if condition else FAIL
    results.append((status, name, detail))
    print(f"[{status}] {name}" + (f" -- {detail}" if detail else ""))


def called(domain, service, entity_id=None):
    return any(d == domain and s == service and
               (entity_id is None or data.get("entity_id") == entity_id)
               for d, s, data in SERVICE_CALLS)


FAKE_STATES = {
    "lock.front_door": "locked",
    "light.office": "off",
    "light.new_lamp": "on",
    "fan.office": "on",
    "fan.den_fan": "unavailable",
    "fan.garage": "unavailable",
    "climate.living_room_living_room": "cool",
    "camera.front_yard_front_yard": "streaming",
    "media_player.office_speaker": "idle",
}
FAKE_FRIENDLY = {
    "light.new_lamp": "Office Lamp",
    "fan.den_fan": "Den Fan",
}


async def main():
    init_db()

    async def rec_call_service(self, domain, service, data=None):
        SERVICE_CALLS.append((domain, service, data or {}))
        return {"ok": True}
    rest.HomeAssistantREST.call_service = rec_call_service

    async def fake_get_entity(self, entity_id):
        attrs = {"supported_features": 1} if entity_id.startswith("fan.") else {}
        return {"entity_id": entity_id,
                "state": FAKE_STATES.get(entity_id, "idle"),
                "attributes": attrs}
    rest.HomeAssistantREST.get_entity = fake_get_entity

    # Inject live states for discovery + resolver availability.
    def build_states():
        out = {}
        for eid, st in FAKE_STATES.items():
            out[eid] = HAEntity(entity_id=eid, state=st,
                                friendly_name=FAKE_FRIENDLY.get(eid),
                                domain=eid.split(".")[0],
                                available=st not in ("unavailable", "unknown"))
        return out

    async def fake_safe_get_states():
        return build_states()
    ha_services.safe_get_states = fake_safe_get_states
    # discovery + router import safe_get_states by reference; patch those too.
    import app.discovery.scanner as scanner
    import app.router.intent_router as ir
    scanner.safe_get_states = fake_safe_get_states
    if hasattr(ir, "safe_get_states"):
        ir.safe_get_states = fake_safe_get_states

    # ---------------------------------------------------------- PART 1: security
    SERVICE_CALLS.clear()
    r = await intent_router.handle_command("atlas", "shawn", "Unlock the front door.")
    check("P1 unlock requires confirmation", r.requires_confirmation is True)
    check("P1 unlock not executed", r.executed is False)
    check("P1 unlock token present", bool(r.confirmation_token))
    check("P1 /command did NOT call lock.unlock", not called("lock", "unlock"),
          str(SERVICE_CALLS))

    token = r.confirmation_token
    r2 = await intent_router.handle_confirmation(token)
    check("P1 /confirm executed", r2.executed is True)
    check("P1 /confirm called lock.unlock", called("lock", "unlock", "lock.front_door"))

    # invalid token
    r3 = await intent_router.handle_confirmation("not-a-real-token")
    check("P1 invalid token fails", r3.success is False and r3.executed is False)

    # reused token (already popped) fails
    r4 = await intent_router.handle_confirmation(token)
    check("P1 reused token fails", r4.success is False)

    # expired token
    from app.router.permissions import get_confirmation_store
    store = get_confirmation_store()
    pc = store.create(intent="unlock_door", params={}, message="x", ttl=1,
                      assistant="atlas", user="shawn",
                      plan={"type": "service", "domain": "lock", "service": "unlock",
                            "data": {"entity_id": "lock.front_door"}})
    pc.expires_at = time.monotonic() - 5  # force-expire
    r5 = await intent_router.handle_confirmation(pc.token)
    check("P1 expired token fails", r5.success is False and r5.executed is False)

    # control_device unlock also gated
    SERVICE_CALLS.clear()
    r = await intent_router.handle_command("atlas", "shawn",
                                           "control the front door lock unlock")
    # (phrasing may route via pre-router 'unlock'); ensure no direct unlock
    check("P1 generic unlock not auto-executed", not called("lock", "unlock"))

    # ---------------------------------------------------- PART 3: generic control
    SERVICE_CALLS.clear()
    from app.actions import control
    ctx = await intent_router.build_context("atlas", "shawn")

    r = await control.control_device(ctx, {"target": "office light", "action": "turn_off"})
    check("P3 control light turn_off executed", r.executed is True)
    check("P3 control light calls light.turn_off", called("light", "turn_off", "light.office"))

    r = await control.control_device(ctx, {"target": "office fan", "action": "set_percentage",
                                           "value": "40"})
    check("P3 control fan set_percentage", called("fan", "set_percentage", "fan.office"))

    r = await control.control_device(ctx, {"target": "living room thermostat",
                                           "action": "set_temperature", "value": "72"})
    check("P3 control climate set_temperature",
          called("climate", "set_temperature", "climate.living_room_living_room"))

    r = await control.query_device(ctx, {"target": "office light"})
    check("P3 query_device returns state", r.executed is True and "state" in r.data)

    # sensitive via control_device must gate
    r = await control.control_device(ctx, {"target": "front door lock", "action": "unlock"})
    check("P3 control unlock gated", r.requires_confirmation is True and r.executed is False)

    # camera status query
    r = await intent_router.handle_command("atlas", "shawn", "what cameras are online")
    check("P3 camera status -> security_check", r.intent == "security_check", r.intent)

    # ------------------------------------------------------- PART 2: discovery
    res = await scanner.scan()
    summ = res["summary"]
    new_ids = summ["new_entities"]["entities"]
    check("P2 discovery finds new light.new_lamp", "light.new_lamp" in new_ids,
          str(new_ids))
    # classification of the new lamp
    lamp = next((e for e in res["entities"] if e["entity_id"] == "light.new_lamp"), None)
    check("P2 new lamp suggested_category light",
          lamp and lamp["suggested_category"] == "light")
    fan_new = next((e for e in res["entities"] if e["entity_id"] == "fan.den_fan"), None)
    check("P2 den fan classified as fan", fan_new and fan_new["likely_device_type"] == "fan")
    check("P2 den fan unavailable but not ignored",
          fan_new and fan_new["is_available"] is False and fan_new["status"] != "ignored")
    lock_c = next((e for e in res["entities"] if e["entity_id"] == "lock.front_door"), None)
    check("P2 lock unlock is critical-risk",
          lock_c and lock_c["risk_level"] == "high")

    # approve writes overlay + reload exposes it
    from app.discovery import registry
    registry.approve("light.new_lamp", mapping="device_aliases", room="office",
                     friendly_name="Office Lamp", aliases=["office lamp"])
    from app.config_loader import reload_config
    cfg = reload_config()
    check("P2 approve writes config",
          any(a.entity_id == "light.new_lamp" for a in cfg.devices.device_aliases))

    # ignore writes avoid
    registry.ignore("media_player.office_tv", reason="duplicate")
    cfg = reload_config()
    check("P2 ignore writes avoid", "media_player.office_tv" in cfg.devices.avoid)

    # ---------------------------------------------------------- PART 8: music
    # devices.yaml music accounts have no default_media -> no false playback.
    SERVICE_CALLS.clear()
    r = await intent_router.handle_command("atlas", "shawn", "Play my music in the office.")
    check("P8 no media_id -> not executed", r.executed is False, str(r.executed))
    check("P8 no media_id message", "no default playable media" in r.message.lower(),
          r.message)
    check("P8 no play_media call", not called("media_player", "play_media"))

    # ------------------------------------------------ PART 10: degraded config
    from app.models.schemas import Display
    ok = True
    try:
        Display(id="d1", name="Kitchen", type="dashboard", dashboard_path="/lovelace/0")
    except Exception:
        ok = False
    check("P10 dashboard display without entity_id loads", ok)
    bad = False
    try:
        Display(id="d2", name="Bad", type="media_player")  # missing entity_id
    except Exception:
        bad = True
    check("P10 media_player display requires entity_id", bad)

    # backend stays up (degraded) on invalid config instead of crashing
    import tempfile
    from pathlib import Path
    from app import config_loader
    tmp = Path(tempfile.mkdtemp())
    (tmp / "devices.yaml").write_text(
        "displays:\n  - id: bad\n    name: Bad\n    type: media_player\n",
        encoding="utf-8")
    cfg_bad = config_loader.load_config(config_dir=tmp)
    check("P10 invalid config -> degraded not crash",
          config_loader.config_error() is not None and cfg_bad is not None)
    # a dashboard display with no entity_id must load fine
    (tmp / "devices.yaml").write_text(
        "displays:\n  - id: ok\n    name: Dash\n    type: dashboard\n"
        "    dashboard_path: /lovelace/0\n", encoding="utf-8")
    cfg_ok = config_loader.load_config(config_dir=tmp)
    check("P10 dashboard display loads without entity_id",
          config_loader.config_error() is None and len(cfg_ok.devices.displays) == 1)

    print("\n--- SUMMARY ---")
    passed = sum(1 for s, _, _ in results if s == PASS)
    print(f"{passed}/{len(results)} checks passed.")
    for s, n, d in results:
        if s == FAIL:
            print(f"  FAILED: {n} ({d})")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
