"""TTNPR "ANY <cost>" (Dave 2026-11-19, DECISIONS G-23): either side of a tech trade with a
computer empire may be any technology of exactly that list price.  The computer empire picks at
turn run with its own valuation (what it gives: the one it values least of those the player
lacks and can use; what it takes: the player's one it values most of those it lacks and can
use); Check orders picks nothing and so reveals nothing of its technologies."""
from __future__ import annotations

import pytest

from mhgc.data.techs import TECHS
from mhgc.engine.turn import check_orders, run_turn
from mhgc.model import from_dict, to_dict
from mhgc.npr import trade
from mhgc.npr.memory import PERSONAS, memory
from mhgc.orders import OrderSyntaxError, any_costs, order_from_dict, parse_line, parse_orders
from tests.conftest import contact, ctx_for, do, make_state


def err(r):
    assert not r.ok, r.messages
    return r.error


def ok(r):
    assert r.ok, r.error
    return r


def _state():
    """R1 human, R3 computer (builder), in contact, 1000 EU each."""
    st = make_state()
    contact(st, 1, 3)
    mem = memory(st, 3)
    mem["persona"] = dict(PERSONAS["builder"], name="builder")
    return st


# ---- syntax -------------------------------------------------------------------------------

@pytest.mark.parametrize("line, give, gc, want, wc", [
    ("TTNPR ANY 1000 ANY 1000 Groachi", None, 1000, None, 1000),
    ("TTNPR 16 ANY 1000 Groachi", 16, None, None, 1000),
    ("TTNPR ANY 500 10 Groachi", None, 500, 10, None),
    ("TTNPR ANY:500 10 Groachi", None, 500, 10, None),
    ("TTNPR any:250 any 250 Groachi", None, 250, None, 250),
    ("TTNPR 8 3 Groachi", 8, None, 3, None),
])
def test_parse_all_forms(line, give, gc, want, wc):
    o = parse_line(line)
    assert (o.give, o.give_any_cost, o.want, o.want_any_cost, o.race) == \
        (give, gc, want, wc, "Groachi")
    again = parse_line(o.to_text())                       # canonical text: "ANY 1000"
    assert again == o and order_from_dict(o.to_dict()) == o
    assert ":" not in o.to_text()


def test_json_forms_and_a_race_called_any():
    o = order_from_dict({"code": "TTNPR", "give_any_cost": 1000, "want": 33, "race": "R3"})
    assert o.to_text() == "TTNPR ANY 1000 33 R3"
    assert o.to_dict() == {"code": "TTNPR", "give_any_cost": 1000, "want": 33, "race": "R3"}
    assert order_from_dict({"code": "TTNPR", "give": "ANY:1000", "want": "any 500",
                            "race": "R3"}).to_text() == "TTNPR ANY 1000 ANY 500 R3"
    assert parse_line("TTNPR 3 5 Any").race == "Any"     # the race is always the last token


@pytest.mark.parametrize("line, msg", [
    ("TTNPR ANY 999 3 R3", "No technology costs exactly 999 EU"),
    ("TTNPR 3 ANY:8000 R3", "No technology costs exactly 8000 EU"),   # only Future Tech
    ("TTNPR ANY 3 R3", "Wrong number of arguments"),
    ("TTNPR ANY R3 3 R3", "ANY needs a cost"),
    ("TTNPR ANY:x 3 R3", "must be a whole number"),
    ("TTNPR 3 R3", "Wrong number of arguments"),
])
def test_bad_forms(line, msg):
    with pytest.raises(OrderSyntaxError, match=msg):
        parse_line(line)


def test_cost_validation_and_the_costs_that_exist():
    assert any_costs() == [100, 250, 500, 1000, 2000, 3000, 4000]
    with pytest.raises(OrderSyntaxError, match="either a tech number or ANY"):
        order_from_dict({"code": "TTNPR", "give": 3, "give_any_cost": 100, "want": 5,
                         "race": "R3"})
    with pytest.raises(OrderSyntaxError, match="Missing want"):
        order_from_dict({"code": "TTNPR", "give": 3, "race": "R3"})
    with pytest.raises(OrderSyntaxError, match="costs exactly 300"):
        order_from_dict({"code": "TTNPR", "give": 3, "want_any_cost": 300, "race": "R3"})


