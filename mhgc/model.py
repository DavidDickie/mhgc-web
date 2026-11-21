"""Game state model: dataclasses plus JSON save/load.

Conventions
- Coordinates are stored ABSOLUTE (0..99).  Each empire sees and orders in coordinates relative to
  its home (home shown at 50,50, rules:1538 "relative coordinate system"); see geometry.py.
- Systems are identified by their index in `GameState.systems` (stable for the whole game).
- Ships, fleets, troops and spies are identified by their number (random, non-sequential, so
  numbers leak nothing about other empires' builds; C allocated them the same way).
- Destroyed units are removed at the end of the turn; during a turn they are flagged `alive=False`.
"""
from __future__ import annotations

import dataclasses
import functools
import json
import typing
from dataclasses import dataclass, field
from typing import Any, Optional

from .data import constants as K
from .data.ships import SHIP_TYPES
from .data.troops import TROOP_TYPES

SAVE_VERSION = 1

# Relations (rules:728-743).  Absence of a key = no contact.
NEUTRAL, ALLIED, AT_WAR, END_WAR = "N", "A", "W", "E"

# Empire kinds
HUMAN, NPR, INDEPENDENT, DEAD = "human", "npr", "independent", "dead"

# Ship orders
STAND, MOVE, INTERCEPT, MOVE_TO_SYSTEM, GUARD = "STAND", "MOVE", "INTERCEPT", "MS", "GUARD"


@dataclass
class System:
    id: int
    name: str
    x: int
    y: int
    owner: int = 0
    pop: float = 0.0
    happy: float = 0.5
    trend: int = 0
    hab: int = 3
    mr: bool = False
    ar: bool = False
    infra: int = 0
    status: int = K.NORMAL
    starport: int = 0
    au: int = 0                      # AU stockpile
    iu: int = 0                      # IU stockpile
    csp_au: int = 50
    csp_iu: int = 25
    csp_eu: int = 25
    au_mode: str = "pct"             # "pct" (CAP) or "num" (CAPN)
    au_value: int = K.DEFAULT_AU_PROFILE
    artifacts: set[str] = field(default_factory=set)
    trade_routes: set[int] = field(default_factory=set)   # empires with a DCT route here

    def has(self, art: str) -> bool:
        return art in self.artifacts

    @property
    def scan_range(self) -> int:
        return 10 if "EESS" in self.artifacts else 6 if "ESS" in self.artifacts else 4


@dataclass
class Ship:
    number: int
    owner: int
    type: str
    x: int
    y: int
    dx: int = 0
    dy: int = 0
    order: str = STAND
    target: Optional[int] = None         # ship number for INTERCEPT
    dest_system: Optional[int] = None    # for MS
    posture: str = "N"
    role: str = "SC"
    fleet: Optional[int] = None
    cargo_au: int = 0
    cargo_iu: int = 0
    cargo_pop: int = 0
    home: Optional[int] = None
    drop: bool = False                   # DOCT flag for this turn
    built_turn: int = 0
    ox: int = 0                          # position at the start of the turn (reports)
    oy: int = 0
    alive: bool = True

    @property
    def stype(self):
        return SHIP_TYPES[self.type]


@dataclass
class Fleet:
    number: int
    owner: int
    name: str
    x: int
    y: int
    dx: int = 0
    dy: int = 0
    order: str = STAND
    target: Optional[int] = None
    dest_system: Optional[int] = None
    posture: str = "M"                   # M H N F AH AN
    role: str = "M"                      # M SC MR GC RD OF DF PT RO
    ro_gc: int = 0
    ro_rd: int = 0
    ro_role: str = "SC"
    speed: Optional[int] = None          # None = automatic (slowest ship of the main body)
    ox: int = 0
    oy: int = 0
    alive: bool = True


@dataclass
class Troop:
    number: int
    owner: int
    type: str
    system: Optional[int] = None         # system id when on the ground
    ship: Optional[int] = None           # ship number when aboard
    posture: str = "A"
    built_turn: int = 0
    alive: bool = True

    @property
    def ttype(self):
        return TROOP_TYPES[self.type]


@dataclass
class Leader:
    id: int
    name: str
    owner: int
    mgmt: int = 50
    eng: int = 50
    combat: int = 50
    intel: int = 50
    social: int = 50
    age: int = 0
    renamed: bool = False
    status: str = "limbo"                # limbo | transit | posted | ice
    system: Optional[int] = None         # destination / post when assigned to a system
    fleet: Optional[int] = None          # destination / post when assigned to a fleet
    transit: int = 0                     # turns until arrival (status transit) / on ice
    alive: bool = True
    description: str = ""


