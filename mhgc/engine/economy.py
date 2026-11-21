"""Turn phases 2-4: produce, feed + happiness (+ rebellion), grow.  Also DCT trade.

Formulas follow gcrun.c:419-742 (ENGINE_MAP 20.4-20.7) except where the rules give numbers
(DECISIONS D-02, §2 #18, §3 table 20).  The C interleaved the three phases per system; the rules
list them as separate phases (rules:180-183), which is what we do.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from ..data import constants as K
from ..model import HUMAN, NPR
from .context import TurnContext
from .orders_exec import create_troop


def leader_factors(ctx: TurnContext, s) -> tuple[float, float]:
    """(management factor, social factor).  Rules:355-421: with no leader a system produces
    5 units per pop (factor 1.0) and 50 is a neutral rating.  The C scale (0.25 + 0.5*mgmt/100,
    0.5 with no leader) is doubled so the rules' example works (DECISIONS D-02)."""
    gov = ctx.state.governor(s.id)
    if gov is None:
        return 1.0, 0.5                        # the same for computer empires (DECISIONS A-01)
    return 0.5 + gov.mgmt / 100.0, gov.social / 100.0


# ---- production of one system, and the split tweak ------------------------------------------
#
# A system's output of each resource is int(base x share / 100 x multipliers): truncated to whole
# units (rules: production).  `SplitContext` holds everything but the split, so the engine, the
# production preview, the split tweak and the bot all compute it with the same floating-point
# operations in the same order.

@dataclass(frozen=True)
class SplitContext:
    base: float                          # production before the split (pop, IF, leader, ...)
    au: tuple[float, ...] = ()           # the AU multipliers, applied in this order
    iu: tuple[float, ...] = ()
    eu: tuple[float, ...] = ()


def production_base(pop: float, infra: int, mgmt: float, status: int, starport: int) -> float:
    """Production before the split (rules: 5 per pop, x infrastructure up to 2, x the governor's
    management, x 0.5 under attack / 0 interdicted, +10% a starport class)."""
    if pop <= 0:
        return 0.0
    if status == K.UNDER_ATTACK:
        cm = 0.5
    elif status == K.INTERDICTED:
        cm = 0.0
    else:
        cm = 1.0
    infra_mult = min(2.0, (pop + infra) / pop)
    return (pop * K.PROD_PER_POP * infra_mult * mgmt * cm *
            (1.0 + K.STARPORT_PROD_BONUS * starport))


def make_split_context(pop: float, infra: int, mgmt: float, status: int, starport: int,
                       mr: bool, ar: bool, artifacts) -> SplitContext:
    """The pure builder (the engine and the bot both use it): MR, CM, AL for IU; AR, BF, AF for
    AU; CB, VRB for EU."""
    a = artifacts
    return SplitContext(
        base=production_base(pop, infra, mgmt, status, starport),
        au=(2 if ar else 1, 1.5 if "BF" in a else 1, 1.5 if "AF" in a else 1),
        iu=(2 if mr else 1, 1.5 if "CM" in a else 1, 1.5 if "AL" in a else 1),
        eu=(1.5 if "CB" in a else 1, 1.5 if "VRB" in a else 1))


def split_context(ctx: TurnContext, s) -> SplitContext:
    """The system's SplitContext as the engine sees it now (governor, status, starport, IF)."""
    mgmt, _ = leader_factors(ctx, s)
    return make_split_context(s.pop, s.infra, mgmt, s.status, s.starport, s.mr, s.ar,
                              s.artifacts)


def split_output(sc: SplitContext, split) -> tuple[int, int, int]:
    """(AU, IU, EU) for a split (au %, iu %, eu %), truncated to whole units."""
    out = []
    for pct, mults in zip(split, (sc.au, sc.iu, sc.eu)):
        v = sc.base * pct / 100.0
        for m in mults:
            v = v * m
        out.append(int(v))
    return out[0], out[1], out[2]


def system_production(ctx: TurnContext, s) -> tuple[int, int, int]:
    """(AU, IU, EU) a populated system produces this turn with its current profile (pure; the
    production phase and the production preview both use it)."""
    return split_output(split_context(ctx, s), (s.csp_au, s.csp_iu, s.csp_eu))


SPLIT_MIN, SPLIT_MAX = 10, 80            # a CSP share is 10-80 and the three total 100


def valid_split(split) -> bool:
    return (len(split) == 3 and all(isinstance(v, int) and not isinstance(v, bool)
                                    for v in split)
            and sum(split) == 100 and all(SPLIT_MIN <= v <= SPLIT_MAX for v in split))


