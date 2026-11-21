"""Dave 2026-11-15: everyone is ranked (DECISIONS A-06), and the bot changes of A-07: aggression
that ramps with light-cruiser-class warships, spies, leaner starports and bot-to-bot tech trades.
All bot decisions still come from the bot's own view (the scramble test at a later turn).
Then the economy-first retune (Dave 2026-11-15, "fight less, research more"; DECISIONS A-09)."""
from __future__ import annotations

import json
import random

from mhgc import model as M
from mhgc.data import constants as K
from mhgc.engine import stats
from mhgc.engine.turn import initial_results, run_turn
from mhgc.mapgen import new_game
from mhgc.model import Spy
from mhgc.npr import econ, memory, npr_orders, spycraft, trade, war
from mhgc.npr.memory import PERSONAS, WAR_STYLE, race as race_of
from mhgc.npr.plan import Plan
from mhgc.npr.brain import inbox
from mhgc.npr.world import build
from mhgc.data.techs import TECHS
from mhgc.rng import Rng
from mhgc.view import view
from tests.conftest import add_ship, contact, ctx_for, make_state, sysn
from tests.test_npr_units import _scramble, _validate

NPR_ID = 3


def _w(st, eid=NPR_ID, persona="aggressive", results=None, scan=False):
    mem = memory(st, eid)
    mem["persona"] = dict(PERSONAS[persona], name=persona)
    if scan:                                            # this turn's scans, as in a game
        results = inbox(initial_results(st), eid)
    return build(view(st, results, eid), mem)


# ---- A-06: ranks and victory over every race ------------------------------------------------

def test_every_race_is_ranked_and_a_computer_empire_can_win():
    st = make_state()                                   # 1, 2 humans; 3 a computer empire
    npr = st.empires[NPR_ID]
    sysn(st, "H3").pop = 9.0                            # first in population
    ctx = ctx_for(st)
    stats.compute_stats(ctx)
    assert npr.ranks and npr.ranks["POP"] == 1
    assert st.empires[1].ranks["POP"] == 2             # second, behind the computer empire
    base = 2 * K.VP_PER_SYSTEM // 2                     # one system, no techs
    assert npr.vp == base + sum(K.VP_STAT_BONUS.get(npr.ranks[s], 0) for s in K.VP_STATS)
    npr.vp = K.VICTORY_POINTS
    stats.check_victory(ctx)
    assert st.winner == NPR_ID and ctx.res.events_of(1, "victory")


def test_a_lone_human_gets_no_free_stat_bonus():
    st = new_game("solo", 740601768, ["GrossBeaks"], size=16)
    initial_results(st)
    vps = {e.id: e.vp for e in st.empires.values() if e.kind in ("human", "npr")}
    assert len(set(vps.values())) == 1                 # all tied at the start, the human too
    run_turn(st, {1: []})
    v = view(st, None, 1)
    assert v["empire"]["ranks"] and "SYS" in v["empire"]["ranks"]


# ---- A-07: aggression ramps with technology -------------------------------------------------

def test_aggression_ramps_with_light_cruisers_by_personality():
    st = make_state()
    st.turn = 46                                        # past every personality's ramp_min
    for persona, gate in (("aggressive", True), ("opportunist", True), ("builder", False)):
        w = _w(st, persona=persona)
        assert not econ.ramped(w)
        w.techs |= {1, 8, 18}                           # High Energy Physics: LightCruiser
        assert econ.ship_tier(w) == 1 and econ.ramped(w) == gate
        w.techs |= {6, 9, 19, 25, 15, 4, 29}            # Cruiser (1000 EU): builders too
        assert econ.ship_tier(w) == 2 and econ.ramped(w)


def test_the_ramp_waits_for_its_turn_even_with_light_cruisers():
    """Research is faster since the economy-first retune (Dave 2026-11-15, "fight less, research
    more"), so the ramp also waits for a turn per personality, aggressive first."""
    st = make_state()
    mins = {}
    for persona in ("aggressive", "opportunist", "builder"):
        mins[persona] = econ.ECON_FIRST[persona]["ramp_min"]
        st.turn = mins[persona] - 1
        w = _w(st, persona=persona)
        w.techs |= {1, 8, 18, 6, 9, 19, 25, 15, 4, 29}  # tier 2 warships
        assert not econ.ramped(w)
        st.turn = mins[persona]
        w = _w(st, persona=persona)
        w.techs |= {1, 8, 18, 6, 9, 19, 25, 15, 4, 29}
        assert econ.ramped(w)
    assert mins["aggressive"] < mins["opportunist"] < mins["builder"]


