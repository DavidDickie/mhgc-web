"""Behaviour taken from the C engine where the rules are silent.  Each test cites the C source
(pristine files in ~/mhgc/work/c-ref/orig/, = ~/mhgc/c/mhgc_c/)."""
import pytest

from mhgc.data import constants as K
from mhgc.engine import economy, events, leaders, maintenance, movement
from mhgc.engine.turn import run_orders
from mhgc.orders import parse_line
from tests.conftest import (ScriptedRng, add_leader, add_ship, add_troop, contact, ctx_for, do,
                            make_state, sysn)


def test_npr_has_no_production_bonus_or_isnpr_income():
    # Dave 2026-11-12 (DECISIONS A-01): computer empires play under exactly the human rules.
    # The C gave leaderless small NPR systems 0.8 (gcrun.c:435) and +50*(turn/6+1) EU (ISNPR).
    st = make_state()
    s = sysn(st, "H3")
    s.starport = 0
    ctx = ctx_for(st)
    economy.produce(ctx)
    assert ctx.econ[s.id].prod_au == int(4 * 5 * 1.0 * 0.5)
    st = make_state()
    eu = st.empires[3].eu
    run_orders(ctx_for(st), {})
    assert st.empires[3].eu == eu and st.empires[1].eu == 1000


def test_uprising_outcome_split():
    # gcrun.c:596-643: militia, else sabotage 40%, else arson 60%, else charismatic leader
    st = make_state()
    s = sysn(st, "H1")
    s.happy, s.au, s.infra = 0.1, 0, 3
    ctx = ctx_for(st, ScriptedRng(script=[True, False, True]))
    economy.happiness(ctx)
    assert s.infra == 2
    st = make_state()
    s = sysn(st, "H1")
    s.happy, s.au, s.iu = 0.1, 0, 101
    ctx = ctx_for(st, ScriptedRng(script=[True, False, False, True]))
    economy.happiness(ctx)
    assert s.iu == 50


def test_emperor_day_eu_bonus_formula():
    # gcrun.c:676-685: y = (r%10 + 1) * prod / 10 + 1
    st = make_state()
    s = sysn(st, "H1")
    s.happy, s.au = 1.6, 300
    ctx = ctx_for(st, ScriptedRng(script=[True, False, False, True], below=[4]))
    ctx.econ[s.id].prod_eu = 20
    eu = st.empires[1].eu
    economy.happiness(ctx)
    assert st.empires[1].eu == eu + int(5 * 20 / 10.0 + 1)


def test_immigration_formula():
    # gcparse1.c:1080-1081: h = pop^2 * n / ((hab + EHC + 3*CS) * 150)
    st = make_state()
    s = sysn(st, "H1")
    s.artifacts = {"EHC", "CS"}
    s.happy = 0.9
    sh = add_ship(st, 1, "T", s.x, s.y, cargo_pop=2)
    ctx = ctx_for(st)
    assert do(ctx, 1, f"U {sh.number} P 2").ok
    assert s.happy == pytest.approx(0.9 - 16 * 2 / ((3 + 1 + 3) * 150.0))


def test_spy_travel_time():
    # gcparse1.c:1289: transit = (int)(distance/6 + 0.5), minimum 1
    st = make_state()
    st.empires[1].techs.add(14)
    ctx = ctx_for(st)
    assert do(ctx, 1, "BT H1 S").ok
    sp = next(iter(st.spies.values()))
    contact(st, 1, 3)
    assert do(ctx, 1, f"SMV {sp.number} H3").ok
    assert sp.transit == int(20 / 6.0 + 0.5)


def test_smo_to_empty_square_silently_loses_a_turn():
    # gcparse1.c:1273-1293
    st = make_state()
    from mhgc.model import Spy
    st.spies[1] = Spy(1, 1, 0)
    ctx = ctx_for(st)
    r = do(ctx, 1, "SMO 1 77 77")
    assert r.ok and st.spies[1].mission == "SMO_FAIL" and st.spies[1].transit == 1


def test_guard_ignores_ships_beyond_its_move():
    # gcrun.c:1541-1564 (distance <= own move)
    st = make_state()
    g = add_ship(st, 1, "PA", 40, 40, order="GUARD")      # move 2
    add_ship(st, 2, "S", 43, 40)
    movement.guard(ctx_for(st))
    assert (g.x, g.y) == (40, 40)


def test_intercepting_fleet_follows_fastest_member():
    # gcrun.c:956-970
    st = make_state()
    tgt = add_ship(st, 2, "S", 60, 60)
    ctx = ctx_for(st)
    a = add_ship(st, 1, "FF", 52, 52)
    b = add_ship(st, 1, "PA", 52, 52)
    assert do(ctx, 1, "CF Hunt 50 50").ok
    f = st.fleet_named("Hunt")
    f.x = f.y = 52
    assert do(ctx, 1, f"AF Hunt {a.number} {b.number}").ok
    assert do(ctx, 1, f"FIS Hunt {tgt.number}").ok
    movement.intercept(ctx)
    assert (f.x, f.y) == (a.x, a.y) == (57, 57)


def test_random_event_schedule():
    # gcrandom.c:148-155: no plague before turn 11; 40% x1 in 11-20; 4 per round after
    st = make_state()
    st.turn = 25
    calls = []
    orig = events.plague
    events.plague = lambda ctx, s: calls.append(s.id)
    try:
        events._other_events(ctx_for(st), set())
    finally:
        events.plague = orig
    assert len(calls) == 4


def test_leader_finding_quota():
    # gcleader.c:25-48: quota 2 + turn/10, chance 15 + 10*deficit %
    st = make_state()
    st.turn = 12
    rng = ScriptedRng()
    rng.pct = lambda: 0
    ctx = ctx_for(st, rng)
    leaders.leader_events(ctx)
    for e in (1, 2, 3):
        assert sum(1 for ld in st.leaders.values() if ld.owner == e) == 1


def test_ship_far_maintenance_scale():
    # gcmaint.c:201-220: far = distance > 4 x move to the nearest owned system
    st = make_state()
    e = st.empires[1]
    sh = add_ship(st, 1, "PA", 19, 10)              # move 2: 9 away > 8
    d0 = e.iu_depot
    maintenance.maintenance(ctx_for(st))
    assert e.iu_depot == d0 - 10


def test_digging_troops_reset_when_attacked():
    # gccombat.c:1866-1887
    from mhgc.engine.combat import Combat
    st = make_state()
    s2 = sysn(st, "H2")
    add_troop(st, 1, "O", system=s2.id)
    d = add_troop(st, 2, "S", system=s2.id, posture="E2")
    rng = ScriptedRng(chance=False)
    rng.between = lambda lo, hi: 1
    rng.random = lambda: 0.99
    ctx = ctx_for(st, rng)
    c = Combat(ctx, s2.x, s2.y, s2)
    c._rel = {}
    c.ground_combat()
    assert d.posture == "A"


def test_tech_capture_pool():
    # gcutils.c:286-303: one of the old owner's 6 highest-numbered techs
    from mhgc.engine import combat
    st = make_state()
    st.empires[2].techs |= set(range(1, 21))
    ctx = ctx_for(st)
    combat.change_owner(ctx, sysn(st, "H2"), 1, "capture")
    got = st.empires[1].techs - {0}
    assert len(got) == 1 and got <= set(range(15, 21))
