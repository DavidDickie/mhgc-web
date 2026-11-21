"""End-of-turn fleet cleanup (Dave 2026-11-16, DECISIONS G-18): a fleet with no ships left is
disbanded at the end of the turn, as DF would, and its name is free again.  A fleet created this
turn by CF or CFXY that has not held a ship yet is spared for that turn only.

Empire 1's home H1 is at (10, 10) absolute = relative (50, 50); H2 (empire 2's home) is at
(20, 20) absolute = relative (60, 60) for empire 1."""
from mhgc.engine.turn import run_turn
from mhgc.model import from_dict, to_dict
from mhgc.orders import parse_orders
from tests.conftest import add_leader, add_ship, contact, make_state


def _st():
    st = make_state(n_humans=2, npr=0)
    contact(st, 1, 2)
    return st


def _fleet(st, name, ships, owner=1):
    """A fleet made the normal way (CF + AF) on a previous turn."""
    x, y = ships[0].x, ships[0].y
    rx, ry = x - 10 + 50, y - 10 + 50
    nums = " ".join(str(s.number) for s in ships)
    run_turn(st, {owner: parse_orders(f"CF {name} {rx} {ry}\nAF {name} {nums}")}, npr_fn=None)
    f = st.fleet_named(name, owner)
    assert f is not None and all(s.fleet == f.number for s in ships)
    return f


def _texts(res, eid, kind=None):
    return [e.text for e in res.report(eid).events if kind is None or e.kind == kind]


def test_a_fleet_destroyed_in_combat_disbands():
    st = _st()
    contact(st, 1, 2, "W")
    sh = add_ship(st, 1, "S", 10, 10)
    f = _fleet(st, "Doomed", [sh])
    adm = add_leader(st, 1, fleet=f.number)
    # the scout flies into R2's home, guarded by battleships
    for _ in range(6):
        add_ship(st, 2, "B", 20, 20, posture="H")
    sh.x, sh.y = sh.ox, sh.oy = 20, 20
    f.x, f.y = f.dx, f.dy = 20, 20
    res = run_turn(st, {}, npr_fn=None)
    assert sh.number not in st.ships
    assert st.fleet_named("Doomed", 1) is None and f.number not in st.fleets
    assert "Fleet Doomed has no ships left and was disbanded." in _texts(res, 1, "fleet_disbanded")
    # the admiral either died in the battle (F-07: 25% x all ships lost) or is back in limbo
    if adm.id in st.leaders:
        assert (adm.status, adm.fleet, adm.system) == ("limbo", None, None)
        assert any("Admiral L" in t and "fleet Doomed" in t for t in _texts(res, 1, "leader_evicted"))
    else:
        assert _texts(res, 1, "leader_killed")
    # the battle report is R1's and R2's, the disband notice R1's alone
    assert not _texts(res, 2, "fleet_disbanded")


def test_a_fleet_whose_ships_are_salvaged_disbands_and_its_admiral_returns_to_limbo():
    st = _st()
    a, b = add_ship(st, 1, "F", 10, 10), add_ship(st, 1, "F", 10, 10)
    f = _fleet(st, "Scrap", [a, b])
    adm = add_leader(st, 1, fleet=f.number)
    res = run_turn(st, {1: parse_orders(f"SS {a.number}\nDS {b.number}")}, npr_fn=None)
    assert all(o.ok for o in res.report(1).orders), [o.error for o in res.report(1).orders]
    assert st.fleet_named("Scrap", 1) is None
    assert _texts(res, 1, "fleet_disbanded") == ["Fleet Scrap has no ships left and was disbanded."]
    assert (adm.status, adm.fleet) == ("limbo", None)
    assert _texts(res, 1, "leader_evicted") == [
        f"Admiral {adm.name} of fleet Scrap has lost his post and is awaiting a new assignment."]


def test_a_fleet_whose_ships_are_gifted_disbands():
    st = _st()
    a = add_ship(st, 1, "F", 10, 10)
    _fleet(st, "Gift", [a])
    res = run_turn(st, {1: parse_orders(f"GS R2 {a.number}")}, npr_fn=None)
    assert res.report(1).orders[0].ok, res.report(1).orders[0].error
    assert st.ships[a.number].owner == 2 and st.ships[a.number].fleet is None
    assert st.fleet_named("Gift", 1) is None
    assert _texts(res, 1, "fleet_disbanded")


