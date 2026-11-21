"""Merge fleets, MGF <fleet> <into> (Dave 2026-11-21, DECISIONS G-27; a new game order).

Every ship of the first fleet joins the second as AF would add it, then the first is disbanded
as DF would (its name is free at once).  Both must be yours, at the same square.  Like AF/LF/CF/DF
the change takes effect at once, so the merged fleet moves this turn with the second fleet's
orders.  Ships of the first fleet away from its main body head for the second fleet (the AF
"main body" rule).

Empire 1's home H1 is at (10, 10) absolute = relative (50, 50); relative (56, 50) is (16, 10)."""
import pytest

from mhgc.engine.turn import check_orders, run_turn
from mhgc.model import INTERCEPT, Fleet
from mhgc.orders import OrderSyntaxError, parse_line, parse_orders
from tests.conftest import add_leader, add_ship, ctx_for, do, make_state


def _fleet(st, num, name, x, y, ships, owner=1, **kw):
    f = Fleet(num, owner, name, x, y, dx=x, dy=y, ox=x, oy=y, **kw)
    st.fleets[num] = f
    for sh in ships:
        sh.fleet = num
    return f


def _two():
    """Main (2 frigates) and Wing (a frigate and a scout) at home H1, both empire 1's."""
    st = make_state(n_humans=2, npr=0)
    main_ships = [add_ship(st, 1, "F", 10, 10) for _ in range(2)]
    wing_ships = [add_ship(st, 1, "F", 10, 10), add_ship(st, 1, "S", 10, 10)]
    main = _fleet(st, 501, "Main", 10, 10, main_ships, posture="H", role="SC", speed=2)
    wing = _fleet(st, 502, "Wing", 10, 10, wing_ships, posture="N", role="MR")
    return st, main, wing, main_ships, wing_ships


def test_merge_moves_every_ship_and_disbands_the_first_fleet():
    st, main, wing, ms, ws = _two()
    ctx = ctx_for(st)
    r = do(ctx, 1, "MGF Wing Main")
    assert r.ok, r.error
    assert all(s.fleet == main.number for s in ms + ws)
    assert not wing.alive and st.fleet_named("Wing", 1) is None
    # the target keeps its name, posture, role and speed; joining ships take its posture/role
    assert (main.name, main.posture, main.role, main.speed) == ("Main", "H", "SC", 2)
    assert all((s.posture, s.role) == ("H", "SC") for s in ws)
    assert "merged into fleet Main, which has 4 ships now" in r.messages[0]


def test_the_merged_fleet_moves_this_turn_with_the_target_fleets_orders():
    st, main, wing, ms, ws = _two()
    main.speed = None
    run_turn(st, {1: parse_orders("MF Wing 40 50\nMGF Wing Main\nMF Main 56 50")}, npr_fn=None)
    assert wing.number not in st.fleets or not st.fleets[wing.number].alive
    slowest = min(s.stype.move for s in ms + ws)
    assert (main.x, main.y) == (10 + slowest, 10)
    assert all((s.x, s.y) == (main.x, main.y) for s in ms + ws)


def test_target_destination_is_kept():
    st, main, wing, ms, ws = _two()
    main.speed = None
    run_turn(st, {1: parse_orders("MF Main 56 50")}, npr_fn=None)    # Main sets off, Wing stays
    # bring Wing to Main's square, with its own (different) destination
    for s in ws:
        s.x, s.y = main.x, main.y
    wing.x, wing.y = main.x, main.y
    wing.dx, wing.dy = 10, 30
    run_turn(st, {1: parse_orders("MGF Wing Main")}, npr_fn=None)
    assert (main.dx, main.dy) == (16, 10)
    assert all((s.x, s.y) == (main.x, main.y) for s in ms + ws)


def test_errors():
    st, main, wing, ms, ws = _two()
    other = _fleet(st, 503, "Far", 14, 10, [add_ship(st, 1, "F", 14, 10)])
    theirs = _fleet(st, 504, "Raiders", 10, 10, [add_ship(st, 2, "F", 10, 10)], owner=2)
    ctx = ctx_for(st)
    assert do(ctx, 1, "MGF Nope Main").error == "You don't have a fleet called Nope."
    assert do(ctx, 1, "MGF Wing Nope").error == "You don't have a fleet called Nope."
    assert do(ctx, 1, "MGF Main Main").error == ("MGF needs two different fleets; Main is "
                                                 "named twice.")
    assert do(ctx, 1, "MGF Wing Far").error == ("Fleet Wing is at 50,50; fleet Far is at "
                                                "54,50: fleets merge only at the same square.")
    # another race's fleet is "not yours" with the same words as one that doesn't exist (G-16)
    assert do(ctx, 1, "MGF Raiders Main").error == "You don't have a fleet called Raiders."
    assert do(ctx, 1, "MGF Wing Raiders").error == "You don't have a fleet called Raiders."
    # nothing changed
    assert wing.alive and other.alive and theirs.alive
    assert all(s.fleet == wing.number for s in ws)


