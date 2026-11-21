"""Turn phase 10: random events (gcrandom.c:37-381; ENGINE_MAP 20.13).

Frequencies and formulas are the C's (the rules give none).  Fixes: an empty system hit by plague
no longer comes back with 1 pop; system selection cannot loop forever; events on systems nobody
lives on are skipped.  The CD-ROM of Ancient Wisdom reveals system locations, as the rules
describe (rules:1196-1198), instead of granting a technology (DECISIONS F-06).
"""
from __future__ import annotations

from ..data import constants as K
from ..data.flavour import LEADER_BAD_EVENT, LEADER_GOOD_EVENT
from ..model import HUMAN
from .context import TurnContext
from .leaders import leader_events

ADVANCED_DNA = 26


def _eng_factor(ctx, sid):
    """(eng/50)^2 for the leader at the system, or None (gcrandom.c:395)."""
    gov = ctx.state.governor(sid)
    if gov is None:
        return None, None
    return (max(gov.eng, 1) / 50.0) ** 2, gov


def _leader_note(gov, bad: bool) -> str:
    i = 0 if gov.eng < 45 else 2 if gov.eng > 60 else 1
    return f"Governor {gov.name} {(LEADER_BAD_EVENT if bad else LEADER_GOOD_EVENT)[i]}!"


def _pick(ctx, done: set) -> int:
    n = len(ctx.state.systems)
    free = [i for i in range(n) if i not in done]
    i = ctx.rng.choice(free) if free else ctx.rng.below(n)
    done.add(i)
    return i


def random_events(ctx: TurnContext) -> None:
    leader_events(ctx)
    done: set[int] = set()
    for _ in range(2):
        _other_events(ctx, done)
    cd_rom(ctx)


def _emit(ctx, s, kind, text, **data):
    if s.owner or s.pop > 0:
        ctx.res.emit(s.owner, kind, text, "random", s.id, **data)


def _other_events(ctx: TurnContext, done: set) -> None:
    st, rng, turn = ctx.state, ctx.rng, ctx.turn
    start = K.EVENTS_START_TURN
    # plague
    m = 0
    if start < turn <= 2 * start:
        m = 1 if rng.below(10) < 4 else 0
    elif turn > 2 * start:
        m = 4
    for _ in range(m):
        plague(ctx, st.systems[_pick(ctx, done)])
    # IU gain
    if rng.below(10) > 4 and turn > start:
        iu_gain(ctx, st.systems[_pick(ctx, done)])
    # AU or IU loss
    s = st.systems[_pick(ctx, done)]
    k = rng.below(100) + 1
    e, gov = _eng_factor(ctx, s.id)
    if e:
        k = int(k / e)
    k = min(k, 100)
    if turn > start:
        if rng.below(10) < 5:
            lvl = rng.below(10)
            if lvl > 8:
                k = min(3 * k, 100)
                txt = (f"MUTANT JEWEL EATING VIRUS ON SYSTEM {s.name}!\n"
                       f"{k} PERCENT AU LOSS DUE TO LUXURY GOODS DESTROYED!")
            elif lvl > 6:
                k = min(2 * k, 100)
                txt = (f"POTATO FAMINE ON SYSTEM {s.name}!\n{k} PERCENT AU LOSS DUE TO "
                       f"DESTROYED FOOD!")
            else:
                txt = (f"VINE ROT ON SYSTEM {s.name} VINEYARDS!\n{k} PERCENT LOSS OF AUs DUE TO "
                       f"DESTROYED WINE!  PEOPLE UNHAPPY!!")
            if s.pop > 0:
                s.au -= int(s.au * k / 100.0)
                _emit(ctx, s, "au_loss", txt, percent=k)
        else:
            lvl = rng.below(10)
            if lvl > 8:
                k = min(3 * k, 100)
                txt = (f"METEOR HITS MAJOR CITY ON SYSTEM {s.name}!\n{k} PERCENT IU STOCKS USED "
                       f"TO REBUILD!")
            elif lvl > 6:
                k = min(2 * k, 100)
                txt = (f"BIOMOD RESEARCH CREATES GODZILLA ON SYSTEM {s.name}!\nBYE BYE TOKYO!\n"
                       f"{k} PERCENT IU STOCKS USED TO REBUILD!")
            else:
                txt = (f"RUST MONSTERS APPEAR ON SYSTEM {s.name}!\nALL AUTOMOBILES CONVERTED TO "
                       f"PILES OF RUST!\n{k} PERCENT IU STOCKS USED TO REBUILD!")
            if s.pop > 0:
                s.iu -= int(s.iu * k / 100.0)
                _emit(ctx, s, "iu_loss", txt, percent=k)
    # infrastructure loss or population boom
    s = st.systems[_pick(ctx, done)]
    k = rng.below(100) + 1
    e, gov = _eng_factor(ctx, s.id)
    if turn > start:
        if rng.below(10) < 5:
            if e:
                k = int(k / e)
            k = min(k, 100)
            if s.pop > 0:
                s.infra -= int(s.infra * k / 100.0)
                _emit(ctx, s, "infra_loss", f"NATURAL DISASTERS ON SYSTEM {s.name}!\n{k} PERCENT "
                      f"INFRASTRUCTURE DESTROYED!", percent=k)
        else:
            k //= 5
            if e:
                k = int(k * e ** 0.5)
            if s.pop > 0:
                txt = (f"ACCIDENTAL RELEASE OF CHEMICAL AGENT 'CRAZED WEASIL' ON SYSTEM "
                       f"{s.name}!\n{k} PERCENT POP INCREASE!")
                s.pop += s.pop * k / 100.0
                if s.pop > K.POP_CAP and not s.has("EUS"):
                    s.pop = K.POP_CAP
                    txt += "\nWho immediately die off without Extended Use of System"
                _emit(ctx, s, "pop_boom", txt, percent=k)


