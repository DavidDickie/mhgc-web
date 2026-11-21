"""Statistics, ranks, victory points and the victory check (rules:197-220, 1107-1127;
gcrun.c:1271-1418).

Ranks and the stat-bonus victory points are over every live race, humans and computer empires
alike, at every game size, and a computer empire can win (Dave 2026-11-15, DECISIONS A-06; this
supersedes rules:238-239, under which NPRs were not ranked and could not win).  One exception
(Dave 2026-11-19, DECISIONS W-28): the races in `state.unranked` (the host's own race when another
human plays) are left out of the ranking pool, get no stat-bonus VP and cannot win.  Each empire still
sees only its own ranks (view.py, its report's stats) unless a spy brings back another's (SON)."""
from __future__ import annotations

from ..data import constants as K
from ..data.ships import NONWAR_CLASSES
from ..data.techs import tech_vp
from ..model import HUMAN, NPR
from .context import TurnContext


def compute_stats(ctx: TurnContext) -> None:
    st = ctx.state
    stats: dict[int, dict[str, float]] = {}
    for e in st.empires.values():
        if e.kind not in (HUMAN, NPR):
            continue
        d = dict.fromkeys(K.STAT_NAMES, 0.0)
        d["GNP"] = ctx.eu_prod[e.id] + ctx.trade_eu[e.id] + ctx.iu_prod[e.id] + ctx.au_prod[e.id]
        d["NNP"] = ctx.eu_prod[e.id] + ctx.trade_eu[e.id] + ctx.iu_prod[e.id]
        for sh in st.live_ships():
            if sh.owner == e.id:
                d["NWR" if sh.type in NONWAR_CLASSES else "WAR"] += 1
        d["CTS"] = sum(1 for t in st.live_troops() if t.owner == e.id)
        hap = 0.0
        for s in st.systems:
            if s.owner == e.id:
                d["POP"] += s.pop
                hap += s.pop * s.happy
                d["SYS"] += 1
                d["STP"] += s.starport
        d["HAP"] = hap / d["POP"] if d["POP"] else 0.0
        d["PRD"] = d["GNP"] / d["POP"] if d["POP"] else 0.0
        d["GWR"] = ctx.growth[e.id]
        d["TEC"] = len([t for t in e.techs if t]) + e.future_tech
        vp = sum(tech_vp(t) for t in e.techs if t) + 4 * e.future_tech
        vp += K.VP_PER_SYSTEM * int(d["SYS"])
        d["VCT"] = vp
        stats[e.id] = d
    # every live race is ranked (A-06), except a host's race handicapped by W-28 (st.unranked):
    # its own figures are kept, but it is outside the pool, so it pushes nobody down a rank
    out = set(st.unranked or ())
    players = sorted(p for p in stats if p not in out)
    ranks: dict[int, dict[str, int]] = {p: {} for p in players}
    for name in K.STAT_NAMES:
        for p in players:
            ranks[p][name] = 1 + sum(1 for q in players if stats[q][name] > stats[p][name])
    for p in players:
        bonus = sum(K.VP_STAT_BONUS.get(ranks[p][s], 0) for s in K.VP_STATS)
        stats[p]["VCT"] += bonus
    for p in players:
        ranks[p]["VCT"] = 1 + sum(1 for q in players if stats[q]["VCT"] > stats[p]["VCT"])
    for eid, d in stats.items():
        e = st.empires[eid]
        e.stats = {k: round(float(v), 3) for k, v in d.items()}
        e.ranks = ranks.get(eid, {})
        e.vp = int(d["VCT"])
        rep = ctx.res.report(eid)
        rep.stats = {"values": e.stats, "ranks": e.ranks, "vp": e.vp,
                     "vp_needed": K.VICTORY_POINTS}
        if eid in out:
            rep.stats["unranked"] = True        # the host's race (W-28): no ranks, can't win
    for viewer, target in ctx.pending_son:
        if target in stats:
            ctx.res.report(viewer).events.append(_son_event(st, target))


def _son_event(st, target):
    from ..results import Event
    e = st.empires[target]
    return Event("spy_report", f"Statistics report of the {e.name}: " +
                 " ".join(f"{k} {v}" for k, v in e.ranks.items()) if e.ranks else
                 f"Statistics of the {e.name}: VP {e.vp}", "spies",
                 data={"race": target, "ranks": e.ranks, "stats": e.stats})


def check_victory(ctx: TurnContext) -> None:
    """First empire to 100 VP wins, human or computer (A-06), except a race in `st.unranked` (the
    host's race in a game with another human, W-28); several reaching it the same turn
    are a tie, decided by NNP (rules:199-200; DECISIONS flag F-05)."""
    st = ctx.state
    if st.winner is not None:
        return
    out = set(st.unranked or ())                # the host's race can't win (W-28)
    reached = [e for e in st.empires.values() if e.kind in (HUMAN, NPR)
               and e.vp >= K.VICTORY_POINTS and e.id not in out]
    if not reached:
        return
    reached.sort(key=lambda e: (e.stats.get("NNP", 0), e.vp), reverse=True)
    w = reached[0]
    st.winner = w.id
    st.winners_vp = {e.id: e.vp for e in reached}
    ctx.res.winner = w.id
    for e in st.empires.values():
        if e.kind in (HUMAN, NPR):
            ctx.res.emit(e.id, "victory", f"The {w.name} have reached {w.vp} victory points and "
                         f"are crowned Grand Poobah of the Universe!", "general", race=w.id)
