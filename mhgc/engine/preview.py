"""Production preview: one empire's expected end-of-turn economy (the Production tab).

`production_preview(state, empire, orders, overrides)` runs the real engine code on a copy of the
game that holds ONLY the requesting empire's own objects (`own_copy`), so the projection cannot
depend on, or reveal, anything about other empires.  The stored game is never touched.

What runs, in the turn's order (engine/turn.py):
  (1) the empire's own draft orders that change its economy this turn (SIMULATED below), through
      the real order handlers; then the profile overrides, applied as if a CSP for that system
      ended the draft (production uses whichever profile was set last);
  (2) production (economy.system_production / produce), without trade income;
  (3) feeding and happiness (economy.settle_happiness), and a rebellion if happiness reaches 0
      (that is certain, not random); uprisings and "we love the emperor" days are random and
      only reported as a risk;
  (4) growth (economy.grow);
  (5) maintenance (maintenance.maintenance): SISD, artifact, ship, troop and spy upkeep and
      AUTOSISD, giving the same ledger as the turn report's maintenance listing.

Left out (so the turn can differ): other empires' orders and anything that depends on them (DCT
trade income, gifts received, SL from your systems, enemy spies' unrest, tech gifts and trades),
your own orders that involve another empire (GT, TTNPR, GS, CTT, SL, and loading or unloading away
from your own systems), random events, uprisings and emperor days, and everything after
maintenance (movement, combat, spies).  AUTOSISD takes IUs from randomly chosen systems: the depot
total is exact, but which system's stockpile pays may differ.
"""
from __future__ import annotations

from typing import Iterable, Optional

from ..data import constants as K
from ..data.artifacts import ARTIFACTS, DISPLAY_ORDER
from ..model import INDEPENDENT, Empire, GameState, System, _encode, from_dict
from ..orders import Order
from ..results import TurnResults
from ..rng import Rng
from . import economy, maintenance
from .context import OrderError, TurnContext
from .orders_exec import _own_system, check_artifact_install, execute

# Orders whose effect on this turn's economy comes only from the empire's own objects.
SIMULATED = frozenset({
    "CSP", "CAP", "CAPN", "SISD", "CI", "BCU", "BS", "BI", "DI", "BT", "DT", "BSP", "DSP",
    "NSY", "TP", "SR", "DCT", "SCT", "ML", "MLF", "PLOI", "PT", "CRP", "AUTOSISD", "NOAUTOSISD",
    "DS", "SS", "WTP", "WTPF", "GE", "DF", "CF", "CFXY", "AF", "LF", "MGF", "FR",
})
# Cargo orders: simulated only when the ship or fleet is at one of the empire's own systems.
CARGO = frozenset({"L", "U", "UG", "FL", "FU", "FUG"})
# Orders that would change this turn's economy but involve another empire: not simulated.
INVOLVE_OTHERS = frozenset({"GT", "TTNPR", "GS", "CTT", "SL"})
KEYS = ("au", "iu", "eu")

LEDGER_LABELS = {
    "initial": "Start of turn",
    "purchases": "Spent by orders (builds, techs, other order costs)",
    "salvage": "Salvage refunds (SS, SCT)",
    "gifts_out": "Given away (GE)",
    "production": "EU produced by systems",
    "sisd": "IUs moved to the depot (SISD)",
    "autosisd": "Autosupply (AUTOSISD)",
    "artifact": "Artifact upkeep",
    "ship": "Ship upkeep",
    "ct": "Combat troop upkeep",
    "spy": "Spy upkeep",
    "final": "End of turn",
}

NOTES = [
    "Estimate, before random events and combat.",
    "Includes your own draft orders' costs, production, feeding, growth and maintenance (SISD, "
    "AUTOSISD, artifact, ship, troop and spy upkeep).",
    "Leaves out DCT trade income, anything other empires do (gifts, SL, spies), your orders that "
    "involve another empire (GT, TTNPR, GS, CTT, SL, cargo away from your systems), uprisings, "
    "emperor days, random events, movement and combat.",
    "AUTOSISD picks the systems that pay at random: the depot total is exact, a system's own IU "
    "stockpile may differ.",
]


