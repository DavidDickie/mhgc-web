"""The FastAPI app (app/main.py) through TestClient: lobby, seats, orders, turns, chat, history,
non-leakage over the wire, persistence across a restart, and concurrent submits."""
from __future__ import annotations

import json

import mhgc
import threading

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from mhgc import model as M


def H(tok):
    return {"X-Seat-Token": tok}


@pytest.fixture
def env(tmp_path):
    app = create_app(tmp_path)
    c = TestClient(app)
    r = c.post("/api/games", json={"password": "secret1", "name": "Test", "humans": 2, "size": 16, "player": "Dave",
                                   "race": "Daves", "seed": 99, "host_password": "secret1"})
    assert r.status_code == 200, r.text
    g = r.json()
    gid, t1 = g["id"], g["token"]
    r = c.post(f"/api/games/{gid}/join", json={"password": "secret2", "seat": 2, "player": "Bob", "race": "Bobbers"})
    assert r.status_code == 200, r.text
    t2 = r.json()["token"]
    return {"app": app, "c": c, "gid": gid, "t1": t1, "t2": t2, "dir": tmp_path}


def home_name(c, gid, tok):
    v = c.get(f"/api/games/{gid}/view", headers=H(tok)).json()
    return next(s["name"] for s in v["systems"] if (s["x"], s["y"]) == (50, 50))


# ---------------------------------------------------------------- lobby and seats
def test_create_validates_and_lists(tmp_path):
    c = TestClient(create_app(tmp_path))
    assert c.post("/api/games", json={"password": "secret1", "humans": 2, "computers": 3, "player": "D", "host_password": "secret1"}).status_code \
        == 400
    assert c.post("/api/games", json={"password": "secret1", "humans": 0, "player": "D", "host_password": "secret1"}).status_code == 400
    assert c.post("/api/games", json={"password": "secret1", "humans": 2, "player": "D", "race": "bad name", "host_password": "secret1"}) \
        .status_code == 400
    r = c.post("/api/games", json={"password": "secret1", "humans": 3, "computers": 13, "player": "Dave Dickie", "host_password": "secret1"})
    g = r.json()["game"]
    assert g["computers"] == 13 and g["open_seats"] == [2, 3] and g["host_seat"] == 1
    assert g["seats"][0]["race"] == "Dave_Dickie" and g["seats"][0]["player"] == "Dave Dickie"
    games = c.get("/api/games").json()
    assert [x["id"] for x in games] == [r.json()["id"]]
    assert "token" not in json.dumps(games)                  # tokens never listed
    h = c.get("/api/health").json()
    assert h["ok"] and h["version"] == mhgc.__version__ and h["version_date"]
    assert "Mega Hyper" in c.get("/").text


def test_join_rules(env):
    c, gid = env["c"], env["gid"]
    assert c.post(f"/api/games/{gid}/join", json={"password": "secret2", "seat": 2, "player": "X"}).status_code == 409
    assert c.post(f"/api/games/{gid}/join", json={"password": "secret2", "seat": 3, "player": "X"}).status_code == 400
    g = c.get(f"/api/games/{gid}", headers=H(env["t2"])).json()
    assert g["you"] == 2 and g["open_seats"] == [] and g["seats"][1]["race"] == "Bobbers"
    assert c.get(f"/api/games/{gid}").json()["you"] is None
    assert c.get("/api/games/deadbeef").status_code == 404


def test_catalogue_and_reference(env):
    c = env["c"]
    cat = c.get("/api/orders/catalogue").json()
    by = {o["code"]: o for o in cat["orders"]}
    assert [a["kind"] for a in by["MO"]["args"]] == ["nat", "coord", "coord"]
    assert by["BS"]["args"][1]["labels"]["C"] == "Cruiser"
    assert [a["name"] for a in by["MESSAGE"]["args"]] == ["recipients", "text"]
    assert all(o["help"] or o["category"] == "pref" for o in cat["orders"])
    ref = c.get("/api/reference").json()
    assert len(ref["techs"]) == 52 and ref["home"] == [50, 50]


