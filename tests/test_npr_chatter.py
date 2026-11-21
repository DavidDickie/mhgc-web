"""Computer empires name their systems and boast in the game-wide chat (Dave 2026-11-13,
DECISIONS W-14): renames through NSY, the boasts' information rules (own view and memory only,
nothing private), the rate limits and the per-game chatter setting, determinism, and the API.

Run with -s to see sample messages."""
from __future__ import annotations

import copy
import json
import random
import re

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from mhgc import model as M
from mhgc.data import constants as K
from mhgc.data.system_names import PERSONA_NAMES, RACE_NAMES
from mhgc.data.techs import TECHS
from mhgc.engine.turn import check_orders, initial_results, run_turn
from mhgc.mapgen import new_game
from mhgc.npr import chatter
from mhgc.npr.memory import memory
from mhgc.npr.naming import is_generated
from mhgc.npr.sim import simulate
from mhgc.orders import parse_orders
from mhgc.rng import Rng
from mhgc.view import view
from tests.test_npr_units import _scramble

ALL_NAMES = {n for v in RACE_NAMES.values() for n in v} | \
    {n for v in PERSONA_NAMES.values() for n in v}
_cache: dict = {}


def game(size=16, seed=4, turns=45, humans=1):
    key = (size, seed, turns, humans)
    if key not in _cache:
        _cache[key] = simulate(seed, humans, turns, "random", size=size)
    return _cache[key]


# ---------------------------------------------------------------- naming
def test_name_lists_are_valid_and_distinct():
    names = [n for v in RACE_NAMES.values() for n in v] + \
        [n for v in PERSONA_NAMES.values() for n in v]
    assert len(names) == len(set(names)) >= 400
    assert set(RACE_NAMES) == set(K.DEFAULT_RACE_NAMES)
    for n in names:
        assert len(n) <= K.NAME_MAX and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", n), n
        assert not is_generated(n)
        assert parse_orders(f"NSY A111 {n}")[0].name == n          # a valid NSY argument


@pytest.mark.parametrize("size", [8, 16])
def test_bots_rename_their_systems(size):
    s = game(size)
    st = s["state"]
    names = [x.name for x in st.systems]
    assert len(names) == len(set(names))                     # unique
    assert all(len(n) <= K.NAME_MAX for n in names)
    owned = [x for x in st.systems if x.owner and st.empires[x.owner].kind == "npr"]
    renamed = [x for x in owned if not is_generated(x.name)]
    assert len(renamed) >= 0.8 * len(owned)                  # most bot systems carry names
    # themed: every bot name is from its own race's list (or a variant of one)
    for x in renamed:
        race = st.empires[x.owner].name
        base = re.sub(r"_(II|III|IV|V|VI|VII|VIII|IX|X)$", "", x.name)
        assert base in RACE_NAMES[race] or re.fullmatch(r"[A-Za-z]+\d\d_\d+", x.name) or \
            base in ALL_NAMES, (race, x.name)
    # the NSY orders were all accepted, and at most 2 a bot a turn
    assert s["codes"]["NSY"] >= len(renamed) * 0.9
    assert not [k for k in s["rejections"] if k.startswith("NSY")]
    for eid, mem in st.npr_state.items():
        assert len(mem["names"]["used"]) == len(set(mem["names"]["used"]))
    # human systems are never touched by the bots
    for x in st.systems:
        if x.owner and st.empires[x.owner].kind == "human" and x.name in ALL_NAMES:
            raise AssertionError(x.name)


def test_renames_are_valid_nsy_orders_and_limited():
    st = new_game("nm", 6, ["Hum"], size=8)
    initial_results(st)
    for _ in range(25):
        st.turn += 1
        from mhgc.npr import npr_orders
        per = {}
        for e in [e for e in st.empires.values() if e.kind == "npr"]:
            orders = npr_orders(st, e.id)
            nsy = [o for o in orders if o.code == "NSY"]
            assert len(nsy) <= 2
            if nsy:
                assert orders[-len(nsy):] == nsy                   # renames go last
            res = check_orders(st, e.id, orders)
            for o, r in zip(orders, res):
                if o.code == "NSY":
                    assert r.ok, r.error
            per[e.id] = orders
        st.turn -= 1
        run_turn(st, per)
    named = [x for x in st.systems if x.owner and not is_generated(x.name)]
    assert named


