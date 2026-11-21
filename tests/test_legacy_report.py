"""The classic text report (mhgc/legacy_report.py, GET /api/games/{gid}/report.txt).

It is a pure function of one empire's view (plus, for INITIAL STOCKS, the same empire's view of
the turn before), so: its sections come in the 2008 order, its numbers are the structured
results' numbers, it carries nothing another empire keeps private (the view's differential and
marker tests, repeated on the text), and the endpoint has /view's permissions and returns exactly
the report of the views /view returns."""
from __future__ import annotations

import copy
import re

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from mhgc import model as M
from mhgc.engine.turn import initial_results, run_turn
from mhgc.legacy_report import legacy_report
from mhgc.mapgen import new_game
from mhgc.orders import parse_orders
from mhgc.view import view

SECTIONS = ["MHGC GAME", "BEGINNING OF TURN REPORT", "ORDER PROBLEMS (if any)", "MESSAGES ",
            "REBELLION (if any)", "MAINTENANCE LISTING", "COMBAT DROPS (if any)", "COMBAT (if any)",
            "RANDOM EVENTS (if any)", "STAFF REPORTS:", "ECONOMIC REPORT", "VICTORY POINT  REPORT",
            "STATISTICS REPORT", "REPORT ON RELATIONS WITH OTHER EMPIRES", "LEADER TRANSIT REPORT",
            "INTELLIGENCE REPORT", "SHIP REPORTS FOR YOUR SHIPS:", "FLEET REPORTS",
            "HOME WORLD REPORTS:", "SHIPS SCANNED:", "FLEETS SCANNED", "SYSTEMS SCANNED:"]


@pytest.fixture(scope="module")
def rich():
    """An 8-empire bot game run to a turn where some empire has battles, spy reports and a
    message: (state before, state after, results, empire)."""
    st = new_game("Classic", 77, ["Alpha"], size=8)
    initial_results(st)
    for _ in range(80):
        before = M.from_dict(M.to_dict(st))
        res = run_turn(st, {})
        rd = res.to_dict()
        for k, rep in rd["reports"].items():
            if rep["combats"] and rep["messages"] and any(e["section"] == "spies" for e in rep["events"]):
                return before, st, rd, int(k)
    pytest.fail("no turn with combat, spies and a message")


def _report(rich):
    before, st, rd, eid = rich
    v = view(st, rd, eid)
    prev = view(before, None, eid)
    return v, prev, legacy_report(v, prev)


def _nums(line):
    return [int(re.sub(r"\s+", "", x)) for x in re.findall(r"[+-]?\s*\d+", line)]


def test_sections_in_the_classic_order(rich):
    v, _, text = _report(rich)
    at = [text.find(s) for s in SECTIONS]
    assert all(i >= 0 for i in at), [s for s, i in zip(SECTIONS, at) if i < 0]
    assert at == sorted(at), "sections out of order"
    assert f"TURN {v['results']['turn']}" in text.splitlines()[0]
    assert "_/_/_/" in text                                       # the banner
    assert "MESSAGE RECEIVED VIA SUBETHERAL BROADBASE SENSORS:" in text
    assert "============COMBAT RESULTS FOR" in text and "======CONFLICT RESOLUTION======" in text
    assert "====RACE RELATIONS====" in text and "============END OF THIS COMBAT============" in text
    assert text.count("============END OF THIS COMBAT============") == len(v["results"]["combats"])
    assert "\t" in text and "CT NUM: " in text and not re.search(r"CT NUM: \d+  ", text)


