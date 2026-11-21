"""Static artifact repricing (Dave 2026-11-19, DECISIONS G-24) and the bot's farcasters and
warp tunnels (mhgc/npr/portals.py).

Prices: the new IU/EU/upkeep table; tech 42 and Warp Tunnel at 2000; the TTNPR ANY cost list
unchanged; prerequisites and crash research unaffected by Warp Tunnel now costing less than its
prerequisites; BT charges the new price (doubled under attack) and the ledger shows it; built
artifacts survive and pay the new upkeep (CS 4) from the next turn.  Bot: builds FP/WT at home
and a far front only, farcasts spare troops and warps ships with orders the engine accepts, and
decides from its own view.
"""
from __future__ import annotations

import json
import random


from mhgc import model as M
from mhgc.data import constants as K
from mhgc.data.artifacts import ARTIFACTS
from mhgc.data.techs import TECHS, all_prereqs, tech_vp
from mhgc.engine.turn import run_turn
from mhgc.model import System
from mhgc.npr import npr_orders, portals, war
from mhgc.npr.plan import Plan
from mhgc.orders import any_costs, parse_orders
from tests.conftest import add_ship, add_troop, contact, ctx_for, do, make_state, sysn
from tests.test_npr_units import NPR_ID, _scramble, _validate, _w

NEW = {   # key: (IU, EU, upkeep EU)
    "CB": (100, 100, 0), "VRB": (150, 150, 0), "BF": (100, 0, 0), "AF": (75, 75, 3),
    "CM": (150, 150, 0), "AL": (150, 150, 0), "EHC": (75, 0, 2), "CS": (100, 100, 4),
    "FP": (50, 50, 0), "WT": (75, 75, 0),
    # unchanged
    "EUS": (100, 0, 3), "PD": (25, 25, 3), "SW": (50, 50, 5), "APD": (100, 100, 5),
    "ESS": (30, 30, 2), "EESS": (30, 30, 2),
}


def test_artifact_table():
    assert set(NEW) == set(ARTIFACTS)
    for k, v in NEW.items():
        a = ARTIFACTS[k]
        assert (a.iu_cost, a.eu_cost, a.maint_eu) == v, k


def test_tech_costs_vp_and_any_list():
    assert TECHS[32].cost == 1000                        # Farcaster Portal unchanged
    assert TECHS[42].cost == 2000 and TECHS[50].cost == 2000
    assert TECHS[42].tier == TECHS[50].tier == 2000     # the Research tab groups them at 2000
    assert tech_vp(42) == 2 and tech_vp(50) == 2        # WT was 3 VP at 4000
    assert any_costs() == [100, 250, 500, 1000, 2000, 3000, 4000]   # G-23 list unchanged
    assert [t for t in TECHS if TECHS[t].cost == 4000] == [49]


def test_warp_tunnel_still_needs_its_prerequisites_and_crash_is_double():
    st = make_state()
    ctx = ctx_for(st)
    e = st.empires[1]
    e.eu = 10000
    r = do(ctx, 1, "PT 50")
    assert not r.ok and "Warp Tunnel needs" in r.error      # cheaper than its prerequisites
    e.techs |= all_prereqs(50) - {43}
    assert "Warp Tunnel needs Alchemy" in do(ctx, 1, "CRP 50").error
    e.techs.add(43)
    assert do(ctx, 1, "CRP 50").ok
    assert e.eu == 10000 - 2 * 2000
    assert do(ctx, 1, "PT 42").ok and e.eu == 6000 - 2000


def test_bt_charges_the_new_prices_and_doubles_under_attack():
    st = make_state()
    ctx = ctx_for(st)
    e = st.empires[1]
    e.techs |= {11, 32}
    h = sysn(st, "H1")
    eu0, iu0 = e.eu, h.iu
    assert do(ctx, 1, "BT H1 CB").ok
    assert (eu0 - e.eu, iu0 - h.iu) == (100, 100)
    h.status = K.UNDER_ATTACK
    assert do(ctx, 1, "BT H1 FP").ok
    assert (eu0 - e.eu, iu0 - h.iu) == (100 + 100, 100 + 100)


def test_bt_ledger_shows_the_new_price():
    st = make_state()
    st.empires[1].techs |= {11}
    res = run_turn(st, {1: parse_orders("BT H1 CB")}, npr_fn=None)
    assert all(o.ok for o in res.report(1).orders)
    led = res.report(1).maintenance
    buy = [ln for ln in led if ln["kind"] == "purchases"]
    assert sum(ln["eu"] for ln in buy) == -100
    assert sum(ln.get("system_iu", 0) for ln in buy) == -100


def test_old_save_keeps_its_artifacts_and_pays_cs_upkeep_4():
    st = make_state()
    h = sysn(st, "H1")
    h.artifacts |= {"CS", "CB", "WT"}                    # built under the old prices
    st2 = M.loads(M.dumps(st))                           # an old save loads as it is
    assert sysn(st2, "H1").artifacts == {"CS", "CB", "WT"}
    res = run_turn(st2, {1: []}, npr_fn=None)
    up = [ln for ln in res.report(1).maintenance if ln["kind"] == "artifact"]
    assert [(ln.get("artifact"), ln["eu"]) for ln in up] == [("CS", -4)]
    assert sysn(st2, "H1").artifacts == {"CS", "CB", "WT"}


# ---- the bot ---------------------------------------------------------------------------------