def test_proper_home_names_are_kept():
    st = new_game("home", 8, ["Hum"], size=9)
    homes = {}
    for e in st.empires.values():
        if e.kind == "npr":
            h = st.system_at(e.home_x, e.home_y)
            h.name = f"Capital{e.id}"
            homes[e.id] = h.id
    initial_results(st)
    for _ in range(6):
        run_turn(st, {})
    for eid, sid in homes.items():
        if st.systems[sid].owner == eid:
            assert st.systems[sid].name == f"Capital{eid}"


def test_old_names_still_work_in_orders():
    """A player who knew a system by its generated name can still send ships there after the
    owner renamed it (the name in their map memory)."""
    st = new_game("old", 3, ["A", "B"])
    initial_results(st)
    a, b = st.empires[1], st.empires[2]
    target = next(s for s in st.systems if s.owner == 2)
    a.seen_systems[target.id] = {"turn": 0, "name": target.name, "owner": 2}
    old = target.name
    run_turn(st, {2: parse_orders(f"NSY {old} Renamed")})
    assert target.name == "Renamed"
    scout = next(s for s in st.live_ships() if s.owner == 1 and s.type == "S")
    r = check_orders(st, 1, parse_orders(f"MS {scout.number} {old}"))
    assert r[0].ok, r[0].error
    r = check_orders(st, 1, parse_orders(f"MS {scout.number} NoSuchPlace"))
    assert not r[0].ok
    _ = b


# ---------------------------------------------------------------- boasts: facts and limits
def _view_and_mem(stats=None, eu=100, vp=0, **emp):
    v = {"game": {"turn": 5, "board": 100}, "empire": {"id": 3, "name": "Spoonbots", "vp": vp,
         "techs": [0], "future_tech": 0, "stats": stats or {}, "ranks": {}, "eu": eu, **emp},
         "races": [{"id": 4, "name": "Groachi", "kind": "npr", "our_stance": "N"}],
         "results": {"events": [], "combats": []}, "systems": [], "known_systems": []}
    mem = {"persona": {"name": "aggressive"}, "races": {}}
    return v, mem


def test_settle_and_capture_boasts_name_the_race_in_caps():
    v, mem = _view_and_mem()
    v["results"]["events"] = [{"kind": "colonized", "system": 9, "data": {}},
                              {"kind": "system_captured", "system": 8, "data": {"race": 4}}]
    out = chatter.boasts(v, mem, Rng(1, 5, "t"))
    kinds = {c["kind"]: c["text"] for c in out}
    assert "SPOONBOTS" in kinds["settle"] and "GROACHI" in kinds["capture"]
    assert all(not re.search(r"\d", c["text"]) for c in out)
    # a loser we have no contact with isn't named; one from the rebels is "reclaimed"
    v, mem = _view_and_mem()
    v["results"]["events"] = [{"kind": "system_captured", "system": 8, "data": {"race": 9}}]
    (c1,) = chatter.boasts(v, mem, Rng(1, 5, "t"))
    assert c1["kind"] == "capture" and "SPOONBOTS" in c1["text"] and "9" not in c1["text"]
    v["game"]["turn"] = 9
    v["results"]["events"] = [{"kind": "system_captured", "system": 8, "data": {"race": 0}}]
    (c2,) = chatter.boasts(v, mem, Rng(1, 9, "t"))
    assert c2["kind"] == "capture" and "rebel" in c2["text"].lower()


def test_improvement_boasts_use_whole_percentages_only():
    v, mem = _view_and_mem({"HAP": 0.5, "POP": 20, "NNP": 100, "SYS": 6, "TEC": 8}, eu=400)
    chatter.boasts(v, mem, Rng(1, 5, "t"))                      # first turn: just remembers
    v["game"]["turn"] = 6
    v["empire"]["stats"] = {"HAP": 0.66, "POP": 21, "NNP": 104, "SYS": 6, "TEC": 8}
    v["empire"]["eu"] = 1234
    out = chatter.boasts(v, mem, Rng(1, 6, "t"))
    imp = [c for c in out if c["kind"] == "improve"]
    assert len(imp) == 1
    # EU went up 208% (400 -> 1234) but only the percentage could be said; the biggest gain wins
    assert "208% richer" in imp[0]["text"] and "1234" not in imp[0]["text"]
    # tiny bases and small gains say nothing
    v2, mem2 = _view_and_mem({"HAP": 0.1, "POP": 2, "NNP": 10, "SYS": 1, "TEC": 1}, eu=20)
    chatter.boasts(v2, mem2, Rng(1, 5, "t"))
    v2["game"]["turn"] = 6
    v2["empire"]["stats"] = {"HAP": 0.2, "POP": 4, "NNP": 20, "SYS": 2, "TEC": 2}
    v2["empire"]["eu"] = 60
    assert not [c for c in chatter.boasts(v2, mem2, Rng(1, 6, "t")) if c["kind"] == "improve"]
    # happiness: 0.5 -> 0.6 is "20% happier"
    v3, mem3 = _view_and_mem({"HAP": 0.5})
    chatter.boasts(v3, mem3, Rng(1, 5, "t"))
    v3["game"]["turn"] = 6
    v3["empire"]["stats"] = {"HAP": 0.6}
    t = [c["text"] for c in chatter.boasts(v3, mem3, Rng(1, 6, "t")) if c["kind"] == "improve"]
    assert t and "20%" in t[0] and "happier" in t[0]


