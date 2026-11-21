"""The bot's order sheet and its single budget.

Every planned order is charged against one budget that mirrors the engine's checks
(engine/orders_exec.py): EUs, each system's IU stockpile, starport build capacity (BS 1, BCU 0.5
per class), a starport change blocking further builds, the 2x cost under attack, interdicted
systems, one technology purchase a turn, the militia limit and ship cargo.  The goal is that
every bot order validates, as a careful player's would.  It is built from the World (the view),
never from the game state.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from ..data import constants as K
from ..data.artifacts import ARTIFACTS, SPY_EU_COST, SPY_IU_COST
from ..data.ships import SHIP_TYPES
from ..data.techs import TECHS, missing_prereqs
from ..data.troops import TROOP_TYPES
from ..orders import Order, OrderSyntaxError, make_order
from .trace import reason_code


class Plan:
    def __init__(self, w):
        self.w = w
        self.orders: list[Order] = []
        self.errors: list[str] = []
        self.eu = w.eu
        self.iu = {s.id: s.iu for s in w.systems}
        self.pop = {s.id: s.pop for s in w.systems}
        self.happy = {s.id: s.happy for s in w.systems}   # after this turn's landings so far
        self.builds: dict[int, float] = defaultdict(float)
        self.sp_changed: set[int] = set()
        self.pt_done = False
        self.busy: set[int] = set()            # ships already given orders this turn
        self.cargo: dict[int, list] = {}
        self.new_ships: dict[int, list] = defaultdict(list)
        self.new_troops: dict[int, list] = defaultdict(list)
        self.moved_troops: set[int] = set()
        self.spent = defaultdict(int)          # EU by purpose (for reports/tests)
        self.cap_short: set[int] = set()       # systems where a build lacked starport capacity
        self.tech_pending = False              # a wanted technology was unaffordable
        self.econ_pending = False              # an economic investment was unaffordable
        self.no_buy: set[int] = set()          # techs not to buy this turn (a trade pending)
        self.tp_done: set[int] = set()         # troops farcast this turn (portals.py)
        self.warped = 0                        # ships sent through warp tunnels this turn
        self.thr: dict = {}                    # this turn's threats (war.threats), for portals
        # the decision log (mhgc/npr/trace.py): the area brain.decide is in, and per order its
        # area, reason code and note (parallel to self.orders)
        self.area = ""
        self.reasons: list[dict] = []

    # ---- emitting -----------------------------------------------------------------------
    def add(self, code: str, why: str = "", rc: Optional[str] = None, **kw) -> Optional[Order]:
        try:
            o = make_order(code, **kw)
        except OrderSyntaxError as exc:      # a bug in the bot, never the engine's fault
            self.errors.append(f"{code} {kw}: {exc}")
            return None
        text = o.to_text()
        o.line = f"{text}  # {why}" if why and code != "MESSAGE" else text
        self.orders.append(o)
        self.reasons.append({"area": self.area, "rc": rc or reason_code(self.area, code, why),
                             "note": why})
        return o

    def message(self, race_name: str, text: str, rc: Optional[str] = None) -> None:
        self.add("MESSAGE", rc=rc, recipients=[race_name], text=text)

    # ---- budget -------------------------------------------------------------------------
    @staticmethod
    def mult(s) -> int:
        return 2 if s.status == K.UNDER_ATTACK else 1

    def capacity(self, s) -> float:
        if s.id in self.sp_changed:
            return 0.0
        return s.starport - self.builds[s.id]

    def can_ship(self, s, code: str, reserve: int = 0) -> bool:
        st = SHIP_TYPES[code]
        if s.status == K.INTERDICTED or not self.w.has_tech(st.tech):
            return False
        m = self.mult(s)
        paid = self.iu.get(s.id, 0) >= st.iu_cost * m and self.eu - reserve >= st.eu_cost * m
        if paid and self.capacity(s) < 1 and s.id not in self.sp_changed:
            self.cap_short.add(s.id)
        return self.capacity(s) >= 1 and paid

    def build_ship(self, s, code: str, posture="N", role="SC", why="", reserve=0,
                   purpose="ships") -> bool:
        if not self.can_ship(s, code, reserve):
            return False
        st = SHIP_TYPES[code]
        m = self.mult(s)
        self.iu[s.id] -= st.iu_cost * m
        self.eu -= st.eu_cost * m
        self.spent[purpose] += st.eu_cost * m
        self.builds[s.id] += 1
        self.new_ships[s.id].append(code)
        self.add("BS", why, system=s.name, type=code, posture=posture, role=role)
        return True

    def can_troop(self, s, code: str, reserve: int = 0) -> bool:
        tt = TROOP_TYPES[code]
        if s.status == K.INTERDICTED:
            return False
        if code == "M":
            have = sum(1 for t in s.troops if t["type"] == "M" and t["owner"] == self.w.eid)
            if have + self.new_troops[s.id].count("M") >= int(s.pop):
                return False
        elif not self.w.has_tech(tt.tech):
            return False
        m = self.mult(s)
        paid = self.iu.get(s.id, 0) >= tt.iu_cost * m and self.eu - reserve >= tt.eu_cost * m
        if paid and self.capacity(s) < 0.5 and s.id not in self.sp_changed:
            self.cap_short.add(s.id)
        return self.capacity(s) >= 0.5 and paid

    def build_troop(self, s, code: str, posture="A", why="", reserve=0) -> bool:
        if not self.can_troop(s, code, reserve):
            return False
        tt = TROOP_TYPES[code]
        m = self.mult(s)
        self.iu[s.id] -= tt.iu_cost * m
        self.eu -= tt.eu_cost * m
        self.spent["troops"] += tt.eu_cost * m
        self.builds[s.id] += 0.5
        self.new_troops[s.id].append(code)
        self.add("BCU", why, system=s.name, type=code, posture=posture)
        return True

    def build_artifact(self, s, key: str, why="", reserve=0) -> bool:
        art = ARTIFACTS[key]
        if s.status == K.INTERDICTED or key in s.artifacts or not self.w.has_tech(art.tech):
            return False
        if key == "EESS" and "ESS" not in s.artifacts:
            return False
        m = self.mult(s)
        if self.iu.get(s.id, 0) < art.iu_cost * m or self.eu - reserve < art.eu_cost * m:
            return False
        self.iu[s.id] -= art.iu_cost * m
        self.eu -= art.eu_cost * m
        self.spent["artifacts"] += art.eu_cost * m
        s.artifacts.add(key)                    # the plan's own copy of the world
        self.add("BT", why, system=s.name, artifact=key)
        return True

    def build_spy(self, s, why="", reserve=0) -> bool:
        m = self.mult(s)
        if s.status == K.INTERDICTED or not self.w.has_tech(14):
            return False
        if self.iu.get(s.id, 0) < SPY_IU_COST * m or self.eu - reserve < SPY_EU_COST * m:
            return False
        self.iu[s.id] -= SPY_IU_COST * m
        self.eu -= SPY_EU_COST * m
        self.spent["spies"] += SPY_EU_COST * m
        self.add("BT", why, system=s.name, artifact="S")
        return True

    def build_starport(self, s, why="", reserve=0) -> bool:
        if s.status == K.INTERDICTED or s.id in self.sp_changed or self.builds[s.id] > 0:
            return False
        cost = K.starport_cost(s.starport + 1) - K.starport_cost(s.starport)
        if self.iu.get(s.id, 0) < cost or self.eu - reserve < cost:
            return False
        self.iu[s.id] -= cost
        self.eu -= cost
        self.spent["starports"] += cost
        self.sp_changed.add(s.id)
        self.add("BSP", why, system=s.name)
        return True

    def infra(self, s, n: int, why="", keep=0) -> bool:
        if s.status != K.NORMAL:
            return False
        n = min(n, (self.iu.get(s.id, 0) - keep) // K.INFRA_IU_COST)
        if n <= 0:
            return False
        self.iu[s.id] -= n * K.INFRA_IU_COST
        self.add("BI", why, system=s.name, amount=n)
        return True

    def buy_tech(self, t: int, why="", reserve=0, crash=False) -> bool:
        if (self.pt_done and not crash) or t not in TECHS or t == 0:
            return False
        if t != 51 and t in self.w.techs:
            return False
        if missing_prereqs(self.w.techs, t):
            return False
        cost = TECHS[t].cost * (2 if crash else 1)
        if self.eu - reserve < cost:
            return False
        self.eu -= cost
        self.spent["research"] += cost
        if not crash:
            self.pt_done = True
        if t != 51:
            self.w.techs.add(t)
        self.add("CRP" if crash else "PT", why, tech=t)
        return True

    def pay(self, eu: int, purpose="misc") -> bool:
        if self.eu < eu:
            return False
        self.eu -= eu
        self.spent[purpose] += eu
        return True

    # ---- cargo --------------------------------------------------------------------------
    def cargo_of(self, sh) -> list:
        c = self.cargo.get(sh.number)
        if c is None:
            c = [sh.cargo[0], sh.cargo[1], sh.cargo[2], len(sh.cargo[3])]
            self.cargo[sh.number] = c
        return c

    def free_points(self, sh) -> int:
        au, iu, pop, cts = self.cargo_of(sh)
        goods = -(-(au + iu) // K.CARGO_UNITS_PER_POINT)
        return sh.st.cargo - goods - pop - cts

    def free_goods(self, sh) -> int:
        au, iu, pop, cts = self.cargo_of(sh)
        return max(0, (sh.st.cargo - pop - cts) * K.CARGO_UNITS_PER_POINT - au - iu)
