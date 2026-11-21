"""Race passwords, sessions, no limit on wrong tries, the pre-password migration, the host's
password reset and hand-to-computer, and the host's export at any time (DECISIONS W-17, W-21,
W-22)."""
from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import create_app
from mhgc import model as M
from mhgc.npr import npr_orders
from mhgc.npr.brain import inbox


def H(tok):
    return {"X-Seat-Token": tok}


def new(c, humans=2, size=8, seed=21, pw="alpha1", race="Daves"):
    r = c.post("/api/games", json={"humans": humans, "size": size, "player": "Dave", "race": race,
                                   "seed": seed, "password": pw, "host_password": pw})
    assert r.status_code == 200, r.text
    return r.json()["id"], r.json()["token"]


def join(c, gid, seat, pw, race=None, player="Bob"):
    body = {"seat": seat, "player": player, "password": pw} | ({"race": race} if race else {})
    r = c.post(f"/api/games/{gid}/join", json=body)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def login(c, gid, seat, pw):
    return c.post(f"/api/games/{gid}/login", json={"seat": seat, "password": pw})


@pytest.fixture
def env(tmp_path):
    app = create_app(tmp_path)
    c = TestClient(app)
    gid, t1 = new(c)
    t2 = join(c, gid, 2, "bravo2", race="Bobbers")
    return {"app": app, "c": c, "gid": gid, "t1": t1, "t2": t2, "dir": tmp_path}


# ---------------------------------------------------------------- create, join, login
def test_create_and_join_need_a_password(tmp_path):
    c = TestClient(create_app(tmp_path))
    for bad in ("", "abc"):
        r = c.post("/api/games", json={"humans": 2, "player": "D", "password": bad,
                                       "host_password": "goodhost"})
        assert r.status_code == 400 and "at least 4" in r.json()["detail"]
    assert c.post("/api/games", json={"humans": 2, "player": "D"}).status_code == 400
    gid, t1 = new(c, pw="abcd")                               # 4 is enough
    r = c.post(f"/api/games/{gid}/join", json={"seat": 2, "player": "B", "password": "xyz"})
    assert r.status_code == 400
    assert c.get(f"/api/games/{gid}").json()["open_seats"] == [2]
    assert c.get(f"/api/games/{gid}/view", headers=H(t1)).status_code == 200


def test_validation_errors_never_echo_the_password(tmp_path):
    c = TestClient(create_app(tmp_path))
    r = c.post("/api/games", json={"humans": "lots", "player": "D", "password": "s3cretXYZ",
                                   "host_password": "s3cretXYZ"})
    assert r.status_code == 422 and "s3cretXYZ" not in r.text
    gid, _ = new(c)
    r = c.post(f"/api/games/{gid}/login", json={"seat": "two", "password": "s3cretXYZ"})
    assert r.status_code == 422 and "s3cretXYZ" not in r.text


def test_login_right_and_wrong(env):
    c, gid = env["c"], env["gid"]
    r = login(c, gid, 2, "nope")
    assert r.status_code == 403 and r.json()["detail"] == "Wrong password for the Bobbers."
    r = login(c, gid, 2, "bravo2")
    assert r.status_code == 200
    d = r.json()
    assert d["seat"] == 2 and d["race"] == "Bobbers" and not d["must_set_password"]
    v = c.get(f"/api/games/{gid}/view", headers=H(d["token"])).json()
    assert v["empire"]["id"] == 2
    assert login(c, gid, 3, "x1234").status_code == 404   # no such human seat (2 humans)
    assert login(c, "deadbeef", 1, "alpha1").status_code == 404


def test_login_to_an_open_seat_is_refused(tmp_path):
    c = TestClient(create_app(tmp_path))
    gid, _ = new(c, humans=3)
    r = login(c, gid, 3, "whatever")
    assert r.status_code == 404 and "take the open seat" in r.json()["detail"]


