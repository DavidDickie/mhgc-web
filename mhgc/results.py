"""Structured turn results.

The old engine wrote text reports (player%d.out).  Here each turn produces a `TurnResults` with a
per-empire `EmpireReport` that a UI renders: per-order outcomes, typed events (with the original
flavour text), combat logs, scans, economy/maintenance ledgers and stats.  Everything is plain data
and JSON serialisable via `to_dict()`.

Event `kind`s are stable identifiers the UI can switch on (see EVENT_KINDS); `text` is a ready-made
human sentence (Dave's report wording where there was one); `data` carries the numbers.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Optional

# Report sections, in the order of the old text report (gcio.c/gcrun.c, ENGINE_MAP 4.8).
SECTIONS = ("orders", "messages", "rebellion", "maintenance", "drops", "combat", "spies",
            "random", "leaders", "scans", "general")

EVENT_KINDS = {
    # orders phase
    "tech_purchased", "tech_gifted", "tech_received", "eu_gift", "eu_received", "system_captured",
    "colonized", "immigration_protest", "trade_route", "message",
    # happiness
    "rebellion", "uprising", "uprising_militia", "emperor_day", "charismatic_leader",
    # maintenance
    "artifact_lost", "ship_demobilized", "troop_demobilized", "spy_lost", "militia_disbanded",
    "pop_capped",
    # movement / drops
    "drop_burned", "drop_landed", "leader_arrived", "leader_evicted", "fleet_link_broken",
    # end-of-turn fleet cleanup (G-18)
    "fleet_disbanded", "fleet_empty",
    # combat
    "combat", "status_change", "system_lost", "system_rebels_to", "tech_captured",
    "leader_killed", "leader_defected",
    # spies
    "spy_report", "spy_caught", "spy_failed", "spy_detected", "assassination", "sabotage",
    "trade_route_ended",
    # random events
    "plague", "iu_gain", "au_loss", "iu_loss", "infra_loss", "pop_boom", "cd_rom",
    "leader_found", "leader_comment", "leader_died", "leader_improved",
    # end of turn
    "contact", "extinction", "victory", "info",
    # orders written by the computer for a missed turn (AOMT, W-29)
    "aomt",
}


@dataclass
class Event:
    kind: str
    text: str
    section: str = "general"
    system: Optional[int] = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class OrderResult:
    index: int
    text: str                       # the order as text (classic code)
    code: str
    ok: bool = True
    messages: list[str] = field(default_factory=list)   # info lines ("PURCHASED TECH" ...)
    error: Optional[str] = None
    built: Optional[int] = None     # BS / BCU: how many units were built (DECISIONS G-19)


@dataclass
class CombatLog:
    id: int
    x: int
    y: int
    system: Optional[int]
    participants: list[int] = field(default_factory=list)
    relations: dict[str, str] = field(default_factory=dict)   # "a,b" -> attack kind
    ships: list[dict] = field(default_factory=list)            # initial listing
    troops: list[dict] = field(default_factory=list)
    # ground forces per side, before -> after the battle: [{"owner", "before": {type: n},
    # "after": {type: n}}] for every participant with troops on the ground (Dave 2026-11-16)
    ground: list[dict] = field(default_factory=list)
    lines: list[dict] = field(default_factory=list)            # {"phase", "text", ...}
    status_before: Optional[int] = None
    status_after: Optional[int] = None
    owner_before: Optional[int] = None
    owner_after: Optional[int] = None


@dataclass
class EmpireReport:
    empire: int
    orders: list[OrderResult] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    combats: list[int] = field(default_factory=list)          # ids into TurnResults.combats
    maintenance: list[dict] = field(default_factory=list)     # ledger lines
    economy: dict[str, Any] = field(default_factory=dict)
    scans: dict[str, Any] = field(default_factory=dict)       # ships/fleets/systems seen
    stats: dict[str, Any] = field(default_factory=dict)
    messages: list[dict] = field(default_factory=list)        # MESSAGE orders received


@dataclass
class TurnResults:
    turn: int
    reports: dict[int, EmpireReport] = field(default_factory=dict)
    combats: list[CombatLog] = field(default_factory=list)
    winner: Optional[int] = None
    general: list[Event] = field(default_factory=list)
    # computer empires' boasts for the game-wide chat: [{"from", "kind", "text"}] (W-14)
    chat: list[dict] = field(default_factory=list)

    def report(self, empire: int) -> EmpireReport:
        r = self.reports.get(empire)
        if r is None:
            r = self.reports[empire] = EmpireReport(empire)
        return r

    def emit(self, empires, kind: str, text: str, section: str = "general",
             system: Optional[int] = None, **data) -> Event:
        """Add the same event to several empires' reports (duplicates removed)."""
        ev = Event(kind, text, section, system, data)
        if isinstance(empires, int):
            empires = (empires,)
        for e in dict.fromkeys(empires):
            if e is not None and e >= 0:
                self.report(e).events.append(ev)
        return ev

    def events_of(self, empire: int, kind: Optional[str] = None) -> list[Event]:
        evs = self.report(empire).events
        return [e for e in evs if kind is None or e.kind == kind]

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)
