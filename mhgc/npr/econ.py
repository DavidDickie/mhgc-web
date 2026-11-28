"""Economy and research for the bot, from the rules' formulas (rules:343-460, 2675-3052).

* Production profiles (CSP): enough AU to keep each system happy enough to grow (growth needs
  happiness above 0.5, rules:378-385) using the rules' happiness formula, the rest to IU or EU by
  each system's multipliers (MR/CM/AL for IU, CB/VRB for EU) and by what the empire is short of.
* Infrastructure up to population (it doubles production, rules:331-333), starports on
  big systems, EUS when a system reaches its 10-pop cap, production artifacts where they pay
  back, leaders as governors of the biggest systems or admirals of the war fleet.
* Research: a value per technology (victory points, economy, the military line types for the
  Mixed Fleet Bonus, defence when threatened), bought once a turn when affordable over the upkeep
  reserve, then crash research with what is left over beyond a margin (several programmes a
  turn, the dearest technology as the PT); a system's idle IU stockpile turns its profile to EU.
"""
from __future__ import annotations

import math

from ..data import constants as K
from ..data.artifacts import ARTIFACTS
from ..data.ships import SHIP_TYPES
from ..data.techs import FUTURE_TECH, TECHS, missing_prereqs, tech_vp
from ..engine import economy as _economy
from . import trace
from . import memory as _memory
from . import portals as _portals
from .world import dist, frontier

TARGET_HAPPY = 0.8

# Economy first (Dave 2026-11-15, second round: "Fight less, research more").  The war style of
# each personality (memory.WAR_STYLE, the 2026-11-15 ramp) retuned: fewer war fleets at once, a
# higher capture chance to launch, a smaller warship upkeep share, a smaller spy service.  The
# order of the personalities stays (aggressive the most warlike).  `room` scales the persona's
# `aggression` share of income for warship upkeep (war.military_room); `war_room` is the extra
# share while at war (it was x1.5); `garrison` scales the standing guard (war.garrison_need);
# `war_at_x` scales the grievance that starts a war of retaliation (diplo.plan);
# `conquest_gap` is the turns after an attack of its choosing sets out (or takes a system) before
# the next is planned (wars on us and rebels aren't held back); `ramp_min` is the earliest turn
# the aggression ramps (research reaches light cruisers sooner than it did).
ECON_FIRST: dict[str, dict] = {
    "aggressive": {"missions": 1, "need": 0.76, "pre": 0.7, "post": 0.9, "conquer_below": 10,
                   "range": 18, "spies": 3, "spy_share": 0.04, "war_room": 1.25,
                   "garrison": 0.9, "war_at_x": 1.1, "conquest_gap": 12, "ramp_min": 30},
    "opportunist": {"missions": 1, "need": 0.82, "pre": 0.7, "post": 0.85, "conquer_below": 4,
                    "range": 15, "spies": 3, "spy_share": 0.06, "war_room": 1.2,
                    "garrison": 0.9, "war_at_x": 1.2, "conquest_gap": 16, "ramp_min": 34},
    "builder": {"missions": 1, "need": 0.87, "pre": 0.75, "post": 0.8, "conquer_below": -5,
                "range": 12, "spies": 2, "spy_share": 0.03, "war_room": 1.15,
                "garrison": 0.9, "war_at_x": 1.3, "conquest_gap": 20, "ramp_min": 45},
}


def style(mem: dict) -> dict:
    """The personality's war style (memory.WAR_STYLE) with the economy-first retune."""
    name = (mem.get("persona") or {}).get("name")
    return {**_memory.style(mem), **ECON_FIRST.get(name, ECON_FIRST["opportunist"])}


def upkeep(w) -> tuple[int, int]:
    """(EU, IU) maintenance for next turn (rules:479-486, chart 3063)."""
    own = {(s.x, s.y) for s in w.systems}
    eu = iu = 0
    for sh in w.ships:
        if (sh.x, sh.y) in own:
            eu += 2
            iu += 2
        else:
            eu += 5
            iu += 5
    eu += sum(t.tt.maint_eu for t in w.troops)
    eu += 5 * len(w.spies)
    eu += sum(ARTIFACTS[a].maint_eu for s in w.systems for a in s.artifacts if a in ARTIFACTS)
    return eu, iu


