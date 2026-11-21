"""The Production tab's projection (mhgc/engine/preview.py, POST /production/preview).

- With no overrides it equals what run_turn really does to the empire in a quiet turn (no other
  orders, no random events), including the draft's own orders and the whole maintenance ledger;
  over a longer game, the only turns where it differs are turns with random events.
- Overrides change production, feeding, happiness and the totals as the formulas say.
- Flags: insufficient infrastructure, tech available (affordable against the stockpiles an
  install order would pay with) and tech blocked.
- The endpoint is seat-only, leaks nothing, depends on nothing hidden, and never mutates the game.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from mhgc import model as M
from mhgc.engine import economy, events, preview as P
from mhgc.engine.turn import run_turn
from mhgc.mapgen import new_game
from mhgc.model import Leader, Spy, Troop, from_dict, to_dict
from mhgc.orders import parse_orders

from tests.conftest import add_ship


def rich_game():
    """Seat 1 with a governor, a colony short of infrastructure, artifacts, techs, a far ship, a
    troop and a spy, so every maintenance line and production factor is exercised."""
    g = new_game("pp", 5, ["Dave", "Bob"])
    e = g.empires[1]
    home = g.system_at(e.home_x, e.home_y)
    col = g.systems[78]                       # K644, 3 squares away, unowned and empty
    col.owner, col.pop, col.infra, col.au, col.iu, col.hab = 1, 3.0, 1, 12, 60, 4
    col.happy = 0.45
    e.techs |= {1, 2, 5, 14}
    home.artifacts |= {"EHC"}
    e.eu, e.iu_depot = 400, 30
    g.leaders[1].mgmt, g.leaders[1].social = 70, 60
    g.leaders[2] = Leader(2, "Gov2", 1, mgmt=30, social=20, status="posted", system=col.id)
    add_ship(g, 1, "F", (home.x + 40) % 100, home.y, number=9001)       # far away
    g.troops[9100] = Troop(9100, 1, "M", system=col.id)
    g.spies[9200] = Spy(9200, 1, home.id)
    return g, home, col


def quiet(monkeypatch):
    """No random happiness outcomes or random events: what the preview leaves out."""
    monkeypatch.setattr(economy, "uprising", lambda ctx, s: None)
    monkeypatch.setattr(economy, "emperor_day", lambda ctx, s: None)
    monkeypatch.setattr(events, "random_events", lambda ctx: None)


DRAFT = """CSP {col} 30 40 30
BI {home} 2
SISD {home} 25
BT {home} PD
BS {home} F
PT 3
CAP {col} 50
MO 2603 60 60
GT Bob 1
"""


def test_no_overrides_equals_a_quiet_run_turn(monkeypatch):
    quiet(monkeypatch)
    g, home, col = rich_game()
    orders = parse_orders(DRAFT.format(home=home.name, col=col.name))
    before = M.dumps(g)
    p = P.production_preview(g, 1, orders)
    assert M.dumps(g) == before                          # never mutates the game
    real = from_dict(to_dict(g))
    res = run_turn(real, {1: orders}, npr_fn=None)
    rep = res.report(1)
    e = real.empires[1]
    assert p["empire"]["eu_after"] == e.eu
    assert p["empire"]["depot_after"] == e.iu_depot
    eco = rep.economy["systems"]
    for row in p["systems"]:
        s = real.systems[row["id"]]
        assert row["production"] == {k: eco[s.id][k] for k in ("au", "iu", "eu")}
        assert row["eaten"] == eco[s.id]["eaten"]
        assert (row["au_after"], row["iu_after"]) == (s.au, s.iu)
        assert row["happy_after"] == pytest.approx(s.happy, abs=1e-4)
        assert row["pop_after"] == pytest.approx(s.pop, abs=1e-4)
        assert row["trend_after"] == s.trend
    # the ledger the preview summarises is the turn's own maintenance listing (minus the GT,
    # which involves another empire and is listed as skipped)
    real_led = {}
    for ln in rep.maintenance:
        if ln["kind"] not in ("initial", "final"):
            real_led.setdefault(ln["kind"], [0, 0])
            real_led[ln["kind"]][0] += ln["iu"]
            real_led[ln["kind"]][1] += ln["eu"]
    assert {x["kind"]: [x["iu"], x["eu"]] for x in p["empire"]["ledger"]} == real_led
    assert [s["text"].split()[0] for s in p["orders"]["skipped"]] == ["GT"]
    assert p["totals"]["production"]["eu"] == sum(r["production"]["eu"] for r in p["systems"])
    row = next(r for r in p["systems"] if r["id"] == col.id)
    assert row["draft_csp"] and row["base"] == {"au": 30, "iu": 40, "eu": 30}


def test_differences_over_a_game_come_only_from_left_out_things():
    """30 turns, NPRs playing, no human orders: whenever the projection misses, the report shows
    something the preview leaves out (a random event, an uprising, an emperor day, combat)."""
    g = new_game("pp2", 11, ["Dave", "Bob"])
    exact = 0
    for _ in range(30):
        p = P.production_preview(g, 1)
        res = run_turn(g, {}, )
        rep = res.report(1)
        e = g.empires[1]
        got = (e.eu, e.iu_depot, [(g.systems[r["id"]].au, g.systems[r["id"]].iu)
                                  for r in p["systems"]])
        want = (p["empire"]["eu_after"], p["empire"]["depot_after"],
                [(r["au_after"], r["iu_after"]) for r in p["systems"]])
        if got == want:
            exact += 1
            continue
        left_out = [ev for ev in rep.events if ev.section in ("random", "rebellion", "combat")
                    or ev.kind in ("eu_received",)]
        assert left_out, (g.turn, got, want, [(ev.kind, ev.text) for ev in rep.events])
    assert exact >= 10


def test_overrides_follow_the_formulas():
    g = new_game("pp3", 3, ["Dave"])
    e = g.empires[1]
    col = next(s for s in g.systems if s.owner == 0 and s.pop == 0)
    # the rules' worked example: 4 pop, default profile, no leader, no bonuses -> 10/5/5
    col.owner, col.pop, col.infra, col.starport, col.au, col.iu, col.hab = 1, 4.0, 0, 0, 0, 0, 3
    col.mr = col.ar = False
    col.happy = 0.5
    base = P.production_preview(g, 1)
    row = next(r for r in base["systems"] if r["id"] == col.id)
    assert row["production"] == {"au": 10, "iu": 5, "eu": 5}
    assert row["eaten"] == 3 and row["au_after"] == 7          # 33% of 10 truncated
    assert row["insufficient_infra"]
    p = P.production_preview(g, 1, overrides={col.id: (20, 40, 40)})
    r2 = next(r for r in p["systems"] if r["id"] == col.id)
    assert r2["production"] == {"au": 4, "iu": 8, "eu": 8}     # 20 units x 20/40/40%
    assert r2["eaten"] == 1 and r2["au_after"] == 3
    assert r2["split"] == {"au": 20, "iu": 40, "eu": 40} and r2["overridden"]
    assert r2["base"] == {"au": 50, "iu": 25, "eu": 25}
    assert r2["happy_after"] < row["happy_after"]               # less food, less happy
    assert p["empire"]["eu_after"] - base["empire"]["eu_after"] == 3
    assert p["totals"]["iu_after"] - base["totals"]["iu_after"] == 3
    # an override equal to the base profile is not "changed"
    same = P.production_preview(g, 1, overrides={col.id: (50, 25, 25)})
    assert not next(r for r in same["systems"] if r["id"] == col.id)["overridden"]
    # other rows are untouched
    others = lambda q: [r for r in q["systems"] if r["id"] != col.id]   # noqa: E731
    assert others(p) == others(base)
    assert e.eu == 100                                           # still nothing stored


def test_tech_flags_use_the_stockpiles_an_install_order_would_pay_with():
    g, home, col = rich_game()                # techs 1, 2 (EHC, on home already), 5, 14
    g.empires[1].eu = 120
    home.iu = 20
    col.iu = 100                              # EHC 75 IU and BF 100 IU (G-24 prices)
    pick = lambda q, s: next(r for r in q["systems"] if r["id"] == s.id)   # noqa: E731
    p = P.production_preview(g, 1)
    h, c = pick(p, home), pick(p, col)
    assert h["tech_available"] == [] and [t["key"] for t in h["tech_blocked"]] == ["PD"]
    assert "needs 25 IU" in h["tech_blocked"][0]["reason"]
    assert [t["key"] for t in c["tech_available"]] == ["EHC", "PD"]   # 75 IU; 25 IU + 25 EU
    # buying Bioengineered Foods first (100 EU) makes BF installable on the colony this turn,
    # and leaves 20 EU, too little for PD anywhere
    p2 = P.production_preview(g, 1, parse_orders("PT 3"))
    h, c = pick(p2, home), pick(p2, col)
    assert [t["key"] for t in c["tech_available"]] == ["EHC", "BF"]
    assert {t["key"] for t in c["tech_blocked"]} == {"PD"}
    assert "costs 25 EU" in next(t for t in c["tech_blocked"] if t["key"] == "PD")["reason"]
    assert h["tech_available"] == [] and {t["key"] for t in h["tech_blocked"]} == {"BF", "PD"}


def test_depends_on_nothing_hidden():
    """Scrambling everything about the other empires leaves the projection identical."""
    g, home, col = rich_game()
    g.empires[1].relations[2] = "N"
    g.empires[2].relations[1] = "N"
    a = P.production_preview(g, 1)
    b2 = g.empires[2]
    b2.eu, b2.iu_depot, b2.techs, b2.split_trade = 98765, 4321, {0, 1, 2, 3}, {1: 100}
    b2.relations[1] = "W"
    for s in g.systems:
        if s.owner not in (1,):
            s.pop, s.iu, s.au, s.happy = 7.0, 999, 999, 0.9
    g.leaders[50] = Leader(50, "Spook", 2, social=0, mgmt=0, status="posted", system=home.id)
    add_ship(g, 2, "F", home.x, home.y, number=9555)
    assert P.production_preview(g, 1) == a
    blob = json.dumps(a)
    for marker in ("98765", "4321", "Spook", "9555"):
        assert marker not in blob


# ---------------------------------------------------------------- the endpoint
@pytest.fixture
def env(tmp_path):
    app = create_app(tmp_path)
    c = TestClient(app)
    g = c.post("/api/games", json={"password": "secret1", "name": "T", "humans": 2, "size": 16, "player": "Dave", "race": "Daves",
                                   "seed": 99, "host_password": "secret1"}).json()
    t2 = c.post(f"/api/games/{g['id']}/join", json={"password": "secret2", "seat": 2, "player": "Bob",
                                                     "race": "Bobbers"}).json()["token"]
    return c, g["id"], g["token"], t2, tmp_path


def test_endpoint_is_seat_only_and_validates(env):
    c, gid, t1, t2, _ = env
    url = f"/api/games/{gid}/production/preview"
    assert c.post(url).status_code == 401
    assert c.post(url, headers={"X-Seat-Token": "nope"}).status_code == 401
    p1 = c.post(url, headers={"X-Seat-Token": t1}).json()
    p2 = c.post(url, headers={"X-Seat-Token": t2}).json()
    mine = {r["id"] for r in p1["systems"]}
    theirs = {r["id"] for r in p2["systems"]}
    assert mine and theirs and not mine & theirs
    sid = next(iter(theirs))
    r = c.post(url, headers={"X-Seat-Token": t1},
               json={"overrides": {str(sid): {"au": 40, "iu": 30, "eu": 30}}})
    assert r.status_code == 422 and "not one of your systems" in r.text
    # the same message for an id that doesn't exist: nothing to learn from it
    r = c.post(url, headers={"X-Seat-Token": t1},
               json={"overrides": {"100000": {"au": 40, "iu": 30, "eu": 30}}})
    assert r.status_code == 422 and "not one of your systems" in r.text
    me = next(iter(mine))
    for bad in ({"au": 50, "iu": 30, "eu": 30}, {"au": 5, "iu": 45, "eu": 50}, {"au": 50}):
        r = c.post(url, headers={"X-Seat-Token": t1}, json={"overrides": {str(me): bad}})
        assert r.status_code == 422, bad
    v2 = c.get(f"/api/games/{gid}/view", headers={"X-Seat-Token": t2}).json()
    blob = json.dumps(p1)
    for s in v2["systems"]:
        assert f'"name": "{s["name"]}"' not in blob


def test_endpoint_does_not_mutate_and_uses_the_draft(env):
    c, gid, t1, _, tmp = env
    H = {"X-Seat-Token": t1}
    url = f"/api/games/{gid}/production/preview"
    p0 = c.post(url, headers=H).json()
    home = p0["systems"][0]
    c.put(f"/api/games/{gid}/orders", headers=H,
          json={"text": f"CSP {home['order_name']} 20 20 60"})
    ver = c.get(f"/api/games/{gid}/version").json()
    files = {p: p.read_bytes() for p in tmp.rglob("*.json")}
    p1 = c.post(url, headers=H, json={"overrides": {str(home["id"]): {"au": 40, "iu": 20,
                                                                         "eu": 40}}}).json()
    assert c.get(f"/api/games/{gid}/version").json() == ver
    assert {p: p.read_bytes() for p in tmp.rglob("*.json")} == files
    row = p1["systems"][0]
    assert row["base"] == {"au": 20, "iu": 20, "eu": 60} and row["draft_csp"]
    assert row["split"] == {"au": 40, "iu": 20, "eu": 40} and row["overridden"]
    p2 = c.post(url, headers=H).json()
    assert p2["systems"][0]["production"]["eu"] > p0["systems"][0]["production"]["eu"]
    assert p2["notes"] and "random events" in p2["notes"][0]
