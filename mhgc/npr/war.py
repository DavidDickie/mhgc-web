"""Warfare for the bot (rules:757-1060, 2118-2177, 3238-3295).

* Threat: the attack of scanned foreign warships that could reach each of our systems within two
  turns, weighted by our relations with their owner.  Troop carriers near a system count too.
* Garrisons sized to the threat (plus a small floor that grows with the game), built where they
  are needed or at the nearest system that can, and idle warships moved to where they are needed.
* Composition against what we have seen: ship choice weighs attack against defence by the enemy's
  observed make-up, and fills the line type we are short of for the Mixed Fleet Bonus (x3 with
  all four lines, rules:819-833).
* Ground defence: dug-in infantry (x2 defence), more when enemy transports are near.
* Upkeep cap: warship maintenance is kept under a personality share of income (rules:479-486),
  and warship plus troop upkeep under 40% of it in every mode, salvaging the weakest warships
  when far over (DECISIONS A-10).  A fleet threatens the systems it reaches first in full.
* Concentration of force and timing: one war fleet at a time, gathered at a staging system, and
  launched only when the engine's own combat code, run on our estimate of the target's defences
  (evalcombat.py), gives at least the personality's required chance of taking the system.
* Intercepts of enemy warships and troop carriers near our space when we can win the fight.
* Spies: see spycraft.py.
"""
from __future__ import annotations

from collections import Counter

from ..data import constants as K
from ..data.ships import DEFENSIVE, FAST, LINE_TYPES, OFFENSIVE, SHIP_TYPES, STANDARD
from ..data.troops import TROOP_TYPES
from .diplo import declare, leader, path_provokes, races_near
from .econ import income, ramped, reserve, style, upkeep
from .evalcombat import assault, fleet_vs_fleet
from .memory import log, race
from .trace import note
from . import portals
from .world import dist, est_ground, frontier, home_xy, turns_to

POSTURE_CODE = {"attack": "A", "defend": "D", "dug in": "E", "digging in [1st turn]": "E3",
                "digging in [2nd turn]": "E2", "digging in [last turn]": "E1"}


# ---------------------------------------------------------------------------------------------
# observation
# ---------------------------------------------------------------------------------------------

def observe_enemies(w) -> None:
    """Remember the make-up of each race's warships we have scanned (decaying)."""
    enemy = w.mem["enemy"]
    for e in enemy.values():
        e["att"] *= 0.9
        e["def"] *= 0.9
        for ln in e["lines"]:
            e["lines"][ln] *= 0.9
    for c in w.contacts:
        if c.st.attack <= 0:
            continue
        e = enemy.setdefault(str(c.owner), {"att": 0.0, "def": 0.0,
                                            "lines": {ln: 0.0 for ln in LINE_TYPES}, "t": 0})
        e["att"] += c.st.attack * 0.1
        e["def"] += c.st.defense * 0.1
        e["lines"][c.st.line] += c.st.attack * 0.1
        e["t"] = w.turn


def weight(w, rid: int) -> float:
    if rid in (0, w.eid) or w.allied(rid):
        return 0.0
    if w.at_war(rid):
        return 1.0
    r = w.mem["races"].get(str(rid))
    if r is not None and r["griev"] > 8:
        return 0.8
    return 0.35


def threats(w) -> dict:
    out = {}
    for s in w.populated:
        a = 0.0
        carriers = 0
        for c in w.contacts:
            wt = weight(w, c.owner)
            if wt <= 0:
                continue
            t = turns_to(c.st.move, dist(c.x, c.y, s.x, s.y))
            if t > 2:
                continue
            a += wt * c.st.attack / max(1, t)
            if c.st.cargo > 0 and (c.cts is None or c.cts > 0) and t <= 2:
                carriers += 1
        if s.status != K.NORMAL:
            a = max(a, 2.0)
        out[s.id] = {"attack": a, "carriers": carriers}
    return out


# ---------------------------------------------------------------------------------------------
# unit choice
# ---------------------------------------------------------------------------------------------

def available(w, min_move: int = 0) -> list:
    return [c for c, st in SHIP_TYPES.items() if st.attack > 0 and w.has_tech(st.tech)
            and st.move >= min_move]


# Ties for the line we are short of go in this order.  The fast line comes last (Dave
# 2026-11-19 ship rebalance): its ships are never the best buy even with the bonus, so in table
# order it took the bonus whenever it and the offensive line were both missing, and the bots
# never built a DeathStar.
SHORT_ORDER = (STANDARD, DEFENSIVE, OFFENSIVE, FAST)


def choose_ship(w, have_lines: dict, enemy_race=None, min_move: int = 0) -> str:
    """Best warship by observed enemy make-up, preferring the line type we are short of."""
    a = 0.5
    if enemy_race is not None:
        e = w.mem["enemy"].get(str(enemy_race))
        if e and e["att"] + e["def"] > 0:
            a = 0.3 + 0.4 * e["def"] / (e["att"] + e["def"])   # tough enemy -> more attack
    best, bv = "F", -1.0
    short = min(SHORT_ORDER, key=lambda ln: (have_lines.get(ln, 0), SHORT_ORDER.index(ln)))
    for code in available(w, min_move) or ["F"]:
        st = SHIP_TYPES[code]
        v = (st.attack ** a) * (st.defense ** (1 - a)) / (st.iu_cost + st.eu_cost) * 100
        if st.line == short:
            v *= 1.6
        if v > bv:
            best, bv = code, v
    return best


def best_troop(w, infantry: bool) -> str:
    """Dug-in defence per cost for garrisons; for assaults, attack (and some defence, since
    ground combat is simultaneous) per cost including its share of a transport (a troop takes
    one cargo point; a Transport carries 3 for 40)."""
    best, bv = "S", 0.0
    tcost = (SHIP_TYPES["T"].iu_cost + SHIP_TYPES["T"].eu_cost) / SHIP_TYPES["T"].cargo
    for code, tt in TROOP_TYPES.items():
        if code == "M" or not w.has_tech(tt.tech) or (infantry and not tt.infantry):
            continue
        v = (tt.defense * (2 if tt.infantry else 1)) / (tt.iu_cost + tt.eu_cost) if infantry \
            else (tt.attack + 0.5 * tt.defense) / (tt.iu_cost + tt.eu_cost + tcost)
        if v > bv:
            best, bv = code, v
    return best


