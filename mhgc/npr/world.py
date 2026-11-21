"""The bot's picture of the game, built ONLY from `mhgc.view.view()` (the read model a human player
gets) plus the bot's own memory.  Nothing here touches the GameState.

All coordinates are the empire's relative ones (home = the board centre: 50,50 on the classic
100x100 board, 37,37 on 75x75, 25,25 on 50x50), exactly as in the view and in orders.  The board side comes from
the view (`game.board`); `build()` records it for `dist()` in a context variable, so concurrent
bots of games with different boards (server threads) don't interfere.  Static tables (ship, troop, tech and artifact data) are public rules knowledge.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from types import SimpleNamespace as NS
from typing import Optional

from ..data import constants as K
from ..data.ships import SHIP_TYPES
from ..data.troops import TROOP_TYPES

HAB_VALUE = {v: k for k, v in K.HAB_NAMES.items()}
STATUS = {"Norm": K.NORMAL, "UA": K.UNDER_ATTACK, "INT": K.INTERDICTED}


_BOARD: ContextVar[int] = ContextVar("mhgc_npr_board", default=K.BOARD)


def board() -> int:
    """The board side of the game the bot is planning for (set by `build`)."""
    return _BOARD.get()


def set_board(n: int) -> None:
    _BOARD.set(int(n))


def home_xy() -> tuple[int, int]:
    """Where the bot sees its own home (the board centre)."""
    b = _BOARD.get()
    return b // 2, b // 2


def dist(ax: int, ay: int, bx: int, by: int) -> int:
    b = _BOARD.get()
    dx = abs(ax - bx) % b
    dy = abs(ay - by) % b
    return max(min(dx, b - dx), min(dy, b - dy))


def turns_to(move: int, d: int) -> int:
    return 0 if d <= 0 else 1 + (d - 1) // max(1, move)


@dataclass
class World:
    view: dict
    mem: dict
    turn: int
    eid: int
    name: str
    eu: int
    iu_depot: int
    vp: int
    techs: set
    systems: list = field(default_factory=list)       # own systems (NS)
    ships: list = field(default_factory=list)         # own ships (NS)
    fleets: list = field(default_factory=list)
    troops: list = field(default_factory=list)
    leaders: list = field(default_factory=list)
    spies: list = field(default_factory=list)
    races: dict = field(default_factory=dict)         # id -> {name, kind, stance}
    known: dict = field(default_factory=dict)         # system id -> NS (foreign, remembered)
    contacts: list = field(default_factory=list)      # scanned foreign ships (NS)
    results: dict = field(default_factory=dict)
    making_peace: set = field(default_factory=set)    # races we EWA this turn (diplo.plan)

    # ---- helpers ----------------------------------------------------------------------
    @property
    def persona(self) -> dict:
        return self.mem["persona"]

    @property
    def populated(self) -> list:
        return [s for s in self.systems if s.pop > 0]

    def sys_by_id(self, sid: int):
        for s in self.systems:
            if s.id == sid:
                return s
        return self.known.get(sid)

    def system_at(self, x: int, y: int):
        for s in self.systems:
            if (s.x, s.y) == (x, y):
                return s
        for s in self.known.values():
            if (s.x, s.y) == (x, y):
                return s
        return None

    def home(self):
        for s in self.systems:
            if (s.x, s.y) == home_xy():
                return s
        return max(self.populated, key=lambda s: (s.pop, -s.id), default=None)

    def stance(self, rid: int) -> str:
        r = self.races.get(rid)
        return r["stance"] if r else "N"

    def at_war(self, rid: int) -> bool:
        return self.stance(rid) in ("W", "E")

    def allied(self, rid: int) -> bool:
        return self.stance(rid) == "A"

    def contacted(self) -> list[int]:
        return sorted(r for r, d in self.races.items() if r != 0 and d["kind"] in
                      ("player", "npr"))

    def race_name(self, rid: int) -> str:
        r = self.races.get(rid)
        return r["name"] if r else f"race {rid}"

    def has_tech(self, t: int) -> bool:
        return t == 0 or t in self.techs

    def nearest_own(self, x: int, y: int, populated=True):
        pool = self.populated if populated else self.systems
        return min(pool, key=lambda s: (dist(x, y, s.x, s.y), s.id), default=None)

    def dist_to_us(self, x: int, y: int) -> int:
        return min((dist(x, y, s.x, s.y) for s in self.populated), default=99)

    def ships_at(self, x: int, y: int) -> list:
        return [sh for sh in self.ships if (sh.x, sh.y) == (x, y)]

    def armed(self) -> list:
        return [sh for sh in self.ships if sh.st.attack > 0]


def build(view: dict, mem: dict) -> World:
    e = view["empire"]
    set_board(view["game"].get("board", K.BOARD))
    w = World(view=view, mem=mem, turn=view["game"]["turn"], eid=e["id"], name=e["name"],
              eu=e["eu"], iu_depot=e["iu_depot"], vp=e.get("vp", 0), techs=set(e["techs"]),
              results=view.get("results") or {})
    for s in view["systems"]:
        w.systems.append(NS(
            id=s["id"], name=s["name"], x=s["x"], y=s["y"], pop=s["pop"], happy=s["happy"],
            trend=s["trend"], hab=s["hab_value"], mr=s["mr"], ar=s["ar"], infra=s["infra"],
            status=STATUS[s["status"]], starport=s["starport"], au=s["au"], iu=s["iu"],
            csp=(s["profile"]["au"], s["profile"]["iu"], s["profile"]["eu"]),
            artifacts=set(s["artifacts"]), governor=s["governor"],
            scan=s["scan_range"], routes=[r["race"] for r in s["trade_routes"]],
            troops=s["troops"], production=s.get("production") or {}, mine=True, owner=w.eid))
    for sh in view["ships"]:
        cargo = sh.get("cargo") or {}
        w.ships.append(NS(
            number=sh["number"], type=sh["type"], st=SHIP_TYPES[sh["type"]], x=sh["x"],
            y=sh["y"], dx=sh["dest"]["x"], dy=sh["dest"]["y"], order=sh["order"],
            target=sh["target"], dest_system=sh["dest_system"], posture=sh["posture"],
            role=sh["role"], fleet=sh["fleet"], built=sh["built_turn"],
            cargo=[cargo.get("AU", 0), cargo.get("IU", 0), cargo.get("POP", 0),
                   list(cargo.get("CT", []))]))
    for f in view["fleets"]:
        w.fleets.append(NS(name=f["name"], x=f["x"], y=f["y"], dx=f["dest"]["x"],
                           dy=f["dest"]["y"], order=f["order"], ships=list(f["ships"]),
                           admiral=f["admiral"], posture=f["posture"], role=f["role"]))
    for t in view["troops"]:
        w.troops.append(NS(number=t["number"], type=t["type"], tt=TROOP_TYPES[t["type"]],
                           system=t["system"], ship=t["ship"], posture=t["posture"]))
    w.leaders = [NS(**ld) for ld in view["leaders"]]
    w.spies = [NS(**sp) for sp in view["spies"]]
    for r in view["races"]:
        w.races[r["id"]] = {"name": r["name"], "kind": r["kind"], "stance": r["our_stance"]}
    own_ids = {s.id for s in w.systems}
    intel = mem["intel"]
    for ks in view["known_systems"]:
        if ks["id"] in own_ids or not ks["name"]:
            continue                             # (an unnamed CD-ROM reveal can't be ordered to)
        w.known[ks["id"]] = NS(id=ks["id"], name=ks["name"], x=ks["x"], y=ks["y"],
                               owner=ks["owner"], last_seen=ks["last_seen"], mine=False,
                               intel=intel.get(str(ks["id"])))
    # this turn's scans: remember what short scans show of foreign systems
    for sc in (view.get("scans") or {}).get("systems") or []:
        if sc.get("level") == "short" and sc["id"] not in own_ids:
            info = {"t": w.turn, "owner": sc.get("owner") or 0, "pop": sc.get("pop", 0),
                    "hab": HAB_VALUE.get(sc.get("hab"), 3), "mr": sc.get("mr", False),
                    "ar": sc.get("ar", False), "starport": sc.get("starport", 0),
                    "status": sc.get("status"), "infra": sc.get("infra", 0),
                    "routes": list(sc.get("trade_routes") or []),
                    "weapons": [a for a in sc.get("artifacts") or [] if a in ("PD", "SW",
                                                                              "APD")],
                    "artifacts": len(sc.get("artifacts") or []),
                    "troops": [[t["owner"], t["type"], t["posture"]]
                               for t in sc.get("troops") or []]}
            intel[str(sc["id"])] = info
            if sc["id"] in w.known:
                w.known[sc["id"]].intel = info
                w.known[sc["id"]].owner = info["owner"] or None
    for c in (view.get("scans") or {}).get("ships") or []:
        if c["owner"] == w.eid:
            continue
        w.contacts.append(NS(number=c["number"], owner=c["owner"], type=c["type"],
                             st=SHIP_TYPES[c["type"]], x=c["x"], y=c["y"], ox=c["ox"],
                             oy=c["oy"], short=c["level"] == "short", fleet=c.get("fleet"),
                             cts=len((c.get("cargo") or {}).get("CT", [])) if
                             c["level"] == "short" else None))
    return w


def frontier(w, s, reach: int = 10) -> bool:
    """A system with a known foreign (not allied) system within `reach` squares."""
    for k in w.known.values():
        o = k.owner
        if o and o != w.eid and not w.allied(o) and dist(k.x, k.y, s.x, s.y) <= reach:
            return True
    return False


def hab_of(s) -> float:
    """Habitability of a known foreign system: from a short scan, else a guess."""
    it = getattr(s, "intel", None)
    if it:
        return it["hab"]
    return 2.5


def est_ground(s) -> float:
    """Estimated ground defence (with postures) of a known system's troops."""
    it = getattr(s, "intel", None)
    if not it:
        return 8.0
    d = 0.0
    for owner, typ, post in it["troops"]:
        tt = TROOP_TYPES[typ]
        mult = 1.5 if post == "defend" else 2.0 if post == "dug in" else 1.0
        d += tt.defense * mult
    return d


__all__ = ["World", "build", "dist", "turns_to", "hab_of", "frontier", "est_ground", "HAB_VALUE", "board",
           "set_board", "home_xy"]
_unused: Optional[int] = None
