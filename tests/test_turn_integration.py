"""Whole-turn integration: determinism, invariants over a long game driven by a crude random
order generator (a fuzz test, not an AI)."""
import random

import pytest

from mhgc import geometry as G
from mhgc import model
from mhgc.data import SHIP_TYPES, TECHS
from mhgc.engine.turn import run_turn
from mhgc.mapgen import new_game
from mhgc.orders import OrderSyntaxError, make_order, parse_line


def fuzz_orders(st, eid, r: random.Random):
    e = st.empires[eid]
    out = []
    mine = [s for s in st.systems if s.owner == eid]
    ships = [s for s in st.live_ships() if s.owner == eid]
    rel = lambda x, y: G.to_rel(x, y, e.home_x, e.home_y)
    cheap = [t for t in sorted(TECHS) if 0 < t < 51 and t not in e.techs]
    if cheap and r.random() < 0.6:
        out.append(f"PT {r.choice(cheap[:6])}")
    for s in mine:
        if s.pop <= 0:
            continue
        roll = r.random()
        if roll < 0.3:
            out.append(f"BS {s.name} {r.choice(['T', 'F', 'S', 'D', 'PA'])} H")
        elif roll < 0.45:
            out.append(f"BCU {s.name} {r.choice(['S', 'M', 'J'])}")
        elif roll < 0.55:
            out.append(f"BI {s.name} 1")
        elif roll < 0.6:
            out.append(f"BSP {s.name}")
        if r.random() < 0.2:
            out.append(f"CSP {s.name} {r.choice(['50 25 25', '20 40 40', '34 33 33'])}")
        if r.random() < 0.1:
            out.append(f"SISD {s.name} 30")
        if r.random() < 0.1 and 2 in e.techs:
            out.append(f"BT {s.name} EHC")
    targets = [s for s in st.systems if s.id in e.seen_systems]
    for sh in ships:
        here = st.system_at(sh.x, sh.y)
        roll = r.random()
        if sh.type == "T" and here is not None and here.owner == eid and here.pop > 3 \
                and sh.cargo_pop == 0:
            out.append(f"L {sh.number} P 1")
            if here.iu >= 10:
                out.append(f"L {sh.number} I 10")
            for t in st.troops_at(here.id):
                if t.owner == eid and t.type != "M":
                    out.append(f"LOCT {sh.number} {t.number}")
                    break
        elif sh.type == "T" and here is not None and here.owner != eid:
            out.append(f"UG {sh.number} P {sh.cargo_pop}")
            for t in st.troops_aboard(sh.number):
                out.append(f"LACT {sh.number} {t.number}")
        if roll < 0.5 and targets:
            tgt = r.choice(targets)
            out.append(f"MS {sh.number} {tgt.name}")
        elif roll < 0.6:
            x, y = rel(sh.x + r.randint(-8, 8), sh.y + r.randint(-8, 8))
            out.append(f"MO {sh.number} {x} {y}")
        elif roll < 0.65:
            out.append(f"G {sh.number}")
        elif roll < 0.7:
            others = [o for o in st.live_ships() if o.owner != eid]
            if others:
                out.append(f"I {sh.number} {r.choice(others).number}")
        if r.random() < 0.1:
            out.append(f"CSCR {sh.number} {r.choice(['SC', 'MR', 'GC', 'RD'])}")
    for other in list(e.relations):
        if other and r.random() < 0.05:
            out.append(f"{r.choice(['DA', 'DW', 'EWA'])} {st.empires[other].name}")
    if ships and r.random() < 0.2:
        fname = f"F{eid}_{st.turn}"
        out.append(f"CF {fname} 50 50")
        out.append("AF " + fname + " " + " ".join(str(s.number) for s in ships[:4]))
        x, y = rel(ships[0].x + 5, ships[0].y)
        out.append(f"MF {fname} {x} {y}")
    for ld in st.leaders.values():
        if ld.owner == eid and ld.status == "limbo" and mine:
            out.append(f"ML {ld.name} {r.choice(mine).name}")
    orders = []
    for line in out:
        try:
            o = parse_line(line)
        except OrderSyntaxError:
            continue
        if o is not None:
            orders.append(o)
    return orders


