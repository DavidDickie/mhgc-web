"""The split tweak (Dave 2026-11-18; DECISIONS G-21): engine/economy.tweak_split, the
production/tweak endpoint (engine/preview.production_tweak) and the bot's use of it
(npr/econ.profiles).

- The helper is exhaustive within +-max_delta (checked against an independent brute force over
  every split), never lowers AU, IU or EU, respects 10-80 and total 100, and finds the textbook
  case (23% gives 9.7 AU, 24% gives 10.1).
- It uses the engine's exact production (the same numbers as system_production), including the
  multipliers, leader, starport, status and the draft's own orders.
- The endpoint is own-only, stores nothing, and its suggestion goes through preview, Check and
  CSP like a typed split; happiness never drops.
- The bot still validates, stays deterministic and uses nothing hidden.
"""
from __future__ import annotations

import json
import random

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from mhgc import model as M
from mhgc.data import constants as K
from mhgc.engine import economy as E
from mhgc.engine import preview as P
from mhgc.engine.context import TurnContext
from mhgc.mapgen import new_game
from mhgc.orders import parse_orders
from mhgc.results import TurnResults
from mhgc.rng import Rng

from tests.test_production_preview import rich_game


def brute(sc, cur, d=3):
    """An independent search: every split of 10-80 totalling 100 within +-d of `cur`.  Best: the
    most units, then the fewest points moved, then the lowest AU, then IU; `cur` itself has
    moved 0, so it wins any tie on units."""
    before = E.split_output(sc, cur)
    best_key, best = (sum(before), 0, 0, 0), cur
    for au in range(10, 81):
        for iu in range(10, 81):
            c = (au, iu, 100 - au - iu)
            if not 10 <= c[2] <= 80 or c == cur or max(abs(x - y) for x, y in zip(c, cur)) > d:
                continue
            out = E.split_output(sc, c)
            if any(o < b for o, b in zip(out, before)):
                continue
            key = (sum(out), -sum(abs(x - y) for x, y in zip(c, cur)), -au, -iu)
            if key[:2] > best_key[:2] or (key[:2] == best_key[:2] and best != cur
                                          and key > best_key):
                best_key, best = key, c
    return best, sum(E.split_output(sc, best)) - sum(before)


def ctx_for(g):
    return TurnContext(state=g, rng=Rng(0, 1, "t"), res=TurnResults(1), checking=True)


# ---------------------------------------------------------------- the helper
def test_finds_the_textbook_case():
    """pop 4.22 with full infrastructure: 42.2 production; 23% AU is 9.706 (9 AU), 24% is
    10.128 (10 AU)."""
    g = new_game("tw", 3, ["Dave"])
    s = g.system_at(g.empires[1].home_x, g.empires[1].home_y)
    s.pop, s.infra, s.starport, s.mr, s.ar, s.artifacts = 4.22, 10, 0, False, False, set()
    s.csp_au, s.csp_iu, s.csp_eu = 23, 40, 37
    g.leaders.clear()
    ctx = ctx_for(g)
    sc = E.split_context(ctx, s)
    assert sc.base == pytest.approx(42.2)
    assert E.system_production(ctx, s) == (9, 16, 15)
    t = E.tweak_split(sc, (23, 40, 37))
    assert not t["optimal"] and t["before"] == (9, 16, 15)
    assert t["after"][0] == 10 and t["after"][1] >= 16 and t["after"][2] >= 15
    assert t["gain"] == sum(t["after"]) - 40 >= 1 and t["split"][0] == 24
    assert (t["split"], t["gain"]) == brute(sc, (23, 40, 37))
    # applied, the engine produces exactly what it promised
    s.csp_au, s.csp_iu, s.csp_eu = t["split"]
    assert E.system_production(ctx, s) == t["after"]
    # and from the tweaked split there is nothing more to find
    assert E.tweak_split(sc, t["split"])["optimal"]


