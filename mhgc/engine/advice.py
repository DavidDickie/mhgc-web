"""Check-orders advice (Dave 2026-11-18, DECISIONS G-20): non-blocking warnings about a draft that
is valid order by order but probably doesn't do what the player means.

  warp_cargo     a load, unload, troop load or landing that runs after a warp jump (WTP, WTPF)
                 of the same unit earlier in the draft: the jump is immediate, so the cargo order
                 acts at the far end; comes with a Fix that moves it before the warp when that
                 works.  (If the cargo order fails there, the error itself says so: cargo_error.)
  move_cargo     an unload or landing at the square where the draft loaded that cargo onto the
                 same unit, for a unit that moves this turn: the cargo goes straight back ashore
                 before the unit leaves (orders run before movement).
  rename         an order names a system or leader by a name that an earlier rename in the draft
                 has changed (it should use the new name), or by the new name before the rename
                 has run (it should use the old one); comes with a one-click fix.
  rename_shift   a name that an earlier rename freed now belongs to another system, so the order
                 means that one (no fix: either reading is possible).
  rename_clash   two renames collide: the same new name twice, or a second rename of a leader or
                 of the race (each can be renamed only once).
  build_partial  a BS / BCU with a count built fewer units than asked (DECISIONS G-19).
  merged_fleet   an order names a fleet that an earlier MGF in the draft merged away (the order
                 fails); comes with a fix that names the fleet it was merged into (G-27).
  merged_move    a move, intercept or speed order for a fleet that a later MGF merges away:
                 it no longer applies, the merged fleet follows the other fleet's orders.

An ordinary load before a move is NOT warned about: MO, MS, MF, MFS, I, FIS and G only set a
destination, so the load runs where the unit is, which is normal play.  A cargo order that
fails because of where the unit is (deep space, or a system that isn't yours) gets a better error
from `cargo_error`, at turn run too: where the unit is, where it is going and when it arrives,
or which warp moved it.

The tracer follows `turn.check_orders`' dry run order by order, so every warning is about what
the engine really does with this draft (renames take effect at once, warp jumps move a unit
immediately, a failed order changes nothing).  Names and places come only from the empire's own
systems and its map memory, as on its own map.
"""
from __future__ import annotations

from typing import Optional

from .. import geometry as G
from ..model import GUARD, INTERCEPT, MOVE, MOVE_TO_SYSTEM
from .context import WhereError

SHIP_CARGO = {"L", "U", "UG", "SL", "LOCT", "LACT"}
FLEET_CARGO = {"FL", "FU", "FUG", "FLOCT", "FLACT"}
# code -> (what the unit does, the verb for doing it elsewhere, the order's name)
CARGO_WORDS = {
    "L": ("loads", "load", "load"), "FL": ("loads", "load", "load"),
    "U": ("unloads", "unload", "unload"), "FU": ("unloads", "unload", "unload"),
    "UG": ("unloads its gift", "unload", "gift unload"),
    "FUG": ("unloads its gift", "unload", "gift unload"),
    "SL": ("is loaded", "load", "load"),
    "LOCT": ("loads combat troop {ct}", "load the troop", "troop load"),
    "FLOCT": ("loads combat troop {ct}", "load the troop", "troop load"),
    "LACT": ("lands combat troop {ct}", "land the troop", "landing"),
    "FLACT": ("lands combat troop {ct}", "land the troop", "landing"),
}
LOADS = {"L", "SL", "FL", "LOCT", "FLOCT"}
UNLOADS = {"U", "UG", "FU", "FUG", "LACT", "FLACT"}
OWN_ONLY = {"L", "SL", "FL", "LOCT", "FLOCT"}        # load only at your own systems
ANY_SYSTEM = {"UG", "FUG", "LACT", "FLACT"}           # work at any system
# orders that name one of your systems or leaders, and the fields that hold the name
SYSTEM_FIELDS = {c: ("system",) for c in (
    "MS", "WTP", "MFS", "WTPF", "NSY", "CSP", "CAP", "CAPN", "SISD", "CI", "BCU", "BS", "BI", "DI",
    "BT", "DT", "BSP", "DSP", "SR", "SSI", "ML", "SMV")}
