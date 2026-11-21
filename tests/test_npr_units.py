"""The bot (mhgc/npr): unit tests for its decision functions, and the proof that it uses no
hidden information."""
from __future__ import annotations

import json
import random

from mhgc import model as M
from mhgc.engine.orders_exec import execute
from mhgc.engine.turn import new_context, run_turn
from mhgc.mapgen import new_game
from mhgc.npr import bot_orders, memory, npr_orders
from mhgc.npr import diplo, econ, expand, war
from mhgc.npr.evalcombat import assault, fleet_vs_fleet
from mhgc.npr.memory import PERSONAS
from mhgc.npr.plan import Plan
from mhgc.npr.world import build
from mhgc.rng import Rng
from mhgc.view import view
from tests.conftest import add_ship, contact, make_state, sysn

NPR_ID = 3          # make_state(): 1, 2 humans, 3 the NPR, home H3 at (30, 30)


def _w(st, eid=NPR_ID, results=None, persona=None):
    mem = memory(st, eid)
    if persona:
        mem["persona"] = dict(PERSONAS[persona], name=persona)
    return build(view(st, results, eid), mem)


def _validate(st, eid, orders):
    ctx = new_context(st)
    ctx.empire_order = [eid]
    out = [execute(ctx, eid, o, i) for i, o in enumerate(orders)]
    return [(r.text, r.error) for r in out if not r.ok]


def _codes(orders):
    return [o.code for o in orders]


# ---- no hidden information --------------------------------------------------------------------

def _scramble(st, eid, r: random.Random):
    """Change everything about the other empires that `eid` cannot see: their money, techs,
    stances (towards us too), memories, leaders, spies, every foreign ship and every foreign
    troop not standing on one of our systems, and the contents of every foreign system."""
    mine = {s.id for s in st.systems if s.owner == eid}
    for e in st.empires.values():
        if e.id == eid:
            continue
        e.eu, e.iu_depot = r.randint(0, 9999), r.randint(0, 999)
        e.techs = {0} | set(r.sample(range(1, 51), r.randint(0, 20)))
        for k in list(e.relations):
            if k == eid and e.relations[k] in ("W", "E"):
                continue                       # war is mutual and visible (DW sets both)
            e.relations[k] = r.choice(["N", "A"])
        e.seen_systems = {}
    for k in list(st.npr_state):
        if k != eid:
            st.npr_state[k] = {"scrambled": r.random()}
    for sh in list(st.ships.values()):
        if sh.owner != eid:
            sh.x, sh.y = r.randrange(100), r.randrange(100)
            sh.dx, sh.dy = sh.x, sh.y
            sh.type = r.choice(["F", "D", "T", "S"])
            sh.cargo_iu = sh.cargo_au = sh.cargo_pop = 0
    for t in st.troops.values():
        if t.owner != eid and t.system not in mine:
            t.type = r.choice(["S", "M", "J"])
            t.system, t.ship = (r.choice([s.id for s in st.systems if s.id not in mine]), None)
    for ld in st.leaders.values():
        if ld.owner != eid:
            ld.mgmt, ld.combat, ld.name = r.randint(0, 99), r.randint(0, 99), f"X{ld.id}"
    for sp in st.spies.values():
        if sp.owner != eid:
            sp.system = r.randrange(len(st.systems))
    for s in st.systems:
        if s.id in mine:
            continue
        s.pop, s.iu, s.au = r.random() * 10 if s.pop > 0 else 0.0, r.randint(0, 500), \
            r.randint(0, 500)
        s.artifacts = set(r.sample(["PD", "SW", "CB", "BF"], r.randint(0, 2)))
        s.starport, s.infra = r.randint(0, 3), r.randint(0, 10)
        if s.owner not in (0, eid):
            s.owner = r.choice([o for o in st.empires if o not in (0, eid)])


def test_bot_orders_depend_only_on_what_the_empire_can_see():
    st = new_game("fog", 21, ["Hum"])
    for _ in range(14):
        run_turn(st, {1: []})
    st.turn += 1                                   # as run_turn does before asking the NPRs
    checked = 0
    for eid in [e.id for e in st.empires.values() if e.kind == "npr"][:6]:
        a, b = M.loads(M.dumps(st)), M.loads(M.dumps(st))
        _scramble(b, eid, random.Random(eid))
        oa = [o.line for o in npr_orders(a, eid)]
        ob = [o.line for o in npr_orders(b, eid)]
        assert oa == ob and oa
        assert json.dumps(a.npr_state[eid], sort_keys=True) == \
            json.dumps(b.npr_state[eid], sort_keys=True)
        checked += 1
    assert checked == 6


