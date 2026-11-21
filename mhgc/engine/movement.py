"""Turn phases 6-7: movement, intercept, guard, deferred fleet adds, combat drops; then leader
and spy transit (gcrun.c:847-1055; ENGINE_MAP 4.2).

Fleet movement follows the rules (rules:877-882): automatic speed is the slowest ship of the main
body; a set speed (FS) is used as given and slower ships are left behind; ships not with the main
body move to rejoin it at their own speed (the C used the rounded *average* speed and ignored FS,
DECISIONS §2 #24).
"""
from __future__ import annotations

from .. import geometry as G
from ..data import constants as K
from ..model import GUARD, INTERCEPT, MOVE, MOVE_TO_SYSTEM, STAND
from .context import TurnContext
from .orders_exec import add_ship_to_fleet, capture_unowned


def fleet_cleanup(ctx: TurnContext) -> None:
    st = ctx.state
    for sh in st.live_ships():
        if sh.fleet is not None:
            f = st.fleets.get(sh.fleet)
            if f is None or not f.alive or f.owner != sh.owner:
                sh.fleet = None
                sh.order, sh.dx, sh.dy = STAND, sh.x, sh.y


def move_fleets(ctx: TurnContext) -> None:
    st = ctx.state
    for f in st.fleets.values():
        if not f.alive or f.order == INTERCEPT:
            continue
        members = [s for s in st.fleet_ships(f.number) if s.owner == f.owner]
        body = [s for s in members if (s.x, s.y) == (f.x, f.y)]
        if f.order in (MOVE, MOVE_TO_SYSTEM) and body:
            slowest = min(s.stype.move for s in body)
            fastest = max(s.stype.move for s in body)
            speed = slowest if f.speed is None else min(f.speed, fastest)
            f.x, f.y = G.step(f.x, f.y, f.dx, f.dy, speed, st.board)
            if (f.x, f.y) == (f.dx, f.dy):
                f.order = STAND
        for s in members:
            s.order, s.dx, s.dy, s.target = MOVE, f.x, f.y, None


def move_ships(ctx: TurnContext) -> None:
    b = ctx.state.board
    for sh in ctx.state.live_ships():
        if sh.order in (MOVE, MOVE_TO_SYSTEM):
            sh.x, sh.y = G.step(sh.x, sh.y, sh.dx, sh.dy, sh.stype.move, b)
            if (sh.x, sh.y) == (sh.dx, sh.dy):
                sh.order = STAND


def intercept(ctx: TurnContext) -> None:
    """Intercepts are resolved after ordinary moves, in repeated one-square sweeps so that ships
    chasing ships that are themselves intercepting follow them, and circles close toward a common
    centre (rules:2155-2161).  Each ship's net displacement per axis is limited to its move
    (the same limit as inter.c, which this replaces; DECISIONS C-01)."""
    st = ctx.state
    chasers = []
    for sh in st.live_ships():
        if sh.order != INTERCEPT:
            continue
        tgt = st.ships.get(sh.target)
        if tgt is None or not tgt.alive:
            sh.order, sh.target, sh.dx, sh.dy = STAND, None, sh.x, sh.y
            continue
        chasers.append(sh)
    budget = {sh.number: [0, 0] for sh in chasers}
    for sweep in range(40):
        moved = False
        for sh in chasers:
            tgt = st.ships[sh.target]
            if (sh.x, sh.y) == (tgt.x, tgt.y):
                continue
            mv = sh.stype.move
            b = budget[sh.number]
            ddx = G.axis_delta(sh.x, tgt.x, st.board)
            ddy = G.axis_delta(sh.y, tgt.y, st.board)
            if ddx and abs(b[0] + (1 if ddx > 0 else -1)) <= mv:
                step = 1 if ddx > 0 else -1
                sh.x = G.wrap(sh.x + step, st.board)
                b[0] += step
                moved = True
            if ddy and abs(b[1] + (1 if ddy > 0 else -1)) <= mv:
                step = 1 if ddy > 0 else -1
                sh.y = G.wrap(sh.y + step, st.board)
                b[1] += step
                moved = True
        if not moved:
            break
    for sh in chasers:
        sh.dx, sh.dy = sh.x, sh.y
    # Intercepting fleets follow their fastest member (gcrun.c:956-970).
    for f in st.fleets.values():
        if f.alive and f.order == INTERCEPT:
            members = [s for s in st.fleet_ships(f.number) if s.owner == f.owner]
            if not members:
                f.order = STAND
                continue
            lead = max(members, key=lambda s: s.stype.move)
            f.x = f.dx = lead.x
            f.y = f.dy = lead.y
            tgt = st.ships.get(f.target)
            if tgt is None or not tgt.alive:
                f.order, f.target = STAND, None