def test_classic_text_round_trip():
    o = parse_line("MGF Wing Main")
    assert (o.code, o.fleet, o.into) == ("MGF", "Wing", "Main")
    assert o.to_text() == "MGF Wing Main"
    with pytest.raises(OrderSyntaxError, match="Usage: MGF <fleet> <into>"):
        parse_line("MGF Wing")


def test_freed_name_can_be_reused_by_cf_later_in_the_draft():
    st, main, wing, ms, ws = _two()
    extra = add_ship(st, 1, "S", 10, 10)
    res = check_orders(st, 1, parse_orders(f"MGF Wing Main\nCF Wing 50 50\nAF Wing {extra.number}"))
    assert all(r.ok for r in res), [r.error for r in res]
    run_turn(st, {1: parse_orders(f"MGF Wing Main\nCF Wing 50 50\nAF Wing {extra.number}")},
             npr_fn=None)
    new = st.fleet_named("Wing", 1)
    assert new is not None and new.number != wing.number
    assert extra.fleet == new.number and all(s.fleet == main.number for s in ws)


def test_ships_away_from_the_main_body_join_the_target_like_af():
    st, main, wing, ms, ws = _two()
    straggler = add_ship(st, 1, "F", 12, 10, fleet=wing.number)    # Wing's, two squares off
    ctx = ctx_for(st)
    r = do(ctx, 1, "MGF Wing Main")
    assert r.ok and straggler.fleet == main.number
    assert any(f"Ship {straggler.number} was not with Wing's main body" in m for m in r.messages)
    run_turn(st, {}, npr_fn=None)
    assert (straggler.x, straggler.y) == (main.x, main.y) == (10, 10)
    assert straggler.fleet == main.number


def test_intercepting_target_sets_the_joining_ships_to_intercept():
    st, main, wing, ms, ws = _two()
    tgt = add_ship(st, 2, "S", 13, 10)
    ctx = ctx_for(st)
    assert do(ctx, 1, f"FIS Main {tgt.number}").ok
    assert do(ctx, 1, "MGF Wing Main").ok
    assert all((s.order, s.target) == (INTERCEPT, tgt.number) for s in ws)


def test_afxy_for_the_absorbed_fleet_fills_the_merged_fleet():
    st, main, wing, ms, ws = _two()
    loose = add_ship(st, 1, "S", 10, 10)
    run_turn(st, {1: parse_orders("AFXY Wing 50 50\nMGF Wing Main")}, npr_fn=None)
    assert loose.fleet == main.number


def test_the_absorbed_fleets_admiral_awaits_a_new_post():
    st, main, wing, ms, ws = _two()
    adm = add_leader(st, 1, fleet=wing.number)
    keep = add_leader(st, 1, fleet=main.number)
    r = do(ctx_for(st), 1, "MGF Wing Main")
    assert (adm.status, adm.fleet) == ("limbo", None)
    assert keep.fleet == main.number and keep.status == "posted"
    assert f"Admiral {adm.name} of fleet Wing is awaiting a new assignment: fleet Main already has an admiral." in r.messages


def test_the_absorbed_fleets_admiral_transfers_when_the_target_has_none():
    st, main, wing, ms, ws = _two()
    adm = add_leader(st, 1, fleet=wing.number)
    r = do(ctx_for(st), 1, "MGF Wing Main")
    assert (adm.status, adm.fleet) == ("posted", main.number)
    assert st.admiral(main.number) is adm
    assert f"Admiral {adm.name} of fleet Wing now commands fleet Main." in r.messages


