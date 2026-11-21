"""Turn phase 11: scans (rules:229-231, 343, 1169-1182; gcscan.c:521-666).

Ships scan out to their scan factor; populated systems to 4 (6 with ESS, 10 with EESS).  The same
square gives a short-range scan (full detail); anything else in range a long-range scan (owner,
name/type and position only).  Systems are only ever long-range scanned by systems.  Computer
empires scan exactly like players (Dave 2026-11-12, DECISIONS A-01).  Scanning something of another race makes
contact both ways (gcscan.c:169-239).  Results go to each empire's report `scans`, and every
system seen is remembered in `Empire.seen_systems` (the C used systems.tr = -1 for this).

Map memory (`remember`) keeps the name, owner and turn of the latest sighting, and, from the
latest SHORT scan only, the habitability and the MR/AR flags with the turn they were seen
(`detail_turn`).  Long scans show only owner, name and location (rules:1174), so they never
change those facts; the last short scan's values stick (Dave 2026-11-13, DECISIONS G-08).
Every square inside an empire's ship and system scans is added to `Empire.scan_history`
(mhgc/scanmask; the old TRACKSCAN map, always on, DECISIONS G-07).

Also here: races with no ships and no systems become extinct (gcscan.c:555-564).
"""
from __future__ import annotations

from .. import geometry as G
from .. import scanmask
from ..data import constants as K
from ..data.troops import POSTURE_NAMES
from ..model import DEAD, HUMAN, NPR
from .context import TurnContext

SHORT, LONG = "short", "long"


def _better(cur, new):
    return SHORT if SHORT in (cur, new) else new or cur


def ship_view(ctx, sh, viewer, level):
    rx, ry = ctx.rel_xy(viewer, sh.x, sh.y)
    ox, oy = ctx.rel_xy(viewer, sh.ox, sh.oy)
    d = {"number": sh.number, "owner": sh.owner, "owner_name": ctx.name(sh.owner),
         "type": sh.type, "x": rx, "y": ry, "ox": ox, "oy": oy, "level": level,
         "moved": (sh.ox, sh.oy) != (sh.x, sh.y)}
    f = ctx.state.fleets.get(sh.fleet) if sh.fleet is not None else None
    if f is not None and f.alive:
        d["fleet"] = f.name
    if level == SHORT:
        d.update(posture=sh.posture, role=sh.role)
        if sh.stype.cargo:
            d["cargo"] = {"AU": sh.cargo_au, "IU": sh.cargo_iu, "POP": sh.cargo_pop,
                          "CT": [{"number": t.number, "type": t.type, "owner": t.owner,
                                  "posture": POSTURE_NAMES[t.posture]}
                                 for t in ctx.state.troops_aboard(sh.number)]}
    return d


def system_view(ctx, s, viewer, level):
    rx, ry = ctx.rel_xy(viewer, s.x, s.y)
    d = {"id": s.id, "name": s.name, "x": rx, "y": ry, "level": level,
         "owner": s.owner,
         "owner_name": (ctx.name(s.owner) if s.owner else ("Rebels" if s.pop > 0
                                                          else "Unowned"))}
    if level == SHORT:
        gov = ctx.state.governor(s.id)
        d.update(pop=round(s.pop, 3), happy=K.happiness_band(s.happy) if s.pop > 0 else None,
                 trend=s.trend, starport=s.starport, status=K.STATUS_NAMES[s.status],
                 infra=s.infra, hab=K.HAB_NAMES[s.hab], mr=s.mr, ar=s.ar, au=s.au, iu=s.iu,
                 artifacts=sorted(s.artifacts),
                 trade_routes=[ctx.name(e) for e in sorted(s.trade_routes)],
                 leader=gov.name if gov else None,
                 troops=[{"number": t.number, "owner": t.owner, "type": t.type,
                          "posture": POSTURE_NAMES[t.posture]}
                         for t in ctx.state.troops_at(s.id)])
    return d


def remember(e, s, turn: int, short: bool) -> None:
    """Record a sighting of system `s` in empire `e`'s map memory (see the module docstring)."""
    old = e.seen_systems.get(s.id) or {}
    info = {"turn": turn, "name": s.name, "owner": s.owner if s.owner else None}
    if not s.owner:          # empire 0: empty ("unowned") or rebel-held (view.py)
        info["independent"] = "rebels" if s.pop > 0 else "unowned"
    if short:
        info.update(hab=s.hab, mr=bool(s.mr), ar=bool(s.ar), detail_turn=turn)
    elif "hab" in old:
        info.update(hab=old["hab"], mr=old.get("mr", False), ar=old.get("ar", False),
                    detail_turn=old.get("detail_turn", old.get("turn")))
    e.seen_systems[s.id] = info


def mark_area_scans(cover: list[int], my_ships, my_sys, board: int) -> None:
    """Add an empire's area scans to its scan-history rows: each live ship's box of its scan
    factor and each populated own system's box of its scan range (no NPR bonus, A-01).  The one
    place both live recording (`do_scans`) and the backfill (`rebuild_scan_history`) mark."""
    for sc in my_ships:
        scanmask.mark(cover, sc.x, sc.y, sc.stype.scan, board)
    for my in my_sys:
        scanmask.mark(cover, my.x, my.y, my.scan_range, board)


def empire_area_scans(st, eid: int):
    """(ships, populated systems) of empire `eid` that scan, as `do_scans` picks them."""
    return ([s for s in st.live_ships() if s.owner == eid],
            [s for s in st.systems if s.owner == eid and s.pop > 0])