SYSTEM_FIELDS["TP"] = ("system", "to")
LEADER_FIELDS = {c: ("leader",) for c in ("CLN", "ML", "MLF", "PLOI")}
RENAMES = {"NSY": "system", "CLN": "leader", "CRN": "race"}
# orders that name one of your fleets (MGF names two), and the fleet move orders (G-27)
FLEET_FIELDS = {c: ("fleet",) for c in (
    "AFXY", "AF", "LF", "MF", "MFS", "FIS", "DF", "FR", "FS", "CFP", "CFCR", "FL", "FU", "FUG",
    "FLOCT", "FLACT", "WTPF", "MLF")}
FLEET_FIELDS["MGF"] = ("fleet", "into")
FLEET_MOVES = {"MF": "move", "MFS": "move", "FIS": "intercept", "FS": "speed"}


def _advice(index: int, kind: str, text: str, fix: Optional[dict] = None) -> dict:
    return {"index": index, "kind": kind, "level": "warning", "text": text, "fix": fix}


def place_name(st, eid: int, x: int, y: int) -> str:
    """A square as the empire knows it: its own system's name, the name in its map memory, else
    its relative coordinates (world.js placeName on the server)."""
    e = st.empires[eid]
    s = st.system_at(x, y)
    if s is not None:
        if s.owner == eid:
            return s.name
        info = e.seen_systems.get(s.id)
        if info and info.get("name"):
            return info["name"]
    rx, ry = G.to_rel(x, y, e.home_x, e.home_y, st.board)
    return f"{rx},{ry}"