def test_no_lockout_after_many_wrong_tries(env):
    """Dave 2026-11-15: no limit on wrong password tries (a few players, not a critical app)."""
    c, gid = env["c"], env["gid"]
    for _ in range(40):
        r = login(c, gid, 2, "bad!")
        assert r.status_code == 403 and "retry-after" not in r.headers
        assert r.json()["detail"] == "Wrong password for the Bobbers."
    assert login(c, gid, 2, "bravo2").status_code == 200      # the right one still works at once
    for _ in range(40):
        r = c.post(f"/api/games/{gid}/host/login", json={"password": "bad1"})
        assert r.status_code == 403 and "retry-after" not in r.headers
    assert c.post(f"/api/games/{gid}/host/login", json={"password": "alpha1"}).status_code == 200
    assert not hasattr(auth, "LoginLimiter")


def test_hashing():
    rec = auth.hash_password("hunter22")
    assert rec["alg"] == "scrypt" and len(bytes.fromhex(rec["salt"])) == 16
    assert "hunter22" not in json.dumps(rec)
    assert auth.verify_password("hunter22", rec) and not auth.verify_password("hunter23", rec)
    assert auth.hash_password("hunter22")["hash"] != rec["hash"]          # per-race salt
    assert not auth.verify_password("x", None)


# ---------------------------------------------------------------- sessions
def test_several_sessions_for_one_race(env):
    c, gid, t2 = env["c"], env["gid"], env["t2"]
    a = login(c, gid, 2, "bravo2").json()["token"]
    b = login(c, gid, 2, "bravo2").json()["token"]
    assert len({t2, a, b}) == 3
    for t in (t2, a, b):
        assert c.get(f"/api/games/{gid}", headers=H(t)).json()["you"] == 2
    c.put(f"/api/games/{gid}/orders", headers=H(a), json={"text": "PT 2"})
    assert [o["code"] for o in c.get(f"/api/games/{gid}/orders", headers=H(b)).json()["orders"]] \
        == ["PT"]                                         # one race, one draft
    # logging out drops only that browser
    assert c.post(f"/api/games/{gid}/logout", headers=H(a)).json()["sessions_ended"] == 1
    assert c.get(f"/api/games/{gid}/view", headers=H(a)).status_code == 401
    assert c.get(f"/api/games/{gid}/view", headers=H(b)).status_code == 200
    assert c.post(f"/api/games/{gid}/logout", headers=H(a)).status_code == 401
    # log out everywhere
    r = c.post(f"/api/games/{gid}/logout", headers=H(b), json={"everywhere": True}).json()
    assert r["sessions_ended"] == 2
    for t in (t2, b):
        assert c.get(f"/api/games/{gid}/view", headers=H(t)).status_code == 401
    assert c.get(f"/api/games/{gid}").json()["seats"][1]["player"] == "Bob"   # still seated
    assert login(c, gid, 2, "bravo2").status_code == 200


def test_one_person_two_races(tmp_path):
    """Dave holds seats 1 and 3, Bob seat 2.  Each of Dave's races is its own seat: separate
    views, drafts, submissions and private chat; the turn runs when all three have submitted."""
    c = TestClient(create_app(tmp_path))
    gid, d1 = new(c, humans=3, size=8)
    b2 = join(c, gid, 2, "bobpass", race="Bobbers")
    d3 = join(c, gid, 3, "dave-two", race="Second", player="Dave")
    g = c.get(f"/api/games/{gid}").json()
    assert [(s["player"], s["race"]) for s in g["seats"]] == [
        ("Dave", "Daves"), ("Bob", "Bobbers"), ("Dave", "Second")]
    v1 = c.get(f"/api/games/{gid}/view", headers=H(d1)).json()
    v3 = c.get(f"/api/games/{gid}/view", headers=H(d3)).json()
    assert v1["empire"]["id"] == 1 and v3["empire"]["id"] == 3
    own3 = {s["id"] for s in v3["systems"]}
    assert not own3 & {s["id"] for s in v1["systems"]}
    ships3 = {s["number"] for s in v3["ships"]}
    t1 = json.dumps(v1)
    assert all(f'"number": {n},' not in t1 for n in ships3 if n not in
               {s["number"] for s in v1["ships"]})
    assert "Second" not in json.dumps(v1["races"])           # not contacted
    # each race submits separately; the turn waits for every human seat
    assert not c.post(f"/api/games/{gid}/submit", headers=H(d1)).json()["turn_ran"]
    assert not c.post(f"/api/games/{gid}/submit", headers=H(b2)).json()["turn_ran"]
    assert c.get(f"/api/games/{gid}").json()["waiting_for"] == [3]
    assert c.post(f"/api/games/{gid}/submit", headers=H(d3)).json()["turn_ran"]
    # the password of one race doesn't open the other
    assert login(c, gid, 3, "alpha1").status_code == 403
    assert login(c, gid, 1, "dave-two").status_code == 403


