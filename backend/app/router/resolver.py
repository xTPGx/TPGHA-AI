"""Intelligent resolver: friendly names -> concrete config entities.

Rules (in order):
  1. Case-insensitive exact alias / name / id match.
  2. Fuzzy match (token overlap + difflib ratio).
  3. Prefer entities that are currently AVAILABLE in Home Assistant over
     unavailable duplicates (see devices.yaml `avoid`).
Each resolution returns a confidence score and a human-readable reason.
"""
from __future__ import annotations

import difflib
from typing import Any, Iterable, Optional

from ..models.results import ResolveResult
from ..models.schemas import (
    AppConfig,
    Assistant,
    Camera,
    Display,
    Lock,
    Room,
    Speaker,
    User,
)
from ..models.schemas import HAEntity


def _norm(text: str) -> str:
    return " ".join(str(text).strip().lower().split())


def _fuzzy_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _token_overlap(query: str, candidate: str) -> float:
    qs = set(_norm(query).split())
    cs = set(_norm(candidate).split())
    if not qs or not cs:
        return 0.0
    return len(qs & cs) / len(qs)


def _best_alias_score(query: str, names: Iterable[str]) -> tuple[float, str]:
    """Return (score, matched_name) using exact, substring, then fuzzy."""
    q = _norm(query)
    best = (0.0, "")
    for name in names:
        if not name:
            continue
        n = _norm(name)
        if q == n:
            return (1.0, name)
        score = 0.0
        if q in n or n in q:
            # Substring match scaled by how much of the query it covers.
            score = max(score, 0.85 + 0.1 * _token_overlap(query, name))
        score = max(score, 0.6 * _token_overlap(query, name))
        score = max(score, 0.7 * _fuzzy_ratio(query, name))
        if score > best[0]:
            best = (min(score, 0.99), name)
    return best