class Tracer:
    def __init__(self, st, eid: int, ctx=None, state0=None, orders=None):
        self.st, self.eid = st, eid
        self.ctx = ctx                   # the dry run's TurnContext (warps, where_fail)
        self.state0, self.orders = state0, orders    # the untouched state and draft (for Fixes)
        self.cargo: list = []            # (index, order, "ship"|"fleet", number, x, y)
        self.loaded: dict = {}           # (unit, number, item or ("ct", n)) -> (index, x, y)
        self.backs: list = []            # (index, order, unit, number, x, y, load index)
        self.fixes: dict = {}            # index -> Fix for a failed cargo order after a warp
        self.events: list = []           # (index, kind, entity id, old, new): renames that ran
        self.pending: list = []          # (index, order, kind, field, value): unknown names
        self.advice: list[dict] = []
        self._rename: Optional[tuple] = None
        self.merges: list = []           # (index, absorbed name, into name): MGFs that ran
        self.fleet_moves: list = []      # (index, order, fleet number): MF/MFS/FIS/FS that ran
        self._merge: Optional[int] = None    # the fleet number an MGF is about to absorb

    # ---- before an order runs: where the unit is, which entity a rename targets, the names used
    def before(self, i: int, o) -> None:
        st, eid = self.st, self.eid
        code = o.code
        if code in SHIP_CARGO or code in FLEET_CARGO:
            u = _unit(st, eid, o)
            if u is not None:
                self.cargo.append((i, o, u[0], u[1], u[3], u[4]))
        self._rename = None
        if code == "NSY":
            s = st.system_named(o.system)
            if s is not None and s.owner == eid:
                self._rename = ("system", s.id, s.name)
        elif code == "CLN":
            ld = st.leader_named(o.leader)
            if ld is not None and ld.owner == eid:
                self._rename = ("leader", ld.id, ld.name)
        elif code == "CRN":
            self._rename = ("race", eid, st.empires[eid].name)
        for fld in SYSTEM_FIELDS.get(code, ()):
            self._ref(i, o, "system", fld)
        for fld in FLEET_FIELDS.get(code, ()):
            self._fleet_ref(i, o, fld)
        self._merge = None
        if code == "MGF" or code in FLEET_MOVES:
            f = st.fleet_named(o.fleet, eid)
            self._merge = f.number if f is not None else None
        for fld in LEADER_FIELDS.get(code, ()):
            self._ref(i, o, "leader", fld)

    def _fleet_ref(self, i: int, o, fld: str) -> None:
        """A fleet named after an MGF in the draft merged it away (and no CF has reused the
        name since): the order fails; suggest the fleet it went into."""
        value = getattr(o, fld, None)
        if not value or self.st.fleet_named(value, self.eid) is not None:
            return
        gone = [m for m in self.merges if m[1] == value]
        if not gone:
            return
        j, _, into = gone[-1]
        right, seen = into, {value}
        while self.st.fleet_named(right, self.eid) is None and right not in seen:
            seen.add(right)                  # merged on again: follow the chain
            nxt = [m for m in self.merges if m[1] == right]
            if not nxt:
                break
            right = nxt[-1][2]
        text = o.line or o.to_text()
        other = getattr(o, "into" if fld == "fleet" else "fleet", None) if o.code == "MGF" else None
        fix = self._fix(o, fld, right) if (self.st.fleet_named(right, self.eid) is not None
                                           and other != right) else None
        self.advice.append(_advice(i, "merged_fleet", (
            f"{text}: fleet {value} is merged into {into} by order {j + 1}, so this order will "
            f"fail: you no longer have a fleet called {value}. Use {right} for the merged "
            f"fleet."), fix))

    def _name_now(self, kind: str, ent: int) -> str:
        return self.st.systems[ent].name if kind == "system" else self.st.leaders[ent].name

    def _known_now(self, kind: str, value: str) -> Optional[int]:
        st = self.st
        if kind == "system":
            s = st.system_named(value)
            if s is not None:
                return s.id
            seen = st.empires[self.eid].seen_systems
            return next((sid for sid, inf in seen.items() if inf.get("name") == value), None)
        ld = st.leader_named(value)
        return ld.id if ld is not None else None

    def _ref(self, i: int, o, kind: str, fld: str) -> None:
        value = getattr(o, fld, None)
        if not value:
            return
        text = o.line or o.to_text()
        what = "system" if kind == "system" else "leader"
        earlier = [ev for ev in self.events if ev[1] == kind and ev[3] == value]
        now = self._known_now(kind, value)
        if now is not None:
            moved = [ev for ev in earlier if ev[2] != now]
            if moved:
                j, _, ent, old, _ = moved[-1]
                self.advice.append(_advice(i, "rename_shift", (
                    f"{text}: {old} is renamed to {self._name_now(kind, ent)} by order {j + 1}, "
                    f"and another {what} has the name {value} now, so this order means that "
                    f"one. If you meant the {what} that was called {old}, use "
                    f"{self._name_now(kind, ent)}.")))
            return
        if earlier:
            j, _, ent, old, _ = earlier[-1]
            right = self._name_now(kind, ent)
            if o.code == "CLN" and fld == "leader":
                self.advice.append(_advice(i, "rename_clash", (
                    f"{text}: order {j + 1} already renames {old} to {right}; a leader can be "
                    f"renamed only once, so this order will fail.")))
                return
            self.advice.append(_advice(i, "rename", (
                f"{text}: {old} is renamed to {right} by order {j + 1}, so this order should "
                f"use {right}."), self._fix(o, fld, right)))
            return
        self.pending.append((i, o, kind, fld, value))

    def _fix(self, o, fld: str, name: str) -> dict:
        d = o.to_dict()
        d[fld] = name
        return {"field": fld, "name": name, "order": d, "label": f"Use {name}"}

    # ---- after it ran: a rename that took effect, or one that collided with an earlier one
    def after(self, i: int, o, r) -> None:
        if o.code in FLEET_MOVES and r.ok and self._merge is not None:
            self.fleet_moves.append((i, o, self._merge))
        if o.code == "MGF" and r.ok:
            self.merges.append((i, o.fleet, o.into))
            for k, mo, fno in self.fleet_moves:
                if fno != self._merge:
                    continue
                what = FLEET_MOVES[mo.code]
                self.advice.append(_advice(k, "merged_move", (
                    f"{mo.line or mo.to_text()}: fleet {o.fleet} is merged into {o.into} by "
                    f"order {i + 1}, so this {what} order no longer applies: the merged fleet "
                    f"moves with fleet {o.into}'s orders.")))
            return
        if o.code in SHIP_CARGO or o.code in FLEET_CARGO:
            self._cargo_after(i, o, r)
            return
        if o.code not in RENAMES or self._rename is None:
            return
        kind, ent, old = self._rename
        text = o.line or o.to_text()
        if r.ok:
            self.events.append((i, kind, ent, old, o.name))
            return
        same = [ev for ev in self.events if ev[1] == kind and ev[2] == ent]
        if kind == "race" and same:
            j = same[-1][0]
            self.advice.append(_advice(i, "rename_clash", (
                f"{text}: order {j + 1} already renames your race to {same[-1][4]}; a race can "
                f"be renamed only once, so this order will fail.")))
            return
        if kind == "leader" and same:
            j = same[-1][0]
            self.advice.append(_advice(i, "rename_clash", (
                f"{text}: order {j + 1} already renames {same[-1][3]} to {same[-1][4]}; a "
                f"leader can be renamed only once, so this order will fail.")))
            return
        taken = [ev for ev in self.events if ev[1] == kind and ev[4] == o.name]
        if taken:
            j, _, _, old_j, _ = taken[-1]
            self.advice.append(_advice(i, "rename_clash", (
                f"{text}: order {j + 1} already renames {old_j} to {o.name}, so this rename "
                f"will fail: the name is taken. Choose another name.")))

    def _cargo_after(self, i: int, o, r) -> None:
        cur = next((c for c in self.cargo if c[0] == i), None)
        if cur is None:
            return
        _, _, unit, num, x, y = cur
        st, eid = self.st, self.eid
        w = self.ctx.warps.get((eid, unit, num)) if self.ctx is not None else None
        if w is not None and w[0] < i and (st.systems[w[3]].x, st.systems[w[3]].y) == (x, y):
            j, fx, fy, _ = w
            fix = self._move_fix(i, j)
            if not r.ok:
                if fix:
                    self.fixes[i] = fix
            else:
                does = CARGO_WORDS[o.code][0].format(ct=getattr(o, "ct", ""))
                self.advice.append(_advice(i, "warp_cargo", (
                    f"{_subject(st, unit, num)} {does} at {place_name(st, eid, x, y)} (after the "
                    f"warp in order {j + 1}), not at {place_name(st, eid, fx, fy)}."), fix))
        if not r.ok:
            return
        thing = ("ct", o.ct) if o.code in ("LOCT", "FLOCT", "LACT", "FLACT") else o.item
        if o.code in LOADS:
            self.loaded[(unit, num, thing)] = (i, x, y)
        elif o.code in UNLOADS:
            ld = self.loaded.get((unit, num, thing))
            if ld is not None and (ld[1], ld[2]) == (x, y):
                self.backs.append((i, o, unit, num, x, y, ld[0]))

    def _move_fix(self, i: int, j: int) -> Optional[dict]:
        """Move order i to just before the warp at j, if the dry run then runs both."""
        if self.state0 is None or self.orders is None:
            return None
        from .turn import check_orders
        lst = list(self.orders)
        lst.insert(j, lst.pop(i))
        res = check_orders(self.state0, self.eid, lst)
        if res[j].ok and res[j + 1].ok:
            return {"move_to": j, "order": None, "label": f"Move it before order {j + 1}"}
        return None

    # ---- after the whole draft: names used too early, cargo unloaded where it was loaded, builds
    def finish(self, orders, results) -> list[dict]:
        for i, o, kind, fld, value in self.pending:
            later = [ev for ev in self.events if ev[1] == kind and ev[4] == value and ev[0] > i]
            if not later:
                continue
            j, _, ent, _, _ = later[0]
            # the entity's name when order i runs: the old name of its first rename at or after i
            first = min((ev for ev in self.events if ev[1] == kind and ev[2] == ent
                         and ev[0] >= i), key=lambda ev: ev[0])
            right = first[3]
            text = o.line or o.to_text()
            self.advice.append(_advice(i, "rename", (
                f"{text}: {right} is renamed to {value} only by order {j + 1}, after this one, "
                f"so this order should use {right}."), self._fix(o, fld, right)))
        self._where_at_end(results)
        for b in self.backs:
            a = self._back_ashore(*b)
            if a:
                self.advice.append(a)
        for i, (o, r) in enumerate(zip(orders, results)):
            if o.code in ("BS", "BCU") and r.ok and o.count and (r.built or 0) < o.count:
                self.advice.append(_advice(i, "build_partial", r.messages[-1]))
        self.advice.sort(key=lambda a: a["index"])
        return self.advice

    def _where_at_end(self, results) -> None:
        """A cargo order that failed for where the unit is: describe where it is going by the
        end of the draft (a move order later in the draft counts), as long as nothing later
        moved the unit itself."""
        if self.ctx is None:
            return
        for i, o, unit, num, x, y in self.cargo:
            base = self.ctx.where_fail.get((self.eid, i))
            if base is None or results[i].ok:
                continue
            u = _unit(self.st, self.eid, o)
            if u is None or (u[3], u[4]) != (x, y):
                continue
            results[i].error = where_error(self.st, self.eid, o, base) or results[i].error

    def _back_ashore(self, i, o, unit, num, x, y, k) -> Optional[dict]:
        st, eid = self.st, self.eid
        u = _unit(st, eid, o)
        if u is None or (u[3], u[4]) != (x, y):
            return None
        motion = u[5]
        if motion is None or motion[0] == "guard":
            return None
        does, inf, noun = CARGO_WORDS[o.code]
        does = does.format(ct=getattr(o, "ct", ""))
        here = place_name(st, eid, x, y)
        thing = "troop" if o.code in ("LACT", "FLACT") else "cargo"
        lead = f"{u[2]} {does} at {here}, where order {k + 1} loaded it, before it moves"
        if motion[0] == "intercept":
            return _advice(i, "move_cargo", (
                f"{lead} to intercept ship {motion[4]} (orders run before movement), so the "
                f"{thing} stays at {here}. To {inf} where it ends up, give the {noun} order "
                f"next turn."))
        _, dx, dy, turns, _ = motion
        dest = place_name(st, eid, dx, dy)
        if turns == 1:
            when = "next turn"
        elif turns:
            when = f"on turn {st.turn + turns}, once it has arrived"
        else:
            when = "once it has arrived"
        return _advice(i, "move_cargo", (
            f"{lead} to {dest} (orders run before movement), so the {thing} stays at {here}. "
            f"To {inf} at {dest}, give the {noun} order {when}."))


