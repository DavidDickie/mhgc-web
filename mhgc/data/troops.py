"""Combat troop types (BCU order).

Attack/defence and costs from the rules' generated tech table (rules:3173-3213, = C CT_char,
gc_vars.h:281-290).  Maintenance: 2 EU for militia and infantry, 5 EU otherwise (gcmaint.c:277-285;
rules:612,616 prose; chart rules:3096-3103).  DECISIONS F-01, F-08.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TroopType:
    code: str
    name: str
    attack: int
    defense: int
    iu_cost: int
    eu_cost: int
    tech: int
    infantry: bool
    maint_eu: int
    transportable: bool = True


_C = [
    ("M", "Militia", 1, 1, 5, 5, 0, False, 2, False),
    ("S", "Shock", 2, 2, 10, 10, 0, True, 2, True),
    ("J", "Jump", 3, 3, 20, 20, 1, True, 2, True),
    ("D", "DefJump", 3, 5, 30, 30, 13, True, 2, True),
    ("C", "Cybertank", 5, 3, 30, 30, 4, False, 5, True),
    ("N", "NetCybertank", 6, 4, 40, 40, 10, False, 5, True),
    ("P", "PlasCyber", 10, 8, 50, 50, 22, False, 5, True),
    ("O", "Ogre", 15, 20, 60, 60, 35, False, 5, True),
]

TROOP_TYPES: dict[str, TroopType] = {c[0]: TroopType(*c) for c in _C}

# Postures.  'E' = entrenched (dug in); 'E3'/'E2'/'E1' = entrenching, turns remaining.
ATTACK, DEFEND, ENTRENCHED = "A", "D", "E"
ENTRENCHING = ("E3", "E2", "E1")
POSTURES = (ATTACK, DEFEND, ENTRENCHED) + ENTRENCHING
POSTURE_NAMES = {
    "A": "attack", "D": "defend", "E": "dug in",
    "E3": "digging in [1st turn]", "E2": "digging in [2nd turn]", "E1": "digging in [last turn]",
}
