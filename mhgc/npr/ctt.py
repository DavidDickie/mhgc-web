"""Trade routes (Decentralized Trading, tech 21; CTT, rules:319-327, 2868-2880).  DECISIONS A-11.

A transport at another race's populated system can be converted into a trade route there (CTT):
the ship is gone and, every turn after, the route earns 25% of that system's EU production
(created, not taken from the owner), all routes on one system together capped at 50% of its
production (engine/economy.trade).  One route per system per race; it is lost when the system
is interdicted or changes owner (or a spy's SET).  So a route is a lasting investment: one
transport (20 IU + 20 EU) and its upkeep on the trip (5 EU a turn away from our systems) for an
income as long as the system stays in the same hands.

The bot (all from its own view, A-02):
* Candidates: known systems of a contacted race we are not at war with (allies too), populated
  by our short-scan intel, status normal, not already carrying our route, no warship of a race at
  war with us seen there.  Rebels and empty worlds are not traded with (the rules: routes go to
  other races).
* Value: the system's EU production estimated from that intel (population, infrastructure,
  starport; the owner's split is unknown, so the default third goes to EU), x 25%, shared out
  when other races' routes (the short scan lists them) would pass the 50% cap.
* A route is worth it when the transport and the trip pay back within PAYBACK turns; the best
  value per cost goes first.  At most a few transports are on their way at once
  (`max_inflight`), built for the purpose after development (or idle transports taken over once
  no colony target is left).
* On arrival, a fresh look: still theirs, populated, not at war with us, no route of ours there
  yet: CTT.  Otherwise another target, or home.
* Our routes are remembered (`mem["routes"]`) from the engine's "trade_route" events, and
  dropped when a short scan no longer lists us, the owner changes, or it is interdicted.
"""
from __future__ import annotations

from ..data import constants as K
from ..data.ships import SHIP_TYPES
from .econ import reserve
from .trace import note
from .world import dist, turns_to

TECH = 21                    # Decentralized Trading
EU_SHARE = 1 / 3             # the default profile's EU share (rules:364), the owner's is unknown
PAYBACK = 15                 # turns the transport and its trip may take to pay back
MIN_VALUE = 2.0              # EU a turn below which a route isn't worth a ship
MAX_TURNS = 7                # longest trip (turns at the transport's speed)
INTEL_AGE = 30               # turns: older short-scan intel is not trusted for a route
SHIP = "T"
TRIP_EU = K.SHIP_MAINT_NORMAL[1]   # upkeep per turn of travel away from our systems


def _routes(w) -> dict:
    return w.mem.setdefault("routes", {})


def _traders(w) -> dict:
    return w.mem.setdefault("traders", {})


def trader_ships(mem: dict) -> set:
    """Ship numbers on their way to a trade route (expand.py leaves them alone)."""
    return {int(k) for k in (mem.get("traders") or {})}


def est_eu(s) -> float:
    """EU a turn the known foreign system s produces, from our short-scan intel."""
    it = getattr(s, "intel", None)
    if not it or it.get("pop", 0) <= 0:
        return 0.0
    pop = it["pop"]
    infra = it.get("infra")
    mult = min(2.0, (pop + infra) / pop) if infra is not None else 1.5
    return pop * K.PROD_PER_POP * mult * (1 + K.STARPORT_PROD_BONUS * it.get("starport", 0)) * \
        EU_SHARE


def route_value(w, s) -> float:
    """Our EU a turn from a route at s (engine/economy.trade, with the 50% cap shared)."""
    it = getattr(s, "intel", None) or {}
    others = [r for r in it.get("routes") or [] if r != w.name]
    n = len(others) + 1
    return K.DCT_SHARE * est_eu(s) * min(1.0, K.DCT_CAP / (K.DCT_SHARE * n))


def _hostile_at(w, s) -> bool:
    return any(c.st.attack > 0 and w.at_war(c.owner) and dist(c.x, c.y, s.x, s.y) <= 2
               for c in w.contacts)