def test_exhaustive_and_never_lowers_a_resource():
    rnd = random.Random(1118)
    found = 0
    for _ in range(600):
        arts = {a for a in ("BF", "AF", "CM", "AL", "CB", "VRB") if rnd.random() < 0.2}
        sc = E.make_split_context(rnd.uniform(0.3, 12), rnd.randint(0, 14),
                                  rnd.choice([1.0, 0.8, 1.2, 1.45]),
                                  rnd.choice([K.NORMAL, K.NORMAL, K.UNDER_ATTACK]),
                                  rnd.randint(0, 6), rnd.random() < 0.2, rnd.random() < 0.2,
                                  arts)
        au = rnd.randint(10, 80)
        iu = rnd.randint(10, min(80, 90 - au))
        cur = (au, iu, 100 - au - iu)
        if not 10 <= cur[2] <= 80:
            continue
        d = rnd.choice([1, 2, 3, 3, 3])
        t = E.tweak_split(sc, cur, d)
        assert (t["split"], t["gain"]) == brute(sc, cur, d)
        new = t["split"]
        assert sum(new) == 100 and all(10 <= v <= 80 for v in new)
        assert all(abs(a - b) <= d for a, b in zip(new, cur))
        assert all(a >= b for a, b in zip(t["after"], t["before"]))
        assert t["after"] == E.split_output(sc, new)
        assert t["optimal"] == (new == cur) and (t["gain"] > 0 or t["optimal"])
        assert t["moved"] == sum(abs(a - b) for a, b in zip(new, cur))
        found += not t["optimal"]
    assert found > 50


def test_limits_and_invalid_splits():
    sc = E.make_split_context(9.3, 9, 1.0, K.NORMAL, 3, True, False, {"CB"})
    for cur in [(10, 10, 80), (80, 10, 10), (10, 80, 10), (11, 11, 78)]:
        t = E.tweak_split(sc, cur)
        assert sum(t["split"]) == 100 and all(10 <= v <= 80 for v in t["split"])
    for bad in [(9, 11, 80), (30, 30, 30), (81, 10, 9), (20.5, 39.5, 40), (True, 49, 50)]:
        with pytest.raises(ValueError):
            E.tweak_split(sc, bad)
    # no production (interdicted): nothing to gain
    z = E.make_split_context(5, 5, 1.0, K.INTERDICTED, 0, False, False, set())
    assert E.tweak_split(z, (20, 40, 40)) == {"split": (20, 40, 40), "before": (0, 0, 0),
                                               "after": (0, 0, 0), "gain": 0, "moved": 0,
                                               "optimal": True}
    # max_delta 0 searches nothing
    assert E.tweak_split(sc, (23, 40, 37), 0)["optimal"]


def test_multipliers_change_the_answer():
    """An MR system's IU is doubled, so the best tweak differs from a plain system's."""
    plain = E.make_split_context(6.7, 7, 1.0, K.NORMAL, 1, False, False, set())
    mr = E.make_split_context(6.7, 7, 1.0, K.NORMAL, 1, True, False, set())
    outs = set()
    for cur in [(23, 41, 36), (17, 46, 37), (31, 33, 36), (12, 49, 39)]:
        a, b = E.tweak_split(plain, cur), E.tweak_split(mr, cur)
        assert b["after"] == E.split_output(mr, b["split"])
        outs.add((a["split"], b["split"]))
    assert any(x != y for x, y in outs)


