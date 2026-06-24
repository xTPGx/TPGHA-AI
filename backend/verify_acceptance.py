"""Offline acceptance check for the orchestrator's routing/resolution.

Runs without OpenAI (uses the deterministic fallback parser) and without a live
Home Assistant (live states are empty, so resolution uses config only).
Execution of HA service calls is monkeypatched to a no-op so we can assert the
resolved entities and confirmation gating.
"""
import asyncio
import os
import sys
import tempfile

os.environ.setdefault("CONFIG_DIR", os.path.join(os.path.dirname(__file__), "..", "config"))
os.environ["DATABASE_URL"] = "sqlite:///./verify_tmp.db"
os.environ["HA_CONFIG_DIR"] = tempfile.mkdtemp(prefix="tpg_ha_cfg_")
# Ensure no OpenAI usage.
os.environ.pop("OPENAI_API_KEY", None)

sys.path.insert(0, os.path.dirname(__file__))

from app.db.database import init_db  # noqa: E402
from app.ai.client import ToolCall  # noqa: E402
from app.homeassistant import rest  # noqa: E402
from app.models.schemas import HAEntity  # noqa: E402
from app.router import intent_router  # noqa: E402
from app.router.permissions import get_confirmation_store  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, condition, detail=""):
    status = PASS if condition else FAIL
    results.append((status, name, detail))
    print(f"[{status}] {name}" + (f" -- {detail}" if detail else ""))


async def noop(*args, **kwargs):
    return {"ok": True}


SERVICE_CALLS: list[tuple[str, str, dict]] = []


async def fake_safe_get_states():
    return {
        "light.office": HAEntity(entity_id="light.office", state="off",
                                 friendly_name="Office Light", domain="light",
                                 available=True),
        "fan.office": HAEntity(entity_id="fan.office", state="on",
                               friendly_name="Office Fan", domain="fan",
                               available=True),
        "fan.living_room": HAEntity(entity_id="fan.living_room", state="off",
                                    friendly_name="Living Room Fan", domain="fan",
                                    available=True),
        "fan.bedroom_fan": HAEntity(entity_id="fan.bedroom_fan", state="off",
                                    friendly_name="Bedroom Fan", domain="fan",
                                    available=True),
        "climate.living_room_living_room": HAEntity(
            entity_id="climate.living_room_living_room", state="cool",
            friendly_name="Living Room Thermostat", domain="climate", available=True,
        ),
        "lock.front_door": HAEntity(entity_id="lock.front_door", state="locked",
                                    friendly_name="Front Door", domain="lock",
                                    available=True),
    }