def test_before_the_ramp_only_wars_rebels_and_easy_prey():
    st = make_state()
    contact(st, 1, NPR_ID)
    contact(st, NPR_ID, 1)
    st.turn = 20
    w = _w(st, persona="builder")
    h1 = sysn(st, "H1")
    w.mem["intel"][str(h1.id)] = {"t": 19, "owner": 1, "pop": 4, "hab": 3, "mr": False,
                                  "ar": False, "starport": 2, "status": "Norm", "weapons": [],
                                  "artifacts": 0, "troops": []}
    w = _w(st, persona="builder")
    assert not [x for x in war.candidate_targets(w) if x[0] != "rebels"]
    w = _w(st, persona="aggressive")
    assert [x[0] for x in war.candidate_targets(w)] == ["easy"]
    w.techs |= {1, 8, 18}
    assert [x[0] for x in war.candidate_targets(w)] == ["easy"]       # not before ramp_min
    st.turn = 30
    w.mem["intel"][str(h1.id)]["t"] = 29
    w = _w(st, persona="aggressive")
    w.techs |= {1, 8, 18}
    assert [x[0] for x in war.candidate_targets(w)] == ["conquest"]


def test_a_neutral_passer_by_no_longer_blocks_every_mission():
    st = make_state()
    contact(st, 1, NPR_ID)
    contact(st, NPR_ID, 1)
    h3 = sysn(st, "H3")
    add_ship(st, NPR_ID, "D", h3.x, h3.y)
    add_ship(st, 1, "D", h3.x + 1, h3.y)                # a neutral destroyer next door
    w = _w(st, scan=True)
    thr = war.threats(w)
    assert thr[h3.id]["attack"] > 0 and not war.under_pressure(w, thr)
    st.empires[NPR_ID].relations[1] = "W"
    w = _w(st, scan=True)
    assert war.under_pressure(w, war.threats(w))


# ---- A-07: starports ------------------------------------------------------------------------

def _starport_plan(st, pending, yards=frozenset()):
    w = _w(st)
    plan = Plan(w)
    plan.tech_pending = pending
    econ.development(w, plan, set(), set(yards))
    return [o for o in plan.orders if o.code == "BSP"], plan, w


def test_starports_wait_while_the_economy_needs_the_money():
    st = make_state()
    for name in ("H1", "H2"):                           # nobody near: an interior world
        s = sysn(st, name)
        s.x, s.y = 80, 80
    h3 = sysn(st, "H3")
    h3.pop, h3.infra, h3.iu, h3.starport = 9.0, 10, 2000, 1
    bsp, plan, _ = _starport_plan(st, pending=False)
    assert bsp and not plan.econ_pending                # bigger is better when nothing waits
    bsp, plan, w = _starport_plan(st, pending=True)
    assert not bsp and plan.econ_pending                # a wanted tech is unaffordable: hold
    bsp, _, _ = _starport_plan(st, pending=True, yards={h3.id})
    assert bsp                                          # ... but not at the main shipyard
    w.mem["sp_short"] = {str(h3.id): st.turn}           # its builds ran out of capacity
    plan = Plan(w)
    plan.tech_pending = True
    econ.development(w, plan, set(), set())
    assert [o for o in plan.orders if o.code == "BSP"]


# ---- A-09: economy first ("fight less, research more") ----------------------------------------

def test_surplus_eu_buys_crash_research_with_the_dearest_as_the_pt():
    st = make_state()
    st.turn = 40
    st.empires[NPR_ID].eu = 6000
    w = _w(st, persona="builder")
    plan = Plan(w)
    econ.research(w, plan, False, False, False)
    buys = [o for o in plan.orders if o.code in ("PT", "CRP")]
    pts = [o for o in buys if o.code == "PT"]
    assert len(pts) == 1 and len(buys) >= 3              # one PT and crash programmes
    cost = {o.tech: TECHS[o.tech].cost for o in buys}
    assert cost[pts[0].tech] == max(cost.values())      # the dearest is the cheap (1x) one
    spent = sum(cost[o.tech] * (2 if o.code == "CRP" else 1) for o in buys)
    assert spent <= 6000 - econ.reserve(w) and plan.eu >= econ.reserve(w)
    assert not _validate(st, NPR_ID, plan.orders)       # the engine accepts every purchase
    st.empires[NPR_ID].eu = 300                         # little money: one PT, no crash
    w = _w(st, persona="builder")
    plan = Plan(w)
    econ.research(w, plan, False, False, False)
    assert [o.code for o in plan.orders] in (["PT"], [])


