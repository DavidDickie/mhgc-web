"""Server-side analysis records (Dave 2026-11-14; DECISIONS W-15..W-17).

* `standings(state, humans, spend)`: one line of `standings.jsonl` - every empire's major
  statistics at the end of a turn, humans and computer empires alike: the engine's own stats
  (`Empire.stats`, the figures the rankings use: engine/stats.py) plus raw counts read from the
  state, the EU stockpile and IU depot, VP, its own stances (who it is at war with / allied to)
  and an estimate of what its orders spent, by category.  This is hidden information while the
  game runs: it is written to SAVE_DIR only and reaches a browser only through the end-of-game
  views (`/final`, `/export`), never through `view()` or `/stats`.
* `spending(before, orders, results)`: EU and IU spent per category by each empire's orders that
  succeeded, priced from the state at the start of the turn (2x under attack, as the engine
  charges).  Builds only; gifts, trades and refunds are left out.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from .data import constants as K
from .data.artifacts import ARTIFACTS, SPY_EU_COST, SPY_IU_COST
from .data.ships import NONWAR_CLASSES, SHIP_TYPES
from .data.techs import TECHS
from .data.troops import TROOP_TYPES
from .model import DEAD, HUMAN, NPR, GameState

STANDINGS_VERSION = 1
SPEND_CATEGORIES = ("ships", "troops", "techs", "infrastructure", "starports", "artifacts",
                    "spies")
STAT_KEYS = tuple(K.STAT_NAMES)


def _cat_cost(st: GameState, sysmap: dict, o) -> Optional[tuple[str, int, int]]:
    """(category, EU, IU) an order costs at the turn's start prices, or None."""
    code = o.code
    if code in ("PT", "CRP"):
        t = TECHS.get(getattr(o, "tech", None))
        if t is None:
            return None
        return "techs", t.cost * (2 if code == "CRP" else 1), 0
    s = sysmap.get(getattr(o, "system", None))
    if s is None:
        return None
    m = 2 if s.status == K.UNDER_ATTACK else 1
    if code == "BS":
        t = SHIP_TYPES.get(o.type)
        return ("ships", t.eu_cost * m, t.iu_cost * m) if t else None
    if code == "BCU":
        t = TROOP_TYPES.get(o.type)
        return ("troops", t.eu_cost * m, t.iu_cost * m) if t else None
    if code == "BT":
        if o.artifact == "S":
            return "spies", SPY_EU_COST * m, SPY_IU_COST * m
        a = ARTIFACTS.get(o.artifact)
        return ("artifacts", a.eu_cost * m, a.iu_cost * m) if a else None
    if code == "BI":
        return "infrastructure", 0, K.INFRA_IU_COST * int(o.amount or 0)
    if code == "BSP":
        c = K.starport_cost(s.starport + 1) - K.starport_cost(s.starport)
        return "starports", c, c
    return None


def spending(before: GameState, orders: dict, results) -> dict[int, dict]:
    """{empire: {category: {"eu": n, "iu": n}}} for orders that ran successfully."""
    out: dict[int, dict] = {}
    for eid, olist in orders.items():
        rep = results.reports.get(eid)
        ok = {r.index: (r.built or 1) for r in (rep.orders if rep else []) if r.ok}
        e = before.empires.get(eid)
        names = {s.name: s for s in before.systems}
        # an empire may use a stale name from its own map memory (W-14): its own systems'
        # current names are what the costs need
        acc = defaultdict(lambda: [0, 0])
        for i, o in enumerate(olist):
            if i not in ok:
                continue
            c = _cat_cost(before, names, o)
            if c is None:
                continue
            n = ok[i] if o.code in ("BS", "BCU") else 1     # a build count (G-19)
            acc[c[0]][0] += c[1] * n
            acc[c[0]][1] += c[2] * n
        if e is not None:
            out[eid] = {k: {"eu": v[0], "iu": v[1]} for k, v in sorted(acc.items())}
    return out


def standings(state: GameState, humans: int, spend: Optional[dict] = None,
              persona: Optional[dict] = None, human_ids: Optional[set] = None,
              changed: Optional[dict] = None) -> dict:
    """Every empire's figures at the end of turn `state.turn` (one standings.jsonl line).
    `human_ids`: the human seats at this turn (default 1..humans).  `changed` = {empire: T}: the
    host handed it to the computer or opened it for a human at turn T (DECISIONS W-22); it is
    `converted_turn` in the row, and `human` says which way."""
    hum = set(human_ids) if human_ids is not None else set(range(1, humans + 1))
    changed = changed or {}
    ships = defaultdict(lambda: [0, 0, 0])            # all, warships, attack
    for sh in state.live_ships():
        a = ships[sh.owner]
        a[0] += 1
        if sh.type not in NONWAR_CLASSES:
            a[1] += 1
        a[2] += sh.stype.attack
    troops = defaultdict(int)
    for t in state.live_troops():
        troops[t.owner] += 1
    spies = defaultdict(int)
    for sp in state.spies.values():
        if sp.alive:
            spies[sp.owner] += 1
    sysn = defaultdict(int)
    pop = defaultdict(float)
    infra = defaultdict(int)
    for s in state.systems:
        if s.owner:
            sysn[s.owner] += 1
            pop[s.owner] += s.pop
            infra[s.owner] += s.infra
    rows = []
    for eid in sorted(state.empires):
        e = state.empires[eid]
        if eid == 0 or e.kind not in (HUMAN, NPR, DEAD):
            continue
        live = e.kind in (HUMAN, NPR)
        st = {k: (e.stats.get(k, 0.0) if live else 0.0) for k in STAT_KEYS}
        rows.append({
            "id": eid, "name": e.name, "kind": e.kind, "human": eid in hum,
            "converted_turn": changed.get(eid),
            "persona": (persona or {}).get(eid),
            "stats": st, "ranks": dict(e.ranks) if live else {},
            "unranked": eid in (state.unranked or ()),          # the host handicap (W-28)
            "vp": e.vp if live else 0, "eu": e.eu, "iu_depot": e.iu_depot,
            "systems": sysn[eid], "pop": round(pop[eid], 3), "infra": infra[eid],
            "techs": len([t for t in e.techs if t]), "future_tech": e.future_tech,
            "ships": ships[eid][0], "warships": ships[eid][1], "attack": ships[eid][2],
            "troops": troops[eid], "spies": spies[eid],
            "happiness": round(st.get("HAP", 0.0), 3),
            "nnp": st.get("NNP", 0.0),
            "contacts": len(e.relations),
            "at_war": sorted(k for k, v in e.relations.items() if v in ("W", "E") and k),
            "allied": sorted(k for k, v in e.relations.items() if v == "A" and k),
            "spend": (spend or {}).get(eid, {}),
        })
    return {"v": STANDINGS_VERSION, "turn": state.turn, "winner": state.winner,
            "empires": rows}


def personas(state: GameState) -> dict[int, str]:
    return {int(eid): (m.get("persona") or {}).get("name")
            for eid, m in state.npr_state.items() if isinstance(m, dict)}


__all__ = ["standings", "spending", "personas", "SPEND_CATEGORIES", "STANDINGS_VERSION"]