def income(w) -> tuple[int, int]:
    eu = iu = 0
    for s in w.populated:
        p = s.production or {}
        eu += p.get("eu", 0)
        iu += p.get("iu", 0)
    if eu == 0 and iu == 0:                      # first turn: estimate
        for s in w.populated:
            P = production(w, s)
            eu += int(P * s.csp[2] / 100)
            iu += int(P * s.csp[1] / 100 * (2 if s.mr else 1))
    # trade routes (ctt.py, DECISIONS A-11): last turn's DCT income, from our own report
    eu += int((w.results.get("economy") or {}).get("trade_eu", 0) or 0)
    return eu, iu


LC_COST = TECHS[SHIP_TYPES["LC"].tech].cost       # the light cruiser's tier (Dave 2026-11-15)


def ship_tier(w) -> int:
    """0 before light-cruiser-class warships; 1 with a warship technology of the light cruiser's
    cost (LightCruiser, Guardian, Mauler); 2 with one costing twice that or more."""
    best = max((TECHS[st.tech].cost for st in SHIP_TYPES.values()
                if st.attack > 0 and w.has_tech(st.tech)), default=0)
    return 2 if best >= 2 * LC_COST else 1 if best >= LC_COST else 0


def ramped(w) -> bool:
    """Has the bot's aggression ramped up (Dave 2026-11-15)?  Aggressive and opportunist bots
    ramp with light cruisers (or any warship of that tier); builders with the next tier, or
    late in the game (memory.WAR_STYLE)."""
    t = ship_tier(w)
    st = style(w.mem)
    if w.turn < st["ramp_min"]:              # research is faster now: not before this turn
        return False
    return t >= 2 or (t >= 1 and (st["ramp_tier"] <= 1 or w.turn >= st["ramp_turn"]))


def _ramp_path() -> set:
    out, todo = set(), [SHIP_TYPES["LC"].tech]
    while todo:
        t = todo.pop()
        if t not in out and t:
            out.add(t)
            todo.extend(TECHS[t].prereqs)
    return out


RAMP_PATH = _ramp_path()                           # High Energy Physics and its prerequisites


def reserve(w) -> int:
    return upkeep(w)[0] + 25


def production(w, s) -> float:
    if s.pop <= 0:
        return 0.0
    mgmt = 1.0
    gov = next((ld for ld in w.leaders if ld.status == "posted" and ld.system == s.id), None)
    if gov is not None:
        mgmt = 0.5 + gov.mgmt / 100.0
    cm = 0.5 if s.status == K.UNDER_ATTACK else 0.0 if s.status == K.INTERDICTED else 1.0
    infra = min(2.0, (s.pop + s.infra) / s.pop)
    return s.pop * K.PROD_PER_POP * infra * mgmt * cm * (1 + K.STARPORT_PROD_BONUS * s.starport)


def au_needed(w, s, target=TARGET_HAPPY) -> float:
    """AU eaten per turn for happiness `target` (inverse of the rules' formula,
    engine/economy.happiness).  At a steady stockpile, eaten = produced."""
    gov = next((ld for ld in w.leaders if ld.status == "posted" and ld.system == s.id), None)
    social = gov.social / 100.0 if gov is not None else 0.5
    a = s.artifacts
    adds = 4.0 if ("EHC" in a and "CS" in a) else 1.0 if "EHC" in a else 3.0 if "CS" in a \
        else 0.0
    adds += 0.5 * sum(1 for x in ("PD", "SW", "APD") if x in a)
    b = (s.hab + (social * 4 - 2) + adds) / (s.pop * 2)
    need_a = max(0.0, target + 0.2 - b)
    return 5.0 * need_a ** 2 * 2.25 * s.pop * (1 + s.starport / 10.0)


IU_GLUT_MIN = 800         # a system's IU stockpile beyond max(this, IU_GLUT_TURNS x its
IU_GLUT_TURNS = 10        # production) is idle: its profile turns to EU for research