def lines_at(ships) -> dict:
    out = {ln: 0 for ln in LINE_TYPES}
    for sh in ships:
        if sh.st.attack > 0:
            out[sh.st.line] += sh.st.attack
    return out


# ---------------------------------------------------------------------------------------------
# defence
# ---------------------------------------------------------------------------------------------

def mission_ships(w) -> set:
    out = set()
    for m in w.mem["missions"]:
        out.update(m.get("ships", []))
        out.update(m.get("transports", []))
    return out


def garrison_need(w, s, thr) -> float:
    big = 1.5 if (s.x, s.y) == home_xy() else 1.0 if s.pop >= 6 else 0.4
    floor = min(12.0, 0.12 * w.turn) * big * style(w.mem)["garrison"]
    if not frontier(w, s) and (s.x, s.y) != home_xy():
        floor *= 0.6                    # interior worlds need less standing guard
    return max(thr["attack"] * 1.4, floor)


def military_room(w, plan) -> int:
    """EUs a turn we may still add in warship upkeep: a personality share of income, smaller
    before the aggression ramp and larger after it (Dave 2026-11-15)."""
    inc, _ = income(w)
    up, _ = upkeep(w)
    st = style(w.mem)
    cap = w.persona["aggression"] * (st["post"] if ramped(w) else st["pre"]) * inc + 10
    if any(w.at_war(r) for r in w.contacted()):
        cap *= st["war_room"]
    ship_up = sum(2 if w.system_at(sh.x, sh.y) and w.system_at(sh.x, sh.y).mine else 5
                  for sh in w.ships if sh.st.attack > 0)
    room = int(cap - ship_up - 2 * sum(len(v) for v in plan.new_ships.values()))
    return min(room, hard_room(w, plan))


# The upkeep cap (Dave 2026-11-16): warship and garrison (troop) upkeep is held to about 40% of
# the EU income, in every mode (defence included: Freepeople spent over half its income on the
# upkeep of 61 warships).  Above SALVAGE_AT x the cap, the weakest and obsolete warships not
# needed where they stand are salvaged at a starport (SS: 75% back, rules:576-578).
MIL_CAP = 0.40
SALVAGE_AT = 1.2
SALVAGE_TO = 1.05
SALVAGE_MAX = 4           # a turn


def mil_upkeep(w) -> int:
    """EU upkeep of warships (2 at our systems, 5 elsewhere, rules:479-486) and troops."""
    up = 0
    for sh in w.ships:
        if sh.st.attack > 0:
            here = w.system_at(sh.x, sh.y)
            up += 2 if here is not None and here.mine else 5
    return up + sum(t.tt.maint_eu for t in w.troops)


def mil_cap(w) -> float:
    return MIL_CAP * max(1, income(w)[0])


def hard_room(w, plan) -> int:
    """EUs a turn of warship upkeep still under the cap, after this turn's planned builds."""
    new = 2 * sum(len(v) for v in plan.new_ships.values()) + \
        sum(TROOP_TYPES[c].maint_eu for v in plan.new_troops.values() for c in v)
    return int(mil_cap(w) - mil_upkeep(w) - new)


def focused_threats(w, thr: dict) -> dict:
    """The threat each system should be garrisoned against.  `threats` counts every enemy ship
    at every system it could reach; a fleet attacks one system at a time, so here a ship counts
    in full only at the systems nearest it (by turns), and a quarter elsewhere: the garrison is
    concentrated where the blow is likely, not spread over every world in reach."""
    out = {sid: 0.0 for sid in thr}
    for c in w.contacts:
        wt = weight(w, c.owner)
        if wt <= 0 or c.st.attack <= 0:
            continue
        reach = []
        for s in w.populated:
            t = turns_to(c.st.move, dist(c.x, c.y, s.x, s.y))
            if t <= 2:
                reach.append((t, s.id))
        if not reach:
            continue
        best = min(t for t, _ in reach)
        for t, sid in reach:
            out[sid] += wt * c.st.attack / max(1, t) * (1.0 if t == best else 0.25)
    for s in w.populated:
        if s.status != K.NORMAL:
            out[s.id] = max(out[s.id], 2.0)
    return {sid: {"attack": a, "carriers": thr[sid]["carriers"]} for sid, a in out.items()}


SYS_DEF = (("PD", 2.0), ("SW", 6.0), ("APD", 5.0))   # attack-equivalent of system defences


def _sys_defence(s) -> float:
    return sum(v for k, v in SYS_DEF if k in s.artifacts)


def _salvage(w, plan, have: dict, eff: dict, busy: set) -> None:
    """Salvage warships while upkeep is far over the cap: the least value per cost first (the
    obsolete ones), only at a NORMAL system with a free starport build, and only where the
    system keeps its garrison without the ship."""
    cap = mil_cap(w)
    up = mil_upkeep(w)
    if up <= SALVAGE_AT * cap:
        return
    best = max((st.attack * st.defense / (st.iu_cost + st.eu_cost)
                for st in SHIP_TYPES.values() if st.attack > 0 and w.has_tech(st.tech)),
               default=1.0)
    cands = []
    for sh in w.ships:
        if sh.st.attack <= 0 or sh.fleet is not None or sh.number in busy or \
                sh.number in plan.busy or sh.order not in ("STAND",) or sh.st.cargo > 0:
            continue
        s = w.system_at(sh.x, sh.y)
        if s is None or not s.mine or s.status != K.NORMAL or s.starport < 1:
            continue
        val = sh.st.attack * sh.st.defense / (sh.st.iu_cost + sh.st.eu_cost) / best
        cands.append((val, sh.st.attack, sh.number, sh, s))
    n = 0
    for val, _, _, sh, s in sorted(cands, key=lambda t: (t[0], t[1], t[2])):
        if n >= SALVAGE_MAX or up <= SALVAGE_TO * cap:
            break
        if have[s.id] - sh.st.attack < garrison_need(w, s, eff[s.id]):
            continue
        if plan.capacity(s) < 1:
            continue
        plan.builds[s.id] += 1
        plan.add("SS", f"salvage: upkeep {up} over {int(cap)} (cap)", ship=sh.number)
        plan.busy.add(sh.number)
        have[s.id] -= sh.st.attack
        up -= 2
        n += 1
        w.mem["stats"]["salvaged"] = w.mem["stats"].get("salvaged", 0) + 1


