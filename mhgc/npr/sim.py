"""Simulations and the bot strength harness.

  python -m mhgc.npr.sim npr  [seed] [humans] [turns] [none|random]
      a normal game: 16 empires, NPRs run by the engine's default bot, 0-2 idle/random humans
  python -m mhgc.npr.sim match [seed] [turns] [bot|base|mix|self]
      a strength match with every seat a *player* seat (so victory points and the 100-VP win
      count): "mix" = 8 bots vs 8 baseline bots; "self" = 16 bots (personalities mixed);
      "base" = 16 baseline bots

Every seat decides from its own view (mhgc.view) only.
"""
from __future__ import annotations

import random
import sys
import time
from collections import Counter, defaultdict

from .. import geometry as G
from ..data.techs import TECHS
from ..engine.turn import run_turn
from ..mapgen import new_game
from ..model import NPR
from ..orders import OrderSyntaxError, parse_line
from ..rng import Rng
from ..view import view
from . import bot_orders
from .baseline import baseline_orders
from .brain import inbox
from .memory import PERSONA_ORDER, memory


def random_orders(st, eid, r: random.Random) -> list:
    """Crude random human orders (a fuzz generator, not an AI)."""
    e = st.empires[eid]
    out = []
    mine = [s for s in st.systems if s.owner == eid and s.pop > 0]
    ships = [s for s in st.live_ships() if s.owner == eid]
    cheap = [t for t in sorted(TECHS) if 0 < t < 51 and t not in e.techs]
    if cheap and r.random() < 0.5:
        out.append(f"PT {r.choice(cheap[:6])}")
    for s in mine:
        roll = r.random()
        if roll < 0.35:
            out.append(f"BS {s.name} {r.choice(['F', 'F', 'D', 'T', 'S'])} H")
        elif roll < 0.45:
            out.append(f"BCU {s.name} S")
        elif roll < 0.55:
            out.append(f"BI {s.name} 1")
    targets = [s for s in st.systems if s.id in e.seen_systems and s.owner != eid]
    for sh in ships:
        roll = r.random()
        if roll < 0.5 and targets:
            near = sorted(targets, key=lambda s: G.distance(sh.x, sh.y, s.x, s.y, st.board))[:6]
            out.append(f"MS {sh.number} {r.choice(near).name}")
        elif roll < 0.6:
            out.append(f"G {sh.number}")
    for other in list(e.relations):
        if other and r.random() < 0.03:
            out.append(f"{r.choice(['DA', 'DW', 'EWA'])} {st.empires[other].name}")
    orders = []
    for line in out:
        try:
            o = parse_line(line)
        except OrderSyntaxError:
            continue
        if o is not None:
            orders.append(o)
    return orders


def _count_orders(stats, res, eids):
    for eid in eids:
        for o in res.report(eid).orders:
            stats["orders"] += 1
            stats["codes"][o.code] += 1
            if not o.ok:
                stats["rejected"] += 1
                stats["rejections"][f"{o.code}: {o.error}"] += 1
                if len(stats["rejection_samples"]) < 30:
                    stats["rejection_samples"].append((res.turn, eid, o.text, o.error))


def _new_stats(**kw):
    d = {"turns": 0, "orders": 0, "rejected": 0, "rejections": Counter(), "codes": Counter(),
         "rejection_samples": [], "seconds": [], "systems": [], "ships": [], "attack": [],
         "vp": [], "history": [], "bugs": []}
    d.update(kw)
    return d


