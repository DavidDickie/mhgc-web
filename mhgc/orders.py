"""Structured order model and the classic text-order parser.

Every order code has a spec (ORDER_SPECS) from which a typed dataclass is generated, e.g.
`MO(ship=32, x=10, y=10)`.  Orders are built either from the UI as JSON
(`order_from_dict({"code": "MO", "ship": 32, "x": 10, "y": 10})`) or from the classic text format
(`parse_line("MO 32 10 10")`), and `to_text()` writes them back in the classic format.

This module does *syntax* validation (argument count, types, ranges) and raises `OrderSyntaxError`
with a clear message.  Validation against the game state (ownership, money, tech, status ...) is
done by the engine when the order executes (engine/orders_exec.py), because orders run in sequence
and earlier orders change what later ones can do (rules:1691-1754).

Coordinates in orders are RELATIVE to the ordering empire (home at 50,50), as players see them.
"""
from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
from typing import Any, ClassVar, Optional

from .data import constants as K
from .data.artifacts import ARTIFACTS, SPY_KEY
from .data.ships import SHIP_TYPES
from .data.troops import TROOP_TYPES


class OrderSyntaxError(ValueError):
    pass


@dataclass
class Order:
    code: ClassVar[str] = ""
    spec: ClassVar[tuple] = ()
    category: ClassVar[str] = ""
    help: ClassVar[str] = ""
    line: str = field(default="", compare=False, repr=False, kw_only=True)
    warnings: list = field(default_factory=list, compare=False, repr=False, kw_only=True)

    def args(self) -> dict:
        return {name: getattr(self, name) for name, _ in self.arg_fields()}

    @classmethod
    def arg_fields(cls):
        return [(a.name, a.kind) for a in cls.spec]

    def to_dict(self) -> dict:
        d = {"code": self.code}
        for name, _ in self.arg_fields():
            v = getattr(self, name)
            if v is not None and v != [] and v != "":
                d[name] = list(v) if isinstance(v, tuple) else v
        if self.code == "MESSAGE":
            d["recipients"] = list(self.recipients)
            d["text"] = self.text
        return d

    def to_text(self) -> str:
        if self.code == "MESSAGE":
            head = "MESSAGE" + "".join(" " + r for r in self.recipients)
            return head + "\n" + self.text + ("\n" if self.text and not self.text.endswith("\n")
                                              else "") + "."
        if self.code == "TTNPR":
            side = lambda t, c: f"ANY {c}" if c is not None else str(t)   # noqa: E731
            return (f"TTNPR {side(self.give, self.give_any_cost)} "
                    f"{side(self.want, self.want_any_cost)} {self.race}")
        parts = [self.code]
        for a in self.spec:
            v = getattr(self, a.name)
            if v is None or v == [] or v == "":
                continue
            if isinstance(v, (list, tuple)):
                parts.extend(str(i) for i in v)
            else:
                parts.append(str(v))
        return " ".join(parts)


@dataclass(frozen=True)
class Arg:
    name: str
    kind: str
    optional: bool = False
    choices: tuple = ()
    lo: Optional[int] = None
    hi: Optional[int] = None


# Argument kinds: int (any integer), nat (>= 0), coord (0..124, the largest board), str (a name token),
# choice (one of `choices`), ints (1..10 integers), text (rest of the line).
def _c(name, *choices, optional=False):
    return Arg(name, "choice", optional, tuple(choices))


ITEMS = ("A", "I", "P")
POSTURES = ("H", "N", "F")
ROLES = ("SC", "MR", "GC", "RD")
CT_POSTURES = ("A", "D", "E")
FLEET_POSTURES = ("M", "H", "N", "F", "AH", "AN")
FLEET_ROLES = ("M", "SC", "MR", "GC", "RD", "OF", "DF", "PT", "RO")
ART_KEYS = tuple(ARTIFACTS) + (SPY_KEY,)
SHIP_CODES = tuple(SHIP_TYPES)
CT_CODES = tuple(TROOP_TYPES)
SPY_MISSIONS = ("SOS", "SOT", "SOL", "SVS", "SOE", "SOM", "SON", "SAL", "SSB", "SUP", "SRS")

