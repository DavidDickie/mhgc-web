"""Dave 2026-11-16, after his turn-45 game: two computer empires at war with him had spent 35 turns
defending, with upkeep over half their income and 7 and 11 technologies.  War-weariness peace,
an upkeep cap with salvage, a research floor and a concentrated defence (DECISIONS A-10).  All
from the bot's own view (the scramble test at the end)."""
from __future__ import annotations

import json
import random

from mhgc import model as M
from mhgc.data import constants as K
from mhgc.engine.turn import initial_results, run_turn
from mhgc.npr.brain import inbox
from mhgc.mapgen import new_game
from mhgc.npr import diplo, econ, memory, npr_orders, war
from mhgc.npr.memory import PERSONAS, race as race_of
from mhgc.npr.plan import Plan
from mhgc.npr.world import build
from mhgc.rng import Rng
from mhgc.view import view
from tests.conftest import add_ship, add_troop, contact, make_state, sysn
from tests.test_npr_units import _scramble, _validate

NPR_ID = 3


def _w(st, persona="opportunist", scan=False):
    mem = memory(st, NPR_ID)
    mem["persona"] = dict(PERSONAS[persona], name=persona)
    results = inbox(initial_results(st), NPR_ID) if scan else None   # this turn's scans
    return build(view(st, results, NPR_ID), mem)


def _at_war(st, since, persona="opportunist"):
    contact(st, NPR_ID, 1, "W")
    st.turn = since
    w = _w(st, persona)
    diplo.learn(w)                                     # notices the war: war_since = since
    return race_of(w.mem, 1, st.turn)


def _diplo(st, persona="opportunist"):
    w = _w(st, persona)
    plan = Plan(w)
    diplo.plan(w, plan, Rng(1, st.turn, "t"))
    return [o for o in plan.orders if o.code in ("MESSAGE", "EWA")], w


def test_a_long_war_with_nothing_gained_brings_a_peace_offer_by_personality():
    for persona, turns in (("builder", 8), ("opportunist", 10), ("aggressive", 14)):
        st = make_state()
        r = _at_war(st, 10, persona)
        r["griev"] = 96.0                              # a grudge doesn't stop a weary bot
        r["last_fight"] = 10 + turns                   # and the fighting hasn't stopped
        st.turn = 10 + turns - 1
        r["last_fight"] = st.turn
        got, _ = _diplo(st, persona)
        assert not got, persona                        # not yet
        st.turn = 10 + turns
        r["last_fight"] = st.turn
        got, w = _diplo(st, persona)
        codes = [o.code for o in got]
        assert codes == ["MESSAGE", "EWA"], persona
        assert "(EWA)" in got[0].text and "peace" in got[0].text.lower()
        assert w.mem["history"][-1]["why"] == "weary"


def test_peace_sooner_against_a_much_stronger_enemy():
    st = make_state()
    r = _at_war(st, 10)
    st.turn = 16                                       # 6 turns: 0.6 x 10 for an opportunist
    r["last_fight"] = st.turn
    got, _ = _diplo(st)
    assert not got
    h1 = sysn(st, "H1")
    for i in range(6):                                 # their warships at our door
        add_ship(st, 1, "D", h1.x + 30 - i % 2, h1.y + 30)
    r["w_pressed"] = 6
    got, w = _diplo(st)
    assert [o.code for o in got] == ["MESSAGE", "EWA"]
    assert diplo.war_weary(w, 1, race_of(w.mem, 1, st.turn))[1]


def test_the_offer_stands_every_turn_and_the_message_is_repeated():
    st = make_state()
    r = _at_war(st, 10)
    msgs = []
    for t in range(20, 34):
        st.turn = t
        r["last_fight"] = t
        got, _ = _diplo(st)
        assert "EWA" in [o.code for o in got]          # every turn while weary
        msgs += [t for o in got if o.code == "MESSAGE"]
    assert msgs == [20, 26, 32]


def test_not_weary_while_the_war_pays():
    st = make_state()
    r = _at_war(st, 10)
    st.turn = 22
    r.update(last_fight=22, w_caps=2, w_gain_t=20,     # took two of their systems lately
             griev=96.0)
    got, w = _diplo(st)
    assert not got
    r.update(w_lost=3)                                 # ... but lost three: no net gain
    got, _ = _diplo(st)
    assert [o.code for o in got] == ["MESSAGE", "EWA"]


def test_after_peace_a_truce_and_no_conquest_of_that_race():
    st = make_state()
    contact(st, 1, NPR_ID)
    contact(st, NPR_ID, 1)
    st.turn = 30
    w = _w(st, "aggressive")
    r = race_of(w.mem, 1, st.turn)
    r.update(griev=90.0, war_since=5, started=5)
    diplo.learn(w)                                     # the peace has come
    assert r["peace_t"] == 30 and r["griev"] <= w.persona["war_at"] * 0.5
    r["griev"] = w.persona["war_at"] * 1.5            # new grievances, but within the truce
    st.turn = 35
    w = _w(st, "aggressive")
    plan = Plan(w)
    diplo.plan(w, plan, Rng(1, 35, "t"))
    assert "DW" not in [o.code for o in plan.orders]
    h1 = sysn(st, "H1")
    w.mem["intel"][str(h1.id)] = {"t": 34, "owner": 1, "pop": 4, "hab": 3, "mr": False,
                                  "ar": False, "starport": 2, "status": "Norm", "weapons": [],
                                  "artifacts": 0, "troops": []}
    w.techs |= {1, 8, 18}
    assert econ.ramped(w)
    assert not [x for x in war.candidate_targets(w) if x[0] == "conquest"]
    st.turn = 30 + war.PEACE_RESPITE
    w.mem["intel"][str(h1.id)]["t"] = st.turn - 1
    w = _w(st, "aggressive")
    w.techs |= {1, 8, 18}
    assert [x[0] for x in war.candidate_targets(w)] == ["conquest"]


