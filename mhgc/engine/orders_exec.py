"""Order execution: validate each order against the current state and apply it.

Handlers raise OrderError(message) *before* changing anything, so a failed order has no effect.
The order of checks and the error wording follow the C engine (gcparser.c, gcparse1.c) where the
rules are silent; DECISIONS.md lists the deliberate differences.  Each handler returns an optional
list of info lines for the order's result (acknowledgements such as "Bought Robotics.").
"""
from __future__ import annotations

from typing import Callable, Optional

from .. import geometry as G
from ..data import constants as K
from ..data.artifacts import ARTIFACTS, SPY_EU_COST, SPY_IU_COST, SPY_KEY
from ..data.ships import SHIP_TYPES
from ..data.techs import FUTURE_TECH, TECHS, missing_prereqs
from ..data.troops import TROOP_TYPES
from ..model import (GUARD, HUMAN, INTERCEPT, MOVE, MOVE_TO_SYSTEM, NPR, STAND, Fleet, Ship, Spy,
                     System, Troop)
from ..orders import Order
from ..results import OrderResult
from .advice import cargo_error
from .context import OrderError, TurnContext, WhereError
from .scans import remember

Handler = Callable[[TurnContext, int, Order], Optional[list]]
HANDLERS: dict[str, Handler] = {}


def handler(*codes):
    def deco(fn):
        for c in codes:
            HANDLERS[c] = fn
        return fn
    return deco


# ---------------------------------------------------------------------------------------------
# lookups that raise OrderError with clear messages.  Where a lookup could reveal something you
# can't see (a ship, system, leader or race you haven't found), "doesn't exist" and "isn't
# yours" share one message.
# ---------------------------------------------------------------------------------------------

ITEM_NAMES = {"A": "AU", "I": "IU", "P": "population"}
STATUS_TEXT = {K.UNDER_ATTACK: "under attack (UA)", K.INTERDICTED: "interdicted (INT)"}


def _status_error(s: System, what: str = "") -> OrderError:
    return OrderError(f"{s.name} is {STATUS_TEXT.get(s.status, K.STATUS_NAMES[s.status])}, so "
                      f"{what or 'this order cannot be carried out there'}.")


def _system(ctx, name) -> System:
    s = ctx.state.system_named(name)
    if s is None:
        raise OrderError(f"There is no system called {name}.")
    return s


def _own_system(ctx, eid, name, status: Optional[str] = None) -> System:
    s = ctx.state.system_named(name)
    if s is None or s.owner != eid:
        raise OrderError(f"You don't own a system called {name}.")
    if status == "normal" and s.status != K.NORMAL:
        raise _status_error(s, "it needs to be at normal status for this order")
    if status == "nonint" and s.status == K.INTERDICTED:
        raise _status_error(s, "it can't do this until the interdiction ends")
    return s


def _known_system(ctx, eid, name) -> System:
    """A system you own or have scanned (or found on a CD-ROM).  An unscanned system gets the
    same message as a name that doesn't exist.

    A system renamed since you last saw it is still found by the name your map memory has for it
    (Dave 2026-11-13, DECISIONS W-14: computer empires now rename the worlds they take, and a
    player's map shows the name as last seen).  Only your own memory is consulted, so this
    reveals nothing new."""
    s = ctx.state.system_named(name)
    if s is None or not _seen(ctx, eid, s):
        seen = ctx.emp(eid).seen_systems
        sid = next((i for i, info in sorted(seen.items()) if info.get("name") == name), None)
        if sid is None or not 0 <= sid < len(ctx.state.systems):
            raise OrderError(f"You haven't scanned a system called {name}.")
        s = ctx.state.systems[sid]
    return s


def _own_ship(ctx, eid, number) -> Ship:
    s = ctx.state.ship(number)
    if s is None or s.owner != eid:
        raise OrderError(f"Ship {number} doesn't exist or isn't yours.")
    return s


def _own_fleet(ctx, eid, name) -> Fleet:
    f = ctx.state.fleet_named(name, eid)
    if f is None:
        raise OrderError(f"You don't have a fleet called {name}.")
    return f


def _own_ct(ctx, eid, number) -> Troop:
    t = ctx.state.troops.get(number)
    if t is None or not t.alive or t.owner != eid:
        raise OrderError(f"Combat troop {number} doesn't exist or isn't yours.")
    return t


def _own_spy(ctx, eid, number) -> Spy:
    s = ctx.state.spies.get(number)
    if s is None or not s.alive or s.owner != eid:
        raise OrderError(f"Spy {number} doesn't exist or isn't yours.")
    return s


def _own_leader(ctx, eid, name):
    ld = ctx.state.leader_named(name)
    if ld is None or ld.owner != eid:
        raise OrderError(f"You don't have a leader called {name}.")
    return ld


def _race(ctx, eid, name, contact=True):
    e = ctx.state.empire_named(name)
    if e is not None and e.id == eid:
        raise OrderError("That's your own race.")
    if e is None or e.id == 0 or (contact and not ctx.emp(eid).has_contact(e.id)):
        raise OrderError(f"You haven't made contact with a race called {name}.")
    if e.kind == "dead":
        raise OrderError(f"The {e.name} are extinct.")
    return e


def _system_at_ship(ctx, ship) -> System:
    s = ctx.state.system_at(ship.x, ship.y)
    if s is None:
        raise WhereError(f"Ship {ship.number} isn't at a system.")
    return s


def _seen(ctx, eid, s: System) -> bool:
    return s.owner == eid or s.id in ctx.emp(eid).seen_systems


def _pay_eu(ctx, eid, amount):
    e = ctx.emp(eid)
    if e.eu < amount:
        raise OrderError(f"This costs {amount} EU, but you have only {e.eu}.")
    return amount


def _need_eu(ctx, eid, amount, what):
    e = ctx.emp(eid)
    if e.eu < amount:
        raise OrderError(f"{what} costs {amount} EU, but you have only {e.eu}.")


def _need_iu(s: System, amount):
    if s.iu < amount:
        raise OrderError(f"This needs {amount} IU from {s.name}'s stockpile, which has only "
                         f"{s.iu}.")


def _spend(ctx, eid, s: Optional[System], iu: int, eu: int):
    """Every EU and system IU an order spends goes through here, so the maintenance ledger
    shows it (DECISIONS, Dave 2026-11-12)."""
    e = ctx.emp(eid)
    e.eu -= eu
    ctx.purch_eu[eid] += eu
    if s is not None and iu:
        s.iu -= iu
        ctx.econ[s.id].purch_iu += iu
        ctx.purch_iu[eid] += iu


def _refund(ctx, eid, s: System, iu: int, eu: int):
    """Salvage (SS, SCT): IUs back to the system, EUs back to the empire, both in the ledger."""
    s.iu += iu
    ctx.emp(eid).eu += eu
    ctx.refund_iu[eid] += iu
    ctx.refund_eu[eid] += eu


def _gift_out(ctx, eid, eu: int):
    """EU an empire gives away or pays for a tech gift or trade (GE, GT, TTNPR)."""
    ctx.emp(eid).eu -= eu
    ctx.gift_out_eu[eid] += eu


def _capacity_left(ctx, s: System) -> float:
    return s.starport - ctx.builds[s.id]


def _check_build(ctx, s: System, need: float):
    if s.id in ctx.starport_changed:
        raise OrderError(f"The starport at {s.name} was built or reduced this turn, so it can't "
                         f"build or salvage anything until next turn.")
    if ctx.builds[s.id] + need > s.starport:
        if s.starport <= 0:
            raise OrderError(f"{s.name} has no starport. Build one first (BSP).")
        raise OrderError(f"The class {s.starport} starport at {s.name} has no capacity left this "
                         f"turn: {ctx.builds[s.id]:g} of {s.starport} used, and this needs "
                         f"{need:g}.")


# ---------------------------------------------------------------------------------------------
# unit creation
# ---------------------------------------------------------------------------------------------

def create_ship(ctx, owner, stype, s: System, posture="N", role="SC") -> Ship:
    st = ctx.state
    num = ctx.rng.new_number(st.ships.keys(), 10000)
    sh = Ship(num, owner, stype, s.x, s.y, dx=s.x, dy=s.y, posture=posture, role=role,
              home=s.id, built_turn=st.turn, ox=s.x, oy=s.y)
    st.ships[num] = sh
    return sh


def create_troop(ctx, owner, ttype, sys_id=None, ship=None, posture="A") -> Troop:
    st = ctx.state
    num = ctx.rng.new_number(st.troops.keys(), 10000)
    t = Troop(num, owner, ttype, system=sys_id, ship=ship, posture=posture, built_turn=st.turn)
    st.troops[num] = t
    return t


def create_spy(ctx, owner, s: System) -> Spy:
    st = ctx.state
    num = ctx.rng.new_number(st.spies.keys(), 1000)
    sp = Spy(num, owner, s.id)
    st.spies[num] = sp
    return sp


def capture_unowned(ctx, eid, s: System, bonus=True):
    """Colonisation/capture of an unowned (or empty) system by landing pop or troops
    (gcparse1.c:1062-1077, 445-455).  The morale bonus applies to every capture route
    (C forgot it for drop pods; DECISIONS B-34)."""
    s.owner = eid
    s.happy = 0.2
    s.trade_routes.clear()
    e = ctx.emp(eid)
    if bonus and e.systems_captured >= 0:
        e.systems_captured += s.hab // 4
    remember(e, s, ctx.turn, True)


# ---------------------------------------------------------------------------------------------
# ship orders
# ---------------------------------------------------------------------------------------------

@handler("MO")
def _mo(ctx, eid, o):
    sh = _own_ship(ctx, eid, o.ship)
    sh.dx, sh.dy = ctx.abs_xy(eid, o.x, o.y)
    sh.order, sh.dest_system, sh.target = MOVE, None, None


