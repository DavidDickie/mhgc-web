"""Scan-history backfill for games that predate it (DECISIONS G-07): rebuilt from the per-turn
states on disk with the engine's own marking, it must equal what live recording produces."""
from __future__ import annotations

import json
import shutil

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from mhgc import model as M
from mhgc import scanmask
from mhgc.engine import scans

TURNS = 6


def H(tok):
    return {"X-Seat-Token": tok}


def _play(root, size, monkeypatch=None, record_from=0):
    """A 2-human game (seed fixed) over the API, scouts flying out, TURNS forced turns.  Live
    recording is switched off (the engine's marking a no-op) until turn `record_from`."""
    real = scans.mark_area_scans
    if monkeypatch is not None and record_from > 0:
        monkeypatch.setattr(scans, "mark_area_scans", lambda *a, **k: None)
    c = TestClient(create_app(root))
    g = c.post("/api/games", json={"password": "secret1", "name": "Backfill", "humans": 2, "size": size,
                                   "player": "Dave", "race": "Daves", "seed": 4711, "host_password": "secret1"}).json()
    gid, t1 = g["id"], g["token"]
    t2 = c.post(f"/api/games/{gid}/join", json={"password": "secret2", "seat": 2, "player": "Bob",
                                                "race": "Bobbers"}).json()["token"]
    for turn in range(1, TURNS + 1):
        if monkeypatch is not None and turn == record_from:
            monkeypatch.setattr(scans, "mark_area_scans", real)
        for tok, d in ((t1, (9, 5)), (t2, (-6, 9))):
            v = c.get(f"/api/games/{gid}/view", headers=H(tok)).json()
            hx = hy = v["game"]["board"] // 2
            b = v["game"]["board"]
            text = "\n".join(f"MO {s['number']} {(hx + d[0] * (i + 1)) % b} {(hy + d[1]) % b}"
                             for i, s in enumerate(v["ships"]) if s["type"] == "S")
            if text:
                c.put(f"/api/games/{gid}/orders", json={"text": text}, headers=H(tok))
        c.post(f"/api/games/{gid}/force", headers=H(t1))
    if monkeypatch is not None:
        monkeypatch.setattr(scans, "mark_area_scans", real)
    return gid, t1, t2


def _states(root, gid):
    d = root / "games" / gid / "turns"
    return {int(p.name): M.loads((p / "state.json").read_text()) for p in d.iterdir()
            if (p / "state.json").exists()}


def _as_old_save(root, gid):
    """Make the game look like a save from before the backfill existed."""
    p = root / "games" / gid / "meta.json"
    meta = json.loads(p.read_text())
    meta.pop("scan_backfill", None)
    p.write_text(json.dumps(meta))


def _without_history(st):
    d = M.to_dict(st)
    for e in d["empires"].values() if isinstance(d["empires"], dict) else d["empires"]:
        e["scan_history"] = ""
    return json.dumps(d, sort_keys=True)


@pytest.mark.parametrize("size", [8, 16])
@pytest.mark.parametrize("record_from", [TURNS + 1, 3])     # never recorded / recorded from turn 3
def test_backfill_equals_live_recording(tmp_path, monkeypatch, size, record_from):
    live_root, old_root = tmp_path / "live", tmp_path / "old"
    gid_live, *_ = _play(live_root, size)
    gid_old, t1, t2 = _play(old_root, size, monkeypatch, record_from)
    live, old = _states(live_root, gid_live), _states(old_root, gid_old)
    assert sorted(live) == sorted(old) == list(range(TURNS + 1))
    board = live[0].board
    assert board == (75 if size == 8 else 100)
    for n in live:                 # same game apart from the history
        assert _without_history(live[n]) == _without_history(old[n])
    assert all(not e.scan_history for e in old[0].empires.values())       # history is missing
    assert any(e.scan_history for e in live[0].empires.values())

    _as_old_save(old_root, gid_old)
    app = create_app(old_root)                           # loading backfills
    back = _states(old_root, gid_old)
    for n in live:
        for eid, e in live[n].empires.items():
            assert back[n].empires[eid].scan_history == e.scan_history, (n, eid)
    assert M.dumps(app.state.games[gid_old].state) == M.dumps(back[TURNS])
    assert json.loads((old_root / "games" / gid_old / "meta.json").read_text())["scan_backfill"]

    # the view (relative coordinates) matches the live game's too, current turn and history
    c_old = TestClient(app)
    for n in (0, 3, TURNS):
        a = c_old.get(f"/api/games/{gid_old}/view?turn={n}", headers=H(t1)).json()
        assert a["scan_history"]["data"]
        exp = scanmask.to_relative(live[n].empires[1].scan_history, live[n].empires[1].home_x,
                                   live[n].empires[1].home_y, board)
        assert a["scan_history"]["data"] == exp

    # idempotent: a restart does nothing, and redoing it (flag removed) writes nothing
    stamp = {n: (old_root / "games" / gid_old / "turns" / str(n) / "state.json").stat().st_mtime_ns
             for n in back}
    app2 = create_app(old_root)
    _as_old_save(old_root, gid_old)
    assert app2.state.games[gid_old].backfill_scan_history() == 0
    assert stamp == {n: (old_root / "games" / gid_old / "turns" / str(n) / "state.json")
                     .stat().st_mtime_ns for n in back}


def test_backfill_own_scans_only_and_missing_turns(tmp_path, monkeypatch):
    root = tmp_path / "old"
    gid, t1, t2 = _play(root, 16, monkeypatch, TURNS + 1)
    full = {n: dict(row) for n, row in scans.rebuild_scan_history(sorted(_states(root, gid).items()))}
    # each empire's mask is exactly the union of its own boxes; nobody else's units matter
    states = _states(root, gid)
    for n, st in states.items():
        others = M.from_dict(M.to_dict(st))
        for s in others.ships.values():
            if s.owner != 1:
                s.x = s.y = 0
        for s in others.systems:
            if s.owner not in (0, 1):
                s.pop = 0
        assert dict(next(scans.rebuild_scan_history([(n, others)]))[1])[1] == \
            dict(next(scans.rebuild_scan_history([(n, st)]))[1])[1]
    own = [0] * 100
    for n in sorted(states):
        scans.mark_area_scans(own, *scans.empire_area_scans(states[n], 1), 100)
        assert full[n][1] == scanmask.encode(own, 100)
    # an old save missing some turn states: backfill what is there
    shutil.rmtree(root / "games" / gid / "turns" / "2")
    (root / "games" / gid / "turns" / "4" / "state.json").write_text("garbage")
    _as_old_save(root, gid)
    app = create_app(root)
    assert app.state.games[gid].state.turn == TURNS
    have = {n: st for n, st in states.items() if n not in (2, 4)}
    exp = dict(scans.rebuild_scan_history(sorted(have.items())))
    d = root / "games" / gid / "turns"
    for n in have:
        st = M.loads((d / str(n) / "state.json").read_text())
        for eid, e in st.empires.items():
            assert e.scan_history == exp[n].get(eid, ""), (n, eid)
    cur = app.state.games[gid].state.empires[1].scan_history
    assert scanmask.count(cur) < scanmask.count(full[TURNS][1]) or cur == full[TURNS][1]
    assert scanmask.union(cur, full[TURNS][1]) == full[TURNS][1]              # never more
    v = TestClient(app).get(f"/api/games/{gid}/view", headers=H(t2)).json()
    e2 = app.state.games[gid].state.empires[2]
    assert v["scan_history"]["data"] == scanmask.to_relative(e2.scan_history, e2.home_x,
                                                             e2.home_y, 100)
