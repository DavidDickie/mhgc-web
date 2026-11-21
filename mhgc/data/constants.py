"""Game constants and tables.  Each value cites the rule it implements, or the C source where the
rules are silent (DECISIONS.md explains every choice)."""
from __future__ import annotations

# --- Board -----------------------------------------------------------------------------------
BOARD = 100                      # rules:225 100x100, wraps both ways (the classic board)
HOME_REL = (50, 50)              # each empire sees its home at 50,50 (gcio.c:990; rules:1538)
#                                  on a smaller board the home is at its centre (geometry.home_rel)
BIN = 25                         # side of one home bin (gcugen.c)
# Game sizes (Dave 2026-11-13 and 2026-11-16, DECISIONS W-13 and W-26): empires -> (bins per side, empty bins as (bx, by)).
# The board side is BIN * bins per side.  Empty bins get their systems but no home empire.
GAME_SIZES = {
    4: (2, ()),                                        # 50x50, four quadrants (Dave 2026-11-16)
    8: (3, ((1, 1),)),                                 # 75x75, the centre bin empty
    9: (3, ()),                                        # 75x75
    12: (4, ((1, 1), (1, 2), (2, 1), (2, 2))),         # 100x100, the 4 centre bins empty
    16: (4, ()),                                       # 100x100, the classic map
}
DEFAULT_GAME_SIZE = 8            # the lobby's default (Dave 2026-11-13)
CHATTER_LEVELS = ("off", "quiet", "normal")   # computer empires' boasts in chat (W-14)

# --- Empires ---------------------------------------------------------------------------------
INDEPENDENT = 0                  # empire 0: rebels / unowned systems (gcrun.c:574, rules:236)
MAX_EMPIRES = 16                 # home positions on the generated map (gcugen.c 4x4 bins)
DEFAULT_RACE_NAMES = [
    # Names from Dave's own examples in the rules (combat example, sample report, orders).
    "Porkines", "Groachi", "Barnacle_Boys", "Grunts", "Freepeople", "Haldermen", "Boviners",
    "Badhombres", "Ravaging_Bugs", "Hopeless", "Blutos", "Mangos", "Gollywogs", "Bratwursts",
    "Googly_eyes", "Ratfinks",
]
INDEPENDENT_NAME = "Rebels"
NAME_MAX = 12                    # system/leader/fleet names (rules:1920, 2310)
RACE_NAME_MAX = 15               # "less than 16 characters" (rules:2648)

# --- System status ---------------------------------------------------------------------------
NORMAL, UNDER_ATTACK, INTERDICTED = 0, 1, 2
STATUS_NAMES = {0: "Norm", 1: "UA", 2: "INT"}

# Habitability 1..5 (rules:346)
HAB_NAMES = {1: "MH", 2: "PH", 3: "H", 4: "VH", 5: "EH"}

# Happiness bands (rules:392; gcio.c:682-687).  Rebellion at happy <= 0 (gcrun.c:568).
def happiness_band(h: float) -> str:
    if h <= 0:
        return "RB"
    if h < 0.2:
        return "UH"
    if h < 0.4:
        return "NH"
    if h < 0.6:
        return "HA"
    if h < 0.8:
        return "VH"
    return "EH"


# --- Economy ---------------------------------------------------------------------------------
PROD_PER_POP = 5.0               # rules:352
CARGO_UNITS_PER_POINT = 20       # 20 AU/IU per cargo point (rules:303,313)
INFRA_IU_COST = 10               # rules:331
DI_COST_EU = 5                   # rules:336 (5 EU) vs 2042 (5 IU); DECISIONS F-03
DSP_COST_EU = 10                 # rules:466
CSP_MIN = 10                     # rules:359
DEFAULT_CSP = (50, 25, 25)       # rules:364
DEFAULT_AU_PROFILE = 33          # rules:364 (DECISIONS F-10)
GROWTH_RATE = 1.0                # the standard 100% rate; CGR is removed (DECISIONS G-09)
POP_CAP = 10.0                   # without EUS (rules:432)
STARPORT_PROD_BONUS = 0.10       # per class (rules:452)
SS_REFUND = 0.75                 # rules:576
SCT_REFUND = 0.50                # rules:606, 2289
DCT_SHARE = 0.25                 # rules:321
DCT_CAP = 0.50                   # rules:323
DD_MIN = 25                      # rules:2473
CI_EU_PER_POINT = 10             # rules:2007

def starport_cost(rating: int) -> int:
    """IU and EU cost of a class `rating` starport (rules:447)."""
    return 0 if rating <= 0 else 25 * 2 ** (rating - 1)


