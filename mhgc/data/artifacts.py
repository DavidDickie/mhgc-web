"""Technological artifacts (BT/DT orders).

Costs and maintenance from the rules' generated table (rules:3176-3231) = C tech[] (_VER4),
except the static repricing of 2026-11-19 (Dave; DECISIONS G-24): CB, VRB, BF, AF, CM, AL, EHC,
CS dearer (CS upkeep 4), FP and WT cheaper.  Built artifacts are kept; new prices apply to new
builds and upkeep is charged at the current rate.
`scan` gives the system scan range the artifact provides (rules:343, 2901-2903, 2986-2989).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Artifact:
    key: str
    name: str
    tech: int
    iu_cost: int
    eu_cost: int
    maint_eu: int

    @property
    def total_cost(self) -> int:
        return self.iu_cost + self.eu_cost


_A = [
    ("EHC", "Extended Home Computing", 2, 75, 0, 2),
    ("BF", "Bioengineered Foods", 3, 100, 0, 0),
    ("PD", "Planetary Defenses", 5, 25, 25, 3),
    ("CB", "Cybernetic Banking", 11, 100, 100, 0),
    ("EUS", "Extended Use of System", 12, 100, 0, 3),
    ("CS", "Cyberspace", 23, 100, 100, 4),
    ("SW", "Spacewarp Weapons", 24, 50, 50, 5),
    ("ESS", "Extended System Scans", 25, 30, 30, 2),
    ("EESS", "Extremely Extended System Scans", 42, 30, 30, 2),
    ("AF", "Artificial Food", 34, 75, 75, 3),
    ("VRB", "Virtual Reality Banking", 31, 150, 150, 0),
    ("FP", "Farcaster Portal", 32, 50, 50, 0),
    ("CM", "Core Mining", 33, 150, 150, 0),
    ("AL", "Alchemy", 43, 150, 150, 0),
    ("APD", "Advanced Planetary Defenses", 44, 100, 100, 5),
    ("WT", "Warp Tunnel", 50, 75, 75, 0),
]

ARTIFACTS: dict[str, Artifact] = {a[0]: Artifact(*a) for a in _A}
# Maintenance is charged in this fixed order (gcmaint.c:118-156).
MAINT_ORDER = ("EHC", "BF", "PD", "CB", "EUS", "CS", "SW", "ESS", "EESS", "AF", "VRB", "FP",
               "CM", "AL", "APD", "WT")
# Display order on a system line (gcio.c:740-768).
DISPLAY_ORDER = ("EHC", "BF", "PD", "CB", "CS", "AF", "SW", "EUS", "ESS", "EESS", "VRB", "FP",
                 "CM", "AL", "APD", "WT")

# The spy "artifact" (BT S, Biomodification) is not a system artifact: it creates a spy.
SPY_KEY = "S"
SPY_IU_COST = 20
SPY_EU_COST = 20
SPY_MAINT_EU = 5
