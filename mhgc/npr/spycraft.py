"""Spies for the bot (Dave 2026-11-15: "bots build spies and use the missions sensibly from their
own view"; rules:2741-2843, 2001-2012).

Everything comes from the bot's own view: its spies (view["spies"]), the systems it knows of and
its short-scan intel on them, its stances, and what its spies reported last turn (the normal
results: a successful SOS is a short scan, an SOT a technology report, a caught spy an event).

* Service size: `memory.WAR_STYLE[...]["spies"]` spies at most (an opportunist keeps more, a
  builder fewer), one before the aggression ramp unless at war, and only while the spy service
  (upkeep 5 EU a spy, rules:2851, plus counter-intelligence) stays within the personality's
  `spy_share` of income.  A spy is built (BT S, Biomodification) only when there is work for it.
* Missions, by priority:
    1. scout a war-fleet target whose intel is more than two turns old (SOS), so the fleet launches
       and lands on fresh figures;
    2. against a race at war with us: SOS when stale, else incite an uprising (SUP: 50% success,
       10% caught) on its populous worlds, or sabotage (SSB: 20%, 40% caught) where intel shows
       artifacts - the bolder personalities only;
    3. scout a neighbour's system whose intel is stale (SOS), conquest prospects first;
    4. once in a while, a technology report (SOT, 50%/10%) on a neighbour, for tech trades.
  Spies sitting at a foreign system get the mission there; others move (SMV) to the best target
  not already covered.  There is no "steal technology" mission in the rules (SOT reports them).
* Counter-intelligence (CI, 10 EU a point, rules:2001-2007) on our systems where an enemy spy was
  caught in the last few turns, or that a race at war with us threatens, most valuable first.
"""
from __future__ import annotations

from ..data import constants as K
from ..data.techs import TECHS
from .econ import income, ramped, reserve, style
from .trace import note
from .world import dist

TECH_BY_NAME = {t.name: tid for tid, t in TECHS.items()}


def learn(w) -> None:
    """Fold last turn's spy reports into memory: technology lists (SOT) and caught spies."""
    mem = w.mem
    sp_mem = mem.setdefault("spy", {"caught": [], "detected": {}, "techs": {}, "sot": {}})
    for ev in (w.results.get("events") or []):
        k = ev.get("kind")
        d = ev.get("data") or {}
        if k == "spy_caught":
            sp_mem["caught"].append(w.turn)
            del sp_mem["caught"][:-10]
        elif k == "spy_detected" and ev.get("system") is not None:
            sp_mem["detected"][str(ev["system"])] = w.turn
        elif k == "spy_report" and d.get("mission") == "SOT" and d.get("success"):
            techs = parse_techs(ev.get("text") or "")
            s = w.sys_by_id(ev.get("system")) if ev.get("system") is not None else None
            owner = (s.owner if s is not None else None) or ((s.intel or {}).get("owner")
                                                             if s is not None else None)
            if owner and techs is not None:
                sp_mem["techs"][str(owner)] = {"t": w.turn - 1, "techs": sorted(techs)}
    for k in [k for k, t in sp_mem["detected"].items() if w.turn - t > 6]:
        del sp_mem["detected"][k]
    # a spy move refused because the system has since been taken by a race we haven't met (our
    # view still shows the old owner): leave that system alone for a while (2026-11-19: the same
    # SMV was otherwise repeated every turn)
    bad = sp_mem.setdefault("nocontact", {})
    for o in (w.results.get("orders") or []):
        if o.get("code") == "SMV" and not o.get("ok") and "made contact" in (o.get("error") or ""):
            parts = (o.get("text") or "").split()
            name = parts[2] if len(parts) > 2 else None
            s = next((x for x in w.known.values() if x.name == name), None)
            if s is not None:
                bad[str(s.id)] = w.turn
    for k in [k for k, t in bad.items() if w.turn - t > NOCONTACT_TURNS]:
        del bad[k]


def parse_techs(text: str):
    """The technology ids in an SOT report ("Technologies of the X: A, B, C.")."""
    if "Technologies of the" not in text:
        return None
    body = text.split("Technologies of the", 1)[1].split(":", 1)
    if len(body) < 2:
        return None
    names = body[1].strip().rstrip(".").split(", ")
    out = {TECH_BY_NAME[n.strip()] for n in names if n.strip() in TECH_BY_NAME}
    out.add(0)
    return out


def _stale(w, s, age: int) -> bool:
    it = s.intel
    return it is None or w.turn - it["t"] > age


NOCONTACT_TURNS = 20


def _reachable(w, s) -> bool:
    """SMV needs contact with the owner (orders_exec._smv); unowned systems are fine, unless a
    spy move there was refused for want of contact lately (learn)."""
    if str(s.id) in w.mem.get("spy", {}).get("nocontact", {}):
        return False
    return not s.owner or s.owner in w.races


