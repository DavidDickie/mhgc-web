"""The host login and host-only games, View as, the host audit log, opening a computer empire
for a human, and games only the host advances (DECISIONS W-22, W-23, W-24)."""
from __future__ import annotations

import io
import json
import zipfile

from fastapi.testclient import TestClient

from app.main import create_app
from mhgc import model as M
from mhgc.view import view as build_view


def H(tok):
    return {"X-Seat-Token": tok}


def host_game(c, humans=2, size=8, seed=31, pw="hostpw"):
    r = c.post("/api/games", json={"humans": humans, "size": size, "player": "Admin",
                                   "seed": seed, "host_only": True, "host_password": pw})
    assert r.status_code == 200, r.text
    return r.json()


def join(c, gid, seat, pw, player="P", race=None):
    r = c.post(f"/api/games/{gid}/join", json={"seat": seat, "player": player, "password": pw}
               | ({"race": race} if race else {}))
    assert r.status_code == 200, r.text
    return r.json()["token"]


def audit(tmp_path, gid):
    p = tmp_path / "games" / gid / "host_audit.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


# ---------------------------------------------------------------- host-only games
def test_host_only_creation(tmp_path):
    c = TestClient(create_app(tmp_path))
    assert c.post("/api/games", json={"humans": 2, "player": "A", "host_only": True,
                                      "host_password": "abc"}).status_code == 400
    r = host_game(c)
    g = r["game"]
    assert r["seat"] is None and r["host"] and g["host_seat"] is None and g["host_only"]
    assert g["open_seats"] == [1, 2] and all(not s["host"] for s in g["seats"])
    ht = r["token"]
    me = c.get(f"/api/games/{r['id']}", headers=H(ht)).json()
    assert me["you"] is None and me["you_host"] and me["you_host_login"]
    assert c.get(f"/api/games/{r['id']}/view", headers=H(ht)).status_code == 401  # no race
    # players take the open seats and name their races (turn 0); none of them is host
    t1 = join(c, r["id"], 1, "one1", race="Ones")
    g = c.get(f"/api/games/{r['id']}", headers=H(t1)).json()
    assert g["host_seat"] is None and not g["you_host"]
    assert c.post(f"/api/games/{r['id']}/force", headers=H(t1)).status_code == 403
    chat = c.get(f"/api/games/{r['id']}/chat").json()["messages"]
    assert "hosts it without a race" in chat[0]["text"]


def test_the_host_is_not_waited_on(tmp_path):
    c = TestClient(create_app(tmp_path))
    r = host_game(c)
    gid = r["id"]
    t1, t2 = join(c, gid, 1, "one1"), join(c, gid, 2, "two2", player="Q")
    assert not c.post(f"/api/games/{gid}/submit", headers=H(t1)).json()["turn_ran"]
    assert c.get(f"/api/games/{gid}").json()["waiting_for"] == [2]
    assert c.post(f"/api/games/{gid}/submit", headers=H(t2)).json()["turn_ran"]


def test_host_login_from_the_lobby_and_for_a_playing_host(tmp_path):
    app = create_app(tmp_path)
    c = TestClient(app)
    r = c.post("/api/games", json={"humans": 2, "player": "Dave", "password": "racepw",
                                   "seed": 3, "host_password": "racepw"}).json()
    gid, t1 = r["id"], r["token"]
    # the host password given as the race password
    assert c.post(f"/api/games/{gid}/host/login", json={"password": "nope"}).status_code == 403
    h = c.post(f"/api/games/{gid}/host/login", json={"password": "racepw"}).json()
    assert h["host"] and h["seat"] is None
    # change it (from the race); other host logins end
    assert c.post(f"/api/games/{gid}/host/password", headers=H(t1),
                  json={"new": "hostpw2"}).status_code == 403          # needs the current one
    assert c.post(f"/api/games/{gid}/host/password", headers=H(t1),
                  json={"new": "hostpw2", "current": "racepw"}).status_code == 200
    assert not c.get(f"/api/games/{gid}", headers=H(h["token"])).json()["you_host"]
    assert c.post(f"/api/games/{gid}/host/login", json={"password": "hostpw2"}).status_code \
        == 200
    # an old game without a host password: the host's race sets one
    gm = app.state.games[gid]
    gm.meta.pop("host_auth")
    assert c.post(f"/api/games/{gid}/host/login", json={"password": "x1234"}).status_code == 409
    assert c.post(f"/api/games/{gid}/host/password", headers=H(t1),
                  json={"new": "fresh-host"}).status_code == 200
    assert c.post(f"/api/games/{gid}/host/login", json={"password": "fresh-host"}).status_code \
        == 200
    # no lockout: wrong host passwords never stop the right one (Dave 2026-11-15)
    for _ in range(25):
        assert c.post(f"/api/games/{gid}/host/login", json={"password": "bad1"}).status_code \
            == 403
    tok = c.post(f"/api/games/{gid}/host/login", json={"password": "fresh-host"})
    assert tok.status_code == 200
    # logout
    ht = tok.json()["token"]
    assert c.post(f"/api/games/{gid}/host/logout", headers=H(ht)).status_code == 200
    assert not c.get(f"/api/games/{gid}", headers=H(ht)).json()["you_host"]


