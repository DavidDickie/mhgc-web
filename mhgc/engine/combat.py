"""Turn phase 8: combat — ship to ship, ship to ground (bombardment and raids), ground to ground,
system status and capture (rules:757-1060; gccombat.c; ENGINE_MAP 4.3-4.4).

The structure is the C engine's; the arithmetic is the rules' where they give it (DECISIONS §2 #2, #23,
#25-28 and §3 table 4.12).  Summary of one combat at a square:

1. Participants: owners of ships there, the system owner, owners of troops on the system.
2. Each empire's posture is that of its most aggressive ship (rules:488-490); an empire that has
   declared an alliance with another behaves Friendly toward it (rules:716-722); war means both
   attack without initiative (rules:750-754).  The posture table (rules:492-505) gives, per pair,
   no attack, a mutual attack, or an attack with initiative.
3. Roles (rules:796-817): SC fires in space; MR joins SC if the enemy has any defence, otherwise
   it bombards at half attack; if SC is still below the enemy's total defence, GC then RD ships
   shift to SC one at a time in random order, at half attack.
4. Mixed Fleet Bonus multiplies the space attack (rules:819-833).  System weapons: PD and SW
   subtract 1 and 5 from each hostile empire's attack; SW (1) and APD (5) fire for the owner
   (rules:2695-2699, 2890-2896, 2998-3008).
5. Effective attack = sqrt(random 1..SC^2), at least 1.  Initiative attacks happen first and
   their kills don't fire back; then all other attacks are simultaneous.  Targets in order of
   combat role SC, MR, GC, RD (random within a role); each kill uses the target's defence; the
   last partial shot kills with chance remaining/defence.
6. Bombardment (GC): 4 points per point of effective troop defence, else attack/(5*defence);
   PD and APD each halve its effect; 25% of hits find shelter in caves.  Raids (RD): 1 pop per 25
   points, and per 5 points one infrastructure, part of an artifact, 10 IU or 10 AU.
7. Ground combat: simultaneous, same sqrt algorithm; capture if no defending troops remain.
8. Status: normal / under attack / interdicted from the attack:defence ratios, one step a turn.
"""
from __future__ import annotations

import math
from typing import Optional

from ..data import constants as K
from ..data.artifacts import ARTIFACTS
from ..data.flavour import (ADMIRAL_TEXT, EFFECTIVENESS, GOVERNOR_TEXT, MISS_TEXT,
                            SYS_STATUS_TEXT)
from ..data.ships import LINE_TYPES
from ..data.techs import TECHS
from ..model import Ship, System, Troop
from ..results import CombatLog
from .context import TurnContext
from .orders_exec import destroy_ship
from .scans import remember

ROLE_ORDER = {"SC": 0, "MR": 1, "GC": 2, "RD": 3}
POSTURE_RANK = {"H": 0, "N": 1, "F": 2}


def find_combats(ctx: TurnContext) -> None:
    """Combat flagging (gcrun.c:1066-1228): any square where ships of different empires meet, or
    a ship is at another empire's populated system; then systems with hostile troops on them."""
    st = ctx.state
    by_square: dict[tuple, list[Ship]] = {}
    for sh in st.live_ships():
        by_square.setdefault((sh.x, sh.y), []).append(sh)
    done_systems = set()
    for (x, y), ships in by_square.items():
        owners = {s.owner for s in ships}
        s = st.system_at(x, y)
        conflict = len(owners) > 1
        if s is not None and (s.owner not in owners or len(owners) > 1) and \
                (s.pop > 0 or s.owner != 0):
            conflict = True                 # incl. another empire's empty, troop-held system
        if s is not None and any(t.owner not in owners | {s.owner}
                                 for t in st.troops_at(s.id)):
            conflict = True
        if s is not None and _hostile_troops(ctx, s):
            conflict = True
        if conflict:
            if s is not None:
                done_systems.add(s.id)
            Combat(ctx, x, y, s).run()
    for s in st.systems:
        if s.id not in done_systems and _hostile_troops(ctx, s):
            Combat(ctx, s.x, s.y, s).run()


def _hostile_troops(ctx, s: System) -> bool:
    """Foreign troops on a system that are not mutually allied with the owner, or two foreign
    troop groups that are not mutually allied with each other (gcrun.c:1182-1228)."""
    owners = sorted({t.owner for t in ctx.state.troops_at(s.id)})
    def allies(a, b):
        return ctx.allied(a, b) and ctx.allied(b, a)
    for a in owners:
        if a != s.owner and not allies(a, s.owner):
            return True
    for i, a in enumerate(owners):
        for b in owners[i + 1:]:
            if not allies(a, b):
                return True
    return False