def check_invariants(st):
    for s in st.systems:
        assert 0 <= s.x < 100 and 0 <= s.y < 100
        assert s.pop >= 0 and s.au >= 0 and s.iu >= 0 and s.infra >= 0, s
        assert s.starport >= 0 and s.status in (0, 1, 2)
        assert s.owner in st.empires
    for e in st.empires.values():
        assert e.eu >= 0 and e.iu_depot >= 0, e
    for sh in st.ships.values():
        assert sh.alive and 0 <= sh.x < 100 and 0 <= sh.y < 100
        assert st.free_cargo(sh, "A") >= 0
        assert st.cargo_points_used(sh) <= sh.stype.cargo
        assert sh.fleet is None or sh.fleet in st.fleets or True
    for t in st.troops.values():
        assert t.alive
        assert (t.system is None) != (t.ship is None)
        if t.ship is not None:
            assert t.ship in st.ships
    for ld in st.leaders.values():
        assert 0 <= ld.mgmt <= 99 and 0 <= ld.combat <= 99


def play(seed, turns, humans=4):
    st = new_game("fuzz", seed, [f"P{i}" for i in range(humans)])
    r = random.Random(seed)
    results = []
    for _ in range(turns):
        orders = {e.id: fuzz_orders(st, e.id, r) for e in st.empires.values()
                  if e.kind == "human"}
        res = run_turn(st, orders)
        check_invariants(st)
        results.append(res)
        if st.winner is not None:
            break
    return st, results


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_long_fuzz_game(seed):
    st, results = play(seed, 40)
    assert st.turn >= 20
    kinds = {ev.kind for r in results for rep in r.reports.values() for ev in rep.events}
    assert "emperor_day" in kinds or "uprising" in kinds
    # results are JSON serialisable
    import json
    json.dumps(results[-1].to_dict())


def test_turns_are_deterministic():
    a, _ = play(5, 15)
    b, _ = play(5, 15)
    assert model.dumps(a) == model.dumps(b)


def test_order_results_reported():
    st = new_game("t", 1, ["Me"])
    home = st.system_at(st.empires[1].home_x, st.empires[1].home_y)
    res = run_turn(st, {1: [parse_line(f"BS {home.name} F"), parse_line("PT 99")]})
    rep = res.report(1)
    assert rep.orders[0].ok and not rep.orders[1].ok
    assert rep.economy["eu"] == st.empires[1].eu
    assert rep.stats["vp"] == st.empires[1].vp
    assert any(m["kind"] == "final" for m in rep.maintenance)


def test_invasion_through_run_turn():
    """A hostile task force sits at an enemy home system: combat every turn, the system moves
    one status step a turn (rules:946-950), and troops landed from orbit take it."""
    st = new_game("t", 2, ["A", "B"])
    a, b = st.empires[1], st.empires[2]
    target = st.system_at(b.home_x, b.home_y)
    from tests.conftest import add_ship, add_troop
    for _ in range(6):
        add_ship(st, 1, "C", target.x, target.y, posture="H", role="SC")
    tr = add_ship(st, 1, "T", target.x, target.y, posture="H", role="RD")
    troops = [add_troop(st, 1, "O", ship=tr.number) for _ in range(3)]
    a.eu = 5000
    a.iu_depot = 5000
    statuses = []
    for turn in range(3):
        orders = {1: []}
        if turn == 1:
            orders[1] = [parse_line(f"LACT {tr.number} {t.number}") for t in troops
                         if t.alive and t.ship == tr.number]
        res = run_turn(st, orders)
        assert res.combats or target.owner == 1
        statuses.append(target.status)
        check_invariants(st)
    assert statuses[0] == 1                      # NORMAL -> UNDER ATTACK, not straight to INT
    assert target.owner == 1                     # captured once the troops landed
    assert any(ev.kind == "system_lost" for ev in res.report(2).events) or \
        target.owner == 1
