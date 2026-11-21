"""Forming a fleet and moving it in the same turn (the browser's "Make fleet", 2026-11-16).

Orders run in the draft's order, before movement (turn phase 1, then 6-7).  CF creates the fleet
at once and AF adds ships at once, so a following MF moves the new fleet that same turn.  CFXY
only collects the unfleeted ships after movement (movement.add_fleet_xy), so a fleet created by
CFXY has no ships while fleets move: an MF given to it the same turn takes effect next turn."""
from mhgc.engine.turn import check_orders, run_turn
from mhgc.model import MOVE, STAND
from mhgc.orders import parse_line
from tests.conftest import add_ship, make_state

# empire 1's home H1 is at (10, 10) absolute = relative (50, 50); y up, so relative (56, 50) is
# absolute (16, 10)


def _orders(*lines):
    return [parse_line(x) for x in lines]


def _quiet():
    st = make_state(n_humans=2, npr=0)
    ships = [add_ship(st, 1, t, 10, 10) for t in ("F", "F", "S")]
    return st, ships


def test_cf_af_then_mf_moves_the_new_fleet_this_turn():
    st, ships = _quiet()
    nums = " ".join(str(s.number) for s in ships)
    run_turn(st, {1: _orders("CF Hunters 50 50", f"AF Hunters {nums}", "MF Hunters 56 50")},
             npr_fn=None)
    f = st.fleet_named("Hunters")
    assert f is not None and f.owner == 1
    assert {s.fleet for s in ships} == {f.number}
    # automatic speed = the slowest ship (frigate, move 4)
    slowest = min(s.stype.move for s in ships)
    assert (f.x, f.y) == (10 + slowest, 10)
    assert all((s.x, s.y) == (f.x, f.y) for s in ships)
    assert f.order == MOVE and (f.dx, f.dy) == (16, 10)


def test_the_order_checker_accepts_the_sequence():
    st, ships = _quiet()
    nums = " ".join(str(s.number) for s in ships)
    res = check_orders(st, 1, _orders("CF Hunters 50 50", f"AF Hunters {nums}", "MF Hunters 56 50"))
    assert [r.ok for r in res] == [True, True, True]
    # nothing changed in the real state
    assert st.fleet_named("Hunters") is None and all(s.fleet is None for s in ships)


def test_mf_before_cf_fails():
    st, ships = _quiet()
    res = check_orders(st, 1, _orders("MF Hunters 56 50", "CF Hunters 50 50",
                                      f"AF Hunters {ships[0].number}"))
    assert [r.ok for r in res] == [False, True, True]
    assert "don't have a fleet called Hunters" in res[0].error


def test_cfxy_fleet_forms_after_movement_and_moves_next_turn():
    st, ships = _quiet()
    run_turn(st, {1: _orders("CFXY Late 50 50", "MF Late 56 50")}, npr_fn=None)
    f = st.fleet_named("Late")
    assert {s.fleet for s in ships} == {f.number}
    assert (f.x, f.y) == (10, 10) and all((s.x, s.y) == (10, 10) for s in ships)
    assert f.order == MOVE                       # the move order stands ...
    run_turn(st, {}, npr_fn=None)
    assert (f.x, f.y) == (14, 10)                # ... and is carried out next turn


def test_a_ship_move_order_is_overridden_by_joining_the_fleet():
    st, ships = _quiet()
    nums = " ".join(str(s.number) for s in ships)
    run_turn(st, {1: _orders(f"MO {ships[2].number} 50 56", "CF Hunters 50 50",
                             f"AF Hunters {nums}")}, npr_fn=None)
    f = st.fleet_named("Hunters")
    # the fleet has no move order, so the scout stays with it
    assert f.order == STAND and all((s.x, s.y) == (10, 10) for s in ships)
