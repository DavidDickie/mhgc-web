"""The computer-run empires (NPRs).

A new bot designed from the rules (Dave 2026-11-12: "don't use the C code for the bots, or the
cheats.  Make a better playing bot.").  See STATUS-npr.md and DECISIONS A-01.

Contract
- `npr_orders(state, empire_id)` returns the orders the NPR gives this turn.  `run_turn` calls it
  at the start of the turn for every empire of kind "npr" that has no orders supplied.  The orders
  go through the same validation as a player's.
- No hidden information: the bot decides only from `mhgc.view.view(state, inbox, empire_id)` -
  the read model a human player gets - and its own memory `state.npr_state[empire_id]`.  The
  "inbox" is the empire's own last turn report, which `observe_turn(state, results)` (called by
  `run_turn` at the end of every turn) stores in that memory.
- It mutates nothing but its own memory.  Randomness: `Rng(state.seed, state.turn,
  f"npr{empire_id}")`.
- `bot_orders(view, memory, rng)` is the same bot for any seat (used by the strength harness,
  mhgc/npr/sim.py, to play bots in player seats where victory points count).
"""
from __future__ import annotations

from typing import Protocol

from ..model import NPR, GameState
from ..orders import Order
from ..rng import Rng
from ..view import view
from .brain import decide, inbox
from .memory import memory


class NprPlayer(Protocol):
    def __call__(self, state: GameState, empire_id: int) -> list[Order]: ...


def npr_view(state: GameState, empire_id: int) -> dict:
    """What the NPR sees: exactly a player's view, with its own last report."""
    mem = memory(state, empire_id)
    return view(state, mem.get("inbox"), empire_id)


def bot_orders(v: dict, mem: dict, rng: Rng) -> list[Order]:
    return decide(v, mem, rng).orders


def npr_orders(state: GameState, empire_id: int) -> list[Order]:
    e = state.empires.get(empire_id)
    if e is None or e.kind != NPR:
        return []
    mem = memory(state, empire_id)
    v = view(state, mem.get("inbox"), empire_id)
    return bot_orders(v, mem, Rng(state.seed, state.turn, f"npr{empire_id}"))


def npr_orders_traced(state: GameState, empire_id: int) -> tuple[list[Order], dict | None]:
    """`npr_orders` plus this turn's decision-log record (mhgc/npr/trace.py, DECISIONS A-05).
    The orders and the memory written are exactly those of `npr_orders`."""
    e = state.empires.get(empire_id)
    if e is None or e.kind != NPR:
        return [], None
    mem = memory(state, empire_id)
    v = view(state, mem.get("inbox"), empire_id)
    plan = decide(v, mem, Rng(state.seed, state.turn, f"npr{empire_id}"), record=True)
    rec = plan.record
    if rec is not None:
        rec["persona"] = mem["persona"]["name"]
    return plan.orders, rec


def adopt(state: GameState, empire_id: int, results: dict | None) -> dict:
    """Hand a human empire to the computer (the host's "Hand to the computer", DECISIONS W-22).

    The empire becomes an NPR with a fresh memory: the personality comes from the game seed as for
    any NPR (`memory.new_memory`), and the only thing it starts knowing is that empire's own last
    turn report (`results`, the stored results dict of the current turn), exactly what an NPR's
    `observe_turn` would have kept.  Relations, holdings and everything else are unchanged.
    Returns the new memory."""
    from .memory import new_memory
    e = state.empires[empire_id]
    e.kind = NPR
    mem = new_memory(state.seed, empire_id, state.turn)
    state.npr_state[empire_id] = mem
    got = stored_inbox(results, empire_id, state.turn)
    if got is not None:
        mem["inbox"] = got
    return mem


