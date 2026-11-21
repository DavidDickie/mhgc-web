"""The turn driver.  Phases in the rules' order (rules:169-193):

 (1) orders, empire by empire in a random order, each empire's orders in sequence
 (2) produce  (3) feed, happiness, rebellion  (4) grow  (5) maintenance
 (6) move, intercept, guard  (7) combat drops  (8) combat  (9) spies
 (10) random events (incl. leaders)  (11) scans
 then statistics, victory points and the victory check.

`run_turn` mutates the state and returns the structured TurnResults.  It is deterministic for a
given state, orders and game seed.
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional

from ..model import DEAD, END_WAR, HUMAN, NPR, GameState, from_dict, to_dict
from ..orders import Order
from ..results import TurnResults
from ..rng import Rng
from . import combat, economy, events, maintenance, movement, scans, spies, stats
from .context import TurnContext
from .orders_exec import disband_fleet, execute

NprOrderFn = Callable[[GameState, int], list]


def _default_npr(state: GameState, empire: int) -> list:
    from ..npr import npr_orders
    return npr_orders(state, empire)


def new_context(state: GameState, checking=False) -> TurnContext:
    rng = Rng(state.seed, state.turn, "check" if checking else "turn")
    return TurnContext(state=state, rng=rng, res=TurnResults(state.turn), checking=checking)


def run_orders(ctx: TurnContext, orders: dict[int, list[Order]]) -> None:
    st = ctx.state
    order = [e for e in st.empires if st.empires[e].kind in (HUMAN, NPR)]
    ctx.rng.shuffle(order)                        # gcrun.c:149-178 random race order
    ctx.empire_order = order + [e for e in st.empires if e not in order]
    for eid in order:
        # Computer empires play under exactly the human rules: no ISNPR income (DECISIONS A-01).
        for i, o in enumerate(orders.get(eid, [])):
            if st.empires[eid].kind == DEAD:
                break
            ctx.res.report(eid).orders.append(execute(ctx, eid, o, i))
        ctx.orders_done.add(eid)


def deliver_messages(ctx: TurnContext) -> None:
    st = ctx.state
    for sender, rec, text in ctx.messages:
        targets = rec if rec is not None else [e.id for e in st.empires.values()
                                               if e.kind in (HUMAN, NPR) and e.id != sender]
        for t in targets:
            rep = ctx.res.report(t)
            rep.messages.append({"from": sender, "from_name": ctx.name(sender), "text": text,
                                 "broadcast": rec is None})


def empty_system(s) -> None:
    """What a system loses when its people are gone, by dying out (depopulation) or by release (SR):
    population, AU/IU stockpiles, infrastructure, starport and artifacts (DECISIONS D-08, G-13)."""
    s.pop = 0.0
    s.au = s.iu = s.infra = s.starport = 0
    s.artifacts.clear()


def depopulation(ctx: TurnContext, had_pop: set) -> None:
    """gcrun.c:388-418, applied only to systems that actually lost their population (the C wiped
    every empty system every turn, destroying the starting artifact systems; DECISIONS B-43)."""
    st = ctx.state
    for s in st.systems:
        if s.pop < 0.5 and s.id in had_pop:
            empty_system(s)
            if s.owner:
                ctx.res.emit(s.owner, "info", f"{s.name} has lost all its population.", "general",
                             s.id)
        if s.pop <= 0 and s.owner:
            if not any(t.owner == s.owner for t in st.troops_at(s.id)):
                e = st.empires[s.owner]
                e.systems_captured = -s.hab if e.systems_captured > 0 else \
                    e.systems_captured - s.hab
                s.owner = 0
                s.trade_routes.clear()


def disband_empty_fleets(ctx: TurnContext) -> None:
    """End-of-turn fleet cleanup (DECISIONS G-18), after combat, salvage, gifts and every other
    way a ship leaves a fleet: a fleet with none of its owner's ships left is disbanded as a DF
    would (its name is free again; an admiral, or a leader on the way to it, returns to limbo).
    A fleet created this turn (CF or CFXY) that has not held a ship yet is spared for this turn:
    a CF waits for AF orders and a CFXY gathers only at the end of its own turn, so either gets
    the next turn's orders to receive ships; still empty at the end of that turn, it goes too."""
    st = ctx.state
    for f in sorted(st.fleets.values(), key=lambda q: q.number):
        if not f.alive:
            continue
        if any(sh.owner == f.owner for sh in st.fleet_ships(f.number)):
            continue
        if f.number in ctx.new_fleets and f.number not in ctx.filled_fleets:
            ctx.res.emit(f.owner, "fleet_empty", f"Fleet {f.name} has no ships yet. Add ships "
                         f"to it next turn (AF or AFXY), or it will be disbanded at the end of "
                         f"that turn.", "general", fleet=f.name)
            continue
        posted = [(ld, ld.status == "posted") for ld in st.leaders.values()
                  if ld.alive and ld.fleet == f.number and ld.owner == f.owner]
        disband_fleet(ctx, f)
        ctx.res.emit(f.owner, "fleet_disbanded", f"Fleet {f.name} has no ships left and was "
                     f"disbanded.", "general", fleet=f.name)
        for ld, admiral in posted:
            text = (f"Admiral {ld.name} of fleet {f.name} has lost his post" if admiral else
                    f"Leader {ld.name}, on the way to fleet {f.name}, has lost his post")
            ctx.res.emit(f.owner, "leader_evicted", f"{text} and is awaiting a new assignment.",
                         "leaders", leader=ld.id)


