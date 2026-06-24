"""Music actions with strict per-user music-account ownership.

Atlas (Shawn) may only use Shawn's Spotify provider; Chatty (Jordie) may only
use Jordie's. We resolve assistant -> owner -> music account, then resolve the
room -> speaker, and prefer Music Assistant playback so Spotify/library search
works instead of sending raw text to a generic media_player.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from ..homeassistant.rest import HAError
from ..models.results import ActionResult
from . import ActionContext


def _effective_user(ctx: ActionContext, requested_user: Optional[str]):
    """Determine whose music account to use.

    Privacy rule: the music account is bound to the ASSISTANT's owner. Atlas
    (owned by Shawn) can never use Jordie's account, and vice versa, regardless
    of what `user` the request claims. We resolve the owner from the active
    assistant and only honor a requested user if it matches that owner.
    """
    # The assistant's owner is the authoritative music-account owner.
    owner = None
    if ctx.assistant is not None:
        owner = ctx.resolver.get_user(ctx.assistant.owner)
    if owner is None:
        owner = ctx.user  # fall back to the request user if no assistant owner

    if not requested_user:
        return owner, None
    res = ctx.resolver.resolve_user(requested_user)
    req = ctx.resolver.get_user(res.id) if res.matched else None
    if owner and req and req.id != owner.id:
        # Privacy guard: refuse to use a different user's account.
        return owner, (
            f"Requested user '{req.name}' differs from this assistant's owner "
            f"'{owner.name}'. Using {owner.name}'s music account."
        )
    return (req or owner), None


async def play_music(ctx: ActionContext, params: dict[str, Any]) -> ActionResult:
    intent = "play_music"
    room = (params.get("room") or "").strip()
    query = _clean_media_query(params.get("query") or params.get("media") or "")
    if not room:
        return ActionResult.fail(intent, "Where should I play music? (e.g. office, everywhere)")

    user, privacy_note = _effective_user(ctx, params.get("user"))
    if not user:
        return ActionResult.fail(intent, "I couldn't determine whose music to play.")

    if not ctx.permissions.user_allows(user.id, "can_control_music"):
        return ActionResult.fail(intent, f"{user.name} is not allowed to control music.")

    acct = ctx.resolver.resolve_music_account(user.id)
    if not acct.matched:
        return ActionResult.fail(intent, acct.reason)

    spk = ctx.resolver.resolve_speaker(room)
    if not spk.matched:
        return ActionResult.fail(intent, f"I couldn't find a speaker for '{room}'. {spk.reason}")

    # Determine a real media_id (PART 8). Order: explicit query > the user's
    # configured default_media. We never guess "Liked Songs".
    default_media = None
    acct_cfg = ctx.config.devices.music_accounts.get(acct.id)
    if acct_cfg and acct_cfg.default_media:
        default_media = acct_cfg.default_media
    media_id: Optional[str] = query or (default_media.media_id if default_media else None)
    media_type = _media_type(params, query) if query else (
        default_media.media_type if default_media else "music")
    ma_entity_id = str(spk.data.get("music_assistant_entity_id") or "").strip() or spk.entity_id

    resolved = {
        "user": user.id,
        "music_account": acct.id,
        "provider": acct.data.get("provider"),
        "account": acct.data.get("account"),
        "room": room,
        "speaker": spk.entity_id,
        "music_assistant_player": ma_entity_id,
        "query": query or None,
        "media_id": media_id,
        "media_type": media_type,
        "confidence": min(acct.confidence, spk.confidence),
        "reason": f"{acct.reason} {spk.reason}",
    }
    if privacy_note:
        resolved["privacy_note"] = privacy_note

    # No playable media -> resolve only, do NOT claim playback (PART 8).
    if not media_id:
        msg = ("Music account and speaker resolved, but no default playable "
               "media is configured. Set a default media_id for "
               f"{user.name}, or ask me to play something specific.")
        if privacy_note:
            msg = f"{privacy_note} {msg}"
        return ActionResult(success=True, intent=intent, executed=False,
                            message=msg, resolved=resolved,
                            data={"needs_media_id": True})

    ma_call = {
        "domain": "music_assistant",
        "service": "play_media",
        "data": {
            "entity_id": ma_entity_id,
            "media_id": media_id,
            "media_type": media_type,
            "enqueue": params.get("enqueue") or "replace",
        },
    }
    if params.get("radio_mode"):
        ma_call["data"]["radio_mode"] = True
    data: dict[str, Any] = {
        "music_assistant": ma_call,
        "service_call": ma_call,
        "playback_backend": "music_assistant",
    }

    try:
        await ctx.ha.music_assistant_play_media(
            ma_entity_id,
            media_id=media_id,
            media_type=media_type,
            enqueue=str(params.get("enqueue") or "replace"),
            radio_mode=bool(params.get("radio_mode")),
        )
    except HAError as exc:
        if exc.status == 404:
            fallback_call = {
                "domain": "media_player",
                "service": "play_media",
                "data": {
                    "entity_id": spk.entity_id,
                    "media_content_id": media_id,
                    "media_content_type": media_type,
                },
            }
            try:
                await ctx.ha.play_media(
                    spk.entity_id,
                    media_content_id=media_id,
                    media_content_type=media_type,
                )
                data.update({
                    "service_call": fallback_call,
                    "media_player": fallback_call,
                    "playback_backend": "media_player_fallback",
                    "fallback_reason": exc.message,
                })
            except HAError as fallback_exc:
                msg = (f"Resolved {acct.name} -> {spk.name}, but Music Assistant "
                       f"and media_player playback both failed: {fallback_exc.message}")
                if privacy_note:
                    msg = f"{privacy_note} {msg}"
                return ActionResult(success=False, intent=intent, executed=False,
                                    message=msg, resolved=resolved,
                                    data=data, error="ha_call_failed")
        else:
            # Be honest: the call failed, so we did NOT start playback.
            msg = (f"Resolved {acct.name} -> {spk.name}, but Music Assistant playback failed: "
                   f"{exc.message}")
            if privacy_note:
                msg = f"{privacy_note} {msg}"
            return ActionResult(success=False, intent=intent, executed=False,
                                message=msg, resolved=resolved,
                                data=data, error="ha_call_failed")

    what = f'"{query}"' if query else f'"{media_id}"'
    backend = "Music Assistant"
    if data.get("playback_backend") == "media_player_fallback":
        backend = "Home Assistant media player fallback"
    message = (
        f"Playing {what} on {spk.name} using {acct.name} for {user.name} "
        f"via {backend}."
    )
    if privacy_note:
        message = f"{privacy_note} {message}"
    return ActionResult(success=True, intent=intent, executed=True,
                        message=message, resolved=resolved,
                        data=data)


def _clean_media_query(value: Any) -> str:
    text = str(value or "").strip().strip("\"'")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"^(?:some|my)\s+music\s*$", "", text, flags=re.I)
    text = re.sub(r"\s+(?:playlist|song|track|album|artist)$", "", text, flags=re.I)
    return text.strip()


def _media_type(params: dict[str, Any], query: str) -> str:
    explicit = str(params.get("media_type") or "").strip().lower()
    allowed = {"music", "track", "album", "artist", "playlist", "radio"}
    if explicit in allowed:
        return explicit
    hint = " ".join(str(params.get(k) or "") for k in ("query", "media", "target", "raw"))
    text = f"{hint} {query}".lower()
    if "playlist" in text:
        return "playlist"
    if "album" in text:
        return "album"
    if "artist" in text:
        return "artist"
    if "radio" in text or "station" in text:
        return "radio"
    if "song" in text or "track" in text:
        return "track"
    return "music"


async def stop_music(ctx: ActionContext, params: dict[str, Any]) -> ActionResult:
    intent = "stop_music"
    room = (params.get("room") or "").strip()
    if not room:
        return ActionResult.fail(intent, "Which room should I stop the music in?")
    spk = ctx.resolver.resolve_speaker(room)
    if not spk.matched:
        return ActionResult.fail(intent, f"I couldn't find a speaker for '{room}'. {spk.reason}")
    resolved = {"room": room, "speaker": spk.entity_id, "reason": spk.reason,
                "confidence": spk.confidence}
    try:
        await ctx.ha.media_stop(spk.entity_id)
        return ActionResult(success=True, intent=intent, executed=True,
                            message=f"Stopped music on {spk.name}.", resolved=resolved)
    except HAError as exc:
        return ActionResult.fail(intent, f"Couldn't stop {spk.name}: {exc.message}",
                                 resolved=resolved)


async def set_volume(ctx: ActionContext, params: dict[str, Any]) -> ActionResult:
    intent = "set_volume"
    room = (params.get("room") or "").strip()
    level_raw = params.get("level")
    if not room or level_raw is None:
        return ActionResult.fail(intent, "I need a room and a volume level.")
    spk = ctx.resolver.resolve_speaker(room)
    if not spk.matched:
        return ActionResult.fail(intent, f"I couldn't find a speaker for '{room}'. {spk.reason}")
    level = float(level_raw)
    level = level / 100.0 if level > 1 else level
    level = max(0.0, min(1.0, level))
    resolved = {"room": room, "speaker": spk.entity_id, "level": level,
                "reason": spk.reason}
    try:
        await ctx.ha.set_volume(spk.entity_id, level)
        return ActionResult(success=True, intent=intent, executed=True,
                            message=f"Set {spk.name} volume to {int(level * 100)}%.",
                            resolved=resolved)
    except HAError as exc:
        return ActionResult.fail(intent, f"Couldn't set volume on {spk.name}: {exc.message}",
                                 resolved=resolved)
