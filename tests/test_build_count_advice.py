"""BS / BCU build counts (DECISIONS G-19) and the check-orders advice (DECISIONS G-20)."""
import pytest

from mhgc.analysis import spending
from mhgc.engine.turn import check_orders, run_turn
from mhgc.model import Fleet, from_dict, to_dict
from mhgc.orders import OrderSyntaxError, make_order, parse_line, parse_orders
from tests.conftest import add_leader, add_ship, add_troop, ctx_for, do, make_state, sysn


# ---------------------------------------------------------------- the classic format
def test_parse_bs_bcu_counts():
    o = parse_line("BS H615 T 3")
    assert (o.type, o.posture, o.role, o.count) == ("T", None, None, 3)
    assert o.to_text() == "BS H615 T 3" and not o.warnings
    o = parse_line("BS H615 F H MR 5")
    assert (o.posture, o.role, o.count) == ("H", "MR", 5)
    assert parse_line("BS H615 F MR 2").role == "MR"
    o = parse_line("BCU H615 S 2")
    assert (o.type, o.posture, o.count) == ("S", None, 2) and o.to_text() == "BCU H615 S 2"
    o = parse_line("BCU H615 S D 4")
    assert (o.posture, o.count) == ("D", 4) and o.to_text() == "BCU H615 S D 4"
    # 1 is the default and is written back without the count
    assert parse_line("BS H615 T 1").to_text() == "BS H615 T"
    assert make_order("BCU", system="X", type="S", count=1).count is None
    # the old forms still parse, with the old warnings
    assert parse_line("BS Earth F oops").warnings
    assert parse_line("BCU Earth S oops").warnings
    assert parse_line("BS Earth D MR H").posture == "H"


@pytest.mark.parametrize("line", ["BS H1 T 0", "BS H1 T 51", "BCU H1 S A 51", "BS H1 T -2"])
def test_count_cap(line):
    with pytest.raises(OrderSyntaxError, match="Count must be between 1 and 50"):
        parse_line(line)


def test_catalogue_has_count():
    from app.catalogue import order_catalogue
    cat = {o["code"]: o for o in order_catalogue()["orders"]}
    for code in ("BS", "BCU"):
        a = cat[code]["args"][-1]
        assert (a["name"], a["optional"], a["lo"], a["hi"]) == ("count", True, 1, 50)
        assert "count" in cat[code]["usage"]


# ---------------------------------------------------------------- the engine
def test_build_three_transports_full():
    st = make_state()
    ctx = ctx_for(st)
    sysn(st, "H1").starport = 3
    e = st.empires[1]
    eu, iu = e.eu, sysn(st, "H1").iu
    r = do(ctx, 1, "BS H1 T 3")
    assert r.ok and r.built == 3
    mine = [s for s in st.ships.values() if s.owner == 1 and s.type == "T"]
    assert len(mine) == 3
    assert r.messages[-1].startswith("Built 3 Transports at H1: ")
    assert e.eu == eu - 60 and sysn(st, "H1").iu == iu - 60
    assert ctx.builds[sysn(st, "H1").id] == 3


def test_build_partial_capacity():
    st = make_state()                         # class 2 starport
    ctx = ctx_for(st)
    r = do(ctx, 1, "BS H1 T 3")
    assert r.ok and r.built == 2
    assert len([s for s in st.ships.values() if s.owner == 1]) == 2
    msg = r.messages[-1]
    assert msg.startswith("Built 2 of 3 Transports at H1: ")
    assert "The other 1 was not built: The class 2 starport at H1 has no capacity left" in msg
    # a second build order finds the starport full and fails as before
    r2 = do(ctx, 1, "BS H1 T")
    assert not r2.ok and "no capacity left" in r2.error


def test_build_partial_money_and_troops():
    st = make_state()
    ctx = ctx_for(st)
    st.empires[1].eu = 25                    # Shock troops cost 10 EU (and 10 IU)
    r = do(ctx, 1, "BCU H1 S 3")
    assert r.ok and r.built == 2
    assert "Built 2 of 3 Shock troops at H1" in r.messages[-1]
    assert "This costs 10 EU, but you have only 5." in r.messages[-1]
    assert st.empires[1].eu == 5


def test_build_none_fails_like_one():
    st = make_state()
    ctx = ctx_for(st)
    sysn(st, "H1").starport = 0
    r = do(ctx, 1, "BS H1 T 4")
    assert not r.ok and r.error == "H1 has no starport. Build one first (BSP)."
    assert r.built is None


