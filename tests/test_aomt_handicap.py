"""AOMT, "Autogenerate orders on missed turn" (DECISIONS W-29), the host handicap in games with
other human players (W-28), and the ship picker groups (G-22).  Dave 2026-11-19."""
from __future__ import annotations

import copy
import json

from fastapi.testclient import TestClient

from app.catalogue import order_catalogue, reference
from app.main import create_app
from mhgc import model as M
from mhgc.data import constants as K
from mhgc.data.ships import SHIP_ORDER, SHIP_TYPES, ship_group
from mhgc.engine import stats
from mhgc.engine.turn import new_context, run_turn
from mhgc.mapgen import new_game
from mhgc.npr import aomt_orders_traced, AOMT_SKIP
from mhgc.orders import parse_orders
from mhgc.view import view as build_view


def H(tok):
    return {"X-Seat-Token": tok}


def two_humans(c, seed=5, size=8):
    """Dave hosts and plays seat 1; P plays seat 2."""
    r = c.post("/api/games", json={"humans": 2, "size": size, "player": "Dave",
                                   "password": "davepw", "seed": seed,
                                   "host_password": "davepw"}).json()
    gid, t1 = r["id"], r["token"]
    t2 = c.post(f"/api/games/{gid}/join", json={"seat": 2, "player": "P", "password": "ppppp2"}
                ).json()["token"]
    return gid, t1, t2


def audit(tmp_path, gid):
    p = tmp_path / "games" / gid / "host_audit.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def botlog(tmp_path, gid):
    p = tmp_path / "games" / gid / "botlog.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


# ================================================================= ship groups (G-22)
def test_ship_groups_follow_the_rules():
    assert [ship_group(c) for c in ("S", "SS", "MS")] == ["scout"] * 3
    assert [ship_group(c) for c in ("T", "MT")] == ["transport"] * 2
    # the armed cargo ships are warships and stay in their Mixed Fleet Bonus line
    assert ship_group("AT") == "STANDARD" and ship_group("MCS") == "FAST"
    assert ship_group("ST") == "OFFENSIVE" and ship_group("PA") == "DEFENSIVE"
    assert sorted(SHIP_ORDER) == sorted(SHIP_TYPES)
    groups = [ship_group(c) for c in SHIP_ORDER]
    assert groups == sorted(groups, key=["scout", "transport", "STANDARD", "OFFENSIVE",
                                         "DEFENSIVE", "FAST"].index)
    assert SHIP_ORDER[:5] == ("S", "SS", "MS", "T", "MT")
    assert [c for c in SHIP_ORDER if ship_group(c) == "STANDARD"] == \
        ["F", "D", "C", "AT", "B", "HB", "DN"]
    ref = reference()
    assert [s["code"] for s in ref["ships"]] == list(SHIP_ORDER)
    assert [g["label"] for g in ref["ship_groups"]] == [
        "Scouts", "Transports", "Standard line", "Offensive line", "Defensive line", "Fast line"]
    bs = next(o for o in order_catalogue()["orders"] if o["code"] == "BS")
    assert next(a for a in bs["args"] if a["name"] == "type")["choices"] == list(SHIP_ORDER)


# ================================================================= host handicap (W-28)
def _ctx_stats(st):
    ctx = new_context(st)
    stats.compute_stats(ctx)
    return ctx


def test_unranked_race_gets_no_stat_vp_and_pushes_nobody_down():
    st = new_game("h", 3, ["A", "B"], size=8)
    base = copy.deepcopy(st)
    # make empire 1 the best at everything that counts
    for s in st.systems:
        if s.owner == 1:
            s.pop += 30
            s.starport += 3
    st2 = copy.deepcopy(st)
    _ctx_stats(st)
    assert st.empires[1].ranks["POP"] == 1 and st.empires[2].ranks["POP"] > 1
    st2.unranked = [1]
    ctx = _ctx_stats(st2)
    e1, e2 = st2.empires[1], st2.empires[2]
    assert e1.ranks == {}
    assert ctx.res.report(1).stats["unranked"] is True
    assert "unranked" not in ctx.res.report(2).stats
    # its VP are only technology and systems
    from mhgc.data.techs import tech_vp
    own = sum(tech_vp(t) for t in e1.techs if t) + 4 * e1.future_tech + \
        K.VP_PER_SYSTEM * int(e1.stats["SYS"])
    assert e1.vp == own
    # the others are ranked exactly as if empire 1 weren't in the game
    ref = copy.deepcopy(st2)
    ref.empires[1].kind = M.INDEPENDENT        # out of every computation
    _ctx_stats(ref)
    for eid in st2.empires:
        if eid not in (0, 1) and st2.empires[eid].kind in (M.HUMAN, M.NPR):
            assert st2.empires[eid].ranks == ref.empires[eid].ranks, eid
            assert st2.empires[eid].vp == ref.empires[eid].vp, eid
    assert e2.ranks["POP"] == ref.empires[2].ranks["POP"]
    del base


