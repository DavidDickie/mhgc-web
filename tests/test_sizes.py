"""Game sizes (Dave 2026-11-13, DECISIONS W-13): 8 empires on 75x75 with the centre bin empty,
9 on 75x75, 12 on 100x100 with the four centre bins empty, and the classic 16 on 100x100; and
(Dave 2026-11-16, W-26) 4 empires on 50x50, four quadrants; and (Dave 2026-11-24, G-30) 20 and 25
empires on 125x125 (5x5 bins; 20 has five empty bins a knight's move apart).

Covers the map generator at every size, the variable board through geometry, scans, movement,
the scan-history mask, the view (home at the board centre) and orders; whole bot games at every
size; and the API (size choice, validation, defaults, old games)."""
from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from app.catalogue import order_catalogue
from app.main import create_app
from mhgc import geometry as G
from mhgc import model as M
from mhgc import scanmask
from mhgc.engine.turn import check_orders, initial_results, run_turn
from mhgc.mapgen import BIN, new_game
from mhgc.npr.sim import simulate
from mhgc.orders import parse_orders
from mhgc.view import view
from tests.test_npr_sim import _check_rejections

EXPECT = {4: (50, 2, [], 44), 8: (75, 3, [[1, 1]], 99), 9: (75, 3, [], 99),
          12: (100, 4, [[1, 1], [1, 2], [2, 1], [2, 2]], 176), 16: (100, 4, [], 176),
          20: (125, 5, [[0, 0], [2, 1], [4, 2], [1, 3], [3, 4]], 275), 25: (125, 5, [], 275)}


def _bin(x, y):
    return x // BIN, y // BIN


@pytest.mark.parametrize("size", sorted(EXPECT))
@pytest.mark.parametrize("seed", [1, 7, 23])
def test_each_size_generates(size, seed):
    board, side, empty, nsys = EXPECT[size]
    humans = ["Dave", "Bob", "Eve"]
    st = new_game("t", seed, humans, size=size)
    assert (st.board, st.bins, st.empty_bins) == (board, side, empty)
    assert len(st.empires) == size + 1 and sum(e.kind == "human" for e in st.empires.values()) == 3
    assert len(st.systems) == nsys == side * side * 11
    coords = [(s.x, s.y) for s in st.systems]
    assert len(set(coords)) == nsys and all(0 <= x < board and 0 <= y < board for x, y in coords)
    assert len({s.name for s in st.systems}) == nsys
    per_bin: dict = {}
    for s in st.systems:
        per_bin.setdefault(_bin(s.x, s.y), []).append(s)
    homes = {_bin(e.home_x, e.home_y): e for e in st.empires.values() if e.id}
    # one home per non-empty bin, none in an empty bin
    assert sorted(homes) == sorted((bx, by) for bx in range(side) for by in range(side)
                                   if [bx, by] not in empty)
    for b in empty:
        sys_b = [s for s in st.systems if _bin(s.x, s.y) == tuple(b) or
                 G.distance(s.x, s.y, b[0] * BIN + 12, b[1] * BIN + 12, board) <= 12]
        assert sys_b and all(s.owner == 0 and s.pop == 0 for s in sys_b)
    # every bin's share: 11 systems placed from it (satellites may cross a bin edge)
    assert sum(1 for s in st.systems if s.artifacts) == side * side
    assert sum(1 for s in st.systems if s.owner == 0) == nsys - size
    # empty bins hold an unowned prize world (VH, MR and AR) at their heart
    prizes = [s for s in st.systems if s.owner == 0 and s.hab == 4 and s.mr and s.ar and
              tuple(_bin(s.x, s.y)) in {tuple(b) for b in empty}]
    assert len(prizes) >= len(empty)
    # no system next to another empire's home (the close-to-home world may touch its own, as
    # in the classic generator); homes spread
    hl = [(e.home_x, e.home_y) for e in st.empires.values() if e.id]
    near_own = 0
    for s in st.systems:
        for hx, hy in hl:
            if (s.x, s.y) != (hx, hy) and G.distance(s.x, s.y, hx, hy, board) <= 1:
                near_own += 1
                assert _bin(s.x, s.y) == _bin(hx, hy) or G.distance(s.x, s.y, hx, hy, board) == 1
    assert near_own <= size
    assert min(G.distance(*a, *b, board) for i, a in enumerate(hl) for b in hl[i + 1:]) > 3
    hum = [(st.empires[i].home_x, st.empires[i].home_y) for i in (1, 2, 3)]
    assert len({_bin(*h) for h in hum}) == 3
    # humans are spread: on 4x4 they are never in neighbouring bins, on 3x3 (where every bin
    # touches every other on the torus) they are still at least a bin apart
    far = 40 if side >= 4 else 15                         # 2x2: every bin touches every other
    assert min(G.distance(*a, *b, board) for i, a in enumerate(hum) for b in hum[i + 1:]) >= far
    # deterministic, and a save round-trips with the board
    assert M.dumps(new_game("t", seed, humans, size=size)) == M.dumps(st)
    st2 = M.loads(M.dumps(st))
    assert (st2.board, st2.bins, st2.empty_bins) == (board, side, empty)


