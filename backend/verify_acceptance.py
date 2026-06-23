"""Offline acceptance check for the orchestrator's routing/resolution.

Runs without OpenAI (uses the deterministic fallback parser) and without a live
Home Assistant (live states are empty, so resolution uses config only).
Execution of HA service calls is monkeypatched to a no-op so we can assert the
resolved entities and confirmation gating.
"""
import asyncio
import os
import sys

os.environ.setdefault("CONFIG_DIR", os.path.join(os.path.dirname(__file__), "..", "config"))
os.environ["DATABASE_URL"] = "sqlite:///./verify_tmp.db"
# Ensure no OpenAI usage.
os.environ.pop("OPENAI_API_KEY", None)

sys.path.insert(0, os.path.dirname(__file__))

from app.db.database import init_db  # noqa: E402
from app.homeassistant import rest  # noqa: E402
from app.router import intent_router  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, condition, detail=""):
    status = PASS if condition else FAIL
    results.append((status, name, detail))
    print(f"[{status}] {name}" + (f" -- {detail}" if detail else ""))


async def noop(*args, **kwargs):
    return {"ok": True}


SERVICE_CALLS: list[tuple[str, str, dict]] = []


async def main():
    init_db()

    # Record every service call so we can assert exact domain/service/data.
    # turn_on/turn_off/lock/unlock/set_volume/etc. all funnel through
    # call_service in the REST client, so recording it captures everything.
    async def rec_call_service(self, domain, service, data=None):
        SERVICE_CALLS.append((domain, service, data or {}))
        return {"ok": True}
    rest.HomeAssistantREST.call_service = rec_call_service

    async def fake_get_entity(self, entity_id):
        attrs = {"supported_features": 1} if entity_id.startswith("fan.") else {}
        return {"entity_id": entity_id, "state": "idle", "attributes": attrs}
    rest.HomeAssistantREST.get_entity = fake_get_entity

    def called(domain, service, entity_id):
        return any(
            d == domain and s == service and data.get("entity_id") == entity_id
            for d, s, data in SERVICE_CALLS
        )

    # 1. "Is the front door locked?" -> security_check (reads lock.front_door)
    r = await intent_router.handle_command("atlas", "shawn", "Is the front door locked?")
    check("Q1 front door locked -> security_check", r.intent == "security_check", r.intent)
    check("Q1 includes lock.front_door",
          any(l.get("entity_id") == "lock.front_door" for l in r.data.get("locks", [])))

    # 2. "Show me the driveway." -> camera.front_yard_front_yard
    r = await intent_router.handle_command("atlas", "shawn", "Show me the driveway.")
    check("Q2 driveway -> show_camera", r.intent == "show_camera", r.intent)
    check("Q2 resolves front_yard cam",
          r.resolved.get("entity_id") == "camera.front_yard_front_yard",
          r.resolved.get("entity_id"))

    # 3. "Show me the front door." -> camera.front_door_front_door_doorbell
    r = await intent_router.handle_command("atlas", "shawn", "Show me the front door.")
    check("Q3 front door -> show_camera", r.intent == "show_camera", r.intent)
    check("Q3 resolves doorbell cam",
          r.resolved.get("entity_id") == "camera.front_door_front_door_doorbell",
          r.resolved.get("entity_id"))

    # 4. Atlas "Play my music in the office." -> shawn / spotify_xtpgx / office speaker
    r = await intent_router.handle_command("atlas", "shawn", "Play my music in the office.")
    check("Q4 play_music", r.intent == "play_music", r.intent)
    check("Q4 user shawn", r.resolved.get("user") == "shawn", r.resolved.get("user"))
    check("Q4 provider spotify_xtpgx", r.resolved.get("music_account") == "spotify_xtpgx",
          r.resolved.get("music_account"))
    check("Q4 office speaker", r.resolved.get("speaker") == "media_player.office_speaker",
          r.resolved.get("speaker"))

    # 5. Chatty "Play my music in the kitchen." -> jordie / spotify_jordierae22 / kitchen display
    r = await intent_router.handle_command("chatty", "jordie", "Play my music in the kitchen.")
    check("Q5 user jordie", r.resolved.get("user") == "jordie", r.resolved.get("user"))
    check("Q5 provider spotify_jordierae22",
          r.resolved.get("music_account") == "spotify_jordierae22", r.resolved.get("music_account"))
    check("Q5 kitchen display", r.resolved.get("speaker") == "media_player.kitchen_display",
          r.resolved.get("speaker"))

    # 5b. Privacy guard: Atlas trying to use jordie should fall back to shawn.
    r = await intent_router.handle_command("atlas", "jordie", "Play my music in the office.")
    check("Q5b privacy guard keeps shawn", r.resolved.get("user") == "shawn",
          r.resolved.get("user"))
    check("Q5b uses shawn provider", r.resolved.get("music_account") == "spotify_xtpgx",
          r.resolved.get("music_account"))

    # 6. "Unlock the front door." -> requires confirmation, not executed
    r = await intent_router.handle_command("atlas", "shawn", "Unlock the front door.")
    check("Q6 unlock requires confirmation", r.requires_confirmation is True)
    check("Q6 not executed", r.executed is False)
    check("Q6 has token", bool(r.confirmation_token))
    # Confirm now executes.
    if r.confirmation_token:
        r2 = await intent_router.handle_confirmation(r.confirmation_token)
        check("Q6 confirm executes unlock", r2.executed is True and r2.intent == "unlock_door",
              f"{r2.intent}/{r2.executed}")

    # 7. "Set the thermostat to cool 75." -> set_climate. A thermostat is now
    #    mapped (climate.living_room_living_room) so it executes against it.
    r = await intent_router.handle_command("atlas", "shawn", "Set the thermostat to cool 75.")
    check("Q7 set_climate tool", r.intent == "set_climate", r.intent)
    check("Q7 mode cool & temp 75", r.resolved.get("mode") == "cool" and r.resolved.get("temperature") == 75,
          f"{r.resolved.get('mode')}/{r.resolved.get('temperature')}")
    check("Q7 resolves living room thermostat",
          r.resolved.get("entity_id") == "climate.living_room_living_room",
          r.resolved.get("entity_id"))
    check("Q7 calls climate.set_temperature",
          called("climate", "set_temperature", "climate.living_room_living_room"))

    # 8. Lock the front door -> executes immediately
    r = await intent_router.handle_command("atlas", "shawn", "Lock the front door.")
    check("Q8 lock_door executes", r.intent == "lock_door" and r.executed is True,
          f"{r.intent}/{r.executed}")

    # 9. "Play music everywhere"
    r = await intent_router.handle_command("atlas", "shawn", "Play music everywhere.")
    check("Q9 everywhere speaker", r.resolved.get("speaker") == "media_player.everywhere",
          r.resolved.get("speaker"))

    # 10. Scheduling -> automation draft
    r = await intent_router.handle_command("atlas", "shawn", "At 7 AM turn on the kitchen lights.")
    check("Q10 automation draft", r.intent == "create_simple_automation", r.intent)
    check("Q10 not executed", r.executed is False)

    # 11. Fan control --------------------------------------------------------
    SERVICE_CALLS.clear()
    r = await intent_router.handle_command("atlas", "shawn", "turn off office fan")
    check("F1 turn off office fan -> turn_off_fan", r.intent == "turn_off_fan", r.intent)
    check("F1 resolves fan.office", r.resolved.get("entity_id") == "fan.office",
          r.resolved.get("entity_id"))
    check("F1 executed", r.executed is True)
    check("F1 calls fan.turn_off fan.office", called("fan", "turn_off", "fan.office"))
    check("F1 message", r.message == "Turned off Office Fan.", r.message)

    r = await intent_router.handle_command("atlas", "shawn", "turn on living room fan")
    check("F2 turn on living room fan -> turn_on_fan", r.intent == "turn_on_fan", r.intent)
    check("F2 resolves fan.living_room", r.resolved.get("entity_id") == "fan.living_room",
          r.resolved.get("entity_id"))
    check("F2 calls fan.turn_on fan.living_room", called("fan", "turn_on", "fan.living_room"))

    r = await intent_router.handle_command("atlas", "shawn", "turn off bedroom fan")
    check("F3 turn off bedroom fan -> turn_off_fan", r.intent == "turn_off_fan", r.intent)
    check("F3 resolves fan.bedroom_fan", r.resolved.get("entity_id") == "fan.bedroom_fan",
          r.resolved.get("entity_id"))
    check("F3 calls fan.turn_off fan.bedroom_fan", called("fan", "turn_off", "fan.bedroom_fan"))

    SERVICE_CALLS.clear()
    r = await intent_router.handle_command("atlas", "shawn", "set office fan to 50%")
    check("F4 set office fan to 50% -> set_fan_percentage",
          r.intent == "set_fan_percentage", r.intent)
    check("F4 resolves fan.office", r.resolved.get("entity_id") == "fan.office",
          r.resolved.get("entity_id"))
    check("F4 percentage 50", r.resolved.get("percentage") == 50, r.resolved.get("percentage"))
    check("F4 calls fan.set_percentage fan.office", called("fan", "set_percentage", "fan.office"))
    check("F4 percentage value in call",
          any(d == "fan" and s == "set_percentage" and data.get("percentage") == 50
              for d, s, data in SERVICE_CALLS))

    print("\n--- SUMMARY ---")
    failed = [r for r in results if r[0] == FAIL]
    print(f"{len(results) - len(failed)}/{len(results)} checks passed.")
    if failed:
        for _s, n, d in failed:
            print(f"  FAILED: {n} ({d})")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