def defend(w, plan, thr: dict) -> dict:
    """Garrison builds, ground troops and moves of idle warships.  Returns per-system have."""
    busy = mission_ships(w) | plan.busy
    res = reserve(w)
    have = {}
    for s in w.populated:
        have[s.id] = sum(sh.st.attack for sh in w.ships if sh.st.attack > 0 and sh.fleet is None
                         and ((sh.x, sh.y) == (s.x, s.y) or ((sh.dx, sh.dy) == (s.x, s.y)
                                                             and sh.order in ("MS", "MOVE"))))
        have[s.id] += _sys_defence(s)
    eff = focused_threats(w, thr)
    order = sorted(w.populated, key=lambda s: (-(eff[s.id]["attack"] - have[s.id]), s.id))
    room = military_room(w, plan)
    for s in order:
        need = garrison_need(w, s, eff[s.id])
        hot = thr[s.id]["attack"] > 0 or s.status != K.NORMAL
        # ground first when carriers are near, ships first otherwise
        if thr[s.id]["carriers"] or hot:
            _ground(w, plan, s, thr[s.id], res // 2)
        if hot and have[s.id] < need:
            # system defences: a one-off cost and small upkeep, and they don't leave (rules:2695,
            # 2892, 2998)
            for key, v in SYS_DEF:
                if have[s.id] < need and plan.build_artifact(s, key, "defences for a threatened "
                                                                     "system", res // 2):
                    have[s.id] += v
        lines = lines_at([sh for sh in w.ships if (sh.x, sh.y) == (s.x, s.y)])
        enemy = _nearest_enemy_race(w, s)
        hard = hard_room(w, plan)
        while have[s.id] < need and (room > 0 or hot) and hard > 0:
            t = choose_ship(w, lines, enemy)
            if not plan.build_ship(s, t, "N", "MR", "garrison", res // (2 if hot else 1),
                                   purpose="defence"):
                break
            have[s.id] += SHIP_TYPES[t].attack
            lines[SHIP_TYPES[t].line] += SHIP_TYPES[t].attack
            room -= 2
            hard -= 2
        if not hot and w.turn > 6:
            _ground(w, plan, s, thr[s.id], res)
    portals.defence(w, plan, thr)            # spare troops by farcaster (G-24)
    # move idle warships to where they are needed most
    free = [sh for sh in w.ships if sh.st.attack > 0 and sh.fleet is None
            and sh.number not in busy and sh.order in ("STAND", "MS", "MOVE")]
    surplus = {s.id: have[s.id] - garrison_need(w, s, eff[s.id]) for s in w.populated}
    needy = sorted((s for s in w.populated if surplus[s.id] < 0),
                   key=lambda s: (surplus[s.id], s.id))
    for s in needy:
        # through a warp tunnel first, from tunnel systems with ships to spare, when sailing
        # would take WARP_MIN_TURNS or more (G-24)
        if "WT" not in s.artifacts:
            continue
        for sh in sorted(free, key=lambda x: (-x.st.attack, x.number)):
            if surplus[s.id] >= 0:
                break
            here = w.system_at(sh.x, sh.y)
            if here is None or not here.mine or here.id == s.id or \
                    surplus.get(here.id, 0) - sh.st.attack < 0 or \
                    (sh.x, sh.y) != (here.x, here.y) or not portals.worth_warping(sh, s) or \
                    not portals.can_warp(w, plan, sh, s):
                continue
            if portals.warp(w, plan, sh, s, "warp to a system under threat" if
                            thr[s.id]["attack"] > 0 else "warp to reinforce"):
                surplus[s.id] += sh.st.attack
                surplus[here.id] -= sh.st.attack
    for s in needy:
        donors = []
        for sh in free:
            here = w.system_at(sh.x, sh.y)
            src = here.id if here is not None and here.mine else None
            if src == s.id or sh.number in plan.busy:
                continue
            if src is not None and surplus.get(src, 0) - sh.st.attack < 0:
                continue
            d = dist(sh.x, sh.y, s.x, s.y)
            if turns_to(sh.st.move, d) > 4:
                continue
            if path_provokes(w, sh.st.move, sh.x, sh.y, s.x, s.y):
                continue                     # don't stop within a move of a neutral's worlds (A-12)
            donors.append((d, sh.number, sh, src))
        for d, _, sh, src in sorted(donors, key=lambda t: (t[0], t[1])):
            if surplus[s.id] >= 0:
                break
            if src is not None and surplus.get(src, 0) - sh.st.attack < 0:
                continue
            plan.add("MS", "reinforce" if thr[s.id]["attack"] <= 0 else
                     "HELP SYSTEM UNDER THREAT", ship=sh.number, system=s.name)
            plan.busy.add(sh.number)
            surplus[s.id] += sh.st.attack
            if src is not None:
                surplus[src] -= sh.st.attack
    _salvage(w, plan, have, eff, busy)
    # stragglers in space go to the nearest system
    for sh in free:
        if sh.number in plan.busy or sh.order != "STAND":
            continue
        here = w.system_at(sh.x, sh.y)
        if here is not None and here.mine:
            continue
        home = _safe_home(w, sh)
        if home is not None:
            plan.add("MS", "back to base", ship=sh.number, system=home.name)
            plan.busy.add(sh.number)
    # a warship of ours left within one move of the worlds of a race we are not at war with
    # (after an intercept, say) gives that race the A-12 reason for war: back to base
    for sh in w.ships:
        if sh.st.attack <= 0 or sh.fleet is not None or sh.number in plan.busy or \
                sh.number in busy:
            continue
        if sh.order == "INTERCEPT":
            # the chase goes on next turn: give it up if it could end near a neutral's worlds
            c = next((c for c in w.contacts if c.number == sh.target), None)
            if c is not None and not races_near(w, c.x, c.y, sh.st.move + c.st.move,
                                                {c.owner}) and \
                    not races_near(w, sh.x, sh.y, sh.st.move):
                continue
        elif not races_near(w, sh.x, sh.y, sh.st.move):
            continue
        if sh.order in ("MS", "MOVE") and any((x.x, x.y) == (sh.dx, sh.dy) for x in w.systems):
            continue                         # already on its way to one of ours
        home = _safe_home(w, sh)
        if home is not None and (home.x, home.y) != (sh.x, sh.y):
            plan.add("MS", "out of a neutral's reach", ship=sh.number, system=home.name)
            plan.busy.add(sh.number)
    return have


def _safe_home(w, sh):
    """The nearest of our systems the ship can reach without stopping within one move of a
    neutral's worlds (A-12); else simply the nearest."""
    pool = sorted(w.populated or w.systems, key=lambda s: (dist(sh.x, sh.y, s.x, s.y), s.id))
    for s in pool[:6]:
        if not path_provokes(w, sh.st.move, sh.x, sh.y, s.x, s.y):
            return s
    return pool[0] if pool else None


def _ground(w, plan, s, thr, res) -> None:
    mine = [t for t in s.troops if t["owner"] == w.eid]
    dfn = sum(TROOP_TYPES[t["type"]].defense * (2 if t["posture"] == "E" else 1) for t in mine)
    want = 2 + s.pop / 3 + 6 * thr["carriers"] + (4 if thr["attack"] > 0 else 0)
    if (s.x, s.y) == home_xy():
        want += 4
    while dfn < want:
        code = best_troop(w, True)
        if not plan.build_troop(s, code, "E", "dig in", res):
            break
        dfn += TROOP_TYPES[code].defense * 2


def _nearest_enemy_race(w, s):
    best, bd = None, None
    for c in w.contacts:
        if c.st.attack > 0 and weight(w, c.owner) >= 0.8:
            d = dist(c.x, c.y, s.x, s.y)
            if bd is None or d < bd:
                best, bd = c.owner, d
    return best


# ---------------------------------------------------------------------------------------------
# intercepts
# ---------------------------------------------------------------------------------------------

def intercepts(w, plan) -> None:
    busy = mission_ships(w) | plan.busy
    free = [sh for sh in w.ships if sh.st.attack > 0 and sh.fleet is None
            and sh.number not in busy and sh.order != "INTERCEPT"]
    targets = []
    for c in w.contacts:
        if not w.at_war(c.owner):
            continue
        d = w.dist_to_us(c.x, c.y)
        if d > 8:
            continue
        pri = (20 if c.st.cargo > 0 else 0) + c.st.attack * 2 - d
        targets.append((-pri, c.number, c))
    for _, _, c in sorted(targets):
        group = []
        for sh in sorted(free, key=lambda s: (dist(s.x, s.y, c.x, c.y), s.number)):
            if sh.number in plan.busy:
                continue
            dd = dist(sh.x, sh.y, c.x, c.y)
            if dd > 2 * sh.st.move or (sh.st.move < c.st.move and dd > sh.st.move):
                continue
            if path_provokes(w, sh.st.move, sh.x, sh.y, c.x, c.y, {c.owner}) or \
                    races_near(w, c.x, c.y, sh.st.move + c.st.move, {c.owner}):
                continue                     # the chase could end near a neutral's worlds (A-12)
            group.append(sh)
            if sum(g.st.attack for g in group) >= 2 * c.st.defense:
                break
        if not group:
            continue
        p = fleet_vs_fleet([g.type for g in group], [c.type], trials=4,
                           seed=w.turn * 7919 + c.number)
        w.mem["stats"]["evals"] += 1
        if p < 0.5:
            continue
        for g in group:
            plan.add("I", f"intercept enemy {c.type} ({p:.0%})", ship=g.number, target=c.number)
            plan.busy.add(g.number)


# ---------------------------------------------------------------------------------------------
# war missions
# ---------------------------------------------------------------------------------------------

PEACE_RESPITE = 20        # turns after a peace before that race is a target of our choosing
LAND_NEED = 0.5                                    # capture chance to land the troops
CONQUER_HELD = 0.5        # a conquest only of a race holding at most this share of our systems
WHY_VALUE = {"rebels": 1.3, "war": 1.2, "easy": 1.2, "conquest": 1.0}


def _enemy_at(w, s) -> list[str]:
    """Enemy warships we believe defend a target system: scanned now at or next to it."""
    out = [c.type for c in w.contacts if c.st.attack > 0 and c.owner != w.eid and
           not w.allied(c.owner) and dist(c.x, c.y, s.x, s.y) <= 1]
    return out


def _their_troops(s, carriers: int = 0, stale: int = 0) -> list:
    """The defenders' troops from our intel, plus what an alert owner adds before our troops
    land: it sees our transports coming and can build two troops a starport class a turn
    (rules:441-444), digging in; its best infantry we have seen.  The older our intel, the more
    it may have built meanwhile."""
    it = s.intel
    if not it:
        return [("S", "E"), ("S", "E"), ("M", "A"), ("M", "A")]
    out = [(typ, POSTURE_CODE.get(post, "A")) for owner, typ, post in it["troops"]
           if owner == it["owner"]]
    if it["owner"] and it["pop"] > 0 and (carriers or stale):
        seen = [typ for typ, _ in out if TROOP_TYPES[typ].infantry]
        typ = max(seen, key=lambda t: (TROOP_TYPES[t].defense, t)) if seen else "S"
        cap = 2 * max(1, it.get("starport") or 0)
        n = min(cap * 2, 3 * carriers) + min(cap, stale // 3)
        out += [(typ, "E3")] * min(10, n)
    return out


def evaluate(w, s, ships: list[str], troops: list[str], reinforce: bool = True) -> dict:
    """The engine's combat on our estimate.  With `reinforce`, the defender also gets what it can
    add before we land (it sees our transports coming), and what it may have built since our
    intel was taken."""
    it = s.intel
    carriers = sum(1 for t in ships if SHIP_TYPES[t].cargo > 0 and SHIP_TYPES[t].attack == 0)
    stale = (w.turn - it["t"]) if it else 0
    their = _their_troops(s, carriers if reinforce else 0, stale if reinforce else 0)
    r = assault(ships, troops, _enemy_at(w, s), their,
                it["pop"] if it else 6.0, it["weapons"] if it else [],
                defender=bool(it and it["owner"]) or bool(s.owner), trials=8,
                seed=w.turn * 104729 + s.id)
    w.mem["stats"]["evals"] += 1
    return r


def target_value(w, s) -> float:
    it = s.intel
    v = 2.0 * K.VP_PER_SYSTEM
    if it:
        v += it["pop"] * 0.6 + it["hab"] + 2 * it["artifacts"] + (2 if it["mr"] else 0)
    else:
        v += 4
    return v


def _standing(w, rid) -> float:
    r = w.mem["races"].get(str(rid))
    return (r["good"] - r["griev"]) if r else 0.0


def candidate_targets(w, ramp: bool | None = None) -> list:
    """(why, system): systems of races we are at war with and rebel worlds; before the ramp
    ("easy") very weak close neighbours for the bolder personalities; after it ("conquest") any
    contacted race we are not allied with, when its system is fresh in our intel (rules:250-252:
    how the NPR treats you depends on how you treat it and how well defended you are)."""
    if ramp is None:
        ramp = ramped(w)
    st = style(w.mem)
    out = []
    for s in w.known.values():
        it = s.intel
        owner = s.owner or (it["owner"] if it else None)
        if not owner:
            if it and it["pop"] > 0 and w.turn - it["t"] < 20:
                out.append(("rebels", s))
            continue
        if owner == w.eid or w.allied(owner) or owner not in w.races:
            continue
        r = w.mem["races"].get(str(owner)) or {}
        if w.at_war(owner):
            if not r.get("weary"):              # offering peace: no new attack on them
                out.append(("war", s))
            continue
        if w.turn - r.get("peace_t", -99) < PEACE_RESPITE:
            continue                            # a recent peace is kept
        if not it or w.turn - it["t"] >= 15 or it["pop"] <= 0:
            continue
        if not ramp:
            if st["easy"] and w.turn >= 15 and _standing(w, owner) < 2:
                out.append(("easy", s))
            continue
        out.append(("conquest", s))
    return out


def _need(w, why, owner) -> float:
    """The capture chance a mission needs: the personality's (lower after the ramp), or 0.9 for an
    easy prey or a neighbour in good standing."""
    p, st = w.persona, style(w.mem)
    base = st["need"] if ramped(w) else p["win_needed"]
    if why == "easy" or (why == "conquest" and _standing(w, owner) >= st["conquer_below"]):
        return max(base, 0.9)
    return base


def _min_move(d: int) -> int:
    """Slow ships (move 2) only join a war fleet for a short trip: the fleet moves at its slowest
    ship's speed (rules:1395)."""
    return 2 if d <= 6 else 3


def under_pressure(w, thr) -> bool:
    """Too threatened to send ships away: a system is under attack, or the warships of races at war
    with us (or that we hold grudges against) near our systems outweigh half our own."""
    if any(s.status != K.NORMAL for s in w.populated):
        return True
    serious = sum(c.st.attack for c in w.contacts if c.st.attack > 0 and weight(w, c.owner) >= 0.8
                  and w.dist_to_us(c.x, c.y) <= 2 * c.st.move)
    mine = sum(sh.st.attack for sh in w.ships if sh.st.attack > 0)
    return serious > 0.5 * mine


def _pool(w, plan, stage, d, ramp) -> list:
    busy = mission_ships(w) | plan.busy
    reach = 4 if ramp else 3
    mm = _min_move(d)
    return [sh for sh in w.ships if sh.st.attack > 0 and sh.fleet is None
            and sh.number not in busy and sh.st.move >= mm
            and turns_to(sh.st.move, dist(sh.x, sh.y, stage.x, stage.y)) <= reach]


def plan_missions(w, plan, rng, thr: dict) -> None:
    alive = []
    for m in w.mem["missions"]:
        if _advance(w, plan, m):
            alive.append(m)
    w.mem["missions"] = alive
    if w.turn < 8:
        return
    ramp = ramped(w)
    cap = style(w.mem)["missions"] if ramp else 1
    active = [m for m in alive if m["state"] != "hold"]
    if len(active) >= cap or under_pressure(w, thr):
        return
    stages = [s for s in w.populated if s.starport > 0 and s.status == K.NORMAL]
    if not stages:
        return
    free = [sh for sh in w.ships if sh.st.attack > 0 and sh.fleet is None
            and sh.number not in plan.busy and sh.number not in mission_ships(w)]
    if sum(sh.st.attack for sh in free) < 4:
        return
    hard = w.mem.setdefault("hard", {})
    for k in [k for k, t in hard.items() if t <= w.turn]:
        del hard[k]
    hard_race = w.mem.setdefault("hard_race", {})
    for k in [k for k, t in hard_race.items() if t <= w.turn]:
        del hard_race[k]
    taken = {m["target"] for m in alive}
    st = style(w.mem)
    lead = leader(w)
    held = Counter(x.owner for x in w.known.values() if x.owner)
    # after a conquest fleet sets out or takes a system, a few turns before the next attack of
    # our choosing is planned
    digesting = w.turn - w.mem.get("last_conquest", -99) < st["conquest_gap"]
    scored = []
    for why, s in candidate_targets(w, ramp):
        if s.id in taken or str(s.id) in hard:
            continue
        stage = min(stages, key=lambda x: (dist(x.x, x.y, s.x, s.y), x.id))
        d = dist(stage.x, stage.y, s.x, s.y)
        # a stage with a farcaster or warp tunnel (G-24) if it is nearly as close
        ported = [x for x in stages if ("FP" in x.artifacts or "WT" in x.artifacts)
                  and dist(x.x, x.y, s.x, s.y) <= d + portals.STAGE_SLACK]
        if ported and stage not in ported:
            stage = min(ported, key=lambda x: (dist(x.x, x.y, s.x, s.y), x.id))
            d = dist(stage.x, stage.y, s.x, s.y)
        limit = 22 if why in ("war", "rebels") else 10 if why == "easy" else st["range"]
        if d > limit:
            continue
        owner = s.owner or ((s.intel or {}).get("owner")) or 0
        if why in ("conquest", "easy") and str(owner) in hard_race:
            continue
        # a fleet that would stop within one move of a third race's worlds on the way (or at
        # the target) starts a war we didn't choose (A-12): another target
        if path_provokes(w, _min_move(d), stage.x, stage.y, s.x, s.y, {owner}):
            continue
        # value for the cost (Dave 2026-11-15, second round): rebels and unowned prize worlds
        # (militia only) and a clearly weak neighbour pay; a conquest of an equal is a grinding
        # war that costs research, so it is not started
        if why == "conquest" and held[owner] > CONQUER_HELD * len(w.systems):
            continue
        if digesting and (why == "conquest" or (why == "war" and race(
                w.mem, owner, w.turn).get("started", -1) >= 0)):
            continue                              # our own wars wait; defence doesn't
        v = target_value(w, s) / (1 + d / 4.0) * WHY_VALUE[why] * \
            (1.2 if owner and owner == lead and why == "war" else 1.0)
        pre = v / (1 + est_ground(s) / 8.0)        # weakly held worlds first
        scored.append((-pre, s.id, why, s, stage, d, owner, v))
    if not scored:
        return
    best = None
    troop = best_troop(w, False)
    for _, _, why, s, stage, d, owner, val in sorted(scored, key=lambda t: (t[0], t[1]))[:4]:
        pool = _pool(w, plan, stage, d, ramp)
        n = 9 if ramp else 6
        est = evaluate(w, s, [sh.type for sh in pool] + ["T"] * (n // 3), [troop] * n)
        need = _need(w, why, owner)
        score = val * min(1.0, est["capture"] / need) * (1.0 - 0.5 * est["lost"])
        if why == "easy" and est["capture"] < need:
            continue                              # only a sure thing before the ramp
        if est["capture"] < 0.4 * need:
            hard[str(s.id)] = w.turn + 8          # too strong for now: look elsewhere
            continue
        if best is None or score > best[0]:
            best = (score, why, s, stage, d, owner, pool, est, need)
    if best is None:
        return
    v, why, s, stage, d, owner, pool, est, need = best
    m = {"id": w.mem["stats"]["missions"] + 1, "target": s.id, "race": owner, "why": why,
         "stage": stage.id, "state": "gather", "start": w.turn, "fleet": "", "ships": [],
         "transports": [], "troop": troop, "troops": 9 if ramp else 6, "est": est["capture"],
         "need": need, "space": est["space"]}
    if est["capture"] < need * 0.6:
        m["state"] = "build"                      # not yet strong enough: build up at the stage
    note("mission_choice", target=s.id, race=owner, why=why, value=round(v, 2),
         stage=stage.id, distance=d, pool=len(pool), est_capture=round(est["capture"], 2),
         need=need, state=m["state"], ramped=ramp, active=len(active))
    w.mem["stats"]["missions"] += 1
    w.mem["missions"].append(m)
    log(w.mem, w.turn, "mission", race=owner, target=s.id, why=why, est=round(est["capture"], 2))
    _advance(w, plan, m)


def _ship(w, n):
    for sh in w.ships:
        if sh.number == n:
            return sh
    return None


def _advance(w, plan, m) -> bool:
    s = w.sys_by_id(m["target"])
    stage = w.sys_by_id(m["stage"])
    if m["state"] == "hold":
        return _hold(w, plan, m, s)
    if s is None or stage is None or not stage.mine:
        log(w.mem, w.turn, "mission_abort", target=m["target"], why="lost the stage")
        return False
    if s.mine:
        return _captured(w, plan, m, s)
    owner = s.owner or ((s.intel or {}).get("owner")) or 0
    if owner and w.allied(owner):
        _done(w, plan, m, "now an ally")
        return False
    if owner and owner != (m.get("race") or 0) and not w.at_war(owner):
        # the target changed hands (a rebel or empty world settled by a third race): not a
        # war we chose, and arriving there would be the A-12 reason for theirs
        f = next((f for f in w.fleets if f.name == m.get("fleet")), None)
        if f is not None and m["state"] in ("move", "siege", "assault"):
            for x in f.ships:
                plan.busy.add(x)
            _withdraw(w, plan, m, f, stage, s, owner, "target changed hands")
            return True
        if m["state"] in ("build", "gather"):
            _done(w, plan, m, "target changed hands")
            return False
    if m["state"] in ("build", "gather"):
        return _gather(w, plan, m, s, stage)
    f = next((f for f in w.fleets if f.name == m["fleet"]), None)
    if f is None:
        log(w.mem, w.turn, "mission_lost", target=m["target"])
        return False
    members = [x for x in (_ship(w, n) for n in f.ships) if x is not None]
    for x in members:
        plan.busy.add(x.number)
    aboard = [t for x in members for t in x.cargo[3]]
    landed = [t for t in w.troops if t.system == s.id]
    armed = sum(x.st.attack for x in members)
    if m["state"] == "return":
        if (f.x, f.y) == (stage.x, stage.y) or f.order == "STAND" or \
                w.turn - m.get("ret_t", w.turn) > 8:
            here = w.system_at(f.x, f.y)
            if here is not None and here.mine:
                for x in members:
                    for t in x.cargo[3]:
                        plan.add("LACT", "troops back on the ground", ship=x.number, ct=t)
            plan.add("DF", "back home", fleet=f.name)
            return False
        return True
    if armed == 0 or (not aboard and not landed and m["state"] == "assault") or \
            w.turn - m.get("launched", w.turn) > 14:
        _withdraw(w, plan, m, f, stage, s, owner, "failed")
        return True
    if (f.x, f.y) != (s.x, s.y):
        return True
    if m["state"] == "move":
        m["state"], m["siege"] = "siege", w.turn
    if m["state"] == "siege" and aboard:
        # in orbit: our short scan shows the defenders now; land when the odds are good
        # (the fleet's armed ships bombard while they wait: OF role, rules:899-901, 769-772)
        types = {t.number: t.type for t in w.troops}
        ours = [types[n] for n in aboard if n in types] + [t.type for t in landed]
        est = evaluate(w, s, [x.type for x in members], ours, reinforce=False)
        m["est"] = round(est["capture"], 2)
        waited = w.turn - m["siege"]
        if est["capture"] >= LAND_NEED or (waited >= 2 and est["capture"] >= 0.3):
            m["state"] = "assault"
        elif waited >= 2 or (waited >= 1 and est["capture"] < 0.15):
            w.mem.setdefault("hard", {})[str(s.id)] = w.turn + 10
            _withdraw(w, plan, m, f, stage, s, owner, "too strong to land")
            return True
        else:
            note("mission_siege", target=s.id, est=m["est"], waited=waited)
            return True
    if m["state"] in ("assault", "siege"):
        m["state"] = "assault"
        for x in members:
            for t in x.cargo[3]:
                plan.add("LACT", "land the assault troops", ship=x.number, ct=t)
    return True


def _withdraw(w, plan, m, f, stage, s, owner, why) -> None:
    plan.add("MFS", "the attack failed; withdraw", fleet=f.name, system=stage.name)
    m["state"], m["ret_t"] = "return", w.turn
    log(w.mem, w.turn, "mission_failed", target=s.id, race=owner, why=why)


def _captured(w, plan, m, s) -> bool:
    """Taken: the fleet breaks up and its warships hold the new system for a few turns (they
    count as its garrison); remaining troops aboard land there."""
    f = next((f for f in w.fleets if f.name == m["fleet"]), None)
    hold = []
    if f is not None:
        members = [x for x in (_ship(w, n) for n in f.ships) if x is not None]
        for x in members:
            for t in x.cargo[3]:
                plan.add("LACT", "garrison the capture", ship=x.number, ct=t)
            if x.st.attack > 0 and (x.x, x.y) == (s.x, s.y):
                hold.append(x.number)
            plan.busy.add(x.number)
        plan.add("DF", "mission over: captured", fleet=f.name)
    w.mem["stats"]["captures"] += 1
    if m["race"]:
        w.mem["last_conquest"] = w.turn
    log(w.mem, w.turn, "mission_captured", target=m["target"], race=m["race"])
    m.update(state="hold", hold_until=w.turn + 3, ships=hold, transports=[], fleet="")
    return True


def _hold(w, plan, m, s) -> bool:
    if s is None or not s.mine or w.turn >= m.get("hold_until", 0):
        return False
    m["ships"] = [n for n in m["ships"] if _ship(w, n) is not None]
    for n in m["ships"]:
        plan.busy.add(n)
    return bool(m["ships"])


def _done(w, plan, m, result):
    f = next((f for f in w.fleets if f.name == m["fleet"]), None)
    if f is not None:
        plan.add("DF", f"mission over: {result}", fleet=f.name)
    log(w.mem, w.turn, "mission_" + result.replace(" ", "_"), target=m["target"],
        race=m["race"])


def _gather(w, plan, m, s, stage) -> bool:
    ramp = ramped(w)
    if w.turn - m["start"] > (12 if ramp else 16):
        log(w.mem, w.turn, "mission_abort", target=s.id, why="took too long")
        w.mem.setdefault("hard", {})[str(s.id)] = w.turn + 6
        return False
    res = reserve(w) // 2
    m["ships"] = [n for n in m["ships"] if _ship(w, n) is not None]
    m["transports"] = [n for n in m["transports"] if _ship(w, n) is not None]
    busy = mission_ships(w)
    d = dist(stage.x, stage.y, s.x, s.y)
    mm = _min_move(d)
    reach = 4 if ramp else 3
    # claim free warships near the stage (fast enough for the trip); with warp tunnels at the
    # stage and the hub, the hub's spare warships come through the tunnel (G-24)
    hub = portals.hub(w)
    hub_spare = 0.0
    if hub is not None and "WT" in stage.artifacts and "WT" in hub.artifacts and \
            hub.id != stage.id:
        t_hub = plan.thr.get(hub.id, {"attack": 0, "carriers": 0})
        if t_hub["attack"] <= 0:
            hub_spare = sum(x.st.attack for x in w.ships_at(hub.x, hub.y)
                            if x.st.attack > 0 and x.fleet is None) + _sys_defence(hub) - \
                garrison_need(w, hub, t_hub)
    for sh in sorted(w.ships, key=lambda x: (dist(x.x, x.y, stage.x, stage.y), x.number)):
        if sh.st.attack <= 0 or sh.fleet is not None or sh.number in plan.busy or \
                sh.number in busy or sh.st.move < mm:
            continue
        here = w.system_at(sh.x, sh.y)
        if hub_spare >= sh.st.attack and here is not None and here.id == hub.id and \
                portals.worth_warping(sh, stage) and portals.can_warp(w, plan, sh, stage):
            if portals.warp(w, plan, sh, stage, "warp to the war fleet"):
                hub_spare -= sh.st.attack
                m["ships"].append(sh.number)
                continue
        if turns_to(sh.st.move, dist(sh.x, sh.y, stage.x, stage.y)) > reach:
            continue
        if here is not None and here.mine and here.id != stage.id and here.status != K.NORMAL:
            continue
        if path_provokes(w, sh.st.move, sh.x, sh.y, stage.x, stage.y,
                         {m["race"]} if m.get("race") and w.at_war(m["race"]) else set()):
            continue                         # not past a neutral's worlds (A-12)
        m["ships"].append(sh.number)
        if (sh.x, sh.y) != (stage.x, stage.y):
            plan.add("MS", "join the war fleet", ship=sh.number, system=stage.name)
        plan.busy.add(sh.number)
    # transports
    tcap = sum(_ship(w, n).st.cargo for n in m["transports"])
    for sh in w.ships:
        if tcap >= m["troops"]:
            break
        if sh.st.cargo > 0 and sh.st.attack == 0 and sh.fleet is None and \
                sh.number not in plan.busy and sh.number not in busy and sh.order == "STAND" \
                and str(sh.number) not in w.mem["claims"] and plan.free_points(sh) == sh.st.cargo:
            m["transports"].append(sh.number)
            tcap += sh.st.cargo
            if (sh.x, sh.y) != (stage.x, stage.y):
                plan.add("MS", "assault transport to the stage", ship=sh.number,
                         system=stage.name)
            plan.busy.add(sh.number)
    ground_ok = m.get("space", 1.0) >= 0.6     # troops only once space looks winnable
    for _ in range(2 if ground_ok else 0):
        if tcap >= m["troops"] or not plan.build_ship(stage, "T", "F", "RD", "assault transport",
                                                       res, purpose="war"):
            break
        tcap += SHIP_TYPES["T"].cargo
    def _ground_here():
        return [t for t in w.troops if t.system == stage.id and t.ship is None and t.type != "M"
                and t.number not in plan.moved_troops]       # (another fleet may load some)
    if ground_ok:                              # spare troops from the rear by farcaster (G-24)
        portals.troops_to_stage(w, plan, stage, m["troops"] + 1 - len(_ground_here()),
                                plan.thr)
    ground = _ground_here()
    attackers = sorted(ground, key=lambda t: (-t.tt.attack, t.number))
    short = m["troops"] + 1 - len(attackers)
    built = 0
    for _ in range(min(4, short) if ground_ok else 0):
        if not plan.build_troop(stage, m["troop"], "A", "assault troops", res):
            break
        built += 1
    if ground_ok and short - built > 0:        # the stage's starport ran out: build at the hub
        portals.troops_to_build_at_hub(w, plan, stage, m["troop"], short - built, res)
    # more warships of the line we lack, while the upkeep allows
    ships = [_ship(w, n) for n in m["ships"]]
    lines = lines_at(ships)
    # (only while space isn't already won: beyond that, warships don't take the ground)
    if military_room(w, plan) > 0 and m.get("space", 0.0) < 0.9:
        t = choose_ship(w, lines, m["race"] or None, min_move=mm)
        plan.build_ship(stage, t, "N", "MR", "for the war fleet", res, purpose="war")
    # ready?  evaluate with what is actually at the stage
    here = [x for x in ships if (x.x, x.y) == (stage.x, stage.y)]
    trans = [_ship(w, n) for n in m["transports"]]
    trans = [x for x in trans if (x.x, x.y) == (stage.x, stage.y)]
    loadable = attackers[:max(0, len(attackers) - 1)][:sum(x.st.cargo for x in trans)]
    if not here or not trans or len(loadable) < 2 or stage.status != K.NORMAL:
        return True
    full = len(loadable) >= m["troops"]
    est = evaluate(w, s, [x.type for x in here] + [x.type for x in trans],
                   [t.type for t in loadable])
    m["est"] = round(est["capture"], 2)
    m["space"] = est["space"]
    need = m.get("need", w.persona["win_needed"])
    if est["capture"] < need or (not full and est["capture"] < 0.95):
        if full and est["space"] >= 0.8 and m["troops"] < 15:
            m["troops"] += 3                      # space is won; the ground needs more troops
        if w.turn - m["start"] > 8 and est["capture"] < 0.5 * need:
            log(w.mem, w.turn, "mission_abort", target=s.id, why="too strong", est=m["est"])
            w.mem.setdefault("hard", {})[str(s.id)] = w.turn + 10
            if m["race"] and m["why"] != "war":   # its other worlds are likely as well held
                w.mem.setdefault("hard_race", {})[str(m["race"])] = w.turn + 8
            return False
        return True
    speed = min([x.st.move for x in here + trans] or [1])
    if path_provokes(w, speed, stage.x, stage.y, s.x, s.y, {m["race"] or 0}):
        # the fleet would stop within one move of a third race's worlds (A-12): not this one
        log(w.mem, w.turn, "mission_abort", target=s.id, why="would provoke a neutral")
        w.mem.setdefault("hard", {})[str(s.id)] = w.turn + 10
        return False
    _launch(w, plan, m, s, stage, here, trans, loadable)
    return True


def _launch(w, plan, m, s, stage, here, trans, troops) -> None:
    owner = m["race"]
    if owner and not w.at_war(owner):
        # a conquest is an open war: declared as the fleet sets out
        declare(w, plan, owner, m["why"], CONQUEST_NOTICE)
    if m["why"] == "conquest" or (owner and race(w.mem, owner, w.turn).get("started", -1) >= 0):
        w.mem["last_conquest"] = w.turn
    slots = []
    for x in trans:
        slots += [x] * plan.free_points(x)
    for t, x in zip(troops, slots):
        plan.add("LOCT", "load the assault troops", ship=x.number, ct=t.number)
        plan.cargo_of(x)[3] += 1
        plan.moved_troops.add(t.number)
    name = f"W{w.eid}M{m['id']}"[:12]
    plan.add("CF", "form the war fleet", name=name, x=stage.x, y=stage.y)
    members = [x.number for x in here + trans]
    for i in range(0, len(members), 10):
        plan.add("AF", "", fleet=name, ships=members[i:i + 10])
    plan.add("CFCR", "", fleet=name, role="OF")
    plan.add("CFP", "", fleet=name, posture="AH")
    plan.add("MFS", f"attack {s.name} ({m['est']:.0%})", fleet=name, system=s.name)
    for n in members:
        plan.busy.add(n)
    m.update(state="move", fleet=name, ships=[x.number for x in here],
             transports=[x.number for x in trans], launched=w.turn)
    log(w.mem, w.turn, "fleet_launched", target=s.id, race=m["race"], fleet=name,
        est=m["est"])


CONQUEST_NOTICE = ("Your defences are a disgrace and your worlds are wasted on you.  Our fleet is "
                   "on its way.  Surrender is not required, but it would save time.")


def note_grievances_from_war(w) -> None:
    for m in w.mem["missions"]:
        if m["race"]:
            race(w.mem, m["race"], w.turn)


__all__ = ["threats", "focused_threats", "mil_upkeep", "mil_cap", "hard_room", "defend", "intercepts", "plan_missions", "observe_enemies",
           "choose_ship", "best_troop", "evaluate", "candidate_targets", "mission_ships"]