def test_vp_tech_and_rank_boasts():
    v, mem = _view_and_mem(vp=20)
    chatter.boasts(v, mem, Rng(1, 5, "t"))
    v["game"]["turn"] = 6
    v["empire"].update(vp=52, techs=[0, 49, 3])
    out = {c["kind"]: c for c in chatter.boasts(v, mem, Rng(1, 6, "t"))}
    assert "50 victory points" in out["vp"]["text"] or "50" in out["vp"]["text"]
    assert TECHS[49].name in out["tech"]["text"]
    # 25 was passed too, but only the newest milestone is the boast picked (highest priority)
    best = chatter.select({3: list(out.values())}, "normal")
    assert best[0]["kind"] == "vp" and "50" in best[0]["text"]
    # no ranks yet: no number-1 boast.  Every race is ranked (DECISIONS A-06), so a computer
    # empire with rank 1 in a figure above zero boasts about it, from its own ranks only
    assert "rank" not in out
    v["game"]["turn"] = 7
    v["empire"]["ranks"] = {"HAP": 1, "POP": 3, "WAR": 1}
    v["empire"]["stats"] = {"HAP": 0.9, "POP": 20.0, "WAR": 0.0}   # first in WAR at 0: a tie
    out = {c["kind"]: c for c in chatter.boasts(v, mem, Rng(1, 7, "t"))}
    assert "happiness" in out["rank"]["text"]
    assert mem["brag"]["rank1"] == ["HAP"]
    v["game"]["turn"] = 8                                         # still number 1: said once
    assert "rank" not in {c["kind"] for c in chatter.boasts(v, mem, Rng(1, 8, "t"))}


def test_war_is_announced_only_once_the_enemy_knows():
    v, mem = _view_and_mem()
    chatter.boasts(v, mem, Rng(1, 5, "t"))
    v["game"]["turn"] = 6
    v["races"][0]["our_stance"] = "W"
    mem["races"] = {"4": {"war_since": 6, "ally_req": -1}}
    assert "war" not in {c["kind"] for c in chatter.boasts(v, mem, Rng(1, 6, "t"))}
    v["game"]["turn"] = 7
    v["results"]["combats"] = [{"participants": [3, 4], "ships": [], "troops": [], "lines": [],
                                "owner_before": None, "owner_after": None}]
    out = {c["kind"]: c for c in chatter.boasts(v, mem, Rng(1, 7, "t"))}
    assert "GROACHI" in out["war"]["text"]
    v["game"]["turn"] = 8
    assert "war" not in {c["kind"] for c in chatter.boasts(v, mem, Rng(1, 8, "t"))}
    v["game"]["turn"] = 9                                         # mutual EWA: peace
    v["results"]["combats"] = []
    v["races"][0]["our_stance"] = "N"
    out = {c["kind"]: c for c in chatter.boasts(v, mem, Rng(1, 9, "t"))}
    assert "GROACHI" in out["peace"]["text"]
    # an alliance is announced only when the other side had asked for one
    v["game"]["turn"] = 10
    v["races"][0]["our_stance"] = "A"
    assert "alliance" not in {c["kind"] for c in chatter.boasts(v, mem, Rng(1, 10, "t"))}
    v["races"][0]["our_stance"] = "N"
    chatter.boasts(v, mem, Rng(1, 11, "t"))
    v["races"][0]["our_stance"] = "A"
    mem["races"]["4"]["ally_req"] = 9
    out = {c["kind"]: c for c in chatter.boasts(v, mem, Rng(1, 12, "t"))}
    assert "GROACHI" in out["alliance"]["text"]