class Resolver:
    def __init__(self, config: AppConfig, live_states: Optional[dict[str, HAEntity]] = None):
        self.config = config
        self.live_states = live_states or {}
        self.avoid = set(config.devices.avoid)

    # ------------------------------------------------------------- helpers
    def _is_available(self, entity_id: Optional[str]) -> bool:
        if not entity_id:
            return False
        if entity_id in self.avoid:
            return False
        if not self.live_states:
            # No live data -> assume available unless explicitly avoided.
            return True
        ent = self.live_states.get(entity_id)
        if ent is None:
            return False
        return ent.available

    def resolve_best_entity(
        self, possible_entities: list[str], live_states: Optional[dict[str, HAEntity]] = None
    ) -> ResolveResult:
        """Pick the best entity from candidates, preferring available ones."""
        states = live_states or self.live_states
        if not possible_entities:
            return ResolveResult.miss("entity", "No candidate entities provided.")

        ranked: list[tuple[int, str]] = []
        for eid in possible_entities:
            score = 0
            if eid in self.avoid:
                score -= 100
            ent = states.get(eid) if states else None
            if ent is not None:
                score += 10 if ent.available else -10
            else:
                score += 1  # unknown but not avoided
            ranked.append((score, eid))
        ranked.sort(key=lambda x: x[0], reverse=True)
        best_score, best = ranked[0]
        if best_score < 0:
            return ResolveResult(
                matched=True,
                kind="entity",
                entity_id=best,
                confidence=0.3,
                reason="All candidates appear unavailable; returned the least-bad option.",
            )
        avail = "available" if self._is_available(best) else "status unknown"
        return ResolveResult(
            matched=True,
            kind="entity",
            entity_id=best,
            confidence=0.9,
            reason=f"Selected {best} ({avail}) over {len(possible_entities) - 1} other candidate(s).",
        )

    # ----------------------------------------------------------- assistant
    def resolve_assistant(self, name: str) -> ResolveResult:
        items = self.config.assistants.assistants
        return self._resolve_named(name, items, kind="assistant")

    def resolve_user(self, name: str) -> ResolveResult:
        items = self.config.assistants.users
        return self._resolve_named(name, items, kind="user")

    def _resolve_named(self, name: str, items: list, kind: str) -> ResolveResult:
        if not name:
            return ResolveResult.miss(kind, f"No {kind} name given.")
        q = _norm(name)
        # Exact by id / name / alias.
        for it in items:
            candidates = [it.id, it.name, *getattr(it, "aliases", [])]
            if q in {_norm(c) for c in candidates}:
                return ResolveResult(
                    matched=True, kind=kind, id=it.id, name=it.name,
                    confidence=1.0, reason=f"Exact match on {kind} '{it.name}'.",
                    data=it.model_dump(),
                )
        # Fuzzy.
        best_item = None
        best_score = 0.0
        best_match = ""
        for it in items:
            names = [it.id, it.name, *getattr(it, "aliases", [])]
            score, matched = _best_alias_score(name, names)
            if score > best_score:
                best_score, best_item, best_match = score, it, matched
        if best_item and best_score >= 0.5:
            return ResolveResult(
                matched=True, kind=kind, id=best_item.id, name=best_item.name,
                confidence=round(best_score, 2),
                reason=f"Fuzzy match on '{best_match}' for {kind} '{best_item.name}'.",
                data=best_item.model_dump(),
            )
        return ResolveResult.miss(kind, f"No {kind} matched '{name}'.")

    def user_for_assistant(self, assistant_name: str) -> Optional[User]:
        res = self.resolve_assistant(assistant_name)
        if not res.matched:
            return None
        owner_id = res.data.get("owner")
        return self.get_user(owner_id) if owner_id else None

    def get_user(self, user_id: Optional[str]) -> Optional[User]:
        for u in self.config.assistants.users:
            if u.id == user_id:
                return u
        return None

    def get_assistant(self, assistant_id: Optional[str]) -> Optional[Assistant]:
        for a in self.config.assistants.assistants:
            if a.id == assistant_id:
                return a
        return None

    # ---------------------------------------------------------------- room
    def resolve_room(self, name: str) -> ResolveResult:
        rooms = self.config.devices.rooms
        if not name:
            return ResolveResult.miss("room", "No room name given.")
        q = _norm(name)
        for r in rooms:
            if q in {_norm(c) for c in [r.id, r.name, *r.aliases]}:
                return self._room_result(r, 1.0, f"Exact match on room '{r.name}'.")
        best_r: Optional[Room] = None
        best_score = 0.0
        best_match = ""
        for r in rooms:
            score, matched = _best_alias_score(name, [r.id, r.name, *r.aliases])
            if score > best_score:
                best_score, best_r, best_match = score, r, matched
        if best_r and best_score >= 0.5:
            return self._room_result(
                best_r, round(best_score, 2),
                f"Fuzzy match on '{best_match}' for room '{best_r.name}'.",
            )
        return ResolveResult.miss("room", f"No room matched '{name}'.")

    def _room_result(self, room: Room, confidence: float, reason: str) -> ResolveResult:
        return ResolveResult(
            matched=True, kind="room", id=room.id, name=room.name,
            confidence=confidence, reason=reason, data=room.model_dump(),
        )

    # -------------------------------------------------------------- camera
    def resolve_camera(self, name: str) -> ResolveResult:
        cams = self.config.devices.cameras
        if not name:
            return ResolveResult.miss("camera", "No camera name given.")
        q = _norm(name)
        for c in cams:
            if q in {_norm(x) for x in [c.id, c.name, *c.aliases]}:
                return self._entity_result("camera", c, 1.0,
                                           f"Exact match on camera '{c.name}'.")
        best: Optional[Camera] = None
        best_score = 0.0
        best_match = ""
        for c in cams:
            score, matched = _best_alias_score(name, [c.id, c.name, *c.aliases])
            if score > best_score:
                best_score, best, best_match = score, c, matched
        if best and best_score >= 0.45:
            return self._entity_result(
                "camera", best, round(best_score, 2),
                f"Fuzzy match on '{best_match}' for camera '{best.name}'.",
            )
        # Try via room -> camera.
        room_res = self.resolve_room(name)
        if room_res.matched and room_res.data.get("camera"):
            eid = room_res.data["camera"]
            cam = self._camera_by_entity(eid)
            cname = cam.name if cam else eid
            return ResolveResult(
                matched=True, kind="camera", id=cam.id if cam else None,
                entity_id=eid, name=cname, confidence=round(room_res.confidence * 0.9, 2),
                reason=f"Resolved camera via room '{room_res.name}'.",
                data=(cam.model_dump() if cam else {"entity_id": eid}),
            )
        return ResolveResult.miss("camera", f"No camera matched '{name}'.")

    def _camera_by_entity(self, entity_id: str) -> Optional[Camera]:
        for c in self.config.devices.cameras:
            if c.entity_id == entity_id:
                return c
        return None

    # ---------------------------------------------------------------- lock
    def resolve_lock(self, name: str) -> ResolveResult:
        locks = self.config.devices.locks
        if not name:
            # Single-lock convenience.
            if len(locks) == 1:
                return self._entity_result("lock", locks[0], 0.6,
                                           "Only one lock configured; assumed it.")
            return ResolveResult.miss("lock", "No lock name given.")
        q = _norm(name)
        for lk in locks:
            if q in {_norm(x) for x in [lk.id, lk.name, *lk.aliases]}:
                return self._entity_result("lock", lk, 1.0,
                                           f"Exact match on lock '{lk.name}'.")
        best: Optional[Lock] = None
        best_score = 0.0
        best_match = ""
        for lk in locks:
            score, matched = _best_alias_score(name, [lk.id, lk.name, *lk.aliases])
            if score > best_score:
                best_score, best, best_match = score, lk, matched
        if best and best_score >= 0.45:
            return self._entity_result(
                "lock", best, round(best_score, 2),
                f"Fuzzy match on '{best_match}' for lock '{best.name}'.",
            )
        if len(locks) == 1:
            return self._entity_result("lock", locks[0], 0.55,
                                       "Defaulted to the only configured lock.")
        return ResolveResult.miss("lock", f"No lock matched '{name}'.")

    # ------------------------------------------------------------- speaker
    def resolve_speaker(self, room: str) -> ResolveResult:
        speakers = self.config.devices.speakers
        if not room:
            return ResolveResult.miss("speaker", "No room/speaker name given.")
        q = _norm(room)
        # Direct speaker alias / name / id (handles "everywhere").
        for s in speakers:
            if q in {_norm(x) for x in [s.id, s.name, *s.aliases]}:
                return self._speaker_result(s, 1.0,
                                            f"Exact match on speaker '{s.name}'.")
        # Via room -> speaker entity.
        room_res = self.resolve_room(room)
        if room_res.matched and room_res.data.get("speaker"):
            eid = room_res.data["speaker"]
            sp = self._speaker_by_entity(eid)
            best = self.resolve_best_entity([eid])
            return ResolveResult(
                matched=True, kind="speaker", id=sp.id if sp else None,
                entity_id=eid, name=(sp.name if sp else eid),
                confidence=round(room_res.confidence * 0.95, 2),
                reason=f"Resolved speaker via room '{room_res.name}'. {best.reason}",
                data=(sp.model_dump() if sp else {"entity_id": eid}),
            )
        # Fuzzy on speakers.
        best_s: Optional[Speaker] = None
        best_score = 0.0
        best_match = ""
        for s in speakers:
            score, matched = _best_alias_score(room, [s.id, s.name, *s.aliases])
            if score > best_score:
                best_score, best_s, best_match = score, s, matched
        if best_s and best_score >= 0.45:
            return self._speaker_result(
                best_s, round(best_score, 2),
                f"Fuzzy match on '{best_match}' for speaker '{best_s.name}'.",
            )
        return ResolveResult.miss("speaker", f"No speaker matched '{room}'.")

    def _speaker_by_entity(self, entity_id: str) -> Optional[Speaker]:
        for s in self.config.devices.speakers:
            if s.entity_id == entity_id:
                return s
        return None

    def _speaker_result(self, s: Speaker, confidence: float, reason: str) -> ResolveResult:
        best = self.resolve_best_entity([s.entity_id])
        return ResolveResult(
            matched=True, kind="speaker", id=s.id, entity_id=s.entity_id,
            name=s.name, confidence=confidence,
            reason=f"{reason} {best.reason}", data=s.model_dump(),
        )

    # ------------------------------------------------------------- display
    def resolve_display(self, name: str) -> ResolveResult:
        displays = self.config.devices.displays
        if not name:
            if self.config.devices.displays:
                d = displays[0]
                return self._entity_result("display", d, 0.5,
                                           "Defaulted to first display.")
            return ResolveResult.miss("display", "No displays configured.")
        q = _norm(name)
        for d in displays:
            if q in {_norm(x) for x in [d.id, d.name, *d.aliases]}:
                return self._entity_result("display", d, 1.0,
                                           f"Exact match on display '{d.name}'.")
        best: Optional[Display] = None
        best_score = 0.0
        best_match = ""
        for d in displays:
            score, matched = _best_alias_score(name, [d.id, d.name, *d.aliases])
            if score > best_score:
                best_score, best, best_match = score, d, matched
        if best and best_score >= 0.45:
            return self._entity_result("display", best, round(best_score, 2),
                                       f"Fuzzy match for display '{best.name}'.")
        return ResolveResult.miss("display", f"No display matched '{name}'.")

    # ---------------------------------------------------------- music acct
    def resolve_music_account(self, user: str) -> ResolveResult:
        u = self.resolve_user(user) if user else ResolveResult.miss("user", "no user")
        accounts = self.config.devices.music_accounts
        if u.matched:
            user_obj = self.get_user(u.id)
            key = user_obj.music_account if user_obj else None
            if key and key in accounts:
                acct = accounts[key]
                return ResolveResult(
                    matched=True, kind="music_account", id=key, name=acct.name,
                    confidence=1.0,
                    reason=f"User '{user_obj.name}' is mapped to {acct.name}.",
                    data={"key": key, **acct.model_dump()},
                )
            return ResolveResult.miss(
                "music_account", f"User '{u.name}' has no mapped music account."
            )
        return ResolveResult.miss("music_account", f"Could not resolve user '{user}'.")

    # ------------------------------------------------------------- aliases
    def resolve_device_alias(self, name: str) -> ResolveResult:
        aliases = self.config.devices.device_aliases
        if not name:
            return ResolveResult.miss("device", "No device name given.")
        q = _norm(name)
        for d in aliases:
            if q in {_norm(x) for x in [d.id, d.name, *d.aliases]}:
                return self._entity_result("device", d, 1.0,
                                           f"Exact match on device '{d.name}'.")
        best = None
        best_score = 0.0
        for d in aliases:
            score, _ = _best_alias_score(name, [d.id, d.name, *d.aliases])
            if score > best_score:
                best_score, best = score, d
        if best and best_score >= 0.5:
            return self._entity_result("device", best, round(best_score, 2),
                                       f"Fuzzy match on device '{best.name}'.")
        return ResolveResult.miss("device", f"No device alias matched '{name}'.")

    # ---------------------------------------------------------------- fans
    def resolve_fan(self, target: str) -> ResolveResult:
        """Resolve a fan target from rooms[].fans, fan.* device aliases, and
        natural aliases like 'office fan'. Prefers available entities and never
        picks an entity listed in `avoid`."""
        if not target:
            return ResolveResult.miss("fan", "No fan name given.")
        q = _norm(target)
        # (score, entity_id, name, id, reason)
        candidates: list[tuple[float, str, str, Optional[str], str]] = []

        # 1. Rooms that declare a `fans` list.
        for r in self.config.devices.rooms:
            fans = getattr(r, "fans", None) or []
            if not fans:
                continue
            names = [r.id, r.name, *r.aliases, f"{r.name} fan"] + [f"{a} fan" for a in r.aliases]
            score, _ = _best_alias_score(target, names)
            if q in {_norm(x) for x in names}:
                score = 1.0
            for eid in fans:
                candidates.append((score, eid, f"{r.name} Fan", r.id, f"room '{r.name}' fan"))

        # 2. device_aliases whose entity_id is in the fan domain.
        for d in self.config.devices.device_aliases:
            if not (d.entity_id or "").startswith("fan."):
                continue
            names = [d.id, d.name, *d.aliases]
            score, _ = _best_alias_score(target, names)
            if q in {_norm(x) for x in names}:
                score = 1.0
            candidates.append((score, d.entity_id, d.name, d.id, f"device alias '{d.name}'"))

        # Never pick an avoided entity.
        candidates = [c for c in candidates if c[1] not in self.avoid]
        if not candidates:
            return ResolveResult.miss("fan", f"No fan matched '{target}'.")

        # Rank by match score, then prefer entities that are currently available.
        candidates.sort(key=lambda c: (c[0], 1 if self._is_available(c[1]) else 0),
                        reverse=True)
        score, entity_id, name, fan_id, reason = candidates[0]
        if score < 0.45:
            return ResolveResult.miss("fan", f"No fan matched '{target}'.")
        avail = "available" if self._is_available(entity_id) else "status unknown"
        return ResolveResult(
            matched=True, kind="fan", id=fan_id, entity_id=entity_id, name=name,
            confidence=round(score, 2),
            reason=f"Matched fan via {reason} ({avail}).",
            data={"entity_id": entity_id, "name": name},
        )

    # ------------------------------------------------------- generic target
    def resolve_target(self, name: str) -> ResolveResult:
        """Generic resolution across all configured device types AND live HA
        entities. Used by control_device/query_device (PART 3). Prefers
        available entities, skips `avoid`, and returns the entity domain."""
        if not name:
            return ResolveResult.miss("target", "No target given.")
        q = _norm(name)
        # (score, entity_id, friendly_name, reason)
        cands: list[tuple[float, str, str, str]] = []

        def add(eid: Optional[str], nm: str, names: list[str], reason: str, scale: float = 1.0):
            if not eid or eid in self.avoid:
                return
            score, _ = _best_alias_score(name, [n for n in names if n])
            if q in {_norm(n) for n in names if n}:
                score = 1.0
            if score > 0:
                cands.append((round(score * scale, 3), eid, nm, reason))

        d = self.config.devices
        for da in d.device_aliases:
            add(da.entity_id, da.name, [da.id, da.name, *da.aliases], f"device alias '{da.name}'")
        for c in d.cameras:
            add(c.entity_id, c.name, [c.id, c.name, *c.aliases], f"camera '{c.name}'")
        for lk in d.locks:
            add(lk.entity_id, lk.name, [lk.id, lk.name, *lk.aliases], f"lock '{lk.name}'")
        for cl in d.climate:
            add(cl.entity_id, cl.name, [cl.id, cl.name, *cl.aliases], f"climate '{cl.name}'")
        for sp in d.speakers:
            add(sp.entity_id, sp.name, [sp.id, sp.name, *sp.aliases], f"speaker '{sp.name}'")
        for dp in d.displays:
            if dp.entity_id:
                add(dp.entity_id, dp.name, [dp.id, dp.name, *dp.aliases], f"display '{dp.name}'")
        for ss in d.security_sensors:
            add(ss.entity_id, ss.name, [ss.entity_id, ss.name, *ss.aliases], f"sensor '{ss.name}'")

        # Direct match against live HA entities (id or friendly name).
        for eid, ent in self.live_states.items():
            if eid in self.avoid:
                continue
            fn = ent.friendly_name or ""
            score, _ = _best_alias_score(name, [eid, fn])
            if _norm(eid) == q or (fn and _norm(fn) == q):
                score = 1.0
            if score >= 0.6:
                cands.append((round(score * 0.95, 3), eid, fn or eid, "live entity match"))

        if not cands:
            return ResolveResult.miss("target", f"No device matched '{name}'.")

        # Rank by score, then prefer available entities.
        cands.sort(key=lambda c: (c[0], 1 if self._is_available(c[1]) else 0), reverse=True)
        score, entity_id, friendly, reason = cands[0]
        if score < 0.45:
            return ResolveResult.miss("target", f"No confident match for '{name}'.")
        domain = entity_id.split(".", 1)[0] if "." in entity_id else ""
        avail = "available" if self._is_available(entity_id) else "unavailable"
        return ResolveResult(
            matched=True, kind="target", entity_id=entity_id, name=friendly or entity_id,
            confidence=round(score, 2),
            reason=f"Matched via {reason} ({avail}).",
            data={"entity_id": entity_id, "domain": domain, "friendly_name": friendly,
                  "available": self._is_available(entity_id)},
        )

    # --------------------------------------------------------------- utils
    def _entity_result(self, kind: str, obj: Any, confidence: float, reason: str) -> ResolveResult:
        return ResolveResult(
            matched=True, kind=kind, id=getattr(obj, "id", None),
            entity_id=getattr(obj, "entity_id", None),
            name=getattr(obj, "name", None),
            confidence=confidence, reason=reason, data=obj.model_dump(),
        )
