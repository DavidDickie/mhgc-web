"""Leaders: ageing, stat drift, natural death, new leaders, comments (rules:619-662;
gcleader.c, gcrandom.c:57-118; ENGINE_MAP 20.14)."""
from __future__ import annotations

from ..data import constants as K
from ..data.flavour import (COMMENT_SOURCE, COMMENT_TOPIC, COMMENT_VERB, DESC_CAREER,
                            DESC_REPUTATION, DESC_SKILL, grade_word, wrap60)
from ..model import DEAD, HUMAN, NPR, Leader
from .context import TurnContext

STATS = ("mgmt", "combat", "social", "eng")


def leader_description(ld: Leader, rng=None) -> str:
    """leader_desc (gcleader.c:223-340).  `rng` picks between the two texts per skill band;
    without one the first is used (deterministic for spy reports)."""
    pick = (lambda: rng.below(2)) if rng is not None else (lambda: 0)
    msg = f"Gov. {ld.name} "
    if ld.intel > 90 and ld.combat > 90 and ld.social > 90:
        x = 0
    elif ld.intel > max(ld.mgmt, ld.eng, ld.social, ld.combat):
        x = 1
    elif ld.social > max(ld.mgmt, ld.eng, ld.combat):
        x = 2
    elif ld.mgmt > max(ld.eng, ld.combat):
        x = 3
    elif ld.eng > ld.combat:
        x = 4
    elif ld.intel > 70:
        x = 6
    else:
        x = 5
    msg += DESC_CAREER[x]
    if ld.mgmt > 80 and ld.social < 50:
        msg += DESC_REPUTATION[0]
    elif ld.social > 80 and ld.mgmt < 50:
        msg += DESC_REPUTATION[1]
    elif ld.mgmt > 80 and ld.intel < 50:
        msg += DESC_REPUTATION[2]
    elif ld.intel > 80 and ld.mgmt < 50:
        msg += DESC_REPUTATION[3]
    for skill in ("mgmt", "eng", "social", "combat"):
        v = getattr(ld, skill)
        i = pick()
        if v > 70:
            msg += DESC_SKILL[skill][i]
        elif v < 55:
            msg += DESC_SKILL[skill][i + 2]
    return wrap60(msg)


def leader_comment(ld: Leader, rng) -> str:
    """leader_comments (gcleader.c:95-215)."""
    skill = ("mgmt", "eng", "intel", "social", "combat")[rng.below(5)]
    msg = (COMMENT_SOURCE[rng.below(6)] + COMMENT_VERB[rng.below(4)] + "concerning the " +
           grade_word(getattr(ld, skill)) + "performance of Gov. " + ld.name + " " +
           COMMENT_TOPIC[skill][rng.below(4)])
    return wrap60(msg)


def _clamp(v: int) -> int:
    return max(0, min(99, v))


def leader_events(ctx: TurnContext) -> None:
    st, rng = ctx.state, ctx.rng
    # ---- ageing, death, drift (gcrandom.c:65-95)
    for ld in st.leaders.values():
        if not ld.alive or st.empires[ld.owner].kind == DEAD:
            continue
        ld.age += 1
        if ld.age > 20:
            ld.intel = _clamp(ld.intel - 1)
        if ld.status == "ice":
            ld.transit -= 1
        if ld.age // 10 > rng.pct() or (ld.status == "ice" and ld.transit <= 0):
            ld.alive = False
            ctx.res.emit(ld.owner, "leader_died", f"LEADER {ld.name} DIES OF NATURAL CAUSES!!!!",
                         "leaders", leader=ld.id)
            continue
        young = ld.age < 20
        for stat in STATS:
            v = getattr(ld, stat)
            if young:
                if rng.pct() < ld.intel and rng.pct() > v:
                    setattr(ld, stat, _clamp(v + 5))
            else:
                if rng.pct() > ld.intel and rng.pct() < v:
                    setattr(ld, stat, _clamp(v - 5))
    # ---- new leaders (gcleader.c:25-87), from turn 4
    if ctx.turn > 3:
        quota = 2 + ctx.turn // 10
        for e in st.empires.values():
            if e.kind not in (HUMAN, NPR):
                continue
            have = sum(1 for ld in st.leaders.values() if ld.alive and ld.owner == e.id)
            if have >= quota:
                continue
            if rng.pct() > 15 + (quota - have) * 10:
                continue
            ld = new_leader(ctx, e.id)
            ctx.res.emit(e.id, "leader_found", f"You have found leader {ld.name}\n\n"
                         f"{ld.description}", "random", leader=ld.id)
    # ---- comments, from turn 11 (20% per leader)
    if ctx.turn > K.EVENTS_START_TURN:
        for ld in st.leaders.values():
            if ld.alive and rng.pct() < 20 and st.empires[ld.owner].kind in (HUMAN, NPR):
                ctx.res.emit(ld.owner, "leader_comment", f"You've received comments on Gov. "
                             f"{ld.name}\n{leader_comment(ld, rng)}", "random", leader=ld.id)


def new_leader(ctx: TurnContext, owner: int) -> Leader:
    st, rng = ctx.state, ctx.rng
    stats = [100 - (rng.below(9) + 1) ** 2 for _ in range(5)]   # intel combat mgmt social eng
    names = {ld.name for ld in st.leaders.values()}
    for _ in range(2000):
        name = f"Ldr_{rng.below(1000)}"
        if name not in names:
            break
    lid = st.next_leader_id
    st.next_leader_id += 1
    ld = Leader(lid, name, owner, intel=stats[0], combat=stats[1], mgmt=stats[2],
                social=stats[3], eng=stats[4], status="limbo")
    ld.description = leader_description(ld, rng)
    st.leaders[lid] = ld
    return ld