def test_unranked_race_reaching_the_target_does_not_win():
    st = new_game("v", 4, ["A", "B"], size=8)
    st.unranked = [1]
    st.empires[1].vp = 150
    ctx = new_context(st)
    stats.check_victory(ctx)
    assert st.winner is None
    st.empires[2].vp = 101
    stats.check_victory(ctx)
    assert st.winner == 2
    st2 = new_game("v", 4, ["A", "B"], size=8)
    st2.empires[1].vp = 150                    # without the handicap it wins
    stats.check_victory(new_context(st2))
    assert st2.winner == 1


def test_handicap_in_the_server_and_its_dynamics(tmp_path):
    c = TestClient(create_app(tmp_path))
    r = c.post("/api/games", json={"humans": 3, "size": 8, "player": "Dave", "password": "davepw",
                                   "seed": 9, "host_password": "davepw"}).json()
    gid, t1 = r["id"], r["token"]
    g = c.get(f"/api/games/{gid}").json()
    assert g["host_handicap"] is False                # open seats are not players
    c.post(f"/api/games/{gid}/force", headers=H(t1))
    v = c.get(f"/api/games/{gid}/view", headers=H(t1)).json()
    assert v["empire"]["unranked"] is False and v["empire"]["ranks"]
    # a second human joins: from the next turn the host's race is unranked
    t2 = c.post(f"/api/games/{gid}/join", json={"seat": 2, "player": "P", "password": "ppppp2"}
                ).json()["token"]
    assert c.get(f"/api/games/{gid}").json()["host_handicap"] is True
    c.post(f"/api/games/{gid}/force", headers=H(t1))
    v1 = c.get(f"/api/games/{gid}/view", headers=H(t1)).json()
    v2 = c.get(f"/api/games/{gid}/view", headers=H(t2)).json()
    assert v1["empire"]["unranked"] is True and v1["empire"]["ranks"] == {}
    assert v1["results"]["stats"]["unranked"] is True
    assert v2["empire"]["unranked"] is False and v2["empire"]["ranks"]
    assert "unranked" not in json.dumps(v2["results"]["stats"])
    # the second human is handed to the computer: no other human, no handicap
    assert c.post(f"/api/games/{gid}/seats/2/computer", headers=H(t1)).status_code == 200
    assert c.get(f"/api/games/{gid}").json()["host_handicap"] is False
    c.post(f"/api/games/{gid}/force", headers=H(t1))
    v1 = c.get(f"/api/games/{gid}/view", headers=H(t1)).json()
    assert v1["empire"]["unranked"] is False and v1["empire"]["ranks"]
    # a third joins, then leaves again
    t3 = c.post(f"/api/games/{gid}/join", json={"seat": 3, "player": "Q", "password": "qqqqq3"}
                ).json()["token"]
    assert c.get(f"/api/games/{gid}").json()["host_handicap"] is True
    c.post(f"/api/games/{gid}/leave", headers=H(t3))
    assert c.get(f"/api/games/{gid}").json()["host_handicap"] is False
    # the standings log records it per turn
    rows = [json.loads(x) for x in (tmp_path / "games" / gid / "standings.jsonl")
            .read_text().splitlines()]
    flags = [next(e for e in r["empires"] if e["id"] == 1)["unranked"] for r in rows[1:]]
    assert flags == [False, True, False]


def test_no_handicap_for_host_alone_or_with_bots(tmp_path):
    c = TestClient(create_app(tmp_path))
    r = c.post("/api/games", json={"humans": 1, "size": 4, "player": "Dave", "password": "davepw",
                                   "seed": 2, "host_password": "davepw"}).json()
    gid, t1 = r["id"], r["token"]
    assert c.get(f"/api/games/{gid}").json()["host_handicap"] is False
    c.post(f"/api/games/{gid}/submit", headers=H(t1))
    v = c.get(f"/api/games/{gid}/view", headers=H(t1)).json()
    assert v["empire"]["unranked"] is False and v["empire"]["ranks"]
    # a host-only game (no race): nobody is handicapped
    r = c.post("/api/games", json={"humans": 2, "size": 4, "player": "Admin", "seed": 3,
                                   "host_only": True, "host_password": "hostpw"}).json()
    gid2 = r["id"]
    for s, pw in ((1, "one111"), (2, "two222")):
        c.post(f"/api/games/{gid2}/join", json={"seat": s, "player": f"P{s}", "password": pw})
    assert c.get(f"/api/games/{gid2}").json()["host_handicap"] is False