def simulate(seed: int, humans: int = 0, turns: int = 40, human_mode: str = "none",
             size: int = 16) -> dict:
    """A normal game of `size` empires: NPR seats are run by run_turn's default bot."""
    st = new_game(f"sim{seed}", seed, [f"Human{i + 1}" for i in range(humans)], size=size)
    r = random.Random(seed)
    stats = _new_stats(seed=seed, humans=humans, mode="npr", size=size)
    stats["chat"] = []
    for _ in range(turns):
        orders = {}
        if human_mode == "random":
            orders = {e.id: random_orders(st, e.id, r) for e in st.empires.values()
                      if e.kind == "human"}
        t0 = time.perf_counter()
        res = run_turn(st, orders)
        stats["seconds"].append(time.perf_counter() - t0)
        stats["turns"] += 1
        stats["chat"] += [dict(m, turn=res.turn) for m in getattr(res, "chat", [])]
        nprs = [e.id for e in st.empires.values() if e.kind == NPR]
        _count_orders(stats, res, nprs)
        _curves(stats, st, set(nprs))
        if st.winner is not None:
            break
    _finish(stats, st)
    return stats


def _curves(stats, st, eids):
    stats["systems"].append(sum(1 for s in st.systems if s.owner in eids))
    stats["ships"].append(sum(1 for s in st.live_ships() if s.owner in eids))
    stats["attack"].append(sum(s.stype.attack for s in st.live_ships() if s.owner in eids))
    stats["vp"].append(round(sum(st.empires[e].vp for e in eids) / max(1, len(eids)), 1))


def _finish(stats, st):
    agg = Counter()
    for eid, mem in st.npr_state.items():
        for k, v in mem["stats"].items():
            agg[k] += v
        stats["history"] += [dict(h, npr=eid) for h in mem["history"]]
        stats["bugs"] += mem.get("bugs", [])
    stats.update(agg)
    stats["state"] = st