# ---------------------------------------------------------------- orders and turns
def test_full_flow(env):
    c, gid, t1, t2 = env["c"], env["gid"], env["t1"], env["t2"]
    assert c.get(f"/api/games/{gid}/view").status_code == 401
    assert c.get(f"/api/games/{gid}/view", headers=H("nope")).status_code == 401
    home = home_name(c, gid, t1)
    v0 = c.get(f"/api/games/{gid}/version").json()

    bad = c.put(f"/api/games/{gid}/orders", json={"text": f"BS {home} F\nMO 1 200 5"},
                headers=H(t1))
    assert bad.status_code == 422 and bad.json()["detail"]["errors"][0]["line"] == 2
    r = c.put(f"/api/games/{gid}/orders", json={"text": f"BS {home} F\nECHO hi\nPT 999"},
              headers=H(t1))
    assert r.status_code == 200 and [o["code"] for o in r.json()["orders"]] == ["BS", "ECHO", "PT"]
    ck = c.post(f"/api/games/{gid}/orders/check", headers=H(t1)).json()
    assert [x["ok"] for x in ck["results"]] == [True, True, False] and not ck["ok"]
    r = c.put(f"/api/games/{gid}/orders",
              json={"orders": [{"code": "BS", "system": home, "type": "F"},
                               {"code": "ECHO", "text": "hi"}]}, headers=H(t1))
    assert r.status_code == 200
    assert c.post(f"/api/games/{gid}/orders/check", headers=H(t1)).json()["ok"]
    assert c.get(f"/api/games/{gid}/orders", headers=H(t1)).json()["orders"][1]["text"] == "ECHO hi"
    # submit, withdraw, resubmit
    r = c.post(f"/api/games/{gid}/submit", headers=H(t1)).json()
    assert r == {"submitted": True, "turn_ran": False, "turn": 0, "waiting_for": [2]}
    assert c.delete(f"/api/games/{gid}/submit", headers=H(t1)).json()["waiting_for"] == [1, 2]
    assert c.post(f"/api/games/{gid}/submit", headers=H(t1)).json()["submitted"]
    v1 = c.get(f"/api/games/{gid}/version").json()
    assert v1["version"] > v0["version"] and v1["submitted"] == [1]
    # editing the draft withdraws the submission
    r = c.put(f"/api/games/{gid}/orders", json={"orders": [{"code": "PT", "tech": 1}]},
              headers=H(t1)).json()
    assert r["withdrawn"] and c.get(f"/api/games/{gid}/version").json()["submitted"] == []
    c.post(f"/api/games/{gid}/submit", json={"orders": [{"code": "BS", "system": home,
                                                          "type": "F"}, {"code": "ECHO",
                                                                         "text": "hi"}]},
           headers=H(t1))
    # the last human in runs the turn
    r = c.post(f"/api/games/{gid}/submit", headers=H(t2)).json()
    assert r["turn_ran"] and r["turn"] == 1
    v = c.get(f"/api/games/{gid}/view", headers=H(t1)).json()
    assert v["game"]["turn"] == 1 and v["current_turn"] == 1
    assert [o["ok"] for o in v["results"]["orders"]] == [True, True]
    assert len(v["ships"]) == 3 and v["results"]["orders"][1]["messages"] == ["hi"]
    assert c.get(f"/api/games/{gid}/orders", headers=H(t1)).json() == {
        "turn": 2, "orders": [], "submitted": False}
    # history
    assert c.get(f"/api/games/{gid}/turns", headers=H(t1)).json()["turns"] == [0, 1]
    old = c.get(f"/api/games/{gid}/view?turn=0", headers=H(t1)).json()
    assert old["game"]["turn"] == 0 and len(old["ships"]) == 2
    assert c.get(f"/api/games/{gid}/view?turn=5", headers=H(t1)).status_code == 404
    # force: host only
    assert c.post(f"/api/games/{gid}/force", headers=H(t2)).status_code == 403
    assert c.post(f"/api/games/{gid}/force", headers=H(t1)).json() == {
        "turn_ran": True, "turn": 2, "turns_run": 1, "finished": False}
    chat = c.get(f"/api/games/{gid}/chat").json()["messages"]
    assert any("forced by the host" in m["text"] for m in chat)


