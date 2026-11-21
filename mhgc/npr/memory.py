"""Bot memory: what a computer empire remembers between turns, kept in `GameState.npr_state`.

Plain JSON with **string keys** throughout (a save/load round trip turns int keys into strings,
so using strings keeps a reloaded game identical to an uninterrupted one).  Everything in it was
derived from the empire's own views (mhgc.view) - nothing else is ever written here.

Personalities are parameter sets (Dave 2026-11-12: "aggressive, builder, opportunist"):
  aggression   share of production that goes into warships, and how readily it attacks
  win_needed   estimated chance of winning (engine combat simulation) needed to attack
  greed        weight of victory points in research and expansion choices
  claim        squares of space around its worlds it claims (warnings, rules:249-250)
  forgive      fraction of grievance forgotten per turn
  war_at       grievance that triggers war
  ally_at      standing needed to offer an alliance
"""
from __future__ import annotations

from typing import Any

from ..rng import Rng
from .trace import note

MEMORY_VERSION = 2
HISTORY_MAX = 80

PERSONAS: dict[str, dict[str, float]] = {
    "aggressive": {"aggression": 0.45, "win_needed": 0.6, "greed": 1.0, "claim": 7,
                   "forgive": 0.04, "war_at": 18, "ally_at": 30},
    "builder": {"aggression": 0.2, "win_needed": 0.85, "greed": 1.4, "claim": 5,
                "forgive": 0.10, "war_at": 30, "ally_at": 12},
    "opportunist": {"aggression": 0.32, "win_needed": 0.7, "greed": 1.2, "claim": 6,
                    "forgive": 0.07, "war_at": 24, "ally_at": 18},
}
PERSONA_ORDER = ("aggressive", "builder", "opportunist")

# How each personality makes war and spies (Dave 2026-11-15).  Looked up by name, so games saved
# before these existed (whose memory holds the older persona dict) pick them up unchanged.
#   ramp_tier / ramp_turn  aggression ramps once it owns a warship class of the light cruiser's
#                tier (tier 1: a 500-EU ship technology, tier 2: 1000 EU or more); a builder
#                waits for tier 2 or turn `ramp_turn`
#   missions     war fleets at once after the ramp (one before)
#   need         engine-estimated capture chance needed to launch after the ramp
#   pre / post   multiplier on the warship upkeep share before / after the ramp
#   conquer_below  standing (goodwill - grievance) under which a neighbour is a fair target after
#                the ramp; anyone not allied is a target when it is very weak (capture >= 0.9)
#   range        squares from the staging system to a conquest target after the ramp
#   easy         before the ramp, also take very weak neighbours close by (capture >= 0.9)
#   spies        spies kept (scouting, sabotage, uprisings, counter-intelligence)
#   spy_share    share of income the spy service may cost a turn (upkeep and missions)
WAR_STYLE: dict[str, dict] = {
    "aggressive": {"ramp_tier": 1, "ramp_turn": 999, "missions": 3, "need": 0.55, "pre": 0.8,
                   "post": 1.15, "conquer_below": 22, "range": 22, "easy": True, "spies": 3,
                   "spy_share": 0.05},
    "opportunist": {"ramp_tier": 1, "ramp_turn": 999, "missions": 2, "need": 0.62, "pre": 0.8,
                    "post": 1.1, "conquer_below": 12, "range": 18, "easy": True, "spies": 4,
                    "spy_share": 0.08},
    "builder": {"ramp_tier": 2, "ramp_turn": 50, "missions": 1, "need": 0.72, "pre": 0.85,
                "post": 1.0, "conquer_below": 0, "range": 14, "easy": False, "spies": 2,
                "spy_share": 0.03},
}


def style(mem: dict) -> dict:
    return WAR_STYLE.get((mem.get("persona") or {}).get("name"), WAR_STYLE["opportunist"])


def new_memory(seed: int, eid: int, turn: int, persona: str | None = None) -> dict[str, Any]:
    if persona is None:
        r = Rng(seed, 0, "npr-persona")
        persona = PERSONA_ORDER[(eid + r.below(len(PERSONA_ORDER))) % len(PERSONA_ORDER)]
    p = dict(PERSONAS[persona])
    p["name"] = persona
    return {
        "v": MEMORY_VERSION, "born": turn, "persona": p, "mode": "expand",
        "inbox": None,          # this empire's own last turn report (what view() needs)
        "races": {},            # str(race) -> standing
        "intel": {},            # str(system) -> facts from short-range scans
        "claims": {},           # str(transport) -> system id it will settle
        "missions": [],         # war fleets
        "enemy": {},            # str(race) -> observed fleet make-up (decaying)
        "visited": [],          # system ids scouted up close
        "history": [],
        "stats": {"wars": 0, "peace": 0, "warnings": 0, "missions": 0, "captures": 0,
                  "colonies": 0, "evals": 0, "alliances": 0},
    }


def memory(state, eid: int, persona: str | None = None) -> dict[str, Any]:
    m = state.npr_state.get(eid)
    if m is None or m.get("v") != MEMORY_VERSION:
        m = new_memory(state.seed, eid, state.turn, persona)
        state.npr_state[eid] = m
    return m


def race(mem: dict, rid: int, turn: int) -> dict[str, Any]:
    k = str(rid)
    r = mem["races"].get(k)
    if r is None:
        r = {"griev": 0.0, "good": 0.0, "met": turn, "warned": -1, "intrude": 0,
             "peace_req": -1, "ally_req": -1, "war_since": -1, "last_fight": -1,
             "peace_offer": -1, "why": []}
        mem["races"][k] = r
    return r


def log(mem: dict, turn: int, ev: str, **data) -> None:
    """The bot's own capped history (it reads it back, e.g. diplo's "losing" check).  Each entry
    also goes to the decision log when one is being collected (mhgc/npr/trace.py)."""
    note(ev, **data)
    mem["history"].append({"t": turn, "ev": ev, **data})
    if len(mem["history"]) > HISTORY_MAX:
        del mem["history"][: len(mem["history"]) - HISTORY_MAX]