def test_build_count_cost_multiplier_and_entrench_warning_once():
    from mhgc.data import constants as K
    st = make_state()
    ctx = ctx_for(st)
    h = sysn(st, "H1")
    h.status = K.UNDER_ATTACK
    eu = st.empires[1].eu
    r = do(ctx, 1, "BCU H1 C E 2")           # Cybertanks: not infantry
    st.empires[1].techs.add(4)
    r = do(ctx, 1, "BCU H1 C E 2")
    assert r.ok and r.built == 2
    assert sum("can't entrench" in m for m in r.messages) == 1
    from mhgc.data.troops import TROOP_TYPES
    assert st.empires[1].eu == eu - 2 * 2 * TROOP_TYPES["C"].eu_cost


def test_count_spending_and_ledger_purchases():
    """The ledger itself is checked by tests/test_ledger.py (BS/BCU count entries); here the
    analysis export counts every unit built, and a real turn reports `built`."""
    st = make_state()
    sysn(st, "H1").starport = 4
    before = from_dict(to_dict(st))
    orders = {1: parse_orders("BS H1 T 3\nBCU H1 S 2")}
    res = run_turn(st, orders, npr_fn=None)
    rep = res.report(1)
    assert [o.built for o in rep.orders] == [3, 2]
    sp = spending(before, orders, res)[1]
    assert sp["ships"] == {"eu": 60, "iu": 60} and sp["troops"] == {"eu": 20, "iu": 20}
    purchases = [ln for ln in rep.maintenance if ln["kind"] == "purchases"]
    assert sum(ln["eu"] for ln in purchases) == -80


def test_check_shows_partial_build_as_advice():
    st = make_state()
    adv = []
    res = check_orders(st, 1, parse_orders("BS H1 T 3"), adv)
    assert res[0].ok and res[0].built == 2
    assert [a["kind"] for a in adv] == ["build_partial"]
    assert adv[0]["text"].startswith("Built 2 of 3 Transports at H1")


# ---------------------------------------------------------------- (a) cargo orders and movement
def _adv(st, text, eid=1, fixes=None):
    adv = []
    res = check_orders(st, eid, parse_orders(text), adv, fixes)
    return res, adv


def _rel(st, x, y, eid=1):
    from mhgc import geometry as G
    e = st.empires[eid]
    rx, ry = G.to_rel(x, y, e.home_x, e.home_y, st.board)
    return f"{rx},{ry}"


def test_ordinary_move_and_load_is_silent():
    """Orders run before movement and a move order only sets a destination, so a load in the
    same turn as a move happens here and works: no warning (Dave 2026-11-18)."""
    st = make_state()
    h = sysn(st, "H1")
    h.au = 100
    add_ship(st, 1, "T", h.x, h.y, number=9835, cargo_au=5)
    add_ship(st, 2, "S", 20, 20, number=777)
    add_ship(st, 1, "T", h.x, h.y, number=501, fleet=1)
    st.fleets[1] = Fleet(1, 1, "Wing", h.x, h.y, dx=h.x, dy=h.y)
    add_troop(st, 1, "S", system=h.id, number=601)
    for text in ("MS 9835 E2\nL 9835 A 10", "L 9835 A 10\nMS 9835 E2", "MO 9835 75 71\nU 9835 A 5",
                 "LOCT 9835 601\nI 9835 777", "G 9835\nL 9835 A 1",
                 "MFS Wing E2\nFL Wing A 5\nL 501 A 5"):
        res, adv = _adv(st, text)
        assert all(r.ok for r in res) and adv == [], (text, adv)


def _warp_state():
    st = make_state()
    st.empires[1].techs.add(50)
    h = sysn(st, "H1")
    col = sysn(st, "E2")
    col.owner, col.pop, col.au = 1, 2.0, 50
    h.artifacts.add("WT")
    col.artifacts.add("WT")
    h.au = 100
    add_ship(st, 1, "T", h.x, h.y, number=9835)
    return st, h, col


