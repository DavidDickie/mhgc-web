"""Computer empires offer technology trades to human players in private chat (Dave 2026-11-15,
DECISIONS A-08): who gets offers and from what knowledge, the rate limits and the chatter
setting, the Accept API, the engine honouring an offered swap, expiry and determinism."""
from __future__ import annotations

import copy
import json
import random

from fastapi.testclient import TestClient

from app.main import create_app
from mhgc import model as M
from mhgc.data.techs import TECHS, missing_prereqs
from mhgc.engine.turn import initial_results, run_turn
from mhgc.mapgen import new_game
from mhgc.npr import trade
from mhgc.npr.memory import PERSONAS, memory
from mhgc.orders import parse_orders
from mhgc.rng import Rng
from mhgc.view import view
from tests.conftest import contact, ctx_for, do, make_state, sysn
from tests.test_npr_units import _scramble


def _closure(t: int) -> set:
    """t and every prerequisite it needs, recursively."""
    out = {0}
    todo = [t]
    while todo:
        x = todo.pop()
        if x in out:
            continue
        out.add(x)
        todo.extend(missing_prereqs(set(), x))
    return out


def _play(seed=3, humans=("H", "J"), turns=40, level="normal", size=8, split=None):
    st = new_game("off", seed, list(humans), size=size)
    st.chatter = level
    initial_results(st)
    offers = []
    for t in range(turns):
        if split is not None and t == split:
            st = M.loads(M.dumps(st))
        if st.winner is not None:
            break
        res = run_turn(st, {})
        for m in res.chat:
            if m.get("kind") == "offer":
                offers.append(dict(m, turn=st.turn, kind_to=st.empires[m["to"]].kind,
                                   contact=m["to"] in st.empires[m["from"]].relations,
                                   stance=st.empires[m["from"]].relations.get(m["to"])))
    return st, offers


def _first_offer(seed=3, humans=("H", "J"), size=8):
    """Play until a computer empire makes an offer; return (state, the chat entry)."""
    st = new_game("off", seed, list(humans), size=size)
    initial_results(st)
    for _ in range(60):
        res = run_turn(st, {})
        for m in res.chat:
            if m.get("kind") == "offer":
                return st, m
    raise AssertionError("no offer in 60 turns")


# ---- who gets offers, how often ------------------------------------------------------------

def test_offers_go_only_to_contacted_human_races_within_the_limits():
    st, offers = _play(turns=60)
    assert len(offers) >= 4
    per_turn: dict = {}
    last_by_bot: dict = {}
    for o in offers:
        assert o["kind_to"] == M.HUMAN and st.empires[o["from"]].kind == M.NPR
        assert o["contact"] and o["stance"] not in ("W", "E")
        assert o["offer"]["until"] == o["turn"] + 1
        assert "Accept by this turn's end" in o["text"]
        assert TECHS[o["offer"]["give"]].name in o["text"]
        if o["offer"].get("any"):                      # "any 1000 EU technology" (G-23)
            assert o["offer"]["wants"] == []
            assert f"for any {o['offer']['any']} EU technology of yours" in o["text"]
        else:
            assert 1 <= len(o["offer"]["wants"]) <= trade.MAX_ALTS
            for w in o["offer"]["wants"]:
                assert TECHS[w].name in o["text"]
        per_turn.setdefault(o["turn"], []).append(o["to"])
        prev = last_by_bot.get(o["from"])
        if prev is not None:
            assert o["turn"] - prev >= trade.HUMAN_EVERY      # one open offer per bot, spaced
        last_by_bot[o["from"]] = o["turn"]
    for tos in per_turn.values():
        assert len(tos) <= trade.OFFERS_PER_TURN and len(set(tos)) == len(tos)


def test_chatter_off_means_no_offers_quiet_still_allows_them():
    _, quiet = _play(turns=40, level="quiet")
    _, off = _play(turns=40, level="off")
    assert quiet and not off


