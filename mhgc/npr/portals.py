"""Farcaster portals and warp tunnels (Dave 2026-11-19, DECISIONS G-24).

The bot builds them only where they pay: an empire with a far front, i.e. a frontier system, a
war-fleet stage or a threatened system at least PORTAL_MIN_DIST squares from home.  Home is the
hub; a few far fronts get the other end.

* **Farcaster (FP, tech 32)**: combat troops (TP, 5 EU each) from the rear to the front.  A war
  fleet gathering at a stage with a portal takes spare assault troops from the other portal
  systems and, when the stage's own starport can't build all it needs, builds the rest at the
  hub, to be farcast next turn.  A threatened system with a portal gets the spare troops of safe
  portal systems.  Spare = not militia, not dug in (or digging in), and the sender keeps the
  ground defence it wants (war._ground's target).
* **Warp tunnel (WT, tech 50)**: ships (WTP, 10 EU each) between our own tunnel systems: warships
  for a war fleet at a stage with a tunnel when the trip would take WARP_MIN_TURNS or more, and
  warships with no job to a tunnel system that is short of its garrison.

Everything is decided from the bot's own view, and each order is checked against the plan's
budget as the engine checks it (orders_exec._tp, _wtp): both ends ours, in normal status, with
the artifact; the troop on the sending system and not aboard; the EUs.
"""
from __future__ import annotations

from ..data import constants as K
from ..data.troops import TROOP_TYPES
from .world import dist, frontier, home_xy, turns_to

PORTAL_MIN_DIST = 10      # a front this far from home (squares) makes a portal worth it
WARP_MIN_TURNS = 3        # a trip this long (in turns of the ship's own speed) is worth a warp
MAX_FRONTS = {"FP": 3, "WT": 2}       # far fronts that get the other end of a portal
TP_COST = 5
WTP_COST = 10
TP_A_TURN = 6             # troops farcast a turn at most
WTP_A_TURN = 6            # ships warped a turn at most
BUILD_MARGIN = 60         # EU kept beyond the upkeep reserve when building a portal
PULL = {32: 6.0, 50: 10.0}            # research value with a far front (econ.tech_score)
STAGE_SLACK = 3           # a war fleet stages at a portal system up to this much further away


def _ok(s) -> bool:
    return s is not None and s.mine and s.pop > 0 and s.status == K.NORMAL


def hub(w):
    """The rear end: the home system."""
    h = w.home()
    return h if _ok(h) else None


def far_fronts(w, thr: dict | None = None, stages: set = frozenset()) -> list:
    """Own systems worth a portal end: populated (3+), with a starport, normal status, at least
    PORTAL_MIN_DIST from the hub, and on the frontier, a war-fleet stage or threatened."""
    h = hub(w)
    if h is None:
        return []
    out = []
    for s in w.populated:
        if s.id == h.id or not _ok(s) or s.pop < 3 or s.starport < 1:
            continue
        d = dist(h.x, h.y, s.x, s.y)
        if d < PORTAL_MIN_DIST:
            continue
        hot = bool(thr and thr.get(s.id, {}).get("attack", 0) > 0)
        stage = s.id in stages
        if not (hot or stage or frontier(w, s)):
            continue
        out.append(((-int(stage), -int(hot), -d, -s.pop, s.id), s))
    return [s for _, s in sorted(out, key=lambda t: t[0])]