async def main():
    init_db()
    intent_router.safe_get_states = fake_safe_get_states

    # Record every service call so we can assert exact domain/service/data.
    # turn_on/turn_off/lock/unlock/set_volume/etc. all funnel through
    # call_service in the REST client, so recording it captures everything.
    async def rec_call_service(self, domain, service, data=None, *, return_response=False):
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

    SERVICE_CALLS.clear()
    r = await intent_router.handle_command(
        "atlas", "shawn", "Play This Is Mitchell Tenpenny playlist on office speaker."
    )
    check("Q4b playlist -> play_music", r.intent == "play_music", r.intent)
    check("Q4b query extracted", r.resolved.get("query") == "This Is Mitchell Tenpenny",
          r.resolved.get("query"))
    check("Q4b media_type playlist", r.resolved.get("media_type") == "playlist",
          r.resolved.get("media_type"))
    check("Q4b calls Music Assistant play_media",
          called("music_assistant", "play_media", "media_player.office_speaker"),
          SERVICE_CALLS)

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

    SERVICE_CALLS.clear()
    r = await intent_router.handle_command("atlas", "shawn", "turn on office tv")
    check("Q9b office TV power on executes", r.success is True and r.executed is True,
          f"{r.intent}/{r.message}")
    check("Q9b calls media_player.turn_on",
          called("media_player", "turn_on", "media_player.office_office_monitor_1_2"),
          str(SERVICE_CALLS))

    # 10. Scheduling -> automation draft
    r = await intent_router.handle_command("atlas", "shawn", "At 7 AM turn on the kitchen lights.")
    check("Q10 automation draft", r.intent == "create_simple_automation", r.intent)
    check("Q10 not executed", r.executed is False)

    r = await intent_router.handle_command("atlas", "shawn", "Set a sleep timer on the office TV in 30 minutes.")
    check("Q11 sleep timer draft", r.intent == "create_simple_automation", r.intent)
    check("Q11 sleep timer not executed", r.executed is False)
    check("Q11 sleep timer has delay", "00:30:00" in r.data.get("proposed_yaml", ""),
          r.data.get("proposed_yaml", ""))
    check("Q11 sleep timer resolves office TV",
          "media_player.office_office_monitor_1_2" in r.data.get("proposed_yaml", ""),
          r.data.get("proposed_yaml", ""))

    r = await intent_router.handle_command("atlas", "shawn", "Dim the living room brightness to 20 at 10 PM.")
    check("Q12 dim schedule draft", r.intent == "create_simple_automation", r.intent)
    check("Q12 dim schedule not executed", r.executed is False)
    check("Q12 dim includes brightness", "brightness_pct" in r.data.get("proposed_yaml", ""),
          r.data.get("proposed_yaml", ""))
    check("Q12 dim parses 10 PM", "at: '22:00:00'" in r.data.get("proposed_yaml", ""),
          r.data.get("proposed_yaml", ""))

    r = await intent_router.handle_command("atlas", "shawn", "Make a movie mode for the living room.")
    check("Q13 movie mode -> create_routine", r.intent == "create_routine", r.intent)
    check("Q13 routine draft created", bool(r.data.get("draft_id")), str(r.data))
    check("Q13 routine has light dim action", "brightness_pct" in r.data.get("proposed_yaml", ""),
          r.data.get("proposed_yaml", ""))

    # 11. Fan control --------------------------------------------------------
    SERVICE_CALLS.clear()
    r = await intent_router.handle_command("atlas", "shawn", "Turn on office light.",
                                           conversation_id="ctx-light")
    check("L1 turn on office light -> turn_on_light", r.intent == "turn_on_light", r.intent)
    check("L1 calls light.turn_on light.office", called("light", "turn_on", "light.office"),
          str(SERVICE_CALLS))
    check("L1 does not call light.turn_off", not called("light", "turn_off", "light.office"),
          str(SERVICE_CALLS))

    r = await intent_router.handle_command("atlas", "shawn", "why did you do that?",
                                           conversation_id="ctx-light")
    check("L1a explain last action -> explain_last_action",
          r.intent == "explain_last_action", r.intent)
    check("L1a explanation references previous light command",
          "turn_on_light" in r.message and "office" in r.message.lower(),
          r.message)
    check("L1a explanation includes audit payload",
          r.data.get("command", {}).get("intent") == "turn_on_light",
          str(r.data))

    SERVICE_CALLS.clear()
    r = await intent_router.handle_command("atlas", "shawn", "turn it off",
                                           conversation_id="ctx-light")
    check("L1b pronoun follow-up -> turn_off_light", r.intent == "turn_off_light", r.intent)
    check("L1b pronoun calls light.turn_off light.office",
          called("light", "turn_off", "light.office"), str(SERVICE_CALLS))

    SERVICE_CALLS.clear()
    r = await intent_router.handle_command("atlas", "shawn", "Turn off office light.",
                                           conversation_id="ctx-correct")
    check("L1c seed correction context", r.intent == "turn_off_light", r.intent)
    SERVICE_CALLS.clear()
    r = await intent_router.handle_command("atlas", "shawn", "actually the fan",
                                           conversation_id="ctx-correct")
    check("L1d correction reuses action -> turn_off_fan", r.intent == "turn_off_fan", r.intent)
    check("L1d correction targets office fan", called("fan", "turn_off", "fan.office"),
          str(SERVICE_CALLS))

    SERVICE_CALLS.clear()
    r = await intent_router.handle_command("atlas", "shawn", "Turn on office light.",
                                           conversation_id="ctx-dim")
    check("L1e seed dim context", r.intent == "turn_on_light", r.intent)
    SERVICE_CALLS.clear()
    r = await intent_router.handle_command("atlas", "shawn", "dim it to 40",
                                           conversation_id="ctx-dim")
    check("L1f pronoun dim uses generic control", r.intent == "control_device", r.intent)
    check("L1f pronoun dim calls light.turn_on with brightness",
          any(d == "light" and s == "turn_on" and data.get("brightness_pct") == 40
              for d, s, data in SERVICE_CALLS),
          str(SERVICE_CALLS))

    bad_tool = ToolCall("turn_off_light", {"target": "office light"}, source="test")
    fixed_tool = intent_router._repair_direction_conflict("Turn on office light.", bad_tool)
    check("L2 direction guard fixes bad off tool",
          fixed_tool.name == "turn_on_light" and fixed_tool.arguments.get("target") == "office light",
          fixed_tool.to_dict())

    bad_generic = ToolCall("control_device", {"target": "office light", "action": "turn_off"}, source="test")
    fixed_generic = intent_router._repair_direction_conflict("Switch on office light.", bad_generic)
    check("L3 direction guard fixes generic off action",
          fixed_generic.name == "control_device" and fixed_generic.arguments.get("action") == "turn_on",
          fixed_generic.to_dict())

    SERVICE_CALLS.clear()
    r = await intent_router.handle_preview("atlas", "shawn", "turn off office fan")
    check("P0 preview fan -> turn_off_fan", r.intent == "turn_off_fan", r.intent)
    check("P0 preview does not execute", r.executed is False, str(r.data))
    check("P0 preview records fan.turn_off",
          r.data.get("preview", {}).get("service_calls", [{}])[0].get("service") == "turn_off",
          str(r.data))
    check("P0 preview does not call real HA", SERVICE_CALLS == [], str(SERVICE_CALLS))

    before_conf = len(get_confirmation_store().list_pending())
    r = await intent_router.handle_preview("atlas", "shawn", "unlock the front door")
    after_conf = len(get_confirmation_store().list_pending())
    check("P0b preview unlock requires confirmation", r.requires_confirmation is True)
    check("P0b preview unlock has no live token", r.confirmation_token is None)
    check("P0b preview unlock does not arm confirmation", before_conf == after_conf,
          f"{before_conf}->{after_conf}")

    SERVICE_CALLS.clear()
    r = await intent_router.handle_command("atlas", "shawn", "turn off office fan")
    check("F1 turn off office fan -> turn_off_fan", r.intent == "turn_off_fan", r.intent)
    check("F1 resolves fan.office", r.resolved.get("entity_id") == "fan.office",
          r.resolved.get("entity_id"))
    check("F1 executed", r.executed is True)
    check("F1 calls fan.turn_off fan.office", called("fan", "turn_off", "fan.office"))
    check("F1 message", r.message == "Turned off Office Fan.", r.message)

    SERVICE_CALLS.clear()
    r = await intent_router.handle_command("atlas", "shawn", "turn up fan speed")
    check("F1b relative speed follow-up -> set_fan_percentage",
          r.intent == "set_fan_percentage", r.intent)
    check("F1b relative speed uses office fan",
          r.resolved.get("entity_id") == "fan.office", r.resolved)
    check("F1b relative speed calls set_percentage",
          called("fan", "set_percentage", "fan.office"), str(SERVICE_CALLS))

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

    SERVICE_CALLS.clear()
    r = await intent_router.handle_command("atlas", "shawn", "set office fan speed to high")
    check("F5 fan speed high -> set_fan_percentage",
          r.intent == "set_fan_percentage", r.intent)
    check("F5 percentage 75", r.resolved.get("percentage") == 75, r.resolved.get("percentage"))
    check("F5 calls fan.set_percentage fan.office", called("fan", "set_percentage", "fan.office"))

    SERVICE_CALLS.clear()
    r = await intent_router.handle_command("atlas", "shawn", "set office fan level to 3")
    check("F6 fan level 3 -> 60%", r.resolved.get("percentage") == 60,
          r.resolved.get("percentage"))

    async def fake_get_entity_tuya(self, entity_id):
        return {
            "entity_id": entity_id,
            "state": "on",
            "attributes": {"supported_features": 0, "preset_modes": ["low", "medium", "high"]},
        }
    rest.HomeAssistantREST.get_entity = fake_get_entity_tuya
    SERVICE_CALLS.clear()
    r = await intent_router.handle_command("atlas", "shawn", "set office fan speed to 10")
    check("F7 Tuya preset fallback succeeds", r.success is True and r.executed is True,
          r.message)
    check("F7 Tuya preset fallback calls set_preset_mode",
          called("fan", "set_preset_mode", "fan.office"), str(SERVICE_CALLS))

    print("\n--- SUMMARY ---")
    failed = [r for r in results if r[0] == FAIL]
    print(f"{len(results) - len(failed)}/{len(results)} checks passed.")
    if failed:
        for _s, n, d in failed:
            print(f"  FAILED: {n} ({d})")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