@handler("MS")
def _ms(ctx, eid, o):
    sh = _own_ship(ctx, eid, o.ship)
    s = _known_system(ctx, eid, o.system)
    sh.dx, sh.dy = s.x, s.y
    sh.order, sh.dest_system, sh.target = MOVE_TO_SYSTEM, s.id, None


@handler("I")
def _i(ctx, eid, o):
    sh = _own_ship(ctx, eid, o.ship)
    tgt = ctx.state.ship(o.target)
    if tgt is None:
        raise OrderError(f"There is no ship {o.target} to intercept.")
    if tgt.number == sh.number:
        raise OrderError(f"Ship {sh.number} can't intercept itself.")
    sh.order, sh.target, sh.dest_system = INTERCEPT, tgt.number, None


@handler("G")
def _g(ctx, eid, o):
    sh = _own_ship(ctx, eid, o.ship)
    sh.order, sh.target, sh.dest_system = GUARD, None, None
    sh.dx, sh.dy = sh.x, sh.y


@handler("SP")
def _sp(ctx, eid, o):
    _own_ship(ctx, eid, o.ship).posture = o.posture


@handler("CSCR")
def _cscr(ctx, eid, o):
    _own_ship(ctx, eid, o.ship).role = o.role


def destroy_ship(ctx, sh: Ship):
    sh.alive = False
    for t in ctx.state.troops_aboard(sh.number):
        t.alive = False


@handler("DS")
def _ds(ctx, eid, o):
    destroy_ship(ctx, _own_ship(ctx, eid, o.ship))


@handler("SS")
def _ss(ctx, eid, o):
    sh = _own_ship(ctx, eid, o.ship)
    s = ctx.state.system_at(sh.x, sh.y)
    if s is None or s.owner != eid:
        raise OrderError(f"Ship {sh.number} must be at one of your systems to be salvaged.")
    if s.status != K.NORMAL:
        raise _status_error(s, "ships can't be salvaged there")
    _check_build(ctx, s, 1)          # NPRs too (DECISIONS A-01)
    ctx.builds[s.id] += 1
    st = sh.stype
    _refund(ctx, eid, s, int(st.iu_cost * K.SS_REFUND), int(st.eu_cost * K.SS_REFUND))
    # Cargo is put ashore rather than orphaned (C left CTs aboard a dead ship; DECISIONS B-23).
    s.au += sh.cargo_au
    s.iu += sh.cargo_iu
    s.pop += sh.cargo_pop
    for t in ctx.state.troops_aboard(sh.number):
        t.ship, t.system = None, s.id
    sh.cargo_au = sh.cargo_iu = sh.cargo_pop = 0
    sh.alive = False
    return [f"Salvaged for {int(st.iu_cost * K.SS_REFUND)} IU (to {s.name}) and "
            f"{int(st.eu_cost * K.SS_REFUND)} EU."]


def _load(ctx, sh: Ship, s: System, item: str, n: int):
    if n < 0:
        raise OrderError("The amount to load can't be negative.")
    what = ITEM_NAMES[item]
    free = ctx.state.free_cargo(sh, item)
    if free < n:
        raise OrderError(f"Ship {sh.number} has room for only {free} more {what}.")
    have = {"A": s.au, "I": s.iu, "P": s.pop}[item]
    if have < n:
        raise OrderError(f"{s.name} has only {have:g} {what} to load.")
    if item == "A":
        s.au -= n
        sh.cargo_au += n
    elif item == "I":
        s.iu -= n
        sh.cargo_iu += n
    else:
        s.pop -= n
        sh.cargo_pop += n


@handler("L")
def _l(ctx, eid, o):
    sh = _own_ship(ctx, eid, o.ship)
    s = _system_at_ship(ctx, sh)
    if s.owner != eid:
        raise WhereError(f"Ship {sh.number} is at {s.name}, which isn't yours. Ships load only "
                         f"at your own systems.")
    _load(ctx, sh, s, o.item, o.amount)


@handler("SL")
def _sl(ctx, eid, o):
    sh = ctx.state.ship(o.ship)
    s = ctx.state.system_at(sh.x, sh.y) if sh is not None else None
    if s is None or s.owner != eid:
        # one message whether or not the ship exists: SL works on any ship at your system
        raise WhereError(f"Ship {o.ship} isn't at one of your systems.")
    _load(ctx, sh, s, o.item, o.amount)


def unload(ctx, eid, sh: Ship, s: System, item: str, n: int, gift: bool,
           fleet: bool = False) -> list:
    """U / UG (gcparse1.c:1017-1104) with the fixes in DECISIONS B-07/B-09."""
    msgs = []
    if n < 0:
        raise OrderError("The amount to unload can't be negative.")
    own = s.owner == eid
    uninhabited = s.pop <= 0 and s.owner in (0, eid)
    if not own and not gift and not (item == "P" and uninhabited):
        if uninhabited:
            # the trap: IU/AU ordered before the population that would capture the system
            raise OrderError(f"{s.name} isn't yours yet. Unload population first to claim it, "
                             f"then unload IU/AU in a later order.")
        raise WhereError(f"{s.name} isn't yours. To unload at another race's system, use "
                         f"{'FUG' if fleet else 'UG'} (unload as a gift).")
    if item == "A":
        if sh.cargo_au < n:
            raise OrderError(f"Ship {sh.number} carries only {sh.cargo_au} AU.")
        sh.cargo_au -= n
        s.au += n
        return msgs
    if item == "I":
        if sh.cargo_iu < n:
            raise OrderError(f"Ship {sh.number} carries only {sh.cargo_iu} IU.")
        sh.cargo_iu -= n
        s.iu += n
        return msgs
    if sh.cargo_pop < n:
        raise OrderError(f"Ship {sh.number} carries only {sh.cargo_pop:g} population.")
    if n == 0:
        return msgs
    if s.pop <= 0:
        if s.owner not in (0, eid):
            raise OrderError(f"{s.name} is held by the {ctx.name(s.owner)}. Land combat troops "
                             f"to take it.")
        newly = s.owner != eid
        if newly:
            capture_unowned(ctx, eid, s)
            msgs.append(f"You have captured the unowned system {s.name}.")
            if not ctx.checking:
                ctx.res.emit(eid, "colonized", f"You have captured the unowned system {s.name}.",
                             "orders", s.id)
    else:
        h = s.pop * s.pop * n / ((s.hab + (1 if s.has("EHC") else 0) +
                                   (3 if s.has("CS") else 0)) * K.IMMIGRATION_DIVISOR)
        if s.happy - h < 0:
            raise OrderError(f"Landing {n} population on {s.name} would push its happiness below "
                             f"zero and start a rebellion, so the landing was cancelled. Try "
                             f"landing fewer.")
        s.happy -= h
        if h > 0.05:
            msgs.append("Crowds protest in anger over forced immigration")
            if s.owner != eid and not ctx.checking:
                ctx.res.emit(s.owner, "immigration_protest",
                             f"Crowds on {s.name} protest in anger over unwelcome alien "
                             f"riff-raff from the {ctx.name(eid)}", "orders", s.id)
    sh.cargo_pop -= n
    s.pop += n
    return msgs


@handler("U", "UG")
def _u(ctx, eid, o):
    sh = _own_ship(ctx, eid, o.ship)
    s = _system_at_ship(ctx, sh)
    return unload(ctx, eid, sh, s, o.item, o.amount, o.code == "UG")


def load_ct(ctx, eid, sh: Ship, t: Troop):
    s = _system_at_ship(ctx, sh)
    if s.owner != eid and not (s.owner > 0 and ctx.allied(s.owner, eid)):
        raise WhereError(f"Ship {sh.number} is at {s.name}, which is neither yours nor an "
                         f"ally's. Troops board only at your own or allied systems.")
    if t.type == "M":
        raise OrderError(f"Militia can't be transported; troop {t.number} is militia.")
    if t.system != s.id:
        sent = ctx.farcast.get((eid, t.number))
        why = ""
        if sent is not None and sent[1] == s.id and t.system == sent[2]:
            why = (f" Your farcaster order (order {sent[0] + 1}) sent it to "
                   f"{ctx.state.systems[sent[2]].name} before this order; put the troop load "
                   f"before the TP.")
        raise OrderError(f"Combat troop {t.number} isn't at {s.name}, where ship {sh.number} "
                         f"is.{why}")
    if ctx.state.cargo_points_used(sh) + 1 > sh.stype.cargo:
        raise OrderError(f"Ship {sh.number} has no cargo room left for a combat troop.")
    t.system, t.ship = None, sh.number
    if t.posture not in ("A", "D"):
        t.posture = "A"


@handler("LOCT")
def _loct(ctx, eid, o):
    load_ct(ctx, eid, _own_ship(ctx, eid, o.ship), _own_ct(ctx, eid, o.ct))


def land_ct(ctx, eid, sh: Ship, t: Troop):
    s = _system_at_ship(ctx, sh)
    if t.ship != sh.number:
        raise OrderError(f"Combat troop {t.number} isn't aboard ship {sh.number}.")
    t.ship, t.system = None, s.id
    msgs = []
    if s.owner == 0 and s.pop < 1.0:
        capture_unowned(ctx, eid, s)
        msgs.append(f"You have captured the unowned system {s.name}.")
    elif s.owner != eid and not ctx.allied(s.owner, eid):
        sh.posture = "H"   # rules:510-516
        # The whole fleet behaves hostile (rules:511): ships take the most aggressive posture.
    return msgs


@handler("LACT")
def _lact(ctx, eid, o):
    return land_ct(ctx, eid, _own_ship(ctx, eid, o.ship), _own_ct(ctx, eid, o.ct))


@handler("DOCT")
def _doct(ctx, eid, o):
    sh = _own_ship(ctx, eid, o.ship)
    if not ctx.state.troops_aboard(sh.number):
        raise OrderError(f"Ship {sh.number} has no combat troops aboard to drop.")
    sh.drop = True