SHIP = Arg("ship", "nat")
FLEET = Arg("fleet", "str")
SYS = Arg("system", "str")
RACE = Arg("race", "str")
X = Arg("x", "coord")
Y = Arg("y", "coord")
N = Arg("amount", "nat")
CT = Arg("ct", "nat")
SPY = Arg("spy", "nat")
LEADER = Arg("leader", "str")
# BS / BCU build count (Dave 2026-11-18, DECISIONS G-19): optional, last, 1-50, default 1.
BUILD_MAX = 50
COUNT = Arg("count", "int", True, lo=1, hi=BUILD_MAX)

# code: (category, args, help)
ORDER_SPECS: dict[str, tuple[str, tuple[Arg, ...], str]] = {
    # ---- ships
    "MO": ("ship", (SHIP, X, Y), "Move ship to x,y"),
    "MS": ("ship", (SHIP, SYS), "Move ship to a system you have scanned"),
    "I": ("ship", (SHIP, Arg("target", "nat")), "Intercept a ship"),
    "G": ("ship", (SHIP,), "Guard: move to enemy ships within one move"),
    "SP": ("ship", (SHIP, _c("posture", *POSTURES)), "Set ship posture"),
    "CSCR": ("ship", (SHIP, _c("role", *ROLES)), "Set ship combat role"),
    "DS": ("ship", (SHIP,), "Disband ship"),
    "SS": ("ship", (SHIP,), "Salvage ship for 75% (uses a starport build)"),
    "L": ("ship", (SHIP, _c("item", *ITEMS), N), "Load cargo at your system"),
    "U": ("ship", (SHIP, _c("item", *ITEMS), N), "Unload cargo at your system"),
    "UG": ("ship", (SHIP, _c("item", *ITEMS), N), "Unload cargo as a gift"),
    "SL": ("ship", (SHIP, _c("item", *ITEMS), N), "System loads cargo onto a ship"),
    "LOCT": ("ship", (SHIP, CT), "Load a combat troop"),
    "LACT": ("ship", (SHIP, CT), "Land a combat troop"),
    "DOCT": ("ship", (SHIP,), "Drop the ship's troops in drop pods after movement"),
    "CTT": ("ship", (SHIP,), "Convert transport to trade route"),
    "WTP": ("ship", (SHIP, SYS), "Send ship through a warp tunnel"),
    "GS": ("ship", (RACE, SHIP), "Gift a ship to another race"),
    # ---- fleets
    "CF": ("fleet", (Arg("name", "str"), X, Y), "Create fleet at x,y"),
    "CFXY": ("fleet", (Arg("name", "str"), X, Y), "Create fleet; unfleeted ships there join"),
    "AFXY": ("fleet", (FLEET, X, Y), "Unfleeted ships at x,y join the fleet"),
    "AF": ("fleet", (FLEET, Arg("ships", "ints")), "Add ships to fleet"),
    "LF": ("fleet", (FLEET, Arg("ships", "ints")), "Remove ships from fleet"),
    "MF": ("fleet", (FLEET, X, Y), "Move fleet to x,y"),
    "MFS": ("fleet", (FLEET, SYS), "Move fleet to a system"),
    "FIS": ("fleet", (FLEET, Arg("target", "nat")), "Fleet intercepts a ship"),
    "DF": ("fleet", (FLEET,), "Disband fleet"),
    # merge fleets (Dave 2026-11-21, DECISIONS G-27): a new game order, not in the rules
    "MGF": ("fleet", (FLEET, Arg("into", "str")),
            "Merge a fleet into another of yours at the same square"),
    "FR": ("fleet", (FLEET,), "Fleet report"),
    "FS": ("fleet", (FLEET, Arg("speed", "speed")), "Fleet speed: A or 1-9"),
    "CFP": ("fleet", (FLEET, _c("posture", *FLEET_POSTURES)), "Fleet posture"),
    "CFCR": ("fleet", (FLEET, _c("role", *FLEET_ROLES), Arg("gc", "nat", True),
                       Arg("rd", "nat", True), _c("other", *ROLES, optional=True)),
             "Fleet combat role (RO gc rd role)"),
    "FL": ("fleet", (FLEET, _c("item", *ITEMS), N), "Fleet load"),
    "FU": ("fleet", (FLEET, _c("item", *ITEMS), N), "Fleet unload"),
    "FUG": ("fleet", (FLEET, _c("item", *ITEMS), N), "Fleet unload gift"),
    "FLOCT": ("fleet", (FLEET, CT), "Fleet load combat troop"),
    "FLACT": ("fleet", (FLEET, CT), "Fleet land combat troop"),
    "WTPF": ("fleet", (FLEET, SYS), "Send fleet through a warp tunnel"),
    # ---- systems
    "NSY": ("system", (SYS, Arg("name", "str")), "Rename system"),
    "CSP": ("system", (SYS, Arg("au", "pct"), Arg("iu", "pct"), Arg("eu", "pct")),
            "System profile %AU %IU %EU"),
    "CAP": ("system", (SYS, Arg("amount", "pct")), "AU profile: % of stockpile released"),
    "CAPN": ("system", (SYS, Arg("amount", "pct")), "AU profile: AUs released per turn"),
    "SISD": ("system", (SYS, N), "IUs to move to the supply depot this turn"),
    "CI": ("system", (SYS, N), "Counter intelligence (10 EU per point)"),
    "BCU": ("system", (SYS, _c("type", *CT_CODES), _c("posture", *CT_POSTURES, optional=True),
                       COUNT), "Build combat unit (optionally several)"),
    "BS": ("system", (SYS, _c("type", *SHIP_CODES), _c("posture", *POSTURES, optional=True),
                      _c("role", *ROLES, optional=True), COUNT), "Build ship (optionally several)"),
    "BI": ("system", (SYS, N), "Build infrastructure (10 IU each)"),
    "DI": ("system", (SYS, N), "Destroy infrastructure (5 EU each)"),
    "BT": ("system", (SYS, _c("artifact", *ART_KEYS)), "Build tech artifact (S = spy)"),
    "DT": ("system", (SYS, _c("artifact", *ARTIFACTS)), "Destroy tech artifact"),
    "BSP": ("system", (SYS,), "Build or upgrade starport by one class"),
    "DSP": ("system", (SYS,), "Reduce starport by one class (10 EU)"),
    "TP": ("system", (SYS, _c("item", "A", "I", "C"), N, Arg("to", "str")),
           "Farcaster: send AUs/IUs/a CT to another system"),
    "SR": ("system", (SYS,), "Release a system with 1 pop or less"),
    "SSI": ("system", (RACE, SYS), "Send system information to a race"),
    # ---- troops
    "DCT": ("troop", (CT,), "Disband combat troop"),
    "SCT": ("troop", (CT,), "Salvage combat troop for 50% (uses a starport build)"),
    "CCP": ("troop", (CT, _c("posture", *CT_POSTURES)), "Combat troop posture"),
    # ---- leaders
    "CLN": ("leader", (LEADER, Arg("name", "str")), "Rename leader (once)"),
    "ML": ("leader", (LEADER, SYS), "Move leader to a system (arrives in two turns)"),
    "MLF": ("leader", (LEADER, FLEET), "Move leader to a fleet (arrives in two turns)"),
    "PLOI": ("leader", (LEADER,), "Put leader on ice"),
    "LR": ("leader", (), "Leader report"),
    # ---- spies
    "SMV": ("spy", (SPY, SYS), "Move spy to a system"),
    "SMO": ("spy", (SPY, X, Y), "Move spy to the system at x,y"),
    "SET": ("spy", (SPY, RACE), "Spy: eliminate a race's trade route"),
    **{m: ("spy", (SPY,), "Spy mission") for m in SPY_MISSIONS},
    # ---- empire / diplomacy
    "DA": ("empire", (RACE,), "Declare alliance"),
    "DW": ("empire", (RACE,), "Declare war"),
    "EWA": ("empire", (RACE,), "End war or alliance"),
    "GE": ("empire", (RACE, N), "Gift EUs"),
    "GT": ("empire", (RACE, Arg("tech", "nat")), "Gift technology"),
    # TTNPR: each side is a tech number or "ANY <cost>" (Dave 2026-11-19, DECISIONS G-23): the
    # computer empire picks a tech of exactly that cost when the turn runs.  Exactly one of
    # give / give_any_cost, and one of want / want_any_cost (checked in _post_check).
    "TTNPR": ("empire", (Arg("give", "nat", True), Arg("give_any_cost", "nat", True),
                         Arg("want", "nat", True), Arg("want_any_cost", "nat", True), RACE),
              "Trade a technology with an NPR"),
    "PT": ("empire", (Arg("tech", "nat"),), "Purchase technology"),
    "CRP": ("empire", (Arg("tech", "nat"),), "Crash research program (2x cost)"),
    "DD": ("empire", (RACE, Arg("amount", "int", lo=25, hi=100)), "Deny DCT trade (25-100%)"),
    "SD": ("empire", (RACE, Arg("amount", "pct")), "Split DCT trade (0-100%)"),
    "AUTOSISD": ("empire", (), "Automatically resupply IU depot"),
    "NOAUTOSISD": ("empire", (), "Turn off automatic resupply"),
    "AOMT": ("empire", (_c("mode", "ON", "OFF"),),
             "Autogenerate orders on missed turn (ON or OFF)"),
    "LT": ("empire", (), "List technology"),
    "CRN": ("empire", (Arg("name", "str"),), "Rename your race (once)"),
    "RESIGN": ("empire", (), "Resign: your empire becomes an NPR"),
    "ECHO": ("misc", (Arg("text", "text", True),), "Echo text into the report"),
    "MESSAGE": ("misc", (), "Send a message"),
}

