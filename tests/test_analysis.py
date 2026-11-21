"""The analysis features (Dave 2026-11-14; DECISIONS A-05, W-15..W-17): the bot decision log,
the all-race standings log, the end-of-game standings view, the analysis export and its
permissions, non-leakage while a game runs, and tools/analyze_game.py."""
from __future__ import annotations

import contextlib
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from mhgc import model as M
from mhgc.data import constants as K
from mhgc.engine.turn import run_turn
from mhgc.mapgen import new_game
from mhgc.npr.trace import REASONS, Tracer
from mhgc.orders import parse_line


def H(tok):
    return {"X-Seat-Token": tok}


def new(c, humans=1, size=8, seed=11):
    r = c.post("/api/games", json={"password": "secret1", "humans": humans, "size": size, "player": "Dave",
                                   "race": "Daves", "seed": seed, "host_password": "secret1"})
    assert r.status_code == 200, r.text
    return r.json()["id"], r.json()["token"]


def jsonl(p):
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


# ---------------------------------------------------------------- the bot decision log
def test_tracer_changes_nothing_and_is_deterministic():
    a = new_game("t", 21, ["Dave"], size=8)
    b = M.from_dict(M.to_dict(a))
    c = M.from_dict(M.to_dict(a))
    logs_b, logs_c = [], []
    for _ in range(14):
        run_turn(a, {})                                     # the default bot, no log
        tb, tc = Tracer(), Tracer()
        logs_b.append(tb.finish(b, run_turn(b, {}, npr_fn=tb)))
        logs_c.append(tc.finish(c, run_turn(c, {}, npr_fn=tc)))
    assert M.dumps(a) == M.dumps(b) == M.dumps(c)           # same game, same bot memory
    assert json.dumps(logs_b, sort_keys=True) == json.dumps(logs_c, sort_keys=True)
    rec = logs_b[-1][0]
    assert set(rec) >= {"turn", "empire", "race", "persona", "saw", "strategy", "orders",
                        "decisions", "rejected", "after"}
    assert rec["turn"] == 14 and rec["empire"] == 2
    assert {"systems", "pop", "eu", "contacts", "threatened", "enemy_seen", "races"} <= \
        set(rec["saw"])
    assert {"mode", "persona", "budget", "missions", "at_war"} <= set(rec["strategy"])
    nprs = [e.id for e in a.empires.values() if e.kind == M.NPR]
    assert [r["empire"] for r in logs_b[-1]] == nprs        # one record per computer empire
    every = [o for t in logs_b for r in t for o in r["orders"]]
    assert every and all(o["rc"] and o["area"] and o["ok"] is not None for o in every)
    assert all("." in o["rc"] for o in every)
    assert not [o for o in every if o["rc"].endswith(".other")]   # every note has a code
    assert set(REASONS.values()) & {o["rc"] for o in every}
    # decisions: research picks at least, with their scores
    decs = [d for t in logs_b for r in t for d in r["decisions"]]
    assert any(d["ev"] == "research_choice" and "value" in d for d in decs)
    # the orders logged are exactly the orders run, in order
    tb = Tracer()
    st = M.from_dict(M.to_dict(b))
    res = run_turn(st, {}, npr_fn=tb)
    for r in tb.finish(st, res):
        ran = res.reports[r["empire"]].orders
        assert [o["code"] for o in r["orders"]] == [x.code for x in ran]


def test_rejected_orders_are_logged_with_the_reason():
    st = new_game("t", 5, ["Dave"], size=8)
    run_turn(st, {})

    class Bad(Tracer):
        def __call__(self, state, eid):
            orders = super().__call__(state, eid)
            if eid == 2:
                orders.append(parse_line("BI Nowhere_At_All 1"))
                self.records[eid]["orders"].append({"i": len(orders) - 1, "code": "BI",
                                                    "text": "BI Nowhere_At_All 1",
                                                    "area": "test", "rc": "test.bad",
                                                    "note": ""})
            return orders

    tr = Bad()
    recs = {r["empire"]: r for r in tr.finish(st, run_turn(st, {}, npr_fn=tr))}
    bad = recs[2]["orders"][-1]
    assert bad["ok"] is False and bad["error"] and recs[2]["rejected"] >= 1