def _front_state(portals_built=False, war_with=2):
    """NPR 3 (at war with R2 unless `war_with` is None): home H3 (30, 30) and a colony F3 15
    squares away near R2's X2."""
    st = make_state()
    e = st.empires[NPR_ID]
    e.eu = 5000
    e.techs |= {32, 50}
    h = sysn(st, "H3")
    h.pop, h.infra, h.iu, h.starport, h.happy = 9.0, 9, 3000, 3, 0.8
    f = System(len(st.systems), "F3", 30, 45, owner=NPR_ID, pop=5.0, happy=0.8, hab=3, infra=5,
               iu=800, starport=1)
    x = System(len(st.systems) + 1, "X2", 30, 52, owner=2, pop=4.0, happy=0.5, hab=3, iu=10)
    st.systems += [f, x]
    for s in (f, x):
        for em in st.empires.values():
            em.seen_systems[s.id] = {"turn": 0, "name": s.name, "owner": s.owner}
    contact(st, NPR_ID, 2, "W" if war_with else "N")
    if portals_built:
        h.artifacts |= {"FP", "WT"}
        f.artifacts |= {"FP", "WT"}
    return st, h, f


def test_bot_builds_fp_and_wt_at_home_and_the_far_front():
    st, h, f = _front_state()
    st.turn += 1
    orders = npr_orders(st, NPR_ID)
    bt = {o.to_text() for o in orders if o.code == "BT"}
    assert {"BT H3 FP", "BT F3 FP", "BT H3 WT", "BT F3 WT"} <= bt
    assert not _validate(st, NPR_ID, orders)


def test_no_portals_without_a_far_front():
    st, h, f = _front_state()
    f.x, f.y = 30, 36                                    # 6 squares from home
    st.turn += 1
    bt = {o.to_text() for o in npr_orders(st, NPR_ID) if o.code == "BT"}
    assert not {x for x in bt if x.endswith((" FP", " WT"))}


def test_farcast_spare_troops_to_the_stage_and_to_a_threatened_system():
    st, h, f = _front_state(portals_built=True)
    for n in (701, 702, 703):
        add_troop(st, NPR_ID, "C", system=h.id, posture="A", number=n)      # spare attackers
    for n in (711, 712, 713):
        add_troop(st, NPR_ID, "S", system=h.id, posture="E", number=n)      # the dug-in guard
    w = _w(st)
    plan = Plan(w)
    thr = war.threats(w)
    wf = next(s for s in w.systems if s.name == "F3")
    sent = portals.troops_to_stage(w, plan, wf, 5, thr)
    assert sent == 3
    assert [o.to_text() for o in plan.orders] == [f"TP H3 C {n} F3" for n in (701, 702, 703)]
    assert plan.eu == w.eu - 15
    assert not _validate(st, NPR_ID, plan.orders)
    assert all(st.troops[n].system == f.id for n in (701, 702, 703))
    assert all(st.troops[n].system == h.id for n in (711, 712, 713))   # the guard stays
    # defence: a threatened portal system gets the spare troops
    st, h, f = _front_state(portals_built=True)
    add_troop(st, NPR_ID, "C", system=h.id, posture="A", number=701)
    for n in (711, 712, 713):
        add_troop(st, NPR_ID, "S", system=h.id, posture="E", number=n)
    w = _w(st)
    plan = Plan(w)
    thr = war.threats(w)
    wf = next(s for s in w.systems if s.name == "F3")
    thr[wf.id] = {"attack": 10.0, "carriers": 1}
    portals.defence(w, plan, thr)
    assert [o.to_text() for o in plan.orders] == ["TP H3 C 701 F3"]
    assert not _validate(st, NPR_ID, plan.orders)


def test_warp_ships_through_the_tunnel():
    st, h, f = _front_state(portals_built=True)
    add_ship(st, NPR_ID, "D", h.x, h.y, number=801)
    w = _w(st)
    plan = Plan(w)
    sh = next(x for x in w.ships if x.number == 801)
    wf = next(s for s in w.systems if s.name == "F3")
    assert portals.worth_warping(sh, wf) and portals.can_warp(w, plan, sh, wf)
    assert portals.warp(w, plan, sh, wf, "warp to the war fleet")
    assert [o.to_text() for o in plan.orders] == ["WTP 801 F3"]
    assert not _validate(st, NPR_ID, plan.orders)
    assert (st.ships[801].x, st.ships[801].y) == (f.x, f.y)
    assert not portals.can_warp(w, plan, sh, wf)             # once a turn, and it's there now


def test_defence_warps_spare_warships_to_a_short_tunnel_system():
    st, h, f = _front_state(portals_built=True, war_with=None)    # (no war fleet takes them)
    for n in range(801, 806):
        add_ship(st, NPR_ID, "D", h.x, h.y, number=n)          # more than home needs
    st.turn = 40                                               # garrison floors are higher
    st.turn += 1
    orders = npr_orders(st, NPR_ID)
    wtp = [o for o in orders if o.code == "WTP"]
    assert wtp and all(o.system == "F3" for o in wtp)
    assert not _validate(st, NPR_ID, orders)


def test_portal_orders_depend_only_on_what_the_empire_can_see():
    st, h, f = _front_state(portals_built=True, war_with=None)
    for n in (701, 702):
        add_troop(st, NPR_ID, "C", system=h.id, posture="A", number=n)
    for n in range(801, 806):
        add_ship(st, NPR_ID, "D", h.x, h.y, number=n)
    st.turn = 41
    a, b = M.loads(M.dumps(st)), M.loads(M.dumps(st))
    _scramble(b, NPR_ID, random.Random(5))
    oa = [o.line for o in npr_orders(a, NPR_ID)]
    ob = [o.line for o in npr_orders(b, NPR_ID)]
    assert oa == ob and any(o.startswith("WTP") for o in oa)
    assert json.dumps(a.npr_state[NPR_ID], sort_keys=True) == \
        json.dumps(b.npr_state[NPR_ID], sort_keys=True)