def test_a_fleet_emptied_by_lf_disbands_and_a_leader_on_the_way_turns_back():
    st = _st()
    a = add_ship(st, 1, "F", 10, 10)
    f = _fleet(st, "Gone", [a])
    ld = add_leader(st, 1)
    ld.status, ld.fleet, ld.transit = "transit", f.number, 2
    res = run_turn(st, {1: parse_orders(f"LF Gone {a.number}")}, npr_fn=None)
    assert st.fleet_named("Gone", 1) is None and st.ships[a.number].fleet is None
    assert (ld.status, ld.fleet, ld.transit) == ("limbo", None, 0)
    assert _texts(res, 1, "leader_evicted") == [
        f"Leader {ld.name}, on the way to fleet Gone, has lost his post and is awaiting a new "
        f"assignment."]


def test_a_fleet_with_ships_left_is_kept():
    st = _st()
    a, b = add_ship(st, 1, "F", 10, 10), add_ship(st, 1, "F", 10, 10)
    _fleet(st, "Half", [a, b])
    res = run_turn(st, {1: parse_orders(f"DS {a.number}")}, npr_fn=None)
    assert st.fleet_named("Half", 1) is not None
    assert not _texts(res, 1, "fleet_disbanded")


def test_cf_plus_af_in_the_same_turn_is_kept():
    st = _st()
    a = add_ship(st, 1, "F", 10, 10)
    res = run_turn(st, {1: parse_orders(f"CF New 50 50\nAF New {a.number}")}, npr_fn=None)
    f = st.fleet_named("New", 1)
    assert f is not None and st.ships[a.number].fleet == f.number
    assert not _texts(res, 1, "fleet_disbanded") and not _texts(res, 1, "fleet_empty")


def test_a_new_fleet_filled_then_destroyed_the_same_turn_disbands():
    # "created this turn" spares only a fleet still waiting for its first ship
    st = _st()
    a = add_ship(st, 1, "F", 10, 10)
    res = run_turn(st, {1: parse_orders(f"CF Brief 50 50\nAF Brief {a.number}\nDS {a.number}")},
                   npr_fn=None)
    assert st.fleet_named("Brief", 1) is None
    assert _texts(res, 1, "fleet_disbanded")


def test_a_cf_fleet_without_ships_gets_one_turn_of_grace():
    st = _st()
    a = add_ship(st, 1, "F", 10, 10)
    res = run_turn(st, {1: parse_orders("CF Later 50 50")}, npr_fn=None)
    assert st.fleet_named("Later", 1) is not None
    assert not _texts(res, 1, "fleet_disbanded")
    assert _texts(res, 1, "fleet_empty") == [
        "Fleet Later has no ships yet. Add ships to it next turn (AF or AFXY), or it will be "
        "disbanded at the end of that turn."]
    # next turn's AF fills it: kept
    run_turn(st, {1: parse_orders(f"AF Later {a.number}")}, npr_fn=None)
    assert st.fleet_named("Later", 1) is not None


def test_a_cfxy_fleet_gathers_after_movement_and_is_kept():
    st = _st()
    ships = [add_ship(st, 1, "F", 10, 10) for _ in range(2)]
    res = run_turn(st, {1: parse_orders("CFXY Late 50 50")}, npr_fn=None)
    f = st.fleet_named("Late", 1)
    assert f is not None and all(s.fleet == f.number for s in ships)
    assert not _texts(res, 1, "fleet_disbanded") and not _texts(res, 1, "fleet_empty")


def test_a_cfxy_fleet_whose_ships_never_arrived_is_kept_one_turn_then_disbanded():
    # G-18: CFXY gathers only at the end of its own turn.  Nothing there: it is spared that turn
    # (with a notice) like an empty CF; still empty at the end of the next turn, it is disbanded.
    st = _st()
    add_ship(st, 1, "F", 10, 10)
    res = run_turn(st, {1: parse_orders("CFXY Nobody 70 70")}, npr_fn=None)
    assert st.fleet_named("Nobody", 1) is not None
    assert _texts(res, 1, "fleet_empty") and not _texts(res, 1, "fleet_disbanded")
    res = run_turn(st, {}, npr_fn=None)
    assert st.fleet_named("Nobody", 1) is None
    assert _texts(res, 1, "fleet_disbanded") == ["Fleet Nobody has no ships left and was disbanded."]


def test_the_name_can_be_reused():
    st = _st()
    a, b = add_ship(st, 1, "F", 10, 10), add_ship(st, 1, "F", 10, 10)
    _fleet(st, "Again", [a])
    run_turn(st, {1: parse_orders(f"DS {a.number}")}, npr_fn=None)
    assert st.fleet_named("Again", 1) is None
    res = run_turn(st, {1: parse_orders(f"CF Again 50 50\nAF Again {b.number}")}, npr_fn=None)
    assert all(o.ok for o in res.report(1).orders), [o.error for o in res.report(1).orders]
    f = st.fleet_named("Again", 1)
    assert f is not None and st.ships[b.number].fleet == f.number