def test_no_offer_to_the_leader_a_race_at_war_or_one_not_contacted(monkeypatch):
    st, m = _first_offer()
    bot, hum = m["from"], m["to"]
    mem = copy.deepcopy(memory(st, bot))
    mem.pop("hoffers", None)
    mem["last_hoffer"] = -99
    mem["hoffer_log"] = []
    v = view(st, mem.get("inbox"), bot)
    from mhgc.npr.world import build
    w = build(v, copy.deepcopy(mem))
    assert trade.human_offer_terms(w, hum) is not None
    monkeypatch.setattr(trade, "leader", lambda w: hum)
    assert trade.human_offer_terms(w, hum) is None       # never feed the leader
    monkeypatch.undo()
    w.races[hum]["stance"] = "W"
    assert trade.human_offer_terms(w, hum) is None       # nor a race at war
    st2 = M.loads(M.dumps(st))
    del st2.empires[bot].relations[hum]                  # no contact: not in its view at all
    v2 = view(st2, mem.get("inbox"), bot)
    assert hum not in {r["id"] for r in v2["races"]}
    c = trade.human_offer_candidate(v2, mem, Rng(1, 1, "x"))
    assert c is None or c["to"] != hum


def test_known_technologies_are_named_and_unknown_ones_offered_as_any():
    st, m = _first_offer()
    bot, hum = m["from"], m["to"]
    mem = copy.deepcopy(memory(st, bot))
    mem.pop("hoffers", None)
    mem["last_hoffer"], mem["hoffer_log"] = -99, []
    v = view(st, mem.get("inbox"), bot)
    from mhgc.npr.world import build
    w = build(v, copy.deepcopy(mem))
    t = trade.human_offer_terms(w, hum)
    assert t and not t["known"] and t["any"]           # unknown: an ANY offer (G-23)
    assert all(TECHS[y].cost == t["any"] for y in t["wants"])
    text = trade.human_offer_text("BOTS", "builder", t, 9)
    assert text.startswith(f"The BOTS offer {TECHS[t['give']].name} for any {t['any']} EU "
                           f"technology of yours that we lack.")
    # the human once offered it a technology it wants (a TTNPR it saw): now it names that one
    y = t["wants"][-1]
    mem["htechs"] = {str(hum): {"has": [y], "t": st.turn}}
    w = build(v, copy.deepcopy(mem))
    t2 = trade.human_offer_terms(w, hum)
    assert t2["known"] and t2["wants"] == [y]
    assert trade.human_offer_text("BOTS", "builder", t2, 9).startswith(
        f"The BOTS offer {TECHS[t2['give']].name} for your {TECHS[y].name}.")
    # a complete SOT list with nothing it wants: no offer at all
    mem["htechs"] = {}
    mem.setdefault("spy", {})["techs"] = {str(hum): {"t": st.turn, "techs": [0]}}
    w = build(v, copy.deepcopy(mem))
    assert trade.human_offer_terms(w, hum) is None


def test_offers_use_only_what_the_bot_knows():
    st = new_game("fog", 5, ["Hum", "Two"], size=8)
    initial_results(st)
    checked = made = 0
    for t in range(1, 41):
        run_turn(st, {})
        if t % 2:
            continue
        for e in [e for e in st.empires.values() if e.kind == M.NPR]:
            a, b = M.loads(M.dumps(st)), M.loads(M.dumps(st))
            ma, mb = memory(a, e.id), memory(b, e.id)
            for m in (ma, mb):                           # as if no offer were open
                m.pop("hoffers", None)
                m["last_hoffer"] = -99
            _scramble(b, e.id, random.Random(e.id * 100 + t))
            for sh in b.ships.values():
                sh.x, sh.y = sh.x % b.board, sh.y % b.board
                sh.dx, sh.dy = sh.x, sh.y
            va, vb = view(a, ma.get("inbox"), e.id), view(b, mb.get("inbox"), e.id)
            ca = trade.human_offer_candidate(va, ma, Rng(1, t, "x"))
            cb = trade.human_offer_candidate(vb, mb, Rng(1, t, "x"))
            assert ca == cb
            assert json.dumps(ma, sort_keys=True) == json.dumps(mb, sort_keys=True)
            checked += 1
            made += ca is not None
    assert checked >= 100 and made >= 5


# ---- the engine honours an offered swap -----------------------------------------------------

