"""The bot's turn: `decide(view, memory, rng)` -> orders.  Pure: it reads only the view (the
player read model, mhgc.view) and its own memory, and writes only its memory.

Order of concerns (also the order of spending priority):
  1. learn from last turn's report; diplomacy (warnings, war, peace, alliances)
  2. colonists and cargo that arrived; war missions in progress
  3. defence of threatened systems (garrisons, dug-in troops, reinforcements), intercepts
  4. tech trades with other computer empires (trade.py), research (one PT, then crash research
     with the EUs left over)
  5. development: infrastructure, EUS, production artifacts, then starports (held back while
     economic investments wait, except where defence or the builds need them)
  6. expansion: transports, settlers, scouts; trade routes (ctt.py: traders under way are moved
     before the colony transports, new ones built after development)
  7. war missions (several at once once aggression has ramped with light cruisers; each
     engine-evaluated), spies and counter-intelligence (spycraft.py); farcasters and warp
     tunnels to far fronts (portals.py: built after development, used by missions and defence)
  8. leaders, production profiles, postures
"""
from __future__ import annotations

from ..data import constants as K
from . import ctt, diplo, econ, expand, naming, portals, spycraft, trace, trade, war
from .plan import Plan
from .world import build


def decide(view: dict, mem: dict, rng, record: bool = False) -> Plan:
    """The bot's orders (`plan.orders`).  With `record`, `plan.record` also holds the decision
    log entry for this turn (mhgc/npr/trace.py); the orders and memory are the same either way."""
    tok = trace.start() if record else None
    try:
        plan = _decide(view, mem, rng, record)
    finally:
        decisions = trace.stop(tok) if tok is not None else []
    if record and plan.record is not None:
        plan.record["decisions"] = decisions
    return plan


def _decide(view: dict, mem: dict, rng, record: bool) -> Plan:
    w = build(view, mem)
    plan = Plan(w)
    plan.record = None
    if not w.systems and not w.ships:
        return plan
    plan.area = "diplomacy"
    seen_stance = {rid: w.stance(rid) for rid in w.contacted()} if record else None
    diplo.learn(w)
    war.observe_enemies(w)
    diplo.plan(w, plan, rng)
    thr = war.threats(w)
    plan.thr = thr
    threatened = {sid for sid, t in thr.items() if t["attack"] > 0}
    at_war = any(w.at_war(r) for r in w.contacted())
    vp_push = w.vp >= 0.6 * K.VICTORY_POINTS
    saw = trace.saw(w, thr, seen_stance) if record else None   # before the plan edits its world

    plan.area = "trade"
    trade.hold_due(w, plan)                  # an agreed tech trade's money, before any spending
    home = w.home()
    home_attacked = home is not None and home.status != K.NORMAL
    held = econ.research_hold(w, plan, home_attacked)   # the research floor, before war spends
    plan.area = "trade_routes"
    ctt.move(w, plan, bool(expand.colony_targets(w)), war.mission_ships(w))
    plan.area = "transports"
    expand.transports(w, plan, threatened, war.mission_ships(w))
    plan.area = "missions"
    war.plan_missions(w, plan, rng, thr)
    plan.area = "defence"
    war.defend(w, plan, thr)
    plan.area = "intercepts"
    war.intercepts(w, plan)
    plan.area = "trade"
    trade.plan_trades(w, plan, rng)
    plan.area = "research"
    econ.research_release(w, plan, held)
    econ.research(w, plan, bool(threatened), at_war, vp_push)
    if not home_attacked:
        econ.research_after(w, plan, held)
    plan.area = "development"
    yards = {m["stage"] for m in mem["missions"]} | ({home.id} if home is not None else set())
    econ.development(w, plan, threatened, yards)
    portals.build(w, plan, thr, {m["stage"] for m in mem["missions"]}, econ.reserve(w))
    plan.area = "trade_routes"
    ctt.build(w, plan, threatened)
    plan.area = "scouts"
    expand.build_scouts(w, plan)
    expand.scouts(w, plan)
    plan.area = "spies"
    spycraft.plan_spies(w, plan, thr)
    plan.area = "leaders"
    fleet = next((m["fleet"] for m in mem["missions"] if m.get("fleet")), None)
    econ.leaders(w, plan, fleet)
    inc_eu, inc_iu = econ.income(w)
    up_eu, _ = econ.upkeep(w)
    want_eu = 1.6 if w.eu < 150 + 2 * up_eu else 1.0 if not vp_push else 1.4
    plan.area = "profiles"
    econ.profiles(w, plan, want_eu)
    plan.area = "postures"
    postures(w, plan)
    plan.area = "naming"
    naming.plan_renames(w, plan, rng)        # last: no later order uses the old names
    mem["mode"] = "defend" if threatened else "war" if (at_war or mem["missions"]) else \
        "expand" if expand.colony_targets(w) else "build"
    mem["last_orders"] = len(plan.orders)
    if plan.errors:
        mem.setdefault("bugs", []).extend(plan.errors[-5:])
    if record:
        plan.record = trace.record(w, plan, saw, {
            "threatened": len(threatened), "vp_push": vp_push, "want_eu": want_eu,
            "income": {"eu": round(inc_eu, 1), "iu": round(inc_iu, 1)},
            "upkeep_eu": round(up_eu, 1), "reserve": econ.reserve(w),
            "leader_race": diplo.leader(w), "ramped": econ.ramped(w),
            "ship_tier": econ.ship_tier(w), "econ_pending": plan.econ_pending,
            "mil_upkeep": war.mil_upkeep(w), "mil_cap": round(war.mil_cap(w)),
            "rsave": mem.get("rsave", 0), "routes": len(mem.get("routes") or {}),
            "traders": len(mem.get("traders") or {}),
            "trade_eu": (w.results.get("economy") or {}).get("trade_eu", 0)})
    return plan


