"""Ship classes (BS order).  Values from the rules' generated tech table (rules:3170-3231), which
matches the compiled C ship_char[] (gc_vars.h:198-228), except the ship rebalance of 2026-11-19
(below).  The C 'UN' (Unknown) pseudo type is not
buildable (DECISIONS B-08).  Line types drive the Mixed Fleet Bonus (rules:819-833)."""
from __future__ import annotations

from dataclasses import dataclass

STANDARD, DEFENSIVE, FAST, OFFENSIVE = "STANDARD", "DEFENSIVE", "FAST", "OFFENSIVE"
LINE_TYPES = (STANDARD, DEFENSIVE, FAST, OFFENSIVE)


@dataclass(frozen=True)
class ShipType:
    code: str
    name: str
    attack: int
    defense: int
    scan: int
    move: int
    cargo: int
    iu_cost: int
    eu_cost: int
    tech: int        # tech id required (0 = basic spaceflight)
    line: str

    @property
    def is_warship(self) -> bool:
        return self.attack > 0

    @property
    def is_scout_class(self) -> bool:
        return self.code in SCOUT_CLASSES


# Ship rebalance (Dave 2026-11-19, DECISIONS G-25): the standard line D/C/B/HB/DN is "a bit
# stronger" (still below the defensive line per cost, the trade for its movement 4-5), and the
# DeathStar "much stronger" (30/8 -> 45/12); the fast line, upkeep and costs are unchanged.  The
# rules' and the C code's values were D 2/4, C 6/10, B 10/14, HB 14/16, DN 20/20, DS 30/8.
_S = [
    ("S", "Scout", 0, 1, 3, 4, 0, 20, 20, 0, STANDARD),
    ("T", "Transport", 0, 1, 1, 4, 3, 20, 20, 0, STANDARD),
    ("F", "Frigate", 1, 2, 2, 4, 0, 30, 30, 0, STANDARD),
    ("D", "Destroyer", 3, 5, 3, 4, 0, 40, 40, 15, STANDARD),
    ("C", "Cruiser", 7, 12, 4, 4, 0, 60, 60, 29, STANDARD),
    ("B", "Battleship", 12, 16, 4, 5, 0, 80, 80, 39, STANDARD),
    ("MS", "Megascout", 0, 8, 8, 8, 0, 40, 40, 41, STANDARD),
    ("MT", "MassTransit", 0, 8, 1, 8, 8, 60, 60, 40, STANDARD),
    ("DN", "Dreadnought", 24, 24, 4, 5, 0, 100, 100, 49, STANDARD),
    ("SS", "SuperScout", 0, 1, 5, 5, 0, 20, 20, 16, STANDARD),
    ("PA", "Patroller", 2, 5, 2, 2, 0, 30, 30, 6, DEFENSIVE),
    ("FF", "FastFrigate", 1, 2, 2, 5, 0, 40, 40, 8, FAST),
    ("DE", "Defender", 4, 8, 2, 2, 0, 40, 40, 9, DEFENSIVE),
    ("LC", "LightCruiser", 3, 5, 2, 6, 0, 50, 50, 18, FAST),
    ("GU", "Guardian", 7, 12, 2, 3, 0, 50, 50, 19, DEFENSIVE),
    ("MCS", "Multirole_CS", 4, 6, 3, 6, 4, 70, 70, 27, FAST),
    ("WS", "Warstation", 11, 17, 3, 3, 0, 60, 60, 28, DEFENSIVE),
    ("FC", "FastCruiser", 7, 8, 3, 7, 0, 80, 80, 37, FAST),
    ("MO", "Monitor", 16, 20, 3, 3, 0, 70, 70, 38, DEFENSIVE),
    ("AT", "ArmedTrans", 4, 6, 3, 5, 5, 70, 70, 36, STANDARD),
    ("HB", "HvyBattleshp", 16, 18, 4, 5, 0, 90, 90, 45, STANDARD),
    ("FB", "FastBttleshp", 9, 12, 3, 8, 1, 90, 90, 46, FAST),
    ("ST", "Striker", 5, 1, 2, 2, 0, 30, 30, 7, OFFENSIVE),
    ("PO", "Pounder", 8, 2, 2, 2, 0, 40, 40, 17, OFFENSIVE),
    ("MA", "Mauler", 12, 5, 2, 3, 0, 50, 50, 20, OFFENSIVE),
    ("E", "Eliminator", 18, 6, 3, 3, 0, 60, 60, 30, OFFENSIVE),
    ("DS", "DeathStar", 45, 12, 2, 3, 0, 100, 100, 47, OFFENSIVE),
    ("BB", "BigBrother", 22, 30, 2, 3, 0, 100, 100, 48, DEFENSIVE),
]

SHIP_TYPES: dict[str, ShipType] = {s[0]: ShipType(*s) for s in _S}
SCOUT_CLASSES = frozenset({"S", "SS", "MS"})
# Non-warship classes for the NWR statistic (gcrun.c:1283-1290: transports and scouts).
NONWAR_CLASSES = frozenset({"T", "MT", "S", "SS", "MS"})

assert len(SHIP_TYPES) == 28

# Display groups for ship pickers and lists (Dave 2026-11-19: "order ships by type group, then by
# tech level within the group", using the rules' own categories).  The rules name the scout class
# (Scout, SuperScout, MegaScout; rules:484-485) and the transports (Transport, and MassTransit
# from Improved Transports), which are also the non-warship classes of the NWR statistic; every
# warship belongs to one of the four ship lines of the Mixed Fleet Bonus, "STANDARD, OFFENSIVE,
# DEFENSIVE and FAST" (rules:819-821), in the rules' order.  The armed cargo ships (ArmedTrans,
# Multirole_CS) stay in their line: they are warships and count for the MFB.  Display only:
# nothing in the engine depends on it.
SHIP_GROUPS: tuple[tuple[str, str], ...] = (
    ("scout", "Scouts"), ("transport", "Transports"), (STANDARD, "Standard line"),
    (OFFENSIVE, "Offensive line"), (DEFENSIVE, "Defensive line"), (FAST, "Fast line"))
TRANSPORT_CLASSES = frozenset({"T", "MT"})


def ship_group(code: str) -> str:
    if code in SCOUT_CLASSES:
        return "scout"
    if code in TRANSPORT_CLASSES:
        return "transport"
    return SHIP_TYPES[code].line


def ship_sort_key(code: str) -> tuple:
    """Group (as SHIP_GROUPS), then the required technology's price (its tech level), then the
    ship's cost, then the tech number."""
    from .techs import TECHS
    st = SHIP_TYPES[code]
    g = [k for k, _ in SHIP_GROUPS].index(ship_group(code))
    return (g, TECHS[st.tech].cost if st.tech else 0, st.eu_cost + st.iu_cost, st.tech, code)


SHIP_ORDER: tuple[str, ...] = tuple(sorted(SHIP_TYPES, key=ship_sort_key))