def _offer_state(offered: bool):
    """Human 1 and computer empire 2.  The bot gives a 1000-EU technology for a 250-EU one: the
    engine's roll (DECISIONS C-07) would always refuse such a trade."""
    x = next(t for t, d in sorted(TECHS.items()) if d.cost == 1000 and trade.tradeable(t))
    y = next(t for t, d in sorted(TECHS.items()) if d.cost <= 250 and trade.tradeable(t)
             and t not in _closure(x))
    assert (100 * (2 * TECHS[y].cost - TECHS[x].cost)) // TECHS[x].cost < 0
    st = make_state(n_humans=1, npr=1)
    contact(st, 1, 2)
    hum, bot = st.empires[1], st.empires[2]
    bot.techs = _closure(x) - {y}
    hum.techs = (_closure(y) | (_closure(x) - {x})) - ({x} if x != 0 else set())
    hum.techs.discard(x)
    bot.techs.discard(y)
    assert not missing_prereqs(bot.techs, y) and not missing_prereqs(hum.techs, x)
    hum.eu = bot.eu = 5000
    for s in ("H1", "H2"):
        sysn(st, s).pop, sysn(st, s).infra = 10.0, 10
    mem = memory(st, 2)
    mem["persona"] = dict(PERSONAS["builder"], name="builder")
    initial_results(st)
    if offered:
        mem["hoffers"] = {"1": {"id": f"{st.turn}-2-1", "t": st.turn, "until": st.turn + 1,
                                "give": x, "wants": [y], "known": True}}
    return st, x, y


def _ttnpr(st, give, want):
    return parse_orders(f"TTNPR {give} {want} {st.empires[2].name}")


def test_an_offered_swap_is_always_accepted_and_both_techs_move():
    st, x, y = _offer_state(True)
    res = run_turn(st, {1: _ttnpr(st, y, x)})
    (o,) = [o for o in res.report(1).orders if o.code == "TTNPR"]
    assert o.ok and "accepts the trade they offered" in " ".join(o.messages)
    assert x in st.empires[1].techs and y in st.empires[2].techs
    # the bot saw it, and the closed offer is remembered as taken
    mem = memory(st, 2)
    assert not mem.get("hoffers")
    assert mem["hoffer_log"][-1]["taken"] is True
    assert y in mem["htechs"]["1"]["has"]


def test_the_same_swap_unsolicited_is_refused_as_before():
    for offered in (False, True):
        st, x, y = _offer_state(offered)
        st.turn += 1                                     # the turn the offer is for
        ctx = ctx_for(st)
        r = do(ctx, 1, f"TTNPR {y} {x} {st.empires[2].name}")
        assert r.ok, r.error
        if offered:
            assert x in st.empires[1].techs and y in st.empires[2].techs
        else:                                            # the roll refuses it, as always
            assert "better offers" in " ".join(r.messages)
            assert x not in st.empires[1].techs and y not in st.empires[2].techs


def test_only_the_exact_offered_swap_is_honoured():
    st, x, y = _offer_state(True)
    mem = memory(st, 2)
    assert trade.offer_open(mem, 1, y, x, st.turn + 1)
    assert not trade.offer_open(mem, 1, x, y, st.turn + 1)         # the other way round
    assert not trade.offer_open(mem, 3, y, x, st.turn + 1)         # another race
    assert not trade.offer_open(mem, 1, y, x, st.turn)             # before it was made
    assert not trade.offer_open(mem, 1, y, x, st.turn + 2)         # expired


def test_a_generated_offer_accepted_at_the_turn_trades_and_then_expires():
    st, m = _first_offer()
    bot, hum = m["from"], m["to"]
    off = memory(st, bot)["hoffers"][str(hum)]
    y, x = off["wants"][0], off["give"]
    h = st.empires[hum]
    h.techs |= _closure(y)                     # the human owns what it was asked for
    h.techs.discard(x)
    h.techs |= _closure(x) - {x}
    h.eu = max(h.eu, 3000)
    assert trade.offer_open(memory(st, bot), hum, y, x, st.turn + 1)
    side = f"ANY {off['any']}" if off.get("any") else str(y)
    res = run_turn(st, {hum: parse_orders(f"TTNPR {side} {x} {st.empires[bot].name}")})
    (o,) = [o for o in res.report(hum).orders if o.code == "TTNPR"]
    assert o.ok, o.error
    assert "the trade they offered" in " ".join(o.messages)
    assert x in st.empires[hum].techs and (set(off["wants"]) & st.empires[bot].techs)
    assert not memory(st, bot).get("hoffers")
    assert memory(st, bot)["hoffer_log"][-1]["taken"]


def test_an_offer_not_taken_expires_after_its_turn():
    st, m = _first_offer()
    bot, hum = m["from"], m["to"]
    mem = memory(st, bot)
    assert trade.open_human_offer(mem, st.turn + 1)
    wants = list(mem["hoffers"][str(hum)]["wants"])
    run_turn(st, {})
    mem = memory(st, bot)
    assert str(hum) not in (mem.get("hoffers") or {})
    log = mem["hoffer_log"][-1]
    assert log["to"] == hum and log["taken"] is False and log["closed"] == st.turn
    assert not trade.offer_open(mem, hum, wants[0], m["offer"]["give"], st.turn + 1)