def test_a_leader_on_the_way_to_the_absorbed_fleet_goes_on_to_the_merged_fleet():
    st, main, wing, ms, ws = _two()
    ld = add_leader(st, 1)
    run_turn(st, {1: parse_orders(f"MLF {ld.name} Wing\nMGF Wing Main")}, npr_fn=None)
    assert ld.fleet == main.number and ld.status == "transit"
    run_turn(st, {1: []}, npr_fn=None)
    assert ld.status == "posted" and st.admiral(main.number) is ld


def test_empty_target_made_this_turn_is_not_disbanded():
    st, main, wing, ms, ws = _two()
    run_turn(st, {1: parse_orders("CF New 50 50\nMGF Wing New")}, npr_fn=None)
    new = st.fleet_named("New", 1)
    assert new is not None and all(s.fleet == new.number for s in ws)


# ---- check-orders advice (G-20 style)
def _advice(st, text):
    adv = []
    res = check_orders(st, 1, parse_orders(text), adv)
    return res, adv


def test_advice_a_later_order_naming_the_absorbed_fleet_fails_with_a_fix():
    st, main, wing, ms, ws = _two()
    res, adv = _advice(st, "MGF Wing Main\nMFS Wing H2")
    assert not res[1].ok
    a = [x for x in adv if x["kind"] == "merged_fleet"]
    assert len(a) == 1 and a[0]["index"] == 1
    assert a[0]["text"] == ("MFS Wing H2: fleet Wing is merged into Main by order 1, so this "
                            "order will fail: you no longer have a fleet called Wing. Use Main "
                            "for the merged fleet.")
    assert a[0]["fix"]["order"]["fleet"] == "Main" and a[0]["fix"]["label"] == "Use Main"


def test_advice_silent_when_cf_reuses_the_name():
    st, main, wing, ms, ws = _two()
    res, adv = _advice(st, "MGF Wing Main\nCF Wing 50 50\nFS Wing 3")
    assert all(r.ok for r in res) and not [x for x in adv if x["kind"].startswith("merged")]


def test_advice_a_move_before_the_merge_no_longer_applies():
    st, main, wing, ms, ws = _two()
    res, adv = _advice(st, "MF Wing 40 50\nFS Wing 3\nMGF Wing Main\nMF Main 56 50")
    assert all(r.ok for r in res)
    a = [x for x in adv if x["kind"] == "merged_move"]
    assert [x["index"] for x in a] == [0, 1]
    assert a[0]["text"] == ("MF Wing 40 50: fleet Wing is merged into Main by order 3, so this "
                            "move order no longer applies: the merged fleet moves with fleet "
                            "Main's orders.")
    assert "speed order" in a[1]["text"]
    # the target's own move is fine
    assert not [x for x in adv if x["index"] == 3]


def test_advice_chained_merge_points_at_the_last_fleet():
    st, main, wing, ms, ws = _two()
    _fleet(st, 505, "Third", 10, 10, [add_ship(st, 1, "F", 10, 10)])
    res, adv = _advice(st, "MGF Wing Main\nMGF Main Third\nMF Wing 40 50")
    a = [x for x in adv if x["kind"] == "merged_fleet"]
    assert len(a) == 1 and a[0]["fix"]["order"]["fleet"] == "Third"


# ---- API and catalogue
from tests import test_api  # noqa: E402

env = test_api.env


def test_catalogue_lists_mgf_with_help(env):
    c = env["c"]
    by = {o["code"]: o for o in c.get("/api/orders/catalogue").json()["orders"]}
    m = by["MGF"]
    assert m["category"] == "fleet" and m["usage"] == "MGF <fleet> <into>"
    assert "Merge fleets" in m["help"] and "same square" in m["help"]
    args = {a["name"]: a for a in m["args"]}
    assert set(args) == {"fleet", "into"} and "disbanded" in args["fleet"]["help"]
    assert "same square" in args["into"]["help"]


def test_api_saves_and_checks_mgf(env):
    c, gid, t1 = env["c"], env["gid"], env["t1"]
    H = test_api.H
    r = c.put(f"/api/games/{gid}/orders", json={"orders": [{"code": "MGF", "fleet": "A",
                                                             "into": "B"}]}, headers=H(t1))
    assert r.status_code == 200 and r.json()["orders"][0]["text"] == "MGF A B"
    ck = c.post(f"/api/games/{gid}/orders/check", headers=H(t1)).json()
    assert ck["results"][0]["error"] == "You don't have a fleet called A."
    bad = c.put(f"/api/games/{gid}/orders", json={"text": "MGF A"}, headers=H(t1))
    assert bad.status_code == 422