# ---- where a unit is and where it is going (the empire's own knowledge only)
def _subject(st, unit: str, num: int) -> str:
    return f"Ship {num}" if unit == "ship" else f"Fleet {st.fleets[num].name}"


def _turns(st, x, y, dx, dy, speed) -> Optional[int]:
    """Movement phases until (x, y) reaches (dx, dy) at `speed` (1 = this turn's)."""
    if speed is None or speed <= 0:
        return None
    n = 0
    while (x, y) != (dx, dy) and n < 500:
        x, y = G.step(x, y, dx, dy, speed, st.board)
        n += 1
    return n if (x, y) == (dx, dy) else None


def fleet_motion(st, f):
    """(kind, dest x, dest y, turns to arrive or None, target) for a fleet that moves, else
    None.  kind: "point" or "intercept"."""
    members = [s for s in st.fleet_ships(f.number) if s.owner == f.owner and s.alive]
    body = [s for s in members if (s.x, s.y) == (f.x, f.y)]
    if f.order == INTERCEPT and members:
        return ("intercept", None, None, None, f.target)
    if f.order in (MOVE, MOVE_TO_SYSTEM) and body and (f.dx, f.dy) != (f.x, f.y):
        slowest = min(s.stype.move for s in body)
        fastest = max(s.stype.move for s in body)
        speed = slowest if f.speed is None else min(f.speed, fastest)
        return ("point", f.dx, f.dy, _turns(st, f.x, f.y, f.dx, f.dy, speed), None)
    return None