def test_open_seat_blocks_auto_run_and_leave_rejoin(env):
    c, gid, t1, t2 = env["c"], env["gid"], env["t1"], env["t2"]
    c.post(f"/api/games/{gid}/force", headers=H(t1))                  # turn 1
    assert c.post(f"/api/games/{gid}/leave", headers=H(t2)).json()["left"] == 2
    assert c.get(f"/api/games/{gid}/view", headers=H(t2)).status_code == 401
    r = c.post(f"/api/games/{gid}/submit", headers=H(t1)).json()
    assert not r["turn_ran"]                                           # seat 2 is open
    r = c.post(f"/api/games/{gid}/join", json={"password": "secret2", "seat": 2, "player": "Carol", "race": "Zed"})
    t3 = r.json()["token"]
    g = r.json()["game"]
    assert g["seats"][1]["race"] == "Bobbers" and g["seats"][1]["player"] == "Carol"
    assert c.post(f"/api/games/{gid}/submit", headers=H(t3)).json()["turn_ran"]
    # the host leaving keeps the host role with the host login (W-23) ...
    c.post(f"/api/games/{gid}/leave", headers=H(t1))
    g = c.get(f"/api/games/{gid}").json()
    assert g["host_seat"] is None and g["host_only"]
    assert c.post(f"/api/games/{gid}/force", headers=H(t3)).status_code == 403
    ht = c.post(f"/api/games/{gid}/host/login", json={"password": "secret1"}).json()["token"]
    assert c.post(f"/api/games/{gid}/force", headers=H(ht)).json()["turn"] == 3
    # ... and in a game without a host password (from before W-23) it passes to a seated player
    gm = env["app"].state.games[gid]
    gm.meta.pop("host_auth")
    gm.meta["host"] = 2
    t1b = c.post(f"/api/games/{gid}/join", json={"password": "secret2", "seat": 1,
                                                 "player": "Dan"}).json()["token"]
    c.post(f"/api/games/{gid}/leave", headers=H(t3))
    assert c.get(f"/api/games/{gid}").json()["host_seat"] == 1
    # the new host is asked for a host password before using host powers (Dave 2026-11-15)
    r = c.post(f"/api/games/{gid}/force", headers=H(t1b))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "set_host_password"
    assert c.post(f"/api/games/{gid}/host/password", headers=H(t1b),
                  json={"new": "danhost"}).status_code == 200
    assert c.post(f"/api/games/{gid}/force", headers=H(t1b)).json()["turn"] == 4


def test_game_over_and_drop(env):
    c, gid, t1, t2 = env["c"], env["gid"], env["t1"], env["t2"]
    env["app"].state.games[gid].state.winner = 1
    assert c.post(f"/api/games/{gid}/submit", headers=H(t1)).status_code == 409
    assert c.post(f"/api/games/{gid}/force", headers=H(t1)).status_code == 409
    assert c.delete(f"/api/games/{gid}").status_code == 401
    assert c.delete(f"/api/games/{gid}", headers=H(t2)).json() == {"dropped": gid}
    assert c.get(f"/api/games/{gid}").status_code == 404
    assert not (env["dir"] / "games" / gid).exists()


