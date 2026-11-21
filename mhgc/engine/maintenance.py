"""Turn phase 5: maintenance (rules:479-486, 2001-2010, chart 3063; gcmaint.c, gcrun.c:766-833).

Order: trade income, supply-depot transfers (SISD), artifact upkeep per system, ships, combat
troops, spies; then the militia cap and the entrenchment countdown.  Anything that cannot be paid
for is destroyed (rules:482, 1310).  Each empire gets a ledger the UI can show as the old
MAINTENANCE LISTING.
"""
from __future__ import annotations

from .. import geometry as G
from ..data import constants as K
from ..data.artifacts import ARTIFACTS, MAINT_ORDER
from ..model import INDEPENDENT
from .context import TurnContext
from .orders_exec import destroy_ship


def _ledger(ctx, eid, kind, text, iu=0, eu=0, **data):
    """One ledger line.  `iu` is a change to the IU supply depot and `eu` to the EU stockpile,
    so "initial" plus every line's iu/eu gives "final".  IUs that orders take from or return to
    system stockpiles are not depot IUs; those lines carry them as `system_iu` instead."""
    ctx.res.report(eid).maintenance.append({"kind": kind, "text": text, "iu": iu, "eu": eu,
                                            **data})


def maintenance(ctx: TurnContext) -> None:
    st = ctx.state
    for e in st.empires.values():
        if e.kind == INDEPENDENT:
            continue
        _ledger(ctx, e.id, "initial", "Start of turn: IU supply depot and EU stockpile",
                e.iu_depot, ctx.start_eu.get(e.id, e.eu))
        # What this empire's orders spent and got back (every spending order, DECISIONS
        # Dave 2026-11-12).  System IUs are shown, but they are not depot IUs.
        if ctx.purch_eu[e.id] or ctx.purch_iu[e.id]:
            _ledger(ctx, e.id, "purchases", "Spent by orders (builds, techs and other "
                    "order costs)", 0, -ctx.purch_eu[e.id],
                    system_iu=-ctx.purch_iu[e.id])
        if ctx.refund_eu[e.id] or ctx.refund_iu[e.id]:
            _ledger(ctx, e.id, "salvage", "Salvage refunds (SS, SCT)", 0, ctx.refund_eu[e.id],
                    system_iu=ctx.refund_iu[e.id])
        if ctx.gift_out_eu[e.id]:
            _ledger(ctx, e.id, "gifts_out", "Given away or paid for tech gifts and trades (GE, "
                    "GT, TTNPR)", 0, -ctx.gift_out_eu[e.id])
        if ctx.gift_in_eu[e.id]:
            _ledger(ctx, e.id, "gifts_in", "EU received as gifts", 0, ctx.gift_in_eu[e.id])
        if ctx.eu_prod[e.id]:
            _ledger(ctx, e.id, "production", "EU produced by systems", 0, ctx.eu_prod[e.id])
        # Trade income for everyone (the C skipped NMC players, DECISIONS B-41).
        if ctx.trade_eu[e.id]:
            e.eu += ctx.trade_eu[e.id]
            _ledger(ctx, e.id, "trade", "EU gathered in trade", 0, ctx.trade_eu[e.id])

    # ---- SISD and artifact upkeep, per populated system in board order
    for s in st.systems:
        if s.pop <= 0 or s.owner == 0:
            continue
        e = st.empires[s.owner]
        ec = ctx.econ[s.id]
        if ec.sisd and ec.sisd_owner == s.owner:
            amt = min(ec.sisd, s.iu)
            s.iu -= amt
            e.iu_depot += amt
            _ledger(ctx, e.id, "sisd", f"IUs moved to the supply depot from {s.name}", amt, 0,
                    system=s.id)
        for key in MAINT_ORDER:
            if key not in s.artifacts:
                continue
            cost = ARTIFACTS[key].maint_eu
            if cost == 0:
                continue
            if e.eu < cost:
                s.artifacts.discard(key)
                ctx.res.emit(e.id, "artifact_lost",
                             f"Not enough EUs to maintain the {ARTIFACTS[key].name} on "
                             f"{s.name} ({cost} EU needed), so it was destroyed.",
                             "maintenance", s.id, artifact=key)
            else:
                e.eu -= cost
                _ledger(ctx, e.id, "artifact", f"Upkeep: {ARTIFACTS[key].name} on {s.name}", 0,
                        -cost, system=s.id, artifact=key)

    # ---- ships
    owned_systems: dict[int, list] = {}
    for s in st.systems:
        if s.owner:
            owned_systems.setdefault(s.owner, []).append(s)
    for sh in list(st.ships.values()):
        if not sh.alive or sh.owner == 0:
            continue
        e = st.empires[sh.owner]
        mine = owned_systems.get(sh.owner, [])
        best, bd = None, 10 ** 6
        for s in mine:
            d = G.distance(sh.x, sh.y, s.x, s.y, st.board)
            if d < bd:
                best, bd = s, d
        if best is not None:
            sh.home = best.id
        if best is not None and bd == 0:
            iu, eu = K.SHIP_MAINT_AT_OWN_SYSTEM
        elif (best is None or bd > K.FAR_TURNS * sh.stype.move) and not sh.stype.is_scout_class:
            iu, eu = K.SHIP_MAINT_FAR
        else:
            iu, eu = K.SHIP_MAINT_NORMAL
        if e.iu_depot < iu and e.autosisd:
            strip_ius(ctx, sh.owner, iu - e.iu_depot)
        if e.iu_depot < iu or e.eu < eu:
            destroy_ship(ctx, sh)
            short = (f"{iu} IU from the supply depot" if e.iu_depot < iu else f"{eu} EU")
            ctx.res.emit(e.id, "ship_demobilized",
                         f"Not enough {'IUs in the supply depot' if e.iu_depot < iu else 'EUs'}"
                         f" to maintain {sh.stype.name} {sh.number} ({short} needed), so it "
                         f"was demobilized.", "maintenance", ship=sh.number)
            continue
        e.iu_depot -= iu
        e.eu -= eu
        _ledger(ctx, e.id, "ship", f"Upkeep: ship {sh.number} ({sh.stype.name})", -iu, -eu,
                ship=sh.number)

    # ---- combat troops
    for t in list(st.troops.values()):
        if not t.alive or t.owner == 0:
            continue
        e = st.empires[t.owner]
        cost = t.ttype.maint_eu
        if e.eu < cost:
            t.alive = False
            ctx.res.emit(e.id, "troop_demobilized",
                         f"Not enough EUs to maintain {t.ttype.name} {t.number} ({cost} EU "
                         f"needed), so it was demobilized.", "maintenance", ct=t.number)
            continue
        e.eu -= cost
        _ledger(ctx, e.id, "ct", f"Upkeep: troop {t.number} ({t.ttype.name})", 0, -cost,
                ct=t.number)

    # ---- militia cap (gcrun.c:766-792; rules:612)
    for s in st.systems:
        mil = [t for t in st.troops_at(s.id) if t.type == "M" and t.owner == s.owner
               and s.owner != 0]
        excess = len(mil) - int(s.pop)
        for t in mil[:max(0, excess)][::-1]:
            t.alive = False
            ctx.res.emit(s.owner, "militia_disbanded",
                         f"Militia {t.number} on {s.name} was disbanded: a system can support"
                         f" only one militia per population point.",
                         "maintenance", s.id)

    # ---- entrenchment countdown (gcrun.c:796-807): E3 -> E2 -> E1 -> E
    nxt = {"E3": "E2", "E2": "E1", "E1": "E"}
    for t in st.troops.values():
        if t.alive and t.posture in nxt:
            t.posture = nxt[t.posture]

    # ---- spies (gcrun.c:815-833)
    for sp in list(st.spies.values()):
        if not sp.alive:
            continue
        e = st.empires[sp.owner]
        if e.eu < K.SPY_MAINT:
            sp.alive = False
            ctx.res.emit(e.id, "spy_lost", f"Not enough EUs to maintain spy {sp.number} "
                         f"({K.SPY_MAINT} EU needed), so it was lost.", "maintenance",
                         spy=sp.number)
            continue
        e.eu -= K.SPY_MAINT
        _ledger(ctx, e.id, "spy", f"Upkeep: spy {sp.number}", 0, -K.SPY_MAINT, spy=sp.number)

    for e in st.empires.values():
        if e.kind != INDEPENDENT:
            _ledger(ctx, e.id, "final", "End of turn: IU supply depot and EU stockpile",
                    e.iu_depot, e.eu)


def strip_ius(ctx: TurnContext, eid: int, needed: int) -> None:
    """AUTOSISD (rules:2561-2563; gcrun.c:1459): take IUs from randomly chosen NORMAL systems.
    Only the shortfall is moved (the C moved the whole cost each time, DECISIONS B-42)."""
    st = ctx.state
    cands = [s for s in st.systems if s.owner == eid and s.status == K.NORMAL and s.iu > 0]
    ctx.rng.shuffle(cands)
    e = st.empires[eid]
    for s in cands:
        if needed <= 0:
            break
        amt = min(needed, s.iu)
        s.iu -= amt
        e.iu_depot += amt
        needed -= amt
        _ledger(ctx, eid, "autosisd",
                f"Autosupply (AUTOSISD): IUs moved to the depot from {s.name}", amt, 0,
                system=s.id)