def tweak_split(sc: SplitContext, split, max_delta: int = 3) -> dict:
    """The split tweak (Dave 2026-11-18; the old players' trick from Richard Aronson's FAQ:
    output is truncated, so pick shares that land just above whole numbers).

    Searches every valid split (whole numbers, each 10-80, total 100) within +-max_delta of each
    current share.  A candidate qualifies only if none of AU, IU, EU goes down against the current
    split; the best is the one with the most total units, then the fewest points moved, then
    the lowest (au, iu) for determinism; the current split wins any tie.  So the tweak only
    recovers rounding waste: what the player aims for is kept, and AU (feeding, happiness) never
    drops.

    Returns {"split", "before", "after", "gain", "moved", "optimal"}: "optimal" is True when
    nothing beats the current split (then split == the current one and gain == 0)."""
    cur = tuple(split)
    if not valid_split(cur):
        raise ValueError("not a valid split (whole numbers, each 10-80, total 100)")
    before = split_output(sc, cur)
    best, best_out, best_key = cur, before, (sum(before), 0)
    d = max(0, int(max_delta))
    for au in range(cur[0] - d, cur[0] + d + 1):
        for iu in range(cur[1] - d, cur[1] + d + 1):
            eu = 100 - au - iu
            cand = (au, iu, eu)
            if abs(eu - cur[2]) > d or cand == cur or not valid_split(cand):
                continue
            out = split_output(sc, cand)
            if any(o < b for o, b in zip(out, before)):
                continue
            moved = abs(au - cur[0]) + abs(iu - cur[1]) + abs(eu - cur[2])
            key = (sum(out), -moved)
            if key > best_key:           # strictly better: earlier (lower au, iu) wins a tie
                best, best_out, best_key = cand, out, key
    moved = sum(abs(a - b) for a, b in zip(best, cur))
    return {"split": best, "before": before, "after": best_out,
            "gain": sum(best_out) - sum(before), "moved": moved, "optimal": best == cur}


def produce(ctx: TurnContext) -> None:
    st = ctx.state
    for s in st.systems:
        if s.pop <= 0:
            continue
        if s.status == K.INTERDICTED:
            s.trade_routes.clear()             # rules:2879 route lost if interdicted
        au, iu, eu = system_production(ctx, s)
        ec = ctx.econ[s.id]
        ec.prod_au, ec.prod_iu, ec.prod_eu = au, iu, eu
        s.au += au
        s.iu += iu
        ctx.au_prod[s.owner] += au
        ctx.iu_prod[s.owner] += iu
        ctx.eu_prod[s.owner] += eu
        st.empires[s.owner].eu += eu
        trade(ctx, s, eu)


def trade(ctx: TurnContext, s, prod_eu: int) -> None:
    """Decentralized Trading (rules:319-327; gcutils.c:754-844).  Each route takes 25% of the
    system's EU production, scaled by the owner's Deny DCT setting, with an optional kick-back
    (Split DCT); all routes together are capped at 50% of production.  Trade EUs are created,
    not taken from the owner."""
    routes = [y for y in sorted(s.trade_routes) if y != s.owner]
    if not routes or prod_eu <= 0:
        return
    owner = ctx.state.empires[s.owner]
    te = prod_eu * K.DCT_SHARE
    parts = []
    for y in routes:
        trader = ctx.state.empires[y]
        base = owner.deny_trade.get(y, 100) / 100.0 * te
        split = trader.split_trade.get(s.owner, 0)
        parts.append((y, base * (100 - split) / 100.0, base * split / 100.0))
    total = sum(a + b for _, a, b in parts)
    prorate = min(1.0, prod_eu * K.DCT_CAP / total) if total > 0 else 0.0
    for y, to_trader, to_owner in parts:
        ctx.trade_eu[y] += int(int(to_trader + 0.5) * prorate)      # gcutils.c:800-830
        ctx.trade_eu[s.owner] += int(int(to_owner + 0.5) * prorate)


def feed_amount(s) -> int:
    """AUs released to the population from the stockpile (rules:400-404, gcrun.c:516-521)."""
    if s.au_mode == "pct":
        return int(s.au * s.au_value / 100.0)
    return min(s.au_value, s.au)


def settle_happiness(ctx: TurnContext, s) -> None:
    """Feed a populated system and move its happiness half-way to the target (deterministic;
    the happiness phase and the production preview both use it)."""
    st = ctx.state
    eat = feed_amount(s)
    ctx.econ[s.id].eaten = eat
    s.au -= eat
    _, social = leader_factors(ctx, s)
    adds = 4.0 if (s.has("EHC") and s.has("CS")) else 1.0 if s.has("EHC") else \
        3.0 if s.has("CS") else 0.0
    adds += 0.5 * sum(1 for a in ("PD", "SW", "APD") if s.has(a))
    a_term = math.sqrt(eat / 5.0) / math.sqrt(2.25 * s.pop * (1.0 + s.starport / 10.0))
    b_term = (s.hab + (social * 4 - 2) + adds) / (s.pop * 2)
    target = a_term + b_term - 0.2
    target -= ctx.spy_unrest[s.id] / 10.0
    if s.status == K.UNDER_ATTACK:
        target -= 0.2
    elif s.status == K.INTERDICTED:
        target -= 0.4
    owner = st.empires[s.owner]
    if owner.systems_captured < -3:
        owner.systems_captured = -3
    target += owner.systems_captured / 10.0
    old = s.happy
    s.trend = -1 if target < old - 0.01 else 1 if target > old + 0.01 else 0
    s.happy += (target - s.happy) / 2.0