@dataclass
class Spy:
    number: int
    owner: int
    system: int
    transit: int = 0
    mission: Optional[str] = None
    mission_arg: Optional[int] = None
    alive: bool = True


@dataclass
class Empire:
    id: int
    name: str
    kind: str = NPR
    eu: int = 100
    iu_depot: int = 50
    home_x: int = 50
    home_y: int = 50
    relations: dict[int, str] = field(default_factory=dict)
    techs: set[int] = field(default_factory=lambda: {0})
    future_tech: int = 0
    renamed: bool = False
    autosisd: bool = True
    # AOMT, "Autogenerate orders on missed turn" (Dave 2026-11-19, DECISIONS W-29): when the host
    # forces a turn this race hasn't submitted, its unsubmitted draft runs, or with no draft the
    # computer writes its orders from its own view.  On by default (Dave 2026-11-20); saves
    # from before the field load as on
    aomt: bool = True
    split_trade: dict[int, int] = field(default_factory=dict)   # % kicked back to owner
    deny_trade: dict[int, int] = field(default_factory=dict)    # % of normal DCT allowed
    systems_captured: int = 0
    seen_systems: dict[int, dict] = field(default_factory=dict)  # sys id -> last seen info
    # every square ever inside one of this empire's scans: base64 board x board bitmask (mhgc/scanmask)
    scan_history: str = ""
    stats: dict[str, float] = field(default_factory=dict)
    ranks: dict[str, int] = field(default_factory=dict)
    vp: int = 0

    @property
    def is_npr(self) -> bool:
        return self.kind in (NPR, INDEPENDENT)

    @property
    def alive(self) -> bool:
        return self.kind != DEAD

    def has_contact(self, other: int) -> bool:
        return other in self.relations


