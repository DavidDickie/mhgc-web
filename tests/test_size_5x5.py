"""The 5x5-bin maps (Dave 2026-11-24, DECISIONS G-30): 20 empires with five empty bins a knight's
move apart, and 25 empires with none, both on 125x125.

Covers the even neighbourhood of the 20-empire pattern on the torus, the names for 25 races, the
view and orders at 125, a forced turn through the API at 25 empires, and the size limits."""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.main import create_app
from mhgc.data import constants as K
from mhgc.data.system_names import PERSONA_NAMES, RACE_NAMES
from mhgc.engine.turn import check_orders, initial_results, run_turn
from mhgc.mapgen import BIN, new_game
from mhgc.npr.naming import _base_names
from mhgc.orders import parse_orders, parse_orders_text
from mhgc.view import view

KING = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)]


def test_knights_move_pattern_is_even_on_the_torus():
    side, empty = K.GAME_SIZES[20]
    assert side == 5 and len(empty) == 5 and 25 - len(empty) == 20
    E = set(empty)
    # one per row and one per column; the empty bin in row r (by) is column (bx) 2r mod 5
    assert sorted(by for _, by in E) == list(range(5)) == sorted(bx for bx, _ in E)
    assert E == {((2 * r) % 5, r) for r in range(5)}
    for bx in range(side):
        for by in range(side):
            near = [(dx, dy) for dx, dy in KING if ((bx + dx) % side, (by + dy) % side) in E]
            if (bx, by) in E:
                assert near == []                          # no two empty bins touch
            else:                                          # every race: one side-on, one corner-on
                assert len(near) == 2
                assert sorted(abs(dx) + abs(dy) for dx, dy in near) == [1, 2]
    assert K.GAME_SIZES[25] == (5, ())
    assert K.MAX_EMPIRES == 25


def test_25_races_have_their_own_names():
    assert len(K.DEFAULT_RACE_NAMES) == len(set(K.DEFAULT_RACE_NAMES)) >= 25
    assert all(len(n) <= K.RACE_NAME_MAX for n in K.DEFAULT_RACE_NAMES)
    st = new_game("n", 2, [], size=25)
    names = [e.name for e in st.empires.values() if e.id]
    assert len(set(names)) == 25 and not any(n.startswith("Race_") for n in names)
    assert all(n in RACE_NAMES for n in names)
    # leaders and systems unique
    assert len({ld.name for ld in st.leaders.values()}) == 25
    assert len({s.name for s in st.systems}) == len(st.systems) == 275
    # a computer empire with any other name draws from its persona pool: no two of 25 share
    for persona in PERSONA_NAMES:
        seen: set[str] = set()
        for eid in range(1, K.MAX_EMPIRES + 1):
            got = _base_names("Somebody", persona, eid)
            assert len(got) == 2 and not seen & set(got)
            seen |= set(got)


def test_20_empire_map_homes_and_spacing():
    st = new_game("t", 9, ["Dave", "Bob", "Eve", "Ann"], size=20)
    assert (st.board, st.bins) == (125, 5)
    homes = {(e.home_x // BIN, e.home_y // BIN) for e in st.empires.values() if e.id}
    assert len(homes) == 20 and not homes & {tuple(b) for b in st.empty_bins}
    # every home system is a starting world, the empty bins' hearts are unowned
    assert sum(1 for s in st.systems if s.owner) == 20


def test_view_and_orders_at_125():
    st = new_game("v", 4, ["Alpha"], size=25)
    v = view(st, initial_results(st), 1)
    assert (v["game"]["board"], v["game"]["size"], v["game"]["bins"]) == (125, 25, 5)
    assert v["empire"]["home"] == {"x": 62, "y": 62}
    assert len(v["scan_history"]["data"]) == 2608
    scout = next(s for s in st.live_ships() if s.owner == 1 and s.type == "S")
    assert check_orders(st, 1, parse_orders(f"MO {scout.number} 124 124"))[0].ok
    # the parser takes coordinates up to the largest board's 124; the game checks its own board
    assert parse_orders_text(f"MO {scout.number} 125 10")[0].error == \
        "X must be between 0 and 124, not 125."
    small = new_game("s", 4, ["Alpha"], size=16)
    sc = next(s for s in small.live_ships() if s.owner == 1 and s.type == "S")
    r = check_orders(small, 1, parse_orders(f"MO {sc.number} 110 10"))[0]
    assert not r.ok and "0 to 99" in r.error
    run_turn(st, {1: parse_orders(f"MO {scout.number} 1 1")})
    assert all(0 <= sh.x < 125 and 0 <= sh.y < 125 for sh in st.live_ships())


def test_api_25_empires_and_forced_turn(tmp_path):
    c = TestClient(create_app(tmp_path))
    r = c.post("/api/games", json={"humans": 0, "size": 25, "player": "Admin", "seed": 5,
                                   "host_only": True, "host_password": "hostpw1"})
    assert r.status_code == 200, r.text
    g = r.json()["game"]
    assert (g["size"], g["board"], g["computers"], g["empty_bins"]) == (25, 125, 25, [])
    t0 = time.perf_counter()
    f = c.post(f"/api/games/{r.json()['id']}/force", json={"turns": 3},
               headers={"X-Seat-Token": r.json()["token"]})
    assert f.status_code == 200, f.text and f.json()["turn"] == 3
    assert (time.perf_counter() - t0) / 3 < 3                  # a few seconds a turn at most
    # 25 human seats fit a 25-empire game, 26 don't; 20 has 5 empty bins
    ok = c.post("/api/games", json={"password": "secret1", "humans": 25, "player": "D",
                                    "size": 25, "host_password": "secret1"})
    assert ok.status_code == 200, ok.text
    assert c.post("/api/games", json={"password": "secret1", "humans": 21, "player": "D",
                                      "size": 20, "host_password": "secret1"}).status_code in (400, 422)
    g20 = c.post("/api/games", json={"password": "secret1", "humans": 2, "computers": 18,
                                     "player": "D", "host_password": "secret1"}).json()["game"]
    assert g20["size"] == 20 and len(g20["empty_bins"]) == 5