# Classic order-file keywords that have no meaning in the web game: accepted and ignored.
IGNORED = {"NMC", "SMC", "LMC", "MAP", "NOMAP", "CONFIRM", "NOCONFIRM", "HOLD", "NOHOLD",
           "SEGMENT", "NOSEGMENT", "SIMTURN", "NOSIMTURN", "ALLSYS", "NOALLSYS", "RESEND",
           "SPW", "EMAIL", "MHGC_ORDERS", "MHGC_ADMIN", "MHGC_DELAYED_ORDERS", "END_ORDERS"}
# C game-master / NPR-only codes, not available to anyone (DECISIONS B-40).
REMOVED = {"ATTP", "FCDR", "BANG", "BANGALL", "ISNPR", "LDD", "NPR_C_1", "NPR_C_2", "RNI", "RC",
           "CFS"}
# Orders dropped from the web game (DECISIONS G-01, G-09).  Typing one is an error, so nobody
# thinks it did something.  Each maps to the reason given.
_DISPLAY_OPTION = "It was a display option that had no effect in the web game"
RETIRED = {"AUTOFLEET": _DISPLAY_OPTION, "NOAUTOFLEET": _DISPLAY_OPTION,
           "TRACKSCAN": _DISPLAY_OPTION, "NOTRACKSCAN": _DISPLAY_OPTION,
           "CGR": "Changing a system's growth rate was taken out of the web game: every system "
                  "grows at the standard rate (100)"}


