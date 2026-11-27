"""A simple baseline bot for strength tests: greedy expansion and random builds.

Like the real bot it decides only from the player view.  It researches a random affordable cheap
technology, builds infrastructure, builds a random unit at each system now and then, sends every
idle transport with a colonist to the nearest known empty world, and wanders its warships and
scouts about.  No diplomacy, no defence planning, no profiles.
"""
from __future__ import annotations

from ..data.ships import SHIP_TYPES
from ..data.techs import TECHS, missing_prereqs
from ..orders import Order
from .plan import Plan
from .world import build, dist


def baseline_orders(view: dict, mem: dict, rng) -> list[Order]:
    w = build(view, mem)
    plan = Plan(w)
    if not w.systems:
        return plan.orders
    cands = sorted((t for t in TECHS if 0 < t < 51 and t not in w.techs
                    and not missing_prereqs(w.techs, t) and TECHS[t].cost <= w.eu - 50),
                   key=lambda t: (TECHS[t].cost, t))
    if cands and rng.random() < 0.7:
        plan.buy_tech(rng.choice(cands[:5]), "random research")
    warships = [c for c, st in SHIP_TYPES.items() if st.attack > 0 and w.has_tech(st.tech)]
    for s in w.populated:
        if s.pop > s.infra:
            plan.infra(s, 1, "infrastructure")
        roll = rng.random()
        if roll < 0.25:
            plan.build_ship(s, "T", "F", None, "random build", 30)
        elif roll < 0.55:
            plan.build_ship(s, rng.choice(warships or ["F"]), "N", "SC", "random build", 30)
        elif roll < 0.65:
            plan.build_troop(s, "S", "A", "random build", 30)
        elif roll < 0.7 and s.starport < 3:
            plan.build_starport(s, "random build", 30)
    empty = [s for s in w.known.values() if not s.owner and
             (s.intel is None or (not s.intel["owner"] and s.intel["pop"] <= 0))]
    for sh in w.ships:
        if sh.order != "STAND" and (sh.x, sh.y) != (sh.dx, sh.dy):
            continue
        here = w.system_at(sh.x, sh.y)
        if sh.st.cargo > 0 and sh.st.attack == 0:
            c = plan.cargo_of(sh)
            if here is not None and not here.mine and not here.owner and c[2] > 0:
                plan.add("U", "settle", ship=sh.number, item="P", amount=c[2])
                c[2] = 0
            elif here is not None and here.mine and plan.pop[here.id] >= 2 and empty:
                tgt = min(empty, key=lambda s: (dist(sh.x, sh.y, s.x, s.y), s.id))
                empty.remove(tgt)
                if c[2] == 0:
                    plan.add("L", "colonist", ship=sh.number, item="P", amount=1)
                    plan.pop[here.id] -= 1
                plan.add("MS", "settle", ship=sh.number, system=tgt.name)
            elif here is None or not here.mine:
                home = w.nearest_own(sh.x, sh.y)
                if home is not None:
                    plan.add("MS", "home", ship=sh.number, system=home.name)
        elif sh.st.is_scout_class:
            plan.add("MO", "wander", ship=sh.number, x=rng.below(100), y=rng.below(100))
        elif sh.st.attack > 0 and rng.random() < 0.1 and w.known:
            near = sorted(w.known.values(), key=lambda s: (dist(sh.x, sh.y, s.x, s.y), s.id))[:5]
            plan.add("MS", "wander", ship=sh.number, system=rng.choice(near).name)
    return plan.orders