def unrest_risk(s, owner_kind: str) -> Optional[tuple[str, int]]:
    """What the settled happiness can set off this turn: ("rebellion", 100), ("uprising", % chance),
    ("emperor_day", % chance) or None (rules:692-701)."""
    if s.status != K.NORMAL:
        return None                             # rules:696-701
    if s.happy < 0.4:
        if owner_kind not in (HUMAN, NPR):
            return None                         # (NPRs rebel like players, DECISIONS A-01)
        if s.happy <= 0:
            return ("rebellion", 100)
        return ("uprising", K.UPRISING_CHANCE_UH if s.happy < 0.2 else K.UPRISING_CHANCE_NH)
    if s.happy > 0.6:
        return ("emperor_day", K.EMPEROR_DAY_EH if s.happy >= 0.8 else K.EMPEROR_DAY_VH)
    return None


def happiness(ctx: TurnContext) -> None:
    st = ctx.state
    for s in st.systems:
        if s.pop <= 0:
            continue
        settle_happiness(ctx, s)
        risk = unrest_risk(s, st.empires[s.owner].kind)
        if risk is None:
            continue
        kind, p = risk
        if kind == "rebellion":
            rebellion(ctx, s)
        elif ctx.rng.chance(p):
            (uprising if kind == "uprising" else emperor_day)(ctx, s)


def rebellion(ctx: TurnContext, s) -> None:
    """The system and its owner's troops become independent (rules:692-693; gcrun.c:568-585)."""
    old = s.owner
    for t in ctx.state.troops_at(s.id):
        if t.owner == old:
            t.owner = 0
    s.owner = 0
    s.trade_routes.clear()
    ctx.res.emit(old, "rebellion", f"REBELLION ON SYSTEM {s.name}!!!", "rebellion", s.id)


def uprising(ctx: TurnContext, s) -> None:
    lines = [f"UPRISING ON SYSTEM {s.name}!!!"]
    kind = "uprising"
    if ctx.rng.chance(K.UPRISING_MILITIA):
        create_troop(ctx, 0, "M", sys_id=s.id)
        lines.append("Rebel Militia Unit created")
        kind = "uprising_militia"
    elif ctx.rng.chance(40):
        s.infra = max(0, s.infra - 1)
        lines.append("Sabotage destroys public works!")
    elif ctx.rng.chance(60):
        lost = s.iu - s.iu // 2
        s.iu //= 2
        lines.append(f"Arson burns down warehouses! ({lost} IUs lost)")
    else:
        s.happy = max(0.01, s.happy - 0.2)
        lines.append("Charismatic rebel leader appears! Incites population!")
    ctx.res.emit(s.owner, kind, "\n".join(lines), "rebellion", s.id)


def emperor_day(ctx: TurnContext, s) -> None:
    lines = [f"WE LOVE THE EMPEROR DAY ON SYSTEM {s.name}!!!"]
    ec = ctx.econ[s.id]
    if ctx.rng.chance(10):
        s.starport += 1
        lines.append("Starport Upgraded for FREE!")
    elif ctx.rng.chance(30):
        y = int((ctx.rng.below(10) + 1) * ec.prod_iu / 10.0 + 1)
        s.iu += y
        ec.prod_iu += y
        ctx.iu_prod[s.owner] += y
        lines.append(f"Population works overtime! Produces {y} extra IUs!")
    elif ctx.rng.chance(50):
        y = int((ctx.rng.below(10) + 1) * ec.prod_eu / 10.0 + 1)
        ctx.state.empires[s.owner].eu += y
        ec.prod_eu += y
        ctx.eu_prod[s.owner] += y
        lines.append(f"People encouraged to invest, {y} EU bonanza!!")
    else:
        s.happy += 0.2
        lines.append("Excited population explodes into song!")
    ctx.res.emit(s.owner, "emperor_day", "\n".join(lines), "rebellion", s.id)


def grow(ctx: TurnContext) -> None:
    """Population growth (gcrun.c:711-738)."""
    for s in ctx.state.systems:
        if s.pop <= 0:
            continue
        before = s.pop
        hf = min(1.5, max(0.0, (s.happy - 0.5) * 2))
        g = min(1.0, K.GROWTH_RATE * hf * s.hab / s.pop)
        s.pop += g
        if not s.has("EUS") and s.pop > K.POP_CAP:
            s.pop = K.POP_CAP
        ctx.growth[s.owner] += s.pop - before