def test_load_after_warp_succeeds_at_the_far_end_with_fix():
    st, h, col = _warp_state()
    res, adv = _adv(st, "ECHO hi\nWTP 9835 E2\nL 9835 A 10")
    assert all(r.ok for r in res)
    assert [(a["index"], a["kind"]) for a in adv] == [(2, "warp_cargo")]
    assert adv[0]["text"] == "Ship 9835 loads at E2 (after the warp in order 2), not at H1."
    assert adv[0]["fix"] == {"move_to": 1, "order": None, "label": "Move it before order 2"}
    # applying the Fix: the load runs at H1, then the warp; no warning
    res, adv = _adv(st, "ECHO hi\nL 9835 A 10\nWTP 9835 E2")
    assert all(r.ok for r in res) and adv == []
    # a move after the warp changes nothing: it still loads at the far end
    _, adv = _adv(st, "WTP 9835 E2\nL 9835 A 10\nMO 9835 10 10")
    assert [a["kind"] for a in adv] == ["warp_cargo"]
    # no Fix when the load wouldn't work before the warp either (nothing at H1)
    h.au = 0
    _, adv = _adv(st, "WTP 9835 E2\nL 9835 A 10")
    assert adv[0]["kind"] == "warp_cargo" and adv[0]["fix"] is None


def test_fleet_load_after_fleet_warp():
    st, h, col = _warp_state()
    add_ship(st, 1, "T", h.x, h.y, number=501, fleet=1)
    st.fleets[1] = Fleet(1, 1, "Wing", h.x, h.y, dx=h.x, dy=h.y)
    res, adv = _adv(st, "WTPF Wing E2\nFL Wing A 5\nL 501 A 5")
    assert all(r.ok for r in res)
    assert [(a["index"], a["text"]) for a in adv] == [
        (1, "Fleet Wing loads at E2 (after the warp in order 1), not at H1."),
        (2, "Ship 501 loads at E2 (after the warp in order 1), not at H1.")]


def test_load_after_warp_fails_with_the_cause_and_a_fix():
    st, h, col = _warp_state()
    col.au = 0
    fixes = {}
    res, adv = _adv(st, "WTP 9835 E2\nL 9835 A 10", fixes=fixes)
    assert res[0].ok and not res[1].ok and adv == []
    assert res[1].error == ("Ship 9835 was moved to E2 by your warp order (order 1) before this "
                            "load, so it tries to load at E2: E2 has only 0 AU to load. Put the "
                            "load before the warp order.")
    assert fixes == {1: {"move_to": 0, "order": None, "label": "Move it before order 1"}}
    # the same text when the turn really runs
    rep = run_turn(from_dict(to_dict(st)), {1: parse_orders("WTP 9835 E2\nL 9835 A 10")},
                   npr_fn=None).report(1)
    assert rep.orders[1].error == res[1].error
    # the system stops being yours after the warp (SR): "which isn't yours"
    col.pop = 1.0
    res, _ = _adv(st, "WTP 9835 E2\nSR E2\nL 9835 A 10")
    assert res[1].ok and res[2].error == (
        "Ship 9835 was moved to E2 by your warp order (order 1) before this load, so it tries "
        "to load at E2, which isn't yours. Put the load before the warp order.")
    # a troop left behind
    add_troop(st, 1, "S", system=h.id, number=601)
    fixes = {}
    res, _ = _adv(st, "WTP 9835 E2\nLOCT 9835 601", fixes=fixes)
    assert res[1].error == ("Ship 9835 was moved to E2 by your warp order (order 1) before this "
                            "troop load, so it tries to load the troop at E2: Combat troop 601 "
                            "isn't at E2, where ship 9835 is. Put the troop load before the warp "
                            "order.")
    assert fixes[1]["move_to"] == 0
    # a failure for another reason, with no warp, is untouched
    res, _ = _adv(st, "L 9835 A 1000")
    assert res[0].error.startswith("Ship 9835 has room for only ")


def _transit_state():
    """Ship 9835 in deep space at 44,50 (absolute) heading for E2 (52,50), which is yours: a
    transport moves 4 squares a turn, so two turns away."""
    from mhgc.model import MOVE
    st = make_state()
    col = sysn(st, "E2")
    col.owner, col.pop, col.au = 1, 2.0, 50
    sh = add_ship(st, 1, "T", 44, 50, number=9835, cargo_au=5)
    sh.order, sh.dx, sh.dy = MOVE, col.x, col.y
    return st, sh, col


