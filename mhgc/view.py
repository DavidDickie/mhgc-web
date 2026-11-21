"""Per-player read model: what one empire is allowed to see, as plain JSON-ready data.

`view(state, results, empire)` is the ONLY thing the web layer sends a browser about the game
world.  It is built from whitelisted fields, never from `model.to_dict`, so new state fields stay
private until someone adds them here on purpose.

What goes in
- The empire's own objects in full: systems (with this turn's production), ships (cargo and troops
  aboard), fleets (members, admiral), troops, leaders, spies, techs, money, preferences, stats.
- Foreign objects only as this empire's scans saw them this turn (`results.reports[e].scans`, built
  by engine/scans.py at short or long range), plus the map memory `Empire.seen_systems` (name and
  owner when last seen; system positions are fixed, so a seen system's position is known; and
  habitability and MR/AR as of the last short scan, with that turn).
- The empire's own scan history (`Empire.scan_history`): every square it has ever had inside one
  of its scans, as a base64 bitmask re-based to relative coordinates (mhgc/scanmask).
- Foreign troops on the ground at the empire's own systems (the owner sees who stands on its world).
- Other empires only once contacted: id, name, kind (rules:240-245: you can tell NPRs once you have
  contact) and THIS empire's stance towards them.  Never their stance towards us: rules:735-737,
  "there is no way to determine whether the other player has ordered an alliance with you".
- This turn's results for this empire only: order outcomes, events, its combats (the logs of
  battles it took part in or that hit its systems), maintenance, economy, stats and the MESSAGE
  orders addressed to it.

Every coordinate is relative to the empire's home (home = the board centre: 50,50 on the classic
100x100 board, 37,37 on 75x75, 25,25 on 50x50).  Absolute coordinates, including
the empire's own home position, are never sent.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Optional

from .data import constants as K
from .data.troops import POSTURE_NAMES
from .geometry import to_rel
from . import scanmask
from .model import GameState, HUMAN, INDEPENDENT, NPR, DEAD

VIEW_VERSION = 1


def _details(info: dict) -> dict:
    """Habitability and MR/AR from map memory, as of the last short scan (or nothing)."""
    if not info or info.get("hab") not in K.HAB_NAMES:
        return {}
    return {"hab": K.HAB_NAMES[info["hab"]], "hab_value": info["hab"], "mr": bool(info.get("mr")),
            "ar": bool(info.get("ar")), "details_turn": info.get("detail_turn", info.get("turn"))}


# Empire 0 holds both never-settled (or emptied) systems and systems that rebelled.  The UI
# shows the first as "Unowned" and the second as "Rebels" (Dave 2026-11-12); troops owned by
# empire 0 are always "Rebels".
OWNER_LABELS = {"unowned": "Unowned", "rebels": "Rebels"}


def independent_kind(pop: float) -> str:
    return "rebels" if pop and pop > 0 else "unowned"


def _results_dict(results: Any) -> Optional[dict]:
    if results is None:
        return None
    if isinstance(results, dict):
        return results
    return dataclasses.asdict(results)


def _report_of(res: Optional[dict], eid: int) -> dict:
    if not res:
        return {}
    reps = res.get("reports") or {}
    return reps.get(eid) or reps.get(str(eid)) or {}


def view(state: GameState, results: Any, empire: int) -> dict:
    """The fog-of-war view of `state` (after the turn in `results`) for empire id `empire`."""
    st = state
    me = st.empires[empire]
    hx, hy = me.home_x, me.home_y

    def rel(x: int, y: int) -> dict:
        rx, ry = to_rel(x, y, hx, hy, st.board)
        return {"x": rx, "y": ry}

    def ename(eid: Optional[int]) -> Optional[str]:
        if eid is None:
            return None
        e = st.empires.get(eid)
        return e.name if e else None

    res = _results_dict(results)
    rep = _report_of(res, empire)

    # ---- own objects -----------------------------------------------------------------------
    econ_sys = (rep.get("economy") or {}).get("systems") or {}
    my_systems = []
    for s in st.systems:
        if s.owner != empire:
            continue
        gov = st.governor(s.id)
        d = {"id": s.id, "name": s.name, **rel(s.x, s.y), "pop": round(s.pop, 3),
             "happy": round(s.happy, 4),
             "happy_band": K.happiness_band(s.happy) if s.pop > 0 else None,
             "trend": s.trend, "hab": K.HAB_NAMES[s.hab], "hab_value": s.hab, "mr": s.mr,
             "ar": s.ar, "infra": s.infra, "status": K.STATUS_NAMES[s.status],
             "starport": s.starport, "au": s.au, "iu": s.iu,
             "profile": {"au": s.csp_au, "iu": s.csp_iu, "eu": s.csp_eu},
             "au_release": {"mode": s.au_mode, "value": s.au_value},
             "artifacts": sorted(s.artifacts),
             "trade_routes": [{"race": r, "name": ename(r)} for r in sorted(s.trade_routes)],
             "governor": gov.name if gov is not None and gov.owner == empire else None,
             "scan_range": s.scan_range if s.pop > 0 else 0,
             "troops": [{"number": t.number, "owner": t.owner, "owner_name": ename(t.owner),
                         "type": t.type, "posture": t.posture,
                         "posture_name": POSTURE_NAMES[t.posture]}
                        for t in st.troops_at(s.id)],
             "production": econ_sys.get(s.id) or econ_sys.get(str(s.id))}
        my_systems.append(d)

    fleet_names = {f.number: f.name for f in st.fleets.values() if f.alive and f.owner == empire}
    my_ships = []
    for sh in st.ships.values():
        if not sh.alive or sh.owner != empire:
            continue
        d = {"number": sh.number, "type": sh.type, "class": sh.stype.name, **rel(sh.x, sh.y),
             "from": rel(sh.ox, sh.oy), "dest": rel(sh.dx, sh.dy), "order": sh.order,
             "target": sh.target, "dest_system": sh.dest_system, "posture": sh.posture,
             "role": sh.role, "fleet": fleet_names.get(sh.fleet), "home_system": sh.home,
             "built_turn": sh.built_turn, "scan": sh.stype.scan, "move": sh.stype.move,
             "cargo_capacity": sh.stype.cargo}
        if sh.stype.cargo:
            d["cargo"] = {"AU": sh.cargo_au, "IU": sh.cargo_iu, "POP": sh.cargo_pop,
                          "CT": [t.number for t in st.troops_aboard(sh.number)]}
            d["cargo_used"] = st.cargo_points_used(sh)
        my_ships.append(d)

    my_fleets = []
    for f in st.fleets.values():
        if not f.alive or f.owner != empire:
            continue
        adm = st.admiral(f.number)
        my_fleets.append({
            "number": f.number, "name": f.name, **rel(f.x, f.y), "from": rel(f.ox, f.oy),
            "dest": rel(f.dx, f.dy), "order": f.order, "target": f.target,
            "dest_system": f.dest_system, "posture": f.posture, "role": f.role,
            "ro": {"gc": f.ro_gc, "rd": f.ro_rd, "role": f.ro_role} if f.role == "RO" else None,
            "speed": f.speed if f.speed is not None else "A",
            "admiral": adm.name if adm is not None and adm.owner == empire else None,
            "ships": sorted(s.number for s in st.fleet_ships(f.number))})

    my_troops = [{"number": t.number, "type": t.type, "system": t.system, "ship": t.ship,
                  "posture": t.posture, "posture_name": POSTURE_NAMES[t.posture],
                  "built_turn": t.built_turn}
                 for t in st.troops.values() if t.alive and t.owner == empire]

    my_leaders = [{"id": ld.id, "name": ld.name, "mgmt": ld.mgmt, "eng": ld.eng,
                   "combat": ld.combat, "intel": ld.intel, "social": ld.social, "age": ld.age,
                   "renamed": ld.renamed, "status": ld.status, "system": ld.system,
                   "fleet": fleet_names.get(ld.fleet) if ld.fleet is not None else None,
                   "transit": ld.transit, "description": ld.description}
                  for ld in st.leaders.values() if ld.alive and ld.owner == empire]

    my_spies = [{"number": sp.number, "system": sp.system, "transit": sp.transit,
                 "mission": sp.mission, "mission_arg": sp.mission_arg}
                for sp in st.spies.values() if sp.alive and sp.owner == empire]

    # ---- other empires: contacted only, and only our stance ---------------------------------
    races = []
    for oid, stance in sorted(me.relations.items()):
        o = st.empires.get(oid)
        if o is None:
            continue
        kind = {HUMAN: "player", NPR: "npr", INDEPENDENT: "independent",
                DEAD: "extinct"}.get(o.kind, o.kind)
        races.append({"id": oid, "name": o.name, "kind": kind, "our_stance": stance,
                      "deny_trade": me.deny_trade.get(oid), "split_trade": me.split_trade.get(oid)})

    # ---- map memory -------------------------------------------------------------------------
    known = []
    for sid, info in sorted(me.seen_systems.items()):
        if not 0 <= sid < len(st.systems):
            continue
        s = st.systems[sid]
        owner = info.get("owner")
        via = info.get("via", "scan")
        kind = None
        if not owner and via == "scan":
            # owner 0 when last seen: the scan recorded whether it was empty or rebel-held
            # (memories from before 2026-11-12 fall back to the system as it is now)
            kind = info.get("independent") or independent_kind(s.pop if s.owner == 0 else 0)
        known.append({"id": sid, **rel(s.x, s.y), "name": info.get("name"), "owner": owner,
                      "owner_name": OWNER_LABELS[kind] if kind else
                      (ename(owner) if owner else None),
                      "owner_kind": kind,
                      "last_seen": info.get("turn"), "via": via,
                      "mine": s.owner == empire, **_details(info)})

    # ---- this turn's scans (already relative and filtered by engine/scans.py) ---------------
    scans = rep.get("scans") or {}
    scan_systems = []
    for d in scans.get("systems") or []:
        d = dict(d)
        s = st.systems[d["id"]] if 0 <= d.get("id", -1) < len(st.systems) else None
        if d.get("owner") in (0, None) and s is not None and s.owner == 0:
            # owner 0 is both "never settled / emptied" and "rebelled".  A short scan knows the
            # population; a long scan shows owners (rules) and this is an owner fact.
            pop = d["pop"] if d.get("pop") is not None else s.pop
            d["owner"] = 0
            d["owner_kind"] = independent_kind(pop)
            d["owner_name"] = OWNER_LABELS[d["owner_kind"]]
        if d.get("level") == "short" and d.get("hab") is not None:
            d["hab_value"] = next(k for k, v in K.HAB_NAMES.items() if v == d["hab"])
        elif d.get("level") == "long":
            # a long scan shows only owner, name and position (rules:1174); what the last short
            # scan saw is remembered and stays known (Dave 2026-11-13)
            d.update(_details(me.seen_systems.get(d["id"]) or {}))
        scan_systems.append(d)
    contacts = []
    for s in scans.get("ships") or []:
        contacts.append(s)

    # ---- this turn's results for this empire only -------------------------------------------
    combat_ids = set(rep.get("combats") or [])
    combats = []
    for c in (res or {}).get("combats") or []:
        if c.get("id") not in combat_ids:
            continue
        c = dict(c)
        c.update(rel(c.pop("x"), c.pop("y")))
        c["participant_names"] = {str(p): ename(p) for p in c.get("participants", [])}
        combats.append(c)

    winner = st.winner
    return {
        "view_version": VIEW_VERSION,
        "game": {"name": st.name, "turn": st.turn,
                 "winner": winner, "winner_name": ename(winner) if winner is not None else None,
                 "vp_to_win": K.VICTORY_POINTS, "board": st.board,
                 "size": sum(1 for e in st.empires.values() if e.id != 0),
                 "bins": st.bins, "empty_bins": [list(b) for b in st.empty_bins]},
        "empire": {"id": me.id, "name": me.name, "kind": me.kind,
                   "home": {"x": st.board // 2, "y": st.board // 2},
                   "eu": me.eu, "iu_depot": me.iu_depot, "techs": sorted(me.techs),
                   "future_tech": me.future_tech, "renamed": me.renamed,
                   "autosisd": me.autosisd, "aomt": me.aomt,
                   "unranked": me.id in (state.unranked or ()), "stats": dict(me.stats),
                   "ranks": dict(me.ranks), "vp": me.vp},
        "races": races,
        "systems": my_systems,
        "ships": my_ships,
        "fleets": my_fleets,
        "troops": my_troops,
        "leaders": my_leaders,
        "spies": my_spies,
        "known_systems": known,
        "scan_history": {"encoding": f"base64 bitmask, bit y*{st.board}+x, LSB first",
                         "data": scanmask.to_relative(me.scan_history, hx, hy, st.board)},
        "scans": {"ships": contacts, "fleets": list(scans.get("fleets") or []),
                  "systems": scan_systems},
        "results": {
            "turn": (res or {}).get("turn", st.turn),
            "orders": list(rep.get("orders") or []),
            "events": list(rep.get("events") or []),
            "messages": list(rep.get("messages") or []),
            "maintenance": list(rep.get("maintenance") or []),
            "economy": {k: v for k, v in (rep.get("economy") or {}).items() if k != "systems"},
            "stats": rep.get("stats") or {},
            "combats": combats,
        },
    }