def own_copy(state: GameState, eid: int) -> GameState:
    """A playable copy of the game holding only `eid`'s own objects.  Other systems are blank
    (unowned, empty, named as `eid` last saw them or not at all); contacted empires are empty
    shells with only the name and kind `eid` can see; nobody else's ships, troops, leaders or
    spies exist."""
    me = state.empires[eid]
    systems = []
    for s in state.systems:
        if s.owner == eid:
            systems.append(_encode(s))
        else:
            seen = me.seen_systems.get(s.id) or {}
            systems.append(_encode(System(s.id, seen.get("name") or f"?{s.id}", s.x, s.y)))
    empires = {"0": _shell(0, K.INDEPENDENT_NAME, INDEPENDENT), str(eid): _encode(me)}
    for oid in me.relations:
        o = state.empires.get(oid)
        if o is not None and oid not in (0, eid):
            empires[str(oid)] = _shell(oid, o.name, o.kind)

    def mine(table):
        return {str(k): _encode(v) for k, v in table.items() if v.owner == eid}

    copy = from_dict({"name": state.name, "seed": 0, "turn": state.turn, "empires": empires,
                      "systems": systems, "ships": mine(state.ships),
                      "fleets": mine(state.fleets), "troops": mine(state.troops),
                      "leaders": mine(state.leaders), "spies": mine(state.spies),
                      "next_leader_id": state.next_leader_id, "winner": None,
                      "winners_vp": {}, "npr_state": {}})
    for s in copy.systems:
        s.trade_routes.clear()           # DCT income depends on other empires: left out
    return copy


def _shell(eid: int, name: str, kind: str) -> dict:
    return _encode(Empire(eid, name, kind=kind, eu=0, iu_depot=0, autosisd=False))


def _at_own_system(st: GameState, eid: int, o: Order) -> bool:
    if o.code in ("FL", "FU", "FUG"):
        f = st.fleet_named(getattr(o, "fleet", None) or "", eid)
        if f is None:
            return True                  # let the handler report the error
        x, y = f.x, f.y
    else:
        sh = st.ship(getattr(o, "ship", None) or -1)
        if sh is None or sh.owner != eid:
            return True
        x, y = sh.x, sh.y
    s = st.system_at(x, y)
    return s is not None and s.owner == eid


def check_split(au, iu, eu) -> tuple[int, int, int]:
    """Validate a profile as the CSP order does (each 10-100, total 100)."""
    from ..orders import make_order
    o = make_order("CSP", system="X", au=au, iu=iu, eu=eu)
    return o.au, o.iu, o.eu


def _prepare(state: GameState, eid: int, orders: Iterable[Order],
             overrides: dict[int, tuple[int, int, int]]):
    """Steps (1) and the overrides: the own copy with the draft's own orders run, as production
    will see it.  Returns (st, ctx, start, draft_csp, base, skipped, failed)."""
    st = own_copy(state, eid)
    st.turn += 1
    ctx = TurnContext(state=st, rng=Rng(0, st.turn, "preview"), res=TurnResults(st.turn),
                      checking=True)
    ctx.empire_order = [eid]
    e = st.empires[eid]
    ctx.start_eu[eid] = e.eu
    start = {s.id: (s.name, s.pop, s.happy) for s in st.systems if s.owner == eid}
    draft_csp = set()

    # (1) own orders
    skipped, failed = [], []
    for i, o in enumerate(orders):
        text = o.line or o.to_text()
        if o.code in CARGO and not _at_own_system(st, eid, o):
            skipped.append({"index": i, "text": text,
                            "reason": "cargo away from your own systems is not projected"})
            continue
        if o.code not in SIMULATED and o.code not in CARGO:
            if o.code in INVOLVE_OTHERS:
                skipped.append({"index": i, "text": text,
                                "reason": "involves another empire, so it is not projected"})
            continue
        try:
            r = execute(ctx, eid, o, i)
        except Exception as exc:         # a handler that needs data the copy lacks
            skipped.append({"index": i, "text": text, "reason": f"not projected ({exc})"})
            continue
        if not r.ok:
            failed.append({"index": i, "text": text, "error": r.error})
        elif o.code == "CSP":
            s = st.system_named(o.system)
            if s is not None:
                draft_csp.add(s.id)
    for s in st.systems:                 # nothing outside the empire can be projected
        if s.owner == eid and s.id not in start:
            s.owner, s.pop = 0, 0.0

    base = {s.id: (s.csp_au, s.csp_iu, s.csp_eu) for s in st.systems if s.owner == eid}
    for sid, split in overrides.items():
        s = st.systems[sid]
        if s.owner == eid:
            s.csp_au, s.csp_iu, s.csp_eu = split
    had_pop = {s.id for s in st.systems if s.pop > 0}
    from .turn import depopulation
    depopulation(ctx, had_pop)
    return st, ctx, start, draft_csp, base, skipped, failed


