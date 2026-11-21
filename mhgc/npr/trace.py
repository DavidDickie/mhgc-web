"""The bot decision log (Dave 2026-11-14: "a full bot decision log for analysing bot behaviour
after a game").  DECISIONS A-05.

Nothing here changes what the bot does.  The log is a side channel:

* `Plan.add` records, for every order, the decision area it was made in (`Plan.area`, set by
  `brain.decide` before each step), a stable reason code and the bot's short note (the `why`
  that already goes into the order line as `# note`).  Reason codes come from `REASONS` below
  (note -> code; prefixes for notes that carry a name or a number) or are `<area>.<CODE>` for
  orders without a note.
* `note(ev, **data)` records a decision that is not an order (a war declared, a peace offer, an
  alliance, a mission chosen with its estimated odds, a research pick, a warning sent) when a
  trace is being collected for this bot's turn; otherwise it does nothing.  `memory.log` (the
  bot's own capped history, which it still uses) also feeds it.  The sink is a context variable,
  so concurrent games in server threads don't mix.
* `Tracer` is an `npr_fn` for `run_turn`: it runs the normal bot for every computer empire and
  keeps one record per empire; `finish(state, results)` adds which orders the engine rejected,
  and why, and returns the records for `botlog.jsonl` (app/main.py).  Records hold only what the
  bot saw (its own view and memory) and decided, contain no timings, and are byte-identical for
  the same game (tests/test_analysis.py).
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Optional

_SINK: ContextVar[Optional[list]] = ContextVar("mhgc_npr_trace", default=None)

# note (the order's `# why`) -> reason code.  Exact notes first, then prefixes.
REASONS = {
    "unarmed ships keep out of fights": "posture.unarmed_safe",
    "scout a world up close": "scout.close_look",
    "explore": "scout.explore",
    "a scout": "scout.build",
    "settle the empty world": "colony.settle",
    "garrison the colony": "colony.garrison",
    "deliver colonists": "cargo.deliver_pop",
    "deliver IUs": "cargo.deliver_iu",
    "transport going home": "transport.home",
    "load colonists": "colony.load_pop",
    "IUs for the colony": "colony.load_iu",
    "colonists for a roomier world": "migrate.load_pop",
    "IUs for a poorer world": "supply.load_iu",
    "a transport for colonists": "colony.build_transport",
    "garrison": "defend.garrison_ship",
    "reinforce": "defend.reinforce",
    "back to base": "defend.return_base",
    "out of a neutral's reach": "defend.leave_neutral",
    "dig in": "defend.dig_in",
    "back home": "mission.disband_home",
    "the attack failed; withdraw": "mission.withdraw",
    "land the assault troops": "mission.land_troops",
    "join the war fleet": "mission.gather_ship",
    "assault transport to the stage": "mission.gather_transport",
    "assault transport": "mission.build_transport",
    "assault troops": "mission.build_troops",
    "for the war fleet": "mission.build_warship",
    "load the assault troops": "mission.load_troops",
    "form the war fleet": "mission.launch",
    "spy on the target": "spy.scan_target",
    "spy to the target": "spy.move_to_target",
    "a spy for the war": "spy.build",
    "production profile": "econ.profile",
    "production profile: tweak": "econ.profile_tweak",
    "infrastructure doubles production": "econ.infrastructure",
    "room to grow past 10": "econ.eus",
    "bigger starport: production and capacity": "econ.starport",
    "bigger starport: the builds here need the capacity": "econ.starport_capacity",
    "bigger starport: defence of a frontier or shipyard": "econ.starport_defence",
    "garrison the capture": "mission.garrison_capture",
    "troops back on the ground": "mission.unload_home",
    "conquest": "diplo.war_conquest",
    "easy": "diplo.war_conquest",
    "rebels": "diplo.war_conquest",
    "war": "diplo.war_conquest",
    "counter-intelligence on a threatened system": "spy.counter_intel",
    "an admiral for the war fleet": "leader.admiral",
    "a governor for a big system": "leader.governor",
    "name our new world": "naming.rename",
    "offer to end the war": "diplo.peace_ewa",
    "end the alliance": "diplo.end_alliance",
    "end the alliance before war": "diplo.end_alliance_for_war",
    "an alliance": "diplo.alliance",
    "retaliation": "diplo.war_retaliation",
    "proximity": "diplo.war_proximity",
    "trade route": "ctt.convert",
    "a transport for a trade route": "ctt.build_transport",
    # farcasters and warp tunnels (portals.py, DECISIONS G-24)
    "farcaster portal: troops to a far front": "portal.build_fp",
    "warp tunnel: ships to a far front": "portal.build_wt",
    "farcast assault troops to the stage": "portal.tp_mission",
    "farcast troops to a threatened system": "portal.tp_defence",
    "assault troops to farcast": "portal.build_troops",
    "warp to the war fleet": "portal.wtp_mission",
    "warp to a system under threat": "portal.wtp_defence",
    "warp to reinforce": "portal.wtp_reinforce",
    # the baseline bot (the strength harness's opponent)
    "random research": "baseline.research",
    "infrastructure": "baseline.infrastructure",
    "random build": "baseline.build",
    "settle": "baseline.settle",
    "colonist": "baseline.load_pop",
    "home": "baseline.home",
    "wander": "baseline.wander",
}
PREFIXES = (
    ("crash research ", "research.crash"),
    ("research ", "research.pick"),
    ("settle ", "colony.send"),
    ("pays back", "econ.artifact"),
    ("intercept enemy ", "defend.intercept"),
    ("attack ", "mission.attack"),
    ("mission over: ", "mission.done"),
    ("HELP SYSTEM UNDER THREAT", "defend.help_threatened"),
    ("a spy for ", "spy.build"),
    ("tech trade agreed", "trade.execute"),
    ("to trade with ", "ctt.send"),
)


def reason_code(area: str, code: str, why: str) -> str:
    if why:
        rc = REASONS.get(why)
        if rc:
            return rc
        for p, rc in PREFIXES:
            if why.startswith(p):
                return rc
        return f"{area or 'misc'}.other"
    return f"{area or 'misc'}.{code}"


def collecting() -> bool:
    return _SINK.get() is not None


def note(ev: str, **data) -> None:
    """Record a decision in the current trace (a no-op when no trace is being collected)."""
    sink = _SINK.get()
    if sink is not None:
        sink.append({"ev": ev, **data})


def start() -> Any:
    return _SINK.set([])


def stop(token) -> list:
    out = _SINK.get() or []
    _SINK.reset(token)
    return out


# ---- the record ---------------------------------------------------------------------------------

def _r(x, n=2):
    return round(float(x), n)


def saw(w, thr: dict, stance: Optional[dict] = None) -> dict:
    """A compact summary of the bot's own view this turn.  `stance` is our stance to each race
    as the view showed it, before this turn's diplomacy (the strategy part has the result)."""
    from .war import weight
    by_race: dict[str, dict] = {}
    for c in w.contacts:
        d = by_race.setdefault(str(c.owner), {"ships": 0, "warships": 0, "attack": 0, "near": 0})
        d["ships"] += 1
        if c.st.attack > 0:
            d["warships"] += 1
            d["attack"] += c.st.attack
            if w.dist_to_us(c.x, c.y) <= w.persona["claim"]:
                d["near"] += 1
    known_by_owner: dict[str, int] = {}
    for s in w.known.values():
        if s.owner:
            known_by_owner[str(s.owner)] = known_by_owner.get(str(s.owner), 0) + 1
    threatened = {str(sid): {"attack": _r(t["attack"]), "carriers": t["carriers"]}
                  for sid, t in thr.items() if t["attack"] > 0 or t["carriers"]}
    enemy = {k: {"att": _r(v["att"]), "def": _r(v["def"]), "t": v["t"]}
             for k, v in sorted(w.mem["enemy"].items()) if v["att"] >= 0.05}
    races = {}
    for rid in w.contacted():
        r = w.mem["races"].get(str(rid)) or {}
        races[str(rid)] = {"name": w.race_name(rid),
                           "stance": (stance or {}).get(rid, w.stance(rid)),
                           "kind": w.races[rid]["kind"],
                           "griev": _r(r.get("griev", 0), 1), "good": _r(r.get("good", 0), 1),
                           "weight": weight(w, rid)}
    return {
        "systems": len(w.systems), "populated": len(w.populated),
        "pop": _r(sum(s.pop for s in w.systems), 1),
        "eu": w.eu, "iu_depot": w.iu_depot, "vp": w.vp, "techs": len([t for t in w.techs if t]),
        "ships": len(w.ships), "warships": sum(1 for sh in w.ships if sh.st.attack > 0),
        "attack": sum(sh.st.attack for sh in w.ships), "fleets": len(w.fleets),
        "troops": len(w.troops), "spies": len(w.spies),
        "under_attack": sum(1 for s in w.systems if s.status != 0),
        "known_systems": len(w.known), "known_by_owner": known_by_owner,
        "contacts": by_race, "threatened": threatened, "enemy_seen": enemy, "races": races,
        "failed_last_turn": sum(1 for o in w.results.get("orders") or [] if not o.get("ok")),
    }