def test_change_password(env):
    c, gid, t2 = env["c"], env["gid"], env["t2"]
    other = login(c, gid, 2, "bravo2").json()["token"]
    r = c.post(f"/api/games/{gid}/password", headers=H(t2), json={"new": "charlie3"})
    assert r.status_code == 403 and "current password" in r.json()["detail"]
    r = c.post(f"/api/games/{gid}/password", headers=H(t2),
               json={"new": "ch", "current": "bravo2"})
    assert r.status_code == 400
    r = c.post(f"/api/games/{gid}/password", headers=H(t2),
               json={"new": "charlie3", "current": "bravo2"})
    assert r.status_code == 200 and r.json()["you"] == 2
    assert c.get(f"/api/games/{gid}/view", headers=H(t2)).status_code == 200   # this one stays
    assert c.get(f"/api/games/{gid}/view", headers=H(other)).status_code == 401  # others out
    assert login(c, gid, 2, "bravo2").status_code == 403
    assert login(c, gid, 2, "charlie3").status_code == 200
    assert c.post(f"/api/games/{gid}/password", json={"new": "zzzz"}).status_code == 401


def test_host_reset(env):
    c, gid, t1, t2 = env["c"], env["gid"], env["t1"], env["t2"]
    url = f"/api/games/{gid}/seats/2/reset-password"
    assert c.post(url, headers=H(t2), json={"password": "temp"}).status_code == 403   # not host
    assert c.post(f"/api/games/{gid}/seats/1/reset-password", headers=H(t1),
                  json={"password": "temp"}).status_code == 400                       # own race
    assert c.post(f"/api/games/{gid}/seats/5/reset-password", headers=H(t1),
                  json={"password": "temp"}).status_code == 404
    assert c.post(url, headers=H(t1), json={"password": "te"}).status_code == 400
    r = c.post(url, headers=H(t1), json={"password": "temp"})
    assert r.status_code == 200
    assert c.get(f"/api/games/{gid}/view", headers=H(t2)).status_code == 401          # logged out
    assert login(c, gid, 2, "bravo2").status_code == 403
    d = login(c, gid, 2, "temp").json()
    assert d["must_set_password"]
    tok = d["token"]
    # until a new password is set the race can't play
    r = c.get(f"/api/games/{gid}/view", headers=H(tok))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "set_password"
    assert c.post(f"/api/games/{gid}/submit", headers=H(tok)).status_code == 403
    g = c.get(f"/api/games/{gid}", headers=H(tok)).json()
    assert g["you"] == 2 and g["you_must_set_password"]
    assert c.post(f"/api/games/{gid}/password", headers=H(tok),
                  json={"new": "newpass"}).status_code == 200           # no current needed
    assert c.get(f"/api/games/{gid}/view", headers=H(tok)).status_code == 200
    assert not c.get(f"/api/games/{gid}", headers=H(tok)).json()["you_must_set_password"]
    chat = c.get(f"/api/games/{gid}/chat").json()["messages"]
    assert any("reset the password of the Bobbers" in m["text"] for m in chat)


def test_leave_clears_the_password(env):
    c, gid, t2 = env["c"], env["gid"], env["t2"]
    c.post(f"/api/games/{gid}/leave", headers=H(t2))
    assert login(c, gid, 2, "bravo2").status_code == 404
    meta = json.loads((env["dir"] / "games" / gid / "meta.json").read_text())
    assert meta["seats"]["2"] is None
    t = join(c, gid, 2, "fresh1", player="Carol")
    assert login(c, gid, 2, "fresh1").status_code == 200 and t


# ---------------------------------------------------------------- migration
def _make_old_save(tmp_path):
    """A game saved before passwords: seats with a token hash only."""
    c = TestClient(create_app(tmp_path))
    gid, t1 = new(c, humans=3)
    join(c, gid, 2, "bravo2")
    p = tmp_path / "games" / gid / "meta.json"
    meta = json.loads(p.read_text())
    old = {"1": "a" * 32, "2": "b" * 32}
    for k, tok in old.items():
        meta["seats"][k] = {"player": meta["seats"][k]["player"], "joined": 1.0,
                            "token_hash": auth.token_hash(tok)}
    p.write_text(json.dumps(meta))
    return gid, old