def tradeable(w, s) -> bool:
    """Is the known foreign system s a place we may set up a route (rules and safety)?"""
    o = s.owner
    if not o or o == w.eid or o not in w.contacted() or w.at_war(o):
        return False
    if str(s.id) in _routes(w):
        return False
    it = getattr(s, "intel", None)
    if not it or it.get("pop", 0) <= 0 or w.turn - it["t"] > INTEL_AGE:
        return False
    if (it.get("owner") or 0) != o or it.get("status") not in (None, "Norm"):
        return False
    if w.name in (it.get("routes") or []):
        return False
    return not _hostile_at(w, s)


def candidates(w, x: int, y: int, move: int, skip: set = frozenset()) -> list:
    """[(score, value, turns, system)] worth a transport from (x, y), best first."""
    out = []
    for s in w.known.values():
        if s.id in skip or not tradeable(w, s):
            continue
        t = turns_to(move, dist(x, y, s.x, s.y))
        if t > MAX_TURNS:
            continue
        v = route_value(w, s)
        if v < MIN_VALUE:
            continue
        st = SHIP_TYPES[SHIP]
        cost = st.eu_cost + st.iu_cost + 2 * TRIP_EU * t
        if cost / v > PAYBACK:
            continue
        out.append((v / cost, v, t, s))
    out.sort(key=lambda c: (-c[0], c[3].id))
    return out


def research_value(w) -> float:
    """What Decentralized Trading is worth to us (econ.tech_score), from the routes we know of:
    about the EU a turn of the four best (+50% EU to an empire of 60 EU a turn is 34)."""
    vals = sorted((route_value(w, s) for s in w.known.values()
                   if s.owner and s.owner in w.contacted() and not w.at_war(s.owner)),
                  reverse=True)[:4]
    return min(40.0, 1.1 * sum(v for v in vals if v >= MIN_VALUE))


