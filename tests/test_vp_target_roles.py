"""The per-game win target (DECISIONS G-28) and transports starting in Ground Combat (G-29)."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import create_app
from mhgc import model as M
from mhgc.data import constants as K
from mhgc.data.ships import SHIP_TYPES, TRANSPORT_CLASSES, default_role
from mhgc.engine import stats
from mhgc.mapgen import new_game
from tests.conftest import (ScriptedRng, add_ship, ctx_for, do, make_state)
from tests.test_combat import _combat


def H(tok):
    return {"X-Seat-Token": tok}


def _new(c, seed=11):
    r = c.post("/api/games", json={"password": "secret1", "humans": 1, "size": 8,
                                   "player": "Dave", "race": "Daves", "seed": seed,
                                   "host_password": "secret1"})
    assert r.status_code == 200, r.text
    return r.json()["id"], r.json()["token"]


# ---- G-28: the win target -----------------------------------------------------------------

def test_new_games_play_to_100():
    assert K.VICTORY_POINTS == 100 and K.LEGACY_VICTORY_POINTS == 90
    st = new_game("g", 3, ["Daves"])
    assert st.vp_to_win == 100
    assert M.loads(M.dumps(st)).vp_to_win == 100                 # stored with the game


def test_saves_without_the_field_keep_90():
    """Saves from before G-28 were moved to 90 by G-26, so they keep playing to 90."""
    d = M.to_dict(new_game("g", 3, ["Daves"]))
    d.pop("vp_to_win")
    assert M.from_dict(d).vp_to_win == 90
    d["vp_to_win"] = 75                                          # a stored target is kept
    assert M.from_dict(d).vp_to_win == 75


def test_victory_uses_the_games_own_target():
    st = make_state()
    ctx = ctx_for(st)
    stats.compute_stats(ctx)
    st.vp_to_win = 90                                            # an old game
    st.empires[1].vp = 95
    stats.check_victory(ctx)
    assert st.winner == 1
    st2 = make_state()
    ctx2 = ctx_for(st2)
    stats.compute_stats(ctx2)
    assert st2.vp_to_win == 100
    st2.empires[1].vp = 95                                       # not enough at 100
    stats.check_victory(ctx2)
    assert st2.winner is None
    st2.empires[1].vp = 100
    stats.check_victory(ctx2)
    assert st2.winner == 1


def test_api_view_and_summary_show_the_target(tmp_path):
    c = TestClient(create_app(tmp_path))
    gid, tok = _new(c)
    assert c.get(f"/api/games/{gid}").json()["vp_to_win"] == 100
    assert c.get(f"/api/games/{gid}/view", headers=H(tok)).json()["game"]["vp_to_win"] == 100
    assert c.get("/api/reference").json()["victory_points"] == 100


def test_an_old_game_on_disk_keeps_90(tmp_path):
    c = TestClient(create_app(tmp_path))
    gid, tok = _new(c)
    p = tmp_path / "games" / gid / "turns" / "0" / "state.json"
    d = json.loads(p.read_text())
    d.pop("vp_to_win")
    p.write_text(json.dumps(d))
    c2 = TestClient(create_app(tmp_path))                        # a restart loads it again
    assert c2.get(f"/api/games/{gid}").json()["vp_to_win"] == 90
    assert c2.get(f"/api/games/{gid}/view", headers=H(tok)).json()["game"]["vp_to_win"] == 90
    c2.post(f"/api/games/{gid}/force", headers=H(tok))           # and a turn keeps it
    assert c2.app.state.games[gid].state.vp_to_win == 90


# ---- G-29: transports start in Ground Combat ----------------------------------------------

def test_default_roles_by_class():
    assert TRANSPORT_CLASSES == {"T", "MT"}
    for code in SHIP_TYPES:
        assert default_role(code) == ("GC" if code in ("T", "MT") else "SC"), code
    assert default_role("AT") == "SC" and default_role("MCS") == "SC"   # armed cargo ships


def test_starting_transport_is_gc():
    st = new_game("g", 5, ["Daves"])
    for sh in st.ships.values():
        assert sh.role == ("GC" if sh.type == "T" else "SC"), sh.type


def test_built_transport_is_gc_unless_a_role_is_given():
    st = make_state()
    st.empires[1].techs |= {40}                                  # Improved Transports: MT
    ctx = ctx_for(st)
    st.systems[0].starport = 4
    before = set(st.ships)
    for line in ("BS H1 T", "BS H1 S", "BS H1 T F SC", "BS H1 MT N"):
        r = do(ctx, 1, line)
        assert r.ok, (line, r.error)
    new = [st.ships[n] for n in sorted(set(st.ships) - before, key=lambda n: st.ships[n].number)]
    got = sorted((sh.type, sh.role) for sh in new)
    assert got == sorted([("T", "GC"), ("S", "SC"), ("T", "SC"), ("MT", "GC")])
    ctx2 = ctx_for(st)
    before = set(st.ships)
    assert do(ctx2, 1, "BS H1 T RD").ok                          # a role given wins
    assert [st.ships[n].role for n in set(st.ships) - before] == ["RD"]


def test_existing_ships_keep_their_role_on_load():
    st = make_state()
    t = add_ship(st, 1, "T", 10, 10, role="SC")                  # an old save's transport
    assert M.loads(M.dumps(st)).ships[t.number].role == "SC"


def test_fleet_roles_still_apply_to_a_gc_transport():
    st = make_state()
    ctx = ctx_for(st)
    t = add_ship(st, 1, "T", 10, 10, role="GC")
    f = add_ship(st, 1, "F", 10, 10)
    assert do(ctx, 1, "CF Wing 50 50").ok
    assert do(ctx, 1, f"AF Wing {t.number} {f.number}").ok
    assert do(ctx, 1, "CFCR Wing DF").ok
    assert t.role == "SC"                                        # DF: all non-attacks SC
    assert do(ctx, 1, "CFCR Wing PT").ok
    assert t.role == "RD"                                        # PT: non-attacks RD


def test_gc_transport_is_shot_after_sc_ships_and_changes_nothing_else():
    """A 0-attack GC transport adds nothing to bombardment or SC, is not shifted to SC, and is
    fired on after the owner's SC ships (combat role order SC, MR, GC, RD)."""
    st = make_state()
    add_ship(st, 1, "D", 70, 70, posture="H")                    # attack 3
    sc = add_ship(st, 2, "S", 70, 70, posture="F", role="SC")
    gc = add_ship(st, 2, "T", 70, 70, posture="F", role="GC")
    rng = ScriptedRng(chance=False)
    rng.between = lambda lo, hi: 1                               # effective attack 1
    ctx, c = _combat(st, 70, 70, rng, system=False)
    rel = c.relation(1, 2)
    c.assign_roles(2)
    assert c.roles[gc.number] == ("GC", 0) and c.pool(2, "SC") == 0
    c.space_combat()
    assert not sc.alive and gc.alive
    # posture decides relations and surprise, not the role
    st2 = make_state()
    add_ship(st2, 1, "D", 70, 70, posture="H")
    add_ship(st2, 2, "S", 70, 70, posture="F", role="SC")
    add_ship(st2, 2, "T", 70, 70, posture="F", role="SC")
    _, c2 = _combat(st2, 70, 70, ScriptedRng(chance=False), system=False)
    assert c2.relation(1, 2) == rel