# ---------------------------------------------------------------- the host password is required
def test_create_needs_a_host_password_in_both_modes(tmp_path):
    """Dave 2026-11-15: every new game has a host password; it may equal the race password."""
    c = TestClient(create_app(tmp_path))
    play = {"humans": 2, "player": "Dave", "password": "racepw"}
    host = {"humans": 2, "player": "Admin", "host_only": True}
    for body in (play, play | {"host_password": ""}, play | {"host_password": None},
                 host, host | {"host_password": ""}, host | {"password": "racepw"}):
        r = c.post("/api/games", json=body)
        assert r.status_code == 400 and "host password" in r.json()["detail"], body
    assert c.post("/api/games", json=play | {"host_password": "abc"}).status_code == 400
    assert c.get("/api/games").json() == []                           # nothing was created
    # the same as the race password, or another one; host-only
    r = c.post("/api/games", json=play | {"host_password": "racepw"}).json()
    assert r["game"]["host_password"] and r["seat"] == 1
    assert c.post(f"/api/games/{r['id']}/host/login", json={"password": "racepw"}).status_code \
        == 200
    r = c.post("/api/games", json=play | {"host_password": "allmygames"}).json()
    assert c.post(f"/api/games/{r['id']}/host/login", json={"password": "racepw"}).status_code \
        == 403
    assert c.post(f"/api/games/{r['id']}/host/login",
                  json={"password": "allmygames"}).status_code == 200
    r = c.post("/api/games", json=host | {"host_password": "allmygames"}).json()
    assert r["host"] and r["game"]["host_only"] and r["game"]["host_password"]
    me = c.get(f"/api/games/{r['id']}", headers=H(r["token"])).json()
    assert me["you_host_login"] and not me["you_must_set_host_password"]