def max_inflight(w) -> int:
    return min(4, 1 + len(w.populated) // 4)


def learn(w) -> None:
    """Our routes, from our own report and scans."""
    routes = _routes(w)
    for ev in (w.results.get("events") or []):
        sid = ev.get("system")
        if ev.get("kind") == "trade_route" and sid is not None:
            r = routes.setdefault(str(sid), {"t": w.turn - 1})
            r["ok"] = True
            k = w.known.get(sid)
            if k is not None and k.owner:
                r["owner"] = k.owner
        elif ev.get("kind") == "trade_route_ended" and sid is not None:
            routes.pop(str(sid), None)
    for key in list(routes):
        r = routes[key]
        k = w.known.get(int(key))
        if not r.get("ok") and w.turn - r["t"] >= 2:
            del routes[key]                      # the CTT failed
            continue
        if k is None:
            continue
        it = k.intel or {}
        gone = (r.get("owner") and k.owner != r["owner"]) or \
            (it.get("t", -1) >= r["t"] + 1 and (w.name not in (it.get("routes") or []) or
                                                 it.get("status") == "INT"))
        if gone and r.get("ok"):
            del routes[key]
            note("ctt_route_lost", system=int(key))
    alive = {sh.number for sh in w.ships}
    tr = _traders(w)
    for key in list(tr):
        if int(key) not in alive:
            del tr[key]
    builds = w.mem.setdefault("ctt_build", {})
    for key in list(builds):
        if w.turn - builds[key] > 2:
            del builds[key]


def _idle(w, sh, plan) -> bool:
    return (sh.st.cargo > 0 and sh.st.attack == 0 and sh.fleet is None and
            sh.number not in plan.busy and str(sh.number) not in w.mem["claims"] and
            not any(plan.cargo_of(sh)[:3]) and not sh.cargo[3] and
            (sh.order == "STAND" or (sh.x, sh.y) == (sh.dx, sh.dy)))


def move(w, plan, colony_targets: bool, mission_ships: set) -> None:
    """Traders under way: convert on arrival, re-target or go home.  Then send new ones: the
    transports built for trade last turn, and idle ones once no colony target is left."""
    if not w.has_tech(TECH):
        return
    learn(w)
    tr = _traders(w)
    taken = {v for v in tr.values()}
    for sh in sorted(w.ships, key=lambda s: s.number):
        key = str(sh.number)
        if key not in tr:
            continue
        s = w.known.get(tr[key])
        moving = sh.order != "STAND" and (sh.x, sh.y) != (sh.dx, sh.dy)
        if s is not None and (sh.x, sh.y) == (s.x, s.y) and not moving:
            if tradeable(w, s):
                plan.add("CTT", "trade route", ship=sh.number)
                _routes(w)[str(s.id)] = {"t": w.turn, "owner": s.owner, "ok": False,
                                         "v": round(route_value(w, s), 1)}
                w.mem["stats"]["routes"] = w.mem["stats"].get("routes", 0) + 1
                note("ctt_convert", system=s.id, owner=s.owner,
                     value=round(route_value(w, s), 1))
                plan.busy.add(sh.number)
                del tr[key]
                continue
            s = None
        elif s is not None and moving and tradeable(w, s):
            plan.busy.add(sh.number)                 # still worth it: on we go
            continue
        # the target went bad: another one, or home
        taken.discard(tr[key])
        del tr[key]
        if not _send(w, plan, sh, taken):
            home = w.nearest_own(sh.x, sh.y)
            if home is not None and (sh.x, sh.y) != (home.x, home.y):
                plan.add("MS", "transport going home", ship=sh.number, system=home.name)
                plan.busy.add(sh.number)
    builds = w.mem.setdefault("ctt_build", {})
    own = {(s.x, s.y): s for s in w.systems}
    n = len(tr)
    for sh in sorted(w.ships, key=lambda s: s.number):
        if n >= max_inflight(w):
            break
        if sh.number in mission_ships or not _idle(w, sh, plan) or (sh.x, sh.y) not in own:
            continue
        here = own[(sh.x, sh.y)]
        built_for = builds.get(str(here.id))
        if not (built_for is not None and sh.built >= built_for) and colony_targets:
            continue
        if _send(w, plan, sh, taken):
            n += 1
            if built_for is not None:
                builds.pop(str(here.id), None)


def _send(w, plan, sh, taken: set) -> bool:
    cands = candidates(w, sh.x, sh.y, sh.st.move, taken)
    if not cands:
        return False
    score, v, t, s = cands[0]
    plan.add("MS", f"to trade with {s.name}", ship=sh.number, system=s.name)
    plan.busy.add(sh.number)
    _traders(w)[str(sh.number)] = s.id
    taken.add(s.id)
    note("ctt_send", ship=sh.number, system=s.id, owner=s.owner, value=round(v, 1),
         turns=t)
    return True


def build(w, plan, threatened: set) -> None:
    """Transports for trade routes, after development (an investment like the others)."""
    if not w.has_tech(TECH):
        return
    tr = _traders(w)
    builds = w.mem.setdefault("ctt_build", {})
    pending = len(tr) + len(builds)
    if pending >= max_inflight(w):
        return
    taken = set(tr.values())
    st = SHIP_TYPES[SHIP]
    res = reserve(w) + 30
    for s in sorted(w.populated, key=lambda s: (-s.pop, s.id)):
        if pending >= max_inflight(w):
            break
        if s.id in threatened or str(s.id) in builds or s.status != K.NORMAL:
            continue
        cands = candidates(w, s.x, s.y, st.move, taken)
        if not cands:
            continue
        if plan.build_ship(s, SHIP, "F", None, "a transport for a trade route", res,
                           purpose="trade"):
            builds[str(s.id)] = w.turn
            taken.add(cands[0][3].id)
            pending += 1
            note("ctt_build", system=s.id, target=cands[0][3].id, value=round(cands[0][1], 1))


__all__ = ["move", "build", "learn", "route_value", "est_eu", "candidates", "research_value",
           "trader_ships", "tradeable", "max_inflight"]