def test_load_in_transit_says_where_and_when():
    st, sh, col = _transit_state()
    here = _rel(st, 44, 50)
    res, adv = _adv(st, "L 9835 A 10")
    assert adv == [] and res[0].error == (
        f"Ship 9835 is in deep space at {here}, still on its way to E2 (arrives in 2 turns, at "
        f"the end of turn 7). It can load once it's there: give the load order on turn 8.")
    # unload, gift unload, troop landing: the right verb
    res, _ = _adv(st, "U 9835 A 5")
    assert res[0].error.endswith("It can unload once it's there: give the unload order on turn 8.")
    add_troop(st, 1, "S", ship=9835, number=602)
    res, _ = _adv(st, "LACT 9835 602")
    assert res[0].error == (
        f"Ship 9835 is in deep space at {here}, still on its way to E2 (arrives in 2 turns, at "
        f"the end of turn 7). It can land the troop once it's there: give the landing order on "
        f"turn 8.")
    # one turn away
    sh.x = 48
    res, _ = _adv(st, "L 9835 A 10")
    assert res[0].error == (
        f"Ship 9835 is in deep space at {_rel(st, 48, 50)}, still on its way to E2 (arrives at "
        f"the end of this turn). It can load once it's there: give the load order next turn.")
    # the same at turn run
    rep = run_turn(from_dict(to_dict(st)), {1: parse_orders("L 9835 A 10")}, npr_fn=None).report(1)
    assert rep.orders[0].error == res[0].error
    # SL on your own ship in transit too; SL on another race's ship stays as it was
    res, _ = _adv(st, "SL 9835 A 1")
    assert res[0].error.startswith(f"Ship 9835 is in deep space at {_rel(st, 48, 50)}, still on")
    add_ship(st, 2, "T", 44, 50, number=777)
    res, _ = _adv(st, "SL 777 A 1")
    assert res[0].error == "Ship 777 isn't at one of your systems."


def test_transit_with_no_move_and_a_later_move_in_the_draft():
    st, sh, col = _transit_state()
    from mhgc.model import STAND
    sh.order, sh.dx, sh.dy = STAND, sh.x, sh.y
    here = _rel(st, 44, 50)
    res, _ = _adv(st, "L 9835 A 10")
    assert res[0].error == (f"Ship 9835 is in deep space at {here} with no move order: it must "
                            f"be at one of your systems to load.")
    # a move given later in the draft is where it is going (check orders)
    res, _ = _adv(st, "L 9835 A 10\nMS 9835 E2")
    assert "still on its way to E2 (arrives in 2 turns" in res[0].error


def test_transit_names_only_what_the_empire_knows():
    st, sh, col = _transit_state()
    # heading for a system it has never scanned: coordinates, not the name
    secret = type(col)(len(st.systems), "Secretia", 60, 50, owner=2, pop=3.0, hab=3)
    st.systems.append(secret)
    sh.dx, sh.dy = secret.x, secret.y
    res, _ = _adv(st, "U 9835 A 5")
    assert "Secretia" not in res[0].error and "R2" not in res[0].error
    assert res[0].error == (f"Ship 9835 is in deep space at {_rel(st, 44, 50)}, still on its way "
                            f"to {_rel(st, 60, 50)} (arrives in 4 turns, at the end of turn 9).")
    # a system renamed since it was scanned: the name in its map memory
    st.empires[1].seen_systems[secret.id] = {"turn": 3, "name": "OldName", "owner": 2}
    res, _ = _adv(st, "L 9835 A 5")
    assert "Secretia" not in res[0].error
    assert res[0].error.endswith("to OldName (arrives in 4 turns, at the end of turn 9), which "
                                 "isn't one of your systems either.")


def test_load_at_a_foreign_system_on_the_way():
    st, sh, col = _transit_state()
    h2 = sysn(st, "H2")
    sh.x, sh.y = h2.x, h2.y
    sh.dx, sh.dy = sysn(st, "H1").x, sysn(st, "H1").y
    res, _ = _adv(st, "L 9835 A 1")
    assert res[0].error == ("Ship 9835 is at H2, which isn't yours. Ships load only at your own "
                            "systems. It is still on its way to H1 (arrives in 3 turns, at the end "
                            "of turn 8). It can load once it's there: give the load order on turn "
                            "9.")


def test_fleet_cargo_in_transit_uses_the_fleets_position():
    st, sh, col = _transit_state()
    sh.fleet = 1
    from mhgc.model import MOVE
    st.fleets[1] = Fleet(1, 1, "Wing", 44, 50, dx=col.x, dy=col.y)
    st.fleets[1].order = MOVE
    res, _ = _adv(st, "FL Wing A 5\nFU Wing A 5")
    assert res[0].error == (
        f"Fleet Wing is in deep space at {_rel(st, 44, 50)}, still on its way to E2 (arrives in 2 "
        f"turns, at the end of turn 7). It can load once it's there: give the load order on "
        f"turn 8.")
    assert res[1].error.startswith("Fleet Wing is in deep space") and "unload" in res[1].error