def test_npr_orders_mutate_only_the_bots_memory():
    st = new_game("u", 9, ["A"])
    for _ in range(10):
        res = run_turn(st, {1: []})
        for e in st.empires.values():
            if e.kind == "npr":
                bad = [(o.text, o.error) for o in res.report(e.id).orders if not o.ok
                       and "use UG" not in o.error]          # another race settled it first
                assert not bad, bad
    before = M.to_dict(st)
    npr_orders(st, 5)
    after = M.to_dict(st)
    before.pop("npr_state"), after.pop("npr_state")
    assert before == after
    assert npr_orders(st, 1) == []                         # a player seat


# ---- economy and research ---------------------------------------------------------------------

def test_profiles_feed_for_growth_and_add_up():
    st = make_state()
    h = sysn(st, "H3")
    h.happy, h.pop, h.au = 0.3, 4.0, 0
    w = _w(st)
    plan = Plan(w)
    econ.profiles(w, plan, 1.0)
    o = plan.orders[0]
    assert o.code == "CSP" and o.au + o.iu + o.eu == 100 and min(o.au, o.iu, o.eu) >= 10
    assert o.au >= 30                                       # unhappy: feed them
    assert econ.au_needed(w, w.systems[0], 0.9) > econ.au_needed(w, w.systems[0], 0.6)
    assert not _validate(st, NPR_ID, plan.orders)


def test_research_one_tech_and_military_lines_when_threatened():
    st = make_state()
    st.empires[NPR_ID].eu = 400
    w = _w(st)
    plan = Plan(w)
    econ.research(w, plan, True, True, False)
    econ.research(w, plan, True, True, False)
    assert _codes(plan.orders) == ["PT"]
    assert plan.orders[0].tech in (6, 7, 4, 1, 5)          # a new line type or defences
    assert not _validate(st, NPR_ID, plan.orders)


def test_development_builds_infrastructure():
    st = make_state()
    w = _w(st)
    plan = Plan(w)
    econ.development(w, plan, set())
    codes = _codes(plan.orders)
    assert "BI" in codes and "CGR" not in codes
    assert not _validate(st, NPR_ID, plan.orders)


# ---- the budget -------------------------------------------------------------------------------

def test_plan_budget_mirrors_the_engine_checks():
    st = make_state()
    w = _w(st)
    h = w.systems[0]                                        # H3: starport 2, 500 IU
    plan = Plan(w)
    assert plan.build_ship(h, "F") and plan.build_troop(h, "S") and plan.build_troop(h, "S")
    assert not plan.build_ship(h, "F")                      # capacity used up
    assert not plan.build_starport(h)                       # builds already made
    assert not _validate(st, NPR_ID, plan.orders)
    st2 = make_state()
    sysn(st2, "H3").status = 1                              # under attack: 2x cost
    w2 = _w(st2)
    p2 = Plan(w2)
    p2.build_ship(w2.systems[0], "F")
    assert p2.iu[w2.systems[0].id] == 500 - 60


# ---- combat evaluation by the engine -----------------------------------------------------------

def test_combat_evaluation_uses_the_engine_and_likes_mixed_fleets():
    strong = assault(["D"] * 6 + ["T"], ["J"] * 3, ["F"], [("S", "E")], 5, [], trials=8)
    weak = assault(["F"], ["S"], ["D"] * 3, [("J", "E")], 10, [], trials=8)
    assert strong["capture"] > 0.5 and weak["capture"] == 0
    mixed = fleet_vs_fleet(["D", "PA", "FF", "ST"], ["D"] * 5, trials=12)
    mono = fleet_vs_fleet(["D"] * 4, ["D"] * 5, trials=12)
    assert mixed >= mono


def test_ship_choice_fills_the_missing_line_and_counters_the_enemy():
    st = make_state()
    st.empires[NPR_ID].techs |= {6, 7, 1, 8, 4, 15}
    w = _w(st)
    lines = {"STANDARD": 10, "DEFENSIVE": 10, "FAST": 10, "OFFENSIVE": 0}
    assert war.SHIP_TYPES[war.choose_ship(w, lines)].line == "OFFENSIVE"
    assert war.best_troop(w, True) in ("J", "S")


# ---- diplomacy --------------------------------------------------------------------------------

def _results(st, eid, combats=(), events=(), messages=()):
    return {"turn": st.turn, "reports": {str(eid): {"combats": [c["id"] for c in combats],
                                                    "events": list(events),
                                                    "messages": list(messages)}},
            "combats": list(combats)}