def test_old_token_migration(tmp_path):
    gid, old = _make_old_save(tmp_path)
    c = TestClient(create_app(tmp_path))                  # the restart migrates meta.json
    meta = json.loads((tmp_path / "games" / gid / "meta.json").read_text())
    assert "token_hash" not in meta["seats"]["1"] and meta["seats"]["1"]["pw"] is None
    t1 = old["1"]
    g = c.get(f"/api/games/{gid}", headers=H(t1)).json()
    assert g["you"] == 1 and g["you_must_set_password"]                 # the old token works...
    assert not g["seats"][0]["password"]
    r = c.get(f"/api/games/{gid}/view", headers=H(t1))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "set_password"   # ...to set one
    assert c.post(f"/api/games/{gid}/force", headers=H(t1)).status_code == 403
    # nobody can log in to a pre-password race, and nobody can join it
    r = login(c, gid, 2, "anything")
    assert r.status_code == 409 and "no password yet" in r.json()["detail"]
    assert c.post(f"/api/games/{gid}/join",
                  json={"seat": 2, "player": "Thief", "password": "mine"}).status_code == 409
    # seat 1 sets a password and plays on with the same token
    assert c.post(f"/api/games/{gid}/password", headers=H(t1),
                  json={"new": "dave-pw"}).status_code == 200
    assert c.get(f"/api/games/{gid}/view", headers=H(t1)).status_code == 200
    assert login(c, gid, 1, "dave-pw").status_code == 200
    # seat 2's token is "lost": the host resets it, and the race can be claimed with the password
    assert c.post(f"/api/games/{gid}/seats/2/reset-password", headers=H(t1),
                  json={"password": "claim2"}).status_code == 200
    assert c.get(f"/api/games/{gid}/view", headers=H(old["2"])).status_code == 401
    d = login(c, gid, 2, "claim2").json()
    assert d["must_set_password"]
    c.post(f"/api/games/{gid}/password", headers=H(d["token"]), json={"new": "bob-own"})
    assert c.get(f"/api/games/{gid}/view", headers=H(d["token"])).status_code == 200


# ---------------------------------------------------------------- nothing secret leaks
def test_no_hashes_or_passwords_in_any_response(tmp_path, monkeypatch):
    from mhgc.data import constants as K
    app = create_app(tmp_path)
    c = TestClient(app)
    gid, t1 = new(c, humans=2, pw="pw-one-1")
    t2 = join(c, gid, 2, "pw-two-2")
    t2b = login(c, gid, 2, "pw-two-2").json()["token"]
    c.post(f"/api/games/{gid}/chat", headers=H(t1), json={"text": "hello"})
    for _ in range(2):
        c.post(f"/api/games/{gid}/force", headers=H(t1))
    meta = app.state.games[gid].meta
    secrets_ = {"pw-one-1", "pw-two-2", "scrypt"}
    for s in meta["seats"].values():
        secrets_ |= {s["pw"]["salt"], s["pw"]["hash"]}
        secrets_ |= {x["h"] for x in s["sessions"]}
    texts = []
    for tok in (t1, t2, t2b, None):
        hdr = H(tok) if tok else {}
        for path in ("", "/view", "/view?turn=1", "/stats", "/turns", "/orders", "/chat",
                     "/version", "/final"):
            texts.append(c.get(f"/api/games/{gid}{path}", headers=hdr).text)
    texts.append(c.get("/api/games").text)
    texts.append(login(c, gid, 2, "pw-two-2").text)
    texts.append(login(c, gid, 2, "wrong-pw").text)
    texts.append(c.post(f"/api/games/{gid}/password", headers=H(t2b),
                        json={"new": "pw-two-3", "current": "pw-two-2"}).text)
    texts.append(c.post(f"/api/games/{gid}/seats/2/reset-password", headers=H(t1),
                        json={"password": "temp-22"}).text)
    texts.append(c.post(f"/api/games/{gid}/leave", headers=H(t2b)).text)
    monkeypatch.setattr(K, "VICTORY_POINTS", 1)
    c.post(f"/api/games/{gid}/force", headers=H(t1))
    texts.append(c.get(f"/api/games/{gid}/final").text)
    z = zipfile.ZipFile(io.BytesIO(c.get(f"/api/games/{gid}/export", headers=H(t1)).content))
    texts += [z.read(n).decode() for n in z.namelist()]
    blob = "\n".join(texts)
    for s in secrets_ - {"pw-two-2"}:
        assert s not in blob, s
    assert "pw-two-2" not in blob.replace('"password"', "")
    for word in ("token_hash", "sessions", '"pw"', "salt"):
        assert word not in blob, word