def test_bad_sizes():
    with pytest.raises(ValueError):
        new_game("t", 1, ["A"], size=10)
    with pytest.raises(ValueError):
        new_game("t", 1, [f"H{i}" for i in range(9)], size=8)


def test_old_saves_are_classic():
    st = new_game("t", 3, ["A"])
    d = M.to_dict(st)
    for k in ("board", "bins", "empty_bins", "chatter"):
        d.pop(k)
    old = M.from_dict(json.loads(json.dumps(d)))
    assert (old.board, old.bins, old.empty_bins, old.chatter) == (100, 4, [], "normal")
    run_turn(old)


def test_geometry_wraps_at_75():
    b = 75
    assert G.home_rel(b) == (37, 37) and G.home_rel() == (50, 50)
    assert G.distance(0, 0, 74, 74, b) == 1 and G.distance(0, 0, 37, 0, b) == 37
    assert G.distance(0, 0, 38, 0, b) == 37
    assert G.step(1, 1, 73, 2, 5, b) == (73, 2)          # the short way, across the seam
    for hx, hy in ((0, 0), (74, 12), (40, 70)):
        for x, y in ((0, 0), (74, 74), (37, 1), (hx, hy)):
            rx, ry = G.to_rel(x, y, hx, hy, b)
            assert 0 <= rx < b and 0 <= ry < b
            assert G.to_abs(rx, ry, hx, hy, b) == (x, y)
        assert G.to_rel(hx, hy, hx, hy, b) == (37, 37)
    # the scan mask at 75: wrap and relative rotation
    rows = scanmask.decode("", b)
    scanmask.mark(rows, 74, 0, 1, b)
    text = scanmask.encode(rows, b)
    assert len(text) == 940 and scanmask.count(text, b) == 9
    for x, y in ((73, 74), (0, 74), (0, 1), (74, 1)):
        assert scanmask.is_set(text, x, y, b)
    rel = scanmask.to_relative(text, 74, 0, b)
    assert scanmask.is_set(rel, 37, 37, b) and scanmask.is_set(rel, 38, 36, b)
    assert scanmask.count(rel, b) == 9


# ---------------------------------------------------------------- size 4 (W-26): 2x2 on 50x50
@pytest.mark.parametrize("seed", range(12))
def test_size4_board_and_home_spacing(seed):
    humans = ["Dave", "Bob", "Eve", "Ann"][: seed % 5]
    st = new_game("q", seed, humans, size=4)
    assert (st.board, st.bins, st.empty_bins, len(st.systems)) == (50, 2, [], 44)
    assert all(0 <= s.x < 50 and 0 <= s.y < 50 for s in st.systems)
    assert len({(s.x, s.y) for s in st.systems}) == 44
    homes = {e.id: (e.home_x, e.home_y) for e in st.empires.values() if e.id}
    assert sorted(_bin(*h) for h in homes.values()) == [(0, 0), (0, 1), (1, 0), (1, 1)]
    # each quadrant's share: one home, one artifact world, 11 systems placed from it
    assert sum(1 for s in st.systems if s.artifacts) == 4
    assert sum(1 for s in st.systems if s.owner) == 4
    # home spacing: at least 15 squares (a home is within 5 of its bin centre), so no empire
    # starts inside another's starting scans (home 4, scout 3), even with an EESS (10)
    d = [G.distance(*a, *b, 50) for i, a in enumerate(homes.values())
         for b in list(homes.values())[i + 1:]]
    assert 15 <= min(d) and max(d) <= 25
    for e in st.empires.values():
        if not e.id:
            continue
        h = _home_system(st, e.id)
        assert h.scan_range == 4
        for s in st.systems:
            if s.owner and s.owner != e.id:
                assert G.distance(h.x, h.y, s.x, s.y, 50) > 2 * 4 + 3
        for sh in st.live_ships():
            if sh.owner != e.id:
                assert G.distance(h.x, h.y, sh.x, sh.y, 50) > h.scan_range + sh.stype.scan
    # the turn-0 view shows no other empire
    v = view(st, initial_results(st), 1)
    assert not v["scans"]["ships"] and all(not s["owner"] or s["owner"] == 1
                                           for s in v["scans"]["systems"])