# ---------------------------------------------------------------- logs written by the server
@pytest.fixture
def solo(tmp_path):
    c = TestClient(create_app(tmp_path))
    gid, tok = new(c)
    return c, gid, tok, tmp_path / "games" / gid


def test_logs_written_each_turn_and_standings_match_engine_stats(solo):
    c, gid, tok, d = solo
    # AOMT off (on by default, W-30): the forced turns give the human no orders
    c.post(f"/api/games/{gid}/aomt", json={"on": False}, headers=H(tok))
    home = next(s["name"] for s in c.get(f"/api/games/{gid}/view", headers=H(tok)).json()
                ["systems"])
    c.post(f"/api/games/{gid}/submit", headers=H(tok), json={"text": f"BI {home} 1\nPT 2"})
    for _ in range(5):
        assert c.post(f"/api/games/{gid}/force", headers=H(tok)).status_code == 200
    rows = jsonl(d / "standings.jsonl")
    assert [r["turn"] for r in rows] == list(range(0, 7))
    for r in rows:
        st = M.loads((d / "turns" / str(r["turn"]) / "state.json").read_text())
        for x in r["empires"]:
            e = st.empires[x["id"]]
            assert x["stats"] == {k: e.stats.get(k, 0.0) for k in K.STAT_NAMES}
            assert (x["vp"], x["eu"], x["iu_depot"], x["name"]) == (e.vp, e.eu, e.iu_depot,
                                                                     e.name)
            assert x["systems"] == sum(1 for s in st.systems if s.owner == e.id)
            assert x["systems"] == int(e.stats["SYS"]) and x["warships"] == int(e.stats["WAR"])
            assert x["troops"] == int(e.stats["CTS"])
            assert x["human"] == (x["id"] == 1)
        assert len(r["empires"]) == 8
    # the human's orders: in orders.json with their results, and their spending estimated
    o1 = json.loads((d / "turns" / "1" / "orders.json").read_text())
    assert [x["code"] for x in o1["1"]] == ["BI", "PT"] and o1["1"][0]["by"] == "human"
    assert all(x["ok"] is not None for k in o1 for x in o1[k])
    sp = rows[1]["empires"][0]["spend"]
    assert sp["infrastructure"] == {"eu": 0, "iu": 10} and sp["techs"]["eu"] > 0
    bot = jsonl(d / "botlog.jsonl")
    assert sorted({(b["turn"]) for b in bot}) == list(range(1, 7))
    assert len(bot) == 6 * 7                                  # 7 computer empires a turn
    assert all(b["orders"] == [] or "rc" in b["orders"][0] for b in bot)


# ---------------------------------------------------------------- visibility while the game runs
def _all_reads(c, gid, tok):
    out = []
    for path in ("", "/view", "/stats", "/turns", "/orders", "/chat", "/version"):
        r = c.get(f"/api/games/{gid}{path}", headers=H(tok))
        out.append((path, r.status_code, r.text))
    out.append(("/view?turn=1", 0, c.get(f"/api/games/{gid}/view?turn=1", headers=H(tok)).text))
    out.append(("games", 0, c.get("/api/games").text))
    return out