def plague(ctx: TurnContext, s) -> None:
    rng = ctx.rng
    k = rng.below(80) + 10
    if s.pop <= 0:
        return                                    # C gave empty systems 1.0 pop (DECISIONS B-29)
    roll = k
    owner = ctx.state.empires[s.owner]
    lines = [f"PLAGUE ON SYSTEM {s.name}!  {k} PERCENT POPULATION AFFECTED!"]
    if ADVANCED_DNA in owner.techs:
        k //= 2
        lines.append("Plague effects reduced by 50% with Advanced DNA Manipulation!")
    e, gov = _eng_factor(ctx, s.id)
    if e:
        k = int(k / e)
        lines.append(_leader_note(gov, True))
    k = min(k, 90)
    if s.pop * k / 100.0 > 3:
        k = int(300.0 / s.pop)
    s.pop -= s.pop * k / 100.0
    if s.pop < 1.0:
        s.pop = 1.0
        lines.append("Population decimated but a few hardy survivors ...err... survive!!")
    elif k == roll:
        lines.append("ALL AFFECTED POP LOST!")
    elif k < roll:
        lines.append(f"Effects of plague mitigated! Only {k} percent people die!")
    else:
        lines.append(f"Effects of plague exacerbated! {k} percent people die!")
    _emit(ctx, s, "plague", "\n".join(lines), percent=k)


def iu_gain(ctx: TurnContext, s) -> None:
    rng = ctx.rng
    k = rng.below(100) + 1
    e, gov = _eng_factor(ctx, s.id)
    if e:
        k = int(k * e)
    if s.iu * k / 100.0 > s.hab * 10:
        k = int(s.hab * 10 * 100.0 / (s.iu + 1))
    m = rng.below(10)
    if m < 3:
        k *= 3
        txt = f"KRYPTONITE MINE FOUND ON SYSTEM {s.name}!\n{k} PERCENT INCREASE IN IU STOCKS!"
    elif m < 7:
        k *= 2
        txt = (f"SOLID NICKEL IRON ASTEROID FOUND IN SYSTEM {s.name}!\n{k} PERCENT INCREASE IN "
               f"IU STOCKS!")
    else:
        txt = f"NEW FISSIONABLES STRIKE IN SYSTEM {s.name}!\n{k} PERCENT INCREASE IN IU STOCKS!"
    if gov is not None:
        txt += "\n" + _leader_note(gov, False)
    if s.pop > 0:
        s.iu += int(s.iu * k / 100.0)
        _emit(ctx, s, "iu_gain", txt, percent=k)


def cd_rom(ctx: TurnContext) -> None:
    """CD-ROM of Ancient Wisdom (rules:1196-1198).  After turn 6, half the turns, one random
    player learns the location of 3-8 systems it has never seen; they appear on its map as
    unowned, unnamed systems.  (The C used this event to hand out a technology instead.)"""
    rng, st = ctx.rng, ctx.state
    if ctx.turn <= K.CD_ROM_START_TURN or rng.below(10) >= 5:
        return
    players = [e for e in st.empires.values() if e.kind == HUMAN]
    if not players:
        return
    e = rng.choice(players)
    unseen = [s for s in st.systems if s.id not in e.seen_systems and s.owner != e.id]
    if not unseen:
        return
    picks = rng.sample(unseen, min(len(unseen), rng.between(3, 8)))
    for s in picks:
        e.seen_systems[s.id] = {"turn": ctx.turn, "name": None, "owner": None, "via": "cdrom"}
    ctx.res.emit(e.id, "cd_rom", f"A CD-ROM OF ANCIENT WISDOM is found!  It reveals the location"
                 f" of {len(picks)} star systems.", "random", systems=[s.id for s in picks])