def strategy(w, plan, extra: dict) -> dict:
    m = w.mem
    return {
        "mode": m["mode"], "persona": m["persona"]["name"],
        "params": {k: v for k, v in m["persona"].items() if k != "name"},
        "budget": {"eu_start": w.eu, "eu_left": plan.eu,
                   "spent": dict(sorted((k, v) for k, v in plan.spent.items() if v))},
        "at_war": [r for r in w.contacted() if w.at_war(r)],
        "allied": [r for r in w.contacted() if w.allied(r)],
        "missions": [{k: mm.get(k) for k in ("id", "target", "race", "why", "stage", "state",
                                              "start", "fleet", "est", "troops")}
                     | {"ships": len(mm.get("ships") or [])} for mm in m["missions"]],
        "claims": len(m["claims"]), **extra,
    }


def record(w, plan, saw_: dict, extra: dict) -> dict:
    orders = []
    for i, (o, rs) in enumerate(zip(plan.orders, plan.reasons)):
        text = o.to_text()
        if o.code == "MESSAGE" and len(text) > 160:
            text = text[:157] + "..."
        orders.append({"i": i, "code": o.code, "text": text, **rs})
    return {"turn": w.turn, "empire": w.eid, "race": w.name, "saw": saw_,
            "strategy": strategy(w, plan, extra), "orders": orders, "decisions": [],
            "plan_errors": list(plan.errors)}