def test_handicapped_host_reaching_the_target_does_not_end_the_game(tmp_path):
    c = TestClient(create_app(tmp_path))
    gid, t1, t2 = two_humans(c)
    st = c.app.state.games[gid].state
    st.empires[1].future_tech = 40                 # 160 VP of future technology alone
    c.post(f"/api/games/{gid}/force", headers=H(t1))
    g = c.get(f"/api/games/{gid}").json()
    v1 = c.get(f"/api/games/{gid}/view", headers=H(t1)).json()
    assert v1["empire"]["vp"] >= K.VICTORY_POINTS
    assert g["finished"] is False and g["winner"] is None


# ================================================================= AOMT (W-29)
def test_aomt_order_parses_and_sets_the_flag():
    st = new_game("a", 1, ["A"], size=4)
    assert st.empires[1].aomt is True                # on by default (Dave 2026-11-20)
    r = run_turn(st, {1: parse_orders("AOMT OFF")})
    assert r.report(1).orders[0].ok and st.empires[1].aomt is False
    st2 = M.loads(M.dumps(st))                       # persists in saves
    assert st2.empires[1].aomt is False
    run_turn(st2, {1: parse_orders("AOMT ON")})
    assert st2.empires[1].aomt is True


def test_aomt_defaults_on_in_new_games_and_old_saves():
    st = new_game("d", 2, ["A", "B"], size=8)
    assert all(st.empires[e].aomt is True for e in (1, 2))
    d = M.to_dict(st)
    for e in d["empires"].values() if isinstance(d["empires"], dict) else d["empires"]:
        e.pop("aomt", None)                          # a save from before the field
    st2 = M.from_dict(d)
    assert st2.empires[1].aomt is True and st2.empires[2].aomt is True


def test_aomt_off_means_no_orders(tmp_path):
    """AOMT off keeps W-10: on a forced turn the unsubmitted draft is ignored, no orders."""
    c = TestClient(create_app(tmp_path))
    gid, t1, t2 = two_humans(c)
    assert c.get(f"/api/games/{gid}/view", headers=H(t2)).json()["empire"]["aomt"] is True
    r = c.post(f"/api/games/{gid}/aomt", json={"on": False}, headers=H(t2))
    assert r.status_code == 200 and r.json()["aomt"] is False
    c.put(f"/api/games/{gid}/orders", json={"text": "PT 1"}, headers=H(t2))   # not submitted
    c.post(f"/api/games/{gid}/force", headers=H(t1))
    v2 = c.get(f"/api/games/{gid}/view", headers=H(t2)).json()
    assert v2["results"]["orders"] == []
    assert not [e for e in v2["results"]["events"] if e["kind"] == "aomt"]
    assert not [a for a in audit(tmp_path, gid) if a["action"] == "aomt_orders"
                and a["seat"] == 2]          # (seat 1, unsubmitted with AOMT on, got the bot)