@handler("CTT")
def _ctt(ctx, eid, o):
    if 21 not in ctx.emp(eid).techs:
        raise OrderError(f"You need {TECHS[21].name} (tech 21) to set up trade routes.")
    sh = _own_ship(ctx, eid, o.ship)
    if sh.stype.cargo <= 0:
        raise OrderError(f"Only a transport can become a trade route; ship {sh.number} is a "
                         f"{sh.stype.name}.")
    s = _system_at_ship(ctx, sh)
    if s.owner == eid:
        raise OrderError(f"{s.name} is your own system. Trade routes go to other races' "
                         f"systems.")
    if s.pop <= 0:
        raise OrderError(f"{s.name} has no population. Trade routes go to other races' "
                         f"populated systems.")
    if eid in s.trade_routes:
        raise OrderError(f"You already have a trade route with {s.name}.")
    if ctx.state.troops_aboard(sh.number):
        raise OrderError(f"Ship {sh.number} has combat troops aboard. Land or unload them first.")
    s.trade_routes.add(eid)
    sh.alive = False
    if not ctx.checking:
        ctx.res.emit(eid, "trade_route", f"Trade route established with {s.name}.", "orders",
                     s.id)


def _check_warp(ctx, eid, x, y, dest: System, what: str) -> System:
    s = ctx.state.system_at(x, y)
    if s is None or s.owner != eid:
        raise OrderError(f"{what} must be at one of your systems to use a warp tunnel.")
    if s.status != K.NORMAL:
        raise _status_error(s, "its warp tunnel can't send anything")
    if not s.has("WT"):
        raise OrderError(f"{s.name} has no warp tunnel to send from.")
    if not dest.has("WT"):
        raise OrderError(f"{dest.name} has no warp tunnel to receive at.")
    return s


def _warp(ctx, eid, sh: Ship, dest: System):
    _spend(ctx, eid, None, 0, 10)
    ctx.warps[(eid, "ship", sh.number)] = (ctx.order_index, sh.x, sh.y, dest.id)
    sh.x = sh.dx = dest.x
    sh.y = sh.dy = dest.y
    sh.order = STAND


@handler("WTP")
def _wtp(ctx, eid, o):
    sh = _own_ship(ctx, eid, o.ship)
    dest = _own_system(ctx, eid, o.system, "normal")
    _check_warp(ctx, eid, sh.x, sh.y, dest, f"Ship {sh.number}")
    _need_eu(ctx, eid, 10, "A warp tunnel jump")
    _warp(ctx, eid, sh, dest)


@handler("GS")
def _gs(ctx, eid, o):
    them = _race(ctx, eid, o.race)
    # Dave 2026-11-12: no gifting ships to a race you are at war with.  "You are at war" is
    # the giver's own stance (W, or E = peace offered); the recipient's stance is hidden.
    if ctx.at_war(eid, them.id):
        raise OrderError(f"You can't gift a ship to the {them.name} while you are at war with "
                         f"them. The war has to end first: both sides give EWA.")
    sh = _own_ship(ctx, eid, o.ship)
    sh.owner = them.id
    sh.fleet = None
    sh.order, sh.dx, sh.dy = STAND, sh.x, sh.y
    for t in ctx.state.troops_aboard(sh.number):
        t.owner = them.id
    if not ctx.checking:
        ctx.res.emit(them.id, "info", f"The {ctx.name(eid)} have given you ship {sh.number} "
                     f"({sh.stype.name}).", "orders")


# ---------------------------------------------------------------------------------------------
# fleets
# ---------------------------------------------------------------------------------------------

def shift_role(sh: Ship, fleet_role: str, carrying_ct: bool) -> str:
    """Roles for OF/DF/PT fleets (rules:899-901; gcparser.c:2502-2524)."""
    armed = sh.stype.attack > 0
    if fleet_role == "OF":
        return "RD" if carrying_ct else ("MR" if armed else "SC")
    if fleet_role == "DF":
        return "MR" if armed else "SC"
    return "SC" if armed else "RD"           # PT: non-attackers RD, everyone else SC


def add_ship_to_fleet(ctx, f: Fleet, sh: Ship):
    """gcparser.c:2617-2658."""
    if f.order == INTERCEPT:
        sh.order, sh.target = INTERCEPT, f.target
    if f.posture in ("H", "N", "F"):
        sh.posture = f.posture
    elif f.posture == "AH":
        sh.posture = "H" if sh.stype.attack > 0 else "F"
    elif f.posture == "AN":
        sh.posture = "N" if sh.stype.attack > 0 else "F"
    if f.role in ("SC", "MR", "GC", "RD"):
        sh.role = f.role
    elif f.role in ("OF", "DF", "PT"):
        sh.role = shift_role(sh, f.role, bool(ctx.state.troops_aboard(sh.number)))
    sh.fleet = f.number
    ctx.filled_fleets.add(f.number)


def create_fleet(ctx, eid, name, x, y) -> Fleet:
    # Unique among your own fleets only (Dave 2026-11-16, G-16): orders name only your own fleets,
    # and a galaxy-wide check told you another race had a fleet of that name.
    if ctx.state.fleet_named(name, eid) is not None:
        raise OrderError(f"You already have a fleet called {name}.")
    num = max(ctx.state.fleets.keys(), default=0) + 1
    f = Fleet(num, eid, name, x, y, dx=x, dy=y, ox=x, oy=y)
    ctx.state.fleets[num] = f
    ctx.new_fleets.add(num)
    return f


@handler("CF", "CFXY")
def _cf(ctx, eid, o):
    x, y = ctx.abs_xy(eid, o.x, o.y)
    f = create_fleet(ctx, eid, o.name, x, y)
    if o.code == "CFXY":
        ctx.addfleetxy.append((f.number, x, y, eid))


@handler("AFXY")
def _afxy(ctx, eid, o):
    f = _own_fleet(ctx, eid, o.fleet)
    x, y = ctx.abs_xy(eid, o.x, o.y)
    ctx.addfleetxy.append((f.number, x, y, eid))


@handler("AF")
def _af(ctx, eid, o):
    f = _own_fleet(ctx, eid, o.fleet)
    msgs, ok = [], 0
    for n in o.ships:
        sh = ctx.state.ship(n)
        if sh is None or sh.owner != eid:
            msgs.append(f"Ship {n} doesn't exist or isn't yours.")
        else:
            add_ship_to_fleet(ctx, f, sh)
            ok += 1
    if not ok:
        raise OrderError(" ".join(msgs))
    return msgs


@handler("LF")
def _lf(ctx, eid, o):
    f = _own_fleet(ctx, eid, o.fleet)
    msgs, ok = [], 0
    for n in o.ships:
        sh = ctx.state.ship(n)
        if sh is None or sh.fleet != f.number:
            msgs.append(f"Ship {n} isn't in fleet {f.name}.")
        else:
            sh.fleet = None
            ok += 1
    if not ok:
        raise OrderError(" ".join(msgs))
    return msgs


def _fleet_members(ctx, f: Fleet):
    return [s for s in ctx.state.fleet_ships(f.number) if s.owner == f.owner]


@handler("MF")
def _mf(ctx, eid, o):
    f = _own_fleet(ctx, eid, o.fleet)
    f.dx, f.dy = ctx.abs_xy(eid, o.x, o.y)
    f.order, f.target, f.dest_system = MOVE, None, None


@handler("MFS")
def _mfs(ctx, eid, o):
    f = _own_fleet(ctx, eid, o.fleet)
    s = _known_system(ctx, eid, o.system)
    f.dx, f.dy = s.x, s.y
    f.order, f.target, f.dest_system = MOVE_TO_SYSTEM, None, s.id


@handler("FIS")
def _fis(ctx, eid, o):
    f = _own_fleet(ctx, eid, o.fleet)
    tgt = ctx.state.ship(o.target)
    if tgt is None:
        raise OrderError(f"There is no ship {o.target} to intercept.")
    f.order, f.target = INTERCEPT, tgt.number
    for sh in _fleet_members(ctx, f):
        if sh.number != tgt.number:
            sh.order, sh.target = INTERCEPT, tgt.number


@handler("DF")
def _df(ctx, eid, o):
    f = _own_fleet(ctx, eid, o.fleet)
    disband_fleet(ctx, f)