def test_size4_geometry_view_and_orders():
    b = 50
    assert G.home_rel(b) == (25, 25)
    assert G.distance(0, 0, 49, 49, b) == 1 and G.distance(0, 0, 25, 0, b) == 25
    assert G.distance(0, 0, 26, 0, b) == 24 and G.step(1, 1, 48, 2, 5, b) == (48, 2)
    for hx, hy in ((0, 0), (49, 12), (30, 47)):
        for x, y in ((0, 0), (49, 49), (25, 1), (hx, hy)):
            rx, ry = G.to_rel(x, y, hx, hy, b)
            assert 0 <= rx < b and 0 <= ry < b and G.to_abs(rx, ry, hx, hy, b) == (x, y)
        assert G.to_rel(hx, hy, hx, hy, b) == (25, 25)
    rows = scanmask.decode("", b)
    scanmask.mark(rows, 49, 0, 1, b)
    text = scanmask.encode(rows, b)
    assert len(text) == 420 and scanmask.count(text, b) == 9
    assert all(scanmask.is_set(text, x, y, b) for x, y in ((48, 49), (0, 49), (0, 1), (49, 1)))
    rel = scanmask.to_relative(text, 49, 0, b)
    assert scanmask.is_set(rel, 25, 25, b) and scanmask.count(rel, b) == 9

    st = new_game("v", 4, ["Alpha", "Bravo"], size=4)
    v = view(st, initial_results(st), 1)
    assert (v["game"]["board"], v["game"]["size"], v["game"]["bins"], v["game"]["empty_bins"]) \
        == (50, 4, 2, [])
    assert v["empire"]["home"] == {"x": 25, "y": 25}
    home = next(s for s in v["systems"] if (s["x"], s["y"]) == (25, 25))
    assert home["name"] == _home_system(st, 1).name
    pts = [(s["x"], s["y"]) for s in v["systems"] + v["known_systems"] + v["ships"]]
    assert pts and all(0 <= x < 50 and 0 <= y < 50 for x, y in pts)
    assert len(v["scan_history"]["data"]) == 420 and "y*50+x" in v["scan_history"]["encoding"]
    scout = next(s for s in st.live_ships() if s.owner == 1 and s.type == "S")
    assert check_orders(st, 1, parse_orders(f"MO {scout.number} 49 49"))[0].ok
    r = check_orders(st, 1, parse_orders(f"MO {scout.number} 50 10"))[0]
    assert not r.ok and "0 to 49" in r.error and "50x50" in r.error
    h = _home_system(st, 1)
    run_turn(st, {1: parse_orders(f"MO {scout.number} 1 1")})       # 24 squares, the short way
    sh = st.ships[scout.number]
    for _ in range(10):
        if (sh.x, sh.y) == (sh.dx, sh.dy):
            break
        run_turn(st, {})
    assert (sh.x, sh.y) == G.to_abs(1, 1, h.x, h.y, 50)
    assert scanmask.is_set(st.empires[1].scan_history, sh.x, sh.y, 50)
    mo = next(o for o in order_catalogue(50)["orders"] if o["code"] == "MO")
    assert [a["hi"] for a in mo["args"] if a["kind"] == "coord"] == [49, 49]
    assert "25,25" in order_catalogue(50)["notes"][1]


def test_size4_bot_scout_grid():
    from mhgc.npr import expand
    from mhgc.npr.world import _BOARD
    tok = _BOARD.set(50)
    try:
        assert expand._per_side() == 5 and expand._cells() == 25
        cells = {expand._cell(x, y) for x in range(50) for y in range(50)}
        assert cells == set(range(25))
        for c in range(25):
            x, y = expand._centre(c)
            assert 0 <= x < 50 and 0 <= y < 50 and expand._cell(x, y) == c
    finally:
        _BOARD.reset(tok)