def test_offers_are_deterministic_and_survive_save_load():
    _, a = _play(turns=36)
    _, b = _play(turns=36, split=18)
    assert a and a == b


# ---- the API: posted privately, Accept adds the order, recipient only -----------------------

def H(tok):
    return {"X-Seat-Token": tok}


def test_accept_api_adds_the_order_for_the_recipient_only(tmp_path):
    c = TestClient(create_app(tmp_path))
    r = c.post("/api/games", json={"password": "secret1", "humans": 2, "player": "Dave", "seed": 3,
                                   "host_password": "hostpw1"}).json()
    gid, t1 = r["id"], r["token"]
    t2 = c.post(f"/api/games/{gid}/join", json={"password": "secret2", "seat": 2,
                                                "player": "Bob"}).json()["token"]
    tok = {1: t1, 2: t2}
    offer = None
    for _ in range(40):
        assert c.post(f"/api/games/{gid}/force", headers=H(t1)).status_code == 200
        for s in (1, 2):
            for m in c.get(f"/api/games/{gid}/chat", headers=H(tok[s])).json()["messages"]:
                if m.get("offer") and m["to"] == s:
                    offer = m
        if offer:
            break
    assert offer, "no offer to a human seat"
    me, other = offer["to"], 3 - offer["to"]
    assert offer["bot"] and offer["from_name"] and offer["to_name"]
    # private: the other seat and spectators don't see it
    assert offer["id"] not in [m["id"] for m in c.get(f"/api/games/{gid}/chat",
                                                       headers=H(tok[other])).json()["messages"]]
    assert offer["id"] not in [m["id"] for m in c.get(f"/api/games/{gid}/chat").json()["messages"]]
    url = f"/api/games/{gid}/chat/{offer['id']}/accept"
    assert c.post(url, json={"alt": 0}, headers=H(tok[other])).status_code == 403
    assert c.post(url, json={"alt": 0}).status_code == 401
    # the host viewing as the recipient: read-only
    hl = c.post(f"/api/games/{gid}/host/login", json={"password": "hostpw1"}).json()
    htok = hl.get("token") or hl.get("host_token")
    assert c.post(f"/api/games/{gid}/as/{me}/chat/{offer['id']}/accept", json={"alt": 0},
                  headers=H(htok)).status_code == 403
    assert c.post(f"/api/games/{gid}/chat/999999/accept", headers=H(tok[me])).status_code == 404
    assert c.post(url, json={"alt": 9}, headers=H(tok[me])).status_code == 422
    # the recipient: the TTNPR goes into the draft, once
    r = c.post(url, json={"alt": 0}, headers=H(tok[me]))
    assert r.status_code == 200, r.text
    r = r.json()
    want, cost = offer["offer"]["give"], offer["offer"].get("any")
    if cost:                                          # an ANY offer (G-23): one Accept
        assert r["added"] and r["order"] == {
            "code": "TTNPR", "give_any_cost": cost, "want": want, "race": offer["from_name"],
            "text": f"TTNPR ANY {cost} {want} {offer['from_name']}"}
        assert c.post(url, json={"alt": 1}, headers=H(tok[me])).status_code == 422
    else:
        give = offer["offer"]["wants"][0]
        assert r["added"] and r["order"] == {"code": "TTNPR", "give": give, "want": want,
                                             "race": offer["from_name"],
                                             "text": f"TTNPR {give} {want} {offer['from_name']}"}
    r2 = c.post(url, json={"alt": 0}, headers=H(tok[me])).json()
    assert not r2["added"]
    rows = c.get(f"/api/games/{gid}/orders", headers=H(tok[me])).json()["orders"]
    assert [x for x in rows if x["code"] == "TTNPR"] == [r["order"]]
    if len(offer["offer"]["wants"]) > 1:            # another alternative replaces the first
        r3 = c.post(url, json={"alt": 1}, headers=H(tok[me])).json()
        tt = [x for x in r3["orders"] if x["code"] == "TTNPR"]
        assert len(tt) == 1 and tt[0]["give"] == offer["offer"]["wants"][1]
    # once its turn has run the offer has expired
    assert c.post(f"/api/games/{gid}/force", headers=H(t1)).status_code == 200
    assert c.post(url, json={"alt": 0}, headers=H(tok[me])).status_code == 409