def test_a_trade_hold_is_respected_by_crash_research():
    st = make_state()
    st.turn = 40
    st.empires[NPR_ID].eu = 6000
    w = _w(st, persona="builder")
    plan = Plan(w)
    plan.no_buy.update({3, 2})
    plan.pay(2000, "offer hold")
    econ.research(w, plan, False, False, False)
    bought = {o.tech for o in plan.orders if o.code in ("PT", "CRP")}
    assert bought and not bought & {3, 2} and plan.eu >= econ.reserve(w)


def test_idle_iu_turns_a_profile_to_eu():
    st = make_state()
    h3 = sysn(st, "H3")
    h3.pop, h3.infra, h3.happy = 8.0, 8, 0.9
    h3.csp = [20, 60, 20]
    h3.iu = 200
    w = _w(st)
    plan = Plan(w)
    econ.profiles(w, plan, 1.0)
    low = [o for o in plan.orders if o.code == "CSP"]
    h3.iu = 9000                                        # far more IU than it can use
    w = _w(st)
    plan = Plan(w)
    econ.profiles(w, plan, 1.0)
    csp = [o for o in plan.orders if o.code == "CSP"]
    assert csp and csp[0].iu == 10 and csp[0].eu > (low[0].eu if low else 20)


def test_peace_settles_the_grudge_that_started_the_war():
    st = make_state()
    contact(st, 1, NPR_ID)
    contact(st, NPR_ID, 1)
    w = _w(st)
    r = race_of(w.mem, 1, st.turn)
    r.update(griev=90.0, war_since=1, started=1)        # we were at war; now at peace
    from mhgc.npr import diplo
    diplo.learn(w)
    assert r["griev"] <= w.persona["war_at"] * 0.5 and "started" not in r


def test_aggressive_is_still_the_most_warlike_but_less_than_before():
    ef, ws = econ.ECON_FIRST, WAR_STYLE
    a, o, b = ef["aggressive"], ef["opportunist"], ef["builder"]
    assert a["need"] < o["need"] < b["need"]
    assert a["conquest_gap"] < o["conquest_gap"] < b["conquest_gap"]
    assert a["war_at_x"] < o["war_at_x"] < b["war_at_x"]
    for name in ef:
        st_ = econ.style({"persona": {"name": name}})
        assert st_["missions"] <= ws[name]["missions"] and st_["need"] > ws[name]["need"]
        assert st_["post"] <= ws[name]["post"] and st_["spies"] <= ws[name]["spies"]
        assert st_["spy_share"] <= ws[name]["spy_share"]


# ---- A-07: spies ----------------------------------------------------------------------------

def test_spies_are_built_and_sent_against_a_war_target():
    st = make_state()
    contact(st, 1, NPR_ID, "W")
    st.empires[NPR_ID].techs |= {3, 14}
    st.turn = 20
    h3 = sysn(st, "H3")
    h3.pop, h3.infra = 10.0, 10
    w = _w(st, persona="opportunist")
    plan = Plan(w)
    spycraft.plan_spies(w, plan, war.threats(w))
    assert [o for o in plan.orders if o.code == "BT" and o.artifact == "S"]
    assert not _validate(st, NPR_ID, plan.orders)
    # a spy at home goes to the enemy; one at the enemy world scouts it, then stirs it up
    h1, h3 = sysn(st, "H1"), sysn(st, "H3")
    st.spies[1] = Spy(1, NPR_ID, h3.id)
    w = _w(st, persona="opportunist")
    plan = Plan(w)
    spycraft.plan_spies(w, plan, war.threats(w))
    assert any(o.code == "SMV" and o.system == "H1" for o in plan.orders)
    st.spies[1].system = h1.id
    w = _w(st, persona="opportunist")
    plan = Plan(w)
    spycraft.plan_spies(w, plan, war.threats(w))
    assert any(o.code == "SOS" for o in plan.orders)
    w.mem["intel"][str(h1.id)] = {"t": st.turn, "owner": 1, "pop": 6, "hab": 3, "mr": False,
                                  "ar": False, "starport": 2, "status": "Norm", "weapons": [],
                                  "artifacts": 0, "troops": []}
    w = _w(st, persona="opportunist")
    plan = Plan(w)
    spycraft.plan_spies(w, plan, war.threats(w))
    assert any(o.code == "SUP" for o in plan.orders)
    assert not _validate(st, NPR_ID, plan.orders)


