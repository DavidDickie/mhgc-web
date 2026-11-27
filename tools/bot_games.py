#!/usr/bin/env python3
"""Bot measurement harness (Dave 2026-11-15): play games without the web app and write each one
as an analysis export directory that `tools/analyze_game.py` reads; then summarise many games.

    python tools/bot_games.py play OUT_DIR --seed 1 --size 16 --turns 70 --mode npr
    python tools/bot_games.py play OUT_DIR --seed 1 --size 16 --mode human     # seat 1 = baseline
    python tools/bot_games.py play OUT_DIR --mode human --accept-peace   # ... which EWAs when asked
    python tools/bot_games.py play OUT_DIR --seed 1 --size 16 --mode h2h --old ~/x/mhgc/npr [--swap]
    python tools/bot_games.py summary DIR [DIR ...] [--groups]

Modes
  npr    every seat a computer empire, run by the engine's default bot (`mhgc.npr`).
  human  seat 1 is a human seat played by the baseline bot from its own view (as
         tools/sample_game.py does through the API); the rest are computer empires.
  h2h    every seat a computer empire; even seats play the current bot and odd seats the bot
         package at `--old` (a copy of an older `mhgc/npr`, loaded as `mhgc.npr_old`, using this
         tree's engine and rules).  `--swap` gives the current bot the odd seats instead.
`--root DIR` imports `mhgc` from DIR instead of this tree (to play an older snapshot whole).

Each game directory holds manifest.json (with `seconds`: time per turn including the bots, and
`bots`: which bot played each seat in h2h), standings.jsonl, botlog.jsonl,
turns/NNNN/orders.json, turns/NNNN/results.json (events only, to keep it small) and
final_state.json.  Nothing here changes how a game plays.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace as NS

HERE = Path(__file__).resolve().parent


def _setup_path(root: str | None) -> None:
    sys.path.insert(0, str(Path(root).expanduser().resolve()) if root else str(HERE.parent))
    sys.path.insert(1, str(HERE))


def load_old_npr(path: str):
    """Load another copy of the bot package as `mhgc.npr_old` (its `..data` etc. imports resolve
    to this tree's `mhgc`)."""
    p = Path(path).expanduser().resolve()
    name = "mhgc.npr_old"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, p / "__init__.py",
                                                  submodule_search_locations=[str(p)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _accept_peace(st, res, hid: int) -> list:
    """`--accept-peace`: the human seat answers a MESSAGE asking for peace from a race it is at
    war with by EWA (the baseline bot has no diplomacy, so it never would)."""
    from mhgc.orders import make_order
    rep = res.reports.get(hid)
    out, seen = [], set()
    for m in (rep.messages if rep else []):
        rid = m.get("from")
        if isinstance(rid, int) and rid not in seen and "peace" in (m.get("text") or "").lower() \
                and st.empires[hid].relations.get(rid) == "W" and rid in st.empires:
            seen.add(rid)
            out.append(make_order("EWA", race=st.empires[rid].name))
    return out


def _light_before(st):
    """What `analysis.spending` needs of the state at the turn's start (prices)."""
    return NS(empires=dict(st.empires),
              systems=[NS(name=s.name, status=s.status, starport=s.starport) for s in st.systems])


def _order_rows(olist, rep, by: str) -> list[dict]:
    got = {r.index: r for r in (rep.orders if rep else [])}
    out = []
    for i, o in enumerate(olist):
        r = got.get(i)
        out.append({"i": i, **o.to_dict(), "text": o.to_text(), "by": by,
                    "ok": None if r is None else bool(r.ok),
                    "error": None if r is None or r.ok else r.error})
    return out


def _events_only(res) -> dict:
    return {"turn": res.turn, "winner": res.winner,
            "reports": {str(eid): {"events": [{"kind": e.kind, "system": e.system,
                                               "data": {k: v for k, v in e.data.items()
                                                        if isinstance(v, (int, float, str))}}
                                              for e in rep.events]}
                        for eid, rep in res.reports.items()}}


def play(out: Path, seed: int, size: int = 16, turns: int = 70, mode: str = "npr",
         old: str | None = None, swap: bool = False, human_race: str = "Scripties",
         quiet: bool = False, accept_peace: bool = False) -> dict:
    from mhgc import model as M
    from mhgc.analysis import personas, spending, standings
    from mhgc.data import constants as K
    from mhgc.engine.turn import initial_results, run_turn
    from mhgc.mapgen import new_game
    from mhgc.npr import trace as ntrace
    from mhgc.npr.baseline import baseline_orders
    from mhgc.npr.brain import inbox
    from mhgc.npr.memory import new_memory
    from mhgc.rng import Rng
    from mhgc.view import view
    import mhgc.npr as new_npr

    humans = [human_race] if mode == "human" else []
    st = new_game(f"{mode}-{size}-{seed}", seed, humans, size=size)
    bots: dict[int, str] = {}
    old_npr = load_old_npr(old) if mode == "h2h" else None
    for eid, e in st.empires.items():
        if e.kind == M.NPR:
            bots[eid] = "new" if mode != "h2h" else (
                "new" if (eid % 2 == 0) != swap else "old")
    out.mkdir(parents=True, exist_ok=True)
    (out / "turns").mkdir(exist_ok=True)
    hum_ids = set(range(1, len(humans) + 1))
    res = initial_results(st)
    lines_st = [standings(st, len(humans), None, personas(st), hum_ids)]
    botlines = []
    base_mem = new_memory(seed, 1, 0, "builder")
    seconds = []

    class Dispatch(ntrace.Tracer):
        def __call__(self, state, eid):
            mod = old_npr if bots.get(eid) == "old" else new_npr
            orders, rec = mod.npr_orders_traced(state, eid)
            self.orders[eid] = list(orders)
            if rec is not None:
                rec["bot"] = bots.get(eid)
                self.records[eid] = rec
            return orders

    for _ in range(turns):
        if st.winner is not None:
            break
        human_orders = {}
        if mode == "human":
            box = inbox(res, 1)
            if st.empires[1].kind == M.HUMAN:
                v = view(st, box, 1)
                v["game"]["turn"] = st.turn + 1
                human_orders[1] = baseline_orders(v, base_mem, Rng(seed, st.turn + 1,
                                                                    "scripted-human"))
                if accept_peace:
                    human_orders[1] += _accept_peace(st, res, 1)
        before = _light_before(st)
        tr = Dispatch()
        t0 = time.perf_counter()
        res = run_turn(st, dict(human_orders), npr_fn=tr)
        seconds.append(round(time.perf_counter() - t0, 4))
        all_orders = dict(tr.orders)
        all_orders.update(human_orders)
        orows = {str(eid): _order_rows(all_orders[eid], res.reports.get(eid),
                                       "human" if eid in human_orders else "computer")
                 for eid in sorted(all_orders)}
        botlines += tr.finish(st, res)
        lines_st.append(standings(st, len(humans), spending(before, all_orders, res),
                                  personas(st), hum_ids))
        d = out / "turns" / f"{st.turn:04d}"
        d.mkdir(exist_ok=True)
        (d / "orders.json").write_text(json.dumps(orows, separators=(",", ":")))
        (d / "results.json").write_text(json.dumps(_events_only(res), separators=(",", ":")))
        if not quiet and st.turn % 10 == 0:
            print(f"{out.name}: turn {st.turn} {seconds[-1]:.2f}s", file=sys.stderr)
    with open(out / "standings.jsonl", "w") as fh:
        for x in lines_st:
            fh.write(json.dumps(x, separators=(",", ":"), sort_keys=True) + "\n")
    with open(out / "botlog.jsonl", "w") as fh:
        for x in botlines:
            fh.write(json.dumps(x, separators=(",", ":"), sort_keys=True) + "\n")
    pers = personas(st)
    man = {"format": "mhgc-analysis-1", "reason": f"tools/bot_games.py {mode}",
           "accept_peace": accept_peace,
           "game": {"name": st.name, "seed": seed, "size": size, "board": st.board,
                    "humans": len(humans), "vp_to_win": st.vp_to_win, "turn": st.turn,
                    "finished": st.winner is not None, "winner": st.winner, "mode": mode,
                    "swap": swap},
           "empires": [{"id": eid, "name": e.name, "human": eid in hum_ids,
                        "persona": pers.get(eid), "bot": bots.get(eid)}
                       for eid, e in sorted(st.empires.items()) if eid],
           "seconds": seconds}
    (out / "manifest.json").write_text(json.dumps(man, indent=1))
    (out / "final_state.json").write_text(M.dumps(st))
    return man


# ---------------------------------------------------------------------------- summary
def game_metrics(path: Path) -> dict:
    import analyze_game as A
    data = A.load(path)
    man = data["manifest"]
    g = man.get("game", {})
    rs = A.races(data)
    bots = {e["id"]: e.get("bot") for e in man.get("empires", [])}
    last = {e["id"]: e for e in data["standings"][-1]["empires"]}
    ws = A.wars(data, rs)
    caps = Counter()
    for eid, evs in data["events"].items():
        caps[eid] = sum(1 for e in evs if e[1] == "system_captured" and e[2])
    spend = {r["id"]: A.spend_totals(data, r["id"]) for r in rs}
    spy_orders = Counter()
    trades = launches = 0
    early = Counter()
    for r in data["standings"]:
        if r["turn"] <= 30:
            for e in r["empires"]:
                if not e.get("human"):
                    for k, v in (e.get("spend") or {}).items():
                        early[k] += v.get("eu", 0) + v.get("iu", 0)
    orders = rej = 0
    for t, by in data["orders"].items():
        for k, ol in by.items():
            for o in ol:
                if o.get("by") != "computer":
                    continue
                orders += 1
                rej += o.get("ok") is False
                if o.get("ok") and o["code"] == "TTNPR":
                    trades += 1
                if o.get("ok") and o["code"] == "CF":
                    launches += 1
                if A.GROUP_OF.get(o["code"]) == "spies" or (o["code"] == "BT" and
                                                             o.get("artifact") == "S"):
                    spy_orders[int(k)] += 1
    turns = sorted(r["turn"] for r in data["standings"])
    curve = {}
    for key in ("systems", "nnp", "vp"):
        curve[key] = {t: _mean([A.series(data, r["id"], key).get(t) for r in rs
                                if not r["human"]]) for t in turns}
    winner = g.get("winner")
    secs = man.get("seconds") or []
    return {"path": str(path), "mode": g.get("mode"), "size": g.get("size"), "seed": g.get("seed"),
            "swap": g.get("swap"), "turn": g.get("turn"), "winner": winner,
            "winner_label": None if winner is None else
            next((("human" if r["human"] else (bots.get(r["id"]) or "bot")) + "/" +
                  r["label"].split("/")[-1] for r in rs if r["id"] == winner), None),
            "races": rs, "bots": bots, "last": last, "wars": ws, "caps": caps, "spend": spend,
            "spy_orders": spy_orders, "orders": orders, "rejected": rej, "curve": curve,
            "trades": trades, "launches": launches, "early": early,
            "sec_mean": _mean(secs), "sec_max": max(secs) if secs else 0}


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0


def _war_turns(wr: dict) -> int:
    """Turns spent at war, summed over an empire's wars (analyze_game.wars lists "T5-12")."""
    import re
    out = 0
    for item in wr.get("list", []):
        mt = re.search(r" T(\d+)-(\d+) ", item)
        if mt:
            out += int(mt.group(2)) - int(mt.group(1)) + 1
    return out


def _group_rows(ms, key) -> list[list]:
    """Per group (h2h: old/new; human games: human/bots) totals across games."""
    agg = defaultdict(lambda: defaultdict(float))
    for m in ms:
        for r in m["races"]:
            g = "human" if r["human"] else (m["bots"].get(r["id"]) or "bot")
            a = agg[g]
            last = m["last"][r["id"]]
            a["n"] += 1
            a["vp"] += last["vp"]
            a["systems"] += last["systems"]
            a["nnp"] += last["nnp"]
            a["techs"] += last.get("techs", 0)
            a["caps"] += m["caps"][r["id"]]
            a["won"] += m["wars"][r["id"]]["won"]
            a["lost"] += m["wars"][r["id"]]["lost"]
            a["nwars"] += m["wars"][r["id"]]["wars"]
            a["warturns"] += _war_turns(m["wars"][r["id"]])
            a["wins"] += 1 if m["winner"] == r["id"] else 0
            a["alive"] += 1 if last["systems"] > 0 else 0
            sp = m["spend"][r["id"]]
            a["spend"] += sum(sp.values())
            a["sp_starports"] += sp.get("starports", 0)
            a["sp_ships"] += sp.get("ships", 0)
            a["sp_spies"] += sp.get("spies", 0)
            a["sp_troops"] += sp.get("troops", 0)
            a["sp_techs"] += sp.get("techs", 0)
            a["top4"] += 1 if r["id"] in [x[0] for x in sorted(
                ((rr["id"], -m["last"][rr["id"]]["vp"], -m["last"][rr["id"]]["systems"])
                 for rr in m["races"]), key=lambda x: (x[1], x[2], x[0]))[:4]] else 0
    rows = []
    for g, a in sorted(agg.items()):
        n = a["n"]
        rows.append([g, int(n), a["wins"], a["top4"] / n * 100, a["vp"] / n, a["systems"] / n,
                     a["nnp"] / n, a["techs"] / n, a["caps"] / n, a["nwars"] / n,
                     a["warturns"] / n, a["won"] / n, a["lost"] / n,
                     a["alive"] / n * 100, 100 * a["sp_starports"] / max(1, a["spend"]),
                     100 * a["sp_ships"] / max(1, a["spend"]),
                     100 * a["sp_troops"] / max(1, a["spend"]),
                     100 * a["sp_techs"] / max(1, a["spend"]),
                     100 * a["sp_spies"] / max(1, a["spend"])])
    return rows


def summary(paths: list[Path], groups: bool = False) -> str:
    import analyze_game as A
    ms = [game_metrics(p) for p in paths]
    L = []
    head = ["Game", "Turns", "Winner", "Captures", "Caps/bot", "Fleets", "Wars", "W/L",
            "Spy orders", "Trades", "Spies %", "Starports %", "SP% T<=30", "Ships %",
            "Troops %", "Research %", "Sys (bots)", "NNP", "Techs", "VP", "Rejected",
            "s/turn (max)"]
    rows = []
    pool = defaultdict(list)
    for m in ms:
        bots = [r for r in m["races"] if not r["human"]]
        caps = sum(m["caps"][r["id"]] for r in bots)
        wars = sum(m["wars"][r["id"]]["wars"] for r in bots)
        won = sum(m["wars"][r["id"]]["won"] for r in bots)
        lost = sum(m["wars"][r["id"]]["lost"] for r in bots)
        tot = Counter()
        for r in bots:
            tot.update(m["spend"][r["id"]])
        s = sum(tot.values())
        es = sum(m["early"].values())
        vals = {"caps": caps, "capsbot": caps / max(1, len(bots)), "fleets": m["launches"],
                "wars": wars, "spy": sum(m["spy_orders"].values()), "trades": m["trades"],
                "spies": 100 * tot.get("spies", 0) / max(1, s),
                "sp": 100 * tot.get("starports", 0) / max(1, s),
                "sp30": 100 * m["early"].get("starports", 0) / max(1, es),
                "ships": 100 * tot.get("ships", 0) / max(1, s),
                "troops": 100 * tot.get("troops", 0) / max(1, s),
                "research": 100 * tot.get("techs", 0) / max(1, s),
                "techs": _mean([m["last"][r["id"]].get("techs", 0) for r in bots]),
                "sys": _mean([m["last"][r["id"]]["systems"] for r in bots]),
                "nnp": _mean([m["last"][r["id"]]["nnp"] for r in bots]),
                "vp": _mean([m["last"][r["id"]]["vp"] for r in bots]),
                "rej": 100 * m["rejected"] / max(1, m["orders"]), "sec": m["sec_mean"],
                "turn": m["turn"], "won": m["winner"] is not None}
        for k, v in vals.items():
            pool[k].append(float(v))
        rows.append([f"{m['mode']}-{m['size']}-s{m['seed']}" + ("x" if m["swap"] else ""),
                     m["turn"], (f"{m['winner_label']}@T{m['turn']}" if m["winner"] is not None
                                 else "-"), caps, caps / max(1, len(bots)), m["launches"], wars,
                     f"{won}/{lost}", sum(m["spy_orders"].values()), m["trades"],
                     A.pct(tot.get("spies", 0), s), A.pct(tot.get("starports", 0), s),
                     f"{vals['sp30']:.0f}%", A.pct(tot.get("ships", 0), s),
                     A.pct(tot.get("troops", 0), s), A.pct(tot.get("techs", 0), s),
                     _mean([m["last"][r["id"]]["systems"] for r in bots]),
                     _mean([m["last"][r["id"]]["nnp"] for r in bots]), vals["techs"],
                     _mean([m["last"][r["id"]]["vp"] for r in bots]),
                     A.pct(m["rejected"], m["orders"]),
                     f"{m['sec_mean']:.2f} ({m['sec_max']:.2f})"])
    if len(ms) > 1:
        P = {k: _mean(v) for k, v in pool.items()}
        rows.append([f"MEAN of {len(ms)}", P["turn"], f"{int(sum(pool['won']))} won",
                     P["caps"], P["capsbot"], P["fleets"], P["wars"], "", P["spy"],
                     P["trades"], f"{P['spies']:.1f}%", f"{P['sp']:.1f}%", f"{P['sp30']:.1f}%",
                     f"{P['ships']:.1f}%", f"{P['troops']:.1f}%", f"{P['research']:.1f}%",
                     P["sys"], P["nnp"], P["techs"], P["vp"], f"{P['rej']:.2f}%",
                     f"{P['sec']:.2f}"])
    L.append(A.table(head, rows))
    L.append("")
    L.append("Curves (mean over computer empires, every 10 turns): systems / NNP / VP")
    for m in ms:
        ts = [t for t in sorted(m["curve"]["vp"]) if t % 10 == 0]
        L.append(f"  {m['mode']}-{m['size']}-s{m['seed']}{'x' if m['swap'] else ''}: " +
                 "  ".join(f"T{t} {m['curve']['systems'][t]:.1f}/{m['curve']['nnp'][t]:.0f}/"
                           f"{m['curve']['vp'][t]:.0f}" for t in ts))
    if groups:
        L.append("")
        L.append("By group, per empire (h2h: new vs old bot; human games: the baseline human vs "
                 "the bots):")
        L.append(A.table(["Group", "Empires", "Wins", "Top-4 %", "VP", "Systems", "NNP",
                          "Techs", "Captures", "Wars", "War turns", "Wars won", "Wars lost",
                          "Alive %",
                          "Starports %", "Ships %", "Troops %", "Research %", "Spies %"],
                         _group_rows(ms, None)))
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("play")
    p.add_argument("out", type=Path)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--size", type=int, default=16)
    p.add_argument("--turns", type=int, default=70)
    p.add_argument("--mode", choices=("npr", "human", "h2h"), default="npr")
    p.add_argument("--old", default=None)
    p.add_argument("--swap", action="store_true")
    p.add_argument("--race", default="Scripties")
    p.add_argument("--root", default=None)
    p.add_argument("--accept-peace", action="store_true",
                   help="human mode: the human seat EWAs when a race at war asks for peace")
    s = sub.add_parser("summary")
    s.add_argument("dirs", type=Path, nargs="+")
    s.add_argument("--groups", action="store_true")
    s.add_argument("--root", default=None)
    a = ap.parse_args(argv)
    _setup_path(a.root)
    if a.cmd == "play":
        if a.mode == "h2h" and not a.old:
            ap.error("--mode h2h needs --old PATH (an older mhgc/npr package)")
        man = play(a.out, a.seed, a.size, a.turns, a.mode, a.old, a.swap, a.race,
                   accept_peace=a.accept_peace)
        secs = man["seconds"]
        print(f"{a.out}: turn {man['game']['turn']}, winner {man['game']['winner']}, "
              f"{_mean(secs):.2f}s per turn", file=sys.stderr)
        return 0
    print(summary(a.dirs, a.groups))
    return 0


if __name__ == "__main__":
    sys.exit(main())