def test_aomt_on_forced_and_not_submitted(tmp_path):
    c = TestClient(create_app(tmp_path))
    gid, t1, t2 = two_humans(c)
    c.post(f"/api/games/{gid}/aomt", json={"on": False}, headers=H(t1))   # seat 1's own
    assert c.get(f"/api/games/{gid}/view", headers=H(t2)).json()["empire"]["aomt"] is True
    # nobody else sees it
    v1 = c.get(f"/api/games/{gid}/view", headers=H(t1)).json()
    assert v1["empire"]["aomt"] is False and "aomt" not in json.dumps(v1["races"])
    # no draft (or one holding only the AOMT setting, which counts as none): the bot plays
    c.put(f"/api/games/{gid}/orders", json={"text": "AOMT ON"}, headers=H(t2))
    assert c.post(f"/api/games/{gid}/submit", headers=H(t1)).json()["turn_ran"] is False
    assert c.post(f"/api/games/{gid}/force", headers=H(t1)).status_code == 200
    v2 = c.get(f"/api/games/{gid}/view", headers=H(t2)).json()
    res = v2["results"]
    ev = [e for e in res["events"] if e["kind"] == "aomt"]
    assert len(ev) == 1 and "You missed turn 1; your orders were generated automatically " \
        "(AOMT is on)" in ev[0]["text"]
    assert res["orders"], "the generated orders are listed"
    assert all(o["ok"] for o in res["orders"]), [o for o in res["orders"] if not o["ok"]]
    codes = {o["code"] for o in res["orders"]}
    assert not codes & AOMT_SKIP
    # still a human race, with nothing new for anyone else to see
    g = c.get(f"/api/games/{gid}").json()
    seat2 = next(s for s in g["seats"] if s["seat"] == 2)
    assert seat2["computer"] is False and seat2["player"] == "P"
    v1 = c.get(f"/api/games/{gid}/view", headers=H(t1)).json()
    assert "AOMT" not in json.dumps(v1) and "automatically" not in json.dumps(v1)
    chat = c.get(f"/api/games/{gid}/chat", headers=H(t1)).json()["messages"]
    assert not any("AOMT" in m["text"] for m in chat)
    # the logs
    a = [x for x in audit(tmp_path, gid) if x["action"] == "aomt_orders"]
    assert len(a) == 1 and a[0]["seat"] == 2 and a[0]["ran"] == 1 and a[0]["source"] == "bot"
    b = [x for x in botlog(tmp_path, gid) if x["empire"] == 2]
    assert len(b) == 1 and b[0]["aomt"] is True and b[0]["rejected"] == 0
    orders = json.loads((tmp_path / "games" / gid / "turns" / "1" / "orders.json").read_text())
    assert {o["by"] for o in orders["2"]} == {"aomt"}
    # the setting persists over a restart, and a consecutive missed turn keeps the memory
    c2 = TestClient(create_app(tmp_path))
    assert c2.get(f"/api/games/{gid}/view", headers=H(t2)).json()["empire"]["aomt"] is True
    c2.post(f"/api/games/{gid}/force", headers=H(t1))
    v2 = c2.get(f"/api/games/{gid}/view", headers=H(t2)).json()
    assert [e for e in v2["results"]["events"] if e["kind"] == "aomt"]
    st = M.loads((tmp_path / "games" / gid / "turns" / "2" / "state.json").read_text())
    assert st.aomt_state[2]["aomt_last"] == 2 and st.aomt_state[2]["born"] == 1
    assert st.empires[2].kind == M.HUMAN
    # the view never carries the stand-in memory
    assert "aomt_last" not in json.dumps(v2)


def test_aomt_unsubmitted_draft_wins_over_the_bot(tmp_path):
    """Dave 2026-11-20: with AOMT on, a forced turn runs the race's unsubmitted, non-empty draft
    as if submitted; the bot stands in only for an empty draft."""
    c = TestClient(create_app(tmp_path))
    gid, t1, t2 = two_humans(c)
    c.put(f"/api/games/{gid}/orders", json={"text": "PT 1\nPT 2"}, headers=H(t2))  # unsent
    assert c.post(f"/api/games/{gid}/submit", headers=H(t1)).json()["turn_ran"] is False
    assert c.post(f"/api/games/{gid}/force", headers=H(t1)).status_code == 200
    res = c.get(f"/api/games/{gid}/view", headers=H(t2)).json()["results"]
    assert [o["text"] for o in res["orders"]] == ["PT 1", "PT 2"]      # the draft, nothing else
    ev = [e for e in res["events"] if e["kind"] == "aomt"]
    assert len(ev) == 1 and ev[0]["data"]["source"] == "draft"
    assert "your unsubmitted draft was run as if you had submitted it (2 orders)" in ev[0]["text"]
    a = [x for x in audit(tmp_path, gid) if x["action"] == "aomt_orders"]
    assert len(a) == 1 and a[0]["seat"] == 2 and a[0]["source"] == "draft" and \
        a[0]["orders"] == 2
    assert not [x for x in botlog(tmp_path, gid) if x["empire"] == 2]    # no stand-in
    orders = json.loads((tmp_path / "games" / gid / "turns" / "1" / "orders.json").read_text())
    assert {o["by"] for o in orders["2"]} == {"human"}                   # the player's own
    # the next forced turn with an empty draft: the bot
    c.post(f"/api/games/{gid}/force", headers=H(t1))
    res = c.get(f"/api/games/{gid}/view", headers=H(t2)).json()["results"]
    ev = [e for e in res["events"] if e["kind"] == "aomt"]
    assert len(ev) == 1 and ev[0]["data"]["source"] == "bot" and res["orders"]