# ---------------------------------------------------------------- production_tweak
def test_production_tweak_uses_the_draft_and_keeps_happiness(monkeypatch):
    g, home, col = rich_game()
    draft = parse_orders(f"BI {home.name} 2\nBT {home.name} PD\nCSP {col.name} 23 41 36\n")
    before = M.dumps(g)
    tw = P.production_tweak(g, 1, draft)
    assert M.dumps(g) == before
    rows = {r["id"]: r for r in tw["systems"]}
    assert set(rows) == {s.id for s in g.systems if s.owner == 1}
    assert rows[col.id]["split"] == {"au": 23, "iu": 41, "eu": 36}       # the draft's CSP
    pv = P.production_preview(g, 1, draft)
    for r in pv["systems"]:                    # before == what the preview projects
        assert rows[r["id"]]["before"] == r["production"]
    over = {sid: tuple(r["suggestion"][k] for k in P.KEYS) for sid, r in rows.items()}
    pv2 = P.production_preview(g, 1, draft, over)
    for r0, r1 in zip(pv["systems"], pv2["systems"]):
        t = rows[r0["id"]]
        assert r1["production"] == t["after"]
        assert all(r1["production"][k] >= r0["production"][k] for k in P.KEYS)
        assert r1["happy_after"] >= r0["happy_after"] - 1e-9
        assert r1["eaten"] >= r0["eaten"]
    assert tw["gain"] == sum(sum(r1["production"].values()) - sum(r0["production"].values())
                             for r0, r1 in zip(pv["systems"], pv2["systems"]))
    # systems=: only those; overrides are the starting split
    one = P.production_tweak(g, 1, draft, {col.id: (30, 40, 30)}, systems=[col.id])
    assert [r["id"] for r in one["systems"]] == [col.id]
    assert one["systems"][0]["split"] == {"au": 30, "iu": 40, "eu": 30}


def test_production_tweak_depends_on_nothing_hidden():
    g, home, col = rich_game()
    a = P.production_tweak(g, 1)
    for s in g.systems:
        if s.owner != 1:
            s.pop, s.iu, s.au, s.infra, s.starport = 7.0, 999, 999, 9, 5
    g.empires[2].eu, g.empires[2].techs = 98765, {0, 1, 2, 3}
    assert P.production_tweak(g, 1) == a
    assert "98765" not in json.dumps(a)


# ---------------------------------------------------------------- the endpoint
@pytest.fixture
def env(tmp_path):
    app = create_app(tmp_path)
    c = TestClient(app)
    g = c.post("/api/games", json={"password": "secret1", "name": "T", "humans": 2, "size": 16,
                                   "player": "Dave", "race": "Daves", "seed": 99,
                                   "host_password": "secret1"}).json()
    t2 = c.post(f"/api/games/{g['id']}/join", json={"password": "secret2", "seat": 2,
                                                     "player": "Bob", "race": "Bobbers"}
                ).json()["token"]
    return c, g["id"], g["token"], t2, tmp_path


def test_endpoint_is_own_only_and_validates(env):
    c, gid, t1, t2, _ = env
    url = f"/api/games/{gid}/production/tweak"
    assert c.post(url).status_code == 401
    assert c.post(url, headers={"X-Seat-Token": "nope"}).status_code == 401
    a = c.post(url, headers={"X-Seat-Token": t1}).json()
    b = c.post(url, headers={"X-Seat-Token": t2}).json()
    mine, theirs = {r["id"] for r in a["systems"]}, {r["id"] for r in b["systems"]}
    assert mine and theirs and not mine & theirs
    sid = next(iter(theirs))
    for body in ({"systems": [sid]}, {"systems": [100000]},
                 {"overrides": {str(sid): {"au": 40, "iu": 30, "eu": 30}}}):
        r = c.post(url, headers={"X-Seat-Token": t1}, json=body)
        assert r.status_code == 422 and "not one of your systems" in r.text, body
    me = next(iter(mine))
    r = c.post(url, headers={"X-Seat-Token": t1},
               json={"overrides": {str(me): {"au": 50, "iu": 30, "eu": 30}}})
    assert r.status_code == 422
    r = c.post(url, headers={"X-Seat-Token": t1}, json={"max_delta": 9})
    assert r.status_code == 422
    v2 = c.get(f"/api/games/{gid}/view", headers={"X-Seat-Token": t2}).json()
    blob = json.dumps(a)
    for s in v2["systems"]:
        assert f'"name": "{s["name"]}"' not in blob


