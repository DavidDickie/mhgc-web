"""Maintenance (rules:479-486, 611-617, chart 3063) and movement (rules:557-561, 854-882,
2126-2179)."""
import pytest

from mhgc.data import constants as K
from mhgc.engine import maintenance, movement
from mhgc.model import GUARD, INTERCEPT, MOVE, STAND
from tests.conftest import (ScriptedRng, add_leader, add_ship, add_troop, ctx_for, do,
                            make_state, sysn)


def _maint(st, rng=None):
    ctx = ctx_for(st, rng)
    maintenance.maintenance(ctx)
    return ctx


# ---- maintenance -------------------------------------------------------------------------

def test_ship_maintenance_by_distance():
    st = make_state()
    e = st.empires[1]
    at_home = add_ship(st, 1, "F", 10, 10)
    near = add_ship(st, 1, "F", 20, 10)            # 10 away from H1, move 4: within 4 turns
    far = add_ship(st, 1, "F", 10, 40)             # 30 away from any of empire 1's systems
    scout = add_ship(st, 1, "S", 10, 40)
    iu0, eu0 = e.iu_depot, e.eu
    _maint(st)
    # 2/2 at own system, 5/5 normal, 10/5 far, scouts never pay the far IU rate
    assert e.iu_depot == iu0 - (2 + 5 + 10 + 5)
    assert e.eu == eu0 - (2 + 5 + 5 + 5)


def test_ship_demobilized_without_funds():
    st = make_state()
    e = st.empires[1]
    e.eu = 3
    sh = add_ship(st, 1, "F", 30, 60)
    ctx = _maint(st)
    assert not sh.alive and ctx.res.events_of(1, "ship_demobilized")


def test_autosisd_takes_only_the_shortfall():
    st = make_state()
    e = st.empires[1]
    e.iu_depot = 1
    add_ship(st, 1, "F", 20, 10)                    # costs 5 IU
    s = sysn(st, "H1")
    _maint(st)
    assert e.iu_depot == 0 and s.iu == 500 - 4
    e.autosisd = False
    e.iu_depot = 0
    sh = add_ship(st, 1, "F", 20, 10)
    _maint(st)
    assert not sh.alive


def test_npr_pays_full_maintenance():
    # DECISIONS A-01 (Dave 2026-11-12): no NPR maintenance discount (rules:256-257 overridden)
    st = make_state()
    e = st.empires[3]                               # NPR
    add_ship(st, 3, "F", 31, 31)                    # 1 from home: 5/5
    add_troop(st, 3, "C", system=sysn(st, "H3").id)     # 5
    iu0, eu0 = e.iu_depot, e.eu
    _maint(st)
    assert e.iu_depot == iu0 - 5 and e.eu == eu0 - 5 - 5


def test_ct_and_spy_maintenance():
    st = make_state()
    e = st.empires[1]
    s = sysn(st, "H1")
    add_troop(st, 1, "M", system=s.id)
    add_troop(st, 1, "S", system=s.id)
    add_troop(st, 1, "C", system=s.id)
    from mhgc.model import Spy
    st.spies[5] = Spy(5, 1, s.id)
    eu0 = e.eu
    _maint(st)
    assert e.eu == eu0 - (2 + 2 + 5) - 5


def test_independents_pay_nothing():
    st = make_state()
    s = sysn(st, "E1")
    t = add_troop(st, 0, "M", system=s.id)
    _maint(st)
    assert t.alive


def test_artifact_maintenance_and_loss():
    st = make_state()
    s = sysn(st, "H1")
    s.artifacts |= {"EHC", "PD", "BF"}
    e = st.empires[1]
    e.eu = 4
    ctx = _maint(st)
    assert "EHC" in s.artifacts and "PD" not in s.artifacts and "BF" in s.artifacts
    assert ctx.res.events_of(1, "artifact_lost")


def test_sisd_and_trade_credit():
    st = make_state()
    ctx = ctx_for(st)
    do(ctx, 1, "SISD H1 600")
    ctx.trade_eu[1] = 7
    e = st.empires[1]
    eu0, d0 = e.eu, e.iu_depot
    maintenance.maintenance(ctx)
    assert e.iu_depot == d0 + 500 and sysn(st, "H1").iu == 0     # clamped to the stockpile
    assert e.eu == eu0 + 7


def test_militia_cap_and_entrenchment():
    st = make_state()
    s = sysn(st, "H1")
    s.pop = 2.5
    mil = [add_troop(st, 1, "M", system=s.id) for _ in range(3)]
    dig = add_troop(st, 1, "S", system=s.id, posture="E3")
    _maint(st)
    assert sum(t.alive for t in mil) == 2
    assert dig.posture == "E2"
    _maint(st)
    _maint(st)
    assert dig.posture == "E"


# ---- movement ----------------------------------------------------------------------------

def test_ship_moves_at_its_speed_with_wrap():
    st = make_state()
    sh = add_ship(st, 1, "S", 1, 1, order=MOVE)
    sh.dx, sh.dy = 95, 3
    ctx = ctx_for(st)
    movement.move_ships(ctx)
    assert (sh.x, sh.y) == (97, 3) and sh.order == MOVE
    movement.move_ships(ctx)
    assert (sh.x, sh.y) == (95, 3) and sh.order == STAND