def _not_available(code: str) -> OrderSyntaxError:
    if code in RETIRED:
        return OrderSyntaxError(f"{code} no longer exists. {RETIRED[code]}, so it was removed; "
                                f"delete this line.")
    return OrderSyntaxError(f"{code} isn't available in this game.")

ORDER_CLASSES: dict[str, type[Order]] = {}


def _make_classes():
    for code, (cat, args, hlp) in ORDER_SPECS.items():
        fields = []
        for a in args:
            if a.kind == "ints":
                fields.append((a.name, list, field(default_factory=list)))
            else:
                fields.append((a.name, Optional[Any], field(default=None)))
        if code == "MESSAGE":
            fields = [("recipients", list, field(default_factory=list)),
                      ("text", str, field(default=""))]
        cls = dataclasses.make_dataclass(code.replace("_", "") + "Order", fields, bases=(Order,))
        cls.code = code
        cls.spec = args
        cls.category = cat
        cls.help = hlp
        ORDER_CLASSES[code] = cls


_make_classes()
globals().update({c: k for c, k in ORDER_CLASSES.items() if c.isidentifier()})


# ---- argument conversion ------------------------------------------------------------------

def _cap(name: str) -> str:
    return name[:1].upper() + name[1:]


def _int(tok: str, what: str) -> int:
    try:
        return int(tok)
    except ValueError:
        raise OrderSyntaxError(f"{_cap(what)} must be a whole number, not '{tok}'.") from None