def test_endpoint_does_not_mutate_and_check_and_csp_work(env):
    c, gid, t1, _, tmp = env
    H = {"X-Seat-Token": t1}
    pv = c.post(f"/api/games/{gid}/production/preview", headers=H).json()
    home = pv["systems"][0]
    # a split with rounding waste (home: 10 pop, 10 IF)
    c.put(f"/api/games/{gid}/orders", headers=H,
          json={"text": f"CSP {home['order_name']} 23 41 36"})
    ver = c.get(f"/api/games/{gid}/version").json()
    files = {p: p.read_bytes() for p in tmp.rglob("*.json")}
    tw = c.post(f"/api/games/{gid}/production/tweak", headers=H,
                json={"systems": [home["id"]]}).json()
    assert c.get(f"/api/games/{gid}/version").json() == ver
    assert {p: p.read_bytes() for p in tmp.rglob("*.json")} == files
    row = tw["systems"][0]
    assert row["split"] == {"au": 23, "iu": 41, "eu": 36}
    sug = row["suggestion"]
    # the suggestion is a valid override for the preview and gives what it said
    p2 = c.post(f"/api/games/{gid}/production/preview", headers=H,
                json={"overrides": {str(home["id"]): sug}}).json()
    assert p2["systems"][0]["production"] == row["after"]
    # as "Generate CSP orders" writes it: Check passes and the preview's base is the suggestion
    c.put(f"/api/games/{gid}/orders", headers=H,
          json={"text": f"CSP {home['order_name']} {sug['au']} {sug['iu']} {sug['eu']}"})
    ck = c.post(f"/api/games/{gid}/orders/check", headers=H).json()
    assert ck["ok"], ck
    p3 = c.post(f"/api/games/{gid}/production/preview", headers=H).json()
    assert p3["systems"][0]["base"] == sug
    again = c.post(f"/api/games/{gid}/production/tweak", headers=H,
                   json={"systems": [home["id"]]}).json()["systems"][0]
    assert again["optimal"] and again["changes"] == []


# ---------------------------------------------------------------- the bot
def test_bot_context_matches_the_engine():
    """The bot's own production context (npr.econ.split_context, from its view) gives the
    engine's numbers for its systems."""
    from mhgc.engine.turn import run_turn
    from mhgc.npr import econ, memory, npr_orders, npr_view
    from mhgc.npr.plan import Plan
    from mhgc.npr.world import build
    g = new_game("bt", 5, [], size=8)
    for _ in range(25):
        run_turn(g, {}, npr_fn=npr_orders)
    checked = 0
    ctx = ctx_for(g)
    for eid, e in g.empires.items():
        if eid == 0 or e.kind != M.NPR:
            continue
        w = build(npr_view(g, eid), json.loads(json.dumps(memory(g, eid))))
        plan = Plan(w)
        for s in w.populated:
            b, e = econ.split_context(w, plan, s), E.split_context(ctx, g.systems[s.id])
            # the view shows population to 3 decimals: the only difference
            assert (b.au, b.iu, b.eu) == (e.au, e.iu, e.eu)
            assert b.base == pytest.approx(e.base, abs=0.02)        # 0.0005 pop x 5 x 2 x 1.5 x 1.6
            checked += 1
    assert checked > 10