# ---------------------------------------------------------------- chat
def test_chat_public_private_and_contact_rule(env):
    c, gid, t1, t2, app = env["c"], env["gid"], env["t1"], env["t2"], env["app"]
    m = c.post(f"/api/games/{gid}/chat", json={"text": "hello all"}, headers=H(t1)).json()
    assert m["from_name"] == "Daves" and m["to"] is None
    assert c.post(f"/api/games/{gid}/chat", json={"text": "x"}).status_code == 401
    # no contact yet: private messages are refused (rules:710-713, 242-245)
    r = c.post(f"/api/games/{gid}/chat", json={"text": "psst", "to": 2}, headers=H(t1))
    assert r.status_code == 403
    assert c.get(f"/api/games/{gid}/chat", headers=H(t1)).json()["recipients"] == []
    st = app.state.games[gid].state
    st.empires[1].relations[2] = "N"
    st.empires[2].relations[1] = "N"
    st.empires[1].relations[5] = "N"                                  # an NPR
    st.empires[5].relations[1] = "N"
    assert c.get(f"/api/games/{gid}/chat", headers=H(t1)).json()["recipients"] == [
        {"empire": 2, "race": "Bobbers", "player": "Bob"}]
    p = c.post(f"/api/games/{gid}/chat", json={"text": "psst", "to": 2}, headers=H(t1)).json()
    assert p["to_name"] == "Bobbers"
    assert c.post(f"/api/games/{gid}/chat", json={"text": "hi npr", "to": 5},
                  headers=H(t1)).status_code == 400
    assert c.post(f"/api/games/{gid}/chat", json={"text": "me", "to": 1},
                  headers=H(t1)).status_code == 400
    texts = lambda tok: [x["text"] for x in c.get(f"/api/games/{gid}/chat",
                                                  headers=H(tok) if tok else {}).json()["messages"]
                         if not x["system"]]
    assert texts(t1) == ["hello all", "psst"] and texts(t2) == ["hello all", "psst"]
    assert texts(None) == ["hello all"]                               # spectators: public only
    since = c.get(f"/api/games/{gid}/chat?since={p['id']}", headers=H(t2)).json()
    assert since["messages"] == [] and since["last"] == p["id"]


# ---------------------------------------------------------------- non-leakage over the wire
def test_view_over_api_leaks_nothing_of_the_other_seat(env):
    c, gid, t1, t2, app = env["c"], env["gid"], env["t1"], env["t2"], env["app"]
    h2 = home_name(c, gid, t2)
    c.put(f"/api/games/{gid}/orders", json={"text": f"ECHO zzsecret\nCF ZZFLEET 50 50\n"
                                                    f"BS {h2} F"}, headers=H(t2))
    c.post(f"/api/games/{gid}/chat", json={"text": "never"}, headers=H(t2))
    c.post(f"/api/games/{gid}/submit", headers=H(t2))
    c.post(f"/api/games/{gid}/submit", headers=H(t1))
    st = app.state.games[gid].state
    assert st.turn == 1 and 2 not in st.empires[1].relations
    text = c.get(f"/api/games/{gid}/view", headers=H(t1)).text
    for secret in ("zzsecret", "ZZFLEET", h2, "Emperor_2", "Bobbers"):
        assert secret not in text, secret
    v = json.loads(text)
    b_numbers = {n for n, s in st.ships.items() if s.owner == 2}
    assert not b_numbers & {s["number"] for s in v["ships"] + v["scans"]["ships"]}
    b_sys = {s.id for s in st.systems if s.owner == 2}
    assert not b_sys & {s["id"] for s in v["systems"] + v["known_systems"]
                        + v["scans"]["systems"]}
    assert "eu" not in json.dumps(v["races"])
    # the other seat's draft and check endpoints are its own
    assert c.get(f"/api/games/{gid}/orders", headers=H(t1)).json()["orders"] == []


