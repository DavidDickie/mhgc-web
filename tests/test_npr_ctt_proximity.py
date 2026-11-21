"""Computer empires and trade routes (CTT, DECISIONS A-11) and the proximity war (A-12).
Dave 2026-11-20."""
from __future__ import annotations

from mhgc.engine.turn import run_turn
from mhgc.npr import ctt, diplo, econ, memory, trade
from mhgc.npr.plan import Plan
from mhgc.npr.world import build
from mhgc.rng import Rng
from mhgc.view import view
from tests.conftest import add_ship, contact, make_state, sysn

NPR_ID = 3          # make_state(): 1, 2 humans, 3 the NPR, home H3 at (30, 30); rel. (50, 50)
H1_REL = (30, 30)   # H1 (10, 10) in the NPR's relative coordinates


def _results(st, eid, ships=(), events=()):
    return {"turn": st.turn, "reports": {str(eid): {
        "combats": [], "events": list(events), "messages": [],
        "scans": {"ships": [dict(number=n, owner=o, owner_name=f"R{o}", type=t, x=x, y=y, ox=x,
                                 oy=y, level="long", moved=True, **({"fleet": f} if f else {}))
                            for n, o, t, x, y, f in ships]}}},
            "combats": []}


def _w(st, results=None, intel=None):
    mem = memory(st, NPR_ID)
    if intel:
        mem["intel"].update(intel)
    return build(view(st, results, NPR_ID), mem)


def _codes(plan):
    return [o.code for o in plan.orders]


def _rich_h1(st, turn=None):
    """Our short-scan intel of R1's home: a big, built-up world."""
    h1 = sysn(st, "H1")
    return {str(h1.id): {"t": st.turn if turn is None else turn, "owner": 1, "pop": 10.0,
                         "hab": 3, "mr": False, "ar": False, "starport": 3, "status": "Norm",
                         "infra": 10, "routes": [], "weapons": [], "artifacts": 0,
                         "troops": []}}


# ================================================================= trade routes (A-11)

def test_route_value_matches_the_engines_trade_income():
    """The bot's estimate of a route is the engine's 25% of the system's EU production (rules:
    319-327), and the bot converts a transport that has arrived: the trade EU then comes in."""
    st = make_state()
    contact(st, 1, NPR_ID)
    st.empires[NPR_ID].techs |= {11, 21}
    h1 = sysn(st, "H1")
    h1.pop, h1.infra, h1.starport = 10.0, 10, 3           # as the intel below saw it
    t = add_ship(st, NPR_ID, "T", h1.x, h1.y)
    mem = memory(st, NPR_ID)
    mem["intel"].update(_rich_h1(st))             # what an earlier short scan showed
    mem["traders"] = {str(t.number): h1.id}       # the transport sent there, now arrived
    res = run_turn(st, {})                        # the bot: CTT on arrival
    rep = res.report(NPR_ID)
    assert any(o.code == "CTT" and o.ok for o in rep.orders), [(o.text, o.error)
                                                               for o in rep.orders if not o.ok]
    assert NPR_ID in h1.trade_routes and t.number not in st.ships
    assert any(e.kind == "trade_route" for e in rep.events)
    res = run_turn(st, {})
    eu_h1 = res.report(1).economy["systems"][h1.id]["eu"]
    got = res.report(NPR_ID).economy["trade_eu"]
    assert got == int(eu_h1 * 0.25 + 0.5) and got > 0
    w = _w(st, results=None)
    w.known[h1.id].intel = mem["intel"][str(h1.id)]
    # the estimate (from population, IF and starport, a third to EU) is in the right range; it
    # can't see the owner's happiness, governor or split
    assert 0.6 * got <= ctt.route_value(w, w.known[h1.id]) <= 1.5 * got, got
    assert mem["routes"][str(h1.id)]["ok"] is True          # remembered from the event


