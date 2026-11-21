"""Analysis logs, the end-of-game standings and the analysis export (Dave 2026-11-14).

Files (per game, under SAVE_DIR/games/<gid>/; never served while the game runs, except as below)
  standings.jsonl      one line per turn: every empire's figures (mhgc/analysis.standings)
  botlog.jsonl         one line per computer empire per turn: what it saw, its strategic state,
                       every order with its reason code and note, which the engine rejected and
                       why, and its diplomacy and mission decisions (mhgc/npr/trace.py)
  turns/<n>/orders.json   every empire's orders that turn n ran, with ok/error
Both .jsonl files are append-only.  They are appended after the turn is committed; if a turn is
ever re-run (a crash between the commit and the append can't cause one, but a manual rollback
could), readers keep the LAST line per (turn) / (turn, empire).

Visibility (DECISIONS W-15..W-17)
  GET /api/games/{gid}/final    the all-race standings; only once the game is over, then for
                                anyone (as the lobby already shows the winner)
  GET /api/games/{gid}/export   a zip for offline analysis (tools/analyze_game.py).  Once the
                                game is over: any seated player.  Before that: the host, at any
                                time and in any game (Dave 2026-11-15, W-17: he accepts that
                                the host can see everything through an export).
"""
from __future__ import annotations

import io
import json
import logging
import time
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import Header, HTTPException
from fastapi.responses import Response

import mhgc
from mhgc import model as M
from mhgc.analysis import personas, spending, standings
from mhgc.data import constants as K

EXPORT_FORMAT = "mhgc-analysis-1"
SERIES = ("vp", "systems", "pop", "nnp", "GNP", "eu", "iu_depot", "techs", "warships",
          "attack", "troops", "happiness", "STP", "ships")
log_ = logging.getLogger("mhgc")


# ---------------------------------------------------------------- writing (Game.run)
def _order_rows(olist, rep, by: str) -> list[dict]:
    got = {r.index: r for r in (rep.orders if rep else [])}
    out = []
    for i, o in enumerate(olist):
        r = got.get(i)
        out.append({"i": i, **o.to_dict(), "text": o.to_text(), "by": by,
                    "ok": None if r is None else bool(r.ok),
                    "error": None if r is None or r.ok else r.error})
    return out


def analysis_records(g, before: M.GameState, after: M.GameState, human_orders: dict,
                     tracer, res_obj) -> dict:
    """The turn's analysis records, computed in memory (the files are written by the caller)."""
    all_orders = dict(tracer.orders)
    all_orders.update(human_orders)
    orders = {}
    for eid in sorted(all_orders):
        orders[str(eid)] = _order_rows(all_orders[eid], res_obj.reports.get(eid),
                                       "human" if eid in human_orders else
                                       "aomt" if eid in getattr(tracer, "aomt", {}) else
                                       "computer")
    bot = tracer.finish(after, res_obj)
    conv = g.converted()
    for rec in bot:                    # the first turn a handed-over race plays as a bot (W-22)
        c = conv.get(rec.get("empire"))
        if c is not None and c["turn"] == before.turn:
            rec["converted"] = {"from": "human", "turn": c["turn"], "player": c.get("player")}
    return {"orders": orders, "botlog": bot,
            "standings": standings(after, g.humans, spending(before, all_orders, res_obj),
                                   personas(after), *g.seat_kinds(after.turn))}


def _append(path: Path, lines: list[dict]) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        for x in lines:
            fh.write(json.dumps(x, separators=(",", ":"), sort_keys=True) + "\n")
        fh.flush()


def write_analysis_logs(g, n: int, log: dict) -> None:
    """Append the turn's lines (after the commit; a failure here never loses the turn)."""
    try:
        _append(g.dir / "standings.jsonl", [log["standings"]])
        if log["botlog"]:
            _append(g.dir / "botlog.jsonl", log["botlog"])
    except OSError:
        log_.exception("analysis logs for %s turn %s", g.gid, n)


def start_logs(g) -> None:
    """Turn 0's standings line, at creation."""
    _append(g.dir / "standings.jsonl",
            [standings(g.state, g.humans, None, personas(g.state), *g.seat_kinds(0))])


# ---------------------------------------------------------------- reading
def read_jsonl(path: Path, key) -> list[dict]:
    """The lines of a .jsonl log, the last one per key, in key order."""
    if not path.exists():
        return []
    out: dict = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:            # a torn last line after a crash
                continue
            out[key(d)] = d
    return [out[k] for k in sorted(out)]