def test_aomt_submitted_means_no_bot(tmp_path):
    c = TestClient(create_app(tmp_path))
    gid, t1, t2 = two_humans(c)
    c.post(f"/api/games/{gid}/aomt", json={"on": True}, headers=H(t2))
    c.post(f"/api/games/{gid}/submit", json={"text": "PT 1"}, headers=H(t2))
    c.post(f"/api/games/{gid}/force", headers=H(t1))
    res = c.get(f"/api/games/{gid}/view", headers=H(t2)).json()["results"]
    assert [o["text"] for o in res["orders"]] == ["PT 1"]
    assert not [e for e in res["events"] if e["kind"] == "aomt"]
    assert not [x for x in botlog(tmp_path, gid) if x["empire"] == 2]


def test_aomt_classic_order_takes_effect_when_saved(tmp_path):
    c = TestClient(create_app(tmp_path))
    gid, t1, t2 = two_humans(c)
    r = c.put(f"/api/games/{gid}/orders", json={"text": "AOMT ON"}, headers=H(t2))
    assert r.status_code == 200
    assert c.get(f"/api/games/{gid}/view", headers=H(t2)).json()["empire"]["aomt"] is True
    c.post(f"/api/games/{gid}/force", headers=H(t1))       # not submitted: the bot plays
    res = c.get(f"/api/games/{gid}/view", headers=H(t2)).json()["results"]
    assert [e for e in res["events"] if e["kind"] == "aomt"]
    # AOMT OFF through the order, submitted: runs as an order
    c.post(f"/api/games/{gid}/submit", json={"text": "AOMT OFF"}, headers=H(t2))
    c.post(f"/api/games/{gid}/force", headers=H(t1))
    v2 = c.get(f"/api/games/{gid}/view", headers=H(t2)).json()
    assert v2["empire"]["aomt"] is False
    assert v2["results"]["orders"][0]["code"] == "AOMT" and v2["results"]["orders"][0]["ok"]
    cat = c.get("/api/orders/catalogue").json()["orders"]
    assert any(o["code"] == "AOMT" for o in cat)


def test_aomt_reset_to_on_when_the_seat_is_left_or_taken(tmp_path):
    c = TestClient(create_app(tmp_path))
    gid, t1, t2 = two_humans(c)
    c.post(f"/api/games/{gid}/aomt", json={"on": False}, headers=H(t2))
    c.post(f"/api/games/{gid}/leave", headers=H(t2))
    st = M.loads((tmp_path / "games" / gid / "turns" / "0" / "state.json").read_text())
    assert st.empires[2].aomt is True                # the default, for the next player
    t3 = c.post(f"/api/games/{gid}/join", json={"seat": 2, "player": "Q", "password": "qqqqq3"}
                ).json()["token"]
    assert c.get(f"/api/games/{gid}/view", headers=H(t3)).json()["empire"]["aomt"] is True


def test_aomt_uses_no_hidden_information():
    """Scramble everything another race holds that this race can't see: the stand-in orders are
    identical (the A-02 test for NPRs, applied to AOMT)."""
    st = new_game("s", 21, ["A", "B"], size=8)
    for _ in range(3):
        run_turn(st, {})
    from mhgc.engine.turn import initial_results
    results = json.loads(json.dumps(initial_results(copy.deepcopy(st)).to_dict()))
    a = copy.deepcopy(st)
    a.turn += 1
    o1, _ = aomt_orders_traced(a, 1, results)
    b = copy.deepcopy(st)
    seen = {sid for sid in b.empires[1].seen_systems}
    for e in b.empires.values():
        if e.id in (0, 1):
            continue
        e.eu, e.iu_depot = 98765, 4321
        e.techs |= {1, 2, 3, 4, 5, 6, 7, 8}
        e.relations = {k: ("W" if k != 1 else v) for k, v in e.relations.items()}
        if 1 in e.relations:
            e.relations[1] = "W"
    for s in b.systems:
        if s.owner not in (1,) and s.id not in seen:
            s.au, s.iu = 777, 888
    for k, m in list(b.npr_state.items()):
        b.npr_state[k] = {**m, "missions": [], "races": {}}
    b.turn += 1
    o2, _ = aomt_orders_traced(b, 1, results)
    assert [o.to_text() for o in o1] == [o.to_text() for o in o2]
    assert o1, "the bot gave orders"
    assert all(o.code not in AOMT_SKIP for o in o1)
    assert a.empires[1].kind == M.HUMAN and 1 not in a.npr_state


def test_aomt_view_is_the_players_view():
    st = new_game("w", 8, ["A", "B"], size=8)
    v = build_view(st, None, 1)
    assert v["empire"]["aomt"] is True and v["empire"]["unranked"] is False
    st.aomt_state[1] = {"secret": "x"}
    assert "secret" not in json.dumps(build_view(st, None, 1))
    assert "secret" not in json.dumps(build_view(st, None, 2))