@handler("MGF")
def _mgf(ctx, eid, o):
    """Merge fleets (Dave 2026-11-21, DECISIONS G-27; a new order, the rules have none).  Every
    ship of the first fleet joins the second exactly as AF would add it (the second fleet's
    posture and role apply; a ship away from the first fleet's main body heads for the second
    fleet's square, the AF "main body" rule), then the first fleet is disbanded as DF would (its
    name is free at once).  Its admiral transfers to the second fleet when that fleet has none
    (otherwise awaits a new post), and a leader on the way to it goes on to the second fleet
    (Dave 2026-11-21).  The second fleet keeps its name, posture, role, speed and orders."""
    a = _own_fleet(ctx, eid, o.fleet)
    b = _own_fleet(ctx, eid, o.into)
    if a is b:
        raise OrderError(f"MGF needs two different fleets; {a.name} is named twice.")
    if (a.x, a.y) != (b.x, b.y):
        ax, ay = ctx.rel_xy(eid, a.x, a.y)
        bx, by = ctx.rel_xy(eid, b.x, b.y)
        raise OrderError(f"Fleet {a.name} is at {ax},{ay}; fleet {b.name} is at {bx},{by}: "
                         f"fleets merge only at the same square.")
    ships = _fleet_members(ctx, a)
    away = [sh.number for sh in ships if (sh.x, sh.y) != (a.x, a.y)]
    for sh in ships:
        add_ship_to_fleet(ctx, b, sh)
    # an AFXY for the absorbed fleet earlier in the draft fills the merged fleet instead
    ctx.addfleetxy = [(b.number if fno == a.number else fno, x, y, ow)
                      for fno, x, y, ow in ctx.addfleetxy]
    adm = ctx.state.admiral(a.number)
    on_way = [ld for ld in ctx.state.leaders.values()
              if ld.alive and ld.fleet == a.number and ld is not adm]
    # the admiral transfers when the merged fleet has none; leaders on the way follow the ships
    moved = adm is not None and ctx.state.admiral(b.number) is None
    if moved:
        adm.fleet = b.number
    for ld in on_way:
        if ld.status == "transit":
            ld.fleet = b.number
    disband_fleet(ctx, a)
    n = len(_fleet_members(ctx, b))
    msgs = [f"Fleet {a.name} ({len(ships)} ship{'' if len(ships) == 1 else 's'}) merged into "
            f"fleet {b.name}, which has {n} ship{'' if n == 1 else 's'} now; the name "
            f"{a.name} is free."]
    if away:
        msgs.append(f"Ship{'' if len(away) == 1 else 's'} {', '.join(map(str, away))} "
                    f"{'was' if len(away) == 1 else 'were'} not with {a.name}'s main body, and "
                    f"head{'s' if len(away) == 1 else ''} for fleet {b.name} to join it.")
    if moved:
        msgs.append(f"Admiral {adm.name} of fleet {a.name} now commands fleet {b.name}.")
    elif adm is not None:
        msgs.append(f"Admiral {adm.name} of fleet {a.name} is awaiting a new assignment: fleet "
                    f"{b.name} already has an admiral.")
    for ld in on_way:
        if ld.status == "transit":
            msgs.append(f"Leader {ld.name}, on the way to fleet {a.name}, goes on to fleet "
                        f"{b.name}.")
        else:
            msgs.append(f"Leader {ld.name}, on the way to fleet {a.name}, is awaiting a new "
                        f"assignment.")
    return msgs


def disband_fleet(ctx, f: Fleet):
    f.alive = False
    for sh in ctx.state.fleet_ships(f.number):
        sh.fleet = None
        sh.order, sh.dx, sh.dy = STAND, sh.x, sh.y

    for ld in ctx.state.leaders.values():
        if ld.alive and ld.fleet == f.number:
            ld.status, ld.fleet, ld.system, ld.transit = "limbo", None, None, 0


@handler("FR")
def _fr(ctx, eid, o):
    f = _own_fleet(ctx, eid, o.fleet)
    lines = [f"Fleet report for {f.name}:"]
    for sh in _fleet_members(ctx, f):
        rx, ry = ctx.rel_xy(eid, sh.x, sh.y)
        lines.append(f"  {sh.number:5d} {sh.stype.name:>14s} {rx:3d} {ry:3d} "
                     f"{sh.posture} {sh.role}")
    return lines


@handler("FS")
def _fs(ctx, eid, o):
    f = _own_fleet(ctx, eid, o.fleet)
    f.speed = None if o.speed == "A" else o.speed


@handler("CFP")
def _cfp(ctx, eid, o):
    f = _own_fleet(ctx, eid, o.fleet)
    f.posture = o.posture
    for sh in _fleet_members(ctx, f):
        if o.posture in ("H", "N", "F"):
            sh.posture = o.posture
        elif o.posture == "AH":
            sh.posture = "H" if sh.stype.attack > 0 else "F"
        elif o.posture == "AN":
            sh.posture = "N" if sh.stype.attack > 0 else "F"


@handler("CFCR")
def _cfcr(ctx, eid, o):
    f = _own_fleet(ctx, eid, o.fleet)
    f.role = o.role
    members = _fleet_members(ctx, f)
    if o.role in ("SC", "MR", "GC", "RD"):
        for sh in members:
            sh.role = o.role
    elif o.role in ("OF", "DF", "PT"):
        for sh in members:
            sh.role = shift_role(sh, o.role, bool(ctx.state.troops_aboard(sh.number)))
    elif o.role == "RO":
        f.ro_gc, f.ro_rd, f.ro_role = o.gc, o.rd, o.other
        tg = tr = 0
        for sh in members:
            if ctx.state.troops_aboard(sh.number):
                sh.role = "RD"
            elif sh.stype.attack > 0:
                if tg < o.gc:
                    sh.role = "GC"
                    tg += sh.stype.attack
                elif tr < o.rd:
                    sh.role = "RD"
                    tr += sh.stype.attack
                else:
                    sh.role = "MR"
            else:
                sh.role = o.other


def _fleet_ships_here(ctx, f):
    return [s for s in _fleet_members(ctx, f) if s.x == f.x and s.y == f.y]


@handler("FL")
def _fl(ctx, eid, o):
    f = _own_fleet(ctx, eid, o.fleet)
    s = ctx.state.system_at(f.x, f.y)
    if s is None:
        raise WhereError(f"Fleet {f.name} isn't at a system.")
    if s.owner != eid:
        raise WhereError(f"Fleet {f.name} is at {s.name}, which isn't yours. Fleets load only "
                         f"at your own systems.")
    ships = [sh for sh in _fleet_ships_here(ctx, f) if ctx.state.free_cargo(sh, o.item) > 0]
    ctx.rng.shuffle(ships)          # "a random transport" (rules:2431)
    have = {"A": s.au, "I": s.iu, "P": s.pop}[o.item]
    what = ITEM_NAMES[o.item]
    if have < o.amount:
        raise OrderError(f"{s.name} has only {have:g} {what} to load.")
    room = sum(ctx.state.free_cargo(sh, o.item) for sh in ships)
    if room < o.amount:
        raise OrderError(f"Fleet {f.name}'s ships here have room for only {room} more {what}.")
    left = o.amount
    for sh in ships:
        if left <= 0:
            break
        part = min(left, ctx.state.free_cargo(sh, o.item))
        _load(ctx, sh, s, o.item, part)
        left -= part


@handler("FU", "FUG")
def _fu(ctx, eid, o):
    f = _own_fleet(ctx, eid, o.fleet)
    s = ctx.state.system_at(f.x, f.y)
    if s is None:
        raise WhereError(f"Fleet {f.name} isn't at a system.")
    attr = {"A": "cargo_au", "I": "cargo_iu", "P": "cargo_pop"}[o.item]
    ships = [sh for sh in _fleet_ships_here(ctx, f) if getattr(sh, attr) > 0]
    ctx.rng.shuffle(ships)
    carried = sum(getattr(sh, attr) for sh in ships)
    if carried < o.amount:
        raise OrderError(f"Fleet {f.name}'s ships here carry only {carried:g} "
                         f"{ITEM_NAMES[o.item]}.")
    msgs, left = [], o.amount
    for sh in ships:
        if left <= 0:
            break
        part = min(left, getattr(sh, attr))
        msgs += unload(ctx, eid, sh, s, o.item, part, o.code == "FUG", fleet=True)
        left -= part
    return msgs


@handler("FLOCT")
def _floct(ctx, eid, o):
    f = _own_fleet(ctx, eid, o.fleet)
    t = _own_ct(ctx, eid, o.ct)
    ships = [sh for sh in _fleet_ships_here(ctx, f)
             if ctx.state.cargo_points_used(sh) < sh.stype.cargo]
    if not ships:
        raise OrderError(f"No ship of fleet {f.name} here has cargo room for a combat troop.")
    load_ct(ctx, eid, ctx.rng.choice(ships), t)


@handler("FLACT")
def _flact(ctx, eid, o):
    f = _own_fleet(ctx, eid, o.fleet)
    t = _own_ct(ctx, eid, o.ct)
    for sh in _fleet_members(ctx, f):
        if t.ship == sh.number:
            if (sh.x, sh.y) != (f.x, f.y):
                raise OrderError(f"Ship {sh.number}, carrying troop {t.number}, isn't with the "
                                 f"main body of fleet {f.name}. Use LACT for that ship.")
            return land_ct(ctx, eid, sh, t)
    raise OrderError(f"Combat troop {t.number} isn't aboard a ship of fleet {f.name}.")


@handler("WTPF")
def _wtpf(ctx, eid, o):
    f = _own_fleet(ctx, eid, o.fleet)
    dest = _own_system(ctx, eid, o.system, "normal")
    _check_warp(ctx, eid, f.x, f.y, dest, f"Fleet {f.name}")
    here = _fleet_ships_here(ctx, f)
    _need_eu(ctx, eid, 10 * len(here), f"Warping the {len(here)} ships of fleet {f.name}")
    msgs = []
    for sh in _fleet_members(ctx, f):
        if sh in here:
            _warp(ctx, eid, sh, dest)
        else:
            msgs.append(f"Warning: ship {sh.number} wasn't with the fleet, so it left fleet "
                        f"{f.name} and is heading to where the fleet was.")
            sh.fleet = None
            sh.dx, sh.dy, sh.order = f.x, f.y, MOVE
    ctx.warps[(eid, "fleet", f.number)] = (ctx.order_index, f.x, f.y, dest.id)
    f.x = f.dx = dest.x
    f.y = f.dy = dest.y
    f.order = STAND
    return msgs


# ---------------------------------------------------------------------------------------------
# system orders
# ---------------------------------------------------------------------------------------------

@handler("NSY")
def _nsy(ctx, eid, o):
    s = _own_system(ctx, eid, o.system)
    if ctx.state.system_named(o.name) is not None:
        raise OrderError(f"The name {o.name} is already taken by a system.")
    s.name = o.name
    remember(ctx.emp(eid), s, ctx.turn, True)


@handler("CSP")
def _csp(ctx, eid, o):
    s = _own_system(ctx, eid, o.system)
    s.csp_au, s.csp_iu, s.csp_eu = o.au, o.iu, o.eu