def _fortress(st, n_ships=30):
    """The computer empire: one system, many destroyers at home, a hostile fleet next door."""
    h3 = sysn(st, "H3")
    h3.pop, h3.infra, h3.iu, h3.starport = 9.0, 9, 3000, 4
    for _ in range(n_ships):
        add_ship(st, NPR_ID, "D", h3.x, h3.y)
    return h3


def test_no_new_warships_over_the_upkeep_cap_even_when_threatened():
    st = make_state()
    contact(st, NPR_ID, 1, "W")
    h3 = _fortress(st, 14)
    st.empires[NPR_ID].eu = 3000
    st.empires[NPR_ID].techs |= {1}
    for _ in range(12):
        add_ship(st, 1, "D", h3.x + 2, h3.y)           # a strong enemy fleet next door
    w = _w(st, scan=True)
    w.populated[0].production = {"eu": 60, "iu": 60}   # a small income: cap 24 EU
    thr = war.threats(w)
    assert thr[h3.id]["attack"] > 0
    assert war.mil_upkeep(w) > war.mil_cap(w)
    plan = Plan(w)
    war.defend(w, plan, thr)
    assert not [o for o in plan.orders if o.code == "BS"]
    assert [o for o in plan.orders if o.code == "BCU"]  # ground troops still dig in


def test_far_over_the_cap_the_weakest_warships_are_salvaged():
    st = make_state()
    h3 = _fortress(st, 30)
    for _ in range(4):
        add_ship(st, NPR_ID, "F", h3.x, h3.y)          # frigates: the obsolete ones
    w = _w(st)
    w.populated[0].production = {"eu": 100, "iu": 60}
    plan = Plan(w)
    war.defend(w, plan, war.threats(w))
    ss = [o for o in plan.orders if o.code == "SS"]
    assert 0 < len(ss) <= min(war.SALVAGE_MAX, h3.starport)
    frigates = {sh.number for sh in st.ships.values() if sh.type == "F"}
    assert {o.ship for o in ss} <= frigates
    assert not _validate(st, NPR_ID, plan.orders)


def test_one_fleet_counts_in_full_only_where_it_can_strike_first():
    st = make_state(npr=1)
    contact(st, NPR_ID, 1, "W")
    h3 = sysn(st, "H3")
    near = M.System(len(st.systems), "N3", h3.x + 2, h3.y, owner=NPR_ID, pop=3.0, hab=3,
                    starport=1)
    st.systems.append(near)
    for e in st.empires.values():
        e.seen_systems[near.id] = {"turn": 0, "name": "N3", "owner": NPR_ID}
    for _ in range(4):
        add_ship(st, 1, "D", h3.x + 6, h3.y)           # 1 turn from N3, 2 from H3
    w = _w(st, scan=True)
    thr = war.threats(w)
    eff = war.focused_threats(w, thr)
    assert eff[near.id]["attack"] == thr[near.id]["attack"]
    assert 0 < eff[h3.id]["attack"] < thr[h3.id]["attack"]


def test_a_quarter_of_income_goes_to_research_even_at_war():
    st = make_state()
    contact(st, NPR_ID, 1, "W")
    h3 = sysn(st, "H3")
    h3.pop, h3.infra, h3.iu = 9.0, 9, 3000
    st.turn = 30
    st.empires[NPR_ID].eu = 400
    for _ in range(6):
        add_ship(st, 1, "D", h3.x + 2, h3.y)
    w = _w(st, scan=True)
    w.populated[0].production = {"eu": 400, "iu": 100}
    plan = Plan(w)
    held = econ.research_hold(w, plan, False)
    assert held == 100 and plan.eu == 300
    war.defend(w, plan, war.threats(w))                # defence can't touch the held 100
    assert plan.eu >= 0
    econ.research_release(w, plan, held)
    econ.research(w, plan, True, True, False)
    econ.research_after(w, plan, held)
    assert plan.spent["research"] >= 100 or w.mem["rsave"] >= 100
    # under attack at home: no hold
    w = _w(st)
    plan = Plan(w)
    assert econ.research_hold(w, plan, True) == 0


def _two_bots_at_war(seed=5):
    st = new_game("weary", seed, [], size=8)
    ids = sorted(e.id for e in st.empires.values() if e.kind == "npr")
    a, b = ids[0], ids[1]
    for _ in range(12):
        run_turn(st, {})
    contact(st, a, b, "W")
    return st, a, b


def test_two_weary_computer_empires_make_peace_through_the_engine():
    st, a, b = _two_bots_at_war()
    for _ in range(25):
        run_turn(st, {})
        if st.empires[a].relations.get(b) == "N":
            break
    assert st.empires[a].relations.get(b) == "N" == st.empires[b].relations.get(a)
    run_turn(st, {})                                   # each notices the peace in its report
    assert any(h["ev"] == "peace" and h.get("race") == b for h in st.npr_state[a]["history"])


def test_weary_bots_still_decide_only_from_their_own_view():
    st, a, b = _two_bots_at_war(seed=6)
    for _ in range(9):
        run_turn(st, {})
    st.turn += 1
    for eid in (a, b):
        x, y = M.loads(M.dumps(st)), M.loads(M.dumps(st))
        _scramble(y, eid, random.Random(eid))
        ox = [o.line for o in npr_orders(x, eid)]
        oy = [o.line for o in npr_orders(y, eid)]
        assert ox == oy and ox
        assert json.dumps(x.npr_state[eid], sort_keys=True) == \
            json.dumps(y.npr_state[eid], sort_keys=True)
    _ = (K, add_troop)