def profiles(w, plan, want_eu: float) -> None:
    for s in w.populated:
        P = production(w, s)
        if P <= 0:
            continue
        growing = s.pop < (K.POP_CAP - 0.3) or "EUS" in s.artifacts
        target = TARGET_HAPPY if growing else 0.65
        au_mult = (2 if s.ar else 1) * (1.5 if "BF" in s.artifacts else 1) * \
            (1.5 if "AF" in s.artifacts else 1)
        need = au_needed(w, s, target)
        stock_cover = s.au / 3.0                 # a stockpile already feeds a while (33%/turn)
        au = int(math.ceil(100.0 * max(0.0, need - stock_cover * 0.5) / (P * au_mult)))
        if s.happy < 0.55 and s.trend <= 0:
            au += 10
        au = max(10, min(80, au))
        rest = 100 - au
        iu_v = (2 if s.mr else 1) * (1.5 if "CM" in s.artifacts else 1) * \
            (1.5 if "AL" in s.artifacts else 1)
        eu_v = (1.5 if "CB" in s.artifacts else 1) * (1.5 if "VRB" in s.artifacts else 1) * \
            want_eu
        share = eu_v / (eu_v + iu_v)
        eu = int(round(rest * share))
        if s.pop < 3:
            eu = int(rest * 0.3)                 # small colonies build themselves up
        elif plan.iu.get(s.id, s.iu) > max(IU_GLUT_MIN, IU_GLUT_TURNS * P):
            eu = rest - 10                       # IU piling up unused: research instead
        eu = max(10, min(rest - 10, eu))
        iu = 100 - au - eu
        cur = tuple(s.csp)
        hungry = cur[0] < au and s.happy < target - 0.05
        if abs(cur[0] - au) + abs(cur[1] - iu) + abs(cur[2] - eu) >= 20 or hungry:
            # the final step: the split tweak on the chosen profile (outputs never go down)
            t = tweak(w, plan, s, (au, iu, eu))
            au, iu, eu = t["split"] if t else (au, iu, eu)
            plan.add("CSP", "production profile", system=s.name, au=au, iu=iu, eu=eu)
        elif TWEAK_REISSUE_GAIN is not None:
            # the profile stays: re-issue it tweaked only for a gain worth an order
            t = tweak(w, plan, s, cur)
            if t and t["gain"] >= TWEAK_REISSUE_GAIN:
                au, iu, eu = t["split"]
                plan.add("CSP", "production profile: tweak", system=s.name, au=au, iu=iu,
                         eu=eu)


# The split tweak (Dave 2026-11-18, engine/economy.tweak_split): +-TWEAK_DELTA points on each
# share to recover what truncation to whole units wastes, never lowering AU, IU or EU.  It is
# applied to every CSP the bot issues anyway.  A profile the bot keeps could be re-issued tweaked
# when that gains at least TWEAK_REISSUE_GAIN units; measured over 6 seeds x 70 turns (DECISIONS
# G-21) that cost 13% more CSP orders (37% at 1 unit) for a further 0.02% of production, so it is
# off (None).
TWEAK_DELTA = 3
TWEAK_REISSUE_GAIN = None


def split_context(w, plan, s):
    """The engine's production context for an own system as it will be at production, from the
    bot's own knowledge: its view of the system and governor, plus this turn's planned BI and
    BSP orders, colonists moved (plan.pop) and installs (the plan's copy of the artifacts)."""
    gov = next((ld for ld in w.leaders if ld.status == "posted" and ld.system == s.id), None)
    mgmt = 0.5 + gov.mgmt / 100.0 if gov is not None else 1.0
    infra, sp = s.infra, s.starport
    for o in plan.orders:
        if getattr(o, "system", None) != s.name:
            continue
        if o.code == "BI":
            infra += o.amount
        elif o.code == "BSP":
            sp += 1
        elif o.code == "DSP":
            sp = max(0, sp - 1)
    return _economy.make_split_context(plan.pop.get(s.id, s.pop), infra, mgmt, s.status, sp,
                                       s.mr, s.ar, s.artifacts)


def tweak(w, plan, s, split):
    """economy.tweak_split for one of the bot's systems, or None for an invalid split."""
    try:
        return _economy.tweak_split(split_context(w, plan, s), split, TWEAK_DELTA)
    except ValueError:
        return None