def _convert(code: str, a: Arg, value: Any) -> Any:
    if value is None:
        return None
    k = a.kind
    if k in ("int", "nat", "coord", "pct"):
        v = value if isinstance(value, int) and not isinstance(value, bool) else _int(str(value),
                                                                                       a.name)
        lo = a.lo if a.lo is not None else {"nat": 0, "coord": 0, "pct": 0}.get(k)
        # a coordinate is checked against the game's own board when the order runs
        # (context.abs_xy); here only against the largest board (0..124, G-30; was 0..99)
        hi = a.hi if a.hi is not None else {"coord": K.MAX_BOARD - 1, "pct": 100}.get(k)
        if lo is not None and v < lo:
            if k == "nat":
                raise OrderSyntaxError(f"{_cap(a.name)} can't be negative.")
            raise OrderSyntaxError(f"{_cap(a.name)} must be between {lo} and {hi}, not {v}."
                                   if hi is not None else
                                   f"{_cap(a.name)} must be at least {lo}, not {v}.")
        if hi is not None and v > hi:
            raise OrderSyntaxError(f"{_cap(a.name)} must be between {lo} and {hi}, not {v}.")
        return v
    if k == "choice":
        v = str(value)
        if v not in a.choices:
            raise OrderSyntaxError(f"'{v}' isn't a valid {a.name}. Use one of "
                                  f"{', '.join(a.choices)}.")
        return v
    if k == "speed":
        v = str(value)
        if v == "A":
            return "A"
        n = _int(v, "speed")
        if not 1 <= n <= 9:
            raise OrderSyntaxError(f"Speed must be A or 1-9, not '{v}'.")
        return n
    if k == "ints":
        vals = [value] if isinstance(value, (int, str)) else list(value)
        out = [_int(str(v), a.name) for v in vals]
        if not 1 <= len(out) <= 10:
            raise OrderSyntaxError("Give between 1 and 10 ship numbers.")
        if any(v < 0 for v in out):
            raise OrderSyntaxError("Ship numbers can't be negative.")
        return out
    if k in ("str", "text"):
        v = str(value)
        if not v and k == "str":
            raise OrderSyntaxError(f"{_cap(a.name)} needs a name.")
        return v
    raise AssertionError(k)


def any_costs() -> list[int]:
    """The list prices a TTNPR "ANY <cost>" may name: those of the tradeable technologies."""
    from .data.techs import FUTURE_TECH, TECHS
    return sorted({t.cost for i, t in TECHS.items() if i not in (0, FUTURE_TECH)})


def _any_side(v):
    """'ANY 1000', 'ANY:1000' or 'any:1000' (a JSON give/want given as text) -> 1000, else None."""
    if not isinstance(v, str):
        return None
    m = re.fullmatch(r"\s*ANY\s*[:\s]\s*(\S+)\s*", v, re.I)
    if not m:
        return None
    return _int(m.group(1), "the ANY cost")