def production_tweak(state: GameState, eid: int, orders: Iterable[Order] = (),
                     overrides: Optional[dict[int, tuple[int, int, int]]] = None,
                     systems: Optional[Iterable[int]] = None, max_delta: int = 3) -> dict:
    """The split tweak for empire `eid`'s systems (Dave 2026-11-18): for each own populated
    system (or those in `systems`), economy.tweak_split on the profile production would use
    (the draft's CSPs, then `overrides`), with the system as production will see it after the
    draft's own orders (BI, BSP, BT, ...).  Runs on the same own-only copy as the preview, so it
    depends on and reveals nothing of other empires; nothing is stored."""
    overrides = overrides or {}
    st, ctx, start, _, _, _, _ = _prepare(state, eid, orders, overrides)
    want = None if systems is None else {int(x) for x in systems}
    out = []
    for s in st.systems:
        if s.id not in start or (want is not None and s.id not in want):
            continue
        cur = (s.csp_au, s.csp_iu, s.csp_eu)
        row = {"id": s.id, "name": start[s.id][0], "split": dict(zip(KEYS, cur))}
        if s.owner != eid or s.pop <= 0:
            row.update({"suggestion": dict(zip(KEYS, cur)), "optimal": True, "gain": 0,
                        "moved": 0, "before": dict(zip(KEYS, (0, 0, 0))),
                        "after": dict(zip(KEYS, (0, 0, 0))), "changes": []})
            out.append(row)
            continue
        t = economy.tweak_split(economy.split_context(ctx, s), cur, max_delta)
        row.update({
            "suggestion": dict(zip(KEYS, t["split"])), "optimal": t["optimal"],
            "gain": t["gain"], "moved": t["moved"],
            "before": dict(zip(KEYS, t["before"])), "after": dict(zip(KEYS, t["after"])),
            "changes": [{"key": k, "from": a, "to": b, "out_from": x, "out_to": y}
                        for k, a, b, x, y in zip(KEYS, cur, t["split"], t["before"],
                                                 t["after"]) if a != b or x != y]})
        out.append(row)
    return {"turn": st.turn, "max_delta": max_delta, "systems": out,
            "gain": sum(r["gain"] for r in out)}