def development(w, plan, threatened: set, shipyards: set = frozenset()) -> None:
    """Infrastructure, EUS, production artifacts, then starports.

    Starports (Dave 2026-11-15): while an economic investment is unaffordable or still to make
    (infrastructure below population, a production artifact that pays back, the technology the
    bot wants), a starport is only enlarged where the system's own build plans ran short of
    capacity in the last turns, or where a bigger one defends something: frontier and threatened
    systems and the main shipyards (home, war-fleet staging systems).  Otherwise bigger is
    better: production (+10% a class, rules:452), build capacity and defence."""
    res = reserve(w)
    pending = bool(getattr(plan, "tech_pending", False))
    for s in sorted(w.populated, key=lambda s: (-s.pop, s.id)):
        if s.status == K.NORMAL:
            n = int(s.pop + 1 - s.infra)
            if n > 0:
                if plan.iu.get(s.id, 0) // K.INFRA_IU_COST < n:
                    pending = True              # can't afford all the infrastructure it wants
                plan.infra(s, n, "infrastructure doubles production", keep=0)
        if s.id in threatened:
            continue
        if s.pop >= K.POP_CAP - 0.6 and "EUS" not in s.artifacts and w.has_tech(12):
            if not plan.build_artifact(s, "EUS", "room to grow past 10", res):
                pending = True
        for key, gain in _artifact_gains(w, s):
            art = ARTIFACTS[key]
            if gain * ARTIFACT_PAYBACK > art.iu_cost + art.eu_cost + \
                    art.maint_eu * ARTIFACT_PAYBACK:
                if not plan.build_artifact(s, key, f"pays back (+{gain:.0f}/turn)", res + 40):
                    pending = True
    short = w.mem.setdefault("sp_short", {})
    for k in [k for k, t in short.items() if w.turn - t > 3]:
        del short[k]
    for sid in plan.cap_short:
        short[str(sid)] = w.turn
    plan.econ_pending = pending
    for s in sorted(w.populated, key=lambda s: (-s.pop, s.id)):
        if plan.new_ships[s.id] or plan.new_troops[s.id] or s.pop < 3:
            continue
        nxt = K.starport_cost(s.starport + 1) - K.starport_cost(s.starport)
        P = production(w, s)
        guard = s.id in threatened or s.id in shipyards
        border = ramped(w) and frontier(w, s)
        special = guard or border
        if pending:
            needed = str(s.id) in short
            if not needed and not (guard and s.starport < 4) and \
                    not (border and s.starport < 3):
                continue
            why = "bigger starport: the builds here need the capacity" if needed else \
                "bigger starport: defence of a frontier or shipyard"
        else:
            payback = 25 if special else 15
            if P * 0.1 * payback <= nxt * 2:
                continue
            why = "bigger starport: production and capacity"
        if plan.iu.get(s.id, 0) > nxt + 40:
            plan.build_starport(s, why, res + 40)


def _artifact_gains(w, s):
    P = production(w, s)
    iu_share, eu_share = s.csp[1] / 100.0, s.csp[2] / 100.0
    au_share = s.csp[0] / 100.0
    a = s.artifacts
    out = []
    eu_now = P * eu_share * (1.5 if "CB" in a else 1) * (1.5 if "VRB" in a else 1)
    iu_now = P * iu_share * (2 if s.mr else 1) * (1.5 if "CM" in a else 1) * \
        (1.5 if "AL" in a else 1)
    au_now = P * au_share * (2 if s.ar else 1)
    for key in ("CB", "VRB"):
        out.append((key, eu_now * 0.5))
    for key in ("CM", "AL"):
        out.append((key, iu_now * 0.5))
    for key in ("BF", "AF"):
        out.append((key, au_now * 0.5 * 0.7))     # AU only matters through happiness
    if s.pop >= 4:
        out.append(("EHC", P * 0.08))
        out.append(("CS", P * 0.15))
    return [(k, g) for k, g in out if k not in a and w.has_tech(ARTIFACTS[k].tech)]


def leaders(w, plan, admiral_fleet: str | None) -> None:
    free = sorted((ld for ld in w.leaders if ld.status == "limbo"),
                  key=lambda ld: (-ld.mgmt, ld.id))
    governed = {ld.system for ld in w.leaders if ld.system is not None}
    cands = sorted((s for s in w.populated if s.id not in governed and s.pop >= 3
                    and s.status == K.NORMAL), key=lambda s: (-s.pop, s.id))
    for ld in free:
        if admiral_fleet and ld.combat >= 70 and ld.combat >= ld.mgmt:
            if not any(x.fleet == admiral_fleet for x in w.leaders):
                plan.add("MLF", "an admiral for the war fleet", leader=ld.name,
                         fleet=admiral_fleet)
                admiral_fleet = None
                continue
        if cands and (ld.mgmt > 55 or ld.social > 70):
            s = cands.pop(0)
            plan.add("ML", "a governor for a big system", leader=ld.name, system=s.name)


# ---- research ---------------------------------------------------------------------------------

ECON = {3: 30, 2: 22, 11: 34, 5: 14, 12: 26, 21: 10, 23: 16, 31: 24, 33: 22, 34: 12, 43: 18,
        14: 10, 25: 8, 26: 4}
LINES = {6: "DEFENSIVE", 7: "OFFENSIVE", 8: "FAST"}


