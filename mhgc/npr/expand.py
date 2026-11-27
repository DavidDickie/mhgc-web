"""Exploration and colonisation (rules:425-432, 1169-1182, 2191-2224).

* Scouts sweep a 10x10 grid of 10-square cells, nearest unexplored first, and visit systems known
  only from long-range scans, because only a short scan shows habitability, population and troops.
* Colonies are chosen by value / distance: habitability (growth and happiness), MR/AR (double
  IU/AU), artifacts; unknown worlds are assumed average.  A transport carries 1-2 colonists and
  40 IUs (infrastructure and a starport for the colony); landing people on an empty world claims
  it (U P, rules:427).
* Transports are built while there are good targets, and also move colonists from full systems
  to roomy ones and IUs from rich to poor ones.
"""
from __future__ import annotations

from ..data import constants as K
from .econ import reserve
from .memory import log
from .world import board, dist, hab_of, home_xy, turns_to

CELL = 10
SETTLE_RANGE = 30


def _per_side() -> int:
    """Scout cells per board side: about CELL squares each (10 on 100x100, 8 on 75x75, 5 on 50x50)."""
    return max(1, round(board() / CELL))


def _cells() -> int:
    return _per_side() ** 2


def _cell(x: int, y: int) -> int:
    n, b = _per_side(), board()
    return (x * n // b) * n + (y * n // b)


def _centre(c: int) -> tuple[int, int]:
    n, b = _per_side(), board()
    return ((c // n) * b + b // 2) // n, ((c % n) * b + b // 2) // n


def scouts(w, plan) -> None:
    mem = w.mem
    cells = set(mem.setdefault("cells", []))
    for sh in w.ships:
        cells.add(_cell(sh.x, sh.y))
    for s in w.populated:
        cells.add(_cell(s.x, s.y))
    visited = set(mem["visited"])
    for sh in w.ships:
        sys_here = w.system_at(sh.x, sh.y)
        if sys_here is not None:
            visited.add(sys_here.id)
    mem["visited"] = sorted(visited)
    if len(cells) >= _cells():
        cells = set()                            # all explored: sweep again
    mem["cells"] = sorted(cells)
    targeted: set = set()
    for sh in sorted((s for s in w.ships if s.st.is_scout_class and s.fleet is None),
                     key=lambda s: s.number):
        if sh.number in plan.busy:
            continue
        if sh.order != "STAND" and (sh.x, sh.y) != (sh.dx, sh.dy):
            targeted.add((sh.dx, sh.dy))
            continue
        best, bd = None, None
        for s in w.known.values():
            if s.id in visited or (s.x, s.y) in targeted:
                continue
            if s.intel is not None and w.turn - s.intel["t"] < 25:
                continue
            if s.owner and w.at_war(s.owner):
                continue
            d = dist(sh.x, sh.y, s.x, s.y)
            if bd is None or d < bd:
                best, bd = s, d
        if best is not None and bd <= 16:
            plan.add("MS", "scout a world up close", ship=sh.number, system=best.name)
            targeted.add((best.x, best.y))
            plan.busy.add(sh.number)
            continue
        free = [c for c in range(_cells()) if c not in cells
                and _centre(c) not in targeted]
        if not free:
            continue
        c = min(free, key=lambda c: (dist(sh.x, sh.y, *_centre(c)) +
                                     0.5 * dist(*home_xy(), *_centre(c)), c))
        cx, cy = _centre(c)
        targeted.add((cx, cy))
        plan.add("MO", "explore", ship=sh.number, x=cx, y=cy)
        plan.busy.add(sh.number)
        cells.add(c)
    mem["cells"] = sorted(cells)


def colony_value(w, s) -> float:
    it = s.intel
    v = hab_of(s) * 1.5 + 3
    if it:
        v += (2 if it["mr"] else 0) + (1.5 if it["ar"] else 0) + 2 * it["artifacts"]
    return v


def colony_targets(w) -> list:
    claimed = {v for v in w.mem["claims"].values() if isinstance(v, int)}
    out = []
    for s in w.known.values():
        if s.id in claimed or s.owner:
            continue
        it = s.intel
        if it is not None and (it["owner"] or it["pop"] > 0) and w.turn - it["t"] < 15:
            continue
        # a hostile warship sitting there makes it a bad idea
        if any((c.x, c.y) == (s.x, s.y) and c.st.attack > 0 and not w.allied(c.owner)
               for c in w.contacts):
            continue
        out.append(s)
    return out


def _transports(w):
    traders = w.mem.get("traders") or {}          # on their way to a trade route (ctt.py)
    return [sh for sh in w.ships if sh.st.cargo > 0 and sh.st.attack == 0 and sh.fleet is None
            and str(sh.number) not in traders]


def _immigration_h(s, pop: float, n: int) -> float:
    """The happiness landing n population costs (engine/orders_exec unload)."""
    return pop * pop * n / ((s.hab + (1 if "EHC" in s.artifacts else 0) +
                             (3 if "CS" in s.artifacts else 0)) * K.IMMIGRATION_DIVISOR)


def _immigration_ok(s, pop: float, n: int, happy: float | None = None) -> bool:
    return (s.happy if happy is None else happy) - _immigration_h(s, pop, n) > 0.1


def transports(w, plan, threatened: set, mission_ships: set) -> None:
    claims = w.mem["claims"]
    alive = {sh.number for sh in w.ships}
    for key in list(claims):
        if int(key) not in alive:
            del claims[key]
    targets = colony_targets(w)
    idle = []
    for sh in _transports(w):
        if sh.number in mission_ships or sh.number in plan.busy:
            continue
        here = w.system_at(sh.x, sh.y)
        c = plan.cargo_of(sh)
        key = str(sh.number)
        moving = sh.order != "STAND" and (sh.x, sh.y) != (sh.dx, sh.dy)
        if moving:
            continue
        if here is not None and not here.mine and not here.owner and c[2] > 0:
            it = here.intel
            if it is None or (not it["owner"] and it["pop"] <= 0):
                plan.add("U", "settle the empty world", ship=sh.number, item="P", amount=c[2])
                for t in sh.cargo[3]:
                    plan.add("LACT", "garrison the colony", ship=sh.number, ct=t)
                if c[1]:
                    plan.add("U", "", ship=sh.number, item="I", amount=c[1])
                if c[0]:
                    plan.add("U", "", ship=sh.number, item="A", amount=c[0])
                plan.cargo[sh.number] = [0, 0, 0, 0]
                claims.pop(key, None)
                w.mem["stats"]["colonies"] += 1
                log(w.mem, w.turn, "colony", system=here.id)
                plan.busy.add(sh.number)
                continue
        if here is not None and here.mine and (c[0] or c[1] or c[2]):
            if c[2] and _immigration_ok(here, plan.pop[here.id], c[2], plan.happy[here.id]):
                plan.add("U", "deliver colonists", ship=sh.number, item="P", amount=c[2])
                # a second landing here this turn sees the happiness this one costs
                plan.happy[here.id] -= _immigration_h(here, plan.pop[here.id], c[2])
                plan.pop[here.id] += c[2]
                c[2] = 0
            if c[1]:
                plan.add("U", "deliver IUs", ship=sh.number, item="I", amount=c[1])
                plan.iu[here.id] += c[1]
                c[1] = 0
            if c[0]:
                plan.add("U", "", ship=sh.number, item="A", amount=c[0])
                c[0] = 0
            claims.pop(key, None)
        if here is None or not here.mine:
            home = w.nearest_own(sh.x, sh.y)
            claims.pop(key, None)
            if home is not None:
                plan.add("MS", "transport going home", ship=sh.number, system=home.name)
                plan.busy.add(sh.number)
            continue
        idle.append((sh, here))
    for sh, here in idle:
        if here.id in threatened or plan.pop.get(here.id, 0) < 2.0:
            if _supply(w, plan, sh, here):
                continue
            continue
        best, bv = None, None
        for s in targets:
            d = dist(here.x, here.y, s.x, s.y)
            if d > SETTLE_RANGE:
                continue
            v = colony_value(w, s) / (1 + turns_to(sh.st.move, d))
            if bv is None or v > bv:
                best, bv = s, v
        if best is None:
            _supply(w, plan, sh, here)
            continue
        c = plan.cargo_of(sh)
        n = 2 if plan.pop[here.id] >= 8 and plan.free_points(sh) >= 3 else 1
        if c[2] < 1:
            plan.add("L", "load colonists", ship=sh.number, item="P", amount=n)
            c[2] += n
            plan.pop[here.id] -= n
        iu = min(plan.iu.get(here.id, 0) - 10, 40, plan.free_goods(sh))
        if iu > 0:
            plan.add("L", "IUs for the colony", ship=sh.number, item="I", amount=iu)
            c[1] += iu
            plan.iu[here.id] -= iu
        plan.add("MS", f"settle {best.name}", ship=sh.number, system=best.name)
        plan.busy.add(sh.number)
        claims[str(sh.number)] = best.id
        targets.remove(best)
    _build(w, plan, threatened, targets, len(idle))


def _supply(w, plan, sh, here) -> bool:
    near = [s for s in w.populated if s.id != here.id and s.status == K.NORMAL
            and dist(here.x, here.y, s.x, s.y) <= 2 * sh.st.move]
    c = plan.cargo_of(sh)
    if plan.pop.get(here.id, 0) >= 9.5:
        roomy = [s for s in near if plan.pop.get(s.id, s.pop) < min(6, s.hab + 2)]
        if roomy:
            dest = min(roomy, key=lambda s: (plan.pop.get(s.id, s.pop), s.id))
            n = min(2, plan.free_points(sh))
            if n > 0:
                plan.add("L", "colonists for a roomier world", ship=sh.number, item="P",
                         amount=n)
                c[2] += n
                plan.pop[here.id] -= n
                plan.add("MS", "", ship=sh.number, system=dest.name)
                plan.busy.add(sh.number)
                w.mem["claims"][str(sh.number)] = "supply"
                return True
    if plan.iu.get(here.id, 0) > 160:
        poor = [s for s in near if plan.iu.get(s.id, s.iu) < 40]
        if poor:
            dest = min(poor, key=lambda s: (plan.iu.get(s.id, s.iu), s.id))
            n = min(60, plan.free_goods(sh))
            if n > 0:
                plan.add("L", "IUs for a poorer world", ship=sh.number, item="I", amount=n)
                c[1] += n
                plan.iu[here.id] -= n
                plan.add("MS", "", ship=sh.number, system=dest.name)
                plan.busy.add(sh.number)
                w.mem["claims"][str(sh.number)] = "supply"
                return True
    return False


def _build(w, plan, threatened, targets, n_idle) -> None:
    trans = _transports(w)
    want = min(3 + len(w.populated) // 2, 10) if targets else 1
    want = min(want, 1 + len(targets))
    if len(trans) >= want or n_idle > 1:
        return
    srcs = sorted((s for s in w.populated if s.pop >= 3 and s.id not in threatened),
                  key=lambda s: (-s.pop, s.id))
    for s in srcs[:3]:
        if len(trans) >= want:
            break
        if plan.build_ship(s, "T", "F", None, "a transport for colonists", reserve(w),
                           purpose="expansion"):
            trans.append(None)


def build_scouts(w, plan) -> None:
    have = sum(1 for sh in w.ships if sh.st.is_scout_class)
    unexplored = _cells() - len(w.mem.get("cells", []))
    want = 2 if w.turn < 30 else 1
    if unexplored < 10:
        want = 1
    home = w.home()
    if home is not None and have < want:
        code = "SS" if w.has_tech(16) else "S"
        plan.build_ship(home, code, "F", "SC", "a scout", reserve(w), purpose="expansion")


__all__ = ["scouts", "transports", "build_scouts", "colony_targets", "colony_value"]
