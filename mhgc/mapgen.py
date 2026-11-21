"""New-game generation: the wrap-around board of home bins.

Game sizes (Dave 2026-11-13 and 2026-11-16, DECISIONS W-13 and W-26; `constants.GAME_SIZES`):

    empires  bins  board    empty bins (no home empire, but their normal share of systems)
       4     2x2   50x50    none (four quadrants)
       8     3x3   75x75    the centre bin
       9     3x3   75x75    none
      12     4x4   100x100  the 4 centre bins
      16     4x4   100x100  none (the classic map, generated exactly as before)

Every bin is 25x25 and holds 11 systems: 44 systems at 2x2, 99 at 3x3 and 176 at 4x4.  An empty bin
has an unowned, very habitable metal- and agriculture-rich world at its heart where a home would
be, and the same ten kinds of system around it: open territory to fight over.

Follows the intent of Dave's generator gcugen.c (4x4 bins of 25x25 squares, 11 systems per bin:
a home system plus ten nearby systems of set kinds), with its bugs fixed (DECISIONS M-01..M-08):
- coordinates wrap onto the board (the C placed systems off-board, ENGINE_MAP 10.9);
- no two systems share a square and none is adjacent to a home system;
- the "between" systems (k = 7..10) no longer read the previous bin's systems (UB for bin 0);
- the switch fall-through for k = 7..10 is fixed (each kind keeps its own habitability);
- the artifact system gets a real artifact (C gave an invisible, maintenance-free EUS or a no-op CM);
- the race-number habitability handicap (which used the *next* bin's race) is removed: every
  empire gets the same mix of systems.

Seats not taken by humans are NPRs.
"""
from __future__ import annotations

from typing import Optional, Sequence

from . import geometry as G
from .data import constants as K
from .model import (Empire, GameState, HUMAN, INDEPENDENT, Leader, NPR, Ship, System)
from .rng import Rng

BIN = K.BIN
SYSTEMS_PER_BIN = 11
# Homes sit within 5 squares of their bin centre (one per bin), so two homes are always at least
# BIN - 10 = 15 squares apart on every axis that separates them, at every size; on a 2x2 torus
# every bin touches every other, so 15 is also the nearest a neighbour can be (W-26).  The check
# below is that guarantee made explicit: farther than twice a home's starting scan (4, rules:343)
# so no empire starts inside another's scan range, nor do two starting scans touch.  It never
# rejects a draw (15 > 8), so every size generates exactly as before.
MIN_HOME_DISTANCE = 2 * 4 + 1

# kind index -> (hab, MR, AR, anchor (kind index or 'bin'), min distance, max distance)
_KINDS = {
    1: (4, False, False, 0, 1, 4),     # close-to-home habitable system (C: hab 3-5 by race no.)
    2: (4, True, False, 0, 4, 8),      # standard MR
    3: (4, False, True, 0, 4, 8),      # standard AR
    4: (4, True, True, 0, 4, 8),       # standard 2R
    5: (3, False, False, 0, 8, 10),    # the "artifact" system
    6: (4, False, False, 5, 1, 4),     # close to the artifact system
    7: (3, True, False, "bin", 0, 0),  # the rest: anywhere in the bin
    8: (2, False, True, "bin", 0, 0),
    9: (1, False, False, "bin", 0, 0),
    10: (1, False, False, "bin", 0, 0),
}
ARTIFACT_CHOICES = ("ESS", "EUS", "CB", "CM", "PD")


def _name(rng: Rng, used: set[str]) -> str:
    while True:
        n = chr(ord("A") + rng.below(26)) + "".join(str(1 + rng.below(9)) for _ in range(3))
        if n not in used:
            used.add(n)
            return n


def _free(x: int, y: int, occupied: dict, homes: list, board: int) -> bool:
    if (x, y) in occupied:
        return False
    return all(G.distance(x, y, hx, hy, board) > 1 for hx, hy in homes)