def _ttnpr_check(o: Order) -> None:
    for side, label in (("give", "give (the tech you offer)"), ("want", "want (the tech you ask for)")):
        t, c = getattr(o, side), getattr(o, f"{side}_any_cost")
        if t is None and c is None:
            raise OrderSyntaxError(f"Missing {label}: a tech number or ANY <cost>. Usage: "
                                   f"{usage('TTNPR')}")
        if t is not None and c is not None:
            raise OrderSyntaxError(f"Give either a tech number or ANY <cost> for {side}, not "
                                   f"both.")
        if c is not None and c not in any_costs():
            raise OrderSyntaxError(f"No technology costs exactly {c} EU, so ANY {c} can't match "
                                   f"one. ANY takes a tech's list price: "
                                   f"{', '.join(map(str, any_costs()))}.")


def _post_check(o: Order) -> None:
    c = o.code
    if c == "TTNPR":
        _ttnpr_check(o)
    if c == "CSP" and o.au + o.iu + o.eu != 100:
        raise OrderSyntaxError(f"The profile must add up to 100%; this one adds up to "
                               f"{o.au + o.iu + o.eu}%.")
    if c == "CSP" and min(o.au, o.iu, o.eu) < 10:
        raise OrderSyntaxError("Each part of the profile must be at least 10%.")
    if c == "CFCR":
        if o.role == "RO" and (o.gc is None or o.rd is None or o.other is None):
            raise OrderSyntaxError("A role override needs ground combat points, raid points and a "
                                   "role for the rest: CFCR <fleet> RO <gc> <rd> <SC|MR|GC|RD>.")
        if o.role != "RO":
            o.gc = o.rd = o.other = None
    if c in ("BS", "BCU") and o.count == 1:
        o.count = None               # the default: "BS H1 T 1" is written back as "BS H1 T"
    if c in ("NSY", "CF", "CFXY", "CLN") and len(o.name) > 12:
        raise OrderSyntaxError(f"Names can be at most 12 characters; '{o.name}' has "
                               f"{len(o.name)}.")
    if c == "CRN" and len(o.name) > 15:
        raise OrderSyntaxError(f"Race names can be at most 15 characters; '{o.name}' has "
                               f"{len(o.name)}.")
    if c == "CRN" and o.name.lower() == "unknown":
        raise OrderSyntaxError("You should know better: 'Unknown' can't be a race name.")


def make_order(code: str, **kwargs) -> Order:
    """Build an order from keyword arguments, with syntax validation."""
    if code in REMOVED or code in RETIRED:
        raise _not_available(code)
    cls = ORDER_CLASSES.get(code)
    if cls is None:
        raise OrderSyntaxError(f"Unknown order code {code}.")
    if code == "MESSAGE":
        return cls(recipients=list(kwargs.get("recipients", [])), text=kwargs.get("text", ""),
                   line=kwargs.get("line", ""))
    if code == "TTNPR":
        kwargs = dict(kwargs)
        for side in ("give", "want"):
            c = _any_side(kwargs.get(side))
            if c is not None or (isinstance(kwargs.get(side), str)
                                 and kwargs[side].strip().upper() == "ANY"):
                if c is None:
                    raise OrderSyntaxError(f"ANY needs a cost: ANY <cost> for {side}, e.g. "
                                           f"ANY 1000.")
                kwargs[side] = None
                kwargs[f"{side}_any_cost"] = c
    vals = {}
    for a in cls.spec:
        v = kwargs.get(a.name)
        if v is None or (a.kind == "ints" and v == []):
            if not a.optional:
                raise OrderSyntaxError(f"Missing {a.name}. Usage: {usage(code)}")
            vals[a.name] = [] if a.kind == "ints" else None
            continue
        vals[a.name] = _convert(code, a, v)
    o = cls(**vals, line=kwargs.get("line", ""))
    _post_check(o)
    return o


def order_from_dict(d: dict) -> Order:
    d = dict(d)
    code = d.pop("code")
    return make_order(code, **d)