# ---- the picks ----------------------------------------------------------------------------

def test_any_want_picks_the_npr_tech_it_values_least_that_the_player_lacks_and_can_use():
    st = _state()
    me, npr = st.empires[1], st.empires[3]
    me.techs |= {0, 3, 6, 4, 7, 17}   # 250 EU techs it can use: 9 (needs 6), 10 (4), 14 (3)
    npr.techs |= {0, 1, 3, 4, 6, 7, 9, 10, 13, 14, 16, 2}
    me.techs.add(13)                  # it has 13 already; 16 needs 2, which it lacks
    eligible = [9, 10, 14]
    mem = memory(st, 3)
    expect = trade.any_pick(mem, npr.techs, st.turn, eligible, most=False)
    scores = {t: trade.tech_score(trade._Valuer(mem, npr.techs, st.turn), t, False)
              for t in eligible}
    assert scores[expect] == min(scores.values())
    ctx = ctx_for(st)
    r = ok(do(ctx, 1, "TTNPR 17 ANY 250 R3"))
    assert me.techs & set(eligible) == {expect} and 17 in npr.techs
    assert r.messages[0].startswith(f"The R3 accept: you gave Solar Collectors (250) and "
                                    f"received {TECHS[expect].name} (250). [100 / ")
    # deterministic: the same state picks the same tech again
    st2 = _state()
    st2.empires[1].techs = set(me.techs - {expect})
    st2.empires[3].techs = set(npr.techs - {17})
    ok(do(ctx_for(st2), 1, "TTNPR 17 ANY 250 R3"))
    assert expect in st2.empires[1].techs


def test_any_give_picks_the_players_tech_the_npr_values_most_that_it_lacks_and_can_use():
    st = _state()
    me, npr = st.empires[1], st.empires[3]
    me.techs |= {0, 1, 2, 3, 4, 8, 11, 13, 14, 16}       # 250s: 8, 11, 13, 14, 16
    npr.techs |= {0, 1, 2, 4, 11, 15}                    # has 11; lacks 3, so 14 is no use
    eligible = [8, 13, 16]
    expect = trade.any_pick(memory(st, 3), npr.techs, st.turn, eligible, most=True)
    ctx = ctx_for(st)
    r = ok(do(ctx, 1, "TTNPR ANY 250 15 R3"))
    assert set(npr.techs) & {8, 13, 14, 16} == {expect} and 15 in me.techs
    assert f"you gave {TECHS[expect].name} (250) and received Improved Weapons I (250)" \
        in r.messages[0]


def test_both_any():
    st = _state()
    me, npr = st.empires[1], st.empires[3]
    me.techs |= {0, 1, 2}
    npr.techs |= {0, 3, 4, 5}
    r = ok(do(ctx_for(st), 1, "TTNPR ANY 100 ANY 100 R3"))
    assert len(npr.techs & {1, 2}) == 1 and len(me.techs & {3, 4, 5}) == 1
    assert r.messages[0].startswith("The R3 accept: you gave ")
    # ledger: each side paid half the list price of what it gave
    assert me.eu == 1000 - 50 and npr.eu == 1000 - 50


def test_ledger_half_costs_for_uneven_any_trade():
    st = _state()
    me, npr = st.empires[1], st.empires[3]
    me.techs |= {0, 1, 8}                               # gives 8 (250)
    npr.techs |= {0, 1, 3}                              # gives 3 (100)
    ctx = ctx_for(st)
    ok(do(ctx, 1, "TTNPR ANY 250 ANY 100 R3"))          # acceptance 400%: always
    assert me.eu == 1000 - 125 and npr.eu == 1000 - 50
    assert ctx.gift_out_eu[1] == 125 and ctx.gift_out_eu[3] == 50