def guard(ctx: TurnContext) -> None:
    """GUARD (rules:2171-2177): stand unless an enemy ship is within one move; then move to it,
    the closest first, ties at random.  Allied ships are ignored."""
    st = ctx.state
    for sh in st.live_ships():
        if sh.order != GUARD:
            continue
        best, bd = [], None
        for o in st.live_ships():
            if o.owner == sh.owner or ctx.allied(sh.owner, o.owner):
                continue
            d = G.distance(sh.x, sh.y, o.x, o.y, st.board)
            if d > sh.stype.move:
                continue
            if bd is None or d < bd:
                best, bd = [o], d
            elif d == bd:
                best.append(o)
        if best:
            t = ctx.rng.choice(best) if len(best) > 1 else best[0]
            sh.x, sh.y = t.x, t.y
            sh.dx, sh.dy = t.x, t.y


def add_fleet_xy(ctx: TurnContext) -> None:
    st = ctx.state
    for fno, x, y, owner in ctx.addfleetxy:
        f = st.fleets.get(fno)
        if f is None or not f.alive or f.owner != owner:
            continue
        for sh in st.live_ships():
            if sh.owner == owner and sh.fleet is None and (sh.x, sh.y) == (x, y):
                add_ship_to_fleet(ctx, f, sh)


def combat_drops(ctx: TurnContext) -> None:
    """DOCT drop pods (rules:599-603; gcparse1.c:466-547): 30% burn-up chance, +15% for each of
    PD, SW and APD on the target system (DECISIONS §2 #22)."""
    st = ctx.state
    for sh in st.live_ships():
        if not sh.drop:
            continue
        sh.drop = False
        s = st.system_at(sh.x, sh.y)
        if s is None:
            ctx.res.emit(sh.owner, "drop_burned", f"Ship {sh.number} isn't at a system, so no "
                         f"troops were dropped.", "drops", ship=sh.number)
            continue
        if s.owner == sh.owner:
            ctx.res.emit(sh.owner, "info", f"Ship {sh.number} is at your own system {s.name}; "
                         f"drop pods are for attacking, so no troops were dropped.", "drops",
                         s.id)
            continue
        chance = K.DROP_BURN_BASE + K.DROP_BURN_PER_DEFENCE * sum(
            1 for a in ("PD", "SW", "APD") if s.has(a))
        troops = st.troops_aboard(sh.number)
        for t in troops:
            if ctx.rng.chance(chance):
                t.alive = False
                ctx.res.emit((sh.owner, s.owner), "drop_burned",
                             f"The drop pod of troop {t.number} burned up attacking "
                             f"{s.name}.", "drops", s.id, ct=t.number)
                continue
            t.ship, t.system = None, s.id
            if s.owner == 0 and s.pop < 1.0:
                capture_unowned(ctx, sh.owner, s)
                ctx.res.emit(sh.owner, "system_captured",
                             f"You have captured the unowned system {s.name}.", "drops", s.id)
            elif not ctx.allied(s.owner, sh.owner):
                sh.posture = "H"
            ctx.res.emit((sh.owner, s.owner), "drop_landed",
                         f"Drop troop {t.number} landed on {s.name}.", "drops", s.id,
                         ct=t.number)


def leader_moves(ctx: TurnContext) -> None:
    """Leaders arrive after two turns in transit (rules:640-646, 2252).  A posted leader whose
    system changes hands, or whose fleet is gone, goes back to awaiting assignment."""
    st = ctx.state
    for ld in st.leaders.values():
        if not ld.alive:
            continue
        if ld.status == "transit":
            ld.transit -= 1
            if ld.transit <= 0:
                ld.status = "posted"
                where = (st.systems[ld.system].name if ld.system is not None
                         else "fleet " + st.fleets[ld.fleet].name if ld.fleet in st.fleets
                         else "?")
                ctx.res.emit(ld.owner, "leader_arrived", f"Leader {ld.name} has arrived at "
                             f"{where}.", "leaders", ld.system, leader=ld.id)
        if ld.status == "posted":
            bad = False
            if ld.system is not None and st.systems[ld.system].owner != ld.owner:
                bad = True
            if ld.fleet is not None:
                f = st.fleets.get(ld.fleet)
                bad = f is None or not f.alive or f.owner != ld.owner
            if bad:
                ld.status, ld.system, ld.fleet, ld.transit = "limbo", None, None, 0
                ctx.res.emit(ld.owner, "leader_evicted", f"Leader {ld.name} has lost his post "
                             f"and is awaiting a new assignment.", "leaders", leader=ld.id)


def spy_moves(ctx: TurnContext) -> None:
    for sp in ctx.state.spies.values():
        if sp.alive and sp.transit > 0:
            sp.transit -= 1
