"""Unload then load on the same turn (Dave 2026-11-21; DECISIONS W-31): orders run in draft
order in phase 1, so a full transport can unload and then take on other cargo, including
what it has just put ashore."""
from mhgc.engine.turn import check_orders
from mhgc.orders import parse_orders
from tests.conftest import add_ship, add_troop, ctx_for, do, make_state, sysn


def _ok(r):
    assert r.ok, r.error
    return r


def test_full_transport_unloads_then_loads_population():
    st = make_state()
    ctx = ctx_for(st)
    h = sysn(st, "H1")
    sh = add_ship(st, 1, "T", h.x, h.y, number=9929, cargo_iu=60)     # 3 of 3 points used
    assert "room for only 0" in do(ctx, 1, "L 9929 P 1").error
    _ok(do(ctx, 1, "U 9929 I 20"))                                     # frees one point
    _ok(do(ctx, 1, "L 9929 P 1"))
    assert (sh.cargo_iu, sh.cargo_pop, h.pop, h.iu) == (40, 1, 3.0, 520)
    assert ctx.state.cargo_points_used(sh) == 3


def test_loading_back_what_was_just_unloaded():
    st = make_state()
    ctx = ctx_for(st)
    h = sysn(st, "H1")
    h.au = 0
    sh = add_ship(st, 1, "T", h.x, h.y, number=9929, cargo_au=60)
    _ok(do(ctx, 1, "U 9929 A 60"))
    assert h.au == 60
    _ok(do(ctx, 1, "L 9929 A 40"))                                     # only there because of the U
    _ok(do(ctx, 1, "L 9929 P 1"))
    assert (sh.cargo_au, sh.cargo_pop, h.au) == (40, 1, 20)


def test_land_troop_then_load():
    st = make_state()
    ctx = ctx_for(st)
    h = sysn(st, "H1")
    sh = add_ship(st, 1, "T", h.x, h.y, number=9929, cargo_iu=40)
    add_troop(st, 1, "S", ship=9929, number=601)                       # full: 2 goods + 1 troop
    _ok(do(ctx, 1, "LACT 9929 601"))
    _ok(do(ctx, 1, "L 9929 P 1"))
    assert sh.cargo_pop == 1 and st.troops[601].system == h.id
    assert "no cargo room" in do(ctx, 1, "LOCT 9929 601").error         # full again


def test_fleet_unload_then_load():
    st = make_state()
    ctx = ctx_for(st)
    h = sysn(st, "H1")
    t1 = add_ship(st, 1, "T", h.x, h.y, cargo_iu=60)
    t2 = add_ship(st, 1, "T", h.x, h.y, cargo_pop=3)
    _ok(do(ctx, 1, "CF Task 50 50"))
    _ok(do(ctx, 1, f"AF Task {t1.number} {t2.number}"))
    assert "room for only 0" in do(ctx, 1, "FL Task P 1").error
    _ok(do(ctx, 1, "FU Task I 60"))
    _ok(do(ctx, 1, "FU Task P 1"))
    _ok(do(ctx, 1, "FL Task P 4"))                                     # 3 free on t1, 1 on t2
    assert t1.cargo_pop + t2.cargo_pop == 6 and t1.cargo_iu == 0
    _ok(do(ctx, 1, "FU Task P 6"))
    _ok(do(ctx, 1, "FL Task I 100"))
    assert t1.cargo_iu + t2.cargo_iu == 100


def test_check_orders_says_both_ok():
    """The Check orders path (a copy of the state, the whole draft in order) agrees."""
    st = make_state()
    h = sysn(st, "H1")
    add_ship(st, 1, "T", h.x, h.y, number=9929, cargo_iu=60)
    adv = []
    res = check_orders(st, 1, parse_orders("U 9929 I 20\nL 9929 P 1"), adv)
    assert [r.ok for r in res] == [True, True], [r.error for r in res]
    assert adv == []
    # the other way round fails: the load runs first, while the ship is still full
    res = check_orders(st, 1, parse_orders("L 9929 P 1\nU 9929 I 20"), [])
    assert not res[0].ok and res[1].ok