class Combat:
    def __init__(self, ctx: TurnContext, x: int, y: int, system: Optional[System]):
        self.ctx = ctx
        self.st = ctx.state
        self.rng = ctx.rng
        self.x, self.y, self.sys = x, y, system
        self.ships = [s for s in self.st.live_ships() if (s.x, s.y) == (x, y)]
        self.troops = self.st.troops_at(system.id) if system is not None else []
        parts = {s.owner for s in self.ships} | {t.owner for t in self.troops}
        if system is not None and (system.pop > 0 or system.owner != 0):
            parts.add(system.owner)
        self.parts = sorted(parts)
        self.log = CombatLog(len(ctx.res.combats), x, y, system.id if system else None,
                             participants=list(self.parts))
        self.roles: dict[int, tuple[str, int]] = {}   # ship number -> (effective role, points)
        self.assigned: set[int] = set()
        self.fleet_losses: dict[int, list] = {}
        self.killed_ships: list[Ship] = []

    # ---- helpers ----------------------------------------------------------------------
    def say(self, phase: str, text: str, **data):
        self.log.lines.append({"phase": phase, "text": text, **data})

    def name(self, e):
        return self.ctx.name(e)

    def mutual_allies(self, a, b) -> bool:
        return self.ctx.allied(a, b) and self.ctx.allied(b, a)

    def agg(self, e) -> str:
        ps = [s.posture for s in self.ships if s.owner == e and s.alive]
        return min(ps, key=POSTURE_RANK.get) if ps else "F"

    def leader_mult(self, sh: Ship) -> float:
        if sh.fleet is not None:
            f = self.st.fleets.get(sh.fleet)
            if f is not None and f.alive and (f.x, f.y) == (sh.x, sh.y):
                adm = self.st.admiral(f.number)
                return (adm.combat + 50) / 100.0 if adm and adm.owner == sh.owner else 1.0
            return 1.0
        if self.sys is not None and self.sys.owner == sh.owner:
            gov = self.st.governor(self.sys.id)
            if gov is not None and gov.owner == sh.owner:
                return (gov.combat + 50) / 100.0
        return 1.0

    def eff_attack(self, sh: Ship) -> int:
        return int(sh.stype.attack * self.leader_mult(sh))

    def eff_defense(self, sh: Ship) -> int:
        return max(1, int(sh.stype.defense * self.leader_mult(sh)))

    def attacks_system(self, e) -> bool:
        """'Set to attack the system' (rules:927-930): hostile, or at war with the owner."""
        s = self.sys
        if s is None or e == s.owner:
            return False
        if self.ctx.at_war(e, s.owner) or self.ctx.at_war(s.owner, e):
            return True
        return self.agg(e) == "H" and not self.ctx.allied(e, s.owner)

    # ---- relations (rules:492-505, 716-754) -------------------------------------------
    def relation(self, a, b):
        """None, 'mutual', or ('init', attacker)."""
        key = (min(a, b), max(a, b))
        if key in self._rel:
            return self._rel[key]
        r = None
        if self.ctx.at_war(a, b) or self.ctx.at_war(b, a):
            r = "mutual"
        elif self.mutual_allies(a, b):
            r = None
        else:
            pa = "F" if self.ctx.allied(a, b) else self.agg(a)
            pb = "F" if self.ctx.allied(b, a) else self.agg(b)
            pair = (pa, pb)
            if "H" in pair:
                if pa == "F":
                    r = ("init", b)
                elif pb == "F":
                    r = ("init", a)
                else:
                    r = "mutual"
            elif pair in K.ATTACK_CHANCE:
                r = "mutual" if self.rng.chance(K.ATTACK_CHANCE[pair]) else None
            else:
                r = None
        self._rel[key] = r
        return r

    def enemies(self, e) -> list[int]:
        return [b for b in self.parts if b != e and self.relation(e, b) is not None]

    # ---- role assignment -----------------------------------------------------------
    def assign_roles(self, e) -> None:
        if e in self.assigned:
            return
        self.assigned.add(e)
        mine = [s for s in self.ships if s.owner == e and s.alive]
        enemy_def = sum(self.eff_defense(s) for s in self.ships if s.alive and s.owner in
                        self.enemies(e))
        sc = 0
        for sh in mine:
            a = self.eff_attack(sh)
            if sh.role == "SC":
                self.roles[sh.number] = ("SC", a)
                sc += a
            elif sh.role == "MR":
                if enemy_def > 0:
                    self.roles[sh.number] = ("SC", a)
                    sc += a
                else:
                    self.roles[sh.number] = ("GC", a // 2)      # rules:769-772
            else:
                self.roles[sh.number] = (sh.role, a)
        if sc < enemy_def:
            for role in ("GC", "RD"):
                cand = [s for s in mine if s.role == role and self.eff_attack(s) > 0]
                self.rng.shuffle(cand)
                for sh in cand:
                    if sc >= enemy_def:
                        break
                    pts = self.eff_attack(sh) // 2              # rules:816-817
                    self.roles[sh.number] = ("SC", pts)
                    sc += pts

    def pool(self, e, role) -> int:
        return sum(self.roles[s.number][1] for s in self.ships
                   if s.owner == e and s.alive and s.number in self.roles
                   and self.roles[s.number][0] == role)

    def mfb(self, e) -> float:
        """Mixed Fleet Bonus ratio (gccombat.c:2105-2160, which reproduces rules:827-832)."""
        lines = {lt: 0 for lt in LINE_TYPES}
        for s in self.ships:
            if s.owner == e and s.alive and s.stype.attack > 0:
                lines[s.stype.line] += s.stype.attack
        n = sum(lines.values())
        if n == 0:
            return 1.0
        vals = list(lines.values())
        total = 0
        while any(v > 0 for v in vals):
            m = sum(1 for v in vals if v > 0)
            total += {4: 12, 3: 6, 2: 3, 1: 1}[m]
            vals = [v - 1 if v > 0 else 0 for v in vals]
        return total / n

    def space_attack(self, e) -> int:
        self.assign_roles(e)
        sc = self.pool(e, "SC")
        ratio = self.mfb(e)
        sc = int(sc * ratio)
        s = self.sys
        if s is not None:
            if s.owner == e:
                sc += sum(v for k, v in K.SYSTEM_WEAPON_ATTACK.items() if s.has(k))
            elif self.attacks_system(e):
                red = (K.PD_ATTACK_REDUCTION if s.has("PD") else 0) + \
                      (K.SW_ATTACK_REDUCTION if s.has("SW") else 0)
                sc = max(0, sc - red)
        return sc

    def roll_effective(self, e, sc) -> int:
        if sc <= 0:
            self.say("space", f"The WUSSY {self.name(e)} attack fleet has no space attack!",
                     race=e)
            return 0
        val = math.sqrt(self.rng.between(1, sc * sc))
        eff = max(1, int(val))
        pct = val * 100.0 / sc
        word = next(w for lim, w in EFFECTIVENESS if pct < lim)
        self.say("space", f"The dreaded {self.name(e)} gets a {word} {pct:2.0f}% effectiveness "
                 f"during combat", race=e, attack=sc, effective=eff)
        r = self.mfb(e)
        if r > 1:
            self.say("space", f"{self.name(e)} mixed fleet bonus is {r:.2f}", race=e)
        return eff

    # ---- firing --------------------------------------------------------------------
    def targets(self, empires) -> list[Ship]:
        cand = [s for s in self.ships if s.alive and s.owner in empires]
        keys = {s.number: self.rng.random() for s in cand}
        return sorted(cand, key=lambda s: (ROLE_ORDER[s.role], keys[s.number]))

    def fire(self, attacker, sc, targets, init: bool, kills: list) -> int:
        for t in targets:
            if sc <= 0:
                break
            if not t.alive or t.number in {k.number for k in kills}:
                continue
            d = self.eff_defense(t)
            if sc >= d:
                sc -= d
                kills.append(t)
                self.say("space", f"{self.name(t.owner)} {t.stype.name} {t.number} DESTROYED by "
                         f"{self.name(attacker)}" + (" without return fire!!!" if init else "!"),
                         ship=t.number, by=attacker)
            else:
                w = 100.0 * sc / d
                roll = self.rng.random() * 100
                if roll < w:
                    kills.append(t)
                    self.say("space", f"{self.name(t.owner)} {t.stype.name} {t.number} DESTROYED"
                             f" by {self.name(attacker)}" +
                             (" without return fire!!!" if init else "!") +
                             f"[{int(roll)}/{int(w)}]", ship=t.number, by=attacker)
                else:
                    r = w / max(roll, 1e-9)
                    txt = next(m for lim, m in MISS_TEXT if r < lim)
                    self.say("space", f"{self.name(t.owner)} {t.stype.name} {t.number} {txt}"
                             f"[{int(roll)}/{int(w)}]", ship=t.number)
                sc = 0
        return sc

    def kill_ship(self, sh: Ship):
        if not sh.alive:
            return
        destroy_ship(self.ctx, sh)
        self.killed_ships.append(sh)
        if sh.fleet is not None:
            self.fleet_losses.setdefault(sh.fleet, []).append(sh)

    def space_combat(self):
        order = [e for e in self.ctx.empire_order if e in self.parts]
        # initiative attacks first (rules:504-505, 845-847)
        leftover: dict[int, int] = {}
        for a in order:
            vict = [b for b in self.parts if b != a and self.relation(a, b) == ("init", a)]
            if not vict or not any(s.owner == a for s in self.ships if s.alive):
                if not vict:
                    continue
            if not any(s.owner in vict and s.alive for s in self.ships):
                continue
            sc = self.roll_effective(a, self.space_attack(a))
            kills: list[Ship] = []
            leftover[a] = self.fire(a, sc, self.targets(vict), True, kills)
            for k in kills:
                self.kill_ship(k)
        # then everyone else, simultaneously (rules:796, 835-836)
        plans = []
        for e in order:
            tgt = [b for b in self.parts if b != e and self.relation(e, b) is not None
                   and self.relation(e, b) != ("init", e)]
            if e in leftover:
                tgt = [b for b in self.parts if b != e and self.relation(e, b) == "mutual"]
            if not tgt or not any(s.owner in tgt and s.alive for s in self.ships):
                continue
            if e in leftover:
                sc = leftover[e]
            else:
                if not any(s.owner == e and s.alive for s in self.ships) and not (
                        self.sys is not None and self.sys.owner == e):
                    continue
                sc = self.roll_effective(e, self.space_attack(e))
            plans.append((e, sc, tgt))
        kills: list[Ship] = []
        for e, sc, tgt in plans:
            self.fire(e, sc, self.targets(tgt), False, kills)
        for k in kills:
            self.kill_ship(k)

    # ---- ship to ground -------------------------------------------------------------
    def bombard_defense(self, t: Troop) -> int:
        d = t.ttype.defense
        if t.posture == "D":
            return math.ceil(d * 1.5)
        if t.posture == "E":
            return d * 4                                    # rules:592-593
        return d

    def bombardment(self):
        s = self.sys
        for e in self.parts:
            if not self.attacks_system(e):
                continue
            self.assign_roles(e)
            pts = self.pool(e, "GC")
            if pts <= 0:
                continue
            factor = (2 if s.has("PD") else 1) * (2 if s.has("APD") else 1)
            targets = [t for t in self.troops if t.alive and t.owner != e and
                       ((self.agg(e) == "H" and not self.ctx.allied(e, t.owner))
                        or self.ctx.at_war(e, t.owner))]
            self.rng.shuffle(targets)
            for t in targets:
                if pts <= 0:
                    break
                ed = self.bombard_defense(t) * factor
                cost = K.BOMBARD_PTS_PER_DEF * ed
                if pts >= cost:
                    pts -= cost
                    if self.rng.chance(K.CAVE_CHANCE):
                        self.say("ground", f"{self.name(t.owner)} {t.ttype.name} {t.number} finds"
                                 f" shelter in deep caves, survives ground bombardment!",
                                 ct=t.number)
                    else:
                        t.alive = False
                        self.say("ground", f"{self.name(t.owner)} {t.ttype.name} {t.number} "
                                 f"DESTROYED FROM SPACE!", ct=t.number, by=e)
                else:
                    chance = 100.0 * pts / (K.BOMBARD_PARTIAL_DIV * ed)
                    roll = self.rng.random() * 100
                    if roll < chance:
                        t.alive = False
                        self.say("ground", f"{self.name(t.owner)} {t.ttype.name} {t.number} "
                                 f"DESTROYED FROM SPACE [{int(roll)}/{int(chance)}]!",
                                 ct=t.number, by=e)
                    else:
                        self.say("ground", f"{self.name(t.owner)} {t.ttype.name} {t.number} "
                                 f"SURVIVES DEADLY SPACE BOMBARDMENT [{int(roll)}/{int(chance)}]!",
                                 ct=t.number)
                    pts = 0

    def raid(self):
        s = self.sys
        for e in self.parts:
            if not self.attacks_system(e) or s.owner == e:
                continue
            self.assign_roles(e)
            pts = self.pool(e, "RD")
            if s.has("APD"):
                pts //= 2                                   # rules:2999
            if pts <= 0:
                continue
            self.say("raid", f"The {self.name(e)} raid {s.name} with {pts} attack points",
                     race=e, points=pts)
            old = s.pop
            kill = pts // K.RAID_PTS_PER_POP
            if self.rng.chance(100.0 * (pts % K.RAID_PTS_PER_POP) / K.RAID_PTS_PER_POP):
                kill += 1
            if kill:
                s.pop -= kill
                if s.pop < 0.5:
                    s.pop = 0.0
                elif s.pop < 1.0:
                    s.pop = 1.0
                if old > 0 and s.pop < old:
                    self.say("raid", f"{100 - s.pop * 100 / old:3.0f} percent of population "
                             f"burned off from space!!!")
            while pts > 0:
                chunk = min(K.RAID_PTS_PER_TARGET, pts)
                pts -= chunk
                frac = chunk / K.RAID_PTS_PER_TARGET
                target = self.rng.below(4)
                if target == 0:
                    if s.infra <= 0:
                        continue
                    if chunk == K.RAID_PTS_PER_TARGET or self.rng.chance(100 * frac):
                        s.infra -= 1
                        self.say("raid", "IF blasted from space!")
                elif target in (1, 2):
                    attr = "iu" if target == 1 else "au"
                    if getattr(s, attr) <= 0:
                        continue
                    loss = min(getattr(s, attr), round(K.RAID_IU_AU_PER_HIT * frac))
                    setattr(s, attr, getattr(s, attr) - loss)
                    self.say("raid", f"{loss} {attr.upper()}s blasted from space!")
                else:
                    arts = sorted(s.artifacts)
                    if not arts:
                        continue
                    a = self.rng.choice(arts)
                    cost = max(1, ARTIFACTS[a].total_cost)
                    if self.rng.chance(100.0 * chunk * 2 / cost):
                        s.artifacts.discard(a)
                        self.say("raid", f"{ARTIFACTS[a].name} blasted from space!", artifact=a)
                    else:
                        self.say("raid", f"{ARTIFACTS[a].name} fired on but missed!",
                                 artifact=a)

    # ---- ground to ground (rules:910-918; gccombat.c:1698-1945) ------------------------
    def ground_mult(self, e) -> float:
        if self.sys is None or e != self.sys.owner:
            return 1.0
        gov = self.st.governor(self.sys.id)
        return (gov.combat + 50) / 100.0 if gov is not None and gov.owner == e else 1.0

    def ground_combat(self):
        alive = [t for t in self.troops if t.alive]
        owners = sorted({t.owner for t in alive})
        fights = any(not self.mutual_allies(a, b) for i, a in enumerate(owners)
                     for b in owners[i + 1:])
        if len(owners) < 2 or not fights:
            return
        ga: dict[int, int] = {}
        for e in owners:
            tot = 0.0
            for t in alive:
                if t.owner != e:
                    continue
                if t.posture == "A":
                    tot += t.ttype.attack
                elif t.posture == "E":
                    tot += t.ttype.attack // 2              # rules:591
            ga[e] = int(tot * self.ground_mult(e))
        eff = {}
        for e in owners:
            if ga[e] <= 0:
                self.say("ground", f"The WUSSY {self.name(e)} ground troops have no attack!",
                         race=e)
                eff[e] = 0
                continue
            v = math.sqrt(self.rng.between(1, ga[e] * ga[e]))
            eff[e] = max(1, int(v))
            pct = eff[e] * 100.0 / ga[e]
            word = next(w for lim, w in EFFECTIVENESS if pct < lim)
            self.say("ground", f"The dreaded {self.name(e)} gets a {word} {pct:2.0f}% "
                     f"effectiveness during ground combat", race=e)
        order = list(alive)
        self.rng.shuffle(order)
        dead: set[int] = set()
        for e in [x for x in self.ctx.empire_order if x in owners]:
            pts = eff[e]
            for t in order:
                if pts <= 0:
                    break
                if t.number in dead or t.owner == e or self.mutual_allies(e, t.owner):
                    continue
                d = t.ttype.defense
                if t.posture == "D":
                    ed = math.ceil(1.5 * d)
                elif t.posture == "E":
                    ed = 2 * d
                else:
                    ed = d
                    if t.posture in ("E1", "E2", "E3"):
                        t.posture = "A"                     # gccombat.c:1866-1887
                ed = max(1, int(ed * self.ground_mult(t.owner)))
                if pts >= ed:
                    pts -= ed
                    dead.add(t.number)
                    self.say("ground", f"{self.name(t.owner)} {t.ttype.name} combat troop "
                             f"{t.number} destroyed in combat!", ct=t.number, by=e)
                else:
                    roll = self.rng.random() * 100
                    if roll < pts * 100.0 / ed:
                        dead.add(t.number)
                        self.say("ground", f"{self.name(t.owner)} {t.ttype.name} combat troop "
                                 f"{t.number} destroyed in combat!", ct=t.number, by=e)
                    else:
                        self.say("ground", f"{self.name(t.owner)} {t.ttype.name} combat troop "
                                 f"{t.number} avoids deadly ground attack!", ct=t.number)
                    pts = 0
        for t in alive:
            if t.number in dead:
                t.alive = False

    # ---- capture and status ----------------------------------------------------------
    def check_capture(self) -> None:
        s = self.sys
        o = s.owner
        alive = [t for t in self.st.troops_at(s.id)]
        defenders = [t for t in alive if t.owner == o or self.mutual_allies(t.owner, o)]
        attackers = [t for t in alive if t.owner != o and not self.mutual_allies(t.owner, o)]
        if attackers and not defenders:
            strength: dict[int, int] = {}
            for t in attackers:
                strength[t.owner] = strength.get(t.owner, 0) + t.ttype.defense + t.ttype.attack
            best = max(strength.values())
            winners = sorted(e for e, v in strength.items() if v == best)
            new = winners[0] if len(winners) == 1 else self.rng.choice(winners)
            change_owner(self.ctx, s, new, "capture", self)
            return
        if s.happy <= 0 and s.pop > 0:
            joiners = [e for e in self.parts if e != o and e != 0 and
                       (self.attacks_system(e) or any(t.owner == e for t in attackers))]
            if joiners and self.rng.chance(K.REBEL_JOIN_CHANCE):
                change_owner(self.ctx, s, self.rng.choice(joiners), "rebel", self)

    def determine_status(self) -> tuple[int, str]:
        s = self.sys
        o = s.owner
        total_a = total_d = 0
        for sh in self.ships:
            if not sh.alive:
                continue
            if sh.owner == o:
                total_d += self.eff_defense(sh)
            elif self.attacks_system(sh.owner):
                total_a += self.eff_attack(sh)
            elif self.ctx.allied(sh.owner, o):
                total_d += self.eff_defense(sh)
        total_d += sum(v for k, v in K.SYSTEM_WEAPON_DEFENSE.items() if s.has(k))
        if total_a < 1 or total_a * K.STATUS_RATIO < total_d:
            ship_st, why = K.NORMAL, "no_attack" if total_a < 1 else "normal"
        elif total_d == 0:
            ship_st, why = K.INTERDICTED, "no_defense"
        elif total_a > K.STATUS_RATIO * total_d:
            ship_st, why = K.INTERDICTED, "int"
        else:
            ship_st, why = K.UNDER_ATTACK, "ua"
        # ground
        ea = od = 0.0
        enemy = False
        for t in self.st.troops_at(s.id):
            if t.owner == o or self.mutual_allies(t.owner, o):
                d = t.ttype.defense
                od += 1.5 * d if t.posture == "D" else 2 * d if t.posture == "E" else d
            else:
                enemy = True
                if t.posture == "A":
                    ea += t.ttype.attack
                elif t.posture == "E":
                    ea += t.ttype.attack // 2
        g_st, g_why = K.NORMAL, "no_attack_ground"
        if enemy:
            if od <= 0 or ea >= od:
                g_st, g_why = K.INTERDICTED, "int_ground"
            elif ea * K.STATUS_RATIO >= od:
                g_st, g_why = K.UNDER_ATTACK, "ua"
        if g_st > ship_st:
            return g_st, g_why
        return ship_st, why

    def set_status(self) -> None:
        s = self.sys
        before = s.status
        new, why = self.determine_status()
        # one category a turn (rules:946-950)
        if new == K.INTERDICTED and before == K.NORMAL:
            new, why = K.UNDER_ATTACK, "shift_int"
        elif new == K.NORMAL and before == K.INTERDICTED:
            new, why = K.UNDER_ATTACK, "shift_norm"
        s.status = new
        if new == K.INTERDICTED:
            s.trade_routes.clear()
        self.log.status_before, self.log.status_after = before, new
        self.say("status", SYS_STATUS_TEXT[why])

    # ---- driver -----------------------------------------------------------------------
    def run(self) -> None:
        ctx = self.ctx
        self._rel: dict = {}
        for i, a in enumerate(self.parts):
            for b in self.parts[i + 1:]:
                if a and b:
                    ctx.make_contact(a, b)
        s = self.sys
        self.log.owner_before = s.owner if s is not None else None
        self.log.ships = [{"number": sh.number, "owner": sh.owner, "type": sh.type,
                           "posture": sh.posture, "role": sh.role, "fleet": sh.fleet}
                          for sh in self.ships]
        self.log.troops = [{"number": t.number, "owner": t.owner, "type": t.type,
                            "posture": t.posture} for t in self.troops]
        rels = {}
        for i, a in enumerate(self.parts):
            for b in self.parts[i + 1:]:
                r = self.relation(a, b)
                if r is None:
                    txt = "ALLIED" if self.mutual_allies(a, b) else "DO NOT ATTACK"
                elif r == "mutual":
                    txt = "ATTACK"
                else:
                    txt = f"SURPRISE ATTACK by {self.name(r[1])}"
                rels[f"{a},{b}"] = txt
        self.log.relations = rels
        for e in self.parts:
            ld = None
            for sh in self.ships:
                if sh.owner == e and sh.fleet is not None:
                    ld = ld or self.st.admiral(sh.fleet)
            if ld is not None:
                txt = next(t for lim, t in ADMIRAL_TEXT if ld.combat < lim)
                self.say("space", f"{self.name(e)} Admiral {ld.name} {txt}")
        if s is not None:
            gov = self.st.governor(s.id)
            if gov is not None and gov.owner == s.owner:
                txt = next(t for lim, t in GOVERNOR_TEXT if gov.combat < lim)
                self.say("space", f"{self.name(s.owner)} Governor {gov.name} {txt}")
        self.space_combat()
        if s is not None:
            self.bombardment()
            if s.pop > 0 or s.artifacts or s.infra or s.iu or s.au:
                self.raid()
            self.ground_combat()
            self.check_capture()
            self.set_status()
            ctx.combat_systems.add(s.id)
            self.log.owner_after = s.owner
            self.log.ground = self.ground_summary()
        self.leader_casualties()
        for sh in self.ships:
            ctx.ships_in_combat.add(sh.number)
        ctx.res.combats.append(self.log)
        viewers = set(self.parts)
        if s is not None:
            viewers.add(s.owner)
        for e in viewers:
            ctx.res.report(e).combats.append(self.log.id)

    def ground_summary(self) -> list[dict]:
        """Each side's troops on the ground at the start and at the end of the battle, by type
        (troops that defect when a system rebels count on their new side afterwards).  Only what
        the log already shows its participants: the opening troop listing and the kill lines."""
        def count(troops, e):
            out: dict[str, int] = {}
            for t in troops:
                if t["owner"] == e:
                    out[t["type"]] = out.get(t["type"], 0) + 1
            return out
        after = [{"owner": t.owner, "type": t.type} for t in self.st.troops_at(self.sys.id)]
        sides = sorted({t["owner"] for t in self.log.troops} | {t["owner"] for t in after})
        return [{"owner": e, "before": count(self.log.troops, e), "after": count(after, e)}
                for e in sides]

    def leader_casualties(self) -> None:
        """Admirals can die in combat (rules:650).  The rules give no formula; we use a chance of
        25% x the fraction of the fleet's ships lost here (DECISIONS F-07)."""
        for fno, lost in self.fleet_losses.items():
            adm = self.st.admiral(fno)
            if adm is None:
                continue
            present = len([s for s in self.ships if s.fleet == fno])
            if present and self.rng.chance(25.0 * len(lost) / present):
                adm.alive = False
                self.say("space", f"Admiral {adm.name} is killed in the battle!")
                self.ctx.res.emit(adm.owner, "leader_killed", f"Admiral {adm.name} was killed in "
                                  f"combat.", "combat", leader=adm.id)


def change_owner(ctx: TurnContext, s: System, new: int, mode: str, combat=None) -> None:
    """Capture by ground troops, or a rebelling system joining an attacker
    (rules:952-983; gccombat.c:1403-1573)."""
    st = ctx.state
    old = s.owner
    say = combat.say if combat else (lambda *a, **k: None)
    s.trade_routes.clear()
    gov = st.governor(s.id)
    if mode == "rebel":
        say("capture", f"{ctx.name(old)} System {s.name} REBELS!  And joins the {ctx.name(new)}!")
        s.au //= 2
        s.iu //= 2
        for t in st.troops_at(s.id):
            if t.owner == old:
                t.owner = new
        if gov is not None and gov.owner == old:
            if ctx.rng.chance(K.REBEL_GOVERNOR_KILL):
                gov.alive = False
                say("capture", f"Governor {gov.name} is killed in the uprising!")
                ctx.res.emit(old, "leader_killed", f"Governor {gov.name} was killed when {s.name} "
                             f"rebelled.", "combat", s.id, leader=gov.id)
            else:
                gov.owner = new
                say("capture", f"Governor {gov.name} defects to the {ctx.name(new)}!")
                ctx.res.emit((old, new), "leader_defected",
                             f"Governor {gov.name} has defected to the {ctx.name(new)}.", "combat",
                             s.id, leader=gov.id)
    else:
        say("capture", f"{ctx.name(old)} System {s.name} captured by {ctx.name(new)} ground "
            f"troops!")
        s.au = s.iu = 0
        if s.pop > 0:
            m = ctx.rng.between(*K.CAPTURE_POP_LOSS)
            s.pop *= (100.0 - m) / 100.0
            say("capture", f"{m} percent of the population die in the assault!")
        m = ctx.rng.between(10, 49)
        if s.infra * m / 100.0 > 1:
            s.infra = int(s.infra * (100 - m) / 100.0)
            say("capture", f"{m} percent of the infrastructure is destroyed in the assault!")
        n = 0 if ctx.rng.below(10) < 5 else ctx.rng.below(5)
        for _ in range(n):
            if not s.artifacts:
                break
            a = ctx.rng.choice(sorted(s.artifacts))
            s.artifacts.discard(a)
            say("capture", f"Artifact {ARTIFACTS[a].name} is destroyed in the assault!")
        if gov is not None:
            gov.alive = False
            say("capture", f"Governor {gov.name} is killed in the assault!")
            ctx.res.emit(gov.owner, "leader_killed", f"Governor {gov.name} was killed in the "
                         f"assault on {s.name}.", "combat", s.id, leader=gov.id)
    # morale bookkeeping (gccombat.c:1435-1438)
    eo, en = st.empires[old], st.empires[new]
    if old != 0:
        eo.systems_captured = -s.hab if eo.systems_captured > 0 else eo.systems_captured - s.hab
    if new != 0 and en.systems_captured >= 0:
        en.systems_captured += s.hab
    # tech capture: only from a race with better technology (rules:267-268, 982-983)
    if old != 0 and new != 0:
        cand = sorted((t for t in eo.techs if 0 < t < 51), reverse=True)[:K.TECH_CAPTURE_POOL]
        if cand and len(eo.techs) > len(en.techs) + K.TECH_CAPTURE_GAP:
            t = ctx.rng.choice(cand)
            if t not in en.techs:
                en.techs.add(t)
                say("capture", f"{en.name} capture {TECHS[t].name} technology!")
                ctx.res.emit(new, "tech_captured", f"You capture {TECHS[t].name} technology "
                             f"on {s.name}!", "combat", s.id, tech=t)
    s.owner = new
    remember(en, s, ctx.turn, True)
    ctx.res.emit(old, "system_lost", f"System {s.name} lost to the {ctx.name(new)}!", "combat",
                 s.id, race=new, mode=mode)
    ctx.res.emit(new, "system_captured", f"System {s.name} captured from the {ctx.name(old)}!",
                 "combat", s.id, race=old, mode=mode)


STATUS_NOW = {K.NORMAL: "back to normal status", K.UNDER_ATTACK: "under attack (UA)",
              K.INTERDICTED: "interdicted (INT)"}


def status_decay(ctx: TurnContext) -> None:
    """Systems not in combat this turn step one category toward NORMAL (gcrun.c:1232-1245)."""
    for s in ctx.state.systems:
        if s.id not in ctx.combat_systems and s.status > K.NORMAL:
            s.status -= 1
            ctx.res.emit(s.owner, "status_change", f"{s.name} is now "
                         f"{STATUS_NOW[s.status]}.", "combat", s.id, status=s.status)
