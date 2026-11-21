"""Order catalogue and reference tables for the UI (static game data, safe to show anyone)."""
from __future__ import annotations

import dataclasses

from mhgc import orders as O
from mhgc.data import constants as K
from mhgc.data.artifacts import ARTIFACTS, SPY_EU_COST, SPY_IU_COST, SPY_KEY
from mhgc.data.ships import SHIP_GROUPS, SHIP_ORDER, SHIP_TYPES, ship_group
from mhgc.data.techs import TECHS, tech_vp
from mhgc.data.troops import POSTURE_NAMES, TROOP_TYPES

KINDS = {
    "int": "a whole number",
    "nat": "a whole number, 0 or more",
    "coord": "a coordinate 0-99 on the 100x100 board (0-74 on 75x75, 0-49 on 50x50), relative to "
             "your home (your home is at the board centre: 50,50, or 37,37 on 75x75, 25,25 on "
             "50x50)",
    "pct": "a percentage 0-100",
    "str": "a name (one word, no spaces)",
    "choice": "one of the listed choices",
    "ints": "1 to 10 ship numbers",
    "text": "free text",
    "speed": "A (automatic: the slowest ship) or 1-9",
    "list": "a list of race names (empty = every other race)",
}

CATEGORIES = {
    "ship": "Ships", "fleet": "Fleets", "system": "Systems", "troop": "Combat troops",
    "leader": "Leaders", "spy": "Spies", "empire": "Empire and diplomacy",
    "misc": "Messages and notes",
}

FIELD_HELP = {
    "ship": "your ship's number", "fleet": "your fleet's name", "system": "a system name",
    "race": "a race name", "x": "x coordinate (relative)", "y": "y coordinate (relative)",
    "amount": "how many", "ct": "a combat troop's number", "spy": "your spy's number",
    "leader": "your leader's name", "target": "the ship number to intercept",
    "tech": "a technology number (see reference techs)", "give": "the tech number you give",
    "want": "the tech number you want", "name": "the new name", "ships": "ship numbers",
    "to": "the destination system name", "posture": "posture", "role": "combat role",
    "item": "A = AU, I = IU, P = population (C = a combat troop for TP)",
    "artifact": "artifact key (see reference artifacts)", "type": "ship or troop type code",
    "au": "% of production to AU", "iu": "% of production to IU", "eu": "% of production to EU",
    "gc": "ground combat points (RO role)", "rd": "raid points (RO role)",
    "other": "role for the remaining points (RO role)", "speed": "fleet speed",
    "text": "text",
    "into": "the fleet that takes the ships: another of yours, at the same square",
    "count": "how many to build, 1-50 (default 1); each is built as if the order were repeated, "
             "and if one can't be built the rest stop there",
}

# where a field means something different for one order
CODE_FIELD_HELP = {
    ("TP", "amount"): "AUs or IUs to send; for C, the combat troop's number",
    ("TP", "item"): "A = AU, I = IU, C = a combat troop",
    ("SL", "ship"): "the ship to load: yours or another race's, at your system",
    ("ML", "system"): "one of your systems",
    ("WTP", "system"): "your destination system (it needs a warp tunnel too)",
    ("WTPF", "system"): "your destination system (it needs a warp tunnel too)",
    ("TTNPR", "give"): "the tech you give, or ANY: any of yours costing the amount below, picked "
                       "by the computer empire when the turn runs",
    ("TTNPR", "want"): "the tech you want, or ANY: any of theirs costing the amount below that "
                       "you lack and can use, picked by them when the turn runs",
    ("TTNPR", "give_any_cost"): "the list price of the tech you give (ANY)",
    ("TTNPR", "want_any_cost"): "the list price of the tech you want (ANY)",
    ("MGF", "fleet"): "the fleet to merge: all its ships move into the other fleet, then it is "
                      "disbanded and its name is free",
    ("AOMT", "mode"): "ON (the default): if the host forces a turn before you submit, your draft "
                      "runs as if submitted, or with an empty draft the computer writes your "
                      "orders from your own view; OFF: you give no orders that turn",
}