def test_old_saves_holding_empty_fleets_are_cleaned_up_at_their_next_turn():
    st = _st()
    a = add_ship(st, 1, "F", 10, 10)
    f = _fleet(st, "Stale", [a])
    adm = add_leader(st, 1, fleet=f.number)
    # an old save: the ship was lost before this rule existed and the fleet stayed behind
    del st.ships[a.number]
    st = from_dict(to_dict(st))
    res = run_turn(st, {}, npr_fn=None)
    assert st.fleet_named("Stale", 1) is None
    assert _texts(res, 1, "fleet_disbanded") == ["Fleet Stale has no ships left and was disbanded."]
    assert st.leaders[adm.id].status == "limbo"


def test_the_order_checker_does_not_disband():
    from mhgc.engine.turn import check_orders
    st = _st()
    a = add_ship(st, 1, "F", 10, 10)
    _fleet(st, "Kept", [a])
    out = check_orders(st, 1, parse_orders(f"DS {a.number}\nMF Kept 52 50"))
    assert [o.ok for o in out] == [True, True]          # the fleet is still there mid-turn
    assert st.fleet_named("Kept", 1) is not None


# ---- ground forces before -> after in the combat log (Dave 2026-11-16) ---------------------------

def _ground_battle():
    from tests.conftest import add_troop
    st = make_state(n_humans=3, npr=0)
    contact(st, 1, 2, "W")
    h2 = st.system_named("H2")
    mine = [add_troop(st, 1, "O", system=h2.id) for _ in range(3)]
    theirs = [add_troop(st, 2, t, system=h2.id, posture="D") for t in ("M", "M", "S")]
    res = run_turn(st, {}, npr_fn=None)
    return st, res, h2, mine, theirs


def _count(troops):
    out = {}
    for t in troops:
        out[t.type] = out.get(t.type, 0) + 1
    return out


def test_the_combat_log_has_each_sides_ground_forces_before_and_after():
    st, res, h2, mine, theirs = _ground_battle()
    c = next(c for c in res.combats if c.system == h2.id)
    sides = {g["owner"]: g for g in c.ground}
    assert set(sides) == {1, 2}
    assert sides[1]["before"] == {"O": 3} and sides[2]["before"] == {"M": 2, "S": 1}
    for eid, troops in ((1, mine), (2, theirs)):
        alive = [t for t in troops if t.number in st.troops and st.troops[t.number].owner == eid]
        assert sides[eid]["after"] == _count(alive)
    assert sides[2]["after"] != sides[2]["before"]      # the Ogres did kill something
    # each kill in the "after" is a kill line the participants already see
    dead = {t.number for t in mine + theirs if t.number not in st.troops}
    assert dead == {ln["ct"] for ln in c.lines if "destroyed" in ln["text"].lower() and "ct" in ln}


def test_ground_forces_reach_participants_only():
    from mhgc.view import view
    st, res, h2, *_ = _ground_battle()
    rd = res.to_dict()
    v1, v2, v3 = view(st, rd, 1), view(st, rd, 2), view(st, rd, 3)
    for v in (v1, v2):
        c = next(c for c in v["results"]["combats"] if c["system"] == h2.id)
        assert {g["owner"] for g in c["ground"]} == {1, 2}
    assert not v3["results"]["combats"]
    assert "ground" not in str(v3["results"]) and "before" not in str(v3["results"])


# ---- the bot copes with its fleets disappearing ------------------------------------------------

def test_a_bot_whose_war_fleet_is_wiped_out_carries_on():
    from mhgc.engine.turn import initial_results
    from mhgc.mapgen import new_game
    from mhgc.model import NPR
    st = new_game("bot", 5, [], size=8)
    initial_results(st)
    fleet = None
    for _ in range(80):
        run_turn(st)
        fleet = next((f for f in st.fleets.values() if st.empires[f.owner].kind == NPR
                      and st.fleet_ships(f.number)), None)
        if fleet is not None:
            break
    assert fleet is not None, "no computer empire formed a fleet"
    eid, name = fleet.owner, fleet.name
    for sh in st.fleet_ships(fleet.number):          # wiped out between turns, as if in battle
        del st.ships[sh.number]
    res = run_turn(st)
    assert st.fleet_named(name, eid) is None
    assert f"Fleet {name} has no ships left and was disbanded." in _texts(res, eid, "fleet_disbanded")
    for _ in range(3):
        res = run_turn(st)
        bad = [(o.text, o.error) for o in res.report(eid).orders
               if not o.ok and name in (o.text + (o.error or ""))]
        assert not bad, bad