def test_unload_where_the_draft_loaded_it_before_moving():
    """(c): load and unload the same cargo at the same place, then move: it all stays here."""
    st = make_state()
    h = sysn(st, "H1")
    h.au = 100
    add_ship(st, 1, "T", h.x, h.y, number=9835)
    add_troop(st, 1, "S", system=h.id, number=601)
    res, adv = _adv(st, "L 9835 A 10\nMS 9835 E2\nU 9835 A 10")
    assert all(r.ok for r in res)
    assert [(a["index"], a["kind"]) for a in adv] == [(2, "move_cargo")]
    assert adv[0]["text"] == (
        "Ship 9835 unloads at H1, where order 1 loaded it, before it moves to E2 (orders run "
        "before movement), so the cargo stays at H1. To unload at E2, give the unload order on "
        "turn 17, once it has arrived.")
    _, adv = _adv(st, "LOCT 9835 601\nLACT 9835 601\nMO 9835 52 52")
    assert adv[0]["text"].startswith("Ship 9835 lands combat troop 601 at H1, where order 1 "
                                      "loaded it, before it moves to 52,52")
    assert "so the troop stays at H1" in adv[0]["text"]
    # silent: no move, a different item, an unload of cargo loaded on an earlier turn
    for text in ("L 9835 A 10\nU 9835 A 10", "L 9835 A 10\nMS 9835 E2\nU 9835 I 0",
                 "MS 9835 E2\nU 9835 A 0"):
        _, adv = _adv(st, text)
        assert adv == [], text


def test_farcast_troop_then_troop_load_says_why():
    st = make_state()
    h = sysn(st, "H1")
    col = sysn(st, "E2")
    col.owner, col.pop = 1, 2.0
    h.artifacts.add("FP")
    col.artifacts.add("FP")
    add_ship(st, 1, "T", h.x, h.y, number=9835)
    add_troop(st, 1, "S", system=h.id, number=601)
    res, _ = _adv(st, "TP H1 C 601 E2\nLOCT 9835 601")
    assert res[0].ok and res[1].error == (
        "Combat troop 601 isn't at H1, where ship 9835 is. Your farcaster order (order 1) sent it "
        "to E2 before this order; put the troop load before the TP.")


# ---------------------------------------------------------------- (b) renames
def test_rename_then_old_name_warns_with_fix():
    st = make_state()
    h = sysn(st, "H1")
    add_ship(st, 1, "T", h.x, h.y, number=9835)
    res, adv = _adv(st, "BS H1 T\nNSY H1 Hamburgia\nBI H1 1\nMS 9835 H1")
    assert not res[2].ok and not res[3].ok
    assert [(a["index"], a["kind"]) for a in adv] == [(2, "rename"), (3, "rename")]
    assert adv[1]["text"] == ("MS 9835 H1: H1 is renamed to Hamburgia by order 2, so this order "
                              "should use Hamburgia.")
    fix = adv[0]["fix"]
    assert fix["order"] == {"code": "BI", "system": "Hamburgia", "amount": 1}
    assert fix["label"] == "Use Hamburgia"
    # applying the fixes clears the warnings and the errors
    fixed = parse_orders("BS H1 T\nNSY H1 Hamburgia")
    from mhgc.orders import order_from_dict
    fixed += [order_from_dict(adv[0]["fix"]["order"]), order_from_dict(adv[1]["fix"]["order"])]
    adv2 = []
    res2 = check_orders(st, 1, fixed, adv2)
    assert all(r.ok for r in res2) and adv2 == []


def test_new_name_before_rename_warns_with_fix():
    st = make_state()
    res, adv = _adv(st, "BI Hamburgia 1\nNSY H1 Hamburgia\nTP Hamburgia A 0 Hamburgia")
    assert [(a["index"], a["kind"]) for a in adv] == [(0, "rename")]
    assert adv[0]["text"] == ("BI Hamburgia 1: H1 is renamed to Hamburgia only by order 2, after "
                              "this one, so this order should use H1.")
    assert adv[0]["fix"]["order"]["system"] == "H1"


def test_chained_renames_and_tp_to_field():
    st = make_state()
    col = sysn(st, "E2")
    col.owner, col.pop = 1, 2.0
    _, adv = _adv(st, "NSY H1 A1\nNSY A1 B1\nTP H1 A 5 E2\nTP B1 A 5 E2\nCSP A1 40 30 30")
    assert [(a["index"], a["fix"]["name"]) for a in adv] == [(2, "B1"), (4, "B1")]