def cleanup(state: GameState) -> None:
    state.ships = {k: v for k, v in state.ships.items() if v.alive}
    state.troops = {k: v for k, v in state.troops.items() if v.alive}
    state.spies = {k: v for k, v in state.spies.items() if v.alive}
    state.leaders = {k: v for k, v in state.leaders.items() if v.alive}
    state.fleets = {k: v for k, v in state.fleets.items() if v.alive}
    for t in state.troops.values():
        if t.ship is not None and t.ship not in state.ships:
            t.alive = False
    state.troops = {k: v for k, v in state.troops.items() if v.alive}


def economy_summary(ctx: TurnContext) -> None:
    for e in ctx.state.empires.values():
        if e.kind not in (HUMAN, NPR):
            continue
        ctx.res.report(e.id).economy = {
            "eu": e.eu, "iu_depot": e.iu_depot,
            "production": {"EU": ctx.eu_prod[e.id] + ctx.trade_eu[e.id],
                           "IU": ctx.iu_prod[e.id], "AU": ctx.au_prod[e.id]},
            "trade_eu": ctx.trade_eu[e.id], "purchases_eu": ctx.purch_eu[e.id],
            "systems": {s.id: {"au": ec.prod_au, "iu": ec.prod_iu, "eu": ec.prod_eu,
                               "eaten": ec.eaten}
                        for s in ctx.state.systems if s.owner == e.id
                        for ec in [ctx.econ[s.id]]},
        }