def test_bot_issues_tweaked_profiles_that_validate():
    """Every CSP the bot issues is valid and executes, and the engine then produces what the
    bot's tweak predicted (all but a few: the view shows population to 3 decimals, and a plan's
    BI or colonists can fail), never less than the untweaked split would have."""
    from mhgc.engine.turn import run_turn
    from mhgc.npr import econ, npr_orders
    g = new_game("bt", 7, [], size=8)
    pred, stats = {}, {"csp": 0, "exact": 0, "checked": 0, "lower": 0}
    real_tweak, real_produce = econ.tweak, E.produce

    def tweak(w, plan, s, split):
        t = real_tweak(w, plan, s, split)
        pred[s.id] = (tuple(split), t)
        return t

    def produce(ctx):
        for s in ctx.state.systems:
            p = pred.get(s.id)
            if p is None or s.pop <= 0 or (s.csp_au, s.csp_iu, s.csp_eu) != p[1]["split"]:
                continue
            sc = E.split_context(ctx, s)
            stats["checked"] += 1
            stats["exact"] += E.split_output(sc, p[1]["split"]) == p[1]["after"]
            stats["lower"] += any(a < b for a, b in zip(E.split_output(sc, p[1]["split"]),
                                                        E.split_output(sc, p[0])))
        real_produce(ctx)
    econ.tweak, E.produce = tweak, produce
    try:
        for _ in range(20):
            pred.clear()
            issued = {}

            def fn(state, eid):
                o = npr_orders(state, eid)
                issued[eid] = o
                return o
            res = run_turn(g, {}, npr_fn=fn)
            for eid, olist in issued.items():
                bad = [r for r in res.report(eid).orders if not r.ok and r.text.startswith("CSP")]
                assert not bad, bad
                for o in olist:
                    if o.code == "CSP":
                        assert o.au + o.iu + o.eu == 100 and min(o.au, o.iu, o.eu) >= 10
                        stats["csp"] += 1
    finally:
        econ.tweak, E.produce = real_tweak, real_produce
    assert stats["csp"] > 100 and stats["checked"] > 100
    assert stats["exact"] >= 0.97 * stats["checked"], stats
    assert stats["lower"] <= 0.01 * stats["checked"], stats
    assert econ.TWEAK_DELTA == 3 and econ.TWEAK_REISSUE_GAIN is None


def test_bot_reissue_option(monkeypatch):
    """Off by default: a profile the bot keeps is not re-issued for the tweak alone.  With
    TWEAK_REISSUE_GAIN set, it is re-issued tweaked when that gains at least so many units."""
    from mhgc.npr import econ, memory, npr_view
    from mhgc.npr.plan import Plan
    from mhgc.npr.world import build
    from tests.conftest import make_state, sysn
    st = make_state()
    h = sysn(st, "H3")                           # the NPR's home
    h.pop, h.infra, h.happy = 4.22, 10, 0.75
    h.csp_au, h.csp_iu, h.csp_eu = 10, 10, 80                 # far from what it wants

    def run():
        w = build(npr_view(st, h.owner), json.loads(json.dumps(memory(st, h.owner))))
        plan = Plan(w)
        econ.profiles(w, plan, 1.0)
        s = next(x for x in w.populated if x.id == h.id)
        return w, plan, s, [o for o in plan.orders if o.code == "CSP"]
    _, _, _, first = run()
    assert first
    chosen = (first[0].au, first[0].iu, first[0].eu)
    found = None
    for da in range(-2, 3):                      # a kept profile near the choice, with waste
        for di in range(-2, 3):
            cur = (chosen[0] + da, chosen[1] + di, chosen[2] - da - di)
            if not E.valid_split(cur):
                continue
            h.csp_au, h.csp_iu, h.csp_eu = cur
            w, plan, s, csp = run()
            t = econ.tweak(w, plan, s, cur)
            if not csp and t["gain"] >= 1:
                found = (cur, t)
                break
        if found:
            break
    assert found, "no kept profile with rounding waste near the bot's choice"
    cur, t = found
    monkeypatch.setattr(econ, "TWEAK_REISSUE_GAIN", t["gain"] + 1)
    assert not run()[3]
    monkeypatch.setattr(econ, "TWEAK_REISSUE_GAIN", t["gain"])
    _, plan, _, csp = run()
    assert len(csp) == 1 and (csp[0].au, csp[0].iu, csp[0].eu) == t["split"]
    assert plan.reasons[-1]["rc"] == "econ.profile_tweak"