# ---------------------------------------------------------------- hand a race to the computer
def test_hand_to_computer_end_to_end(tmp_path):
    from mhgc.npr.memory import PERSONA_ORDER
    app = create_app(tmp_path)
    c = TestClient(app)
    gid, t1 = new(c, humans=3, size=8, seed=5)
    t2 = join(c, gid, 2, "bobpass", race="Bobbers")
    for t in (t1, t2):          # AOMT off (on by default, W-30): forced turns give no orders
        c.post(f"/api/games/{gid}/aomt", json={"on": False}, headers=H(t))
    for _ in range(3):
        c.post(f"/api/games/{gid}/force", headers=H(t1))
    c.put(f"/api/games/{gid}/orders", headers=H(t2), json={"text": "PT 2"})
    c.post(f"/api/games/{gid}/submit", headers=H(t2))
    url = f"/api/games/{gid}/seats/2/computer"
    rel_before = dict(app.state.games[gid].state.empires[2].relations)
    assert c.post(url, headers=H(t2)).status_code == 403                  # host only
    assert c.post(f"/api/games/{gid}/seats/1/computer", headers=H(t1)).status_code == 400
    r = c.post(url, headers=H(t1))
    assert r.status_code == 200 and not r.json()["turn_ran"]              # seat 3 still open
    g = r.json()["game"]
    s2 = g["seats"][1]
    assert s2["computer"] and not s2["open"] and s2["player"] is None and not s2["needs_orders"]
    assert 2 not in g["open_seats"] and 2 not in g["waiting_for"]
    assert c.post(url, headers=H(t1)).status_code == 404                  # already done
    g_ = app.state.games[gid]
    st = g_.state
    assert st.empires[2].kind == M.NPR
    assert st.npr_state[2]["persona"]["name"] in PERSONA_ORDER
    assert not g_.draft_path(2).exists() and 2 not in g_.meta["submitted"]
    assert c.get(f"/api/games/{gid}/view", headers=H(t2)).status_code == 401   # sessions gone
    assert login(c, gid, 2, "bobpass").status_code == 409
    assert c.post(f"/api/games/{gid}/join",
                  json={"seat": 2, "player": "X", "password": "abcd"}).status_code == 409
    chat = c.get(f"/api/games/{gid}/chat").json()["messages"]
    assert any("handed the Bobbers" in m["text"] for m in chat)
    # the open seat 3 too, and then the turn runs without waiting for either
    r = c.post(f"/api/games/{gid}/seats/3/computer", headers=H(t1)).json()
    assert r["game"]["waiting_for"] == [1]
    turn = c.post(f"/api/games/{gid}/submit", headers=H(t1)).json()
    assert turn["turn_ran"] and turn["turn"] == 4
    # the bot gave orders, all valid: none rejected for syntax, most succeed
    orders = json.loads((tmp_path / "games" / gid / "turns" / "4" / "orders.json").read_text())
    assert orders["2"] and all(o["by"] == "computer" for o in orders["2"])
    assert sum(o["ok"] is True for o in orders["2"]) >= len(orders["2"]) * 0.7
    # the logs mark the conversion; it is unranked from then on
    lines = [json.loads(x) for x in (tmp_path / "games" / gid / "standings.jsonl")
             .read_text().splitlines()]
    row = {r["turn"]: next(e for e in r["empires"] if e["id"] == 2) for r in lines}
    assert row[3]["human"] and row[3]["converted_turn"] is None
    assert not row[4]["human"] and row[4]["converted_turn"] == 3
    bot = [json.loads(x) for x in (tmp_path / "games" / gid / "botlog.jsonl")
           .read_text().splitlines()]
    first = next(b for b in bot if b["empire"] == 2)
    assert first["turn"] == 4 and first["converted"] == {"from": "human", "turn": 3,
                                                         "player": "Bob"}
    assert next(b for b in bot if b["empire"] == 3).get("converted")["player"] is None
    # the final/export views say who played it
    emp = {e["id"]: e for e in __import__("app.analysis_api", fromlist=["x"])
           ._empires(g_, None)}
    assert emp[2]["converted_turn"] == 3 and not emp[2]["human"] and emp[2]["player"] == "Bob"
    # relations carry over unchanged (the stored turn-3 state is the converted one)
    assert g_.turn_data(3)[0].empires[2].relations == rel_before
    assert g_.turn_data(3)[0].empires[2].kind == M.NPR
    # a restart keeps it a computer empire
    c2 = TestClient(create_app(tmp_path))
    g2 = c2.get(f"/api/games/{gid}").json()
    assert g2["seats"][1]["computer"] and g2["waiting_for"] == [1]


