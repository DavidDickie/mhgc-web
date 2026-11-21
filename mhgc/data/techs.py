"""Technologies (52 entries: 0 = basic spaceflight .. 51 = Future Technology).

Source of truth: the rules' "TECHS GROUPED BY COST" table (rules:3167-3233), which the rules
themselves call the more current list (rules:2675, 3052).  That table is an exact dump of the
compiled C table (gc_vars.h:78-132, the `_VER4` table), so prose/chart differences are resolved in
its favour.  See docs/DECISIONS.md F-01.

Technology ids are the player-visible numbers used by the PT order (rules:271-274).  The C engine
used a different internal index; we do not.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Tech:
    id: int
    name: str
    cost: int                    # EU purchase price
    prereqs: tuple[int, ...]     # tech ids that must be owned first
    tier: int                    # the cost band (100..4000), used for victory points
    unlocks: str = ""            # short description for the UI
    artifact: Optional[str] = None   # BT keyword, if the tech unlocks an artifact


FUTURE_TECH = 51
BASIC_SPACEFLIGHT = 0

_T = [
    # id, name, cost, prereqs, unlocks, artifact
    (0, "Basic Spaceflight", 0, (), "Scout, Transport, Frigate, Militia, Shock Troops", None),
    (1, "Powered Armor", 100, (), "Jump Troops (BCU J)", None),
    (2, "Extended Home Computing", 100, (), "EHC artifact: happiness", "EHC"),
    (3, "Bioengineered Foods", 100, (), "BF artifact: AU production x1.5", "BF"),
    (4, "Cybernetic Tanks", 100, (), "Cybertank battalion (BCU C)", None),
    (5, "Planetary Defenses", 100, (), "PD artifact (see rules)", "PD"),
    (6, "Missile Technology", 100, (), "Patroller (BS PA)", None),
    (7, "Solar Concentrators", 100, (), "Striker (BS ST)", None),
    (8, "Improved Engines I", 250, (1,), "Fast Frigate (BS FF)", None),
    (9, "Advanced Missile Tech", 250, (6,), "Defender (BS DE)", None),
    (10, "Networked Cyber Tanks", 250, (4,), "Networked Cybertank (BCU N)", None),
    (11, "Cybernetic Banking", 250, (2,), "CB artifact: EU production x1.5", "CB"),
    (12, "Extended Use of System", 250, (5,), "EUS artifact: population above 10", "EUS"),
    (13, "Extended Powered Armor", 250, (1,), "Defensive Jump Troops (BCU D)", None),
    (14, "Biomodification", 250, (3,), "Spies (BT S)", "S"),
    (15, "Improved Weapons I", 250, (4,), "Destroyer (BS D)", None),
    (16, "Improved Electronics I", 250, (2,), "SuperScout (BS SS)", None),
    (17, "Solar Collectors", 250, (7,), "Pounder (BS PO)", None),
    (18, "High Energy Physics", 500, (8,), "Light Cruiser (BS LC)", None),
    (19, "Neutrino Emission Seeker", 500, (9, 4), "Guardian (BS GU)", None),
    (20, "Improved Solar Collectors I", 500, (17, 13), "Mauler (BS MA)", None),
    (21, "Decentralized Trading", 500, (11,), "Trade routes (CTT)", None),
    (22, "Plasma Weapons", 500, (10,), "Plasma Cybertank (BCU P)", None),
    (23, "Cyberspace", 500, (11,), "CS artifact: happiness", "CS"),
    (24, "Spacewarp Weapons", 500, (12,), "SW artifact (see rules)", "SW"),
    (25, "Improved Electronics II", 500, (15,), "ESS artifact: system scan 6", "ESS"),
    (26, "Advanced DNA Manipulation", 500, (14,), "Halves plague effects", None),
    (27, "Systems Integration", 1000, (18, 10), "Multirole Combat Ship (BS MCS)", None),
    (28, "High Res Neutrino Scanners", 1000, (19,), "WarStation (BS WS)", None),
    (29, "Improved Weapons II", 1000, (25,), "Cruiser (BS C)", None),
    (30, "Improved Solar Collectors II", 1000, (20,), "Eliminator (BS E)", None),
    (31, "Virtual Reality Banking", 1000, (21, 23), "VRB artifact: EU production x1.5", "VRB"),
    (32, "Farcaster Portal", 1000, (24,), "FP artifact: teleport cargo (TP)", "FP"),
    (33, "Core Mining", 1000, (24,), "CM artifact: IU production x1.5", "CM"),
    (34, "Artificial Food", 1000, (26,), "AF artifact: AU production x1.5", "AF"),
    (35, "Ogre", 1000, (13, 22), "Ogre (BCU O)", None),
    (36, "Plastisteel Construction", 1000, (25,), "Armed Transport (BS AT)", None),
    (37, "Matter-Antimatter Engines", 2000, (27,), "Fast Cruiser (BS FC)", None),
    (38, "Integrated Systems Defense", 2000, (28,), "Monitor (BS MO)", None),
    (39, "Photon Torpedoes", 2000, (29, 35), "Battleship (BS B)", None),
    (40, "Improved Transports", 2000, (27,), "Mass Transit (BS MT)", None),
    (41, "Tachyon Emission Sensors", 2000, (32, 25), "Megascout (BS MS)", None),
    (42, "Improved Electronics III", 2000, (25,), "EESS artifact: system scan 10", "EESS"),
    (43, "Alchemy", 3000, (33,), "AL artifact: IU production x1.5", "AL"),
    (44, "Advanced Planetary Defenses", 3000, (32, 41), "APD artifact (see rules)", "APD"),
    (45, "Improved Weapons III", 3000, (39,), "Heavy Battleship (BS HB)", None),
    (46, "Graviton Engines", 3000, (37, 40), "Fast Battleship (BS FB)", None),
    (47, "Improved Solar Collectors III", 3000, (30,), "DeathStar (BS DS)", None),
    (48, "Matter/Antimatter Warhead", 3000, (38,), "Big Brother (BS BB)", None),
    (49, "Dreadnoughts", 4000, (45,), "Dreadnought (BS DN)", None),
    (50, "Warp Tunnel", 2000, (43, 44), "WT artifact: warp ships (WTP)", "WT"),
    # 42 and 50 repriced to 2000 (Dave 2026-11-19, DECISIONS G-24; were 3000 and 4000).  Warp
    # Tunnel is so a 2000 tech with 3000-cost prerequisites; nothing assumes prerequisites are cheaper.
    # Future Tech: cost 8000 from the rules chart (rules:3164); prerequisites from the C table
    # (gc_vars.h, IW-III + Warp Tunnel).  Repeatable.  DECISIONS F-02.
    (51, "Future Technology", 8000, (45, 50), "4 victory points each; repeatable", None),
]

TECHS: dict[int, Tech] = {
    i: Tech(i, n, c, p, (c if i != FUTURE_TECH else 4000), u, a) for (i, n, c, p, u, a) in _T
}

assert len(TECHS) == 52


def tech_vp(tech_id: int) -> int:
    """Victory points for owning a technology (rules:212-216)."""
    if tech_id == FUTURE_TECH:
        return 4
    cost = TECHS[tech_id].cost
    if cost in (500, 1000):
        return 1
    if cost in (2000, 3000):
        return 2
    if cost == 4000:
        return 3
    return 0


def all_prereqs(tech_id: int) -> set[int]:
    """Transitive prerequisites of a tech (the C re-validated chains recursively, gcutils.c:636)."""
    out: set[int] = set()
    stack = list(TECHS[tech_id].prereqs)
    while stack:
        t = stack.pop()
        if t not in out and t != BASIC_SPACEFLIGHT:
            out.add(t)
            stack.extend(TECHS[t].prereqs)
    return out


def missing_prereqs(owned: set[int], tech_id: int) -> list[int]:
    """Prerequisites (direct and transitive, as the C recursion checked) missing from `owned`."""
    return sorted(p for p in all_prereqs(tech_id) if p not in owned)