def test_builds_a_trade_transport_for_a_worthwhile_route_only():
    st = make_state()
    contact(st, 1, NPR_ID)
    st.empires[NPR_ID].techs |= {11, 21}
    w = _w(st, intel=_rich_h1(st))
    h1 = sysn(st, "H1")
    v = ctt.route_value(w, w.known[h1.id])
    assert 9 < v < 12                         # 10 pop x 5 x 2 (IF) x 1.3 (SP3) / 3 x 25%
    plan = Plan(w)
    ctt.build(w, plan, set())
    assert any(o.code == "BS" and o.type == "T" for o in plan.orders)
    assert "a transport for a trade route" in plan.orders[0].line
    assert w.mem["ctt_build"]
    # without the technology, at war with the owner, or a route of ours there already: nothing
    for setup in ("notech", "war", "route", "tiny"):
        st2 = make_state()
        contact(st2, 1, NPR_ID, "W" if setup == "war" else "N")
        if setup != "notech":
            st2.empires[NPR_ID].techs |= {11, 21}
        intel = _rich_h1(st2)
        if setup == "tiny":
            intel[str(sysn(st2, "H1").id)].update(pop=1.0, infra=0, starport=0)
        w2 = _w(st2, intel=intel)
        if setup == "route":
            w2.mem["routes"] = {str(sysn(st2, "H1").id): {"t": 1, "ok": True, "owner": 1}}
        p2 = Plan(w2)
        ctt.build(w2, p2, set())
        assert not p2.orders, setup


def test_sends_an_idle_transport_and_shares_the_cap():
    st = make_state()
    contact(st, 1, NPR_ID)
    st.empires[NPR_ID].techs |= {11, 21}
    h3 = sysn(st, "H3")
    add_ship(st, NPR_ID, "T", h3.x, h3.y)
    w = _w(st, intel=_rich_h1(st))
    plan = Plan(w)
    ctt.move(w, plan, False, set())                # no colony targets left: idle ones trade
    ms = [o for o in plan.orders if o.code == "MS"]
    assert ms and ms[0].system == "H1" and w.mem["traders"]
    # three other races' routes there already: the 50% cap shares it out (2 / 4 of 25%)
    h1 = sysn(st, "H1")
    one = ctt.route_value(w, w.known[h1.id])
    w.known[h1.id].intel = dict(w.known[h1.id].intel, routes=["A", "B", "C"])
    assert abs(ctt.route_value(w, w.known[h1.id]) - one * 0.5) < 1e-9


def test_decentralized_trading_is_worth_more_with_routes_to_set_up():
    st = make_state()
    contact(st, 1, NPR_ID)
    st.empires[NPR_ID].techs |= {11}
    bare = econ.tech_score(_w(st), 21, False)
    st2 = make_state()
    contact(st2, 1, NPR_ID)
    st2.empires[NPR_ID].techs |= {11}
    rich = econ.tech_score(_w(st2, intel=_rich_h1(st2)), 21, False)
    assert rich > bare + 8


# ================================================================= proximity war (A-12)

def _near(st, dx, typ="D", owner=1, fleet=None, number=901):
    return [(number, owner, typ, 50 + dx, 50, fleet)]


def test_war_on_warships_within_one_move():
    st = make_state()
    contact(st, 1, NPR_ID)
    w = _w(st, results=_results(st, NPR_ID, _near(st, 4)))      # a Destroyer moves 4
    plan = Plan(w)
    diplo.plan(w, plan, Rng(1, 1, "t"))
    dw = [(o, r) for o, r in zip(plan.orders, plan.reasons) if o.code == "DW"]
    assert dw and dw[0][1]["rc"] == "diplo.war_proximity"
    assert any(o.code == "MESSAGE" for o in plan.orders)
    assert w.at_war(1)
    # out of reach (6 squares), an unarmed ship, or a slow fleet: no war
    for ships in (_near(st, 6), _near(st, 3, "T"), _near(st, 4, "D", fleet="F1") +
                  [(902, 1, "PA", 50 + 4, 50, "F1")]):      # the fleet moves at 2 (Patroller)
        st2 = make_state()
        contact(st2, 1, NPR_ID)
        w2 = _w(st2, results=_results(st2, NPR_ID, ships))
        p2 = Plan(w2)
        diplo.plan(w2, p2, Rng(1, 1, "t"))
        assert "DW" not in _codes(p2), ships


def test_no_proximity_war_on_allies_at_war_or_at_their_own_world():
    for rel in ("A", "W"):
        st = make_state()
        contact(st, 1, NPR_ID)
        st.empires[NPR_ID].relations[1] = rel
        w = _w(st, results=_results(st, NPR_ID, _near(st, 2)))
        p = Plan(w)
        diplo.plan(w, p, Rng(1, 1, "t"))
        assert "DW" not in _codes(p), rel                    # already at war: a no-op
    # their warship at their own world, which happens to be within one move of ours
    st = make_state()
    contact(st, 1, NPR_ID)
    h1 = sysn(st, "H1")
    h1.x, h1.y = 33, 30                                      # rel (53, 50)
    st.empires[NPR_ID].seen_systems[h1.id] = {"turn": 5, "name": "H1", "owner": 1}
    w = _w(st, results=_results(st, NPR_ID, _near(st, 3)))
    p = Plan(w)
    diplo.plan(w, p, Rng(1, 1, "t"))
    assert "DW" not in _codes(p)