def _point_near(rng: Rng, ax: int, ay: int, lo: int, hi: int, occupied, homes, board: int):
    for _ in range(500):
        dx = rng.between(lo, hi) * (1 if rng.below(2) else -1)
        dy = rng.between(0, hi) * (1 if rng.below(2) else -1)
        if rng.below(2):
            dx, dy = dy, dx
        x, y = G.wrap(ax + dx, board), G.wrap(ay + dy, board)
        if G.distance(ax, ay, x, y, board) >= max(lo, 1) and _free(x, y, occupied, homes, board):
            return x, y
    raise RuntimeError("could not place a system")


def _point_in_bin(rng: Rng, bx: int, by: int, occupied, homes, board: int):
    for _ in range(500):
        x, y = bx * BIN + rng.below(BIN), by * BIN + rng.below(BIN)
        if _free(x, y, occupied, homes, board):
            return x, y
    raise RuntimeError("could not place a system")


def bin_centre(b: int, side: int) -> tuple[int, int]:
    return (b // side) * BIN + 12, (b % side) * BIN + 12


def _spread_bins(rng: Rng, n_humans: int, bins: list[int], side: int) -> list[int]:
    """Bins for human players, spread out (greedy max-min torus distance from a random start)."""
    board = side * BIN
    centres = {b: bin_centre(b, side) for b in bins}
    if n_humans <= 0:
        return []
    chosen = [bins[rng.below(len(bins))]]
    while len(chosen) < n_humans:
        best = max((b for b in bins if b not in chosen),
                   key=lambda b: (min(G.distance(*centres[b], *centres[c], board)
                                      for c in chosen), rng.random()))
        chosen.append(best)
    return chosen


def new_game(name: str, seed: int, humans: Sequence[str] = (), npr_names: Optional[Sequence[str]]
             = None, size: int = 16) -> GameState:
    """Create a new game of `size` empires (4, 8, 9, 12 or 16; constants.GAME_SIZES).  `humans` are
    the race names of the human seats (1..size); computer empires (NPRs) fill the rest."""
    if size not in K.GAME_SIZES:
        raise ValueError(f"a game has {', '.join(map(str, sorted(K.GAME_SIZES)))} empires")
    if len(humans) > size:
        raise ValueError(f"at most {size} empires")
    side, empty = K.GAME_SIZES[size]
    board = side * BIN
    rng = Rng(seed, 0, "mapgen")
    st = GameState(name=name, seed=seed, turn=0, board=board, bins=side,
                   empty_bins=[list(b) for b in empty])
    st.empires[0] = Empire(0, K.INDEPENDENT_NAME, kind=INDEPENDENT, eu=0, iu_depot=0)

    # Empire slots 1..size; humans take the first slots, NPRs the rest.
    pool = [n for n in (npr_names or K.DEFAULT_RACE_NAMES) if n not in humans]
    names = list(humans) + pool[: size - len(humans)]
    while len(names) < size:
        names.append(f"Race_{len(names) + 1}")
    for i, nm in enumerate(names, start=1):
        st.empires[i] = Empire(i, nm, kind=HUMAN if i <= len(humans) else NPR)

    empty_ids = {bx * side + by for bx, by in empty}
    home_bins = [b for b in range(side * side) if b not in empty_ids]
    human_bins = _spread_bins(rng, len(humans), home_bins, side)
    other_bins = [b for b in home_bins if b not in human_bins]
    rng.shuffle(other_bins)
    bin_of = {}
    for i in range(1, size + 1):
        bin_of[i] = human_bins[i - 1] if i <= len(humans) else other_bins.pop()

    used_names: set[str] = set()
    occupied: dict = {}
    # Place all home systems first so satellites keep clear of every home.
    homes = {}
    for emp, b in bin_of.items():
        bx, by = b // side, b % side
        while True:
            hx = bx * BIN + 12 + rng.below(6) * (1 if rng.below(2) else -1)
            hy = by * BIN + 12 + rng.below(6) * (1 if rng.below(2) else -1)
            if all(G.distance(hx, hy, x, y, board) >= MIN_HOME_DISTANCE
                   for x, y in homes.values()):
                break
        homes[emp] = (hx, hy)
    home_list = list(homes.values())

    # Home bins in bin order (as the classic generator), then the empty bins: emp None = no home.
    # An empty bin's heart sits where a home would, near the bin centre.
    plan: list[tuple[Optional[int], int, tuple[int, int]]] = [
        (emp, bin_of[emp], homes[emp]) for emp in sorted(bin_of, key=lambda e: bin_of[e])]
    for b in sorted(empty_ids):
        bx, by = b // side, b % side
        while True:
            cx = bx * BIN + 12 + rng.below(6) * (1 if rng.below(2) else -1)
            cy = by * BIN + 12 + rng.below(6) * (1 if rng.below(2) else -1)
            if (cx, cy) not in occupied and _free(cx, cy, {}, home_list, board):
                break
        occupied[(cx, cy)] = -1                  # reserved; replaced by its id below
        plan.append((None, b, (cx, cy)))

    for emp, b, (hx, hy) in plan:
        bx, by = b // side, b % side
        placed: dict[int, tuple[int, int]] = {}
        for k in range(SYSTEMS_PER_BIN):
            sid = len(st.systems)
            if k == 0:
                if emp is not None:
                    s = System(sid, _name(rng, used_names), hx, hy, owner=emp, pop=10.0,
                               happy=0.5, hab=5, mr=True, ar=True, infra=10, au=60, iu=75,
                               starport=1)
                else:                            # the heart of an empty bin: a prize world
                    s = System(sid, _name(rng, used_names), hx, hy, owner=0, hab=4, mr=True,
                               ar=True)
                occupied[(hx, hy)] = sid
                placed[0] = (hx, hy)
                st.systems.append(s)
                continue
            hab, mr, ar, anchor, lo, hi = _KINDS[k]
            others = [h for h in home_list if h != (hx, hy)]
            if anchor == "bin":
                x, y = _point_in_bin(rng, bx, by, occupied, home_list, board)
            else:
                ax, ay = placed[anchor]
                x, y = _point_near(rng, ax, ay, lo, hi, occupied, others + [(hx, hy)]
                                   if anchor != 0 else others, board)
            if k in (9, 10):
                mr = rng.below(100) < 20
                ar = rng.below(100) < 20
            s = System(sid, _name(rng, used_names), x, y, owner=0, hab=hab, mr=mr, ar=ar)
            if k == 5:
                s.artifacts.add(ARTIFACT_CHOICES[rng.below(len(ARTIFACT_CHOICES))])
            occupied[(x, y)] = sid
            placed[k] = (x, y)
            st.systems.append(s)

    # Empires: home, emperor, a scout and a transport (gcugen.c:384-430).
    used_numbers: set[int] = set()
    for emp, (hx, hy) in homes.items():
        e = st.empires[emp]
        e.home_x, e.home_y = hx, hy
        e.eu, e.iu_depot = 100, 50
        home = st.system_at(hx, hy)
        lid = st.next_leader_id
        st.next_leader_id += 1
        st.leaders[lid] = Leader(lid, f"Emperor_{emp}", emp, mgmt=90, eng=90, combat=90,
                                 intel=90, social=90, status="posted", system=home.id)
        for stype in ("S", "T"):
            num = rng.new_number(used_numbers, 10000)
            used_numbers.add(num)
            st.ships[num] = Ship(num, emp, stype, hx, hy, dx=hx, dy=hy, posture="N", role="SC",
                                 home=home.id, ox=hx, oy=hy)
        e.seen_systems[home.id] = {"turn": 0, "name": home.name, "owner": emp}
    return st
