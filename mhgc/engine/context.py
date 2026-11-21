"""Per-turn scratch state shared by the turn phases (the C kept these in globals and sys_econ[])."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional


from ..data import constants as K
from ..geometry import to_abs, to_rel
from ..model import GameState, System
from ..results import TurnResults
from ..rng import Rng


class OrderError(Exception):
    """An order failed validation against the game state; nothing was changed."""


class WhereError(OrderError):
    """An OrderError because the unit isn't where the order can act (in deep space, or at a
    system that isn't yours).  For a cargo order, `execute` adds where the unit is and where it
    is going (engine/advice.where_error, DECISIONS G-20)."""


@dataclass
class SysEcon:
    prod_au: int = 0
    prod_iu: int = 0
    prod_eu: int = 0
    eaten: int = 0
    purch_iu: int = 0
    sisd: int = 0
    sisd_owner: int = -1


@dataclass
class TurnContext:
    state: GameState
    rng: Rng
    res: TurnResults
    checking: bool = False             # order check (dry run on a copy): no NPR rolls etc.
    built: Optional[int] = None        # set by BS / BCU: units built by the current order
    pt_done: set = field(default_factory=set)       # bought/received a tech (PTflag)
    gt_done: set = field(default_factory=set)       # gifted a tech (GTflag)
    ft_done: set = field(default_factory=set)       # bought a Future Tech this turn
    npr_trade_done: set = field(default_factory=set)
    tech_why: dict = field(default_factory=dict)    # eid -> what used its one tech this turn
    gift_why: dict = field(default_factory=dict)    # eid -> the tech gift it made this turn
    orders_done: set = field(default_factory=set)   # empires whose orders have run (turn_done)
    builds: dict = field(default_factory=lambda: defaultdict(float))
    starport_changed: set = field(default_factory=set)
    econ: dict = field(default_factory=lambda: defaultdict(SysEcon))
    ci: dict = field(default_factory=lambda: defaultdict(lambda: 1))
    spy_unrest: dict = field(default_factory=lambda: defaultdict(int))
    # What orders spent or got back, per empire, for the maintenance ledger.  Every EU or IU
    # an order takes or returns goes through one of these (orders_exec._spend/_refund/_gift).
    purch_eu: dict = field(default_factory=lambda: defaultdict(int))     # EU spent by orders
    purch_iu: dict = field(default_factory=lambda: defaultdict(int))     # system IUs spent
    refund_eu: dict = field(default_factory=lambda: defaultdict(int))    # SS/SCT salvage
    refund_iu: dict = field(default_factory=lambda: defaultdict(int))
    gift_out_eu: dict = field(default_factory=lambda: defaultdict(int))  # GE, GT, TTNPR costs
    gift_in_eu: dict = field(default_factory=lambda: defaultdict(int))   # GE received
    trade_eu: dict = field(default_factory=lambda: defaultdict(int))
    eu_prod: dict = field(default_factory=lambda: defaultdict(int))
    iu_prod: dict = field(default_factory=lambda: defaultdict(int))
    au_prod: dict = field(default_factory=lambda: defaultdict(int))
    growth: dict = field(default_factory=lambda: defaultdict(float))
    addfleetxy: list = field(default_factory=list)  # (fleet number, x, y, owner)
    # end-of-turn fleet cleanup (DECISIONS G-18): fleets CF/CFXY created this turn, and fleets
    # that held a ship at some point this turn (a new fleet still waiting for ships is spared)
    new_fleets: set = field(default_factory=set)
    filled_fleets: set = field(default_factory=set)
    ssi: list = field(default_factory=list)         # (system id, recipient)
    messages: list = field(default_factory=list)    # (sender, recipients, text)
    pending_captures: dict = field(default_factory=dict)
    combat_systems: set = field(default_factory=set)
    ships_in_combat: set = field(default_factory=set)
    start_eu: dict = field(default_factory=dict)
    extra_scans: list = field(default_factory=list)  # (system id, viewer, "short"/"long")
    pending_son: list = field(default_factory=list)  # (viewer, target) spy stats reports
    empire_order: list = field(default_factory=list)  # random processing order this turn
    # draft-order bookkeeping for cargo-order errors and check advice (DECISIONS G-20)
    order_index: int = -1                            # index of the order now running
    warps: dict = field(default_factory=dict)        # (eid, "ship"|"fleet", n) -> (index, x, y, sys id)
    farcast: dict = field(default_factory=dict)      # (eid, troop) -> (index, from sys id, to sys id)
    where_fail: dict = field(default_factory=dict)   # (eid, index) -> undecorated WhereError text

    @property
    def turn(self) -> int:
        return self.state.turn

    # ---- helpers ----------------------------------------------------------------------
    def emp(self, eid: int):
        return self.state.empires[eid]

    def name(self, eid: int) -> str:
        e = self.state.empires.get(eid)
        return e.name if e else f"race {eid}"

    def rel_xy(self, eid: int, x: int, y: int) -> tuple[int, int]:
        e = self.emp(eid)
        return to_rel(x, y, e.home_x, e.home_y, self.state.board)

    def abs_xy(self, eid: int, x: int, y: int) -> tuple[int, int]:
        e = self.emp(eid)
        b = self.state.board
        if not (0 <= x < b and 0 <= y < b):
            raise OrderError(f"{x},{y} is off the board: this galaxy is {b}x{b}, so coordinates "
                             f"run from 0 to {b - 1}.")
        return to_abs(x, y, e.home_x, e.home_y, b)

    def sys_label(self, s: System) -> str:
        return s.name

    def is_npr(self, eid: int) -> bool:
        return self.emp(eid).is_npr

    def allied(self, a: int, b: int) -> bool:
        """a has declared an alliance with b."""
        return self.emp(a).relations.get(b) == "A"

    def at_war(self, a: int, b: int) -> bool:
        return self.emp(a).relations.get(b) in ("W", "E")

    def make_contact(self, a: int, b: int) -> None:
        """Symmetric first contact (gcscan.c:169-239, gccombat flagging)."""
        if a == b or a < 0 or b < 0:
            return
        ea, eb = self.state.empires.get(a), self.state.empires.get(b)
        if ea is None or eb is None:
            return
        new = False
        if b not in ea.relations:
            ea.relations[b] = "N"
            new = True
        if a not in eb.relations:
            eb.relations[a] = "N"
            new = True
        if new and not self.checking:
            for x, y in ((a, b), (b, a)):
                if self.state.empires[x].kind in ("human", "npr"):
                    self.res.emit(x, "contact", f"First contact with the {self.name(y)}!",
                                  "general", race=y)

    def cost_mult(self, s: System) -> int:
        return 2 if s.status == K.UNDER_ATTACK else 1