def ship_motion(st, sh):
    """The same for a ship: its own move, intercept or guard, or its fleet's."""
    f = st.fleets.get(sh.fleet) if sh.fleet is not None else None
    if f is not None and f.alive and f.owner == sh.owner:
        fm = fleet_motion(st, f)
        if (sh.x, sh.y) == (f.x, f.y):
            return fm
        # away from its fleet: it heads for the fleet's square (movement.move_fleets)
        if fm is not None and fm[0] == "intercept":
            return fm
        if fm is not None and fm[3] == 1:
            tx, ty = fm[1], fm[2]
        else:
            tx, ty = f.x, f.y
        turns = _turns(st, sh.x, sh.y, tx, ty, sh.stype.move)
        if fm is not None and fm[3] != 1 and turns != 1:
            turns = None                 # the fleet moves on meanwhile
        return ("point", tx, ty, turns, None)
    if sh.order in (MOVE, MOVE_TO_SYSTEM) and (sh.dx, sh.dy) != (sh.x, sh.y):
        return ("point", sh.dx, sh.dy, _turns(st, sh.x, sh.y, sh.dx, sh.dy, sh.stype.move), None)
    if sh.order == INTERCEPT:
        return ("intercept", None, None, None, sh.target)
    if sh.order == GUARD:
        return ("guard", None, None, None, None)
    return None