def test_learning_war_and_never_on_ourselves():
    st = make_state()
    contact(st, 1, NPR_ID)
    h = sysn(st, "H3")
    cl = {"id": 0, "x": h.x, "y": h.y, "system": h.id, "participants": [1, NPR_ID],
          "relations": {f"1,{NPR_ID}": "SURPRISE ATTACK by R1"},
          "ships": [{"number": 77, "owner": NPR_ID, "type": "F"}], "troops": [],
          "lines": [{"text": "R3 Frigate 77 DESTROYED by R1", "ship": 77, "by": 1}],
          "owner_before": NPR_ID, "owner_after": NPR_ID}
    w = _w(st, results=_results(st, NPR_ID, [cl]), persona="aggressive")
    diplo.learn(w)
    r = w.mem["races"]["1"]
    assert r["griev"] > 25 and r["last_fight"] == st.turn
    plan = Plan(w)
    diplo.plan(w, plan, Rng(1, 1, "t"))
    assert "DW" in _codes(plan.orders) and "MESSAGE" in _codes(plan.orders)
    assert not _validate(st, NPR_ID, plan.orders)
    assert not diplo.declare(w, plan, NPR_ID, "x") and not diplo.declare(w, plan, 0, "x")


def test_peace_when_overmatched_or_asked():
    st = make_state()
    contact(st, 1, NPR_ID, "W")
    h = sysn(st, "H3")
    for i in range(8):
        add_ship(st, 1, "D", h.x + 3, h.y)                  # a big enemy fleet in scan range
    res = _results(st, NPR_ID)
    res["reports"][str(NPR_ID)]["scans"] = {"ships": [
        # 6 squares off: out of a Destroyer's one move (4), so no A-12 block on the peace
        {"number": s.number, "owner": 1, "owner_name": "R1", "type": "D", "x": 56, "y": 50,
         "ox": 56, "oy": 50, "level": "long", "moved": False}
        for s in st.ships.values() if s.owner == 1]}
    w = _w(st, results=res)
    diplo.learn(w)
    plan = Plan(w)
    diplo.plan(w, plan, Rng(1, 1, "t"))
    assert "EWA" in _codes(plan.orders)
    assert any(h["ev"] == "peace_offer" and h["why"] == "overmatched" for h in w.mem["history"])
    assert not _validate(st, NPR_ID, plan.orders)


def test_alliance_for_good_standing_but_not_with_the_leader():
    st = make_state()
    contact(st, 1, NPR_ID)
    contact(st, 2, NPR_ID)
    w = _w(st, persona="builder")
    diplo.learn(w)
    w.mem["races"]["2"]["good"] = 25.0
    w.mem["races"]["1"]["good"] = 25.0
    for s in list(w.known.values())[:0]:
        pass
    for i in range(10):                                     # race 1 holds many systems
        w.known[1000 + i] = type(w.systems[0])(id=1000 + i, name=f"Z{i}", x=i, y=0, owner=1,
                                               intel=None, mine=False, last_seen=1)
    assert diplo.leader(w) == 1
    plan = Plan(w)
    diplo.plan(w, plan, Rng(1, 1, "t"))
    da = [o.race for o in plan.orders if o.code == "DA"]
    assert da == ["R2"]


# ---- expansion --------------------------------------------------------------------------------

def test_settler_loads_goes_and_settles():
    st = make_state()
    h = sysn(st, "H3")
    t = add_ship(st, NPR_ID, "T", h.x, h.y)
    w = _w(st)
    plan = Plan(w)
    expand.transports(w, plan, set(), set())
    assert _codes(plan.orders)[:3] == ["L", "L", "MS"]
    tgt = plan.orders[2].system
    assert tgt in ("E1", "E2") and not _validate(st, NPR_ID, plan.orders)
    target = sysn(st, tgt)
    t.x, t.y = target.x, target.y
    w = _w(st)
    plan = Plan(w)
    expand.transports(w, plan, set(), set())
    assert plan.orders[0].code == "U" and plan.orders[0].item == "P"
    assert not _validate(st, NPR_ID, plan.orders) and target.owner == NPR_ID


def test_bot_orders_for_any_seat():
    st = new_game("seat", 3, ["A", "B"])
    from mhgc.engine.turn import initial_results
    res = initial_results(st)
    mem = memory(st, 1, "builder")
    orders = bot_orders(view(st, res, 1), mem, Rng(3, 1, "npr1"))
    assert orders and not _validate(st, 1, orders)