def test_size4_bots_only_60_turns():
    """A 60-turn game of four computer empires: orders valid, the bots expand and meet, and the
    turns are quick.  Prints the rejection rate and timing (STATUS.md quotes them)."""
    t0 = time.perf_counter()
    s = simulate(31, 0, 60, "none", size=4)
    wall = time.perf_counter() - t0
    st = s["state"]
    _check_rejections(s)
    assert s["turns"] == 60 or st.winner is not None
    assert s["systems"][-1] >= 16 and s["ships"][-1] > s["ships"][0]
    mean = sum(s["seconds"]) / len(s["seconds"])
    assert mean < 0.3
    assert all(e.relations for e in st.empires.values() if e.id and e.alive)  # they meet
    print(f"\nsize 4 bots only: {s['turns']} turns, {s['orders']} orders, {s['rejected']} "
          f"rejected ({100 * s['rejected'] / max(1, s['orders']):.2f}%), s/turn mean "
          f"{mean:.3f} max {max(s['seconds']):.3f}, wall {wall:.1f} s, systems "
          f"{s['systems'][-1]}, mean VP {s['vp'][-1]}, top VP "
          f"{max(e.vp for e in st.empires.values() if e.id)}")


def _home_system(st, eid):
    e = st.empires[eid]
    return st.system_at(e.home_x, e.home_y)


def test_view_and_orders_at_75():
    st = new_game("v", 5, ["Alpha", "Bravo"], size=8)
    res = initial_results(st)
    v = view(st, res, 1)
    assert v["game"]["board"] == 75 and v["game"]["size"] == 8 and v["game"]["bins"] == 3
    assert v["game"]["empty_bins"] == [[1, 1]] and v["empire"]["home"] == {"x": 37, "y": 37}
    home = next(s for s in v["systems"] if (s["x"], s["y"]) == (37, 37))
    assert home["name"] == _home_system(st, 1).name
    pts = [(s["x"], s["y"]) for s in v["systems"] + v["known_systems"] + v["ships"]]
    pts += [(s["x"], s["y"]) for s in v["scans"]["systems"] + v["scans"]["ships"]]
    assert pts and all(0 <= x < 75 and 0 <= y < 75 for x, y in pts)
    data = v["scan_history"]["data"]
    assert len(data) == 940 and "y*75+x" in v["scan_history"]["encoding"]
    assert scanmask.is_set(data, 37, 37, 75)
    # MO to the far edge works (across the seam), off-board coordinates are refused clearly
    scout = next(s for s in st.live_ships() if s.owner == 1 and s.type == "S")
    r = check_orders(st, 1, parse_orders(f"MO {scout.number} 74 74"))
    assert r[0].ok, r[0].error
    r = check_orders(st, 1, parse_orders(f"MO {scout.number} 80 10"))
    assert not r[0].ok and "0 to 74" in r[0].error
    h = _home_system(st, 1)
    run_turn(st, {1: parse_orders(f"MO {scout.number} 74 74")})   # 37 squares west/south
    sh = st.ships[scout.number]
    assert G.distance(sh.x, sh.y, h.x, h.y, 75) == sh.stype.move
    for _ in range(12):
        if (sh.x, sh.y) == (sh.dx, sh.dy):
            break
        run_turn(st, {})
    assert (sh.x, sh.y) == G.to_abs(74, 74, h.x, h.y, 75)
    v = view(st, None, 1)
    assert next(s for s in v["ships"] if s["number"] == scout.number)["x"] == 74
    hist = st.empires[1].scan_history
    assert scanmask.is_set(hist, sh.x, sh.y, 75)
    # the catalogue for a 75x75 game
    cat = order_catalogue(75)
    mo = next(o for o in cat["orders"] if o["code"] == "MO")
    assert [a["hi"] for a in mo["args"] if a["kind"] == "coord"] == [74, 74]
    assert "37,37" in cat["notes"][1]
    assert [a["hi"] for a in next(o for o in order_catalogue()["orders"]
                                  if o["code"] == "MO")["args"] if a["kind"] == "coord"] == [99, 99]


GAMES = {4: (10, 1), 8: (11, 1), 9: (12, 0), 12: (13, 2), 16: (14, 1), 20: (15, 2), 25: (16, 1)}
_games: dict = {}


def _game(size):
    if size not in _games:
        seed, humans = GAMES[size]
        t0 = time.perf_counter()
        _games[size] = simulate(seed, humans, 40, "random", size=size)
        _games[size]["wall"] = time.perf_counter() - t0
    return _games[size]