def test_existing_game_host_is_prompted_for_a_host_password(tmp_path):
    """A game saved before host passwords were required: on the host's next visit the summary
    says `you_must_set_host_password`, and every host power answers 403 set_host_password until
    the host sets one (the race itself plays on)."""
    c = TestClient(create_app(tmp_path))
    r = c.post("/api/games", json={"humans": 2, "player": "Dave", "password": "racepw",
                                   "host_password": "racepw", "seed": 5}).json()
    gid, t1 = r["id"], r["token"]
    t2 = join(c, gid, 2, "two2", player="Bob")
    p = tmp_path / "games" / gid / "meta.json"
    meta = json.loads(p.read_text())
    meta.pop("host_auth")
    p.write_text(json.dumps(meta))
    c = TestClient(create_app(tmp_path))                               # the restart loads it
    me = c.get(f"/api/games/{gid}", headers=H(t1)).json()
    assert me["you"] == 1 and me["you_host"] and me["you_must_set_host_password"]
    assert not me["host_password"] and not me["you_must_set_password"]
    other = c.get(f"/api/games/{gid}", headers=H(t2)).json()
    assert not other["you_must_set_host_password"]                    # only the host is asked
    assert c.get(f"/api/games/{gid}/view", headers=H(t1)).status_code == 200   # still plays
    for method, url, body in (("post", "force", None), ("get", "host/races", None),
                              ("post", "seats/2/reset-password", {"password": "temp2"}),
                              ("post", "seats/2/computer", None),
                              ("post", "settings", {"chatter": "off"})):
        r = getattr(c, method)(f"/api/games/{gid}/{url}", headers=H(t1),
                                **({"json": body} if body else {}))
        assert r.status_code == 403 and r.json()["detail"]["code"] == "set_host_password", url
    assert c.post(f"/api/games/{gid}/host/login", json={"password": "racepw"}).status_code == 409
    # Bob is not the host and can't set it
    assert c.post(f"/api/games/{gid}/host/password", headers=H(t2),
                  json={"new": "stolen"}).status_code == 403
    assert c.post(f"/api/games/{gid}/host/password", headers=H(t1),
                  json={"new": "abc"}).status_code == 400
    assert c.post(f"/api/games/{gid}/host/password", headers=H(t1),
                  json={"new": "allmygames"}).status_code == 200
    me = c.get(f"/api/games/{gid}", headers=H(t1)).json()
    assert me["host_password"] and not me["you_must_set_host_password"]
    assert c.post(f"/api/games/{gid}/force", headers=H(t1)).status_code == 200
    assert c.post(f"/api/games/{gid}/host/login", json={"password": "allmygames"}).status_code \
        == 200


# ---------------------------------------------------------------- View as
def test_view_as_is_exactly_that_race_and_read_only(tmp_path):
    app = create_app(tmp_path)
    c = TestClient(app)
    r = host_game(c, humans=2, seed=4)
    gid, ht = r["id"], r["token"]
    t1 = join(c, gid, 1, "one1", race="Ones")
    t2 = join(c, gid, 2, "two2", race="Twos", player="Q")
    c.put(f"/api/games/{gid}/orders", headers=H(t1), json={"text": "PT 2"})
    c.post(f"/api/games/{gid}/chat", headers=H(t1), json={"text": "hello all"})
    for _ in range(2):
        c.post(f"/api/games/{gid}/force", headers=H(ht))
    c.put(f"/api/games/{gid}/orders", headers=H(t1), json={"text": "PT 3"})
    g = app.state.games[gid]
    # a human race: the same view, draft, stats and chat as the race itself sees
    mine = c.get(f"/api/games/{gid}/view", headers=H(t1)).json()
    seen = c.get(f"/api/games/{gid}/as/1/view", headers=H(ht)).json()
    for k in ("empire", "systems", "ships", "fleets", "races", "results", "known_systems",
              "scans", "game"):
        assert seen[k] == mine[k], k
    assert seen["seat"]["view_as"] and not seen["seat"]["needs_orders"]
    assert c.get(f"/api/games/{gid}/as/1/orders", headers=H(ht)).json() == \
        c.get(f"/api/games/{gid}/orders", headers=H(t1)).json()
    assert c.get(f"/api/games/{gid}/as/1/stats", headers=H(ht)).json() == \
        c.get(f"/api/games/{gid}/stats", headers=H(t1)).json()
    assert c.get(f"/api/games/{gid}/as/1/chat", headers=H(ht)).json() == \
        c.get(f"/api/games/{gid}/chat", headers=H(t1)).json()
    old = c.get(f"/api/games/{gid}/as/2/view?turn=1", headers=H(ht)).json()
    assert old["empire"] == c.get(f"/api/games/{gid}/view?turn=1",
                                  headers=H(t2)).json()["empire"]
    # a computer race: the normal read model for that empire
    npr = next(e.id for e in g.state.empires.values() if e.kind == M.NPR)
    v = c.get(f"/api/games/{gid}/as/{npr}/view", headers=H(ht)).json()
    ref = build_view(g.state, g.results, npr)
    assert v["empire"] == json.loads(json.dumps(ref["empire"]))
    assert v["systems"] == json.loads(json.dumps(ref["systems"]))
    assert c.get(f"/api/games/{gid}/as/99/view", headers=H(ht)).status_code == 404
    # read-only: every write under /as/ is refused, and the host login has no race of its own
    for method, path, body in (("PUT", "orders", {"text": "PT 2"}), ("POST", "submit", None),
                               ("DELETE", "orders", None), ("POST", "chat", {"text": "x"}),
                               ("DELETE", "submit", None), ("POST", "leave", None)):
        r = c.request(method, f"/api/games/{gid}/as/1/{path}", headers=H(ht), json=body)
        assert r.status_code == 403, (method, path)
        r = c.request(method, f"/api/games/{gid}/{path}", headers=H(ht), json=body)
        assert r.status_code in (401, 403), (method, path)
    assert c.get(f"/api/games/{gid}/orders", headers=H(t1)).json()["orders"][0]["text"] == "PT 3"
    # non-hosts can't use it; nor can the host's race without the host login
    for tok in (t1, t2, None):
        assert c.get(f"/api/games/{gid}/as/2/view", headers=H(tok) if tok else {}) \
            .status_code == 403