# ---- the run_turn hook ------------------------------------------------------------------------

class Tracer:
    """`run_turn(state, orders, npr_fn=Tracer())`: the normal computer empires, plus a record of
    each one's decisions.  Then `finish(state, results)` -> the turn's log records."""

    def __init__(self, aomt_results: Optional[dict] = None):
        self.records: dict[int, dict] = {}
        self.orders: dict[int, list] = {}           # the orders each computer empire gave
        self.aomt: dict[int, list] = {}             # stand-in orders for human races (W-29)
        self._aomt_results = aomt_results           # the stored results the race last saw

    def stand_in(self, state, empire_id: int) -> list:
        """`aomt_fn` for run_turn: a human race's orders for a missed turn (AOMT, W-29), from
        its own view; the record is marked `aomt` in the bot log."""
        from . import aomt_orders_traced
        orders, rec = aomt_orders_traced(state, empire_id, self._aomt_results)
        self.orders[empire_id] = list(orders)
        self.aomt[empire_id] = list(orders)
        if rec is not None:
            self.records[empire_id] = rec
        return orders

    def __call__(self, state, empire_id: int) -> list:
        from . import npr_orders_traced
        orders, rec = npr_orders_traced(state, empire_id)
        self.orders[empire_id] = list(orders)
        if rec is not None:
            self.records[empire_id] = rec
        return orders

    def finish(self, state, results) -> list[dict]:
        out = []
        for eid in sorted(self.records):
            rec = self.records[eid]
            rep = results.reports.get(eid)
            got = {r.index: r for r in (rep.orders if rep else [])}
            rejected = 0
            for o in rec["orders"]:
                r = got.get(o["i"])
                if r is None:
                    o["ok"], o["error"] = None, "not run (the empire was destroyed first)"
                    continue
                o["ok"] = bool(r.ok)
                if not r.ok:
                    o["error"] = r.error
                    rejected += 1
            rec["rejected"] = rejected
            e = state.empires.get(eid)
            rec["after"] = {"vp": e.vp, "systems": int(e.stats.get("SYS", 0)), "eu": e.eu,
                            "kind": e.kind} if e is not None else None
            out.append(rec)
        return out


__all__ = ["note", "reason_code", "Tracer", "collecting", "REASONS"]