def test_rename_clashes():
    st = make_state()
    col = sysn(st, "E2")
    col.owner, col.pop = 1, 2.0
    _, adv = _adv(st, "NSY H1 Hamburgia\nNSY E2 Hamburgia")
    assert [a["kind"] for a in adv] == ["rename_clash"]
    assert adv[0]["text"] == ("NSY E2 Hamburgia: order 1 already renames H1 to Hamburgia, so this "
                              "rename will fail: the name is taken. Choose another name.")
    _, adv = _adv(st, "CRN Bigs\nCRN Smalls")
    assert adv[0]["kind"] == "rename_clash" and "renamed only once" in adv[0]["text"]
    ld = add_leader(st, 1, system=sysn(st, "H1").id)
    _, adv = _adv(st, f"CLN {ld.name} Bob\nCLN Bob Rob")
    assert adv[0]["kind"] == "rename_clash" and adv[0]["text"].startswith(
        f"CLN Bob Rob: order 1 already renames {ld.name} to Bob; a leader can be renamed only once")
    _, adv = _adv(st, f"CLN {ld.name} Bob\nML {ld.name} E2")
    assert adv[0]["kind"] == "rename" and adv[0]["fix"]["order"]["leader"] == "Bob"


def test_freed_name_taken_by_another_system():
    st = make_state()
    col = sysn(st, "E2")
    col.owner, col.pop = 1, 2.0
    _, adv = _adv(st, "NSY H1 Home\nNSY E2 H1\nBI H1 1")
    assert [a["kind"] for a in adv] == ["rename_shift"]
    assert adv[0]["fix"] is None and "use Home" in adv[0]["text"]


def test_no_rename_warnings_for_unrelated_orders():
    st = make_state()
    _, adv = _adv(st, "NSY H1 Hamburgia\nBI Hamburgia 1\nPT 4\nCSP Hamburgia 40 30 30")
    assert adv == []
    _, adv = _adv(st, "BI H1 1\nNSY H1 Hamburgia")
    assert adv == []


def test_api_check_returns_advice(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    c = TestClient(create_app(tmp_path))
    g = c.post("/api/games", json={"password": "secret1", "name": "T", "humans": 1, "size": 8,
                                   "player": "Dave", "race": "Daves", "seed": 5,
                                   "host_password": "secret1"}).json()
    gid, h = g["id"], {"X-Seat-Token": g["token"]}
    v = c.get(f"/api/games/{gid}/view", headers=h).json()
    home = next(s["name"] for s in v["systems"])
    r = c.put(f"/api/games/{gid}/orders", headers=h,
              json={"text": f"NSY {home} Hamburgia\nBI {home} 1\nBS Hamburgia S 3"})
    assert r.status_code == 200, r.text
    ck = c.post(f"/api/games/{gid}/orders/check", headers=h).json()
    assert [a["kind"] for a in ck["advice"]] == ["rename", "build_partial"]
    assert ck["results"][1]["advice"][0]["fix"]["order"] == {"code": "BI", "system": "Hamburgia",
                                                            "amount": 1}
    assert ck["results"][0]["advice"] == [] and 1 <= ck["results"][2]["built"] < 3
    # Fix: put the rewritten order back; the warning goes
    rows = [{k: v for k, v in o.items() if k != "text"} for o in r.json()["orders"]]
    rows[1] = ck["results"][1]["advice"][0]["fix"]["order"]
    assert c.put(f"/api/games/{gid}/orders", headers=h, json={"orders": rows}).status_code == 200
    ck = c.post(f"/api/games/{gid}/orders/check", headers=h).json()
    assert [a["kind"] for a in ck["advice"]] == ["build_partial"] and ck["results"][1]["ok"]


def test_legacy_report_shows_counts_and_partial_builds():
    from mhgc.engine.turn import initial_results
    from mhgc.legacy_report import legacy_report
    from mhgc.mapgen import new_game
    from mhgc.view import view
    st = new_game("Counts", 3, ["Alpha"], size=8)
    initial_results(st)
    home = next(s for s in st.systems if s.owner == 1 and s.starport)
    want = int(home.starport) + 1
    rd = run_turn(st, {1: parse_orders(f"BS {home.name} S {want}")}).to_dict()
    text = legacy_report(view(st, rd, 1), None)
    assert f"BS {home.name} S {want}" in text
    assert f"***WARNING Built {want - 1} of {want} Scouts at {home.name}: " in text