def test_fleet_moves_at_slowest_and_set_speed():
    # rules:877-882
    st = make_state()
    ctx = ctx_for(st)
    fast = add_ship(st, 1, "FF", 10, 10)            # move 5
    slow = add_ship(st, 1, "PA", 10, 10)            # move 2
    do(ctx, 1, "CF Task 50 50")
    do(ctx, 1, f"AF Task {fast.number} {slow.number}")
    do(ctx, 1, "MF Task 60 50")                     # relative: 10 squares east
    f = st.fleet_named("Task")
    movement.move_fleets(ctx)
    movement.move_ships(ctx)
    assert (f.x, f.y) == (12, 10) and (fast.x, slow.x) == (12, 12)
    do(ctx, 1, "FS Task 5")
    movement.move_fleets(ctx)
    movement.move_ships(ctx)
    assert f.x == 17 and fast.x == 17 and slow.x == 14     # slower ship left behind
    movement.move_fleets(ctx)                        # body is now just the fast ship
    movement.move_ships(ctx)
    assert f.x == 20 and slow.x == 16 and f.order == STAND


def test_intercept_reaches_and_chains():
    st = make_state()
    target = add_ship(st, 2, "S", 40, 40)
    a = add_ship(st, 1, "F", 36, 40, order=INTERCEPT, target=target.number)
    b = add_ship(st, 1, "F", 32, 40, order=INTERCEPT, target=a.number)
    ctx = ctx_for(st)
    movement.intercept(ctx)
    assert (a.x, a.y) == (40, 40)
    assert (b.x, b.y) == (36, 40)                    # chases a's new square, limited by move 4


def test_intercept_circle_converges():
    st = make_state()
    a = add_ship(st, 1, "F", 40, 40)
    b = add_ship(st, 2, "F", 44, 40, order=INTERCEPT, target=a.number)
    a.order, a.target = INTERCEPT, b.number
    ctx = ctx_for(st)
    movement.intercept(ctx)
    assert (a.x, a.y) == (b.x, b.y)


def test_intercept_lost_target_stands():
    st = make_state()
    a = add_ship(st, 1, "F", 40, 40, order=INTERCEPT, target=999)
    movement.intercept(ctx_for(st))
    assert a.order == STAND


def test_guard_moves_to_closest_enemy_not_allies():
    # rules:2171-2177
    st = make_state()
    g = add_ship(st, 1, "F", 40, 40, order=GUARD)
    ally = add_ship(st, 2, "S", 41, 40)
    st.empires[1].relations[2] = "A"
    enemy = add_ship(st, 3, "S", 43, 43)
    add_ship(st, 3, "S", 45, 45)                     # out of range (move 4)
    movement.guard(ctx_for(st))
    assert (g.x, g.y) == (43, 43) and g.order == GUARD


def test_afxy_adds_ships_after_movement():
    st = make_state()
    ctx = ctx_for(st)
    do(ctx, 1, "CFXY Grp 50 50")                     # relative 50,50 = home (10,10)
    sh = add_ship(st, 1, "T", 10, 10)
    movement.add_fleet_xy(ctx)
    assert sh.fleet == st.fleet_named("Grp").number


def test_drop_pods_burn_chance():
    # rules:599-603: 30% base, more with PD/SW/APD
    st = make_state()
    s2 = sysn(st, "H2")
    s2.artifacts |= {"PD", "SW"}
    sh = add_ship(st, 1, "T", s2.x, s2.y, drop=True)
    t1 = add_troop(st, 1, "S", ship=sh.number)
    t2 = add_troop(st, 1, "S", ship=sh.number)
    rng = ScriptedRng(script=[True, False])
    movement.combat_drops(ctx_for(st, rng))
    assert rng.calls == [60, 60]
    assert not t1.alive and t2.system == s2.id and sh.posture == "H"


def test_drop_on_unowned_captures():
    st = make_state()
    e1 = sysn(st, "E1")
    sh = add_ship(st, 1, "T", e1.x, e1.y, drop=True)
    add_troop(st, 1, "S", ship=sh.number)
    ctx = ctx_for(st, ScriptedRng(chance=False))
    movement.combat_drops(ctx)
    assert e1.owner == 1 and st.empires[1].systems_captured == e1.hab // 4


def test_leader_arrives_on_third_turn():
    # rules:2252 "in transit for two turns, arrives third turn"
    st = make_state()
    ld = add_leader(st, 1)
    ctx = ctx_for(st)
    do(ctx, 1, f"ML {ld.name} H1")
    movement.leader_moves(ctx)                       # end of order turn
    assert ld.status == "transit"
    movement.leader_moves(ctx)                       # end of next turn
    assert ld.status == "posted" and ld.system == sysn(st, "H1").id


def test_leader_evicted_when_system_changes_hands():
    st = make_state()
    s = sysn(st, "H1")
    ld = add_leader(st, 1, system=s.id)
    s.owner = 2
    movement.leader_moves(ctx_for(st))
    assert ld.status == "limbo" and ld.system is None