def test_select_limits_and_levels():
    def c(kind, pr, tie):
        return {"kind": kind, "priority": pr, "text": kind, "tie": tie}
    cands = {i: [c("settle", 30, 0.1 * i), c("improve", 20, 0.5)] for i in range(1, 9)}
    cands[3].append(c("capture", 90, 0.2))
    cands[5].append(c("tech", 60, 0.9))
    out = chatter.select(cands, "normal")
    assert len(out) == 4 and len({m["from"] for m in out}) == 4      # one per bot, 4 a turn
    assert [m["kind"] for m in out[:2]] == ["capture", "tech"]         # notable first
    q = chatter.select(cands, "quiet")
    assert [m["kind"] for m in q] == ["capture", "tech"]
    assert chatter.select(cands, "off") == []


def _messages(s):
    """The boasts (trade offers to human races are tested in test_npr_trade_offers)."""
    return [m for m in s["chat"] if m.get("kind") != "offer"]


@pytest.mark.parametrize("size", [8, 16])
def test_rate_limits_in_a_real_game(size):
    s = game(size)
    msgs = _messages(s)
    assert len(msgs) >= s["turns"]                       # plenty of chatter
    by_turn: dict = {}
    for m in msgs:
        by_turn.setdefault(m["turn"], []).append(m)
    for t, ms in by_turn.items():
        assert len(ms) <= 4
        assert len({m["from"] for m in ms}) == len(ms)    # one per bot per turn
    kinds = {m["kind"] for m in msgs}
    assert {"settle", "contact"} <= kinds and len(kinds) >= 5
    if "_printed" not in _cache:
        _cache["_printed"] = True
        st = s["state"]
        print("\nsample messages:")
        for m in msgs[::max(1, len(msgs) // 24)][:24]:
            print(f"  T{m['turn']:>2} {st.empires[m['from']].name:<14} [{m['kind']}] {m['text']}")


def test_chatter_levels_change_only_the_posting():
    a = new_game("lv", 12, ["H"], size=8)
    b = M.loads(M.dumps(a))
    c = M.loads(M.dumps(a))
    a.chatter, b.chatter, c.chatter = "normal", "quiet", "off"
    for st in (a, b, c):
        initial_results(st)
    counts = {"normal": [], "quiet": [], "off": []}
    offers = {"normal": [], "quiet": [], "off": []}
    for _ in range(25):
        for st in (a, b, c):
            chat = run_turn(st, {}).chat
            counts[st.chatter].append([m for m in chat if m["kind"] != "offer"])
            offers[st.chatter] += [m for m in chat if m["kind"] == "offer"]
    assert sum(map(len, counts["normal"])) > sum(map(len, counts["quiet"])) >= 0
    assert all(len(x) <= 2 and all(chatter.PRIORITY.get(m["kind"], 0) >= 60 for m in x)
               for x in counts["quiet"])
    assert not any(counts["off"]) and not offers["off"]
    # trade offers aren't boasts: quiet makes the same ones as normal (DECISIONS A-08)
    assert offers["quiet"] == offers["normal"]

    # the bots play the same game whatever the boast setting.  ("off" also stops trade offers,
    # and a bot holds back money for an open offer, so it is compared with the others only when
    # no offer was made.)
    def strip(st):
        d = M.to_dict(st)
        d.pop("chatter")
        for m in d["npr_state"].values():
            m.pop("brag", None)
        return d
    assert strip(a) == strip(b)
    if not offers["normal"]:
        assert strip(a) == strip(c)


def test_deterministic_and_survives_save_load():
    def play(split):
        st = new_game("det", 21, ["H"], size=9)
        initial_results(st)
        out = []
        for t in range(24):
            if split and t == 12:
                st = M.loads(M.dumps(st))
            out.append(run_turn(st, {}).chat)
        return out, [x.name for x in st.systems]
    assert play(False) == play(True)


# ---------------------------------------------------------------- no hidden information
NUM_OK = re.compile(r"\b(25|50|75) victory points|\b\d+%|\b[Nn]umber 1\b")   # own rank (A-06)


def _numbers_left(text, st):
    t = text
    for e in st.empires.values():
        t = t.replace(chatter.caps(e.name), "")
    for tech in TECHS.values():
        t = t.replace(tech.name, "")
    t = NUM_OK.sub("", t)
    return re.findall(r"\d+", t)


@pytest.mark.parametrize("size,seed", [(16, 21), (8, 5)])
def test_boasts_depend_only_on_what_the_empire_can_see(size, seed):
    st = new_game("fog", seed, ["Hum"], size=size)
    initial_results(st)
    checked = 0
    for t in range(1, 31):
        res = run_turn(st, {1: []})
        if t % 3:
            continue
        for e in [e for e in st.empires.values() if e.kind == "npr"][:6]:
            a, b = M.loads(M.dumps(st)), M.loads(M.dumps(st))
            ma, mb = memory(a, e.id), memory(b, e.id)
            ma["brag"] = copy.deepcopy(ma.get("brag"))
            _scramble(b, e.id, random.Random(e.id * 100 + t))
            for sh in b.ships.values():
                sh.x, sh.y = sh.x % b.board, sh.y % b.board
                sh.dx, sh.dy = sh.x, sh.y
            # the stored inbox is the empire's own report: what view() shows it
            va = view(a, ma.get("inbox"), e.id)
            vb = view(b, mb.get("inbox"), e.id)
            ca = chatter.boasts(va, ma, Rng(1, t, "x"))
            cb = chatter.boasts(vb, mb, Rng(1, t, "x"))
            assert ca == cb
            assert json.dumps(ma.get("brag"), sort_keys=True) == \
                json.dumps(mb.get("brag"), sort_keys=True)
            checked += 1
        _ = res
    assert checked >= 30


@pytest.mark.parametrize("size", [8, 16])
def test_no_coordinates_or_private_numbers(size):
    s = game(size)
    st = s["state"]
    for m in _messages(s):
        assert not re.search(r"\d+\s*,\s*\d+", m["text"]), m       # no x,y
        assert not _numbers_left(m["text"], st), m                  # only VP milestones and %
        assert not re.search(r"\b(fleet|ships?|warships?)\b.*\d", m["text"], re.I), m


# ---------------------------------------------------------------- the API
def H(tok):
    return {"X-Seat-Token": tok}


def test_api_posts_bot_messages_to_chat(tmp_path):
    c = TestClient(create_app(tmp_path))
    r = c.post("/api/games", json={"password": "secret1", "humans": 2, "player": "Dave", "seed": 7,
                                   "host_password": "secret1"}).json()
    gid, t1 = r["id"], r["token"]
    assert r["game"]["chatter"] == "normal"
    t2 = c.post(f"/api/games/{gid}/join", json={"password": "secret2", "seat": 2, "player": "Bob"}).json()["token"]
    for _ in range(12):
        assert c.post(f"/api/games/{gid}/force", headers=H(t1)).status_code == 200
    msgs = c.get(f"/api/games/{gid}/chat").json()["messages"]     # spectators see them too
    bots = [m for m in msgs if m.get("bot")]
    assert bots and all(not m["system"] and m["to"] is None and m["from"] > 2 for m in bots)
    names = {e["race"] for e in c.get(f"/api/games/{gid}").json()["seats"]}
    for m in bots:
        assert m["from_name"] and m["from_name"] not in names
        assert chatter.caps(m["from_name"]) in m["text"]
    per_turn: dict = {}
    for m in bots:
        per_turn[m["turn"]] = per_turn.get(m["turn"], 0) + 1
    assert max(per_turn.values()) <= 4
    # they are in the turn results on disk too, and survive a restart
    res = json.loads((tmp_path / "games" / gid / "turns" / "3" / "results.json").read_text())
    assert "chat" in res
    c2 = TestClient(create_app(tmp_path))
    assert [m for m in c2.get(f"/api/games/{gid}/chat").json()["messages"] if m.get("bot")] == bots
    # the host turns chatter off: no more boasts; only the host may
    assert c2.post(f"/api/games/{gid}/settings", json={"chatter": "off"},
                   headers=H(t2)).status_code == 403
    g = c2.post(f"/api/games/{gid}/settings", json={"chatter": "off"}, headers=H(t1)).json()
    assert g["chatter"] == "off"
    assert c2.post(f"/api/games/{gid}/settings", json={"chatter": "loud"},
                   headers=H(t1)).status_code == 422
    last = c2.get(f"/api/games/{gid}/chat").json()["last"]
    for _ in range(4):
        c2.post(f"/api/games/{gid}/force", headers=H(t1))
    new = c2.get(f"/api/games/{gid}/chat?since={last}").json()["messages"]
    assert new and not [m for m in new if m.get("bot")]
    # the setting can be chosen at creation
    r = c2.post("/api/games", json={"password": "secret1", "humans": 1, "player": "D", "chatter": "quiet",
                                     "host_password": "secret1"}).json()
    assert r["game"]["chatter"] == "quiet"