@pytest.mark.parametrize("size", sorted(GAMES))
def test_bot_games_at_every_size(size):
    s = _game(size)
    st = s["state"]
    assert st.board == EXPECT[size][0] and s["turns"] == 40
    _check_rejections(s)                                  # < 0.3%, only the explained kinds
    nprs = size - GAMES[size][1]
    assert s["systems"][-1] >= 4 * nprs                   # the bots expand
    assert s["ships"][-1] > s["ships"][0]
    assert sum(s["seconds"]) / len(s["seconds"]) < 0.5
    for sh in st.live_ships():
        assert 0 <= sh.x < st.board and 0 <= sh.y < st.board
    for e in st.empires.values():
        if e.id:
            assert len(e.scan_history) in (0, 4 * -(-scanmask.nbytes(st.board) // 3))


# ---------------------------------------------------------------- API
def H(tok):
    return {"X-Seat-Token": tok}


def test_api_sizes(tmp_path):
    c = TestClient(create_app(tmp_path))
    r = c.post("/api/games", json={"password": "secret1", "humans": 2, "player": "Dave", "host_password": "secret1"})
    assert r.status_code == 200, r.text
    g = r.json()["game"]
    assert (g["size"], g["board"], g["computers"], g["empty_bins"], g["chatter"]) == \
        (8, 75, 6, [[1, 1]], "normal")
    v = c.get(f"/api/games/{r.json()['id']}/view", headers=H(r.json()["token"])).json()
    assert v["game"]["board"] == 75 and v["empire"]["home"] == {"x": 37, "y": 37}
    for size in (4, 9, 12, 16, 20, 25):
        g = c.post("/api/games", json={"password": "secret1", "humans": 1, "player": "D", "size": size, "host_password": "secret1"}).json()["game"]
        assert g["size"] == size and g["computers"] == size - 1
        assert g["board"] == {4: 50, 9: 75, 20: 125, 25: 125}.get(size, 100)
    g = c.post("/api/games", json={"password": "secret1", "humans": 3, "computers": 9, "player": "D", "host_password": "secret1"}).json()["game"]
    assert g["size"] == 12
    bad = [{"humans": 2, "player": "D", "size": 10}, {"humans": 9, "player": "D", "size": 8},
           {"humans": 5, "player": "D", "size": 4}, {"humans": 2, "player": "D", "size": 2},
           {"humans": 2, "computers": 1, "player": "D", "size": 4},
           {"humans": 2, "computers": 5, "player": "D"},
           {"humans": 2, "computers": 5, "player": "D", "size": 9}]
    for body in bad:
        assert c.post("/api/games", json=body | {"password": "secret1"}).status_code == 400, body
    assert c.post("/api/games", json={"password": "secret1", "humans": 1, "player": "D", "chatter": "loud", "host_password": "secret1"}) \
        .status_code == 422
    assert c.get("/api/orders/catalogue?board=75").json()["board"] == 75
    assert c.get("/api/orders/catalogue?board=50").json()["board"] == 50
    assert c.get("/api/orders/catalogue?board=125").json()["board"] == 125
    assert c.get("/api/orders/catalogue?board=60").status_code == 422
    sizes = c.get("/api/reference").json()["game_sizes"]
    assert [(z["size"], z["board"], z["home"]) for z in sizes] == \
        [(4, 50, [25, 25]), (8, 75, [37, 37]), (9, 75, [37, 37]), (12, 100, [50, 50]), (16, 100, [50, 50]),
         (20, 125, [62, 62]), (25, 125, [62, 62])]


def test_api_old_game_without_size_loads(tmp_path):
    app = create_app(tmp_path)
    c = TestClient(app)
    r = c.post("/api/games", json={"password": "secret1", "humans": 1, "player": "D", "size": 16, "host_password": "secret1"}).json()
    gid = r["id"]
    meta_p = tmp_path / "games" / gid / "meta.json"
    meta = json.loads(meta_p.read_text())
    del meta["size"], meta["chatter"]
    meta_p.write_text(json.dumps(meta))
    st_p = tmp_path / "games" / gid / "turns" / "0" / "state.json"
    d = json.loads(st_p.read_text())
    for k in ("board", "bins", "empty_bins", "chatter"):
        d.pop(k)
    st_p.write_text(json.dumps(d))
    c2 = TestClient(create_app(tmp_path))
    g = c2.get(f"/api/games/{gid}").json()
    assert (g["size"], g["board"], g["computers"], g["chatter"]) == (16, 100, 15, "normal")
    assert c2.post(f"/api/games/{gid}/force", headers=H(r["token"])).status_code == 200
