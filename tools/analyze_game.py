#!/usr/bin/env python3
"""Summarise an MHGC game export ("Export game for analysis") per race, for comparing a human's
play with the computer empires'.

    python tools/analyze_game.py mhgc-<id>-turnN.zip            # or an unzipped directory
    python tools/analyze_game.py export.zip --every 5 --race Dave

Needs only the Python standard library (no need for the game's code).  Sections:
  overview, expansion and economy curves, human vs computer comparison, spending mix, order mix,
  wars (started / won / lost / drawn), captures, rejection rates, milestones, and for computer
  empires their most common decision reasons and rejection causes (from botlog.jsonl).

A war is a run of turns in which one empire's own stance to another is "at war" (W, or E =
peace offered).  It is won by the side that took more systems from the other during it (lost if
fewer, drawn if equal or none); "started" means that empire's DW order opened it.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

GROUPS = {
    "build": "BS BCU BT BI BSP DI DT DSP",
    "research": "PT CRP",
    "ship moves": "MO MS I G SP CSCR DS SS WTP",
    "cargo": "L U UG SL LOCT LACT DOCT CTT",
    "fleets": "CF CFXY AFXY AF LF MF MFS FIS DF FR FS CFP CFCR FL FU FUG FLOCT FLACT WTPF",
    # CGR was retired (2026-11-14, orders.RETIRED); kept here so older exports still group it
    "economy": "CSP CAP CAPN CGR SISD CI TP SR AUTOSISD NOAUTOSISD LT",
    "troops": "DCT SCT CCP",
    "leaders": "CLN ML MLF PLOI LR",
    "spies": "SMV SMO SET SOS SOT SOL SVS SOE SOM SON SAL SSB SUP SRS SSI",
    "diplomacy": "DA DW EWA GE GT GS TTNPR MESSAGE DD SD",
    "naming": "NSY CRN",
}
GROUP_OF = {c: g for g, codes in GROUPS.items() for c in codes.split()}
SPEND = ("ships", "troops", "techs", "infrastructure", "starports", "artifacts", "spies")
CURVES = (("systems", "Systems", 0), ("pop", "Population", 0), ("nnp", "NNP (net production)", 0),
          ("vp", "Victory points", 0), ("techs", "Technologies", 0), ("eu", "EU stockpile", 0),
          ("warships", "Warships", 0), ("troops", "Combat troops", 0),
          ("happiness", "Happiness", 2))
MILESTONES = (("systems", (3, 5, 10, 15, 20)), ("pop", (25, 50, 100, 150)),
              ("vp", (25, 50, 75, 100)), ("techs", (5, 10, 20, 30)), ("warships", (5, 10, 25)))


# ---------------------------------------------------------------- loading
class Export:
    def __init__(self, path: Path):
        self.path = path
        self.zip = zipfile.ZipFile(path) if path.is_file() else None

    def names(self) -> list[str]:
        if self.zip:
            return self.zip.namelist()
        return [str(p.relative_to(self.path)) for p in self.path.rglob("*") if p.is_file()]

    def text(self, name: str) -> str | None:
        try:
            if self.zip:
                return self.zip.read(name).decode("utf-8")
            return (self.path / name).read_text(encoding="utf-8")
        except (KeyError, FileNotFoundError):
            return None

    def json(self, name: str):
        t = self.text(name)
        return None if t is None else json.loads(t)

    def jsonl(self, name: str) -> list[dict]:
        t = self.text(name) or ""
        return [json.loads(x) for x in t.splitlines() if x.strip()]


def load(path: Path) -> dict:
    ex = Export(path)
    man = ex.json("manifest.json") or {}
    stand = sorted(ex.jsonl("standings.jsonl"), key=lambda r: r["turn"])
    bot = ex.jsonl("botlog.jsonl")
    turns = sorted({int(n.split("/")[1]) for n in ex.names()
                    if n.startswith("turns/") and n.count("/") == 2})
    orders, events = {}, defaultdict(list)
    for n in turns:
        orders[n] = ex.json(f"turns/{n:04d}/orders.json") or {}
        res = ex.json(f"turns/{n:04d}/results.json") or {}
        for k, rep in (res.get("reports") or {}).items():
            for ev in rep.get("events") or []:
                if ev.get("kind") in ("system_captured", "system_lost", "colonized", "rebellion",
                                      "extinction", "victory"):
                    events[int(k)].append((n, ev.get("kind"), (ev.get("data") or {}).get("race"),
                                           ev.get("system")))
    return {"manifest": man, "standings": stand, "botlog": bot, "orders": orders,
            "events": events}


# ---------------------------------------------------------------- formatting
def table(head: list[str], rows: list[list], right_from: int = 1) -> str:
    cells = [[str(c) for c in head]] + [[_fmt(c) for c in r] for r in rows]
    w = [max(len(r[i]) for r in cells) for i in range(len(head))]
    out = []
    for j, r in enumerate(cells):
        out.append("  ".join(c.rjust(w[i]) if i >= right_from else c.ljust(w[i])
                             for i, c in enumerate(r)).rstrip())
        if j == 0:
            out.append("  ".join("-" * x for x in w))
    return "\n".join(out)


def _fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        if abs(v) >= 100:
            return f"{v:.0f}"
        return f"{v:.2f}" if abs(v) < 10 else f"{v:.1f}"
    return str(v)


def pct(a, b) -> str:
    return f"{100 * a / b:.0f}%" if b else "-"


# ---------------------------------------------------------------- analysis
def races(data) -> list[dict]:
    last = data["standings"][-1]["empires"] if data["standings"] else []
    man = {e["id"]: e for e in data["manifest"].get("empires", [])}
    out = []
    for e in last:
        m = man.get(e["id"], {})
        label = "human" if e["human"] else f"bot/{e.get('persona') or m.get('persona') or '?'}"
        out.append({"id": e["id"], "name": e["name"], "human": e["human"], "label": label,
                    "player": m.get("player")})
    out.sort(key=lambda r: (not r["human"], r["id"]))
    return out


def series(data, eid: int, key: str) -> dict[int, float]:
    out = {}
    for r in data["standings"]:
        for e in r["empires"]:
            if e["id"] == eid:
                out[r["turn"]] = e.get(key, e["stats"].get(key))
    return out


def wars(data, rs) -> dict[int, dict]:
    """Per empire: wars started/joined, won/lost/drawn (by captures from that opponent)."""
    name = {r["id"]: r["name"] for r in rs}
    caps = defaultdict(list)                  # (taker, loser) -> [turn]
    for eid, evs in data["events"].items():
        for t, kind, other, _sys in evs:
            if kind == "system_captured" and isinstance(other, int) and other:
                caps[(eid, other)].append(t)
    dw = set()                                # (turn, empire, race name) of successful DWs
    for t, by in data["orders"].items():
        for k, olist in by.items():
            for o in olist:
                if o.get("code") == "DW" and o.get("ok"):
                    dw.add((t, int(k), o.get("race")))
    spans = defaultdict(list)                 # (a, b) -> [[start, end]]
    prev: dict[tuple, int] = {}
    for r in data["standings"]:
        t = r["turn"]
        now = set()
        for e in r["empires"]:
            for b in e.get("at_war") or []:
                now.add((e["id"], b))
        for key in now:
            if key not in prev:
                spans[key].append([t, t])
            spans[key][-1][1] = t
        prev = {k: 1 for k in now}
    out = {r["id"]: {"wars": 0, "started": 0, "won": 0, "lost": 0, "drawn": 0, "list": []}
           for r in rs}
    for (a, b), runs in spans.items():
        if a not in out:
            continue
        for s, e in runs:
            took = sum(1 for t in caps[(a, b)] if s <= t <= e + 1)
            gave = sum(1 for t in caps[(b, a)] if s <= t <= e + 1)
            started = any((t, a, name.get(b)) in dw for t in range(s - 1, s + 1))
            res = "won" if took > gave else "lost" if gave > took else "drawn"
            d = out[a]
            d["wars"] += 1
            d["started"] += started
            d[res] += 1
            d["list"].append(f"{name.get(b, b)} T{s}-{e} {res} ({took}:{gave})"
                             + (" started" if started else ""))
    return out


def order_stats(data, eid: int):
    codes, groups = Counter(), Counter()
    total = rej = 0
    errs = Counter()
    for t, by in data["orders"].items():
        for o in by.get(str(eid), []):
            total += 1
            codes[o["code"]] += 1
            groups[GROUP_OF.get(o["code"], "other")] += 1
            if o.get("ok") is False:
                rej += 1
                errs[_short_err(o.get("code"), o.get("error"))] += 1
    return total, rej, codes, groups, errs


def _short_err(code, err) -> str:
    err = (err or "?").split(". ")[0]
    for ch in "0123456789":
        err = err.replace(ch, "#")
    while "##" in err:
        err = err.replace("##", "#")
    return f"{code}: {err[:70]}"


def spend_totals(data, eid: int) -> dict[str, int]:
    tot = Counter()
    for r in data["standings"]:
        for e in r["empires"]:
            if e["id"] == eid:
                for k, v in (e.get("spend") or {}).items():
                    tot[k] += v.get("eu", 0) + v.get("iu", 0)
    return tot


def milestones(data, eid: int) -> list[str]:
    out = []
    for key, steps in MILESTONES:
        s = series(data, eid, key)
        for x in steps:
            t = next((t for t in sorted(s) if (s[t] or 0) >= x), None)
            if t is not None:
                out.append(f"{key}>={x}@T{t}")
    caps = [t for t, k, *_ in data["events"].get(eid, []) if k == "system_captured"]
    if caps:
        out.append(f"first capture@T{min(caps)}")
    for r in data["standings"]:
        e = next((e for e in r["empires"] if e["id"] == eid), None)
        if e and e.get("at_war"):
            out.append(f"first war@T{r['turn']}")
            break
    return out


# ---------------------------------------------------------------- the report
def report(data, every: int, only: str | None) -> str:
    man = data["manifest"]
    g = man.get("game", {})
    rs = races(data)
    if only:
        keep = {r["id"] for r in rs if only.lower() in r["name"].lower()
                or (r["player"] or "").lower() == only.lower()}
    else:
        keep = {r["id"] for r in rs}
    sel = [r for r in rs if r["id"] in keep]
    turns = [r["turn"] for r in data["standings"]]
    last_t = turns[-1] if turns else 0
    winner = g.get("winner")
    name = {r["id"]: r["name"] for r in rs}
    L = []
    L.append(f"MHGC game analysis: {g.get('name', '?')} ({g.get('size', '?')} empires, "
             f"{g.get('board', '?')}x{g.get('board', '?')}, {g.get('humans', '?')} human seat(s))")
    L.append(f"Turns 0-{last_t}; " + (f"winner: {name.get(winner, winner)}" if winner else
                                     "not finished") + f"; exported ({man.get('reason', '?')})")
    L.append("")

    last = {e["id"]: e for e in data["standings"][-1]["empires"]} if turns else {}
    order_rank = sorted(rs, key=lambda r: (-last[r["id"]]["vp"], -last[r["id"]]["systems"],
                                           r["id"]))
    rank = {r["id"]: i + 1 for i, r in enumerate(order_rank)}
    L.append("== Overview (final turn) ==")
    L.append(table(["Race", "Who", "Rank", "VP", "Sys", "Pop", "NNP", "Tech", "War", "CT",
                    "EU", "Hap"],
                   [[r["name"] + (" *" if r["id"] == winner else ""), r["label"], rank[r["id"]],
                     last[r["id"]]["vp"], last[r["id"]]["systems"], last[r["id"]]["pop"],
                     last[r["id"]]["nnp"], last[r["id"]]["techs"], last[r["id"]]["warships"],
                     last[r["id"]]["troops"], last[r["id"]]["eu"], last[r["id"]]["happiness"]]
                    for r in order_rank if r["id"] in keep], right_from=2))
    if any(e.get("ranks") for e in last.values() if not e.get("human")):
        L.append("Rank: by VP, then systems.  Everyone's VP include the stat-ranking bonus: "
                 "ranks are over all races, humans and computer empires (DECISIONS A-06).")
    else:
        L.append("Rank: by VP, then systems.  Humans' VP include the stat-ranking bonus (in "
                 "games before 2026-11-15 ranks were among human players only, rules:238-239); "
                 "computer empires' VP don't, so the two aren't comparable.")
    L.append("")

    picks = sorted(set([t for t in turns if t % every == 0] + [last_t]))
    for key, label, _ in CURVES:
        L.append(f"== {label} by turn ==")
        rows = []
        for r in sel:
            s = series(data, r["id"], key)
            rows.append([r["name"], r["label"]] + [s.get(t) for t in picks])
        L.append(table(["Race", "Who"] + [f"T{t}" for t in picks], rows, right_from=2))
        L.append("")

    humans = [r for r in rs if r["human"]]
    bots = [r for r in rs if not r["human"]]
    if humans and bots:
        L.append("== Human vs computer (human value / computer mean / computer best) ==")
        for h in humans:
            rows = []
            for key, label, _ in CURVES[:7]:
                row = [label]
                for t in picks:
                    hv = series(data, h["id"], key).get(t)
                    bv = [series(data, b["id"], key).get(t) for b in bots]
                    bv = [x for x in bv if x is not None]
                    mean = sum(bv) / len(bv) if bv else None
                    row.append(f"{_fmt(hv)}/{_fmt(mean)}/{_fmt(max(bv) if bv else None)}")
                rows.append(row)
            L.append(f"-- {h['name']} --")
            L.append(table(["Measure"] + [f"T{t}" for t in picks], rows))
            L.append("")

    L.append("== Spending mix (EU+IU by orders that succeeded, % of total) ==")
    rows = []
    for r in sel:
        tot = spend_totals(data, r["id"])
        s = sum(tot.values())
        rows.append([r["name"], r["label"], s] + [pct(tot.get(k, 0), s) for k in SPEND])
    L.append(table(["Race", "Who", "Total"] + list(SPEND), rows, right_from=2))
    L.append("")

    L.append("== Order mix (% of orders) and rejections ==")
    rows = []
    gnames = list(GROUPS) + ["other"]
    rej_detail = {}
    for r in sel:
        total, rej, codes, groups, errs = order_stats(data, r["id"])
        rej_detail[r["id"]] = errs
        rows.append([r["name"], r["label"], total, f"{total / max(1, len(turns) - 1):.1f}",
                     pct(rej, total)] + [pct(groups.get(gname, 0), total) for gname in gnames])
    L.append(table(["Race", "Who", "Orders", "/turn", "Rejected"] + gnames, rows, right_from=2))
    L.append("")
    L.append("Top order codes:")
    for r in sel:
        _, _, codes, _, _ = order_stats(data, r["id"])
        L.append(f"  {r['name']:<14} " + ", ".join(f"{c} {n}" for c, n in codes.most_common(8)))
    L.append("")

    L.append("== Wars and captures ==")
    ws = wars(data, rs)
    rows = []
    for r in sel:
        w = ws[r["id"]]
        evs = data["events"].get(r["id"], [])
        took = sum(1 for e in evs if e[1] == "system_captured")
        lost = sum(1 for e in evs if e[1] == "system_lost")
        col = sum(1 for e in evs if e[1] == "colonized")
        reb = sum(1 for e in evs if e[1] == "rebellion")
        rows.append([r["name"], r["label"], w["wars"], w["started"], w["won"], w["lost"],
                     w["drawn"], took, lost, col, reb])
    L.append(table(["Race", "Who", "Wars", "Started", "Won", "Lost", "Drawn", "Captured",
                    "Lost sys", "Settled", "Rebellions"], rows, right_from=2))
    for r in sel:
        if ws[r["id"]]["list"]:
            L.append(f"  {r['name']}: " + "; ".join(ws[r["id"]]["list"][:8]))
    L.append("")

    L.append("== Milestones (first turn reached) ==")
    for r in sel:
        L.append(f"  {r['name']:<14} {r['label']:<17} " + " ".join(milestones(data, r["id"])))
    L.append("")

    L.append("== Most common rejections ==")
    for r in sel:
        errs = rej_detail.get(r["id"])
        if errs:
            L.append(f"  {r['name']}: " + "; ".join(f"{e} x{n}" for e, n in errs.most_common(3)))
    L.append("")

    if data["botlog"]:
        L.append("== Computer empires: top decision reasons (share of orders) ==")
        by = defaultdict(Counter)
        decisions = defaultdict(Counter)
        modes = defaultdict(Counter)
        for rec in data["botlog"]:
            if rec["empire"] not in keep:
                continue
            for o in rec["orders"]:
                by[rec["empire"]][o["rc"]] += 1
            for d in rec.get("decisions") or []:
                decisions[rec["empire"]][d["ev"]] += 1
            modes[rec["empire"]][rec["strategy"]["mode"]] += 1
        for r in sel:
            if r["id"] not in by:
                continue
            c = by[r["id"]]
            n = sum(c.values())
            L.append(f"  {r['name']:<14} {r['label']:<17} " +
                     ", ".join(f"{k} {pct(v, n)}" for k, v in c.most_common(6)))
            md = modes[r["id"]]
            L.append(f"  {'':<14} {'modes':<17} " +
                     ", ".join(f"{k} {v}" for k, v in md.most_common()))
            dd = decisions[r["id"]]
            if dd:
                L.append(f"  {'':<14} {'decisions':<17} " +
                         ", ".join(f"{k} {v}" for k, v in dd.most_common(8)))
        allc = Counter()
        for c in by.values():
            allc.update(c)
        n = sum(allc.values())
        L.append("")
        L.append("  All computer empires: " + ", ".join(f"{k} {pct(v, n)}"
                                                      for k, v in allc.most_common(12)))
        L.append("")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("export", type=Path, help="the export zip (or an unzipped directory)")
    ap.add_argument("--every", type=int, default=10, help="turn spacing of the curve tables")
    ap.add_argument("--race", help="only this race (name part) or player")
    a = ap.parse_args(argv)
    if not a.export.exists():
        print(f"No such file: {a.export}", file=sys.stderr)
        return 2
    data = load(a.export)
    if not data["standings"]:
        print("This export has no standings log.", file=sys.stderr)
        return 1
    print(report(data, max(1, a.every), a.race))
    return 0


if __name__ == "__main__":
    sys.exit(main())