def test_no_eligible_tech_fails_clearly_without_using_the_attempt():
    st = _state()
    me, npr = st.empires[1], st.empires[3]
    me.techs |= {0, 1, 3}
    npr.techs |= {0, 1, 2}
    ctx = ctx_for(st)
    assert err(do(ctx, 1, "TTNPR 3 ANY 1000 R3")) == \
        "The R3 have no 1000 EU tech you lack and could use."
    npr.techs.add(16)                                  # 250, but it needs 2, which R1 lacks
    assert err(do(ctx, 1, "TTNPR 3 ANY 250 R3")) == \
        "The R3 have no 250 EU tech you lack and could use."
    assert 1 not in ctx.npr_trade_done                 # failed checks, not refusals (G-17)
    # a corrected order still goes through this turn
    r = ok(do(ctx, 1, "TTNPR 3 ANY 100 R3"))
    assert 2 in me.techs and 3 in npr.techs and "received Extended Home Computing" in r.messages[0]


def test_give_any_fails_when_the_npr_lacks_nothing_of_yours():
    st = _state()
    me, npr = st.empires[1], st.empires[3]
    me.techs |= {0, 1, 2, 8}
    npr.techs |= {0, 3, 8}
    ctx = ctx_for(st)
    assert err(do(ctx, 1, "TTNPR ANY 250 3 R3")) == \
        "You have no 250 EU tech the R3 lack and could use."
    assert err(do(ctx, 1, "TTNPR ANY 500 3 R3")) == "You own no 500 EU tech to offer."
    assert 1 not in ctx.npr_trade_done


def test_one_tech_a_turn_applies():
    st = _state()
    me, npr = st.empires[1], st.empires[3]
    me.techs |= {0, 1, 2}
    npr.techs |= {0, 3, 4}
    ctx = ctx_for(st)
    ok(do(ctx, 1, "PT 5"))
    e = err(do(ctx, 1, "TTNPR ANY 100 ANY 100 R3"))
    assert "you bought Planetary Defenses (PT) earlier this turn" in e
    assert 1 not in ctx.npr_trade_done
    st = _state()
    me, npr = st.empires[1], st.empires[3]
    me.techs |= {0, 1, 2}
    npr.techs |= {0, 3, 4}
    ctx = ctx_for(st)
    ok(do(ctx, 1, "TTNPR ANY 100 ANY 100 R3"))
    got = next(t for t in (3, 4) if t in me.techs)
    e = err(do(ctx, 1, "PT 5"))
    assert f"you traded with the R3 for {TECHS[got].name} (TTNPR) earlier this turn" in e
    assert "one attempt a turn" in err(do(ctx, 1, "TTNPR ANY 100 ANY 100 R3"))


def test_ledger_reconciles_for_an_any_trade():
    from tests.test_ledger import SPENDING_ORDERS
    assert "TTNPR ANY" in SPENDING_ORDERS


# ---- Check orders: nothing leaks ----------------------------------------------------------

def _check_lines(st, line):
    (r,) = check_orders(st, 1, parse_orders(line))
    return r.ok, r.error, list(r.messages)


def test_check_says_the_npr_picks_at_turn_run_and_reveals_nothing():
    a = _state()
    a.empires[1].techs |= {0, 1, 2, 8}
    a.empires[3].techs |= {0, 3, 4, 5, 9, 6}
    b = from_dict(to_dict(a))
    b.empires[3].techs = {0, 7}                         # nothing the player could get
    for line in ("TTNPR 8 ANY 250 R3", "TTNPR ANY 100 ANY 100 R3", "TTNPR ANY 250 ANY 250 R3"):
        ra, rb = _check_lines(a, line), _check_lines(b, line)
        assert ra == rb, line
        assert ra[0], ra
        text = " ".join(ra[2])
        assert "When the turn runs, the R3 will pick" in text
        assert "without using this turn's attempt" in text
        for t in a.empires[3].techs - {0}:
            assert TECHS[t].name not in text
    assert _check_lines(a, "TTNPR 8 ANY 250 R3")[2][-1] == "Acceptance chance about 100%."
    assert _check_lines(a, "TTNPR ANY 250 ANY 1000 R3")[2][-1] == "Acceptance chance about 0%."
    ok_, e, _ = _check_lines(a, "TTNPR ANY 500 ANY 250 R3")
    assert not ok_ and e == "You own no 500 EU tech to offer."
    a.empires[1].eu = 10
    ok_, e, _ = _check_lines(a, "TTNPR 8 ANY 250 R3")
    assert not ok_ and "your half of the trade is 125" in e
    del a.empires[1].relations[3]                       # contact still needed
    assert not _check_lines(a, "TTNPR 8 ANY 250 R3")[0]