CHOICE_LABELS = {
    "ship_posture": {"H": "hostile", "N": "neutral", "F": "friendly"},
    "ship_role": {"SC": "space combat", "MR": "missile/raid", "GC": "ground combat",
                  "RD": "raid"},
    "ct_posture": {"A": "attack", "D": "defend", "E": "entrench"},
    "fleet_posture": {"M": "mixed (each ship's own)", "H": "hostile", "N": "neutral",
                      "F": "friendly", "AH": "all hostile", "AN": "all neutral"},
    "fleet_role": {"M": "mixed (each ship's own)", "SC": "space combat", "MR": "missile/raid",
                   "GC": "ground combat", "RD": "raid", "OF": "offensive", "DF": "defensive",
                   "PT": "protect", "RO": "role override (gc rd other)"},
    "item": {"A": "AU", "I": "IU", "P": "population", "C": "combat troop"},
    "mode": {"ON": "on", "OFF": "off"},
}


# Fuller one-line help for the spy missions (the order table only says "Spy mission");
# wording and odds from RULEBOOK "[14] Biomodification".
SPY_HELP = {
    "SOS": "Spy out system: a short range scan of the spy's system (100% success, 5% capture)",
    "SOT": "Spy out technology: the owner's technologies (50%, 10% capture)",
    "SOL": "Spy out leader: all about the system's governor (50%, 10% capture)",
    "SVS": "Spy vs. spy: which of your systems the owner has spies on (25%, 50% capture)",
    "SOE": "Spy out economics: the owner's EU, IU depot and production (50%, 10% capture)",
    "SOM": "Spy out map: a long range scan of some of the owner's systems (30%, 10% capture)",
    "SON": "Spy out numerical stats: the owner's GNP, NNP etc. (100%, 5% capture)",
    "SAL": "Assassinate the system's leader (30%, 30% capture)",
    "SSB": "Sabotage an artifact, the IU or the AU stockpile (20%, 40% capture)",
    "SUP": "Uprising: lower happiness and try to make the system revolt (50%, 10% capture)",
    "SRS": "Retire the spy (it is removed)",
    "SET": "Eliminate a race's trade route at the spy's system (20%, 40% capture)",
}


def _labels(code: str, arg: dict) -> dict:
    name, choices = arg["name"], set(arg["choices"])
    if name == "type" and choices <= set(SHIP_TYPES):
        return {c: SHIP_TYPES[c].name for c in arg["choices"]}
    if name == "type" and choices <= set(TROOP_TYPES):
        return {c: TROOP_TYPES[c].name for c in arg["choices"]}
    if name == "artifact":
        return {c: ("Spy" if c == SPY_KEY else ARTIFACTS[c].name) for c in arg["choices"]}
    if name == "item":
        return {c: CHOICE_LABELS["item"][c] for c in arg["choices"]}
    if name == "mode":
        return {c: CHOICE_LABELS["mode"].get(c, c) for c in arg["choices"]}
    if name == "posture":
        table = ("fleet_posture" if code.startswith("CF") else
                 "ct_posture" if code in ("BCU", "CCP") else "ship_posture")
        return {c: CHOICE_LABELS[table].get(c, c) for c in arg["choices"]}
    if name in ("role", "other"):
        table = "fleet_role" if code == "CFCR" and name == "role" else "ship_role"
        return {c: CHOICE_LABELS[table].get(c, c) for c in arg["choices"]}
    return {}