def _slow(w) -> int:
    """The median speed of our warships (the war fleet moves at its slowest ship's)."""
    mv = sorted(sh.st.move for sh in w.ships if sh.st.attack > 0)
    return mv[len(mv) // 2] if mv else 4


def research_pull(w, t: int) -> float:
    if t not in PULL:
        return 0.0
    h = hub(w)
    if h is None:
        return 0.0
    far = any(dist(h.x, h.y, s.x, s.y) >= PORTAL_MIN_DIST and frontier(w, s)
              for s in w.populated if s.pop >= 3)
    return PULL[t] if far else 0.0


def build(w, plan, thr: dict, stages: set, res: int) -> None:
    """Portal ends: the hub first, then up to MAX_FRONTS far fronts."""
    from .econ import ramped
    h = hub(w)
    if h is None or h.id in {sid for sid, t in thr.items() if t["attack"] > 0}:
        return
    at_war = any(w.at_war(r) for r in w.contacted())
    fronts = far_fronts(w, thr, stages)
    if not fronts:
        return
    for key, tech in (("FP", 32), ("WT", 50)):
        if not w.has_tech(tech):
            continue
        if key == "FP" and not (at_war or ramped(w) or stages):
            continue                        # troops only matter once it fights
        if key == "WT":
            fronts_wt = [s for s in fronts if turns_to(_slow(w), dist(h.x, h.y, s.x, s.y))
                         >= WARP_MIN_TURNS]
            if not fronts_wt or not (at_war or len(fronts_wt) >= 2):
                continue
            want = fronts_wt[:MAX_FRONTS[key]]
        else:
            want = fronts[:MAX_FRONTS[key]]
        why = ("farcaster portal: troops to a far front" if key == "FP" else
               "warp tunnel: ships to a far front")
        if key not in h.artifacts and not plan.build_artifact(h, key, why, res + BUILD_MARGIN):
            continue
        for s in want:
            if key not in s.artifacts:
                plan.build_artifact(s, key, why, res + BUILD_MARGIN)


# ---- farcasting troops -------------------------------------------------------------------------

def _ground_want(w, s, t) -> float:
    """war._ground's target defence for a system."""
    want = 2 + s.pop / 3 + 6 * t["carriers"] + (4 if t["attack"] > 0 else 0)
    if (s.x, s.y) == home_xy():
        want += 4
    return want


def _dfn(w, s) -> float:
    return sum(TROOP_TYPES[t["type"]].defense * (2 if t["posture"] == "E" else 1)
               for t in s.troops if t["owner"] == w.eid)


def spare_troops(w, plan, s, thr: dict) -> list:
    """Troops `s` can send by farcaster: not militia, not dug in or digging in, on the ground,
    not already moved or loaded this turn; best attackers first, while `s` keeps its ground
    defence target."""
    if not _ok(s) or "FP" not in s.artifacts or thr.get(s.id, {}).get("attack", 0) > 0:
        return []
    left = _dfn(w, s) - _ground_want(w, s, thr.get(s.id, {"attack": 0, "carriers": 0}))
    out = []
    pool = sorted((t for t in w.troops if t.system == s.id and t.ship is None and t.type != "M"
                   and t.posture in ("A", "D") and t.number not in plan.moved_troops
                   and t.number not in plan.tp_done),
                  key=lambda t: (-t.tt.attack, t.number))
    for t in pool:
        if left - t.tt.defense < 0:
            break
        left -= t.tt.defense
        out.append(t)
    return out


def farcast(w, plan, t, src, dst, why: str) -> bool:
    if plan.eu < TP_COST or not _ok(src) or not _ok(dst) or "FP" not in src.artifacts or \
            "FP" not in dst.artifacts or t.system != src.id or t.ship is not None:
        return False
    if plan.add("TP", why, system=src.name, item="C", amount=t.number, to=dst.name) is None:
        return False
    plan.pay(TP_COST, "portals")
    plan.tp_done.add(t.number)
    # the plan's own copy of the world: the troop is now on dst (a load later this turn works)
    t.system = dst.id
    for row in list(src.troops):
        if row.get("number") == t.number:
            src.troops.remove(row)
            dst.troops.append(row)
            break
    w.mem.setdefault("stats", {}).setdefault("tp", 0)
    w.mem["stats"]["tp"] += 1
    return True


def _senders(w, dst):
    return sorted((s for s in w.populated if s.id != dst.id and "FP" in s.artifacts and _ok(s)),
                  key=lambda s: (dist(s.x, s.y, dst.x, dst.y) * -1, s.id))


def troops_to_stage(w, plan, stage, need: int, thr: dict) -> int:
    """Farcast up to `need` spare troops from our other portal systems to a war-fleet stage."""
    if need <= 0 or not _ok(stage) or "FP" not in stage.artifacts:
        return 0
    sent = 0
    for s in _senders(w, stage):
        for t in spare_troops(w, plan, s, thr):
            if sent >= min(need, TP_A_TURN) or len(plan.tp_done) >= TP_A_TURN:
                return sent
            if t.tt.attack < 2:
                continue                     # defensive kinds aren't assault troops
            if farcast(w, plan, t, s, stage, "farcast assault troops to the stage"):
                sent += 1
    return sent


def troops_to_build_at_hub(w, plan, stage, code: str, n: int, res: int) -> int:
    """Assault troops built at the hub (posture A) for a stage with a portal whose own
    starport ran out: they are farcast next turn."""
    h = hub(w)
    if n <= 0 or h is None or h.id == stage.id or "FP" not in h.artifacts or \
            "FP" not in stage.artifacts or not _ok(stage):
        return 0
    built = 0
    for _ in range(min(n, 4)):
        if not plan.build_troop(h, code, "A", "assault troops to farcast", res + TP_COST * 4):
            break
        built += 1
    return built


def defence(w, plan, thr: dict) -> None:
    """Spare troops by farcaster to threatened portal systems (both ends must be normal, so this
    is before the attack lands)."""
    hot = sorted((s for s in w.populated if "FP" in s.artifacts and _ok(s)
                  and thr.get(s.id, {}).get("attack", 0) > 0),
                 key=lambda s: (-(thr[s.id]["attack"] + 6 * thr[s.id]["carriers"]), s.id))
    for dst in hot:
        gap = _ground_want(w, dst, thr[dst.id]) - _dfn(w, dst)
        for s in _senders(w, dst):
            if gap <= 0 or len(plan.tp_done) >= TP_A_TURN:
                break
            for t in spare_troops(w, plan, s, thr):
                if gap <= 0 or len(plan.tp_done) >= TP_A_TURN:
                    break
                if farcast(w, plan, t, s, dst, "farcast troops to a threatened system"):
                    gap -= t.tt.defense


# ---- warping ships -----------------------------------------------------------------------------

def can_warp(w, plan, sh, dst) -> bool:
    if not _ok(dst) or "WT" not in dst.artifacts or plan.eu < WTP_COST or \
            plan.warped >= WTP_A_TURN or sh.number in plan.busy:
        return False
    here = w.system_at(sh.x, sh.y)
    return _ok(here) and here.id != dst.id and "WT" in here.artifacts


def warp(w, plan, sh, dst, why: str) -> bool:
    if plan.add("WTP", why, ship=sh.number, system=dst.name) is None:
        return False
    plan.pay(WTP_COST, "portals")
    plan.warped += 1
    plan.busy.add(sh.number)
    sh.x = sh.dx = dst.x
    sh.y = sh.dy = dst.y
    sh.order = "STAND"
    w.mem.setdefault("stats", {}).setdefault("wtp", 0)
    w.mem["stats"]["wtp"] += 1
    return True


def worth_warping(sh, dst) -> bool:
    return turns_to(sh.st.move, dist(sh.x, sh.y, dst.x, dst.y)) >= WARP_MIN_TURNS


__all__ = ["build", "far_fronts", "hub", "research_pull", "spare_troops", "farcast",
           "troops_to_stage", "troops_to_build_at_hub", "defence", "can_warp", "warp",
           "worth_warping"]
