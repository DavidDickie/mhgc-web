"""The bot in whole games (mhgc/npr/sim.py): normal games with NPR seats, strength matches with
bots in player seats, and a defence scenario.

Invariants: bot orders validate (any rejection is one of the known races between empires in the
same order phase); bots expand, build fleets, fight, make peace; they beat the baseline bot;
games are deterministic per seed and survive a save/load; turn time stays small.
Run with `-s` to see the reports.
"""
from __future__ import annotations

import pytest

from mhgc import geometry as G
from mhgc import model as M
from mhgc.engine.turn import run_turn
from mhgc.mapgen import new_game
from mhgc.npr.sim import match, match_report, report, simulate
from tests.conftest import add_ship

# Rejections a bot cannot foresee: it plans before any order runs and the empires' orders run in
# a random order, so another race may settle its colony target first, or declare war on it first
# (its own DW/DA then fails), or consume the ship it meant to intercept (CTT/SS/DS).  A spy sent
# (SMV) to a system last seen long ago may find it has since been taken by a race we haven't met:
# the view still shows the old owner (2026-11-19, seed 1 turn 59: seen T13, owner changed since).
EXPLAINED = ("use UG (unload as a gift)", "You are already at war", "You are at war with the",
             "doesn't exist or isn't yours", "There is no ship",
             "You haven't made contact with the race that owns")
SIMS = {"s1_h0_none_60": (1, 0, 60, "none"), "s2_h1_random_60": (2, 1, 60, "random"),
        "s3_h2_none_45": (3, 2, 45, "none")}
_cache: dict = {}


def sim(key):
    if key not in _cache:
        _cache[key] = simulate(*SIMS[key])
        print("\n" + report(_cache[key]))
    return _cache[key]


def mixmatch():
    if "mix" not in _cache:
        _cache["mix"] = match(5, 60, "mix")
        print("\n" + match_report(_cache["mix"]))
    return _cache["mix"]


def _check_rejections(d):
    assert not d["bugs"]
    rate = d["rejected"] / max(1, d["orders"])
    assert rate < 0.003, d["rejections"]
    for msg in d["rejections"]:
        assert any(x in msg for x in EXPLAINED), msg


@pytest.mark.parametrize("key", list(SIMS))
def test_bot_orders_validate(key):
    s = sim(key)
    assert s["orders"] > 100 * s["turns"]
    _check_rejections(s)


@pytest.mark.parametrize("key", list(SIMS))
def test_bots_expand_and_build_fleets(key):
    s = sim(key)
    sysc = s["systems"]
    assert sysc[9] >= 3 * sysc[0] and sysc[-1] >= 7 * (16 - s["humans"])
    assert s["colonies"] >= 80 and s["ships"][-1] >= 4 * s["ships"][0]
    # every race is ranked (DECISIONS A-06): on turn 1 all are tied first in every statistic,
    # so VP start near 20 for everyone; measure the growth from turn 10 instead
    assert s["vp"][-1] > 1.5 * s["vp"][9]
    for c in ("BS", "BCU", "L", "U", "MS", "MO", "PT", "BI", "CSP", "BSP", "BT"):
        assert s["codes"][c] > 0, c


@pytest.mark.parametrize("key", list(SIMS))
def test_bots_warn_fight_and_never_declare_on_themselves(key):
    s = sim(key)
    assert s["warnings"] > 0 and s["missions"] >= 1 and s["evals"] > 0
    for h in s["history"]:
        if h["ev"] == "war":
            assert h["race"] not in (0, h["npr"])


def test_wars_captures_and_peace_over_the_games():
    tot = {k: sum(sim(key).get(k, 0) for key in SIMS) for k in ("wars", "captures", "peace")}
    assert tot["wars"] >= 2 and tot["captures"] >= 2 and tot["peace"] >= 1


@pytest.mark.parametrize("key", list(SIMS))
def test_turn_time(key):
    secs = sim(key)["seconds"]
    assert sum(secs) / len(secs) < 1.0 and max(secs) < 4.0


def test_bot_beats_the_baseline():
    m = mixmatch()
    bot, base = m["by_kind"]["bot"], m["by_kind"]["base"]
    _check_rejections(bot)
    assert bot["vp"][-1] > 1.5 * base["vp"][-1]
    assert bot["systems"][-1] > base["systems"][-1]
    top = [kind for _, kind, *_ in m["ranking"][:4]]
    assert top.count("bot") >= 3


def test_deterministic_per_seed_and_across_save_load():
    a = simulate(7, 1, 18, "random")["state"]
    b = simulate(7, 1, 18, "random")["state"]
    assert M.dumps(a) == M.dumps(b)
    st = new_game("d", 8, ["H"])
    for _ in range(14):
        run_turn(st, {1: []})
    copy = M.loads(M.dumps(st))
    for _ in range(5):
        run_turn(st, {1: []})
        run_turn(copy, {1: []})
    assert M.dumps(st) == M.dumps(copy)


def test_bot_defends_against_an_attack_and_hits_back():
    """A hostile squadron parks at a bot's home: the bot builds defences there, intercepts the
    attackers, and the grievance becomes war.  It counter-attacks only systems it knows of (no
    hidden information), otherwise it offers peace once the war goes quiet."""
    st = new_game("t", 11, ["Human"])
    hum = st.empires[1]
    npr = min((e for e in st.empires.values() if e.kind == "npr"),
              key=lambda e: G.distance(e.home_x, e.home_y, hum.home_x, hum.home_y))
    for _ in range(10):
        run_turn(st, {1: []})
    home = st.system_at(npr.home_x, npr.home_y)
    attackers = [add_ship(st, 1, "D", home.x, home.y, number=20000 + i, posture="H",
                          role="SC").number for i in range(3)]
    hum.techs.add(15)
    seen = {"defence": False, "war": None, "intercept": False}
    # 20 turns: with CGR gone (DECISIONS G-09) the bot's random draws shifted and its peace
    # offer, made once the war has gone quiet, comes on turn 17-20 of the scenario (was <= 16).
    for _ in range(20):
        res = run_turn(st, {1: []})
        rep = res.report(npr.id)
        assert all(o.ok for o in rep.orders), [(o.text, o.error) for o in rep.orders
                                               if not o.ok]
        seen["defence"] |= any(o.code in ("BS", "BCU") and home.name in o.text
                               for o in rep.orders)
        seen["intercept"] |= any(o.code == "I" and str(attackers[0])[:3] in o.text
                                 for o in rep.orders)
        if npr.relations.get(1) == "W" and seen["war"] is None:
            seen["war"] = st.turn
    mem = st.npr_state[npr.id]
    assert seen["defence"] and seen["intercept"] and seen["war"] is not None
    assert not any(st.ship(n) for n in attackers)
    assert any(h["ev"] == "war" and h["race"] == 1 for h in mem["history"])
    knows_them = any(info.get("owner") == 1 for info in npr.seen_systems.values())
    if knows_them:
        assert any(h["ev"] == "mission" and h["race"] == 1 for h in mem["history"])
    else:
        assert any(h["ev"] == "peace_offer" and h["race"] == 1 for h in mem["history"])