def match(seed: int, turns: int = 60, lineup: str = "mix", size: int = 16) -> dict:
    """Bots in player seats.  Returns per-kind curves, rejections, winner."""
    if lineup == "mix":
        kinds = ["bot" if i % 2 == 0 else "base" for i in range(size)]
    elif lineup == "self":
        kinds = ["bot"] * size
    elif lineup == "base":
        kinds = ["base"] * size
    else:
        raise ValueError(lineup)
    st = new_game(f"match{seed}", seed, [f"{k.capitalize()}{i + 1}" for i, k in
                                         enumerate(kinds)], size=size)
    seat = {i + 1: k for i, k in enumerate(kinds)}
    for eid, k in seat.items():
        if k == "bot":
            memory(st, eid, PERSONA_ORDER[(eid // 2 + seed) % len(PERSONA_ORDER)])
        else:
            memory(st, eid)
    from ..engine.turn import initial_results
    res = initial_results(st)
    boxes = {eid: inbox(res, eid) for eid in seat}
    out = {"seed": seed, "lineup": lineup, "turns": 0, "winner": None, "winner_kind": None,
           "seconds": [], "by_kind": {k: _new_stats() for k in set(kinds)},
           "final": {}, "personas": {}}
    for _ in range(turns):
        orders = {}
        for eid, k in seat.items():
            if st.empires[eid].kind == "dead":
                continue
            mem = memory(st, eid)
            mem["inbox"] = boxes[eid]
            v = view(st, boxes[eid], eid)
            v["game"]["turn"] = st.turn + 1          # the turn being planned
            rng = Rng(st.seed, st.turn + 1, f"npr{eid}")
            orders[eid] = bot_orders(v, mem, rng) if k == "bot" else \
                baseline_orders(v, mem, rng)
        t0 = time.perf_counter()
        res = run_turn(st, orders)
        out["seconds"].append(time.perf_counter() - t0)
        out["turns"] += 1
        boxes = {eid: inbox(res, eid) for eid in seat}
        for k, d in out["by_kind"].items():
            eids = {e for e, kk in seat.items() if kk == k}
            _count_orders(d, res, eids)
            _curves(d, st, eids)
        if st.winner is not None:
            out["winner"] = st.winner
            out["winner_kind"] = seat[st.winner]
            break
    for eid, k in seat.items():
        e = st.empires[eid]
        out["final"][eid] = {"kind": k, "vp": e.vp, "systems": sum(1 for s in st.systems
                                                                   if s.owner == eid),
                             "alive": e.kind != "dead",
                             "persona": st.npr_state[eid]["persona"]["name"] if k == "bot"
                             else "baseline"}
    for k, d in out["by_kind"].items():
        d["bugs"] = [b for eid, kk in seat.items() if kk == k
                     for b in st.npr_state[eid].get("bugs", [])]
    ranking = sorted(out["final"].items(), key=lambda kv: -kv[1]["vp"])
    out["ranking"] = [(eid, f["kind"], f["persona"], f["vp"], f["systems"])
                      for eid, f in ranking]
    out["state"] = st
    return out


def report(stats: dict) -> str:
    n, rej, secs = stats["orders"], stats["rejected"], stats["seconds"]
    lines = [f"seed {stats.get('seed')} size {stats.get('size', 16)} humans {stats.get('humans')} "
             f"turns {stats['turns']}",
             f"  NPR orders {n}, rejected {rej} ({100.0 * rej / max(1, n):.2f}%)",
             f"  NPR systems (every 5th): {stats['systems'][::5]} -> {stats['systems'][-1]}",
             f"  NPR ships   (every 5th): {stats['ships'][::5]} -> {stats['ships'][-1]}",
             f"  mean NPR VP (every 5th): {stats['vp'][::5]} -> {stats['vp'][-1]}",
             f"  colonies {stats.get('colonies', 0)}, captures {stats.get('captures', 0)}, "
             f"missions {stats.get('missions', 0)}, wars {stats.get('wars', 0)}, peace "
             f"{stats.get('peace', 0)}, alliances {stats.get('alliances', 0)}, warnings "
             f"{stats.get('warnings', 0)}, combat evals {stats.get('evals', 0)}",
             f"  seconds/turn: mean {sum(secs) / len(secs):.3f}, max {max(secs):.3f}",
             f"  order mix: {dict(stats['codes'].most_common(22))}"]
    if stats["rejections"]:
        lines.append("  rejections: " + "; ".join(f"{k} x{v}" for k, v in
                                                   stats["rejections"].most_common(12)))
    if stats["bugs"]:
        lines.append(f"  bot order-construction bugs: {stats['bugs'][:5]}")
    return "\n".join(lines)


def match_report(m: dict) -> str:
    secs = m["seconds"]
    lines = [f"match seed {m['seed']} lineup {m['lineup']} turns {m['turns']} winner "
             f"{m['winner']} ({m['winner_kind']})",
             f"  seconds/turn: mean {sum(secs) / len(secs):.3f}, max {max(secs):.3f}"]
    for k, d in sorted(m["by_kind"].items()):
        n, rej = d["orders"], d["rejected"]
        lines.append(f"  {k:5s}: mean VP (every 10th) {d['vp'][::10]} -> {d['vp'][-1]}; "
                     f"systems {d['systems'][::10]} -> {d['systems'][-1]}; orders {n}, "
                     f"rejected {rej} ({100.0 * rej / max(1, n):.2f}%)")
        if d["rejections"]:
            lines.append("         rejections: " + "; ".join(
                f"{x} x{v}" for x, v in d["rejections"].most_common(6)))
        if d["bugs"]:
            lines.append(f"         bugs: {d['bugs'][:3]}")
    lines.append("  ranking (id, kind, persona, VP, systems): " +
                 ", ".join(str(r) for r in m["ranking"][:8]))
    return "\n".join(lines)


def _avg(xs):
    return sum(xs) / max(1, len(xs))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "match":
        m = match(int(a[1]) if len(a) > 1 else 1, int(a[2]) if len(a) > 2 else 60,
                  a[3] if len(a) > 3 else "mix", int(a[4]) if len(a) > 4 else 16)
        print(match_report(m))
    else:
        a = a[1:] if a and a[0] == "npr" else a
        s = simulate(int(a[0]) if a else 1, int(a[1]) if len(a) > 1 else 0,
                     int(a[2]) if len(a) > 2 else 40, a[3] if len(a) > 3 else "none",
                     int(a[4]) if len(a) > 4 else 16)
        print(report(s))

_ = defaultdict