def test_numbers_match_the_structured_results(rich):
    v, prev, text = _report(rich)
    r = v["results"]
    lines = text.splitlines()
    led = {}
    for line in r["maintenance"]:
        led.setdefault(line["kind"], []).append(line)
    # empire totals
    fin = next(ln for ln in lines if ln.startswith("FINAL IU / EU TOTAL:"))
    assert _nums(fin) == [led["final"][0]["iu"], led["final"][0]["eu"]]
    ini = next(ln for ln in lines if ln.startswith("IU SUPPLY DEPOT / EU STOCKPILE INITIAL:"))
    assert _nums(ini) == [led["initial"][0]["iu"], led["initial"][0]["eu"]]
    comb = next(ln for ln in lines if ln.startswith("COMBINED MAINT COSTS:"))
    upkeep = [q for k in ("ship", "ct", "spy") for q in led.get(k, [])]
    assert _nums(comb) == [-sum(q["iu"] for q in upkeep), -sum(q["eu"] for q in upkeep)]
    # the running stockpile reconciles: beginning - upkeep (+ autosupply) = final
    beg = _nums(next(ln for ln in lines if ln.startswith("BEGINNING IU SUPPLIES/EU STOCKPILE")))
    auto = sum(q["iu"] for q in led.get("autosisd", []))
    assert beg[1] + sum(q["eu"] for q in upkeep) == led["final"][0]["eu"]
    assert beg[0] + auto + sum(q["iu"] for q in upkeep) == led["final"][0]["iu"]
    # every system block: production, food and the end-of-turn stocks
    for s in v["systems"]:
        i = lines.index(f"SYSTEM {s['name']}")
        block = lines[i:lines.index("", i)]
        prod = next(ln for ln in block if ln.strip().startswith("PRODUCTION"))
        p = s["production"]
        assert _nums(prod) == [p["au"], p["iu"], p["eu"]]
        assert _nums(next(ln for ln in block if "AU EATEN BY" in ln))[-1] == -p["eaten"]
        assert _nums(block[-1])[:2] == [s["au"], s["iu"]] and block[-1].startswith("TOTAL")
        prof = next(ln for ln in block if ln.strip().startswith("PROFILE"))
        assert _nums(prof) == [s["profile"]["au"], s["profile"]["iu"], s["profile"]["eu"]]
        ps = next((q for q in prev["systems"] if q["id"] == s["id"]), None)
        if ps:
            assert _nums(block[1])[:2] == [ps["au"], ps["iu"]]
    # staff reports
    e = r["economy"]
    i = lines.index("ECONOMIC REPORT")
    assert _nums(lines[i + 2]) == [e["eu"], e["iu_depot"]]
    assert _nums(lines[i + 3]) == [e["production"]["EU"], e["production"]["IU"], e["production"]["AU"]]
    assert f"YOU HAVE COLLECTED {r['stats']['vp']} OUT OF {r['stats']['vp_needed']:>4} VICTORY POINTS" in text
    i = lines.index("STATISTICS REPORT")
    heads = lines[i + 2].split()
    ranks = _nums(lines[i + 3][16:])
    assert dict(zip([h.rstrip("*") for h in heads], ranks)) == r["stats"]["ranks"]
    # orders, events, messages, battles, relations
    for o in r["orders"]:
        if o["error"]:
            assert f"***ERROR {o['error']}" in text
        for m in o["messages"]:
            assert m in text
    for ev in r["events"]:
        assert ev["text"].split("\n")[0].strip() in text, ev["kind"]
    for m in r["messages"]:
        assert m["text"].strip().split("\n")[-1] in text
    for c in r["combats"]:
        for line in c["lines"]:
            assert line["text"].split("\n")[0] in text
    for race in v["races"]:
        assert re.search(rf"\t{re.escape(race['name'])} +\(", text)
    for s in v["ships"]:
        assert re.search(rf" {s['number']} +{re.escape(s['class'])} ", text)


A, B = 1, 2


def _two(turns=3):
    st = new_game("leak", 4242, ["Alpha", "Bravo"])
    bh = next(s for s in st.systems if (s.x, s.y) == (st.empires[B].home_x, st.empires[B].home_y))
    st.leaders[next(ld.id for ld in st.leaders.values() if ld.owner == B)].name = "ZZSECRETLDR"
    initial_results(st)
    hist = []
    for t in range(turns):
        before = M.from_dict(M.to_dict(st))
        orders = {B: parse_orders(f"BS {bh.name} F\nCFXY ZZSECRETFL 50 50\nECHO ZZSECRETECHO\n"
                                  f"MESSAGE {st.empires[3].name}\nZZSECRETMSG\n.")} if t == 0 else {}
        hist.append((before, run_turn(st, orders).to_dict()))
    return st, hist, bh


def test_no_foreign_data_markers():
    st, hist, bh = _two()
    assert st.empires[A].relations.get(B) is None
    for i, (before, rd) in enumerate(hist):
        text = legacy_report(view(st if i == len(hist) - 1 else hist[i + 1][0], rd, A), view(before, None, A))
        for marker in ("ZZSECRETLDR", "ZZSECRETFL", "ZZSECRETECHO", "ZZSECRETMSG", bh.name, "Bravo"):
            assert marker not in text, marker
    assert "ZZSECRETECHO" in str(hist[0][1]["reports"][B])           # the fixture isn't vacuous


def test_report_unchanged_by_anything_private_to_b():
    """The view's differential proof, on the text: scramble everything about B that A hasn't
    scanned, plus B's whole report; A's classic report is identical."""
    st, hist, _ = _two()
    before, rd = hist[-1]
    st.empires[A].relations[B] = st.empires[B].relations[A] = "N"
    text = legacy_report(view(st, rd, A), view(before, None, A))
    st2, rd2 = M.from_dict(M.to_dict(st)), copy.deepcopy(rd)
    eb = st2.empires[B]
    eb.relations[A] = "A"
    eb.eu, eb.iu_depot, eb.vp, eb.stats = 5, 6, 77, {"GNP": 1.0}
    eb.split_trade, eb.deny_trade = {A: 50}, {A: 25}
    for s in st2.systems:
        if s.owner == B:
            s.au, s.iu, s.pop, s.starport, s.infra = 1, 2, 3.0, 4, 5
            s.csp_au, s.csp_iu, s.csp_eu = 10, 10, 80
    for sh in st2.ships.values():
        if sh.owner == B:
            sh.x, sh.dx, sh.cargo_au = (sh.x + 1) % st2.board, 3, 9
    for ld in st2.leaders.values():
        if ld.owner == B:
            ld.name = "Other"
    rd2["reports"][str(B) if str(B) in rd2["reports"] else B] = {
        "empire": B, "orders": [{"text": "X", "ok": False, "error": "ZZ", "messages": []}],
        "events": [], "messages": [], "combats": [], "scans": {}, "stats": {}, "maintenance": [],
        "economy": {}}
    b2 = M.from_dict(M.to_dict(before))
    for s in b2.systems:
        if s.owner == B:
            s.au, s.iu = 11, 12
    assert legacy_report(view(st2, rd2, A), view(b2, None, A)) == text