def order_catalogue(board: int = K.BOARD) -> dict:
    """The catalogue for a game on a `board` x `board` map (coordinate fields run 0..board-1)."""
    out = []
    c = board // 2
    for entry in O.catalogue():
        code = entry["code"]
        if code == "MESSAGE":
            entry["args"] = [
                {"name": "recipients", "kind": "list", "optional": True, "choices": [],
                 "lo": None, "hi": None},
                {"name": "text", "kind": "text", "optional": False, "choices": [], "lo": None,
                 "hi": None}]
            entry["usage"] = "MESSAGE [race ...] / text lines / ."
            entry["help"] = ("Send a message with your orders; it arrives in the recipients' "
                             "turn results.  No recipients = every other race.")
        if code in SPY_HELP:
            entry["help"] = SPY_HELP[code]
        if code == "TTNPR":          # DECISIONS C-07, G-23
            entry["help"] = ("Trade a technology with an NPR: either side can be ANY and a "
                             "cost, meaning any technology of exactly that list price, which "
                             "the computer empire picks when the turn runs (of yours, the one "
                             "it values most that it lacks; of its own, the one it values least "
                             "that you lack and can use). Example: TTNPR ANY 1000 ANY 1000 "
                             "Groachi.")
            entry["any_costs"] = O.any_costs()
        if code == "MGF":            # DECISIONS G-27
            entry["help"] = ("Merge fleets: every ship of the first fleet joins the second, then "
                             "the first is disbanded (its name is free at once). Both must be "
                             "yours and at the same square. The second fleet keeps its name, "
                             "posture, role, speed and orders, and moves this turn with its own "
                             "orders. Example: MGF Wing Main.")
        if code == "AOMT":           # DECISIONS W-29
            entry["help"] = ("Autogenerate orders on missed turn: a race setting, on or off. On, a "
                             "turn the host forces before you have submitted is played for you: "
                             "the computer writes your orders from your own view (an unsubmitted "
                             "draft is not used), and your report says so. Takes effect as soon "
                             "as the order is saved, and stays until you turn it off. Also on the "
                             "Empire tab.")
        for a in entry["args"]:
            if a["name"] == "type" and a.get("choices") and set(a["choices"]) <= set(SHIP_TYPES):
                a["choices"] = sorted(a["choices"], key=SHIP_ORDER.index)   # by group (G-22)
            if a.get("kind") == "coord":
                a["hi"] = board - 1
            a["help"] = CODE_FIELD_HELP.get((code, a["name"])) or FIELD_HELP.get(a["name"], a["name"])
            a["labels"] = _labels(code, a)
        entry["category_label"] = CATEGORIES.get(entry["category"], entry["category"])
        out.append(entry)
    kinds = dict(KINDS)
    kinds["coord"] = (f"a coordinate 0-{board - 1}, relative to your home (your home is "
                      f"{c},{c})")
    return {"orders": out, "kinds": kinds, "categories": CATEGORIES, "board": board,
            "notes": ["Orders run in the order given; a failed order changes nothing.",
                      f"Coordinates are relative to your home system, which is at {c},{c}.",
                      "Order JSON is {\"code\": ..., <arg name>: value, ...}; classic text "
                      "orders (one per line) are accepted too."]}


def reference() -> dict:
    return {
        "techs": [{**dataclasses.asdict(t), "vp": tech_vp(t.id) if t.id else 0}
                  for t in TECHS.values()],
        # in picker order: group, then tech level, then cost (DECISIONS G-22)
        "ships": [{**dataclasses.asdict(SHIP_TYPES[c]), "group": ship_group(c),
                   "group_label": dict(SHIP_GROUPS)[ship_group(c)]} for c in SHIP_ORDER],
        "ship_groups": [{"key": k, "label": lab} for k, lab in SHIP_GROUPS],
        "troops": [dataclasses.asdict(t) for t in TROOP_TYPES.values()],
        "artifacts": [dataclasses.asdict(a) for a in ARTIFACTS.values()]
        + [{"key": SPY_KEY, "name": "Spy", "tech": 0, "iu_cost": SPY_IU_COST,
            "eu_cost": SPY_EU_COST, "maint_eu": None}],
        "troop_postures": POSTURE_NAMES,
        "status_names": K.STATUS_NAMES, "hab_names": K.HAB_NAMES,
        "stat_names": list(K.STAT_NAMES), "victory_points": K.VICTORY_POINTS,
        "board": K.BOARD, "home": list(K.HOME_REL), "max_empires": K.MAX_EMPIRES,
        # game sizes (DECISIONS W-13): the board and home of a game are in its view's `game`
        "game_sizes": [{"size": n, "bins": side, "board": side * K.BIN,
                        "home": [side * K.BIN // 2] * 2, "empty_bins": [list(b) for b in emp]}
                       for n, (side, emp) in sorted(K.GAME_SIZES.items())],
        "default_game_size": K.DEFAULT_GAME_SIZE, "chatter_levels": list(K.CHATTER_LEVELS),
    }