def usage(code: str) -> str:
    if code == "TTNPR":
        return "TTNPR <give|ANY cost> <want|ANY cost> <race>"
    cls = ORDER_CLASSES[code]
    parts = [code]
    for a in cls.spec:
        label = "|".join(a.choices) if a.kind == "choice" else a.name
        if a.kind == "ints":
            label = "ship [ship ...]"
        parts.append(f"[{label}]" if a.optional else f"<{label}>")
    return " ".join(parts)


# ---- classic text parsing -----------------------------------------------------------------

def _tokens(line: str) -> list[str]:
    toks = line.split()
    # Trailing comments: anything from a token that starts with '#' (after the first) is ignored.
    for i, t in enumerate(toks):
        if i > 0 and t.startswith("#"):
            return toks[:i]
    return toks


def parse_line(line: str) -> Optional[Order]:
    """Parse one classic order line.  Returns None for blank/comment/ignored lines."""
    raw = line.rstrip("\r\n")
    toks = _tokens(raw)
    if not toks:
        return None
    code = toks[0]
    if code == "#":
        return None
    if code in IGNORED:
        return None
    if code.startswith("#"):
        # rules:1688-1689: '#U' is not a comment, it is an unknown order.
        raise OrderSyntaxError(f"Unknown order code {code}.")
    if code in REMOVED or code in RETIRED:
        raise _not_available(code)
    cls = ORDER_CLASSES.get(code)
    if cls is None:
        raise OrderSyntaxError(f"Unknown order code {code}.")
    rest = toks[1:]
    kwargs: dict[str, Any] = {"line": raw}
    warnings: list[str] = []
    if code == "MESSAGE":
        return make_order(code, recipients=rest, text="", line=raw)
    if code == "ECHO":
        kwargs["text"] = raw.split(None, 1)[1] if len(raw.split(None, 1)) > 1 else ""
        return make_order(code, **kwargs)
    if code == "TTNPR":
        return _parse_ttnpr(rest, raw)
    if code in ("BS", "BCU"):
        # BS: posture and role in either order; BCU: posture.  Either may end with a count.
        if len(rest) < 2:
            raise OrderSyntaxError(f"Wrong number of arguments. Usage: {usage(code)}")
        kwargs["system"], kwargs["type"] = rest[0], rest[1]
        opts = rest[2:]
        if opts and opts[-1].lstrip("+-").isdigit():
            kwargs["count"] = opts[-1]
            opts = opts[:-1]
        slots = ((POSTURES, "posture"), (ROLES, "role")) if code == "BS" else \
            ((CT_POSTURES, "posture"),)
        for t in opts[:len(slots)]:
            slot = next((n for ch, n in slots if t in ch and n not in kwargs), None)
            if slot is None:
                what = "a posture or a combat role" if code == "BS" else "a posture"
                warnings.append(f"Warning: '{t}' was ignored; it isn't {what}.")
                break
            kwargs[slot] = t
        else:
            if len(opts) > len(slots):
                warnings.append(f"Warning: '{' '.join(opts[len(slots):])}' was ignored. Put # "
                                f"before comments.")
        o = make_order(code, **kwargs)
        o.warnings = warnings
        return o
    spec = cls.spec
    i = 0
    for a in spec:
        if a.kind == "ints":
            nums = []
            while i < len(rest) and len(nums) < 10:
                try:
                    nums.append(int(rest[i]))
                except ValueError:
                    warnings.append(f"Warning: '{rest[i]}' isn't a ship number, so it and the rest "
                                    f"of the line were ignored.")
                    i = len(rest)
                    break
                i += 1
            kwargs[a.name] = nums
            continue
        if i >= len(rest):
            if a.optional:
                break
            raise OrderSyntaxError(f"Wrong number of arguments. Usage: {usage(code)}")
        tok = rest[i]
        if a.optional and a.kind == "choice" and tok not in a.choices:
            warnings.append(f"Warning: '{tok}' isn't a valid {a.name}, so it was ignored.")
            break
        kwargs[a.name] = tok
        i += 1
    if i < len(rest) and not warnings and spec and spec[-1].optional:
        warnings.append(f"Warning: '{' '.join(rest[i:])}' was ignored. Put # before "
                        f"comments.")
    o = make_order(code, **kwargs)
    o.warnings = warnings
    return o


