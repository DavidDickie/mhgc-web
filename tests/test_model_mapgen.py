"""State model, JSON save/load, RNG, geometry and map generation."""
from mhgc import geometry as G
from mhgc import model
from mhgc.data import constants as K
from mhgc.engine.turn import run_turn
from mhgc.mapgen import new_game
from mhgc.rng import Rng


def test_geometry_wraps():
    # rules:225-231: 0,0 -> 0,99 / 99,99 / 99,0 are adjacent; moves are square
    assert G.distance(0, 0, 99, 99) == 1
    assert G.distance(5, 5, 8, 8) == 3
    assert G.step(0, 0, 97, 3, 2) == (98, 2)
    assert G.step(5, 5, 6, 9, 3) == (6, 8)
    assert G.to_rel(12, 90, 12, 90) == (50, 50)
    assert G.to_abs(*G.to_rel(3, 97, 60, 20), 60, 20) == (3, 97)


def test_rng_reproducible_and_independent():
    a, b = Rng(1, 5), Rng(1, 5)
    assert [a.pct() for _ in range(20)] == [b.pct() for _ in range(20)]
    assert [Rng(1, 6).pct() for _ in range(5)] != [Rng(1, 5).pct() for _ in range(5)]
    n = Rng(1, 1).new_number({5, 6}, 10)
    assert n not in (5, 6) and 1 <= n < 10


def test_mapgen_full_board():
    g = new_game("t", 3, ["Dave", "Bob", "Eve"])
    assert len(g.systems) == 176 and len(g.empires) == 17
    assert sum(e.kind == "human" for e in g.empires.values()) == 3
    coords = [(s.x, s.y) for s in g.systems]
    assert len(set(coords)) == 176
    assert all(0 <= x < K.BOARD and 0 <= y < K.BOARD for x, y in coords)
    names = [s.name for s in g.systems]
    assert len(set(names)) == 176
    for e in list(g.empires.values())[1:]:
        home = g.system_at(e.home_x, e.home_y)
        assert (home.owner, home.pop, home.infra, home.hab, home.mr, home.ar, home.starport) == \
            (e.id, 10.0, 10, 5, True, True, 1)
        assert sorted(s.type for s in g.ships.values() if s.owner == e.id) == ["S", "T"]
        assert any(ld.owner == e.id and ld.system == home.id for ld in g.leaders.values())
    # one artifact system per bin
    assert sum(1 for s in g.systems if s.artifacts) == 16


def test_mapgen_deterministic_and_spread():
    a, b = new_game("t", 9, ["A", "B"]), new_game("t", 9, ["A", "B"])
    assert model.dumps(a) == model.dumps(b)
    e1, e2 = a.empires[1], a.empires[2]
    assert G.distance(e1.home_x, e1.home_y, e2.home_x, e2.home_y) >= 40


def test_json_roundtrip_mid_game():
    g = new_game("t", 4, ["A"])
    for _ in range(3):
        run_turn(g)
    text = model.dumps(g)
    g2 = model.loads(text)
    assert model.dumps(g2) == text
    # continuing from the reloaded state gives the same result
    run_turn(g)
    run_turn(g2)
    assert model.dumps(g) == model.dumps(g2)


def test_old_save_growth_rate_is_reset_to_standard():
    """DECISIONS G-09 (Dave 2026-11-14): CGR is gone and every system grows at the standard
    rate.  A save made when a system's growth rate had been changed still loads; the stored rate
    is dropped, so the system grows at 100 from then on."""
    from mhgc.engine import economy
    from tests.conftest import ctx_for
    st = new_game("old", 3, ["A", "B"])
    d = model.to_dict(st)
    home = next(s for s in d["systems"] if s["owner"] == 1)
    home["growth"] = 150
    old = model.from_dict(d)
    assert not hasattr(old.systems[home["id"]], "growth")
    assert "growth" not in model.to_dict(old)["systems"][home["id"]]
    a, b = model.from_dict(d), model.from_dict(model.to_dict(st))
    economy.grow(ctx_for(a)), economy.grow(ctx_for(b))
    assert [s.pop for s in a.systems] == [s.pop for s in b.systems]