RESEARCH_MARGIN = 30      # EU kept beyond the upkeep reserve when buying a technology (was 60)
CRASH_MARGIN = 150        # and beyond that before crash research (was 300)
ARTIFACT_PAYBACK = 18     # turns a production artifact may take to pay back (was 12)
RAMP_PULL = 8             # research pull towards light cruisers (was 14)
MAX_TECHS_A_TURN = 5      # one PT and up to four crash programmes


def tech_score(w, t: int, pressed: bool, vp_push: bool = False) -> float:
    """What technology t is worth to us (before its price): victory points, economy, military,
    what it unlocks.  Research and tech trades (trade.py) both use it."""
    score = tech_vp(t) * 18 * w.persona["greed"] * (2.0 if vp_push else 1.0)
    score += ECON.get(t, 0) * (1.0 if w.turn < 60 else 0.6)
    score += _military_value(w, t) * (2.0 if pressed else 1.0) * \
        (0.5 + w.persona["aggression"] * 2)
    score += _unlock_value(w, t) * 0.4
    if hasattr(w, "home"):                     # FP/WT with a far front (G-24); a trade
        score += _portals.research_pull(w, t)  # valuer (trade._Valuer, TTNPR ANY) has no map
    if t == 21 and t not in w.techs and hasattr(w, "known"):   # routes we could set up (A-11)
        from . import ctt
        score += ctt.research_value(w)
    if t in RAMP_PATH and w.turn >= 12 and style(w.mem)["ramp_tier"] <= 1:
        score += RAMP_PULL * (0.5 + w.persona["aggression"] * 2)   # towards light cruisers
    return score


def research(w, plan, threatened: bool, at_war: bool, vp_push: bool) -> None:
    """One PT a turn on the best value for the money, then crash research (CRP, twice the
    cost, any number a turn, rules:342) while EUs are left over beyond a margin: money in the
    bank scores nothing (2026-11-15 runs: 2000-9000 EU and 30-130k IU idle late in the game).
    The purchases are chosen first; the dearest of them is then the PT and the rest the crash
    programmes (the cheapest way to buy the same set)."""
    res = reserve(w) + RESEARCH_MARGIN
    if plan.pt_done:                             # a tech trade takes this turn's purchase
        return
    pressed = threatened or at_war
    inc = max(1, income(w)[0])
    margin = (100 if vp_push else CRASH_MARGIN) + inc // 4
    budget = plan.eu - res
    picks: list[int] = []
    added: list[int] = []
    ft = False
    try:
        while len(picks) < MAX_TECHS_A_TURN:
            first = not picks
            t, value = _best_buy(w, plan, budget - (0 if first else margin), 1 if first else 2,
                                 pressed, vp_push, ft)
            if first:
                plan.tech_pending = _wanted_unaffordable(w, plan, res, t)
                if t is not None and trace.collecting():
                    trace.note("research_choice", tech=t, name=TECHS[t].name,
                               cost=TECHS[t].cost, value=round(value, 2), vp_push=vp_push,
                               threatened=threatened, at_war=at_war)
            if t is None:
                break
            picks.append(t)
            budget -= TECHS[t].cost * (1 if first else 2)
            if t == FUTURE_TECH:
                ft = True
            elif t not in w.techs:
                w.techs.add(t)
                added.append(t)
    finally:
        for t in added:                          # buy_tech adds them again as it buys
            w.techs.discard(t)
    if not picks:
        return
    pt = max(picks, key=lambda t: (TECHS[t].cost, -picks.index(t)))
    for t in picks:
        crash = t != pt
        plan.buy_tech(t, f"{'crash research' if crash else 'research'} {TECHS[t].name}", res,
                      crash=crash)


# The research floor (Dave 2026-11-16): at least RESEARCH_FLOOR of the EU income goes to research
# every turn, at war too, unless the home system is under attack this turn.  The share is set
# aside before war missions and defence spend (brain.decide), and what research can't use yet
# is saved for the next technology (memory `rsave`, at most `_save_cap`).
RESEARCH_FLOOR = 0.25


def _save_cap(w) -> int:
    inc = max(1, income(w)[0])
    cheapest = min((TECHS[t].cost for t in TECHS if t not in (0, FUTURE_TECH)
                    and t not in w.techs and not missing_prereqs(w.techs, t)), default=0)
    if not cheapest and len(w.techs) >= 50:
        cheapest = TECHS[FUTURE_TECH].cost
    return 0 if not cheapest else max(2 * inc, cheapest)