def standings_all(g) -> list[dict]:
    """Every turn's standings.  Turns missing from the log (games from before it existed) are
    rebuilt from the stored turn states (without the spending estimate) and the log rewritten."""
    rows = {d["turn"]: d for d in read_jsonl(g.dir / "standings.jsonl", lambda d: d["turn"])}
    missing = [n for n in range(0, g.state.turn + 1) if n not in rows]
    if missing:
        for n in missing:
            try:
                st = g.state if n == g.state.turn else M.loads(
                    (g.turn_dir(n) / "state.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            rows[n] = standings(st, g.humans, None, personas(st),
                                *g.seat_kinds(n)) | {"rebuilt": True}
        text = "".join(json.dumps(rows[n], separators=(",", ":"), sort_keys=True) + "\n"
                       for n in sorted(rows))
        from .main import _atomic_write
        _atomic_write(g.dir / "standings.jsonl", text)
    return [rows[n] for n in sorted(rows)]


def botlog_all(g) -> list[dict]:
    return read_jsonl(g.dir / "botlog.jsonl", lambda d: (d["turn"], d["empire"]))


# ---------------------------------------------------------------- permissions
def final_allowed(g) -> None:
    if g.state.winner is None:
        raise HTTPException(409, "The final standings are shown when the game is over. Until "
                                 "then each player sees only their own statistics.")


def export_allowed(g, token: Optional[str]) -> str:
    """-> the reason the export is allowed; raises 401/403 otherwise.  The host (its race or the
    host login) may export at any time (Dave 2026-11-15); any other race once the game is over."""
    host = g.host_principal(token) is not None
    if not host and g.seat_of(token) is None:
        raise HTTPException(401, "This browser isn't logged in to a race in this game")
    if g.state.winner is not None:
        return "game over"
    if host:
        return "host (any time, W-17)"
    raise HTTPException(403, "The game isn't over yet. Until the end only the host can "
                             "export it.")


# ---------------------------------------------------------------- views
def _relation(state: M.GameState, viewer: Optional[int], eid: int) -> str:
    if viewer is None:
        return "none"
    if eid == viewer:
        return "own"
    v = state.empires[viewer].relations.get(eid)
    if v is None:
        return "stranger"
    return "ally" if v == "A" else "war" if v in ("W", "E") else "neutral"


def _empires(g, viewer: Optional[int]) -> list[dict]:
    st = g.state
    ps = personas(st)
    hs = set(g.human_seats())
    changes = {c["eid"]: c for c in g.seat_log()}            # the latest change per empire
    out = []
    for eid in sorted(st.empires):
        e = st.empires[eid]
        if eid == 0 or e.kind not in (M.HUMAN, M.NPR, M.DEAD):
            continue
        c = changes.get(eid)
        human = eid in hs
        info = g.seat_info(eid) if human else None
        out.append({"id": eid, "name": e.name, "human": human,
                    "player": info["player"] if info else (c or {}).get("player"),
                    "persona": None if human else ps.get(eid),
                    "converted_turn": c["turn"] if c else None,
                    "kind": e.kind, "relation": _relation(st, viewer, eid)})
    return out


def final_view(g, viewer: Optional[int]) -> dict:
    rows = standings_all(g)
    emp = _empires(g, viewer)
    ids = [e["id"] for e in emp]
    turns = [r["turn"] for r in rows]
    series: dict[str, dict[str, list]] = {k: {str(i): [] for i in ids} for k in SERIES}
    for r in rows:
        by = {x["id"]: x for x in r["empires"]}
        for k in SERIES:
            for i in ids:
                x = by.get(i)
                v = None if x is None else (x["stats"].get(k) if k in x["stats"] else x.get(k))
                series[k][str(i)].append(v)
    last = rows[-1]["empires"] if rows else []
    # the winner first (on a VP tie the winner is decided by NNP, F-05), then by VP, systems
    # a host's race that couldn't win (W-28) is listed after the others, without a rank
    final = sorted(last, key=lambda x: (x["id"] != g.state.winner, bool(x.get("unranked")),
                                        -x["vp"], -x["systems"], -x["pop"], x["id"]))
    return {"game": g.summary(), "viewer": viewer, "vp_to_win": K.VICTORY_POINTS,
            "winner": g.state.winner, "empires": emp, "turns": turns, "series": series,
            "final": [{k: x[k] for k in ("id", "name", "human", "kind", "vp", "systems", "pop",
                                          "nnp", "eu", "iu_depot", "techs", "warships",
                                          "troops", "happiness", "ships", "attack")}
                      | {"unranked": bool(x.get("unranked")),
                         "rank": None if x.get("unranked") else i + 1}
                      for i, x in enumerate(final)]}


def _results(g, n: int) -> Optional[dict]:
    if n == g.state.turn:
        return g.results
    p = g.turn_dir(n) / "results.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _orders_of(g, n: int, res: Optional[dict]) -> dict:
    p = g.turn_dir(n) / "orders.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    out = {}                    # older turns: what the results recorded of each order
    for k, rep in ((res or {}).get("reports") or {}).items():
        if rep.get("orders"):
            out[str(k)] = [{"i": o["index"], "code": o["code"], "text": o["text"],
                            "by": "human" if int(k) in g.seat_kinds(n)[0] else "computer",
                            "ok": o["ok"], "error": o.get("error")} for o in rep["orders"]]
    return out


def export_zip(g, seat: int, reason: str) -> bytes:
    st = g.state
    rows = standings_all(g)
    bot = botlog_all(g)
    manifest = {
        "format": EXPORT_FORMAT, "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                              time.gmtime()),
        "exported_by_seat": seat, "reason": reason,
        "app_version": mhgc.__version__,
        "game": {"id": g.gid, "name": g.meta["name"], "seed": g.meta.get("seed"),
                 "size": g.size, "board": st.board, "bins": st.bins,
                 "empty_bins": [list(b) for b in st.empty_bins], "humans": g.humans,
                 "chatter": g.chatter, "vp_to_win": K.VICTORY_POINTS,
                 "created": g.meta.get("created"), "turn": st.turn,
                 "finished": st.winner is not None, "winner": st.winner},
        "empires": _empires(g, None),
        "files": {"standings.jsonl": "every empire's figures after each turn",
                  "botlog.jsonl": "computer empires' decisions, one line per empire per turn",
                  "turns/NNNN/orders.json": "every empire's orders that turn, with ok/error",
                  "turns/NNNN/results.json": "the engine's structured results of the turn",
                  "final_state.json": "the game state after the last turn",
                  "host_audit.jsonl": "the host's actions and View as, one line each (W-23)"},
        "seat_changes": [{k: c[k] for k in ("eid", "turn", "to", "player")}
                         for c in g.seat_log()],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=1))
        z.writestr("standings.jsonl", "".join(json.dumps(r, separators=(",", ":"),
                                                         sort_keys=True) + "\n" for r in rows))
        z.writestr("botlog.jsonl", "".join(json.dumps(r, separators=(",", ":"),
                                                      sort_keys=True) + "\n" for r in bot))
        for n in range(0, st.turn + 1):
            res = _results(g, n)
            if res is not None:
                z.writestr(f"turns/{n:04d}/results.json", json.dumps(res, separators=(",", ":")))
            z.writestr(f"turns/{n:04d}/orders.json",
                       json.dumps(_orders_of(g, n, res), separators=(",", ":")))
        z.writestr("final_state.json", M.dumps(st))
        ap = g.dir / "host_audit.jsonl"
        z.writestr("host_audit.jsonl", ap.read_text(encoding="utf-8") if ap.exists() else "")
        z.writestr("README.txt", "MHGC game export for analysis.\n\n"
                                 "Summarise it with:  python tools/analyze_game.py <this zip>\n"
                                 "See manifest.json for the contents.\n")
    return buf.getvalue()