def test_sot_reports_are_read_back():
    assert spycraft.parse_techs("Spy 4 at X:\n\tTechnologies of the R1: Powered Armor, "
                                "Missile Technology.") == {0, 1, 6}
    assert spycraft.parse_techs("The spy failed to get the technology report.") is None


# ---- A-07: tech trades between computer empires ---------------------------------------------

def test_two_computer_empires_agree_and_trade_a_technology():
    st = make_state(n_humans=1, npr=2)                  # 2 and 3 are computer empires
    contact(st, 2, 3)
    st.turn = 12
    common = {1, 7, 8, 13, 17}
    st.empires[2].techs |= common | {18}                # High Energy Physics, 500 EU
    st.empires[3].techs |= common | {20}                # Improved Solar Collectors I, 500 EU
    for eid in (2, 3):
        st.empires[eid].eu = 500                        # neither can buy the other's yet
    for eid, other in ((2, 3), (3, 2)):
        mem = memory(st, eid)
        mem["persona"] = dict(PERSONAS["builder"], name="builder")
        mem["races"][str(other)] = {"griev": 0.0, "good": 6.0, "met": 1, "warned": -1,
                                    "intrude": 0, "peace_req": -1, "ally_req": -1,
                                    "war_since": -1, "last_fight": -1, "peace_offer": -1,
                                    "why": []}
        mem["last_offer"] = 99 if eid == 3 else -99     # only 2 offers
        s = sysn(st, f"H{eid}")
        s.pop, s.infra = 10.0, 10
    res = initial_results(st)
    traded = None
    for _ in range(6):
        st.empires[2].eu = max(st.empires[2].eu, 400)   # income enough to pay its half
        res = run_turn(st, {1: []})
        for eid in (2, 3):
            for o in res.report(eid).orders:
                if o.code == "TTNPR":
                    assert o.ok, o.error
                    traded = st.turn
        if traded:
            break
    assert traded is not None
    assert 20 in st.empires[2].techs and 18 in st.empires[3].techs
    assert trade.swap_for is not None


def test_no_trade_with_the_leader_or_at_war():
    st = make_state(n_humans=1, npr=2)
    contact(st, 2, 3)
    st.empires[2].techs |= {3}
    w = _w(st, eid=3, persona="builder")
    w.races[2]["kind"] = "npr"
    assert trade.swap_for(w, 2, [3], [1]) is None       # we don't own what they want
    st.empires[3].techs |= {1}
    w = _w(st, eid=3, persona="builder")
    assert trade.swap_for(w, 2, [3], [1]) == (1, 3)
    st.empires[3].relations[2] = "W"
    w = _w(st, eid=3, persona="builder")
    assert trade.swap_for(w, 2, [3], [1]) is None


# ---- still no hidden information, later in the game (spies, trades, missions active) --------

def test_ramped_bots_still_decide_only_from_their_own_view():
    st = new_game("fog2", 31, ["Hum"], size=8)
    for _ in range(36):
        run_turn(st, {1: []})
    st.turn += 1
    checked = 0
    for eid in [e.id for e in st.empires.values() if e.kind == "npr"][:4]:
        a, b = M.loads(M.dumps(st)), M.loads(M.dumps(st))
        _scramble(b, eid, random.Random(eid))
        oa = [o.line for o in npr_orders(a, eid)]
        ob = [o.line for o in npr_orders(b, eid)]
        assert oa == ob and oa
        assert json.dumps(a.npr_state[eid], sort_keys=True) == \
            json.dumps(b.npr_state[eid], sort_keys=True)
        checked += 1
    assert checked == 4
    _ = Rng