def test_logs_never_reach_players_during_a_game(tmp_path):
    c = TestClient(create_app(tmp_path))
    gid, t1 = new(c, humans=2)
    t2 = c.post(f"/api/games/{gid}/join", json={"password": "secret2", "seat": 2, "player": "Bob"}).json()["token"]
    for _ in range(3):
        c.post(f"/api/games/{gid}/force", headers=H(t1))
    d = tmp_path / "games" / gid
    before = {t: _all_reads(c, gid, t) for t in (t1, t2)}
    # scramble every figure in the logs: nothing a player can read changes
    for name in ("standings.jsonl", "botlog.jsonl"):
        p = d / name
        p.write_text(p.read_text().replace("1", "7").replace("2", "9"))
    after = {t: _all_reads(c, gid, t) for t in (t1, t2)}
    strip = lambda rows: [(p, s, t if p != "/version" else "") for p, s, t in rows]  # noqa: E731
    assert strip(before[t1]) == strip(after[t1]) and strip(before[t2]) == strip(after[t2])
    # each player's stats endpoint carries only their own report's figures
    st = json.loads(c.get(f"/api/games/{gid}/stats", headers=H(t1)).text)
    assert "standings" not in json.dumps(st) and "botlog" not in json.dumps(st)
    # the end-of-game views are closed
    for tok in (t1, t2, None):
        hdr = H(tok) if tok else {}
        assert c.get(f"/api/games/{gid}/final", headers=hdr).status_code == 409
    # the host may export at any time (Dave 2026-11-15, W-17); nobody else before the end
    assert c.get(f"/api/games/{gid}/export", headers=H(t1)).status_code == 200   # the host
    assert c.get(f"/api/games/{gid}/export", headers=H(t2)).status_code == 403
    assert c.get(f"/api/games/{gid}/export").status_code == 401
    assert "only the host" in c.get(f"/api/games/{gid}/export",
                                    headers=H(t2)).json()["detail"]
    # the files are not reachable as static files either
    for name in ("standings.jsonl", "botlog.jsonl"):
        assert c.get(f"/static/{name}").status_code == 404
        assert c.get(f"/static/../saves/games/{gid}/{name}").status_code == 404


# ---------------------------------------------------------------- the export and the final view
def test_export_permissions(tmp_path, monkeypatch):
    c = TestClient(create_app(tmp_path))
    gid, tok = new(c)                                        # one human: the host may export
    c.post(f"/api/games/{gid}/force", headers=H(tok))
    assert c.get(f"/api/games/{gid}/export", headers=H(tok)).status_code == 200
    assert c.get(f"/api/games/{gid}/export").status_code == 401
    assert c.get(f"/api/games/{gid}/export", headers=H("nope")).status_code == 401
    assert c.get(f"/api/games/{gid}/final").status_code == 409

    gid2, h1 = new(c, humans=2, seed=3)          # two humans: the host any time, others at the end
    h2 = c.post(f"/api/games/{gid2}/join", json={"password": "secret2", "seat": 2, "player": "Bo"}).json()["token"]
    c.post(f"/api/games/{gid2}/force", headers=H(h1))
    assert c.get(f"/api/games/{gid2}/export", headers=H(h1)).status_code == 200
    assert c.get(f"/api/games/{gid2}/export", headers=H(h2)).status_code == 403
    monkeypatch.setattr(K, "VICTORY_POINTS", 1)              # someone wins next turn
    c.post(f"/api/games/{gid2}/force", headers=H(h1))
    assert c.get(f"/api/games/{gid2}").json()["finished"]
    for tok_ in (h1, h2):
        r = c.get(f"/api/games/{gid2}/export", headers=H(tok_))
        assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert c.get(f"/api/games/{gid2}/export").status_code == 401   # still needs a seat
    for hdr in (H(h1), H(h2), {}):                           # the final view: anyone
        assert c.get(f"/api/games/{gid2}/final", headers=hdr).status_code == 200