@dataclass
class GameState:
    name: str
    seed: int
    turn: int = 0
    empires: dict[int, Empire] = field(default_factory=dict)
    systems: list[System] = field(default_factory=list)
    ships: dict[int, Ship] = field(default_factory=dict)
    fleets: dict[int, Fleet] = field(default_factory=dict)
    troops: dict[int, Troop] = field(default_factory=dict)
    leaders: dict[int, Leader] = field(default_factory=dict)
    spies: dict[int, Spy] = field(default_factory=dict)
    next_leader_id: int = 1
    winner: Optional[int] = None
    winners_vp: dict[int, int] = field(default_factory=dict)
    # Computer-empire memory (the C kept the scout grid in npr_state.dat): empire id -> plain JSON
    # data owned by mhgc/npr (string keys only, so a save/load round trip is exact).  Never sent
    # to a browser (view.py whitelists fields).
    npr_state: dict[int, dict[str, Any]] = field(default_factory=dict)
    # AOMT stand-in memory for human races (DECISIONS W-29): empire id -> a bot memory built from
    # that race's own view only, kept across consecutive missed turns and started afresh after a
    # turn the player gave orders.  Like npr_state, never sent to a browser.
    aomt_state: dict[int, dict[str, Any]] = field(default_factory=dict)
    # Board and bins (Dave 2026-11-13, DECISIONS W-13).  Saves from before then load as the
    # classic 100x100 board with 4x4 bins and none empty.
    board: int = 100
    bins: int = 4
    empty_bins: list[list[int]] = field(default_factory=list)     # [bx, by] bins with no home
    # computer empires' chat boasts: "off" / "quiet" / "normal" (W-14); the app keeps the
    # setting in meta.json and copies it here before running a turn
    chatter: str = "normal"
    # Races that can't win and earn no stat-bonus VP this turn: the host's own race in a game with
    # another human player (Dave 2026-11-19, DECISIONS W-28).  The app works it out from the
    # seats and copies it here before every turn (as `chatter`); the engine never decides it.
    unranked: list[int] = field(default_factory=list)

    # ---- lookups ------------------------------------------------------------------------
    def system_named(self, name: str) -> Optional[System]:
        for s in self.systems:
            if s.name == name:
                return s
        return None

    def system_at(self, x: int, y: int) -> Optional[System]:
        for s in self.systems:
            if s.x == x and s.y == y:
                return s
        return None

    def empire_named(self, name: str) -> Optional[Empire]:
        for e in self.empires.values():
            if e.name == name:
                return e
        return None

    def fleet_named(self, name: str, owner: Optional[int] = None) -> Optional[Fleet]:
        """A live fleet called `name`; with `owner`, only that empire's (fleet names are unique per
        empire, not galaxy-wide: Dave 2026-11-16, DECISIONS G-16)."""
        for f in self.fleets.values():
            if f.name == name and f.alive and (owner is None or f.owner == owner):
                return f
        return None

    def leader_named(self, name: str) -> Optional[Leader]:
        for ld in self.leaders.values():
            if ld.name == name and ld.alive:
                return ld
        return None

    def ship(self, number: int) -> Optional[Ship]:
        s = self.ships.get(number)
        return s if s is not None and s.alive else None

    def live_ships(self):
        return [s for s in self.ships.values() if s.alive]

    def live_troops(self):
        return [t for t in self.troops.values() if t.alive]

    def troops_aboard(self, ship_number: int) -> list[Troop]:
        return [t for t in self.troops.values() if t.alive and t.ship == ship_number]

    def troops_at(self, sys_id: int) -> list[Troop]:
        return [t for t in self.troops.values() if t.alive and t.system == sys_id]

    def fleet_ships(self, fleet_number: int) -> list[Ship]:
        return [s for s in self.ships.values() if s.alive and s.fleet == fleet_number]

    def governor(self, sys_id: int) -> Optional[Leader]:
        """The leader posted at a system (first match; normally the owner's)."""
        sysobj = self.systems[sys_id]
        best = None
        for ld in self.leaders.values():
            if ld.alive and ld.status == "posted" and ld.system == sys_id:
                if ld.owner == sysobj.owner:
                    return ld
                best = best or ld
        return None

    def admiral(self, fleet_number: int) -> Optional[Leader]:
        for ld in self.leaders.values():
            if ld.alive and ld.status == "posted" and ld.fleet == fleet_number:
                return ld
        return None

    def players(self) -> list[Empire]:
        """Empires that take part in rankings (rules:238: NPRs are not represented)."""
        return [e for e in self.empires.values() if e.kind == HUMAN]

    def cargo_ct(self, ship: Ship) -> int:
        return len(self.troops_aboard(ship.number))

    def free_cargo(self, ship: Ship, item: str) -> int:
        """Free capacity in pop units (item 'P') or AU/IU units ('A'/'I') (gcutils.c:494)."""
        k = ship.stype.cargo - ship.cargo_pop - self.cargo_ct(ship)
        if item == "P":
            # pop needs a whole cargo point free of AU/IU too
            used_goods_points = -(-(ship.cargo_au + ship.cargo_iu) // K.CARGO_UNITS_PER_POINT)
            return max(0, k - used_goods_points)
        return max(0, k * K.CARGO_UNITS_PER_POINT - ship.cargo_au - ship.cargo_iu)

    def cargo_points_used(self, ship: Ship) -> int:
        goods = -(-(ship.cargo_au + ship.cargo_iu) // K.CARGO_UNITS_PER_POINT)
        return goods + ship.cargo_pop + self.cargo_ct(ship)


# ---- JSON serialisation -------------------------------------------------------------------

_CLASSES = {c.__name__: c for c in (System, Ship, Fleet, Troop, Leader, Spy, Empire, GameState)}


def _encode(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj):
        return {f.name: _encode(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, (set, frozenset)):
        return sorted(_encode(v) for v in obj)
    if isinstance(obj, dict):
        return {str(k): _encode(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_encode(v) for v in obj]
    return obj


@functools.lru_cache(maxsize=None)
def _type_hints(tp: type) -> dict:
    return typing.get_type_hints(tp)          # cached: evaluating the hints dominated loading


def _decode(tp: Any, value: Any) -> Any:
    if value is None:
        return None
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin is typing.Union:
        inner = [a for a in args if a is not type(None)]
        return _decode(inner[0], value)
    if isinstance(tp, type) and dataclasses.is_dataclass(tp):
        hints = _type_hints(tp)
        kwargs = {}
        for f in dataclasses.fields(tp):
            if f.name in value:
                kwargs[f.name] = _decode(hints[f.name], value[f.name])
        return tp(**kwargs)
    if origin in (set, frozenset):
        return {_decode(args[0], v) for v in value}
    if origin is list:
        return [_decode(args[0], v) for v in value]
    if origin is tuple:
        return tuple(value)
    if origin is dict:
        kt, vt = args
        return {(int(k) if kt is int else k): _decode(vt, v) for k, v in value.items()}
    if tp is float:
        return float(value)
    return value


def to_dict(state: GameState) -> dict:
    d = _encode(state)
    d["save_version"] = SAVE_VERSION
    return d


def from_dict(d: dict) -> GameState:
    d = dict(d)
    d.pop("save_version", None)
    return _decode(GameState, d)


def dumps(state: GameState) -> str:
    return json.dumps(to_dict(state), separators=(",", ":"))


def loads(text: str) -> GameState:
    return from_dict(json.loads(text))


def save(state: GameState, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(dumps(state))


def load(path: str) -> GameState:
    with open(path, encoding="utf-8") as fh:
        return loads(fh.read())