def postures(w, plan) -> None:
    busy = war.mission_ships(w) | plan.busy
    for sh in w.ships:
        if sh.fleet is not None or sh.number in busy:
            continue
        if sh.st.attack == 0 and sh.posture != "F":
            plan.add("SP", "unarmed ships keep out of fights", ship=sh.number, posture="F")
        elif sh.st.attack > 0 and sh.posture == "H" and sh.order != "INTERCEPT":
            plan.add("SP", "", ship=sh.number, posture="N")


# ---- the inbox: the empire's own last report, kept for view() ---------------------------------

def inbox(results, eid: int) -> dict:
    """The parts of a turn's results that view() shows this empire, trimmed to what the bot
    uses (combat logs keep their kill lines only).  Stored in the bot's memory."""
    rep = results.reports.get(eid)
    if rep is None:
        return {"turn": results.turn, "reports": {}, "combats": []}
    ids = set(rep.combats)
    combats = []
    for c in results.combats:
        if c.id not in ids:
            continue
        combats.append({"id": c.id, "x": c.x, "y": c.y, "system": c.system,
                        "participants": list(c.participants), "relations": dict(c.relations),
                        "ships": [{"number": s["number"], "owner": s["owner"], "type": s["type"]}
                                  for s in c.ships],
                        "troops": [{"number": t["number"], "owner": t["owner"], "type": t["type"]}
                                   for t in c.troops],
                        "lines": [{"text": ln["text"][:60], "ship": ln.get("ship"),
                                   "ct": ln.get("ct"), "by": ln.get("by")}
                                  for ln in c.lines if ln.get("by") is not None],
                        "status_before": c.status_before, "status_after": c.status_after,
                        "owner_before": c.owner_before, "owner_after": c.owner_after})
    r = {"orders": [{"code": o.code, "ok": o.ok, "error": o.error, "text": o.text}
                    for o in rep.orders if not o.ok],
         "events": [{"kind": e.kind, "system": e.system, "data": {
             k: v for k, v in e.data.items() if isinstance(v, (int, float, str, bool))},
             **({"text": e.text} if e.kind == "spy_report" and e.data.get("mission") == "SOT"
                else {})}
             for e in rep.events],
         "messages": [dict(m) for m in rep.messages],
         "combats": sorted(ids), "scans": rep.scans, "stats": rep.stats,
         "economy": {k: v for k, v in rep.economy.items()}}
    import json
    r = json.loads(json.dumps(r))           # plain JSON (string keys), as after a reload
    return {"turn": results.turn, "reports": {str(eid): r}, "combats": combats}