def test_export_contents_and_final_view(tmp_path, monkeypatch):
    c = TestClient(create_app(tmp_path))
    gid, tok = new(c)
    c.post(f"/api/games/{gid}/aomt", json={"on": False}, headers=H(tok))   # W-30: on by default
    home = next(s["name"] for s in c.get(f"/api/games/{gid}/view", headers=H(tok)).json()
                ["systems"])
    for n in range(4):
        r = c.post(f"/api/games/{gid}/submit", headers=H(tok),
                   json={"text": f"BI {home} 1" if n % 2 == 0 else "PT 2"})
        assert r.json()["turn_ran"]
    monkeypatch.setattr(K, "VICTORY_POINTS", 1)
    c.post(f"/api/games/{gid}/force", headers=H(tok))
    z = zipfile.ZipFile(io.BytesIO(c.get(f"/api/games/{gid}/export", headers=H(tok)).content))
    names = set(z.namelist())
    assert {"manifest.json", "standings.jsonl", "botlog.jsonl", "final_state.json"} <= names
    for n in range(0, 6):
        assert f"turns/{n:04d}/results.json" in names and f"turns/{n:04d}/orders.json" in names
    man = json.loads(z.read("manifest.json"))
    assert man["format"] == "mhgc-analysis-1" and man["reason"] == "game over"
    assert man["game"]["seed"] == 11 and man["game"]["size"] == 8 and man["game"]["humans"] == 1
    assert len(man["empires"]) == 8 and man["empires"][0]["human"]
    assert all(e["persona"] for e in man["empires"][1:])
    o = json.loads(z.read("turns/0001/orders.json"))
    assert o["1"][0]["text"] == f"BI {home} 1" and o["1"][0]["by"] == "human"
    assert len(o) == 8 and all(x["by"] == "computer" for k in o if k != "1" for x in o[k])
    assert len(z.read("standings.jsonl").decode().splitlines()) == 6
    assert len(z.read("botlog.jsonl").decode().splitlines()) == 5 * 7

    f = c.get(f"/api/games/{gid}/final", headers=H(tok)).json()
    # with 1 VP to win everyone reaches it; computer empires can win too (DECISIONS A-06), so
    # the NNP tie-break decides who
    assert f["turns"] == list(range(0, 6)) and f["winner"] == man["game"]["winner"] \
        and f["winner"] is not None and f["viewer"] == 1
    assert len(f["empires"]) == 8 and f["empires"][0]["relation"] == "own"
    assert {e["relation"] for e in f["empires"][1:]} <= {"stranger", "neutral", "ally", "war"}
    rows = jsonl(tmp_path / "games" / gid / "standings.jsonl")
    for key in ("vp", "systems", "pop", "nnp", "techs", "warships"):
        for e in f["empires"]:
            want = [next(x for x in r["empires"] if x["id"] == e["id"])[key] for r in rows]
            assert f["series"][key][str(e["id"])] == want
    assert [x["rank"] for x in f["final"]] == list(range(1, 9))
    assert f["final"][0]["id"] == f["winner"]                # the winner first
    anon = c.get(f"/api/games/{gid}/final").json()
    assert anon["viewer"] is None and {e["relation"] for e in anon["empires"]} == {"none"}


def test_old_games_without_logs_are_rebuilt(solo):
    c, gid, tok, d = solo
    for _ in range(3):
        c.post(f"/api/games/{gid}/force", headers=H(tok))
    want = jsonl(d / "standings.jsonl")
    (d / "standings.jsonl").unlink()
    (d / "turns" / "2" / "orders.json").unlink()
    z = zipfile.ZipFile(io.BytesIO(c.get(f"/api/games/{gid}/export", headers=H(tok)).content))
    got = [json.loads(x) for x in z.read("standings.jsonl").decode().splitlines()]
    assert [g["turn"] for g in got] == [0, 1, 2, 3] and all(g.get("rebuilt") for g in got)
    for a, b in zip(want, got):
        assert [x["stats"] for x in a["empires"]] == [x["stats"] for x in b["empires"]]
    o2 = json.loads(z.read("turns/0002/orders.json"))        # from the results instead
    assert o2 and all("code" in x and "ok" in x for k in o2 for x in o2[k])


# ---------------------------------------------------------------- tools/analyze_game.py
def test_analyze_game_on_a_generated_game(tmp_path):
    from tools import analyze_game, sample_game
    out = tmp_path / "g.zip"
    r = sample_game.play(out, turns=12, size=8, seed=4, save_dir=str(tmp_path / "s"),
                         quiet=True)
    assert r["turn"] == 12 and out.exists()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert analyze_game.main([str(out), "--every", "4"]) == 0
    text = buf.getvalue()
    for section in ("== Overview", "== Systems by turn", "== NNP", "== Human vs computer",
                    "== Spending mix", "== Order mix", "== Wars and captures", "== Milestones",
                    "top decision reasons"):
        assert section in text, section
    assert "Scripties" in text and "human" in text and "bot/" in text
    assert "T0" in text and "T12" in text
    data = analyze_game.load(out)
    assert len(data["standings"]) == 13 and data["botlog"]
    total, rej, codes, groups, errs = analyze_game.order_stats(data, 1)
    assert total > 0 and rej <= total
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert analyze_game.main([str(out), "--race", "Scripties"]) == 0
    assert "Groachi" not in buf.getvalue().split("== Systems by turn")[1].split("==")[0]