def rebuild_scan_history(states):
    """Scan history rebuilt from stored per-turn states (the DECISIONS G-07 backfill for games
    that predate it).  `states` iterates (turn, GameState) in ascending turn order over the turns
    that are on disk (gaps are fine).  Each state is the game after that turn, which is the game
    as it was when that turn's `do_scans` ran: nothing after the scan phase moves, kills or
    settles anything, and extinction only marks empires that had nothing left to scan with.
    Yields (turn, {empire id: mask}), each mask the union of that empire's OWN area scans over
    every available turn up to and including that one (the same marks `do_scans` makes).  Only an
    empire's own ships and systems ever go into its mask."""
    cover: dict[int, list[int]] = {}
    for turn, st in states:
        row: dict[int, str] = {}
        for e in st.empires.values():
            if e.kind in (HUMAN, NPR):
                rows = cover.setdefault(e.id, [0] * st.board)
                mark_area_scans(rows, *empire_area_scans(st, e.id), st.board)
            if e.id in cover:
                row[e.id] = scanmask.encode(cover[e.id], st.board)
        yield turn, row


def do_scans(ctx: TurnContext) -> None:
    st = ctx.state
    ships = st.live_ships()
    systems = st.systems
    for e in st.empires.values():
        if e.kind not in (HUMAN, NPR):
            continue
        extra = 0                       # no NPR scan bonus (DECISIONS A-01)
        my_ships, my_sys = empire_area_scans(st, e.id)
        cover = scanmask.decode(e.scan_history, st.board)
        mark_area_scans(cover, my_ships, my_sys, st.board)
        e.scan_history = scanmask.encode(cover, st.board)
        ship_lvl: dict[int, str] = {}
        sys_lvl: dict[int, str] = {}
        for sc in my_ships:
            rng_ = sc.stype.scan + extra
            for o in ships:
                if o.owner == e.id:
                    continue
                d = G.distance(sc.x, sc.y, o.x, o.y, st.board)
                if d == 0:
                    ship_lvl[o.number] = SHORT
                elif d <= rng_:
                    ship_lvl[o.number] = _better(ship_lvl.get(o.number), LONG)
            for s in systems:
                if s.owner == e.id:
                    continue
                d = G.distance(sc.x, sc.y, s.x, s.y, st.board)
                if d == 0:
                    sys_lvl[s.id] = SHORT
                elif d <= rng_:
                    sys_lvl[s.id] = _better(sys_lvl.get(s.id), LONG)
        for my in my_sys:
            rng_ = my.scan_range + extra
            for o in ships:
                if o.owner == e.id:
                    continue
                d = G.distance(my.x, my.y, o.x, o.y, st.board)
                if d == 0:
                    ship_lvl[o.number] = SHORT
                elif d <= rng_:
                    ship_lvl[o.number] = _better(ship_lvl.get(o.number), LONG)
            for s in systems:
                if s.owner != e.id and G.distance(my.x, my.y, s.x, s.y, st.board) <= rng_:
                    sys_lvl[s.id] = _better(sys_lvl.get(s.id), LONG)
        for sid, viewer, lvl in ctx.extra_scans:
            if viewer == e.id and systems[sid].owner != e.id:
                sys_lvl[sid] = _better(sys_lvl.get(sid), SHORT if lvl == "short" else LONG)
        for sid, viewer in ctx.ssi:
            if viewer == e.id:
                sys_lvl[sid] = SHORT
        # combat participants see everything at the square (COMBAT_SCAN)
        rep = ctx.res.report(e.id)
        rep.scans["ships"] = [ship_view(ctx, st.ships[n], e.id, lvl)
                              for n, lvl in sorted(ship_lvl.items())]
        rep.scans["systems"] = [system_view(ctx, systems[i], e.id, lvl)
                                for i, lvl in sorted(sys_lvl.items())]
        fleets = {}
        for n in ship_lvl:
            sh = st.ships[n]
            if sh.fleet is not None and sh.fleet in st.fleets and st.fleets[sh.fleet].alive:
                f = st.fleets[sh.fleet]
                rx, ry = ctx.rel_xy(e.id, f.x, f.y)
                fleets.setdefault(f.number, {"name": f.name, "owner": f.owner,
                                             "owner_name": ctx.name(f.owner), "x": rx, "y": ry,
                                             "ships": []})["ships"].append(n)
        rep.scans["fleets"] = list(fleets.values())
        for i, lvl in sys_lvl.items():
            s = systems[i]
            remember(e, s, st.turn, lvl == SHORT)
            if s.owner:
                ctx.make_contact(e.id, s.owner)
        for my in systems:
            if my.owner == e.id:     # your own systems: you know them in full
                remember(e, my, st.turn, True)
        for n in ship_lvl:
            ctx.make_contact(e.id, st.ships[n].owner)


def extinction(ctx: TurnContext) -> None:
    st = ctx.state
    for e in st.empires.values():
        if e.kind not in (HUMAN, NPR):
            continue
        has_ship = any(s.owner == e.id for s in st.live_ships())
        has_sys = any(s.owner == e.id for s in st.systems)
        if not has_ship and not has_sys:
            e.kind = DEAD
            for other in st.empires.values():
                if e.id in other.relations:
                    del other.relations[e.id]
                    if other.kind in (HUMAN, NPR):
                        ctx.res.emit(other.id, "extinction", f"Our Ambassador to the {e.name} "
                                     f"sadly reports their extinction.", "general", race=e.id)
            e.relations.clear()
            ctx.res.emit(e.id, "extinction", "Your race has been wiped out.", "general")