def test_check_any_against_war():
    st = _state()
    st.empires[1].techs |= {0, 1}
    st.empires[3].relations[1] = "W"
    st.empires[1].relations[3] = "W"
    ok_, e, _ = _check_lines(st, "TTNPR 1 ANY 100 R3")
    assert not ok_ and "war" in e


# ---- bot offers: "any 250 EU technology of yours" ----------------------------------------

def _any_offer_state():
    """The bot (R3) offers 33 Core Mining (1000) for any 250 EU tech of the human's (R1): the
    roll alone would always refuse that."""
    st = _state()
    me, npr = st.empires[1], st.empires[3]
    npr.techs |= {0, 5, 12, 24, 33, 1}
    me.techs |= {0, 5, 12, 24, 3, 14, 2, 16}                 # 250s it lacks: 14, 16
    me.eu = npr.eu = 5000
    mem = memory(st, 3)
    mem["hoffers"] = {"1": {"id": f"{st.turn}-3-1", "t": st.turn, "until": st.turn + 1,
                            "give": 33, "wants": [16], "known": False, "any": 250}}
    return st


def test_bot_any_offer_is_honoured_and_prefers_what_it_said_it_would_take():
    st = _any_offer_state()
    (c,) = check_orders(st, 1, parse_orders("TTNPR ANY 250 33 R3"))
    assert c.ok and c.messages[-1] == "The R3 offered this trade, so they will accept."
    res = run_turn(st, {1: parse_orders("TTNPR ANY 250 33 R3")})
    (o,) = [o for o in res.report(1).orders if o.code == "TTNPR"]
    assert o.ok, o.error
    assert o.messages == ["The R3 accept the trade they offered you: you gave Improved "
                          "Electronics I (250) and received Core Mining (1000)."]
    assert 33 in st.empires[1].techs and 16 in st.empires[3].techs
    assert 14 not in st.empires[3].techs
    mem = memory(st, 3)
    assert mem["hoffer_log"][-1]["taken"] is True and 16 in mem["htechs"]["1"]["has"]


def test_bot_any_offer_text_and_chat_payload():
    t = {"give": 33, "wants": [16, 14], "known": False, "any": 250}
    assert trade.human_offer_text("BOTS", "builder", t, 9).startswith(
        "The BOTS offer Core Mining for any 250 EU technology of yours that we lack. Accept by "
        "this turn's end (turn 9).")
    mem: dict = {}
    rec = trade.record_human_offer(mem, 3, 8, {"to": 1, "terms": t})
    assert rec["any"] == 250 and rec["wants"] == [16, 14]


def test_accept_api_for_an_any_offer(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    c = TestClient(create_app(tmp_path))
    r = c.post("/api/games", json={"password": "secret1", "humans": 1, "player": "Dave",
                                   "seed": 3, "host_password": "hostpw1"}).json()
    gid, tok = r["id"], r["token"]
    H = {"X-Seat-Token": tok}
    offer = None
    for _ in range(40):
        assert c.post(f"/api/games/{gid}/force", headers=H).status_code == 200
        offer = next((m for m in c.get(f"/api/games/{gid}/chat", headers=H).json()["messages"]
                      if m.get("offer") and m["offer"].get("any")), None)
        if offer:
            break
    assert offer, "no ANY offer"
    assert offer["offer"]["wants"] == []
    url = f"/api/games/{gid}/chat/{offer['id']}/accept"
    r = c.post(url, json={"alt": 0}, headers=H).json()
    cost, want = offer["offer"]["any"], offer["offer"]["give"]
    assert r["added"] and r["order"]["text"] == f"TTNPR ANY {cost} {want} {offer['from_name']}"
    assert not c.post(url, json={"alt": 0}, headers=H).json()["added"]
    assert c.post(url, json={"alt": 1}, headers=H).status_code == 422
    rows = c.get(f"/api/games/{gid}/orders", headers=H).json()["orders"]
    assert [x["text"] for x in rows if x["code"] == "TTNPR"] == [r["order"]["text"]]