def test_view_as_needs_the_host_login_not_the_host_race(tmp_path):
    c = TestClient(create_app(tmp_path))
    r = c.post("/api/games", json={"humans": 2, "player": "Dave", "password": "racepw", "host_password": "racepw"}).json()
    gid, t1 = r["id"], r["token"]
    assert c.get(f"/api/games/{gid}/as/2/view", headers=H(t1)).status_code == 403
    ht = c.post(f"/api/games/{gid}/host/login", json={"password": "racepw"}).json()["token"]
    assert c.get(f"/api/games/{gid}/as/2/view", headers=H(ht)).status_code == 200
    races = c.get(f"/api/games/{gid}/host/races", headers=H(ht)).json()["races"]
    assert len(races) == 8 and races[0]["human"] and not races[3]["human"]
    assert c.get(f"/api/games/{gid}/host/races").status_code == 401


def test_audit_log_and_export(tmp_path):
    c = TestClient(create_app(tmp_path))
    r = host_game(c, humans=2, seed=6)
    gid, ht = r["id"], r["token"]
    t1 = join(c, gid, 1, "one1")
    join(c, gid, 2, "two2", player="Q")
    c.get(f"/api/games/{gid}/as/1/view", headers=H(ht))
    c.get(f"/api/games/{gid}/as/1/view", headers=H(ht))          # deduplicated
    c.get(f"/api/games/{gid}/as/5/view", headers=H(ht))
    c.post(f"/api/games/{gid}/force", headers=H(ht))
    c.post(f"/api/games/{gid}/seats/2/reset-password", headers=H(ht), json={"password": "tmp1"})
    c.post(f"/api/games/{gid}/settings", headers=H(ht), json={"chatter": "off"})
    c.post(f"/api/games/{gid}/seats/2/computer", headers=H(ht))
    c.post(f"/api/games/{gid}/seats/7/human", headers=H(ht))
    z = zipfile.ZipFile(io.BytesIO(c.get(f"/api/games/{gid}/export", headers=H(ht)).content))
    lines = audit(tmp_path, gid)
    acts = [(x["action"], x.get("seat")) for x in lines]
    # the two unsubmitted human seats have AOMT on (the default, W-30): stand-in orders
    assert acts == [("create", None), ("view_as", 1), ("view_as", 5), ("aomt_orders", 1),
                    ("aomt_orders", 2), ("force_turn", None),
                    ("reset_password", 2), ("settings", None), ("to_computer", 2),
                    ("to_human", 7), ("export", None)]
    assert all(x["by"] == "host" for x in lines)
    zl = [json.loads(x) for x in z.read("host_audit.jsonl").decode().splitlines()]
    assert [x["action"] for x in zl] == [a for a, _ in acts]         # the export included
    man = json.loads(z.read("manifest.json"))
    assert [(x["eid"], x["to"]) for x in man["seat_changes"]] == [(2, "computer"), (7, "human")]
    # everyone sees a notice for the admin actions; View as is silent
    text = " ".join(m["text"] for m in c.get(f"/api/games/{gid}/chat", headers=H(t1))
                    .json()["messages"])
    assert "forced by the host" in text and "reset the password" in text
    assert "handed the" in text and "opened the" in text and "chatter" in text
    assert "view" not in text.lower()
    # the audit is not a static file
    assert c.get("/static/host_audit.jsonl").status_code == 404