def research_hold(w, plan, home_attacked: bool) -> int:
    """Set the research floor aside: plan.eu is reduced by the held EUs (given back with
    `research_release` just before research)."""
    if home_attacked:
        return 0
    save = min(w.mem.get("rsave", 0) + RESEARCH_FLOOR * max(0, income(w)[0]), _save_cap(w))
    w.mem["rsave"] = int(save)
    hold = int(max(0, min(save, plan.eu - reserve(w))))
    plan.eu -= hold
    return hold


def research_release(w, plan, hold: int) -> None:
    plan.eu += hold


def research_after(w, plan, hold: int) -> None:
    """After research: what it spent comes off the savings; the rest of the savings stays in
    hand through the rest of the turn's spending."""
    if "rsave" not in w.mem:
        return
    left = max(0, w.mem["rsave"] - plan.spent.get("research", 0))
    w.mem["rsave"] = int(left)
    keep = int(max(0, min(left, plan.eu - reserve(w))))
    plan.eu -= keep


def _best_buy(w, plan, budget: float, mult: int, pressed: bool, vp_push: bool, ft_done: bool):
    """The technology worth most per cost (score / (cost/100)^0.6) that `budget` buys at
    `mult` times its cost, or (None, 0)."""
    best, bv = None, 0.0
    for t, tech in TECHS.items():
        if t == 0 or t in plan.no_buy:
            continue
        if t == FUTURE_TECH:
            if ft_done or len(w.techs) < 50:
                continue
        elif t in w.techs or missing_prereqs(w.techs, t):
            continue
        if tech.cost * mult > budget:
            continue
        v = tech_score(w, t, pressed, vp_push) / (tech.cost / 100.0) ** 0.6
        if v > bv:
            best, bv = t, v
    return best, bv


def _wanted_unaffordable(w, plan, res, best) -> bool:
    """Are we saving for a technology?  True when the technology we value most per cost (the
    choice research would make with the money) is out of reach this turn but within two turns'
    income: then the starport rule in `development` holds back."""
    top, tv = None, 0.0
    for t, tech in TECHS.items():
        if t in (0, FUTURE_TECH) or t in w.techs or missing_prereqs(w.techs, t):
            continue
        v = tech_score(w, t, False) / (tech.cost / 100.0) ** 0.6
        if v > tv:
            top, tv = t, v
    if top is None or top == best:
        return False
    cost = TECHS[top].cost
    return plan.eu - res < cost <= plan.eu - res + 2 * max(1, income(w)[0])


def _military_value(w, t: int) -> float:
    """New ship classes in a missing line type count most (Mixed Fleet Bonus x3 with all four,
    rules:819-833); otherwise the improvement in the best ship of the line."""
    v = 0.0
    lines_owned = {st.line for st in SHIP_TYPES.values() if st.attack > 0 and w.has_tech(st.tech)}
    for st in SHIP_TYPES.values():
        if st.tech != t or st.attack <= 0:
            continue
        if st.line not in lines_owned:
            v += 30
        best = max((x.attack * x.defense / (x.iu_cost + x.eu_cost) for x in SHIP_TYPES.values()
                    if x.line == st.line and x.attack > 0 and w.has_tech(x.tech)), default=0)
        mine = st.attack * st.defense / (st.iu_cost + st.eu_cost)
        if mine > best:
            v += min(40.0, 40 * (mine - best) / max(mine, 0.01))
    from ..data.troops import TROOP_TYPES
    for tt in TROOP_TYPES.values():
        if tt.tech == t:
            # assault troops matter once the bot means to take systems (dug-in defenders count
            # double, rules:591-593)
            v += (8 + tt.attack) * (1.5 if ship_tier(w) >= 1 else 1.0)
    if t in (5, 24, 44):                         # PD / SW / APD
        v += 10
    return v


def _unlock_value(w, t: int) -> float:
    v = 0.0
    for u, tech in TECHS.items():
        if u not in w.techs and t in tech.prereqs:
            v += ECON.get(u, 0) + _military_value(w, u) * 0.5 + tech_vp(u) * 8
    return v


def tech_vp_now(w) -> int:
    return sum(tech_vp(t) for t in w.techs if t)


__all__ = ["profiles", "development", "leaders", "research", "tech_score", "ramped",
           "ship_tier", "upkeep", "income", "reserve",
           "production", "au_needed", "research_hold", "research_release", "research_after",
           "dist"]