def test_hand_to_computer_runs_the_turn_when_everyone_else_is_in(env):
    c, gid, t1 = env["c"], env["gid"], env["t1"]
    assert not c.post(f"/api/games/{gid}/submit", headers=H(t1)).json()["turn_ran"]
    r = c.post(f"/api/games/{gid}/seats/2/computer", headers=H(t1)).json()
    assert r["turn_ran"] and r["turn"] == 1


def test_handed_over_bot_knows_only_its_own_empire(tmp_path):
    """The new memory holds nothing but the race's own last report, and the bot's orders don't
    change when other empires' hidden figures do."""
    app = create_app(tmp_path)
    c = TestClient(app)
    gid, t1 = new(c, humans=2, size=8, seed=8)
    join(c, gid, 2, "bobpass")
    for _ in range(4):
        c.post(f"/api/games/{gid}/force", headers=H(t1))
    g = app.state.games[gid]
    before = M.from_dict(M.to_dict(g.state))
    c.post(f"/api/games/{gid}/seats/2/computer", headers=H(t1))
    mem = g.state.npr_state[2]
    assert set(mem["inbox"]["reports"]) == {"2"}
    own = (g.results["reports"].get("2") or {})
    assert sorted(c_["id"] for c_ in mem["inbox"]["combats"]) == sorted(own.get("combats", []))
    assert mem["races"] == {} and mem["intel"] == {} and mem["history"] == []
    # the same as the inbox an NPR keeps from its own report
    from mhgc.npr import adopt
    st2 = M.from_dict(M.to_dict(before))
    adopt(st2, 2, g.results)
    assert st2.npr_state[2] == mem
    # scramble what empire 2 can't see: the other empires' stockpiles and techs
    a = M.from_dict(M.to_dict(g.state))
    b = M.from_dict(M.to_dict(g.state))
    for eid, e in b.empires.items():
        if eid not in (0, 2):
            e.eu, e.iu_depot = e.eu + 5000, e.iu_depot + 777
    oa = [o.to_text() for o in npr_orders(a, 2)]
    ob = [o.to_text() for o in npr_orders(b, 2)]
    assert oa and oa == ob


def test_inbox_from_stored_results_matches_the_live_one(tmp_path):
    """adopt() rebuilds the report from results.json; it must equal what observe_turn keeps."""
    from mhgc.engine.turn import run_turn
    from mhgc.mapgen import new_game
    from mhgc.npr import adopt
    st = new_game("t", 3, ["A", "B"], size=8)
    for _ in range(3):
        res = run_turn(st, {})
    live = inbox(res, 2)
    st2 = M.from_dict(M.to_dict(st))
    adopt(st2, 2, json.loads(json.dumps(res.to_dict())))
    assert st2.npr_state[2]["inbox"] == live


def test_host_exports_any_time_others_at_the_end(env):
    c, gid, t1, t2 = env["c"], env["gid"], env["t1"], env["t2"]
    assert c.get(f"/api/games/{gid}/export", headers=H(t1)).status_code == 200
    r = c.get(f"/api/games/{gid}/export", headers=H(t2))
    assert r.status_code == 403 and "only the host" in r.json()["detail"]