def _unit(st, eid: int, o):
    """("ship"|"fleet", number, subject, x, y, motion) for a cargo order's own unit, else None
    (SL on another race's ship, a ship or fleet that doesn't exist)."""
    if o.code in SHIP_CARGO:
        sh = st.ship(o.ship)
        if sh is None or not sh.alive or sh.owner != eid:
            return None
        return ("ship", sh.number, f"Ship {sh.number}", sh.x, sh.y, ship_motion(st, sh))
    if o.code in FLEET_CARGO:
        f = st.fleet_named(o.fleet, eid)
        if f is None or not f.alive:
            return None
        return ("fleet", f.number, f"Fleet {f.name}", f.x, f.y, fleet_motion(st, f))
    return None


def _going(st, eid: int, o, motion) -> str:
    """"Goosebeak (arrives in 2 turns, at the end of turn 8). It can load once it's there: give
    the load order on turn 9." for a unit on its way somewhere."""
    _, dx, dy, turns, _ = motion
    _, inf, noun = CARGO_WORDS[o.code]
    dest = place_name(st, eid, dx, dy)
    if turns == 1:
        arr, when = " (arrives at the end of this turn)", " next turn"
    elif turns:
        arr = f" (arrives in {turns} turns, at the end of turn {st.turn + turns - 1})"
        when = f" on turn {st.turn + turns}"
    else:
        arr, when = "", ""
    ds = st.system_at(dx, dy)
    known = ds is not None and (ds.owner == eid or ds.id in st.empires[eid].seen_systems)
    if known and (ds.owner == eid or o.code in ANY_SYSTEM):
        if when:
            return f"{dest}{arr}. It can {inf} once it's there: give the {noun} order{when}."
        return f"{dest}{arr}. It can {inf} once it's there."
    if known and o.code in OWN_ONLY:
        return f"{dest}{arr}, which isn't one of your systems either."
    return f"{dest}{arr}."


def where_error(st, eid: int, o, base: str) -> Optional[str]:
    """A cargo order that failed because of where its unit is: say where that is and, for a
    unit still travelling, where it is going and when it gets there.  None if it isn't the
    empire's own unit (nothing is said about other races' ships)."""
    u = _unit(st, eid, o)
    if u is None:
        return None
    _, _, subject, x, y, motion = u
    inf = CARGO_WORDS[o.code][1]
    need = "one of your systems" if o.code in OWN_ONLY else "a system"
    if st.system_at(x, y) is None:
        lead = f"{subject} is in deep space at {place_name(st, eid, x, y)}"
        if motion is None or motion[0] == "guard":
            return f"{lead} with no move order: it must be at {need} to {inf}."
        if motion[0] == "intercept":
            return (f"{lead}, on its way to intercept ship {motion[4]}: it must be at {need} "
                    f"to {inf}.")
        return f"{lead}, still on its way to {_going(st, eid, o, motion)}"
    if motion is None or motion[0] != "point":
        return base
    return f"{base} It is still on its way to {_going(st, eid, o, motion)}"


def cargo_error(ctx, eid: int, o, index: int, exc) -> str:
    """The error text for a failed order (orders_exec.execute).  For a cargo order: after a
    warp of the same unit earlier in the draft, the warp is named as the cause; when the unit
    isn't where it can act (WhereError), where it is and where it is going."""
    base = str(exc)
    if o.code not in SHIP_CARGO and o.code not in FLEET_CARGO:
        return base
    st = ctx.state
    u = _unit(st, eid, o)
    if u is None:
        return base
    unit, num, subject, x, y, _ = u
    w = ctx.warps.get((eid, unit, num))
    if w is not None and w[0] < index and (st.systems[w[3]].x, st.systems[w[3]].y) == (x, y):
        _, inf, noun = CARGO_WORDS[o.code]
        there = place_name(st, eid, x, y)
        s = st.system_at(x, y)
        if isinstance(exc, WhereError) and (s is None or s.owner != eid):
            mid = ", which isn't yours."
        else:
            mid = f": {base}"
        return (f"{subject} was moved to {there} by your warp order (order {w[0] + 1}) before "
                f"this {noun}, so it tries to {inf} at {there}{mid} Put the {noun} before the "
                f"warp order.")
    if isinstance(exc, WhereError):
        ctx.where_fail[(eid, index)] = base
        return where_error(st, eid, o, base) or base
    return base