def stored_inbox(results: dict | None, empire_id: int, turn: int) -> dict | None:
    """The bot inbox (brain.inbox) of one empire from a stored results dict (results.json):
    that empire's own report and the battles it was in, nothing else.  None without a report."""
    from ..results import CombatLog, EmpireReport, Event, OrderResult, TurnResults
    rep = ((results or {}).get("reports") or {}).get(str(empire_id))
    if rep is None:
        return None
    er = EmpireReport(empire_id,
                      orders=[OrderResult(**o) for o in rep.get("orders", [])],
                      events=[Event(**x) for x in rep.get("events", [])],
                      combats=list(rep.get("combats", [])),
                      economy=dict(rep.get("economy") or {}),
                      scans=rep.get("scans") or {}, stats=rep.get("stats") or {},
                      messages=list(rep.get("messages") or []))
    ids = set(er.combats)
    tr = TurnResults(results.get("turn", turn), reports={empire_id: er},
                     combats=[CombatLog(**c) for c in results.get("combats", [])
                              if c.get("id") in ids])
    return inbox(tr, empire_id)


# AOMT, "Autogenerate orders on missed turn" (Dave 2026-11-19, DECISIONS W-29).  The bot stands in
# for a human race the host forces a turn on before it has submitted.  It plays as a caretaker:
# nothing that speaks for the player or changes its standing with other races, so the race stays
# recognisably the player's (no messages, renames, war, alliances, gifts, trade terms, tech trades,
# resignation).  Everything else (research, building, settling, defending, missions in progress)
# is the normal bot.
AOMT_SKIP = frozenset({"MESSAGE", "NSY", "CRN", "DA", "DW", "EWA", "GE", "GT", "TTNPR", "DD",
                       "SD", "UG", "RESIGN", "AOMT"})


def aomt_orders_traced(state: GameState, empire_id: int,
                       results: dict | None) -> tuple[list[Order], dict | None]:
    """The stand-in orders of a human race for this turn (`state.turn` is the turn being run),
    and the decision-log record (marked `aomt`).  No hidden information (A-02): the bot sees
    exactly `view(state, inbox, empire_id)`, the race's own read model, where the inbox is the
    race's own last report (`results`, the stored results of the previous turn).  Its memory is
    `state.aomt_state[empire_id]`: kept from the previous turn if that one was an AOMT turn too,
    otherwise new (personality from the seed, as any bot).  Only that memory is written."""
    from ..model import HUMAN
    from .memory import MEMORY_VERSION, new_memory
    e = state.empires.get(empire_id)
    if e is None or e.kind != HUMAN:
        return [], None
    mem = state.aomt_state.get(empire_id)
    if mem is None or mem.get("v") != MEMORY_VERSION or mem.get("aomt_last") != state.turn - 1:
        mem = new_memory(state.seed, empire_id, state.turn)
    mem["inbox"] = stored_inbox(results, empire_id, state.turn) or mem.get("inbox")
    v = view(state, mem.get("inbox"), empire_id)
    plan = decide(v, mem, Rng(state.seed, state.turn, f"aomt{empire_id}"), record=True)
    mem["aomt_last"] = state.turn
    state.aomt_state[empire_id] = mem
    keep, dropped = [], []
    for o in plan.orders:
        (dropped if o.code in AOMT_SKIP else keep).append(o)
    rec = plan.record
    if rec is not None:
        rows = [r for r in rec["orders"] if r["code"] not in AOMT_SKIP]
        for i, r in enumerate(rows):
            r["i"] = i
        rec["orders"] = rows
        rec["persona"] = mem["persona"]["name"]
        rec["aomt"] = True
        rec["aomt_dropped"] = [o.to_text()[:160] for o in dropped]
    return keep, rec


def observe_turn(state: GameState, results) -> None:
    """Keep each NPR's own report of the turn (its inbox for next turn's view), then let the
    computer empires boast about it in the game-wide chat (`results.chat`, DECISIONS W-14)."""
    for e in state.empires.values():
        if e.kind == NPR:
            memory(state, e.id)["inbox"] = inbox(results, e.id)
    from .chatter import turn_chat
    results.chat = turn_chat(state, results)


__all__ = ["npr_orders", "npr_orders_traced", "aomt_orders_traced", "stored_inbox", "AOMT_SKIP", "observe_turn", "bot_orders", "npr_view", "memory", "NprPlayer", "adopt"]