def run_turn(state: GameState, orders: Optional[dict[int, list[Order]]] = None,
             npr_fn: Optional[NprOrderFn] = _default_npr, aomt: Iterable[int] = (),
             aomt_fn: Optional[NprOrderFn] = None) -> TurnResults:
    """`aomt`: human races that haven't submitted and have AOMT on, on a turn the host forced
    (DECISIONS W-29).  One that has orders in `orders` (the caller passes its unsubmitted draft)
    runs them; for one without, `aomt_fn(state, empire)` writes its orders (app:
    npr.trace.Tracer.aomt), called after the turn number has moved on, as for the computer
    empires.  Either way its report gets an `aomt` event saying which (`source`)."""
    if state.winner is not None:
        raise RuntimeError("the game is over")
    orders = dict(orders or {})
    state.turn += 1
    ctx = new_context(state)
    for sh in state.ships.values():
        sh.ox, sh.oy = sh.x, sh.y
    for f in state.fleets.values():
        f.ox, f.oy = f.x, f.y
    for e in state.empires.values():
        ctx.start_eu[e.id] = e.eu
    if npr_fn is not None:
        for e in state.empires.values():
            if e.kind == NPR and e.id not in orders:
                orders[e.id] = list(npr_fn(state, e.id))
    for eid in sorted(set(aomt)):
        e = state.empires.get(eid)
        if e is None or e.kind != HUMAN:
            continue
        if orders.get(eid):
            # the race's unsubmitted draft, which the caller passes as its orders: the draft wins
            # over the bot (Dave 2026-11-20, W-29)
            ctx.res.emit(eid, "aomt", f"You missed turn {state.turn}; AOMT is on, so your "
                         f"unsubmitted draft was run as if you had submitted it "
                         f"({len(orders[eid])} orders).", "general", orders=len(orders[eid]),
                         source="draft")
            continue
        if aomt_fn is not None:
            orders[eid] = list(aomt_fn(state, eid))
            ctx.res.emit(eid, "aomt", f"You missed turn {state.turn}; your orders were generated "
                         f"automatically (AOMT is on). They are listed with your order results "
                         f"({len(orders[eid])} orders).", "general", orders=len(orders[eid]),
                         source="bot")

    # (1) orders
    run_orders(ctx, orders)
    deliver_messages(ctx)
    for e in state.empires.values():           # gcrun.c:365-367
        for k, v in list(e.relations.items()):
            if v == END_WAR:
                e.relations[k] = "W"
    had_pop = {s.id for s in state.systems if s.pop > 0}
    depopulation(ctx, had_pop)
    # (2)-(4)
    economy.produce(ctx)
    economy.happiness(ctx)
    economy.grow(ctx)
    for e in state.empires.values():
        e.systems_captured = 0                   # gcrun.c:750-751
    # (5)
    maintenance.maintenance(ctx)
    # (6)-(7)
    movement.fleet_cleanup(ctx)
    movement.move_fleets(ctx)
    movement.move_ships(ctx)
    movement.intercept(ctx)
    movement.guard(ctx)
    movement.add_fleet_xy(ctx)
    movement.combat_drops(ctx)
    movement.leader_moves(ctx)
    movement.spy_moves(ctx)
    # (8)
    combat.find_combats(ctx)
    combat.status_decay(ctx)
    # (9)-(11)
    spies.spy_phase(ctx)
    events.random_events(ctx)
    depopulation(ctx, {s.id for s in state.systems if 0 < s.pop < 0.5})
    disband_empty_fleets(ctx)
    cleanup(state)
    scans.do_scans(ctx)
    scans.extinction(ctx)
    stats.compute_stats(ctx)
    stats.check_victory(ctx)
    economy_summary(ctx)
    if npr_fn is not None:
        from ..npr import observe_turn          # NPR memory learns from its own report
        observe_turn(state, ctx.res)
    return ctx.res


def check_orders(state: GameState, empire: int, orders: Iterable[Order],
                 advice: Optional[list] = None, fixes: Optional[dict] = None):
    """Dry-run one empire's orders against a copy of the current state (the old order checker).
    Other empires' orders are not known, so results can differ when the turn really runs.
    Pass a list as `advice` to have it filled with the non-blocking warnings of
    engine/advice.py (DECISIONS G-20), and a dict as `fixes` (with `advice`) to get
    {index: fix} for failed orders that a Fix would make work (a cargo order after a warp)."""
    from .advice import Tracer
    copy = from_dict(to_dict(state))
    copy.turn += 1
    ctx = new_context(copy, checking=True)
    ctx.empire_order = [empire]
    orders = list(orders)
    tracer = Tracer(copy, empire, ctx, state, orders) if advice is not None else None
    out = []
    for i, o in enumerate(orders):
        if tracer:
            tracer.before(i, o)
        r = execute(ctx, empire, o, i)
        if tracer:
            tracer.after(i, o, r)
        out.append(r)
    if tracer:
        advice.extend(tracer.finish(orders, out))
        if fixes is not None:
            fixes.update(tracer.fixes)
    return out


def initial_results(state: GameState) -> TurnResults:
    """The 'turn 0' report for a new game: scans, map memory, stats and an economy summary, so
    every player starts with a picture of their neighbourhood.  Does not advance the turn."""
    ctx = new_context(state)
    scans.do_scans(ctx)
    stats.compute_stats(ctx)
    economy_summary(ctx)
    from ..npr import observe_turn              # computer empires get their turn-0 report too
    observe_turn(state, ctx.res)
    return ctx.res