def targets(w, ramp: bool) -> list:
    """[(priority, system id, mission or None (= decide on arrival), why)] from our own view."""
    out = []
    mission_targets = {m["target"] for m in w.mem["missions"] if m["state"] != "hold"}
    for sid in mission_targets:
        s = w.sys_by_id(sid)
        if s is not None and not s.mine and _reachable(w, s) and _stale(w, s, 2):
            out.append((100, s.id, "SOS", "fresh intel for the war fleet"))
    p = w.persona["name"]
    home = w.home()
    hx, hy = (home.x, home.y) if home is not None else (w.view["empire"]["home"]["x"],
                                                        w.view["empire"]["home"]["y"])
    for s in w.known.values():
        owner = s.owner or ((s.intel or {}).get("owner"))
        if not owner or owner == w.eid or w.allied(owner) or not _reachable(w, s):
            continue
        d = dist(hx, hy, s.x, s.y)
        if d > 30:
            continue
        it = s.intel
        if w.at_war(owner):
            if _stale(w, s, 4):
                out.append((80 - d, s.id, "SOS", "scout an enemy world"))
            elif it and it["pop"] >= 4 and p != "builder":
                if it["artifacts"] and p == "aggressive":
                    out.append((60 - d, s.id, "SSB", "sabotage an enemy world"))
                else:
                    out.append((65 - d, s.id, "SUP", "stir up an enemy world"))
            continue
        # (fewer conquests since the economy-first retune: neighbours are scouted less often,
        # and caught spies start wars)
        if _stale(w, s, 14 if ramp else 15) and d <= (16 if ramp else 14):
            out.append((40 - d + (10 if ramp else 0), s.id, "SOS", "scout a neighbour"))
    sot = w.mem.setdefault("spy", {}).setdefault("sot", {})
    for rid in w.contacted():
        if w.at_war(rid) or w.allied(rid) or w.races[rid]["kind"] != "npr":
            continue
        if w.turn - sot.get(str(rid), -99) < 20:
            continue
        near = [s for s in w.known.values() if s.owner == rid and dist(hx, hy, s.x, s.y) <= 20]
        if near:
            s = min(near, key=lambda x: (dist(hx, hy, x.x, x.y), x.id))
            out.append((20, s.id, "SOT", "their technologies, for trading"))
    out.sort(key=lambda t: (-t[0], t[1]))
    return out


def plan_spies(w, plan, thr: dict) -> None:
    if not w.has_tech(14):
        return
    learn(w)
    st = style(w.mem)
    ramp = ramped(w)
    at_war = any(w.at_war(r) for r in w.contacted())
    inc = max(1, income(w)[0])
    budget = st["spy_share"] * inc
    if at_war or ramp:
        budget = max(budget, 5.0)                 # one spy at least, at war or once ramped
    limit = st["spies"] if (ramp or at_war) else 1
    # counter-intelligence first (it protects what we have)
    ci_spent = _counter_intelligence(w, plan, thr, budget - 5 * len(w.spies))
    jobs = targets(w, ramp)
    used: set = set()
    sp_mem = w.mem["spy"]
    idle = []
    for sp in sorted(w.spies, key=lambda x: x.number):
        if sp.transit:
            if sp.system is not None:
                used.add(sp.system)
            continue
        here = w.sys_by_id(sp.system)
        job = next((j for j in jobs if j[1] == sp.system and j[1] not in used), None)
        if job is not None and here is not None and not here.mine:
            code = job[2]
            plan.add(code, job[3], rc=f"spy.{code}", spy=sp.number)
            used.add(job[1])
            if code == "SOT" and here.owner:
                sp_mem["sot"][str(here.owner)] = w.turn
            continue
        idle.append(sp)
    for sp in idle:
        job = next((j for j in jobs if j[1] not in used), None)
        if job is None:
            break
        s = w.sys_by_id(job[1])
        if s is None:
            continue
        plan.add("SMV", "spy to the target", spy=sp.number, system=s.name)
        used.add(job[1])
    open_jobs = [j for j in jobs if j[1] not in used]
    upkeep_now = 5 * len(w.spies) + ci_spent
    if open_jobs and len(w.spies) < limit and upkeep_now + 5 <= budget:
        stage = w.home()
        if stage is not None and plan.build_spy(stage, "a spy for " + open_jobs[0][3],
                                                reserve(w) + 30):
            note("spy_built", job=open_jobs[0][3], spies=len(w.spies) + 1, limit=limit)


def _counter_intelligence(w, plan, thr: dict, budget: float) -> int:
    det = w.mem["spy"]["detected"]
    cands = []
    for s in w.populated:
        hot = str(s.id) in det
        threatened = thr.get(s.id, {}).get("attack", 0) > 0 and any(
            w.at_war(c.owner) and dist(c.x, c.y, s.x, s.y) <= 4 for c in w.contacts)
        if hot or threatened:
            cands.append((-(s.pop + (5 if hot else 0)), s.id, s))
    spent = 0
    for _, _, s in sorted(cands)[:2]:
        pts = 2 if str(s.id) in det else 1
        cost = K.CI_EU_PER_POINT * pts
        if spent + cost > max(0.0, budget) or plan.eu - reserve(w) < cost:
            break
        plan.add("CI", "counter-intelligence on a threatened system", rc="spy.counter_intel",
                 system=s.name, amount=pts)
        plan.pay(cost, "counter-intelligence")
        spent += cost
    return spent


__all__ = ["plan_spies", "targets", "learn", "parse_techs"]