def test_no_peace_while_their_warships_are_within_one_move():
    st = make_state()
    contact(st, 1, NPR_ID, "W")
    mem = memory(st, NPR_ID)
    r = mem["races"].setdefault("1", {"griev": 0.0, "good": 0.0, "met": 0, "warned": -1,
                                      "intrude": 0, "peace_req": -1, "ally_req": -1,
                                      "war_since": -1, "last_fight": -1, "peace_offer": -1,
                                      "why": []})
    r.update(war_since=st.turn - 20, last_fight=st.turn - 20, peace_req=st.turn)   # asked
    w = _w(st, results=_results(st, NPR_ID, _near(st, 3)))
    p = Plan(w)
    diplo.plan(w, p, Rng(1, 1, "t"))
    assert "EWA" not in _codes(p) and "DW" not in _codes(p)
    # they have gone: the normal peace logic offers peace again
    w = _w(st, results=_results(st, NPR_ID, _near(st, 9)))
    p = Plan(w)
    diplo.plan(w, p, Rng(1, 1, "t"))
    assert "EWA" in _codes(p) and 1 in w.making_peace
    # while making peace our own warships keep out of their reach
    assert 1 in diplo.races_near(w, H1_REL[0] + 3, H1_REL[1], 4)


def test_a_turn_of_grace_after_a_peace():
    st = make_state()
    contact(st, 1, NPR_ID)
    mem = memory(st, NPR_ID)
    w0 = _w(st)
    from mhgc.npr.memory import race
    race(mem, 1, st.turn)["peace_t"] = st.turn
    w = _w(st, results=_results(st, NPR_ID, _near(st, 3)))
    p = Plan(w)
    diplo.plan(w, p, Rng(1, 1, "t"))
    assert "DW" not in _codes(p)
    race(mem, 1, st.turn)["peace_t"] = st.turn - 3
    w = _w(st, results=_results(st, NPR_ID, _near(st, 3)))
    p = Plan(w)
    diplo.plan(w, p, Rng(1, 1, "t"))
    assert "DW" in _codes(p)
    assert w0 is not None


def test_own_warships_avoid_a_neutrals_reach():
    st = make_state()
    contact(st, 1, NPR_ID)
    w = _w(st)
    x, y = H1_REL
    assert diplo.races_near(w, x + 4, y, 4) == {1}
    assert diplo.races_near(w, x + 5, y, 4) == set()
    assert diplo.races_near(w, 50, 50, 8) == set()            # our own system is safe ground
    # a straight run past H1 stops within one move of it; a run elsewhere doesn't
    assert diplo.path_provokes(w, 4, x + 12, y + 2, x - 12, y + 2) == {1}
    assert diplo.path_provokes(w, 4, 50, 50, 50, 70) == set()
    assert diplo.path_provokes(w, 4, x + 12, y + 2, x - 12, y + 2, exclude={1}) == set()
    # a warship of ours left near H1 goes back to base
    from mhgc.npr import war
    sh = add_ship(st, NPR_ID, "D", 13, 10, order="INTERCEPT")   # rel (33, 30): 3 from H1,
    # chasing a ship it no longer sees
    w = _w(st)
    p = Plan(w)
    war.defend(w, p, war.threats(w))
    assert any(o.code == "MS" and getattr(o, "ship", None) == sh.number for o in p.orders)
    assert any(r["rc"] == "defend.leave_neutral" for r in p.reasons)


def test_no_trade_offer_to_a_race_whose_warships_are_within_one_move():
    st = make_state()
    contact(st, 1, NPR_ID)
    w = _w(st, results=_results(st, NPR_ID, _near(st, 6)))
    assert trade._good_partner(w, 1, "player")
    w = _w(st, results=_results(st, NPR_ID, [(901, 1, "LC", 56, 50, None)]))   # LC moves 6
    assert not trade._good_partner(w, 1, "player")