# ---------------------------------------------------------------- endpoints
def register_analysis(app, get) -> None:
    @app.get("/api/games/{gid}/final")
    def final(gid: str, x_seat_token: Optional[str] = Header(default=None)):
        """Final standings: every race's figures over every turn.  Only once the game is over
        (409 before); then for anyone, seated or not."""
        g = get(gid)
        with g.lock:
            final_allowed(g)
            return final_view(g, g.seat_of(x_seat_token))

    @app.get("/api/games/{gid}/export")
    def export(gid: str, x_seat_token: Optional[str] = Header(default=None)):
        """Export the game for analysis (a zip): standings log, bot decision log, every turn's
        orders (humans' included) and results, the settings and the final state.  Once the game
        is over, any seated player; before that only the host of a one-human game."""
        g = get(gid)
        with g.lock:
            reason = export_allowed(g, x_seat_token)
            seat = g.seat_of(x_seat_token)
            who = g.host_principal(x_seat_token)
            if who is not None:
                g.audit("export", who)
            data = export_zip(g, seat, reason)
            name = f"mhgc-{g.gid}-turn{g.state.turn}.zip"
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})


__all__ = ["analysis_records", "write_analysis_logs", "start_logs", "register_analysis",
           "standings_all", "botlog_all", "export_allowed", "final_allowed"]