# --- Leaders ---------------------------------------------------------------------------------
LEADER_MOVE_TURNS = 2            # "in transit for two turns, arrives third turn" (rules:2252)
LEADER_ICE_TURNS = 5             # rules:2273 (C: dies 5 turns later, gcrandom.c:72)
LEADER_LIMBO = 1000              # awaiting assignment marker (gcleader.c:70)

# --- Maintenance (rules:479-486, chart 3063; gcmaint.c:201-220) --------------------------------
SHIP_MAINT_AT_OWN_SYSTEM = (2, 2)    # (IU, EU) halved, rounded down from 5/5
SHIP_MAINT_NORMAL = (5, 5)
SHIP_MAINT_FAR = (10, 5)             # IU doubled beyond 4 turns from an owned system
FAR_TURNS = 4
SPY_MAINT = 5

# --- Combat ----------------------------------------------------------------------------------
BOMBARD_PTS_PER_DEF = 4              # rules:777
BOMBARD_PARTIAL_DIV = 5              # rules:779 attack/(5*def)
CAVE_CHANCE = 25                     # rules:782
RAID_PTS_PER_TARGET = 5              # rules:787
RAID_PTS_PER_POP = 25                # rules:790
RAID_IU_AU_PER_HIT = 10
STATUS_RATIO = 3.0                   # rules:924-941 (strict "more than", DECISIONS F-04)
DROP_BURN_BASE = 30                  # rules:601
DROP_BURN_PER_DEFENCE = 15           # gcparse1.c:498 (rules: "increases"; amount from C)
PD_ATTACK_REDUCTION = 1              # rules:2697
SW_ATTACK_REDUCTION = 5              # rules:2892
SYSTEM_WEAPON_ATTACK = {"SW": 1, "APD": 5}          # rules:2893, 3001
SYSTEM_WEAPON_DEFENSE = {"PD": 1, "SW": 5, "APD": 15}   # rules:2698, 2894, 3001
CAPTURE_POP_LOSS = (10, 50)          # rules:965
TECH_CAPTURE_GAP = 3                 # gcrun/gccombat message gate (rules:983 "better technology")
TECH_CAPTURE_POOL = 6                # TECHDELTA, gcutils.c:286

# Ship/system relation table (rules:492-505)
ATTACK_CHANCE = {("N", "N"): 50, ("N", "F"): 10, ("F", "N"): 10}

# --- Spies (rules:2829-2843; SOM not in the table: C 30/10) ------------------------------------
SPY_ODDS = {   # mission: (success %, capture %)
    "SMV": (100, 5), "SMO": (100, 5), "SOS": (100, 5), "SOT": (50, 10), "SOL": (50, 10),
    "SAL": (30, 30), "SSB": (20, 40), "SET": (20, 40), "SUP": (50, 10), "SVS": (25, 50),
    "SOE": (50, 10), "SON": (100, 5), "SRS": (100, 0), "SOM": (30, 10),
}
SPY_MOVE_DIVISOR = 6.0               # rules:2752

# --- Happiness, uprisings (rules:677-701; gcrun.c:516-700) ------------------------------------
UPRISING_CHANCE_UH = 50              # rules:677
UPRISING_CHANCE_NH = 10              # rules:685
UPRISING_MILITIA = 10                # "one in ten times" (rules:679)
EMPEROR_DAY_VH = 10                  # rules:687
EMPEROR_DAY_EH = 50                  # rules:690
REBEL_JOIN_CHANCE = 10               # rules:700
REBEL_GOVERNOR_KILL = 75             # rules:972
IMMIGRATION_DIVISOR = 150.0          # gcparse1.c:1080

# --- Random events (gcrandom.c; rules silent on frequencies) -----------------------------------
EVENTS_START_TURN = 10
CD_ROM_START_TURN = 6

# --- Victory (rules:197-220) -----------------------------------------------------------------
VICTORY_POINTS = 90                  # Dave 2026-11-19 (was 100): see DECISIONS G-26
VP_PER_SYSTEM = 2
VP_STAT_BONUS = {1: 2, 2: 1}
VP_STATS = ("WAR", "NWR", "STP", "POP", "HAP", "PRD", "CTS", "GWR", "TEC")
STAT_NAMES = ("GNP", "NNP", "WAR", "NWR", "STP", "POP", "HAP", "PRD", "SYS", "GWR", "TEC", "VCT",
              "CTS")

# --- NPRs: no advantages.  The rules' NPR "cheats" (rules:252-257: longer scans, more production,
# cheaper upkeep) and the C's extras (ISNPR income, PT discount, EU cap, majority tech grant, no
# rebellion) are all gone: computer empires play under exactly the human rules (Dave 2026-11-12,
# DECISIONS A-01).