@handler("CAP")
def _cap(ctx, eid, o):
    s = _own_system(ctx, eid, o.system)
    s.au_mode, s.au_value = "pct", o.amount


@handler("CAPN")
def _capn(ctx, eid, o):
    s = _own_system(ctx, eid, o.system)
    s.au_mode, s.au_value = "num", o.amount


@handler("SISD")
def _sisd(ctx, eid, o):
    s = _own_system(ctx, eid, o.system, "normal")
    ctx.econ[s.id].sisd = o.amount     # sets the DESIRED number (rules:1982)
    ctx.econ[s.id].sisd_owner = eid


@handler("CI")
def _ci(ctx, eid, o):
    s = _own_system(ctx, eid, o.system)
    cost = K.CI_EU_PER_POINT * o.amount
    _need_eu(ctx, eid, cost, f"Counter-intelligence of {o.amount}")
    ctx.ci[s.id] = o.amount + 1
    _spend(ctx, eid, None, 0, cost)


def _plural(name: str) -> str:
    return name if name[-1:] in "sS" else name + "s"


def _build_many(ctx, eid, o, s: System, name: str, plural: str, build_one) -> list:
    """BS / BCU with a count (Dave 2026-11-18, DECISIONS G-19): each unit is built exactly as if
    the order were given `count` times in a row (starport capacity, IU, EU and the cost
    multiplier checked and spent unit by unit).  When one can't be built the order stops there:
    the units already built stand and the result says how many of how many, and why the next
    one failed.  If not even the first can be built, the order fails as a single build would."""
    want = o.count or 1
    numbers: list[int] = []
    msgs: list[str] = []
    for _ in range(want):
        try:
            num, extra = build_one()
        except OrderError as exc:
            if not numbers:
                raise
            ctx.built = len(numbers)
            return msgs + [f"Built {len(numbers)} of {want} {plural} at {s.name}: "
                           f"{', '.join(map(str, numbers))}. The other {want - len(numbers)} "
                           f"{'was' if want - len(numbers) == 1 else 'were'} not built: {exc}"]
        numbers.append(num)
        for m in extra:
            if m not in msgs:
                msgs.append(m)
    ctx.built = want
    if want == 1:
        return msgs + [f"Built {name} {numbers[0]}."]
    return msgs + [f"Built {want} {plural} at {s.name}: {', '.join(map(str, numbers))}."]


@handler("BCU")
def _bcu(ctx, eid, o):
    s = _own_system(ctx, eid, o.system, "nonint")
    tt = TROOP_TYPES[o.type]

    def one():
        _check_build(ctx, s, 0.5)       # 2 CTs per starport class, militia included (rules:443)
        if tt.code == "M":
            militia = sum(1 for t in ctx.state.troops_at(s.id) if t.type == "M" and t.owner == eid)
            if militia >= int(s.pop):
                raise OrderError(f"{s.name} already has {militia} militia, the most its "
                                 f"population of {s.pop:g} can support (one per population "
                                 f"point).")
        elif tt.tech not in ctx.emp(eid).techs:
            raise OrderError(f"You need {TECHS[tt.tech].name} (tech {tt.tech}) to build "
                             f"{tt.name} troops.")
        m = ctx.cost_mult(s)
        _need_iu(s, tt.iu_cost * m)
        _pay_eu(ctx, eid, tt.eu_cost * m)
        extra = []
        posture = o.posture or "A"
        if posture == "E":
            if tt.infantry:
                posture = "E3"
            else:
                extra.append(f"Warning: {tt.name} troops aren't infantry and can't entrench, so "
                             f"the troop was given the attack posture.")
                posture = "A"
        t = create_troop(ctx, eid, tt.code, sys_id=s.id, posture=posture)
        _spend(ctx, eid, s, tt.iu_cost * m, tt.eu_cost * m)
        ctx.builds[s.id] += 0.5
        return t.number, extra

    return _build_many(ctx, eid, o, s, tt.name, f"{tt.name} troops", one)


@handler("BS")
def _bs(ctx, eid, o):
    s = _own_system(ctx, eid, o.system, "nonint")
    st = SHIP_TYPES[o.type]

    def one():
        _check_build(ctx, s, 1)
        if st.tech and st.tech not in ctx.emp(eid).techs:
            raise OrderError(f"You need {TECHS[st.tech].name} (tech {st.tech}) to build a "
                             f"{st.name}.")
        m = ctx.cost_mult(s)
        _need_iu(s, st.iu_cost * m)
        _pay_eu(ctx, eid, st.eu_cost * m)
        sh = create_ship(ctx, eid, st.code, s, o.posture or "N", o.role or "SC")
        _spend(ctx, eid, s, st.iu_cost * m, st.eu_cost * m)
        ctx.builds[s.id] += 1
        return sh.number, []

    return _build_many(ctx, eid, o, s, st.name, _plural(st.name), one)


@handler("BI")
def _bi(ctx, eid, o):
    s = _own_system(ctx, eid, o.system, "normal")
    cost = o.amount * K.INFRA_IU_COST
    _need_iu(s, cost)
    _spend(ctx, eid, s, cost, 0)
    s.infra += o.amount


@handler("DI")
def _di(ctx, eid, o):
    s = _own_system(ctx, eid, o.system, "normal")
    if o.amount > s.infra:
        raise OrderError(f"{s.name} has only {s.infra} infrastructure to destroy.")
    cost = o.amount * K.DI_COST_EU
    _need_eu(ctx, eid, cost, f"Destroying {o.amount} infrastructure")
    s.infra -= o.amount
    _spend(ctx, eid, None, 0, cost)


def check_artifact_install(ctx, eid, s: System, art) -> None:
    """Raise OrderError unless `BT <s> <art>` would install the artifact now (the system's
    status is checked by the caller).  The BT order and the production preview's "tech
    available" flag both use it."""
    m = ctx.cost_mult(s)
    if art.tech not in ctx.emp(eid).techs:
        raise OrderError(f"You need {TECHS[art.tech].name} (tech {art.tech}) to build the "
                         f"{art.name}.")
    _need_iu(s, art.iu_cost * m)
    _pay_eu(ctx, eid, art.eu_cost * m)
    if s.has(art.key):
        raise OrderError(f"{s.name} already has the {art.name}.")
    if art.key == "EESS" and not s.has("ESS"):
        raise OrderError(f"The {art.name} can only be built where there is already the "
                         f"{ARTIFACTS['ESS'].name}, and {s.name} has none.")


@handler("BT")
def _bt(ctx, eid, o):
    s = _own_system(ctx, eid, o.system, "nonint")
    m = ctx.cost_mult(s)
    e = ctx.emp(eid)
    if o.artifact == SPY_KEY:
        if 14 not in e.techs:
            raise OrderError(f"You need {TECHS[14].name} (tech 14) to create spies.")
        _need_iu(s, SPY_IU_COST * m)
        _pay_eu(ctx, eid, SPY_EU_COST * m)
        sp = create_spy(ctx, eid, s)
        _spend(ctx, eid, s, SPY_IU_COST * m, SPY_EU_COST * m)
        return [f"Created spy {sp.number}."]
    art = ARTIFACTS[o.artifact]
    check_artifact_install(ctx, eid, s, art)
    s.artifacts.add(art.key)
    _spend(ctx, eid, s, art.iu_cost * m, art.eu_cost * m)


@handler("DT")
def _dt(ctx, eid, o):
    s = _own_system(ctx, eid, o.system, "normal")
    if not s.has(o.artifact):
        raise OrderError(f"{s.name} has no {ARTIFACTS[o.artifact].name} to destroy.")
    s.artifacts.discard(o.artifact)


@handler("BSP")
def _bsp(ctx, eid, o):
    s = _own_system(ctx, eid, o.system, "nonint")
    if s.id in ctx.starport_changed:
        raise OrderError(f"The starport at {s.name} was already built or reduced this turn; "
                         f"that can happen once a turn.")
    if ctx.builds[s.id] > 0:
        raise OrderError(f"The starport at {s.name} has already built or salvaged something "
                         f"this turn, so it can't be upgraded until next turn.")
    cost = K.starport_cost(s.starport + 1) - K.starport_cost(s.starport)
    _need_iu(s, cost)
    _pay_eu(ctx, eid, cost)
    _spend(ctx, eid, s, cost, cost)
    s.starport += 1
    ctx.starport_changed.add(s.id)


@handler("DSP")
def _dsp(ctx, eid, o):
    s = _own_system(ctx, eid, o.system, "normal")
    _need_eu(ctx, eid, K.DSP_COST_EU, "Reducing a starport")
    if s.starport <= 0:
        raise OrderError(f"{s.name} has no starport to reduce.")
    if s.id in ctx.starport_changed:
        raise OrderError(f"The starport at {s.name} was already built or reduced this turn; "
                         f"that can happen once a turn.")
    s.starport -= 1
    _spend(ctx, eid, None, 0, K.DSP_COST_EU)
    ctx.starport_changed.add(s.id)


