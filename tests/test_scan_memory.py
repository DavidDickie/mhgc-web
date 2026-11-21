"""Scan history (every square ever scanned) and sticky map memory (habitability, MR/AR) -
DECISIONS G-07 and G-08 (Dave 2026-11-13)."""
from __future__ import annotations

import json

from mhgc import geometry as G
from mhgc import model as M
from mhgc import scanmask
from mhgc.engine.turn import initial_results, run_turn
from mhgc.mapgen import new_game
from mhgc.view import view

A, B = 1, 2


def _home(st, eid):
    e = st.empires[eid]
    return st.system_at(e.home_x, e.home_y)


def _place(sh, x, y):
    sh.x, sh.y, sh.ox, sh.oy, sh.dx, sh.dy = x, y, x, y, x, y


def _far_from_everything_of(st, eid, x0, y0, min_d=25):
    """A square at least `min_d` from every ship and populated system of `eid`."""
    mine = [(s.x, s.y) for s in st.systems if s.owner == eid] + \
           [(s.x, s.y) for s in st.live_ships() if s.owner == eid]
    for d in range(0, 100):
        x, y = (x0 + d) % 100, (y0 + 37) % 100
        if all(G.distance(x, y, a, b) >= min_d for a, b in mine):
            return x, y
    raise AssertionError("no free square")


def _setup():
    st = new_game("scanmem", 4242, ["Alpha", "Bravo"])
    initial_results(st)
    home = _home(st, A)
    scout = next(s for s in st.live_ships() if s.owner == A and s.type == "S")
    others = [s for s in st.live_ships() if s.owner == A and s is not scout]
    for sh in others:                      # keep the rest at home
        _place(sh, home.x, home.y)
    # a target system nobody of A's has seen, well away from A's home
    target = max((s for s in st.systems if s.owner == 0),
                 key=lambda s: G.distance(home.x, home.y, s.x, s.y) if
                 G.distance(home.x, home.y, s.x, s.y) < 30 else -1)
    assert target.id not in st.empires[A].seen_systems
    return st, home, scout, target


def _rel(st, eid, x, y):
    e = st.empires[eid]
    return G.to_rel(x, y, e.home_x, e.home_y)


def test_history_accumulates_and_round_trips():
    st, home, scout, target = _setup()
    e = st.empires[A]
    assert e.scan_history                                  # the initial scans count
    start = scanmask.count(e.scan_history)
    assert scanmask.is_set(e.scan_history, home.x, home.y)
    _place(scout, target.x, target.y)
    run_turn(st, {})
    assert scanmask.is_set(e.scan_history, target.x, target.y)
    after1 = scanmask.count(e.scan_history)
    assert after1 > start
    # move the scout far away: the old square stays in the history but is no longer scanned
    fx, fy = _far_from_everything_of(st, A, target.x, target.y)
    _place(scout, fx, fy)
    res = run_turn(st, {})
    assert scanmask.is_set(e.scan_history, target.x, target.y)
    assert scanmask.is_set(e.scan_history, fx, fy)
    assert scanmask.count(e.scan_history) > after1
    # exactly the squares the empire's own scans covered, and nothing else
    rows = [0] * 100
    # rebuild independently: every square within reach of the three scout positions or home
    for (x, y, r) in [(target.x, target.y, scout.stype.scan), (fx, fy, scout.stype.scan)]:
        scanmask.mark(rows, x, y, r)
    hist = scanmask.decode(e.scan_history)
    assert all(h & r == r for h, r in zip(hist, rows))
    never = _far_from_everything_of(st, A, fx + 30, fy)
    if G.distance(never[0], never[1], target.x, target.y) > 10:
        assert not scanmask.is_set(e.scan_history, *never)
    # view: relative coordinates, encoded, not 10,000 cells
    v = view(st, res, A)
    mask = v["scan_history"]["data"]
    assert isinstance(mask, str) and len(mask) == 1668
    assert scanmask.is_set(mask, *_rel(st, A, target.x, target.y))
    assert scanmask.is_set(mask, 50, 50)                   # home is 50,50 in relative coordinates
    assert scanmask.count(mask) == scanmask.count(e.scan_history)
    # save / load round trip
    st2 = M.loads(M.dumps(st))
    assert st2.empires[A].scan_history == e.scan_history
    # an old save (no field) loads as an empty history and the view still works
    d = M.to_dict(st)
    for ed in d["empires"].values():
        ed.pop("scan_history", None)
    old = M.from_dict(d)
    assert old.empires[A].scan_history == ""
    assert view(old, res, A)["scan_history"]["data"] == ""


def test_history_is_own_scans_only_and_not_leaked():
    st, home, scout, target = _setup()
    _place(scout, target.x, target.y)
    res = run_turn(st, {})
    a, b = st.empires[A], st.empires[B]
    assert not scanmask.is_set(b.scan_history, target.x, target.y) or \
        any(G.distance(s.x, s.y, target.x, target.y) <= 10 for s in st.systems if s.owner == B)
    vb = json.dumps(view(st, res, B))
    assert a.scan_history not in vb
    assert scanmask.to_relative(a.scan_history, b.home_x, b.home_y) not in vb
    # B's view is unchanged whatever A's history holds
    before = json.dumps(view(st, res, B), sort_keys=True)
    a.scan_history = scanmask.encode([(1 << 100) - 1] * 100)
    assert json.dumps(view(st, res, B), sort_keys=True) == before