# ---------------------------------------------------------------- persistence
def test_persistence_across_restart(env):
    c, gid, t1, t2 = env["c"], env["gid"], env["t1"], env["t2"]
    for t in (t1, t2):          # AOMT off (on by default, W-30): a forced turn gives no orders
        c.post(f"/api/games/{gid}/aomt", json={"on": False}, headers=H(t))
    c.post(f"/api/games/{gid}/force", headers=H(t1))
    home = home_name(c, gid, t1)
    c.put(f"/api/games/{gid}/orders", json={"text": f"BS {home} F"}, headers=H(t1))
    c.post(f"/api/games/{gid}/submit", headers=H(t1))
    c.post(f"/api/games/{gid}/chat", json={"text": "remember me"}, headers=H(t2))
    before = env["app"].state.games[gid]
    snap = (M.dumps(before.state), json.dumps(before.results, sort_keys=True),
            c.get(f"/api/games/{gid}/view", headers=H(t2)).json())

    app2 = create_app(env["dir"])                       # a fresh server on the same SAVE_DIR
    c2 = TestClient(app2)
    after = app2.state.games[gid]
    assert M.dumps(after.state) == snap[0]
    assert json.dumps(after.results, sort_keys=True) == snap[1]
    assert c2.get(f"/api/games/{gid}/view", headers=H(t2)).json() == snap[2]
    assert c2.get(f"/api/games/{gid}/version").json()["submitted"] == [1]
    assert c2.get(f"/api/games/{gid}/orders", headers=H(t1)).json()["orders"][0]["text"] \
        == f"BS {home} F"
    assert any(m["text"] == "remember me"
               for m in c2.get(f"/api/games/{gid}/chat").json()["messages"])
    assert c2.post(f"/api/games/{gid}/submit", headers=H(t2)).json()["turn_ran"]
    assert c2.get(f"/api/games/{gid}/view?turn=1", headers=H(t1)).status_code == 200
    v = c2.get(f"/api/games/{gid}/view", headers=H(t1)).json()
    assert v["game"]["turn"] == 2 and len(v["ships"]) == 3
    # a half-written turn (no commit in meta.json) is ignored on restart
    (env["dir"] / "games" / gid / "turns" / "3").mkdir()
    (env["dir"] / "games" / gid / "turns" / "3" / "state.json").write_text("garbage")
    assert create_app(env["dir"]).state.games[gid].state.turn == 2


def test_unreadable_game_is_skipped(tmp_path):
    (tmp_path / "games" / "0badbeef").mkdir(parents=True)
    (tmp_path / "games" / "0badbeef" / "meta.json").write_text("{not json")
    c = TestClient(create_app(tmp_path))
    assert c.get("/api/games").json() == []


# ---------------------------------------------------------------- concurrency
def test_concurrent_submits_run_each_turn_once(env):
    app, gid, t1, t2 = env["app"], env["gid"], env["t1"], env["t2"]
    for rnd in range(8):
        barrier = threading.Barrier(2)
        out = {}

        def go(tok):
            cl = TestClient(app)
            barrier.wait()
            out[tok] = cl.post(f"/api/games/{gid}/submit", headers=H(tok)).json()

        th = [threading.Thread(target=go, args=(t,)) for t in (t1, t2)]
        [t.start() for t in th]
        [t.join() for t in th]
        ran = [r["turn_ran"] for r in out.values()]
        assert sorted(ran) == [False, True], out
        assert app.state.games[gid].state.turn == rnd + 1
    turns = sorted(int(p.name) for p in (env["dir"] / "games" / gid / "turns").iterdir())
    assert turns == list(range(0, 9))


def test_concurrent_chat_ids_unique(env):
    app, gid, t1, t2 = env["app"], env["gid"], env["t1"], env["t2"]

    def spam(tok):
        cl = TestClient(app)
        for i in range(25):
            assert cl.post(f"/api/games/{gid}/chat", json={"text": f"{tok[:4]} {i}"},
                           headers=H(tok)).status_code == 200

    th = [threading.Thread(target=spam, args=(t,)) for t in (t1, t2, t1)]
    [t.start() for t in th]
    [t.join() for t in th]
    msgs = TestClient(app).get(f"/api/games/{gid}/chat?limit=2000").json()["messages"]
    ids = [m["id"] for m in msgs]
    assert len(ids) == len(set(ids)) and len([m for m in msgs if not m["system"]]) == 75
    reloaded = create_app(env["dir"]).state.games[gid]
    assert len(reloaded.chat) == len(msgs)
