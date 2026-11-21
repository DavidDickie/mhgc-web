"""Computer empires name the systems they own (Dave 2026-11-13: "Have the bots name systems";
DECISIONS W-14).

A system the bot owns that still has a generated name (a capital letter and three digits, as
mapgen makes them) gets a themed name through the normal NSY order, at most one a turn (two when
four or more are waiting).  Homes the race already named are left alone.  Names come from the
race's own list (mhgc/data/system_names.py), shuffled once per game from the bot's seeded
randomness, then _II/_III variants, then numbered names.  A name is never one the bot can see on
any system (own, scanned or remembered), never one it used before, and never one an earlier NSY
of its own was refused for (another race may hold it out of sight).

The NSY orders go last in the turn's orders, so nothing earlier in the same orders still uses the
old name.  Other empires' orders that name the system by its old name keep working: the engine
resolves a foreign system by the name the ordering empire last saw it under
(orders_exec._known_system).
"""
from __future__ import annotations

import re

from ..data import constants as K
from ..data.system_names import PERSONA_NAMES, RACE_NAMES, ROMAN

GENERATED = re.compile(r"^[A-Z][1-9]{3}$")
TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def is_generated(name: str | None) -> bool:
    return bool(name) and bool(GENERATED.fullmatch(name))


def _base_names(race: str, persona: str, eid: int) -> list[str]:
    if race in RACE_NAMES:
        return list(RACE_NAMES[race])
    pool = PERSONA_NAMES.get(persona) or PERSONA_NAMES["builder"]
    return [n for i, n in enumerate(pool) if i % 16 == (eid - 1) % 16]


def _candidates(nm: dict, race: str, eid: int):
    base = nm["order"]
    yield from base
    for r in ROMAN:
        for n in base:
            v = f"{n}_{r}"
            if len(v) <= K.NAME_MAX:
                yield v
    stem = re.sub(r"[^A-Za-z]", "", race)[:7] or "World"
    for i in range(1, 100):
        yield f"{stem}{eid:02d}_{i}"


def visible_names(view: dict) -> set[str]:
    out = {s["name"] for s in view["systems"]}
    out |= {s["name"] for s in view["known_systems"] if s.get("name")}
    out |= {s["name"] for s in (view.get("scans") or {}).get("systems") or [] if s.get("name")}
    return out


def plan_renames(w, plan, rng) -> list[tuple[str, str]]:
    """Add this turn's NSY orders (call last).  Returns [(old, new)]."""
    mem = w.mem
    nm = mem.get("names")
    if nm is None:
        order = _base_names(w.name, w.persona.get("name", "builder"), w.eid)
        rng.shuffle(order)
        nm = mem["names"] = {"order": order, "used": [], "burned": []}
    # an NSY refused last turn: someone holds that name out of our sight
    for o in (w.results or {}).get("orders") or []:
        if o.get("code") == "NSY" and not o.get("ok") and o.get("text"):
            bad = o["text"].split()[-1]
            if bad not in nm["burned"]:
                nm["burned"].append(bad)
    pending = sorted((s for s in w.systems if is_generated(s.name)),
                     key=lambda s: (-s.pop, s.id))
    if not pending:
        return []
    k = 2 if len(pending) >= 4 else 1
    taken = visible_names(w.view) | set(nm["used"]) | set(nm["burned"])
    out = []
    gen = _candidates(nm, w.name, w.eid)
    for s in pending[:k]:
        new = next((n for n in gen if n not in taken and TOKEN.fullmatch(n) and
                    len(n) <= K.NAME_MAX), None)
        if new is None:
            break
        taken.add(new)
        if plan.add("NSY", "name our new world", system=s.name, name=new) is not None:
            nm["used"].append(new)
            out.append((s.name, new))
    return out


__all__ = ["plan_renames", "is_generated", "GENERATED"]