def test_mask_helpers():
    rows = [0] * 100
    scanmask.mark(rows, 99, 0, 1)                          # wraps on both axes
    t = scanmask.encode(rows)
    for x, y in [(98, 99), (0, 99), (98, 1), (0, 0), (99, 0)]:
        assert scanmask.is_set(t, x, y)
    assert scanmask.count(t) == 9
    assert not scanmask.is_set(t, 1, 0)
    r = scanmask.to_relative(t, 99, 0)                     # home at 99,0 -> 50,50
    assert scanmask.is_set(r, 50, 50) and scanmask.is_set(r, 49, 49) and scanmask.count(r) == 9
    assert scanmask.decode("") == [0] * 100 and scanmask.encode([0] * 100) == ""


def test_memory_keeps_hab_and_resources_after_leaving_range_and_updates_on_rescan():
    st, home, scout, target = _setup()
    target.hab, target.mr, target.ar = 4, True, False
    _place(scout, target.x, target.y)
    run_turn(st, {})
    seen_turn = st.turn
    info = st.empires[A].seen_systems[target.id]
    assert (info["hab"], info["mr"], info["ar"], info["detail_turn"]) == (4, True, False, seen_turn)
    # leave scan range
    _place(scout, *_far_from_everything_of(st, A, target.x, target.y))
    target.hab, target.ar = 5, True                       # changes A can't see
    res = run_turn(st, {})
    v = view(st, res, A)
    assert target.id not in {s["id"] for s in v["scans"]["systems"]}
    k = next(s for s in v["known_systems"] if s["id"] == target.id)
    assert (k["hab"], k["hab_value"], k["mr"], k["ar"]) == ("VH", 4, True, False)
    assert k["details_turn"] == seen_turn and k["last_seen"] == seen_turn
    # a long scan (one square off) refreshes name/owner but keeps the short scan's facts
    _place(scout, (target.x + 1) % 100, target.y)
    res = run_turn(st, {})
    info = st.empires[A].seen_systems[target.id]
    assert info["turn"] == st.turn and info["detail_turn"] == seen_turn and info["hab"] == 4
    v = view(st, res, A)
    sc = next(s for s in v["scans"]["systems"] if s["id"] == target.id)
    assert sc["level"] == "long" and sc["hab"] == "VH" and sc["details_turn"] == seen_turn
    # a short rescan updates them
    _place(scout, target.x, target.y)
    res = run_turn(st, {})
    info = st.empires[A].seen_systems[target.id]
    assert (info["hab"], info["ar"], info["detail_turn"]) == (5, True, st.turn)
    sc = next(s for s in view(st, res, A)["scans"]["systems"] if s["id"] == target.id)
    assert sc["level"] == "short" and sc["hab"] == "EH" and sc["hab_value"] == 5 and sc["ar"]
    # round trip, and an old memory entry (no hab fields) loads and shows no hab
    st2 = M.loads(M.dumps(st))
    assert st2.empires[A].seen_systems[target.id]["hab"] == 5
    st2.empires[A].seen_systems[target.id] = {"turn": 1, "name": target.name, "owner": None}
    _place(st2.ships[scout.number], *_far_from_everything_of(st2, A, target.x, target.y))
    res2 = run_turn(st2, {})
    k = next(s for s in view(st2, res2, A)["known_systems"] if s["id"] == target.id)
    assert "hab" not in k and "mr" not in k and "details_turn" not in k


def test_never_short_scanned_system_exposes_no_hab_or_resources():
    st, home, scout, target = _setup()
    near = [s for s in st.systems if s.owner == 0 and s.id not in st.empires[A].seen_systems
            and s is not target]
    longonly = near[0]
    never = next(s for s in near[1:] if G.distance(s.x, s.y, longonly.x, longonly.y) > 12
                 and G.distance(s.x, s.y, home.x, home.y) > 12)
    longonly.hab = never.hab = 5
    longonly.mr = longonly.ar = never.mr = never.ar = True
    _place(scout, (longonly.x + 1) % 100, longonly.y)
    res = run_turn(st, {})
    v = view(st, res, A)
    sc = next(s for s in v["scans"]["systems"] if s["id"] == longonly.id)
    assert sc["level"] == "long"
    for d in [sc] + [s for s in v["known_systems"] if s["id"] == longonly.id]:
        assert not {"hab", "hab_value", "mr", "ar", "details_turn"} & set(d)
    assert "hab" not in st.empires[A].seen_systems[longonly.id]
    ids = {s["id"] for s in v["known_systems"]} | {s["id"] for s in v["scans"]["systems"]}
    assert never.id not in ids
    # differential: changing the unseen system's facts changes nothing in A's view
    before = json.dumps(v, sort_keys=True)
    never.hab, never.mr, never.ar = 1, False, False
    longonly.hab, longonly.mr, longonly.ar = 1, False, False
    assert json.dumps(view(st, res, A), sort_keys=True) == before
