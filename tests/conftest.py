"""Shared fixtures: tiny hand-built game states and scripted randomness."""
from __future__ import annotations

import os
import tempfile

# app.main builds a module-level app at import; keep its save directory out of the repo.
os.environ.setdefault("SAVE_DIR", tempfile.mkdtemp(prefix="mhgc-test-saves-"))

import pytest

from mhgc.engine.context import TurnContext
from mhgc.engine.orders_exec import execute
from mhgc.engine.turn import new_context
from mhgc.model import Empire, GameState, HUMAN, INDEPENDENT, NPR, Leader, Ship, System, Troop
from mhgc.orders import parse_line, parse_orders
from mhgc.rng import Rng


class ScriptedRng(Rng):
    """Rng whose chance() answers come from a script (default: a fixed answer); other draws are
    normal seeded draws."""

    def __init__(self, chance=None, script=(), seed=1, roll_max=False, below=()):
        super().__init__(seed, 1, "test")
        self.default = chance
        self.script = list(script)
        self.calls = []
        self.roll_max = roll_max
        self.below_script = list(below)

    def between(self, lo, hi):
        return hi if self.roll_max else super().between(lo, hi)

    def below(self, n):
        if self.below_script:
            return self.below_script.pop(0) % n
        return super().below(n)

    def chance(self, percent):
        self.calls.append(percent)
        if self.script:
            return self.script.pop(0)
        if self.default is None:
            return super().chance(percent)
        return self.default


def make_state(n_humans=2, npr=1) -> GameState:
    """Empires: 0 independents, 1..n_humans humans, then `npr` NPRs.  Each empire i has home
    system 'H<i>' at (10*i, 10*i) with 4 pop and default profiles, no leader.  An unowned empty
    system 'E1' at (50, 50) and 'E2' at (52, 50)."""
    st = GameState(name="test", seed=7, turn=5)
    st.empires[0] = Empire(0, "Rebels", kind=INDEPENDENT, eu=0, iu_depot=0)
    ids = list(range(1, n_humans + npr + 1))
    for i in ids:
        kind = HUMAN if i <= n_humans else NPR
        st.empires[i] = Empire(i, f"R{i}", kind=kind, eu=1000, iu_depot=200,
                               home_x=10 * i, home_y=10 * i)
        st.systems.append(System(len(st.systems), f"H{i}", 10 * i, 10 * i, owner=i, pop=4.0,
                                 happy=0.5, hab=3, infra=0, au=0, iu=500, starport=2))
    st.systems.append(System(len(st.systems), "E1", 50, 50, owner=0, hab=4))
    st.systems.append(System(len(st.systems), "E2", 52, 50, owner=0, hab=3))
    for e in st.empires.values():
        for s in st.systems:
            e.seen_systems[s.id] = {"turn": 0, "name": s.name, "owner": s.owner}
    return st


def sysn(st, name) -> System:
    return st.system_named(name)


def add_ship(st, owner, stype, x, y, number=None, **kw) -> Ship:
    number = number or (max(st.ships, default=100) + 1)
    sh = Ship(number, owner, stype, x, y, dx=x, dy=y, ox=x, oy=y, **kw)
    st.ships[number] = sh
    return sh


def add_troop(st, owner, ttype, system=None, ship=None, posture="A", number=None) -> Troop:
    number = number or (max(st.troops, default=100) + 1)
    t = Troop(number, owner, ttype, system=system, ship=ship, posture=posture)
    st.troops[number] = t
    return t


def add_leader(st, owner, system=None, fleet=None, **skills) -> Leader:
    lid = st.next_leader_id
    st.next_leader_id += 1
    ld = Leader(lid, f"L{lid}", owner, status="posted", system=system, fleet=fleet, **skills)
    st.leaders[lid] = ld
    return ld


def contact(st, a, b, rel="N", back=None):
    st.empires[a].relations[b] = rel
    st.empires[b].relations[a] = back or ("W" if rel == "W" else "N")


def ctx_for(st, rng=None) -> TurnContext:
    ctx = new_context(st)
    if rng is not None:
        ctx.rng = rng
    ctx.empire_order = list(st.empires)
    return ctx


def do(ctx, eid, text):
    """Execute one order line for empire `eid`; returns the OrderResult."""
    o = parse_line(text)
    return execute(ctx, eid, o, 0)


@pytest.fixture
def st():
    return make_state()