# ---------------------------------------------------------------- computer -> human
def test_open_a_computer_empire_for_a_human(tmp_path):
    app = create_app(tmp_path)
    c = TestClient(app)
    r = c.post("/api/games", json={"humans": 1, "size": 8, "player": "Dave", "password": "racepw",
                                   "seed": 12, "host_password": "racepw"}).json()
    gid, t1 = r["id"], r["token"]
    for _ in range(2):
        c.post(f"/api/games/{gid}/force", headers=H(t1))
    g = app.state.games[gid]
    name5 = g.state.empires[5].name
    assert c.post(f"/api/games/{gid}/seats/1/human", headers=H(t1)).status_code == 404
    assert c.post(f"/api/games/{gid}/seats/5/human").status_code == 401
    r = c.post(f"/api/games/{gid}/seats/5/human", headers=H(t1)).json()
    s5 = next(s for s in r["game"]["seats"] if s["seat"] == 5)
    assert s5["open"] and not s5["computer"] and s5["race"] == name5
    assert r["game"]["open_seats"] == [5] and r["game"]["humans"] == 2
    assert g.state.empires[5].kind == M.HUMAN and 5 not in g.state.npr_state
    # the open seat blocks the automatic turn (W-08)
    assert not c.post(f"/api/games/{gid}/submit", headers=H(t1)).json()["turn_ran"]
    # a new player takes it with a password; the name stays (after turn 0)
    t5 = join(c, gid, 5, "five5", player="Eve", race="Renamed")
    assert g.state.empires[5].name == name5
    v = c.get(f"/api/games/{gid}/view", headers=H(t5)).json()
    assert v["empire"]["id"] == 5 and v["seat"]["needs_orders"]
    assert c.get(f"/api/games/{gid}").json()["waiting_for"] == [5]
    assert c.post(f"/api/games/{gid}/submit", headers=H(t5)).json()["turn_ran"]   # turn 3
    # it is ranked (as every race is, or every human under the older rule)
    assert g.state.empires[5].ranks and set(g.state.empires[5].ranks) >= {"VCT"}
    lines = [json.loads(x) for x in (tmp_path / "games" / gid / "standings.jsonl")
             .read_text().splitlines()]
    row = {ln["turn"]: next(e for e in ln["empires"] if e["id"] == 5) for ln in lines}
    assert not row[2]["human"] and row[3]["human"] and row[3]["converted_turn"] == 2
    # and back again: hand it to the computer, then reopen it
    assert c.post(f"/api/games/{gid}/seats/5/computer", headers=H(t1)).status_code == 200
    assert g.state.empires[5].kind == M.NPR and g.state.npr_state[5]["inbox"] is not None
    assert c.post(f"/api/games/{gid}/force", headers=H(t1)).status_code == 200   # bot plays
    orders = json.loads((tmp_path / "games" / gid / "turns" / "4" / "orders.json").read_text())
    assert orders["5"] and all(o["by"] == "computer" for o in orders["5"])
    assert c.post(f"/api/games/{gid}/seats/5/human", headers=H(t1)).status_code == 200
    t5b = join(c, gid, 5, "again5", player="Fay")
    assert c.get(f"/api/games/{gid}/view", headers=H(t5b)).json()["empire"]["id"] == 5
    assert c.get(f"/api/games/{gid}/view", headers=H(t5)).status_code == 401
    log = g.meta["seat_log"]
    assert [(x["eid"], x["to"]) for x in log] == [(5, "human"), (5, "computer"), (5, "human")]


def test_seat_one_handed_over_and_reopened(tmp_path):
    """A creation-time seat goes computer -> human again and can be joined."""
    c = TestClient(create_app(tmp_path))
    r = host_game(c, humans=2, seed=13)
    gid, ht = r["id"], r["token"]
    join(c, gid, 1, "one1")
    assert c.post(f"/api/games/{gid}/seats/1/computer", headers=H(ht)).status_code == 200
    g = c.get(f"/api/games/{gid}").json()
    assert g["seats"][0]["computer"] and g["open_seats"] == [2]
    assert c.post(f"/api/games/{gid}/seats/1/human", headers=H(ht)).status_code == 200
    g = c.get(f"/api/games/{gid}").json()
    assert not g["seats"][0]["computer"] and g["open_seats"] == [1, 2]
    join(c, gid, 1, "one2", player="New")


