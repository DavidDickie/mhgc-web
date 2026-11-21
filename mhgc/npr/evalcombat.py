"""Battle evaluation with the engine's own combat code (engine/combat.py), run on a small
synthetic game built from the bot's ESTIMATE of the situation (its own ships and troops, and what
its scans and memory say the enemy has) - never on the true hidden state.

`assault(...)` plays N independent trials of one combat at an enemy system: our ships arriving,
our troops landed on the ground (as LACT does), against the estimated defending ships, troops,
population and system weapons, all at war.  It returns the chance that the enemy's ships are
destroyed, the chance that the system is captured, and our expected fraction of ships lost.
"""
from __future__ import annotations

from ..data import constants as K
from ..engine.combat import Combat
from ..engine.context import TurnContext
from ..model import HUMAN, Empire, GameState, Ship, System, Troop
from ..results import TurnResults
from ..rng import Rng

US, THEM = 1, 2


def _state(our_ships, our_troops, their_ships, their_troops, pop, weapons, defender) -> GameState:
    st = GameState(name="eval", seed=0, turn=1)
    st.empires[0] = Empire(0, "Rebels", kind="independent")
    st.empires[US] = Empire(US, "Us", kind=HUMAN, relations={THEM: "W"})
    st.empires[THEM] = Empire(THEM, "Them", kind=HUMAN, relations={US: "W"})
    owner = THEM if defender else 0
    if not defender:
        st.empires[US].relations = {}
    st.systems.append(System(0, "T", 0, 0, owner=owner, pop=max(0.0, pop), hab=3,
                             artifacts=set(weapons), infra=int(pop)))
    n = 1
    for typ in our_ships:
        st.ships[n] = Ship(n, US, typ, 0, 0, posture="H", role="SC" if typ not in ("T", "MT")
                           else "RD")
        n += 1
    for typ in their_ships:
        st.ships[n] = Ship(n, owner, typ, 0, 0, posture="H", role="MR")
        n += 1
    k = 1
    for typ in our_troops:
        st.troops[k] = Troop(k, US, typ, system=0, posture="A")
        k += 1
    for typ, post in their_troops:
        st.troops[k] = Troop(k, owner, typ, system=0, posture=post)
        k += 1
    return st


def assault(our_ships: list[str], our_troops: list[str], their_ships: list[str],
            their_troops: list[tuple[str, str]], pop: float, weapons: list[str],
            defender: bool = True, trials: int = 8, seed: int = 0) -> dict:
    space = capture = 0
    lost = 0.0
    for i in range(trials):
        st = _state(our_ships, our_troops, their_ships, their_troops, pop, weapons, defender)
        ctx = TurnContext(state=st, rng=Rng(seed, i, "npr-eval"), res=TurnResults(1))
        ctx.empire_order = [US, THEM] if i % 2 == 0 else [THEM, US]
        Combat(ctx, 0, 0, st.systems[0]).run()
        alive_us = sum(1 for s in st.ships.values() if s.alive and s.owner == US)
        alive_them = sum(1 for s in st.ships.values() if s.alive and s.owner != US)
        if alive_them == 0:
            space += 1
        if st.systems[0].owner == US:
            capture += 1
        if our_ships:
            lost += 1.0 - alive_us / len(our_ships)
    return {"space": space / trials, "capture": capture / trials, "lost": lost / trials,
            "trials": trials}


def fleet_vs_fleet(our_ships: list[str], their_ships: list[str], trials: int = 6,
                   seed: int = 0) -> float:
    """Chance that our ships destroy theirs in one round of space combat in open space."""
    return assault(our_ships, [], their_ships, [], 0.0, [], True, trials, seed)["space"]


__all__ = ["assault", "fleet_vs_fleet", "K"]