def _parse_ttnpr(rest: list[str], raw: str) -> Order:
    """TTNPR <give> <want> <race>, each of give and want a tech number, `ANY <cost>` (two tokens)
    or `ANY:<cost>` (one); ANY is not case sensitive (DECISIONS G-23).  The race is always the
    last token, so a race named "Any" is still read correctly."""
    kwargs: dict[str, Any] = {"line": raw}
    i = 0
    for side in ("give", "want"):
        if i >= len(rest):
            raise OrderSyntaxError(f"Wrong number of arguments. Usage: {usage('TTNPR')}")
        tok = rest[i]
        up = tok.upper()
        if up == "ANY":
            if i + 1 >= len(rest) or not rest[i + 1].lstrip("+-").isdigit():
                raise OrderSyntaxError(f"ANY needs a cost after it ({side}), e.g. ANY 1000. "
                                       f"Usage: {usage('TTNPR')}")
            kwargs[f"{side}_any_cost"] = rest[i + 1]
            i += 2
        elif up.startswith("ANY:"):
            kwargs[f"{side}_any_cost"] = _int(tok[4:], f"the ANY cost ({side})")
            i += 1
        else:
            kwargs[side] = tok
            i += 1
    if i >= len(rest):
        raise OrderSyntaxError(f"Wrong number of arguments. Usage: {usage('TTNPR')}")
    kwargs["race"] = rest[i]
    o = make_order("TTNPR", **kwargs)
    if i + 1 < len(rest):
        o.warnings = [f"Warning: '{' '.join(rest[i + 1:])}' was ignored. Put # before comments."]
    return o


@dataclass
class ParsedLine:
    lineno: int
    text: str
    order: Optional[Order] = None
    error: Optional[str] = None


def parse_orders_text(text: str) -> list[ParsedLine]:
    """Parse a whole classic order block (MESSAGE ... '.' blocks included).

    Header/trailer lines (MHGC_ORDERS ..., END_ORDERS) are ignored, so old order files work.
    """
    out: list[ParsedLine] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i].rstrip("\r")
        toks = raw.split()
        if toks and toks[0] == "MESSAGE":
            recipients = list(toks[1:])
            body: list[str] = []
            j = i + 1
            terminated = False
            while j < len(lines):
                t = lines[j].rstrip("\r")
                tt = t.split()
                if tt and tt[0] == ".":
                    terminated = True
                    break
                if tt and tt[0] == "MESSAGE":
                    recipients.extend(tt[1:])     # rules:2584-2588: more recipients
                elif tt and tt[0] == "END_ORDERS":
                    break
                else:
                    body.append(t)
                j += 1
            pl = ParsedLine(i + 1, raw)
            if not terminated:
                pl.error = ("This message has no end line. Add a line with just '.' after the "
                            "message text.")
            pl.order = make_order("MESSAGE", recipients=recipients, text="\n".join(body),
                                  line=raw)
            out.append(pl)
            i = j + 1
            continue
        pl = ParsedLine(i + 1, raw)
        try:
            pl.order = parse_line(raw)
        except OrderSyntaxError as exc:
            pl.error = str(exc)
        if pl.order is not None or pl.error is not None:
            out.append(pl)
        i += 1
    return out


def parse_orders(text: str) -> list[Order]:
    """Parse and return only the valid orders (errors are dropped; see parse_orders_text)."""
    return [p.order for p in parse_orders_text(text) if p.order is not None and p.error is None]


def catalogue() -> list[dict]:
    """Machine-readable order catalogue for UI forms."""
    out = []
    for code, (cat, args, hlp) in ORDER_SPECS.items():
        out.append({"code": code, "category": cat, "help": hlp, "usage": usage(code),
                    "args": [{"name": a.name, "kind": a.kind, "optional": a.optional,
                              "choices": list(a.choices), "lo": a.lo, "hi": a.hi}
                             for a in args]})
    return out