# ---------------------------------------------------------------- games only the host advances
def test_full_bot_game_never_advances_by_itself(tmp_path):
    c = TestClient(create_app(tmp_path))
    r = host_game(c, humans=0, seed=14)
    gid, ht = r["id"], r["token"]
    g = r["game"]
    assert g["humans"] == 0 and g["computers"] == 8 and g["host_runs"] and g["seats"] == []
    assert g["waiting_for"] == []
    for _ in range(3):
        assert c.get(f"/api/games/{gid}/version").json()["turn"] == 0
        c.get(f"/api/games/{gid}")
    # the host's run advances exactly one turn
    r = c.post(f"/api/games/{gid}/force", headers=H(ht)).json()
    assert r["turn"] == 1 and r["turns_run"] == 1
    assert c.get(f"/api/games/{gid}/version").json()["turn"] == 1
    chat = c.get(f"/api/games/{gid}/chat").json()["messages"]
    assert any(m["text"] == "Turn 1 has run." for m in chat)       # not "forced"
    # several at once: each committed and logged
    r = c.post(f"/api/games/{gid}/force", headers=H(ht), json={"turns": 3}).json()
    assert r["turn"] == 4 and r["turns_run"] == 3
    lines = (tmp_path / "games" / gid / "standings.jsonl").read_text().splitlines()
    assert [json.loads(x)["turn"] for x in lines] == [0, 1, 2, 3, 4]
    bot = [json.loads(x)["turn"] for x in (tmp_path / "games" / gid / "botlog.jsonl")
           .read_text().splitlines()]
    assert sorted(set(bot)) == [1, 2, 3, 4]
    for n in range(1, 5):
        assert (tmp_path / "games" / gid / "turns" / str(n) / "state.json").exists()
    assert c.post(f"/api/games/{gid}/force", headers=H(ht), json={"turns": 21}).status_code \
        == 422


def test_multi_run_stops_at_game_over(tmp_path):
    app = create_app(tmp_path)
    c = TestClient(app)
    r = c.post("/api/games", json={"humans": 1, "size": 8, "player": "D", "password": "racepw",
                                   "seed": 15, "host_password": "racepw"}).json()
    gid, t1 = r["id"], r["token"]
    # with a human giving orders, several turns at once is refused
    assert c.post(f"/api/games/{gid}/force", headers=H(t1), json={"turns": 2}).status_code == 400
    r = host_game(c, humans=0, seed=17)
    gid, ht = r["id"], r["token"]
    g = app.state.games[gid]
    orig = g.run

    def run_and_end(**kw):                     # computer empires can't win: end it by hand
        n = orig(**kw)
        if n == 2:
            g.state.winner = 3
        return n
    g.run = run_and_end
    r = c.post(f"/api/games/{gid}/force", headers=H(ht), json={"turns": 5}).json()
    assert r["turns_run"] == 2 and r["finished"] and r["turn"] == 2
    assert c.post(f"/api/games/{gid}/force", headers=H(ht)).status_code == 409


def test_converting_the_last_human_makes_it_host_advanced(tmp_path):
    c = TestClient(create_app(tmp_path))
    r = host_game(c, humans=1, seed=16)
    gid, ht = r["id"], r["token"]
    t1 = join(c, gid, 1, "one1")
    assert not c.get(f"/api/games/{gid}").json()["host_runs"]
    c.post(f"/api/games/{gid}/submit", headers=H(t1))                # turn 1 runs
    assert c.get(f"/api/games/{gid}/version").json()["turn"] == 1
    r = c.post(f"/api/games/{gid}/seats/1/computer", headers=H(ht)).json()
    assert not r["turn_ran"] and r["game"]["host_runs"] and r["game"]["waiting_for"] == []
    assert c.get(f"/api/games/{gid}/version").json()["turn"] == 1   # nothing ran by itself
    assert c.post(f"/api/games/{gid}/force", headers=H(ht)).json()["turn"] == 2