@handler("TP")
def _tp(ctx, eid, o):
    src = _own_system(ctx, eid, o.system)
    if not src.has("FP"):
        raise OrderError(f"{src.name} has no farcaster to send from.")
    if src.status != K.NORMAL:
        raise _status_error(src, "its farcaster can't send anything")
    dst = _own_system(ctx, eid, o.to)
    if not dst.has("FP"):
        raise OrderError(f"{dst.name} has no farcaster to receive at.")
    if dst.status != K.NORMAL:
        raise _status_error(dst, "its farcaster can't receive anything")
    if o.item in ("A", "I"):
        attr = "au" if o.item == "A" else "iu"
        if getattr(src, attr) < o.amount:
            raise OrderError(f"{src.name} has only {getattr(src, attr)} "
                             f"{ITEM_NAMES[o.item]} to send.")
        cost = 5 * ((o.amount + 19) // 20)
        _need_eu(ctx, eid, cost, f"Farcasting {o.amount} {ITEM_NAMES[o.item]}")
        setattr(src, attr, getattr(src, attr) - o.amount)
        setattr(dst, attr, getattr(dst, attr) + o.amount)
        _spend(ctx, eid, None, 0, cost)
        return
    t = ctx.state.troops.get(o.amount)
    if t is None or not t.alive or t.owner != eid:
        raise OrderError(f"Combat troop {o.amount} doesn't exist or isn't yours.")
    if t.system != src.id:
        raise OrderError(f"Combat troop {t.number} isn't on {src.name}.")
    _need_eu(ctx, eid, 5, "Farcasting a combat troop")
    ctx.farcast[(eid, t.number)] = (ctx.order_index, src.id, dst.id)
    t.system = dst.id
    _spend(ctx, eid, None, 0, 5)


@handler("SR")
def _sr(ctx, eid, o):
    s = _own_system(ctx, eid, o.system, "normal")
    if s.pop > 1.0:
        raise OrderError(f"{s.name} has {s.pop:g} population; only a system with 1 or less "
                         f"can be released.")
    # Released systems are emptied exactly as a depopulated one is (Dave 2026-11-14, DECISIONS G-13):
    # otherwise SR handed a partner the stockpiles, infrastructure, starport and artifacts intact.
    from .turn import empty_system
    empty_system(s)
    s.trade_routes.clear()
    ctx.emp(eid).systems_captured -= s.hab
    s.owner = 0


@handler("SSI")
def _ssi(ctx, eid, o):
    them = _race(ctx, eid, o.race)
    if ctx.at_war(eid, them.id):
        raise OrderError(f"You are at war with the {them.name}, so you can't send them system "
                         f"information.")
    s = _own_system(ctx, eid, o.system)
    ctx.ssi.append((s.id, them.id))


# ---------------------------------------------------------------------------------------------
# troops
# ---------------------------------------------------------------------------------------------

@handler("DCT")
def _dct(ctx, eid, o):
    _own_ct(ctx, eid, o.ct).alive = False


@handler("SCT")
def _sct(ctx, eid, o):
    t = _own_ct(ctx, eid, o.ct)
    if t.system is None:
        where = f"aboard ship {t.ship}" if t.ship is not None else "in transit"
        raise OrderError(f"Combat troop {t.number} is {where}. Troops can only be salvaged on "
                         f"the ground at one of your systems.")
    s = ctx.state.systems[t.system]
    if s.owner != eid:
        raise OrderError(f"Combat troop {t.number} is on {s.name}, which isn't yours. Troops "
                         f"can only be salvaged at your own systems.")
    if s.status != K.NORMAL:
        raise _status_error(s, "troops can't be salvaged there")
    _check_build(ctx, s, 1)          # NPRs too (DECISIONS A-01)
    ctx.builds[s.id] += 1
    tt = t.ttype
    _refund(ctx, eid, s, int(tt.iu_cost * K.SCT_REFUND), int(tt.eu_cost * K.SCT_REFUND))
    t.alive = False


@handler("CCP")
def _ccp(ctx, eid, o):
    t = _own_ct(ctx, eid, o.ct)
    if o.posture == "E":
        if not t.ttype.infantry:
            raise OrderError(f"Combat troop {t.number} ({t.ttype.name}) isn't infantry, so it "
                             f"can't entrench.")
        if t.posture in ("E", "E1", "E2", "E3"):
            return [f"Combat troop {t.number} is already entrenched or entrenching; nothing "
                    f"changed."]
        t.posture = "E3"
    else:
        t.posture = o.posture


# ---------------------------------------------------------------------------------------------
# leaders
# ---------------------------------------------------------------------------------------------

@handler("CLN")
def _cln(ctx, eid, o):
    ld = _own_leader(ctx, eid, o.leader)
    if ld.renamed:
        raise OrderError(f"You have already renamed {ld.name}; a leader can be renamed only "
                         f"once.")
    if ctx.state.leader_named(o.name) is not None:
        raise OrderError(f"The name {o.name} is already taken by a leader.")
    ld.name, ld.renamed = o.name, True


@handler("ML")
def _ml(ctx, eid, o):
    ld = _own_leader(ctx, eid, o.leader)
    s = _own_system(ctx, eid, o.system)
    ld.status, ld.system, ld.fleet, ld.transit = "transit", s.id, None, K.LEADER_MOVE_TURNS


@handler("MLF")
def _mlf(ctx, eid, o):
    ld = _own_leader(ctx, eid, o.leader)
    f = _own_fleet(ctx, eid, o.fleet)
    ld.status, ld.system, ld.fleet, ld.transit = "transit", None, f.number, K.LEADER_MOVE_TURNS


@handler("PLOI")
def _ploi(ctx, eid, o):
    ld = _own_leader(ctx, eid, o.leader)
    ld.status, ld.system, ld.fleet, ld.transit = "ice", None, None, K.LEADER_ICE_TURNS


@handler("LR")
def _lr(ctx, eid, o):
    out = ["Leader report:", " Name          Mgt Eng Cmb Int Soc Age  Status"]
    for ld in ctx.state.leaders.values():
        if ld.alive and ld.owner == eid:
            where = ""
            if ld.system is not None:
                where = ctx.state.systems[ld.system].name
            elif ld.fleet is not None and ld.fleet in ctx.state.fleets:
                where = "fleet " + ctx.state.fleets[ld.fleet].name
            out.append(f" {ld.name:13s} {ld.mgmt:3d} {ld.eng:3d} {ld.combat:3d} {ld.intel:3d} "
                       f"{ld.social:3d} {ld.age:3d}  {ld.status} {where}")
    return out


# ---------------------------------------------------------------------------------------------
# spies
# ---------------------------------------------------------------------------------------------

def _spy_here(ctx, eid, number) -> Spy:
    sp = _own_spy(ctx, eid, number)
    if sp.transit:
        raise OrderError(f"Spy {sp.number} is still travelling; give it a mission once it "
                         f"arrives.")
    return sp


def _spy_move(ctx, eid, sp: Spy, s: System):
    here = ctx.state.systems[sp.system]
    d = G.distance(here.x, here.y, s.x, s.y, ctx.state.board)
    sp.transit = max(1, int(d / K.SPY_MOVE_DIVISOR + 0.5))
    sp.system = s.id
    sp.mission, sp.mission_arg = "SMV", None


@handler("SMV")
def _smv(ctx, eid, o):
    sp = _own_spy(ctx, eid, o.spy)
    if sp.transit:
        raise OrderError(f"Spy {sp.number} is already travelling.")
    s = _known_system(ctx, eid, o.system)
    if s.owner not in (0, eid) and not ctx.emp(eid).has_contact(s.owner):
        raise OrderError(f"You haven't made contact with the race that owns {s.name}, so your "
                         f"spy can't go there.")
    _spy_move(ctx, eid, sp, s)


@handler("SMO")
def _smo(ctx, eid, o):
    sp = _own_spy(ctx, eid, o.spy)
    if sp.transit:
        raise OrderError(f"Spy {sp.number} is already travelling.")
    x, y = ctx.abs_xy(eid, o.x, o.y)
    s = ctx.state.system_at(x, y)
    if s is None or (s.owner not in (0, eid) and not ctx.emp(eid).has_contact(s.owner)):
        # Silently loses a turn: "appears to execute" (rules:2760-2764).
        sp.mission, sp.transit = "SMO_FAIL", 1
        return
    _spy_move(ctx, eid, sp, s)


@handler("SET")
def _set(ctx, eid, o):
    sp = _spy_here(ctx, eid, o.spy)
    e = ctx.state.empire_named(o.race)
    if e is None:
        raise OrderError(f"There is no race called {o.race}.")
    sp.mission, sp.mission_arg = "SET", e.id


@handler("SRS")
def _srs(ctx, eid, o):
    _own_spy(ctx, eid, o.spy).alive = False


@handler("SOS", "SOT", "SOL", "SVS", "SOE", "SOM", "SON", "SAL", "SSB", "SUP")
def _spy_mission(ctx, eid, o):
    sp = _spy_here(ctx, eid, o.spy)
    if o.code in ("SOL", "SAL") and ctx.state.governor(sp.system) is None:
        raise OrderError(f"There is no leader on {ctx.state.systems[sp.system].name} to "
                         + ("spy on." if o.code == "SOL" else "assassinate."))
    sp.mission, sp.mission_arg = o.code, None
    if o.code == "SUP" and not ctx.checking:
        # Uprising unrest takes effect this turn (rules:1989-1990; DECISIONS F-11).
        succ = K.SPY_ODDS["SUP"][0] / ctx.ci[sp.system]
        if ctx.rng.chance(succ):
            ctx.spy_unrest[sp.system] += 1
            sp.mission_arg = 1
        else:
            sp.mission_arg = 0


# ---------------------------------------------------------------------------------------------
# empire / diplomacy
# ---------------------------------------------------------------------------------------------

@handler("DA")
def _da(ctx, eid, o):
    them = _race(ctx, eid, o.race)
    mine = ctx.emp(eid).relations[them.id]
    if mine == "A":
        raise OrderError(f"You are already allied with the {them.name}.")
    if mine in ("W", "E"):
        raise OrderError(f"You are at war with the {them.name}. End the war first (EWA; both "
                         f"sides must offer peace).")
    ctx.emp(eid).relations[them.id] = "A"


@handler("DW")
def _dw(ctx, eid, o):
    them = _race(ctx, eid, o.race)
    if ctx.emp(eid).relations[them.id] in ("W", "E"):
        raise OrderError(f"You are already at war with the {them.name}.")
    ctx.emp(eid).relations[them.id] = "W"
    them.relations[eid] = "W"


@handler("EWA")
def _ewa(ctx, eid, o):
    them = _race(ctx, eid, o.race)
    me = ctx.emp(eid)
    mine, theirs = me.relations[them.id], them.relations.get(eid, "N")
    if mine == "N":
        raise OrderError(f"You are neither at war nor allied with the {them.name}.")
    if mine == "A":
        me.relations[them.id] = "N"
        return [f"You have ended your alliance with the {them.name}; you are now neutral."]
    if mine == "W":
        if theirs == "E":
            me.relations[them.id] = "N"
            them.relations[eid] = "N"
            return [f"The war with the {them.name} is over."]
        me.relations[them.id] = "E"
        return [f"You offer the {them.name} peace. The war ends when they offer it too."]
    raise OrderError(f"You have already offered the {them.name} peace; the war ends when they "
                     f"offer it too.")


@handler("GE")
def _ge(ctx, eid, o):
    them = _race(ctx, eid, o.race)
    me = ctx.emp(eid)
    if me.eu < o.amount:
        raise OrderError(f"You have only {me.eu} EU, so you can't gift {o.amount} to the "
                         f"{them.name}.")
    _gift_out(ctx, eid, o.amount)
    them.eu += o.amount
    ctx.gift_in_eu[them.id] += o.amount
    if not ctx.checking:
        late = them.id in ctx.orders_done
        ctx.res.emit(them.id, "eu_received",
                     f"You have received a gracious gift of {o.amount} EUs from the {me.name} "
                     f"empire" + (" (unfortunately, it arrived too late for you to use this "
                                  "turn)" if late else ""), "orders", amount=o.amount, race=eid,
                     late=late)


def gift_tech(ctx, giver: int, them_id: int, t: int) -> list:
    """GT checks in C order (gcparse1.c:198-281)."""
    me, them = ctx.emp(giver), ctx.emp(them_id)
    if t not in TECHS or t == 0:
        raise OrderError(f"There is no technology {t} to gift.")
    if t == FUTURE_TECH:
        raise OrderError("Future Technology can't be gifted or traded.")
    tech = TECHS[t]
    _need_eu(ctx, giver, tech.cost // 2, f"Gifting {tech.name} (half its price)")
    if t not in me.techs:
        raise OrderError(f"You don't own {tech.name} (tech {t}).")
    if t in them.techs:
        raise OrderError(f"The {them.name} already own {tech.name}.")
    miss = missing_prereqs(them.techs, t)
    if miss:
        raise OrderError(f"The {them.name} can't receive {tech.name}: they lack its "
                         f"prerequisite {TECHS[miss[0]].name} (tech {miss[0]}).")
    if giver in ctx.gt_done:
        raise OrderError("You have already gifted a tech this turn; that's one a turn.")
    if them_id in ctx.pt_done:
        raise OrderError(f"The {them.name} have already bought or received a tech this turn. "
                         f"Try again next turn.")
    _gift_out(ctx, giver, tech.cost // 2)
    them.techs.add(t)
    ctx.gt_done.add(giver)
    ctx.pt_done.add(them_id)
    ctx.gift_why[giver] = f"you gifted {tech.name} to the {them.name} (GT)"
    ctx.tech_why[them_id] = f"the {me.name} gave you {tech.name}"
    if not ctx.checking:
        late = them_id in ctx.orders_done
        ctx.res.emit(them_id, "tech_received",
                     f"You have received a gift of {tech.name} from the gracious {me.name} "
                     f"empire" + (" (unfortunately, it arrived too late for you to use this "
                                  "turn)" if late else ""), "orders", tech=t, race=giver)
    return [f"You have graciously provided a gift of {tech.name} to the {them.name} empire"]


@handler("GT")
def _gt(ctx, eid, o):
    them = _race(ctx, eid, o.race)
    return gift_tech(ctx, eid, them.id, o.tech)


def _slot_used(ctx, eid: int, what: str) -> str:
    """Why `eid` can't take another tech this turn, naming what used the slot (Dave 2026-11-16)."""
    why = ctx.tech_why.get(eid) or ctx.gift_why.get(eid)
    used = f"{why} earlier this turn" if why else "you already bought, gifted or received a tech this turn"
    return (f"You can't {what}: {used}. Only one tech a turn comes by purchase (PT), gift (GT) or "
            f"trade (TTNPR); crash research (CRP) doesn't count, so buying with CRP instead "
            f"leaves room for a trade.")


@handler("TTNPR")
def _ttnpr(ctx, eid, o):
    """Tech-for-tech swap with an NPR (rules:2532-2541: "equivalent to each of you doing a Gift
    Tech").  Acceptance odds adapt the C formula (gcparse1.c:347) with the offered tech's cost
    standing in for the EUs offered.  DECISIONS C-07.  Either side may be "ANY <cost>" (Dave
    2026-11-19, DECISIONS G-23): the computer empire picks a tech of exactly that cost when the
    turn runs (`_any_picks`); Check orders doesn't pick, so it reveals nothing of its techs."""
    if eid in ctx.npr_trade_done:
        raise OrderError("You have already tried a tech trade with a computer empire this "
                         "turn; that's one attempt a turn.")
    npr = _race(ctx, eid, o.race)
    if npr.kind != NPR:
        raise OrderError(f"The {npr.name} aren't a computer empire. TTNPR trades only with "
                         f"computer empires; use GT to gift a tech to a player.")
    me = ctx.emp(eid)
    give_any = getattr(o, "give_any_cost", None)
    want_any = getattr(o, "want_any_cost", None)
    from ..orders import any_costs
    for c, label in ((give_any, "offered"), (want_any, "asked for")):
        if c is not None and c not in any_costs():
            raise OrderError(f"No technology costs exactly {c} EU, so the ANY {c} {label} can't "
                             f"match one.")
    for t, label in ((o.give, "offered"), (o.want, "asked for")):
        if t is not None and (t not in TECHS or t in (0, FUTURE_TECH)):
            raise OrderError(f"The tech {label} ({t}) isn't one that can be traded.")
    # Check orders with an ANY side checks only what the player can know (their own techs and
    # money, contact, war, the one-tech slot), so it says nothing of the computer empire's
    # techs or money either way (G-23)
    blind = ctx.checking and (give_any is not None or want_any is not None)
    if o.want is not None and not blind and o.want not in npr.techs:
        raise OrderError("We don't have that tech!")
    if o.give is not None and o.give not in me.techs:
        raise OrderError(f"You don't own {TECHS[o.give].name} (tech {o.give}), so you can't "
                         f"offer it.")
    if give_any is not None and not any(_any_ok(t, give_any) for t in me.techs):
        raise OrderError(f"You own no {give_any} EU tech to offer.")
    if ctx.at_war(npr.id, eid):
        raise OrderError("We are at war with you you fool!")
    if npr.id in ctx.gt_done and not blind:
        raise OrderError("Sorry, we already traded this turn.  Try again, though!")
    if o.give is not None and not blind and o.give in npr.techs:
        raise OrderError("We already have that tech!")
    cg = TECHS[o.give].cost if o.give is not None else give_any
    cw = TECHS[o.want].cost if o.want is not None else want_any
    if blind:
        if me.eu < cg // 2:
            raise OrderError(f"You have only {me.eu} EU; your half of the trade is {cg // 2}.")
    elif me.eu < cg // 2 or npr.eu < cw // 2:
        raise OrderError("Sorry, we don't have the money this turn.  Try again, though!")
    for receiver, t in ((npr, o.give), (me, o.want)):
        if blind and receiver is npr:
            continue
        miss = missing_prereqs(receiver.techs, t) if t is not None else None
        if miss:
            raise OrderError(f"Sorry, our trade failed... missing the prerequisite tech "
                             f"{TECHS[miss[0]].name}")
    if eid in ctx.pt_done or eid in ctx.gt_done:
        raise OrderError(_slot_used(ctx, eid, "trade for a tech"))
    acceptance = (100 * (2 * cg - cw)) // cw
    if blind:
        ctx.npr_trade_done.add(eid)            # as a valid offer would (the likely case)
        return _any_check_lines(ctx, npr, eid, o, acceptance)
    # ANY sides: the computer empire picks now.  No eligible tech is a failed check, not a
    # refusal, so the turn's attempt isn't used (G-17, G-23).
    give, want = _any_picks(ctx, npr, me, o)
    # A refused offer uses the turn's one attempt (rules); an invalid one doesn't (Dave 2026-11-16).
    ctx.npr_trade_done.add(eid)
    # the computer empire offered exactly this swap in chat (npr/trade.py, DECISIONS A-08):
    # it keeps its word, whatever the roll would say.  Unsolicited offers roll as before.
    offered = _npr_offered(ctx, npr.id, eid, give, want)
    if ctx.checking:
        if offered:
            return [f"The {npr.name} offered this trade, so they will accept."]
        return [f"Acceptance chance about {max(0, min(100, acceptance + 1))}%."]
    picked = give_any is not None or want_any is not None
    roll = ctx.rng.pct()
    if roll > acceptance and not offered:
        ctx.res.emit(npr.id, "trade_offered", f"The {me.name} offered us {TECHS[give].name} "
                     f"for our {TECHS[want].name}; we refused.", "orders", race=eid,
                     give=give, want=want, ok=False)
        # (with ANY sides the picks aren't named: no trade, so nothing of theirs is shown)
        return [f"Sorry, we have better offers [{acceptance} chance, {roll} roll]!"]
    ctx.res.emit(npr.id, "trade_offered", f"The {me.name} traded us {TECHS[give].name} for "
                 f"our {TECHS[want].name}.", "orders", race=eid, give=give, want=want,
                 ok=True)
    _gift_out(ctx, eid, cg // 2)
    _gift_out(ctx, npr.id, cw // 2)
    me.techs.add(want)
    npr.techs.add(give)
    ctx.gt_done.update((eid, npr.id))
    ctx.pt_done.update((eid, npr.id))
    ctx.tech_why[eid] = f"you traded with the {npr.name} for {TECHS[want].name} (TTNPR)"
    ctx.tech_why[npr.id] = f"you traded with the {me.name} for {TECHS[give].name}"
    gave = (f": you gave {TECHS[give].name} ({cg}) and received {TECHS[want].name} ({cw})"
            if picked else "")
    if offered:
        if picked:
            return [f"The {npr.name} accept the trade they offered you{gave}."]
        return [f"{npr.name} accepts the trade they offered you: {TECHS[give].name} for "
                f"{TECHS[want].name}."]
    if picked:
        return [f"The {npr.name} accept{gave}. [{acceptance} / {roll}]"]
    return [f"{npr.name} accepts your generous offer for a tech trade! [{acceptance} / {roll}]"]


def _any_ok(t: int, cost: int) -> bool:
    return t in TECHS and t not in (0, FUTURE_TECH) and TECHS[t].cost == cost


def _any_check_lines(ctx, npr, eid: int, o, acceptance: int) -> list:
    """Check orders for a TTNPR with an ANY side: the picks are made when the turn runs."""
    from ..npr.trade import open_offer_to
    parts = []
    if o.give is None:
        parts.append(f"one of your {o.give_any_cost} EU techs that they lack and could use "
                     f"(what you give)")
    if o.want is None:
        parts.append(f"one of their {o.want_any_cost} EU techs that you lack and could use "
                     f"(what you get)")
    lines = [f"When the turn runs, the {npr.name} will pick {' and '.join(parts)}. If there is "
             f"none, the trade fails without using this turn's attempt."]
    mem = ctx.state.npr_state.get(npr.id) or {}
    off = open_offer_to(mem, eid, ctx.state.turn)
    if off is not None and o.want == off["give"] and o.give is None \
            and off.get("any") == o.give_any_cost:
        lines.append(f"The {npr.name} offered this trade, so they will accept.")
    else:
        lines.append(f"Acceptance chance about {max(0, min(100, acceptance + 1))}%.")
    return lines


def _any_picks(ctx, npr, me, o) -> tuple[int, int]:
    """Resolve the ANY sides of a TTNPR (DECISIONS G-23), as the computer empire would: for
    "want ANY X" it gives the X EU tech the player lacks and can use (prerequisites owned) that
    it values least; for "give ANY X" it takes the player's X EU tech it lacks and can use that
    it values most, preferring one it said it would take in an open chat offer (A-08)."""
    from ..npr.memory import new_memory
    from ..npr.trade import any_pick, open_offer_to
    st = ctx.state
    mem = st.npr_state.get(npr.id) or {}
    if "persona" not in mem:                       # an empire the bot never ran: seeded persona
        mem = dict(mem, persona=new_memory(st.seed, npr.id, st.turn)["persona"])
    want = o.want
    if want is None:
        c = o.want_any_cost
        want = any_pick(mem, npr.techs, st.turn,
                        [t for t in npr.techs if _any_ok(t, c) and t not in me.techs
                         and not missing_prereqs(me.techs, t)], most=False)
        if want is None:
            raise OrderError(f"The {npr.name} have no {c} EU tech you lack and could use.")
    give = o.give
    if give is None:
        c = o.give_any_cost
        cands = [t for t in me.techs if _any_ok(t, c) and t not in npr.techs
                 and not missing_prereqs(npr.techs, t)]
        if not cands:
            raise OrderError(f"You have no {c} EU tech the {npr.name} lack and could use.")
        off = open_offer_to(mem, me.id, st.turn)
        if off is not None and off["give"] == want:
            cands = [t for t in cands if t in off["wants"]] or cands
        give = any_pick(mem, npr.techs, st.turn, cands, most=True)
    return give, want


def _npr_offered(ctx, npr_id: int, eid: int, give: int, want: int) -> bool:
    """Did this computer empire offer `eid` exactly this swap (its own memory says so)?"""
    from ..npr.trade import offer_open
    mem = ctx.state.npr_state.get(npr_id)
    return bool(mem) and offer_open(mem, eid, give, want, ctx.state.turn)


def _buy_tech(ctx, eid, t: int, crash: bool) -> list:
    e = ctx.emp(eid)
    if t not in TECHS or t == 0:
        raise OrderError(f"There is no technology {t} to buy.")
    if not crash and eid in ctx.pt_done:
        raise OrderError(_slot_used(ctx, eid, "buy another tech with PT"))
    if t == FUTURE_TECH and eid in ctx.ft_done:
        raise OrderError("You can buy only one Future Technology a turn.")
    if t != FUTURE_TECH and t in e.techs:
        raise OrderError(f"You already own {TECHS[t].name}.")
    tech = TECHS[t]
    cost = tech.cost * (2 if crash else 1)
    _need_eu(ctx, eid, cost, f"{tech.name}" + (" by crash research" if crash else ""))
    miss = missing_prereqs(e.techs, t)
    if miss:
        raise OrderError(f"{tech.name} needs {TECHS[miss[0]].name} (tech {miss[0]}) first.")
    _spend(ctx, eid, None, 0, cost)  # no NPR discount (DECISIONS A-01)
    if t == FUTURE_TECH:
        e.future_tech += 1
        ctx.ft_done.add(eid)
    else:
        e.techs.add(t)
    if not crash:
        ctx.pt_done.add(eid)
        ctx.tech_why[eid] = f"you bought {tech.name} (PT)"
    return [("Crash research bought " if crash else "Bought ") + tech.name + "."]


@handler("PT")
def _pt(ctx, eid, o):
    return _buy_tech(ctx, eid, o.tech, False)


@handler("CRP")
def _crp(ctx, eid, o):
    return _buy_tech(ctx, eid, o.tech, True)


@handler("DD")
def _dd(ctx, eid, o):
    them = _race(ctx, eid, o.race)
    ctx.emp(eid).deny_trade[them.id] = o.amount
    return [f"The {them.name} now get {o.amount}% of their normal trade EUs from your "
            f"systems."]


@handler("SD")
def _sd(ctx, eid, o):
    them = _race(ctx, eid, o.race)
    ctx.emp(eid).split_trade[them.id] = o.amount
    return [f"The {them.name} now pass {o.amount}% of their trade EUs from your systems back "
            f"to you."]


@handler("AUTOSISD", "NOAUTOSISD")
def _autosisd(ctx, eid, o):
    ctx.emp(eid).autosisd = o.code == "AUTOSISD"
    return ["Automatic supply depot resupply is on." if o.code == "AUTOSISD" else
            "Automatic supply depot resupply is off."]


@handler("AOMT")
def _aomt(ctx, eid, o):
    """A race setting (DECISIONS W-29); the server also applies it as soon as a draft holding it
    is saved, so it covers this turn already."""
    e = ctx.emp(eid)
    if e.kind != HUMAN:
        raise OrderError("AOMT is for races played by a person.")
    e.aomt = o.mode == "ON"
    return ["AOMT is on: if the host forces a turn before you have submitted, your draft runs as "
            "if submitted, or with an empty draft the computer writes your orders for it from "
            "your own view." if e.aomt else
            "AOMT is off: a turn forced before you submit runs with no orders from you."]


@handler("LT")
def _lt(ctx, eid, o):
    e = ctx.emp(eid)
    lines = ["Technologies you own:"] + [f"  {t:2d} {TECHS[t].name}" for t in sorted(e.techs)
                                         if t]
    if e.future_tech:
        lines.append(f"  51 Future Technology x{e.future_tech}")
    return lines


@handler("CRN")
def _crn(ctx, eid, o):
    e = ctx.emp(eid)
    if e.renamed:
        raise OrderError("You have already renamed your race; that can be done only once.")
    if ctx.state.empire_named(o.name) is not None:
        raise OrderError(f"The race name {o.name} is already taken.")
    e.name, e.renamed = o.name, True
    return [f"Your race is now called the {o.name}."]


@handler("RESIGN")
def _resign(ctx, eid, o):
    e = ctx.emp(eid)
    e.kind = NPR
    autobuff(ctx, eid)
    return ["You have resigned. Your empire is now run by the computer."]


def autobuff(ctx, eid):
    """Dropped players are "buffed up significantly" (rules:259-261; gcnprutils.c:2260)."""
    for s in ctx.state.systems:
        if s.owner == eid and s.status == K.NORMAL:
            s.starport += 1
            if s.iu < 150:
                s.iu += 150


@handler("ECHO")
def _echo(ctx, eid, o):
    return [o.text or ""]


@handler("MESSAGE")
def _message(ctx, eid, o):
    rec, msgs = [], []
    for name in o.recipients:
        e = ctx.state.empire_named(name)
        if e is None:
            msgs.append(f"Warning: there is no race called {name}, so no message went to it.")
        else:
            rec.append(e.id)
    if o.recipients and not rec:
        raise OrderError("None of the recipients is a known race, so the message wasn't "
                         "sent.")
    ctx.messages.append((eid, rec or None, o.text))
    return msgs


# ---------------------------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------------------------

def execute(ctx: TurnContext, eid: int, order: Order, index: int) -> OrderResult:
    r = OrderResult(index, order.line or order.to_text(), order.code)
    r.messages.extend(order.warnings)
    fn = HANDLERS.get(order.code)
    if fn is None:
        r.ok, r.error = False, f"Unknown order code {order.code}."
        return r
    ctx.built = None
    ctx.order_index = index
    try:
        out = fn(ctx, eid, order)
        if out:
            r.messages.extend(out)
        r.built = ctx.built
    except OrderError as exc:
        # a cargo order that fails because of where the unit is: say where it is, where it is
        # going, or which warp moved it (engine/advice.py, DECISIONS G-20)
        r.ok, r.error = False, cargo_error(ctx, eid, order, index, exc)
    return r
