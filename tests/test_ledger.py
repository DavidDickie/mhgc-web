"""The maintenance ledger shows every EU and IU an order spends or gets back (Dave 2026-11-12).

For each spending order: the order-related ledger lines equal the change the order makes to the
empire's EU stockpile and its systems' IU stockpiles, and the ledger reconciles
(initial + every line = final) for both the EU stockpile and the IU supply depot.
"""
import pytest

from mhgc.engine.turn import run_turn
from mhgc.model import Fleet, from_dict, to_dict
from mhgc.orders import parse_orders
from tests.conftest import add_ship, add_troop, contact, ctx_for, do, make_state, sysn

ORDER_KINDS = {"purchases", "salvage", "gifts_out", "gifts_in"}
TOTALS = {"initial", "final"}


def scenario():
    st = make_state()                     # R1, R2 human; R3 computer
    e1 = st.empires[1]
    e1.techs |= {1, 2, 8, 14, 21, 32, 33, 50}
    st.empires[3].techs |= {1, 3}
    h1 = sysn(st, "H1")
    h1.infra = 5
    h1.artifacts |= {"FP", "WT"}
    col = sysn(st, "E2")
    col.owner, col.pop, col.happy, col.iu = 1, 2.0, 0.5, 100
    col.artifacts |= {"FP", "WT"}
    contact(st, 1, 2)
    contact(st, 1, 3)
    add_ship(st, 1, "F", h1.x, h1.y, number=501)
    add_ship(st, 1, "F", h1.x, h1.y, number=502, fleet=1)
    st.fleets[1] = Fleet(1, 1, "Wing", h1.x, h1.y, dx=h1.x, dy=h1.y)
    add_troop(st, 1, "S", system=h1.id, number=601)
    return st


SPENDING_ORDERS = {
    "BS": ["BS H1 F"],
    "BS count": ["BS H1 F 2"],
    "BS count, partial": ["BS H1 T 3"],          # class 2 starport: builds 2 (G-19)
    "BCU count": ["BCU H1 S 3"],
    "BCU": ["BCU H1 S"],
    "BT": ["BT H1 CM"],
    "BT S": ["BT H1 S"],
    "BSP": ["BSP H1"],
    "BI": ["BI H1 2"],
    "DI": ["DI H1 2"],
    "DSP": ["DSP H1"],
    "CI": ["CI H1 3"],
    "TP A/I": ["TP H1 I 40 E2"],
    "TP C": ["TP H1 C 601 E2"],
    "WTP": ["WTP 501 E2"],
    "WTPF": ["WTPF Wing E2"],
    "PT": ["PT 4"],
    "CRP": ["CRP 5"],
    "GE": ["GE R2 100"],
    "GT": ["GT R2 2"],
    "TTNPR": ["TTNPR 8 3 R3"],
    "TTNPR ANY": ["TTNPR ANY 250 ANY 100 R3"],     # G-23: picks 8 or 14, gets 3
    "SS": ["SS 501"],
    "SCT": ["SCT 601"],
    "several": ["DI H1 1", "DSP H1", "GE R2 10", "BI E2 1", "PT 4"],
}


def _stock(st, systems_of):
    return {e: (st.empires[e].eu, sum(st.systems[i].iu for i in ids))
            for e, ids in systems_of.items()}


@pytest.mark.parametrize("name", list(SPENDING_ORDERS))
def test_ledger_reconciles_for_every_spending_order(name):
    lines = SPENDING_ORDERS[name]
    base = scenario()
    systems_of = {e: [s.id for s in base.systems if s.owner == e] for e in (1, 2, 3)}
    before = _stock(base, systems_of)

    # what the orders themselves do to the stockpiles
    st = from_dict(to_dict(base))
    ctx = ctx_for(st)
    for ln in lines:
        r = do(ctx, 1, ln)
        assert r.ok, (ln, r.error)
    after = _stock(st, systems_of)
    delta = {e: (after[e][0] - before[e][0], after[e][1] - before[e][1]) for e in after}
    assert delta[1] != (0, 0) or name == "TP A/I", "the order spent nothing?"

    # the same orders through a real turn: the ledger shows exactly that, and reconciles
    st2 = from_dict(to_dict(base))
    res = run_turn(st2, {1: parse_orders("\n".join(lines))}, npr_fn=None)
    assert all(o.ok for o in res.report(1).orders), [(o.text, o.error)
                                                      for o in res.report(1).orders]
    for e in (1, 2, 3):
        led = res.report(e).maintenance
        mine = [ln for ln in led if ln["kind"] in ORDER_KINDS]
        assert sum(ln["eu"] for ln in mine) == delta[e][0], (e, mine, delta[e])
        assert sum(ln.get("system_iu", 0) for ln in mine) == delta[e][1], (e, mine, delta[e])
        assert all(ln["iu"] == 0 for ln in mine)          # orders never touch the depot
        first, last = led[0], led[-1]
        assert (first["kind"], last["kind"]) == ("initial", "final")
        body = [ln for ln in led if ln["kind"] not in TOTALS]
        assert first["eu"] + sum(ln["eu"] for ln in body) == last["eu"] == st2.empires[e].eu
        assert first["iu"] + sum(ln["iu"] for ln in body) == last["iu"] == \
            st2.empires[e].iu_depot


def test_ledger_texts_are_sentence_case():
    st = scenario()
    res = run_turn(st, {1: parse_orders("DI H1 1\nGE R2 10\nSS 501")}, npr_fn=None)
    for ln in res.report(1).maintenance:
        assert ln["text"] != ln["text"].upper(), ln["text"]
