"""The per-player read model (mhgc/view.py): fog of war, relative coordinates, no leaks."""
from __future__ import annotations

import copy
import json

from mhgc import model as M
from mhgc.engine.turn import initial_results, run_turn
from mhgc.mapgen import new_game
from mhgc.orders import parse_orders
from mhgc.view import view

A, B = 1, 2


def _renumber_ships(st, eid, base):
    """Give empire `eid`'s ships distinctive numbers, so a leak is easy to spot."""
    for i, old in enumerate(sorted(n for n, s in st.ships.items() if s.owner == eid)):
        sh = st.ships.pop(old)
        sh.number = base + i
        st.ships[sh.number] = sh
        for t in st.troops.values():
            if t.ship == old:
                t.ship = sh.number


def _home(st, eid):
    e = st.empires[eid]
    return st.system_at(e.home_x, e.home_y)


def _game(turns=3, history=None):
    st = new_game("leak", 4242, ["Alpha", "Bravo"])
    _renumber_ships(st, B, 990001)
    bh = _home(st, B)
    st.leaders[next(l.id for l in st.leaders.values() if l.owner == B)].name = "ZZSECRETLDR"
    res = initial_results(st)
    for t in range(turns):
        orders = {B: parse_orders(f"BS {bh.name} F\nCFXY ZZSECRETFL 50 50\nECHO ZZSECRETECHO\n"
                                  f"MESSAGE {st.empires[3].name}\nZZSECRETMSG\n.")
                  if t == 0 else []}
        res = run_turn(st, orders)
        if history is not None:
            history.append(res)
        for f in [f for f in st.fleets.values() if f.owner == B and f.number < 990000]:
            old = f.number                        # distinctive fleet numbers too
            f.number = 990500 + old
            st.fleets[f.number] = st.fleets.pop(old)
            for sh in st.ships.values():
                if sh.fleet == old:
                    sh.fleet = f.number
    return st, res


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _ints(obj):
    if isinstance(obj, bool):
        return
    if isinstance(obj, int):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k.isdigit():
                yield int(k)
            yield from _ints(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _ints(v)


def test_own_objects_in_full_and_relative():
    st, res = _game(1)
    v = view(st, res, A)
    assert v["empire"]["id"] == A and v["empire"]["home"] == {"x": 50, "y": 50}
    home = _home(st, A)
    sysv = next(s for s in v["systems"] if s["id"] == home.id)
    assert (sysv["x"], sysv["y"]) == (50, 50)
    assert sysv["au"] == home.au and sysv["iu"] == home.iu
    assert sysv["governor"] == "Emperor_1"
    assert {s["number"] for s in v["ships"]} == {n for n, s in st.ships.items() if s.owner == A}
    assert all((s["x"], s["y"]) == (50, 50) for s in v["ships"])
    assert v["empire"]["eu"] == st.empires[A].eu
    assert "home_x" not in json.dumps(v)          # absolute home position never sent
    # the same holds for B in B's own view: its home is at 50,50 too
    vb = view(st, res, B)
    assert next(s for s in vb["systems"] if s["id"] == _home(st, B).id)["x"] == 50


def test_view_is_json_serialisable_and_survives_results_round_trip():
    st, res = _game(2)
    v1 = view(st, res, A)
    v2 = view(st, json.loads(json.dumps(res.to_dict())), A)
    assert json.loads(json.dumps(v1)) == json.loads(json.dumps(v2))


def test_no_markers_of_unscanned_empire_in_view():
    hist = []
    st, res = _game(3, hist)
    st.empires[B].eu = 987001
    st.empires[B].iu_depot = 987002
    bh = _home(st, B)
    bh.au, bh.iu = 987003, 987004
    assert st.empires[A].relations.get(B) is None, "fixture: A must not have met B"
    v = view(st, res, A)
    text = json.dumps(v)
    for marker in ("ZZSECRETLDR", "ZZSECRETFL", "ZZSECRETECHO", "ZZSECRETMSG", bh.name,
                   "Bravo"):
        assert marker not in text, marker
    ints = set(_ints(v))
    b_ids = ({n for n, s in st.ships.items() if s.owner == B}
             | {f.number for f in st.fleets.values() if f.owner == B}
             | {t.number for t in st.troops.values() if t.owner == B}
             | {987001, 987002, 987003, 987004})
    assert any(n >= 990001 for n, s in st.ships.items() if s.owner == B)
    assert not (ints & b_ids), ints & b_ids
    # no B system (by id) anywhere: not in systems, scans or the map memory
    b_sys = {s.id for s in st.systems if s.owner == B}
    for d in _walk(v):
        if "id" in d and "x" in d:
            assert d["id"] not in b_sys
    # the B home's position, in A's coordinates, carries nothing
    from mhgc.geometry import to_rel
    ea = st.empires[A]
    bpos = to_rel(bh.x, bh.y, ea.home_x, ea.home_y)
    assert not [d for d in _walk(v) if (d.get("x"), d.get("y")) == bpos]
    # B really did all of that (so the test isn't vacuous)
    assert any(f.name == "ZZSECRETFL" for f in st.fleets.values())
    assert "ZZSECRETECHO" in json.dumps(hist[0].to_dict()["reports"][B])
    assert "ZZSECRETMSG" in json.dumps(hist[0].to_dict()["reports"][3])
    for r in hist:                                # and no earlier turn's view leaks it either
        assert "ZZSECRETECHO" not in json.dumps(view(st, r, A))
        assert "ZZSECRETMSG" not in json.dumps(view(st, r, A))


def test_view_unchanged_by_anything_private_to_b():
    """Differential proof: scramble everything about B that A hasn't scanned, plus B's whole
    report; A's view must be byte-for-byte identical."""
    st, res = _game(3)
    rd = res.to_dict()
    # give A contact with B (both neutral) so B shows up as a race; then B secretly allies A
    st.empires[A].relations[B] = "N"
    st.empires[B].relations[A] = "N"
    before = json.dumps(view(st, rd, A), sort_keys=True)

    st2 = M.from_dict(M.to_dict(st))
    rd2 = copy.deepcopy(rd)
    eb = st2.empires[B]
    eb.relations[A] = "A"                         # rules:735-737: A can't know this
    eb.eu, eb.iu_depot, eb.techs, eb.vp = 5, 6, {0, 1, 2, 3}, 77
    eb.stats = {"GNP": 1.0}
    eb.split_trade, eb.deny_trade = {A: 50}, {A: 25}
    eb.seen_systems = {}
    eb.scan_history = ""
    for s in st2.systems:
        if s.owner == B:
            s.au, s.iu, s.pop, s.starport, s.infra = 1, 2, 3.0, 4, 5
            s.csp_au, s.csp_iu, s.csp_eu = 10, 10, 80
            s.artifacts = {"PD"}
    for sh in st2.ships.values():
        if sh.owner == B:
            sh.x, sh.y, sh.dx, sh.dy = (sh.x + 1) % 100, sh.y, 3, 4
            sh.cargo_au, sh.posture = 9, "H"
    for ld in st2.leaders.values():
        if ld.owner == B:
            ld.name, ld.combat, ld.intel = "Other", 10, 11
    st2.spies[424242] = M.Spy(424242, B, _home(st2, A).id, mission="SOS")
    rd2["reports"][B] = {"empire": B, "orders": [{"text": "X"}], "events": [], "messages": [],
                         "combats": [], "scans": {"ships": [{"number": 1}]}, "stats": {},
                         "maintenance": [], "economy": {}}
    after = json.dumps(view(st2, rd2, A), sort_keys=True)
    assert before == after
    race = next(r for r in json.loads(after)["races"] if r["id"] == B)
    assert race["our_stance"] == "N" and set(race) == {"id", "name", "kind", "our_stance",
                                                       "deny_trade", "split_trade"}


def test_scanned_enemy_ship_is_visible_but_nothing_else():
    st, res = _game(1)
    ha = _home(st, A)
    near = next(s for s in st.ships.values() if s.owner == B and s.type == "T")
    far = next(s for s in st.ships.values() if s.owner == B and s.type == "S")
    near.x, near.y = (ha.x + 2) % 100, ha.y              # inside the home's scan range (4)
    near.dx, near.dy = near.x, near.y
    near.fleet = None                                   # out of B's fleet ZZSECRETFL (CFXY)
    st.empires[B].eu = 987001
    res = run_turn(st, {})
    v = view(st, res, A)
    seen = {s["number"]: s for s in v["scans"]["ships"]}
    assert near.number in seen and seen[near.number]["level"] == "long"
    assert (seen[near.number]["x"], seen[near.number]["y"]) == (52, 50)
    assert "cargo" not in seen[near.number] and "posture" not in seen[near.number]
    assert far.number not in set(_ints(v))
    assert 987001 not in set(_ints(v))
    # scanning made contact: B is a known race now, with only A's stance shown
    assert [r["name"] for r in v["races"] if r["id"] == B] == ["Bravo"]
    # and the same square gives a short-range scan (posture, cargo)
    near.x, near.y, near.dx, near.dy = ha.x, ha.y, ha.x, ha.y
    near.fleet = None
    res = run_turn(st, {})
    v = view(st, res, A)
    s = next(s for s in v["scans"]["ships"] if s["number"] == near.number)
    assert s["level"] == "short" and "cargo" in s and (s["x"], s["y"]) == (50, 50)


def test_results_only_for_this_empire_and_messages_addressed_to_it():
    st = new_game("msg", 7, ["Alpha", "Bravo", "Charlie"])
    initial_results(st)
    res = run_turn(st, {A: parse_orders("ECHO hello-from-a\nMESSAGE Bravo\nfor bravo only\n."),
                        3: parse_orders("ECHO charlie-secret\nMESSAGE\nto everyone\n.")})
    vb = json.dumps(view(st, res, B))
    vc = json.dumps(view(st, res, 3))
    assert "for bravo only" in vb and "for bravo only" not in vc
    assert "to everyone" in vb and "hello-from-a" not in vb and "charlie-secret" not in vb
    assert "charlie-secret" in vc


def test_combat_logs_only_for_participants_and_relative():
    st = new_game("war", 11, ["Alpha", "Bravo", "Charlie"])
    initial_results(st)
    ha = _home(st, A)
    for sh in st.ships.values():
        if sh.owner == B:
            sh.x, sh.y, sh.dx, sh.dy = ha.x, ha.y, ha.x, ha.y
            sh.posture = "H"
            sh.type = "C"
    st.empires[A].relations[B] = "W"
    st.empires[B].relations[A] = "W"
    res = run_turn(st, {})
    assert res.combats, "fixture should produce a combat"
    va, vc = view(st, res, A), view(st, res, 3)
    assert va["results"]["combats"] and not vc["results"]["combats"]
    c = va["results"]["combats"][0]
    assert (c["x"], c["y"]) == (50, 50)
    # the ground forces before -> after (2026-11-16) are the participants' only
    assert {g["owner"] for g in c["ground"]} <= set(c["participants"])
    assert all(set(g) == {"owner", "before", "after"} for g in c["ground"])


def test_unowned_and_rebel_labels():
    """Dave 2026-11-12 (DECISIONS G-05): empire 0 with no population is "Unowned", with
    population "Rebels"; troops of empire 0 are always "Rebels".  Decided in view.py."""
    from tests.conftest import add_ship, add_troop, make_state, sysn
    st = make_state()
    e1, e2, h1 = sysn(st, "E1"), sysn(st, "E2"), sysn(st, "H1")
    e2.pop, e2.happy = 3.0, 0.4                          # a rebel-held system
    add_ship(st, 1, "S", e1.x, e1.y, number=501)         # short scans E1 and E2
    add_troop(st, 0, "M", system=h1.id, number=601)      # a rebel militia on our home
    res = initial_results(st)
    v = view(st, res, 1)
    scans = {s["id"]: s for s in v["scans"]["systems"]}
    assert scans[e1.id]["owner_kind"] == "unowned" and scans[e1.id]["owner_name"] == "Unowned"
    assert scans[e2.id]["owner_kind"] == "rebels" and scans[e2.id]["owner_name"] == "Rebels"
    assert all(s["owner"] == 0 for s in scans.values())
    known = {s["id"]: s for s in v["known_systems"]}
    assert (known[e1.id]["owner_kind"], known[e1.id]["owner_name"]) == ("unowned", "Unowned")
    assert (known[e2.id]["owner_kind"], known[e2.id]["owner_name"]) == ("rebels", "Rebels")
    home = next(s for s in v["systems"] if s["id"] == h1.id)
    assert [t["owner_name"] for t in home["troops"] if t["number"] == 601] == ["Rebels"]
    # a long scan (no population shown) is decided from the true state, including results
    # stored before 2026-11-12 that said owner None / "Unknown"
    rd = json.loads(json.dumps(res.to_dict()))          # as stored in results.json
    rep = rd["reports"]["1"]
    rep["scans"]["systems"] = [
        {"id": e1.id, "name": "E1", "x": 0, "y": 0, "level": "long", "owner": None,
         "owner_name": "Unknown"},
        {"id": e2.id, "name": "E2", "x": 2, "y": 0, "level": "long", "owner": None,
         "owner_name": "Unknown"}]
    v2 = {s["id"]: s for s in view(st, rd, 1)["scans"]["systems"]}
    assert v2[e1.id]["owner_name"] == "Unowned" and v2[e2.id]["owner_name"] == "Rebels"
    assert "pop" not in v2[e2.id]                       # still no population on a long scan
    # map memory without the stored label (older saves) falls back to the system's state
    for s in (e1, e2):
        st.empires[1].seen_systems[s.id].pop("independent", None)
    known = {s["id"]: s for s in view(st, res, 1)["known_systems"]}
    assert known[e1.id]["owner_name"] == "Unowned" and known[e2.id]["owner_name"] == "Rebels"