def production_preview(state: GameState, eid: int, orders: Iterable[Order] = (),
                       overrides: Optional[dict[int, tuple[int, int, int]]] = None) -> dict:
    """The Production tab's projection for empire `eid` (see the module docstring)."""
    overrides = overrides or {}
    st, ctx, start, draft_csp, base, skipped, failed = _prepare(state, eid, orders, overrides)
    e = st.empires[eid]

    # flags that look at the systems as an install order at the end of the draft would see them
    flags = {}
    for s in st.systems:
        if s.owner != eid:
            continue
        avail, blocked = [], []
        if s.status != K.INTERDICTED:
            for key in DISPLAY_ORDER:
                art = ARTIFACTS[key]
                if art.tech not in e.techs or s.has(key):
                    continue
                m = ctx.cost_mult(s)
                item = {"key": key, "name": art.name, "iu": art.iu_cost * m, "eu": art.eu_cost * m,
                        "maint_eu": art.maint_eu}
                try:
                    _own_system(ctx, eid, s.name, "nonint")
                    check_artifact_install(ctx, eid, s, art)
                    avail.append(item)
                except OrderError as exc:
                    blocked.append({**item, "reason": str(exc)})
        flags[s.id] = {"infra": s.infra, "pop_at_production": s.pop,
                       "insufficient_infra": s.pop > 0 and s.infra < s.pop,
                       "tech_available": avail, "tech_blocked": blocked}

    # (2) production
    economy.produce(ctx)
    # (3) feeding and happiness (no random uprisings or emperor days)
    risks = {}
    for s in st.systems:
        if s.pop <= 0:
            continue
        economy.settle_happiness(ctx, s)
        risk = economy.unrest_risk(s, st.empires[s.owner].kind)
        if risk is not None:
            risks[s.id] = {"kind": risk[0], "chance": risk[1]}
            if risk[0] == "rebellion":
                economy.rebellion(ctx, s)
    # (4) growth
    economy.grow(ctx)
    e.systems_captured = 0
    # (5) maintenance
    maintenance.maintenance(ctx)

    rows = []
    for s in st.systems:
        if s.id not in start:
            continue
        name0, pop0, happy0 = start[s.id]
        ec = ctx.econ[s.id]
        f = flags.get(s.id) or {"infra": s.infra, "pop_at_production": s.pop,
                                "insufficient_infra": False, "tech_available": [],
                                "tech_blocked": []}
        b = base.get(s.id, (s.csp_au, s.csp_iu, s.csp_eu))
        used = (s.csp_au, s.csp_iu, s.csp_eu)
        rows.append({
            "id": s.id, "name": name0, "order_name": s.name,
            "pop": pop0, "pop_after": round(s.pop, 4),
            "happy": happy0, "band": K.happiness_band(happy0) if pop0 > 0 else None,
            "happy_after": round(s.happy, 4),
            "band_after": K.happiness_band(s.happy) if s.pop > 0 else None,
            "trend_after": s.trend, "status": K.STATUS_NAMES[s.status],
            "base": {"au": b[0], "iu": b[1], "eu": b[2]},
            "split": {"au": used[0], "iu": used[1], "eu": used[2]},
            "overridden": s.id in overrides and tuple(overrides[s.id]) != tuple(b),
            "draft_csp": s.id in draft_csp,
            "production": {"au": ec.prod_au, "iu": ec.prod_iu, "eu": ec.prod_eu},
            "eaten": ec.eaten, "au_after": s.au, "iu_after": s.iu,
            "infra": f["infra"], "insufficient_infra": f["insufficient_infra"],
            "tech_available": f["tech_available"], "tech_blocked": f["tech_blocked"],
            "risk": risks.get(s.id), "lost": s.owner != eid,
        })

    ledger = ctx.res.report(eid).maintenance
    summary: dict[str, dict] = {}
    for ln in ledger:
        k = ln["kind"]
        if k in ("initial", "final"):
            continue
        g = summary.setdefault(k, {"kind": k, "label": LEDGER_LABELS.get(k, ln["text"]),
                                   "iu": 0, "eu": 0, "system_iu": 0, "count": 0})
        g["iu"] += ln.get("iu", 0)
        g["eu"] += ln.get("eu", 0)
        g["system_iu"] += ln.get("system_iu", 0)
        g["count"] += 1
    first = next((ln for ln in ledger if ln["kind"] == "initial"), {"iu": 0, "eu": 0})
    last = next((ln for ln in ledger if ln["kind"] == "final"), {"iu": e.iu_depot, "eu": e.eu})
    lost = [{"kind": ev.kind, "text": ev.text} for ev in ctx.res.report(eid).events
            if ev.kind in ("ship_demobilized", "troop_demobilized", "spy_lost", "artifact_lost",
                           "rebellion", "militia_disbanded")]
    tot = {k: sum(r["production"][k] for r in rows) for k in ("au", "iu", "eu")}
    return {
        "turn": st.turn,
        "systems": rows,
        "totals": {
            "pop": round(sum(r["pop"] for r in rows), 4),
            "pop_after": round(sum(r["pop_after"] for r in rows if not r["lost"]), 4),
            "production": tot, "eaten": sum(r["eaten"] for r in rows),
            "au_after": sum(r["au_after"] for r in rows if not r["lost"]),
            "iu_after": sum(r["iu_after"] for r in rows if not r["lost"]),
        },
        "empire": {"eu_start": first["eu"], "eu_after": last["eu"],
                   "depot_start": first["iu"], "depot_after": last["iu"],
                   "autosisd": e.autosisd, "ledger": list(summary.values()), "losses": lost},
        "orders": {"failed": failed, "skipped": skipped},
        "notes": NOTES,
    }