# ---------------------------------------------------------------- the endpoint
def H(tok):
    return {"X-Seat-Token": tok}


@pytest.fixture
def env(tmp_path):
    app = create_app(tmp_path)
    c = TestClient(app)
    g = c.post("/api/games", json={"password": "secret1", "name": "Classic test", "humans": 2, "size": 8,
                                   "player": "Dave", "race": "Daves", "seed": 99,
                                   "host_password": "hostpw1"}).json()
    t2 = c.post(f"/api/games/{g['id']}/join", json={"password": "secret2", "seat": 2, "player": "Bob",
                                                    "race": "Bobbers"}).json()["token"]
    gid = g["id"]
    ht = c.post(f"/api/games/{gid}/host/login", json={"password": "hostpw1"}).json()["token"]
    for _ in range(2):
        assert c.post(f"/api/games/{gid}/force", headers=H(ht)).status_code == 200
    return c, gid, g["token"], t2, ht


def test_endpoint_is_the_report_of_the_view(env):
    c, gid, t1, t2, ht = env
    for tok in (t1, t2):
        for turn, q in ((2, ""), (2, "?turn=2"), (1, "?turn=1"), (0, "?turn=0")):
            r = c.get(f"/api/games/{gid}/report.txt{q}", headers=H(tok))
            assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
            v = c.get(f"/api/games/{gid}/view?turn={turn}", headers=H(tok)).json()
            prev = c.get(f"/api/games/{gid}/view?turn={turn - 1}", headers=H(tok)).json() if turn else None
            assert r.text == legacy_report(v, prev)
            assert f"TURN {turn}" in r.text.splitlines()[0]
    mine = c.get(f"/api/games/{gid}/report.txt", headers=H(t1)).text
    assert "Daves (player)" in mine and "Bobbers (player)" not in mine


def test_endpoint_permissions(env):
    c, gid, t1, t2, ht = env
    assert c.get(f"/api/games/{gid}/report.txt").status_code == 401
    assert c.get(f"/api/games/{gid}/report.txt", headers=H("nonsense")).status_code == 401
    assert c.get(f"/api/games/{gid}/report.txt?turn=9", headers=H(t1)).status_code == 404
    # view as: the host login only, read-only, the viewed race's report
    assert c.get(f"/api/games/{gid}/as/2/report.txt", headers=H(t1)).status_code == 403
    r = c.get(f"/api/games/{gid}/as/2/report.txt?turn=1", headers=H(ht))
    assert r.status_code == 200
    assert r.text == c.get(f"/api/games/{gid}/report.txt?turn=1", headers=H(t2)).text
    assert "Bobbers (player)" in r.text
    assert c.get(f"/api/games/{gid}/as/0/report.txt", headers=H(ht)).status_code == 404
    npr = c.get(f"/api/games/{gid}/as/5/report.txt", headers=H(ht))
    assert npr.status_code == 200 and "(NPR)" in npr.text


# ---------------------------------------------------------------- ground forces after a battle
def test_ground_forces_after_the_battle_for_participants_only():
    from tests.conftest import add_troop, contact, make_state
    st = make_state(n_humans=3, npr=0)
    contact(st, 1, 2, "W")
    contact(st, 1, 3)
    h2 = st.system_named("H2")
    for _ in range(3):
        add_troop(st, 1, "O", system=h2.id)
    for t in ("M", "M", "S"):
        add_troop(st, 2, t, system=h2.id, posture="D")
    rd = run_turn(st, {}, npr_fn=None).to_dict()
    c = next(c for c in rd["combats"] if c["system"] == h2.id)
    g = {x["owner"]: x for x in c["ground"]}
    for eid in (1, 2):
        text = legacy_report(view(st, rd, eid))
        block = text.split("====GROUND FORCES AFTER THE BATTLE====")[1].split("END OF THIS COMBAT")[0]
        assert "R1" in block and "R2" in block
        n_after = g[1]["after"].get("O", 0)
        assert re.search(rf"R1\s+Ogre\s+3 -> {n_after}\b", block), block
        for t, name in (("M", "Militia"), ("S", "Shock")):
            assert re.search(rf"{name}\s+{g[2]['before'][t]} -> {g[2]['after'].get(t, 0)}\b", block)
    # R3 took no part: no battle, no ground block, nothing about the troops
    text3 = legacy_report(view(st, rd, 3))
    assert "GROUND FORCES" not in text3 and "Ogre" not in text3 and "Militia" not in text3
