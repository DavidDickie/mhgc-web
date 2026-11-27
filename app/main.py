"""MHGC web server: FastAPI JSON API under /api plus the static single-page UI (app/ui).

Games
- Any number of games run side by side, each with its own lock.  A game has 4, 8 (the default),
  9, 12 or 16 empires (Dave 2026-11-13/16, DECISIONS W-13, W-26: 50x50, 75x75 or 100x100
  boards); the host picks the size and how many are human seats, and the rest are computer
  empires (NPRs).
- Computer empires boast in the game-wide chat (DECISIONS W-14).  The per-game `chatter` setting
  (off / quiet / normal, default normal) is chosen at creation and the host can change it.  The
  messages are made when the turn runs (`TurnResults.chat`) and stored like other chat.
  Computer empires also post technology trade offers privately to contacted human races
  (DECISIONS A-08); `POST .../chat/{id}/accept` puts the matching TTNPR in the recipient's draft.
- Races have passwords (Dave 2026-11-15, DECISIONS W-21, superseding W-02's browser-tied seats).
  Creating a game, taking an open seat or logging in to a race with its password returns a random
  session token that the browser keeps (localStorage) and sends back in the `X-Seat-Token`
  header.  A race can be logged in from any number of browsers, and one browser can hold several
  races of a game.  The server stores only a salted scrypt hash of each password and a SHA-256
  hash of each session token (app/auth.py); neither ever appears in a response.  There is no
  limit on wrong password tries (Dave 2026-11-15).  Every game has a host password (W-23), given
  when it is created.  The creator holds seat 1 and is the host.  Host
  powers: forcing the turn (W-01), resetting another race's password (W-21), handing a race to
  the computer (W-22) and exporting the game at any time (W-17).
- A turn runs as soon as every human seat is taken and has submitted; the host can force it at any
  time (seats that haven't submitted give no orders that turn).  No deadlines, no AI takeover.

Persistence (SAVE_DIR, default ./saves)
  games/<gid>/meta.json                 seats, submissions, version, current turn (commit point)
  games/<gid>/chat.json                 chat messages
  games/<gid>/turns/<n>/state.json      the game state after turn n (0 = the new game)
  games/<gid>/turns/<n>/results.json    the structured results of turn n
  games/<gid>/orders/<n>/<seat>.json    draft orders for turn n (the next turn to run)
  games/<gid>/turns/<n>/orders.json     every empire's orders that turn n ran (DECISIONS W-17)
  games/<gid>/standings.jsonl           every empire's figures after each turn (W-15; secret)
  games/<gid>/botlog.jsonl              the computer empires' decision log (A-05; secret)
The two .jsonl logs are append-only and never sent to a browser while the game runs; see
app/analysis_api.py for who may read them when.
Every file is written atomically (temp file + rename).  A turn is committed by rewriting meta.json
after its state and results are on disk, so a crash mid-turn leaves the previous turn current.

Security model: the browser never receives raw game state.  Everything about the game world goes
through `mhgc.view.view(state, results, empire)` (fog of war, relative coordinates); see that
module.  Chat follows the rules' contact requirement for private messages (see `post_chat`).
"""
from __future__ import annotations

import dataclasses
import hmac
import json
import logging
import os
import re
import secrets
import shutil
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import mhgc
from mhgc import model as M
from mhgc import scanmask
from mhgc.data import constants as K
from mhgc.engine.preview import check_split, production_preview, production_tweak
from mhgc.engine.scans import rebuild_scan_history
from mhgc.engine.turn import check_orders, initial_results, run_turn
from mhgc.mapgen import new_game
from mhgc.orders import Order, OrderSyntaxError, order_from_dict, parse_orders_text
from mhgc.view import view as build_view
from mhgc.legacy_report import legacy_report

from mhgc.npr import adopt as npr_adopt
from mhgc.npr.trace import Tracer

from . import auth
from .analysis_api import analysis_records, register_analysis, start_logs, write_analysis_logs
from .catalogue import order_catalogue, reference

ROOT = Path(__file__).resolve().parent
GID = re.compile(r"^[0-9a-f]{8}$")
RACE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
MAX_ORDERS = 2000
CHAT_MAX = 2000              # characters per chat message
CHAT_KEEP = 20000            # messages kept per game (oldest dropped)


# ---------------------------------------------------------------- helpers
def _hash(token: str) -> str:
    return auth.token_hash(token)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _write_json(path: Path, obj: Any) -> None:
    _atomic_write(path, json.dumps(obj, separators=(",", ":")))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _clean_name(s: str) -> str:
    return " ".join(s.split())


def _default_race(player: str) -> str:
    r = re.sub(r"[^A-Za-z0-9_]", "_", player.strip())[: K.RACE_NAME_MAX].strip("_")
    if not r or not r[0].isalpha():
        r = ("R_" + r)[: K.RACE_NAME_MAX]
    return r


def _check_race(race: str, state: Optional[M.GameState] = None, own: Optional[int] = None):
    if not RACE_RE.fullmatch(race) or len(race) > K.RACE_NAME_MAX:
        raise HTTPException(400, f"Race names are one word of letters, digits and _, starting "
                                 f"with a letter, at most {K.RACE_NAME_MAX} characters")
    if race.lower() in ("unknown", K.INDEPENDENT_NAME.lower()):
        raise HTTPException(400, "That race name is not allowed")
    if state is not None:
        for e in state.empires.values():
            if e.id != own and e.name.lower() == race.lower():
                raise HTTPException(409, "That race name is taken")


def parse_order_input(orders: Optional[list], text: Optional[str]):
    """-> (orders, errors, warnings).  Errors are [{"index"|"line", "text", "error"}]."""
    out: list[Order] = []
    errors, warnings = [], []
    if orders is not None and text is not None:
        raise HTTPException(422, "Send either 'orders' or 'text', not both")
    if text is not None:
        for pl in parse_orders_text(text):
            if pl.error:
                errors.append({"line": pl.lineno, "text": pl.text, "error": pl.error})
            elif pl.order is not None:
                out.append(pl.order)
                for w in pl.order.warnings:
                    warnings.append({"line": pl.lineno, "text": pl.text, "warning": w})
    for i, d in enumerate(orders or []):
        try:
            if not isinstance(d, dict) or "code" not in d:
                raise OrderSyntaxError("each order needs a 'code'")
            out.append(order_from_dict(d))
        except (OrderSyntaxError, TypeError, ValueError) as exc:
            errors.append({"index": i, "text": str(d)[:200], "error": str(exc)})
    if len(out) > MAX_ORDERS:
        raise HTTPException(422, f"At most {MAX_ORDERS} orders a turn")
    return out, errors, warnings


def _order_rows(orders: list[Order]) -> list[dict]:
    return [{**o.to_dict(), "text": o.to_text()} for o in orders]


# ---------------------------------------------------------------- game record
class Game:
    """One game: metadata, the current state/results, under its own lock."""

    def __init__(self, root: Path, gid: str, meta: dict, state: M.GameState, results: dict,
                 chat: list):
        self.root, self.gid, self.meta, self.state, self.results, self.chat = (
            root, gid, meta, state, results, chat)
        self.lock = threading.RLock()
        self.dropped = False
        self.history: OrderedDict[int, tuple] = OrderedDict()
        self.stats_cache: dict[int, dict] = {}     # turn -> {seat: stats row}; past turns only

    # ---- paths / persistence
    @property
    def dir(self) -> Path:
        return self.root / self.gid

    def turn_dir(self, n: int) -> Path:
        return self.dir / "turns" / str(n)

    def draft_path(self, seat: int) -> Path:
        return self.dir / "orders" / str(self.state.turn + 1) / f"{seat}.json"

    def guard(self) -> None:
        """A request that waited on the lock while the game was dropped must not write."""
        if self.dropped:
            raise HTTPException(404, "No such game")

    def save_meta(self) -> None:
        self.guard()
        self.meta["updated"] = time.time()
        _write_json(self.dir / "meta.json", self.meta)

    def save_chat(self) -> None:
        self.guard()
        _write_json(self.dir / "chat.json", self.chat)

    def bump(self) -> None:
        self.meta["version"] = self.meta.get("version", 0) + 1

    # ---- seats
    @property
    def humans(self) -> int:
        return self.meta["humans"]

    @property
    def size(self) -> int:
        """Empires in the game (old games, before sizes existed, are all 16)."""
        return self.meta.get("size") or sum(1 for e in self.state.empires if e != 0)

    @property
    def chatter(self) -> str:
        return self.meta.get("chatter", "normal")

    def human_seats(self) -> list[int]:
        """The empires that are human seats now (taken or open).  At creation 1..humans; the
        host can hand one to the computer or open a computer empire for a human (W-22)."""
        hs = self.meta.get("human_seats")
        return sorted(hs) if hs is not None else list(range(1, self.humans + 1))

    def set_human(self, eid: int, human: bool, player: Optional[str]) -> None:
        hs = set(self.human_seats())
        (hs.add if human else hs.discard)(eid)
        self.meta["human_seats"] = sorted(hs)
        self.meta.setdefault("seat_log", []).append(
            {"eid": eid, "turn": self.state.turn, "to": "human" if human else "computer",
             "player": player, "time": time.time()})

    def seat_log(self) -> list[dict]:
        return list(self.meta.get("seat_log") or [])

    def seat_kinds(self, n: int) -> tuple[set, dict]:
        """For turn n's records: (the human empires, {empire: turn of its last change})."""
        human = set(range(1, self.humans + 1))
        changed: dict[int, int] = {}
        for c in self.seat_log():
            if c["turn"] < n:
                (human.add if c["to"] == "human" else human.discard)(c["eid"])
                changed[c["eid"]] = c["turn"]
        return human, changed

    def converted(self) -> dict[int, dict]:
        """Human seats now played by the computer: {empire: the log entry} (W-22)."""
        out = {}
        for c in self.seat_log():
            if c["to"] == "computer":
                out[c["eid"]] = c
            else:
                out.pop(c["eid"], None)
        return {k: v for k, v in out.items() if k not in self.human_seats()}

    # ---- the host (W-23): the race at meta["host"] and/or a host-only login (host password)
    def host_session(self, token: Optional[str]) -> bool:
        ha = self.meta.get("host_auth")
        if not token or not ha:
            return False
        h = _hash(token)
        return any(hmac.compare_digest(x["h"], h) for x in ha.get("sessions", []))

    def has_host_password(self) -> bool:
        return bool((self.meta.get("host_auth") or {}).get("pw"))

    def host_principal(self, token: Optional[str]) -> Optional[str]:
        """'host' for a host-only login, 'seat N' for the host's race, else None."""
        if self.host_session(token):
            return "host"
        seat = self.seat_of(token)
        if seat is not None and seat == self.meta.get("host"):
            return f"seat {seat}"
        return None

    def audit(self, action: str, by: str, **data) -> None:
        """The host audit log (W-23): every host action, and every view-as, one JSON line."""
        line = {"time": round(time.time(), 3), "turn": self.state.turn, "action": action,
                "by": by, **data}
        try:
            with open(self.dir / "host_audit.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, separators=(",", ":"), sort_keys=True) + "\n")
        except OSError:
            logging.getLogger("mhgc").exception("host audit for %s", self.gid)

    def session_of(self, token: Optional[str]) -> Optional[tuple[int, bool]]:
        """-> (seat, restricted) for a valid session token, else None.  A restricted session
        must set the race's password before it can play (W-21)."""
        if not token:
            return None
        h = _hash(token)
        found = None
        for k, s in self.meta["seats"].items():
            if not s:
                continue
            for sess in s.get("sessions", []):
                if hmac.compare_digest(sess["h"], h):
                    found = (int(k), auth.restricted(s))
        return found

    def seat_of(self, token: Optional[str]) -> Optional[int]:
        """The seat of a session that may play (restricted sessions count as no seat)."""
        got = self.session_of(token)
        return got[0] if got and not got[1] else None

    def seat_info(self, seat: int) -> Optional[dict]:
        return self.meta["seats"].get(str(seat))

    def needs_orders(self, seat: int) -> bool:
        e = self.state.empires.get(seat)
        return e is not None and e.kind == M.HUMAN

    def waiting_for(self) -> list[int]:
        return [s for s in self.human_seats()
                if self.needs_orders(s) and s not in self.meta["submitted"]]

    def host_runs(self) -> bool:
        """No human seat gives orders (a game of computer empires only, or the last human
        handed to the computer): only the host advances it, with Run turn (W-24)."""
        return self.state.winner is None and not any(self.needs_orders(s)
                                                     for s in self.human_seats())

    def handicapped(self) -> list[int]:
        """The host's race when the host plays a race in a game with at least one other human
        player (Dave 2026-11-19, DECISIONS W-28): it can't win and earns no stat-bonus VP, and
        is left out of the ranking pool.  "Another human" is another human seat that is taken
        and still in the game; open seats, computer empires and handed-over races don't count.
        Worked out afresh before every turn, so joins, leaves and hand-overs change it."""
        h = self.meta.get("host")
        if h is None or h not in self.human_seats() or not self.needs_orders(h) \
                or not self.seat_info(h):
            return []
        others = [s for s in self.human_seats()
                  if s != h and self.needs_orders(s) and self.seat_info(s)]
        return [h] if others else []

    def aomt_due(self) -> list[int]:
        """Taken human seats with AOMT on that haven't submitted: on a forced turn the computer
        writes their orders from their own view (DECISIONS W-29)."""
        return [s for s in self.human_seats()
                if self.needs_orders(s) and self.seat_info(s) and s not in self.meta["submitted"]
                and self.state.empires[s].aomt]

    def set_aomt(self, seat: int, on: bool) -> bool:
        """Switch a race's AOMT setting now (the current turn's state is rewritten, as W-22
        does).  Returns whether it changed.  Caller holds the lock."""
        e = self.state.empires[seat]
        if e.aomt == on:
            return False
        e.aomt = on
        self.guard()
        _atomic_write(self.turn_dir(self.state.turn) / "state.json", M.dumps(self.state))
        self.history.pop(self.state.turn, None)
        return True

    def all_in(self) -> bool:
        """Every human seat is taken and has submitted (open seats block; the host can force).
        With no human seat giving orders it is never true: the host runs each turn (W-24)."""
        req = [s for s in self.human_seats() if self.needs_orders(s)]
        return bool(req) and all(self.seat_info(s) and s in self.meta["submitted"] for s in req)

    # ---- drafts
    def load_draft(self, seat: int) -> list[dict]:
        p = self.draft_path(seat)
        if not p.exists():
            return []
        return _read_json(p).get("orders", [])

    def save_draft(self, seat: int, orders: list[Order]) -> None:
        self.guard()
        _write_json(self.draft_path(seat), {"orders": [o.to_dict() for o in orders],
                                            "updated": time.time()})

    def load_draft_for(self, turn: int, seat: int) -> list[dict]:
        p = self.dir / "orders" / str(turn) / f"{seat}.json"
        return _read_json(p).get("orders", []) if p.exists() else []

    def draft_orders(self, seat: int) -> list[Order]:
        out = []
        for d in self.load_draft(seat):
            try:
                out.append(order_from_dict(d))
            except (OrderSyntaxError, TypeError, ValueError):
                continue
        return out

    # ---- history
    def turn_data(self, n: int) -> tuple[M.GameState, dict]:
        if n == self.state.turn:
            return self.state, self.results
        if n in self.history:
            self.history.move_to_end(n)
            return self.history[n]
        d = self.turn_dir(n)
        if not (d / "state.json").exists():
            raise HTTPException(404, "No such turn")
        data = (M.loads((d / "state.json").read_text(encoding="utf-8")),
                _read_json(d / "results.json"))
        self.history[n] = data
        while len(self.history) > 6:
            self.history.popitem(last=False)
        return data

    def stats_row(self, n: int, seat: int) -> Optional[dict]:
        """This seat's stats/economy line for turn n, read from results.json (never from the
        state: it is the seat's own report, so it leaks nothing)."""
        if n == self.state.turn:
            res = self.results
        elif n in self.stats_cache:
            return self.stats_cache[n].get(seat)
        else:
            p = self.turn_dir(n) / "results.json"
            if not p.exists():
                return None
            res = _read_json(p)
        rows = {}
        for k, rep in (res.get("reports") or {}).items():
            st = rep.get("stats") or {}
            rows[int(k)] = {"turn": n, "values": st.get("values", {}), "ranks": st.get("ranks", {}),
                            "vp": st.get("vp"),
                            # as in view.py: the per-system breakdown stays out
                            "economy": {k: v for k, v in (rep.get("economy") or {}).items()
                                        if k != "systems"},
                            "events": len(rep.get("events", [])),
                            "combats": len(rep.get("combats", []))}
        if n != self.state.turn:
            self.stats_cache[n] = rows
        return rows.get(seat)

    # ---- the turn
    def run(self, forced_by: Optional[int] = None) -> int:
        """Run the next turn with the submitted orders.  Caller holds the lock."""
        self.guard()
        if self.state.winner is not None:
            raise HTTPException(409, "The game is over")
        orders = {s: self.draft_orders(s) for s in self.meta["submitted"]
                  if self.needs_orders(s)}
        # AOMT (W-29; Dave 2026-11-20): a race that hasn't submitted and has it on runs its
        # unsubmitted draft as if submitted; only with no draft (nothing but AOMT settings
        # counts as none) does the bot write its orders, from its own view.  A race with AOMT
        # off keeps W-10: its draft is ignored and it gives no orders.
        aomt = self.aomt_due()
        drafts = {}
        for s in aomt:
            d = self.draft_orders(s)
            if any(o.code != "AOMT" for o in d):
                drafts[s] = d
        orders.update(drafts)
        new_state = M.from_dict(M.to_dict(self.state))       # a failed turn changes nothing
        new_state.chatter = self.chatter                     # the host's current setting
        new_state.unranked = self.handicapped()              # the host handicap (W-28)
        tracer = Tracer(aomt_results=self.results)           # the bot decision log (A-05)
        res_obj = run_turn(new_state, orders, npr_fn=tracer, aomt=aomt, aomt_fn=tracer.stand_in)
        res = json.loads(json.dumps(res_obj.to_dict()))      # as on disk
        n = new_state.turn
        log = analysis_records(self, self.state, new_state, orders, tracer, res_obj)
        _write_json(self.turn_dir(n) / "results.json", res)
        _write_json(self.turn_dir(n) / "orders.json", log["orders"])
        _atomic_write(self.turn_dir(n) / "state.json", M.dumps(new_state))
        self.meta["turn"] = n
        self.meta["submitted"] = []
        self.meta["last_turn_at"] = time.time()
        self.bump()
        self.save_meta()                                       # the commit point
        self.state, self.results = new_state, res
        write_analysis_logs(self, n, log)                      # botlog/standings (W-15)
        for s in sorted(set(tracer.aomt) | set(drafts)):
            self.audit("aomt_orders", forced_by or "host", seat=s, race=new_state.empires[s].name,
                       ran=n, source="draft" if s in drafts else "bot",
                       orders=len(drafts[s]) if s in drafts else len(tracer.aomt[s]))
        note = f"Turn {n} has run" + (" (forced by the host)" if forced_by else "") + "."
        if new_state.winner is not None:
            note += f" The {new_state.empires[new_state.winner].name} have won the game!"
        self.system_chat(note)
        for m in res.get("chat") or []:      # computer empires' boasts (W-14), offers (A-08)
            e = new_state.empires.get(m.get("from"))
            if e is None:
                continue
            msg = {"from": e.id, "from_name": e.name, "player": None, "to": None,
                   "to_name": None, "text": m["text"], "system": False, "bot": True,
                   "kind": m.get("kind")}
            to = new_state.empires.get(m.get("to")) if m.get("to") is not None else None
            if m.get("to") is not None:
                if to is None:
                    continue
                msg.update({"to": to.id, "to_name": to.name, "offer": m.get("offer")})
            self.add_chat(msg, save=False)
        if res.get("chat"):
            self.save_chat()
            self.save_meta()
        return n

    # ---- scan history backfill (DECISIONS G-07)
    SCAN_BACKFILL = 1

    def backfill_scan_history(self) -> int:
        """Games that predate scan history (2026-11-13) recorded none for their earlier turns.
        Rebuild it once from the per-turn states on disk (`scans.rebuild_scan_history`, the same
        marks the engine makes) and OR it into every stored turn's masks, so the current view and
        history browsing both show it.  Turns whose state is missing are skipped; an OR is
        idempotent, so a crash part-way is simply redone.  Each state file is rewritten
        atomically, past turns first and the current one last; `meta.scan_backfill` then marks
        the game done (without touching `updated`).  Returns the number of files rewritten.
        Caller holds the lock (or the game isn't shared yet)."""
        if self.meta.get("scan_backfill", 0) >= self.SCAN_BACKFILL:
            return 0
        cur = self.state.turn
        turns = sorted(int(p.name) for p in (self.dir / "turns").iterdir()
                       if p.name.isdigit() and int(p.name) <= cur and (p / "state.json").exists())

        def states():
            for n in turns:
                if n == cur:
                    yield n, self.state
                    continue
                try:
                    yield n, M.loads((self.turn_dir(n) / "state.json").read_text(encoding="utf-8"))
                except Exception:          # an unreadable old turn: backfill what is there
                    continue

        loaded: dict[int, M.GameState] = {}

        def remembering():
            for n, st in states():
                loaded[n] = st
                yield n, st

        written = 0
        for n, masks in rebuild_scan_history(remembering()):
            st = loaded.pop(n)
            changed = False
            for eid, mask in masks.items():
                e = st.empires.get(eid)
                if e is None:
                    continue
                merged = scanmask.union(e.scan_history, mask, st.board)
                if merged != e.scan_history:
                    e.scan_history, changed = merged, True
            if changed:
                _atomic_write(self.turn_dir(n) / "state.json", M.dumps(st))
                written += 1
        self.history.clear()
        self.meta["scan_backfill"] = self.SCAN_BACKFILL
        _write_json(self.dir / "meta.json", self.meta)
        return written

    # ---- chat
    def system_chat(self, text: str) -> None:
        self.add_chat({"from": None, "from_name": None, "player": None, "to": None,
                       "to_name": None, "text": text, "system": True})

    def add_chat(self, msg: dict, save: bool = True) -> dict:
        nid = self.meta.get("chat_next", 1)
        self.meta["chat_next"] = nid + 1
        msg = {"id": nid, "turn": self.state.turn, "time": time.time(), **msg}
        self.chat.append(msg)
        if len(self.chat) > CHAT_KEEP:
            del self.chat[: len(self.chat) - CHAT_KEEP]
        self.bump()
        if save:
            self.save_chat()
            self.save_meta()
        return msg

    # ---- public summary (lobby)
    def summary(self) -> dict:
        st = self.state
        seats = []
        hs = set(self.human_seats())
        shown = sorted(hs | set(self.converted()))
        for s in shown:
            info = self.seat_info(s) if s in hs else None
            e = st.empires[s]
            seats.append({"seat": s, "race": e.name, "player": info["player"] if info else None,
                          "open": info is None and s in hs,
                          "computer": s not in hs, "password": bool(info and info.get("pw")),
                          "host": s == self.meta.get("host"),
                          "submitted": s in self.meta["submitted"],
                          "needs_orders": self.needs_orders(s)})
        return {"id": self.gid, "name": self.meta["name"], "turn": st.turn,
                "created": self.meta["created"], "updated": self.meta.get("updated"),
                "humans": len(hs), "computers": self.size - len(hs),
                "host_only": self.meta.get("host") is None and bool(self.meta.get("host_auth")),
                "host_password": self.has_host_password(),
                "host_runs": self.host_runs(),
                # the host's race can't win or earn ranking VP (W-28), as of now
                "host_handicap": bool(self.handicapped()),
                "size": self.size, "board": st.board, "bins": st.bins,
                "vp_to_win": st.vp_to_win,          # fixed at creation (G-28)
                "empty_bins": [list(b) for b in st.empty_bins], "chatter": self.chatter,
                "host_seat": self.meta.get("host"), "seats": seats,
                "open_seats": [x["seat"] for x in seats if x["open"]],
                "waiting_for": self.waiting_for(), "finished": st.winner is not None,
                "winner": st.empires[st.winner].name if st.winner is not None else None,
                "version": self.meta.get("version", 0)}


# ---------------------------------------------------------------- request models
class NewGame(BaseModel):
    name: str = Field(default="", max_length=60)
    # empires in the game: 4, 8 (default), 9, 12, 16, 20 or 25 (DECISIONS W-13, W-26, G-30).  When omitted and
    # `computers` is given, the size is humans + computers.
    size: Optional[int] = None
    humans: int = Field(ge=0, le=K.MAX_EMPIRES)
    computers: Optional[int] = Field(default=None, ge=0, le=K.MAX_EMPIRES - 1)
    chatter: str = Field(default="normal", pattern="^(off|quiet|normal)$")
    player: str = Field(min_length=1, max_length=30)
    race: Optional[str] = Field(default=None, max_length=K.RACE_NAME_MAX)
    seed: Optional[int] = None
    password: str = ""                      # checked by auth.check_password_rules
    # W-23: host the game without a race.  The host password opens the host login; it is
    # required in both modes (Dave 2026-11-15) and may equal the race password.
    host_only: bool = False
    host_password: Optional[str] = None


class Login(BaseModel):
    seat: int = Field(ge=1, le=K.MAX_EMPIRES)
    password: str = ""


class PasswordBody(BaseModel):
    new: str = ""
    current: Optional[str] = None


class ResetBody(BaseModel):
    password: str = ""


class LogoutBody(BaseModel):
    everywhere: bool = False


class Join(BaseModel):
    seat: int = Field(ge=1, le=K.MAX_EMPIRES)
    player: str = Field(min_length=1, max_length=30)
    race: Optional[str] = Field(default=None, max_length=K.RACE_NAME_MAX)
    password: str = ""


class AomtBody(BaseModel):
    on: bool


class OrdersBody(BaseModel):
    orders: Optional[list[Any]] = Field(default=None, max_length=MAX_ORDERS)
    text: Optional[str] = Field(default=None, max_length=200_000)


class PreviewBody(BaseModel):
    # {system id: {"au": %, "iu": %, "eu": %}}: profiles to try instead of the draft's
    overrides: dict[str, dict[str, int]] = Field(default_factory=dict, max_length=500)


class TweakBody(PreviewBody):
    # the systems to tweak (default: every own system); the search is +-max_delta points
    systems: Optional[list[int]] = Field(default=None, max_length=500)
    max_delta: int = Field(default=3, ge=0, le=5)


class ForceBody(BaseModel):
    turns: int = Field(default=1, ge=1, le=20)


class HostLogin(BaseModel):
    password: str = ""


class Settings(BaseModel):
    chatter: Optional[str] = Field(default=None, pattern="^(off|quiet|normal)$")


class ChatBody(BaseModel):
    text: str = Field(min_length=1, max_length=CHAT_MAX)
    to: Optional[int] = Field(default=None, ge=0, le=K.MAX_EMPIRES)


class AcceptBody(BaseModel):
    alt: int = Field(default=0, ge=0, le=10)      # which alternative of the offer


# ---------------------------------------------------------------- the app
def create_app(save_dir: Optional[str | Path] = None) -> FastAPI:
    saves = Path(save_dir or os.environ.get("SAVE_DIR") or ROOT.parent / "saves")
    root = saves / "games"
    root.mkdir(parents=True, exist_ok=True)
    games: dict[str, Game] = {}
    registry = threading.Lock()

    def load_all() -> None:
        for d in sorted(root.iterdir()):
            if not d.is_dir() or not GID.fullmatch(d.name) or not (d / "meta.json").exists():
                continue
            try:
                meta = _read_json(d / "meta.json")
                td = d / "turns" / str(meta["turn"])
                state = M.loads((td / "state.json").read_text(encoding="utf-8"))
                results = _read_json(td / "results.json")
                chat = _read_json(d / "chat.json") if (d / "chat.json").exists() else []
            except Exception:          # unreadable (e.g. an older save format): skip, don't crash
                continue
            g = Game(root, d.name, meta, state, results, chat)
            if any([auth.migrate_seat(v) for v in meta.get("seats", {}).values()]):
                _write_json(d / "meta.json", meta)   # pre-password seats (W-21 migration)
            try:
                g.backfill_scan_history()
            except Exception:          # never let the backfill keep a game from loading
                logging.getLogger("mhgc").exception("scan-history backfill failed for %s", d.name)
            games[d.name] = g

    load_all()
    app = FastAPI(title="Mega Hyper Galactic Conquest",
                  description="JSON API for the MHGC web game.  Seat tokens go in the "
                              "X-Seat-Token header.")
    app.state.games = games
    app.state.save_dir = saves
    trust_proxy = os.environ.get("MHGC_TRUST_PROXY", "") not in ("", "0")

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        """As FastAPI's own 422, minus the `input` echo (it could contain a password)."""
        return JSONResponse(status_code=422, content={"detail": [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg", "invalid"),
             "type": e.get("type", "")} for e in exc.errors()]})

    def client_ip(request: Request) -> str:
        """The client's address.  Behind Render's proxy (MHGC_TRUST_PROXY=1) it is the last
        X-Forwarded-For entry, the one the proxy added.  Nothing uses it since the login rate
        limit was removed (Dave 2026-11-15); it is kept, with the setting, for anything that
        needs the real visitor address later."""
        if trust_proxy:
            xff = request.headers.get("x-forwarded-for", "")
            if xff.strip():
                return xff.split(",")[-1].strip()
        return request.client.host if request.client else "?"

    @app.middleware("http")
    async def revalidate(request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache"
        else:
            response.headers["Cache-Control"] = "no-store"
        return response

    def get(gid: str) -> Game:
        g = games.get(gid) if GID.fullmatch(gid) else None
        if g is None:
            raise HTTPException(404, "No such game")
        return g

    def seat_or_401(g: Game, token: Optional[str]) -> int:
        got = g.session_of(token)
        if got is None:
            raise HTTPException(401, "This browser isn't logged in to a race in this game")
        if got[1]:
            raise HTTPException(403, {"message": "Set a password for your race before you play",
                                      "code": "set_password"})
        return got[0]

    def session_or_401(g: Game, token: Optional[str]) -> int:
        """Any valid session, restricted or not (setting the password, logging out)."""
        got = g.session_of(token)
        if got is None:
            raise HTTPException(401, "This browser isn't logged in to a race in this game")
        return got[0]

    def host_or_403(g: Game, token: Optional[str], what: str, *, unset_ok: bool = False) -> str:
        """-> who acts: 'host' (a host-only login) or 'seat N' (the host's race).  In a game
        from before host passwords were required, the host's race must set one before it can
        use any host power (403 code "set_host_password"; Dave 2026-11-15)."""
        who = g.host_principal(token)
        if who is not None:
            if not unset_ok and not g.has_host_password():
                raise HTTPException(403, {"message": "Set a host password before you use the "
                                                     "host's powers",
                                          "code": "set_host_password"})
            return who
        if g.session_of(token) is None:
            raise HTTPException(401, "This browser isn't logged in to this game")
        raise HTTPException(403, f"Only the host can {what}")

    def host_seat_of(who: str) -> Optional[int]:
        return int(who.split()[1]) if who.startswith("seat ") else None

    def host_login_or_403(g: Game, token: Optional[str]) -> None:
        """View as (W-23) needs a host login (the host password), not the host's race."""
        if not g.host_session(token):
            raise HTTPException(403, "Viewing as a race needs the host login (the host "
                                     "password)")

    def password_or_400(pw) -> str:
        try:
            return auth.check_password_rules(pw)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    def new_seat(player: str, pw: str) -> tuple[dict, str]:
        info = {"player": player, "joined": time.time(), "pw": auth.hash_password(pw),
                "must_set": False, "sessions": []}
        return info, auth.add_session(info)

    def you(g: Game, token: Optional[str]) -> dict:
        got = g.session_of(token)
        return {"you": got[0] if got else None,
                "you_must_set_password": bool(got and got[1]),
                "you_host": g.host_principal(token) is not None,
                "you_host_login": g.host_session(token),
                # a game from before host passwords were required: the host must set one now
                "you_must_set_host_password": g.host_principal(token) is not None
                and not g.has_host_password()}

    def orders_for(g: Game, seat: int, body: Optional[OrdersBody]):
        if body is None or (body.orders is None and body.text is None):
            return g.draft_orders(seat), [], []
        return parse_order_input(body.orders, body.text)

    def need_playing(g: Game, seat: int) -> None:
        if g.state.winner is not None:
            raise HTTPException(409, "The game is over")
        if not g.needs_orders(seat):
            raise HTTPException(409, "Your empire no longer gives orders (resigned or extinct)")

    # ---- static data
    @app.get("/api/health")
    def health():
        return {"ok": True, "games": len(games), "version": mhgc.__version__,
                "version_date": mhgc.__version_date__}

    @app.get("/api/orders/catalogue")
    def catalogue(board: int = Query(default=K.BOARD)):
        """The order catalogue; `board` (50, 75, 100 or 125) sets the coordinate fields' range."""
        if board not in {side * K.BIN for side, _ in K.GAME_SIZES.values()}:
            raise HTTPException(422, "No such board size")
        return order_catalogue(board)

    @app.get("/api/reference")
    def ref():
        return reference()

    # ---- games
    @app.get("/api/rulebook", response_class=PlainTextResponse)
    def rulebook():
        """The player rulebook (docs/RULEBOOK.md) as Markdown, for the UI's help page."""
        p = ROOT.parent / "docs" / "RULEBOOK.md"
        if not p.exists():
            raise HTTPException(404, "No rulebook")
        return PlainTextResponse(p.read_text(encoding="utf-8"), media_type="text/markdown")

    @app.get("/api/games")
    def list_games():
        rows = []
        for g in list(games.values()):
            with g.lock:
                rows.append(g.summary())
        return sorted(rows, key=lambda r: -(r["updated"] or 0))

    @app.post("/api/games")
    def create(req: NewGame):
        sizes = sorted(K.GAME_SIZES)
        size = req.size
        if size is None:
            size = req.humans + req.computers if req.computers is not None else \
                K.DEFAULT_GAME_SIZE
            if size not in K.GAME_SIZES:
                raise HTTPException(400, f"A game has {', '.join(map(str, sizes))} empires: "
                                         f"{req.humans} human seats and {req.computers} computer "
                                         f"empires make {size}")
        if size not in K.GAME_SIZES:
            raise HTTPException(400, f"A game has {', '.join(map(str, sizes))} empires, not "
                                     f"{size}")
        if req.humans == 0 and not req.host_only:
            raise HTTPException(400, "A game you play in has at least one human seat")
        if req.humans > size:
            raise HTTPException(400, f"A {size}-empire game has at most {size} human seats")
        computers = size - req.humans
        if req.computers is not None and req.computers != computers:
            raise HTTPException(400, f"A {size}-empire game with {req.humans} human seats has "
                                     f"{computers} computer empires")
        player = _clean_name(req.player)
        if not player:
            raise HTTPException(400, "Give your name")
        if not req.host_password:
            raise HTTPException(400, "Choose a host password (it may be the same as your race "
                                     "password, and the same for all the games you host)")
        hpw = password_or_400(req.host_password)
        if req.host_only:
            race = None
            names = [f"Open_{i}" for i in range(1, req.humans + 1)]
        else:
            pw = password_or_400(req.password)
            race = req.race.strip() if req.race else _default_race(player)
            _check_race(race)
            names = [race] + [f"Open_{i}" for i in range(2, req.humans + 1)]
        if len({n.lower() for n in names}) != len(names):
            raise HTTPException(409, "That race name is taken")
        seed = req.seed if req.seed is not None else secrets.randbelow(2**31)
        title = _clean_name(req.name) or f"{player}'s game, {time.strftime('%b %d %H:%M')}"
        state = new_game(title, seed, names, size=size)
        state.chatter = req.chatter
        results = json.loads(json.dumps(initial_results(state).to_dict()))
        host_auth = {"pw": auth.hash_password(hpw), "player": player, "sessions": []}
        if req.host_only:
            seats, token = {}, auth.add_session(host_auth)
        else:
            seat1, token = new_seat(player, pw)
            seats = {"1": seat1}
        with registry:
            gid = secrets.token_hex(4)
            while gid in games or (root / gid).exists():
                gid = secrets.token_hex(4)
            now = time.time()
            meta = {"id": gid, "name": title, "created": now, "updated": now, "seed": seed,
                    "humans": req.humans, "size": size, "chatter": req.chatter,
                    "host": None if req.host_only else 1, "host_auth": host_auth,
                    "turn": 0, "submitted": [], "version": 1,
                    "chat_next": 1, "save_version": 1,
                    "scan_backfill": Game.SCAN_BACKFILL,     # recorded live from turn 0
                    "seats": seats}
            g = Game(root, gid, meta, state, results, [])
            with g.lock:
                _write_json(g.turn_dir(0) / "results.json", results)
                _atomic_write(g.turn_dir(0) / "state.json", M.dumps(state))
                g.save_chat()
                g.save_meta()
                start_logs(g)                             # standings at turn 0 (W-15)
                games[gid] = g
                if req.host_only:
                    g.system_chat(f"{player} created the game and hosts it without a race.")
                    g.audit("create", "host", host_only=True)
                    return {"id": gid, "seat": None, "host": True, "token": token,
                            "game": g.summary()}
                g.system_chat(f"{player} created the game as the {race} (seat 1, host).")
                return {"id": gid, "seat": 1, "host": True, "token": token, "game": g.summary()}

    @app.get("/api/games/{gid}")
    def read_game(gid: str, x_seat_token: Optional[str] = Header(default=None)):
        g = get(gid)
        with g.lock:
            return g.summary() | you(g, x_seat_token)

    @app.post("/api/games/{gid}/join")
    def join(gid: str, req: Join):
        g = get(gid)
        with g.lock:
            if req.seat in g.converted():
                raise HTTPException(409, "That race is played by the computer now")
            if req.seat not in g.human_seats():
                raise HTTPException(400, "No such human seat")
            if g.seat_info(req.seat) is not None:
                raise HTTPException(409, "That seat is already taken")
            if not g.needs_orders(req.seat):
                raise HTTPException(409, "That race is out of the game")
            player = _clean_name(req.player)
            if not player:
                raise HTTPException(400, "Give your name")
            pw = password_or_400(req.password)
            e = g.state.empires[req.seat]
            if g.state.turn == 0:
                race = req.race.strip() if req.race else _default_race(player)
                _check_race(race, g.state, own=req.seat)
                e.name = race
                _atomic_write(g.turn_dir(0) / "state.json", M.dumps(g.state))
            g.meta["seats"][str(req.seat)], token = new_seat(player, pw)
            g.set_aomt(req.seat, True)      # a newly taken seat starts with AOMT on (W-29)
            if g.meta.get("host") is None and not g.meta.get("host_auth"):
                g.meta["host"] = req.seat                  # an old game whose seats all left
            g.bump()
            g.save_meta()
            g.system_chat(f"{player} takes seat {req.seat} as the {e.name}.")
            return {"id": gid, "seat": req.seat, "token": token, "game": g.summary()}

    @app.post("/api/games/{gid}/leave")
    def leave(gid: str, x_seat_token: Optional[str] = Header(default=None)):
        g = get(gid)
        with g.lock:
            seat = seat_or_401(g, x_seat_token)
            player = g.seat_info(seat)["player"]
            g.meta["seats"][str(seat)] = None              # password and sessions go with it
            g.set_aomt(seat, True)     # back to the default (on) for the next player (W-29)
            g.meta["submitted"] = [s for s in g.meta["submitted"] if s != seat]
            if g.meta.get("host") == seat and (g.meta.get("host_auth") or {}).get("pw"):
                g.meta["host"] = None          # the host stays host through the host login
            elif g.meta.get("host") == seat:
                taken = [int(k) for k, v in g.meta["seats"].items() if v]
                g.meta["host"] = min(taken) if taken else None
            g.bump()
            g.save_meta()
            g.system_chat(f"{player} left seat {seat}; it is open for someone to join.")
            return {"left": seat, "game": g.summary()}

    @app.post("/api/games/{gid}/login")
    def login(gid: str, req: Login):
        """Log in to a race with its password: a new session token for this browser.  There is
        no limit on wrong tries (Dave 2026-11-15)."""
        g = get(gid)
        with g.lock:
            info = g.seat_info(req.seat) if req.seat in g.human_seats() else None
            if info is None:
                if req.seat in g.converted():
                    raise HTTPException(409, "That race is played by the computer now")
                raise HTTPException(404, "Nobody plays that race yet: take the open seat instead")
            race = g.state.empires[req.seat].name
            if info.get("pw") is None:
                raise HTTPException(409, f"The {race} have no password yet. Log in from the "
                                         f"browser that holds the race and set one, or ask the "
                                         f"host to reset it.")
            if not auth.verify_password(req.password, info["pw"]):
                raise HTTPException(403, f"Wrong password for the {race}.")
            token = auth.add_session(info)
            g.save_meta()
            return {"id": gid, "seat": req.seat, "race": race, "player": info["player"],
                    "token": token, "must_set_password": auth.restricted(info),
                    "game": g.summary()}

    @app.post("/api/games/{gid}/password")
    def set_password(gid: str, body: PasswordBody,
                     x_seat_token: Optional[str] = Header(default=None)):
        """Change your race's password (`current` is needed unless the race must set a new one:
        after a host reset or for a seat from before passwords).  Every other browser logged in
        to the race is logged out; this one stays in."""
        g = get(gid)
        with g.lock:
            seat = session_or_401(g, x_seat_token)
            info = g.seat_info(seat)
            new = password_or_400(body.new)
            if not auth.restricted(info) and not auth.verify_password(body.current or "",
                                                                      info["pw"]):
                raise HTTPException(403, "Your current password isn't right")
            info["pw"] = auth.hash_password(new)
            info["must_set"] = False
            h = _hash(x_seat_token)
            info["sessions"] = [x for x in info["sessions"] if hmac.compare_digest(x["h"], h)]
            g.bump()                               # other browsers notice they are logged out
            g.save_meta()
            return {"ok": True, "seat": seat} | you(g, x_seat_token)

    @app.post("/api/games/{gid}/logout")
    def logout(gid: str, body: Optional[LogoutBody] = None,
               x_seat_token: Optional[str] = Header(default=None)):
        """Log this browser out of its race (the session token stops working).
        `everywhere` logs out every browser logged in to the race."""
        g = get(gid)
        with g.lock:
            seat = session_or_401(g, x_seat_token)
            info = g.seat_info(seat)
            if body is not None and body.everywhere:
                n = len(info["sessions"])
                info["sessions"] = []
                g.bump()
            else:
                n = int(auth.drop_session(info, x_seat_token))
            g.save_meta()
            return {"logged_out": seat, "sessions_ended": n}

    @app.post("/api/games/{gid}/seats/{seat}/reset-password")
    def reset_password(gid: str, seat: int, body: ResetBody,
                       x_seat_token: Optional[str] = Header(default=None)):
        """Host only: give another race a temporary password (the host tells its player).  Every
        browser logged in to that race is logged out, and on its next login the race must choose
        a new password.  Posted in the game-wide chat, so it is never secret (W-21)."""
        g = get(gid)
        with g.lock:
            who = host_or_403(g, x_seat_token, "reset a password")
            if seat == host_seat_of(who):
                raise HTTPException(400, "Use Change password for your own race")
            info = g.seat_info(seat) if seat in g.human_seats() else None
            if info is None:
                raise HTTPException(404, "Nobody plays that race: there is no password to reset")
            pw = password_or_400(body.password)
            info["pw"] = auth.hash_password(pw)
            info["must_set"] = True
            info["sessions"] = []
            g.bump()
            g.save_meta()
            race = g.state.empires[seat].name
            g.audit("reset_password", who, seat=seat, race=race)
            g.system_chat(f"The host reset the password of the {race} (seat {seat}).")
            return {"reset": seat, "game": g.summary()}

    @app.post("/api/games/{gid}/seats/{seat}/computer")
    def to_computer(gid: str, seat: int, x_seat_token: Optional[str] = Header(default=None)):
        """Host only: hand a human race (taken or open) to the computer for good (W-22).  It
        becomes a computer empire: a personality from the seed, a memory that starts from its
        own last report only; its password, sessions, draft and submission are dropped, and the
        turn no longer waits for it."""
        g = get(gid)
        with g.lock:
            who = host_or_403(g, x_seat_token, "hand a race to the computer")
            if g.state.winner is not None:
                raise HTTPException(409, "The game is over")
            if seat in (host_seat_of(who), g.meta.get("host")):
                raise HTTPException(400, "You can't hand your own race to the computer")
            if seat not in g.human_seats():
                raise HTTPException(404, "That isn't a human race")
            if not g.needs_orders(seat):
                raise HTTPException(409, "That race is out of the game")
            info = g.seat_info(seat)
            e = g.state.empires[seat]
            npr_adopt(g.state, seat, g.results)
            _atomic_write(g.turn_dir(g.state.turn) / "state.json", M.dumps(g.state))
            g.set_human(seat, False, info["player"] if info else None)
            g.meta["seats"][str(seat)] = None
            g.meta["submitted"] = [s for s in g.meta["submitted"] if s != seat]
            g.draft_path(seat).unlink(missing_ok=True)
            g.bump()
            g.save_meta()
            g.audit("to_computer", who, seat=seat, race=e.name,
                    player=info["player"] if info else None)
            g.system_chat(f"The host handed the {e.name} (seat {seat}"
                          f"{', ' + info['player'] if info else ''}) to the computer. "
                          f"They are a computer empire from now on.")
            ran = None
            if g.all_in():
                ran = g.run()
            return {"computer": seat, "turn_ran": ran is not None, "turn": g.state.turn,
                    "game": g.summary()}

    @app.post("/api/games/{gid}/seats/{eid}/human")
    def to_human(gid: str, eid: int, x_seat_token: Optional[str] = Header(default=None)):
        """Host only: open a computer empire for a human player (W-22).  It becomes an open human
        seat (kind HUMAN, its bot memory and personality dropped; the bot log keeps its past).
        A new player takes it as any open seat, keeping its name after turn 0.  Until then it
        gives no orders and, as any open seat (W-08), blocks the automatic turn."""
        g = get(gid)
        with g.lock:
            who = host_or_403(g, x_seat_token, "open a computer empire for a human")
            if g.state.winner is not None:
                raise HTTPException(409, "The game is over")
            e = g.state.empires.get(eid)
            if e is None or eid == 0 or e.kind != M.NPR:
                raise HTTPException(404, "That isn't a computer empire")
            e.kind = M.HUMAN
            g.state.npr_state.pop(eid, None)
            _atomic_write(g.turn_dir(g.state.turn) / "state.json", M.dumps(g.state))
            g.set_human(eid, True, None)
            g.meta["seats"][str(eid)] = None
            g.meta["submitted"] = [s for s in g.meta["submitted"] if s != eid]
            g.bump()
            g.save_meta()
            g.audit("to_human", who, seat=eid, race=e.name)
            g.system_chat(f"The host opened the {e.name} for a human player: seat {eid} is "
                          f"open to join.")
            return {"human": eid, "game": g.summary()}

    # ---- the host login (W-23)
    @app.post("/api/games/{gid}/host/login")
    def host_login(gid: str, req: HostLogin):
        """Log in as the game's host with the host password: a session that holds no seat,
        is never waited on, and has the host's powers plus View as."""
        g = get(gid)
        with g.lock:
            ha = g.meta.get("host_auth") or {}
            if not ha.get("pw"):
                raise HTTPException(409, "This game has no host password. The host can set one "
                                         "from their race's menu.")
            if not auth.verify_password(req.password, ha["pw"]):
                raise HTTPException(403, "Wrong host password.")
            token = auth.add_session(ha)
            g.save_meta()
            g.audit("host_login", "host")
            return {"id": gid, "seat": None, "host": True, "token": token, "game": g.summary()}

    @app.post("/api/games/{gid}/host/logout")
    def host_logout(gid: str, x_seat_token: Optional[str] = Header(default=None)):
        g = get(gid)
        with g.lock:
            if not g.host_session(x_seat_token):
                raise HTTPException(401, "This browser isn't logged in as the host")
            auth.drop_session(g.meta["host_auth"], x_seat_token)
            g.save_meta()
            return {"logged_out": "host"}

    @app.post("/api/games/{gid}/host/password")
    def host_password(gid: str, body: PasswordBody,
                      x_seat_token: Optional[str] = Header(default=None)):
        """Set or change the host password (the host's race or a host login).  Changing it needs
        the current one and logs out every other host login."""
        g = get(gid)
        with g.lock:
            who = host_or_403(g, x_seat_token, "set the host password", unset_ok=True)
            new = password_or_400(body.new)
            ha = g.meta.setdefault("host_auth", {"sessions": []})
            if ha.get("pw") and not auth.verify_password(body.current or "", ha["pw"]):
                raise HTTPException(403, "The current host password isn't right")
            ha["pw"] = auth.hash_password(new)
            h = _hash(x_seat_token or "")
            ha["sessions"] = [x for x in ha.get("sessions", []) if hmac.compare_digest(x["h"], h)]
            g.bump()
            g.save_meta()
            g.audit("host_password", who)
            return {"ok": True, "game": g.summary()}

    @app.get("/api/games/{gid}/host/races")
    def host_races(gid: str, x_seat_token: Optional[str] = Header(default=None)):
        """Host only: every empire, human or computer, for View as and the host's controls."""
        g = get(gid)
        with g.lock:
            host_or_403(g, x_seat_token, "list every race")
            hs = set(g.human_seats())
            out = []
            for eid in sorted(g.state.empires):
                e = g.state.empires[eid]
                if eid == 0 or e.kind not in (M.HUMAN, M.NPR, M.DEAD):
                    continue
                info = g.seat_info(eid) if eid in hs else None
                out.append({"id": eid, "race": e.name, "kind": e.kind, "human": eid in hs,
                            "player": info["player"] if info else None,
                            "open": eid in hs and info is None,
                            "submitted": eid in g.meta["submitted"]})
            return {"races": out}

    # ---- View as (W-23): read-only, host login only, audited, silent
    def as_seat(g: Game, token: Optional[str], eid: int, what: str, turn=None) -> int:
        host_login_or_403(g, token)
        e = g.state.empires.get(eid)
        if e is None or eid == 0 or e.kind not in (M.HUMAN, M.NPR, M.DEAD):
            raise HTTPException(404, "No such race")
        # audit every view fetch, but not the same race and turn again within 5 minutes
        last = getattr(g, "last_view_as", None)
        key = (eid, g.state.turn if turn is None else turn)
        if what in ("view", "report") and (last is None or last[0] != key or time.time() - last[1] > 300):
            g.audit("view_as", "host", seat=eid, race=e.name, turn_viewed=key[1])
            g.last_view_as = (key, time.time())
        return eid

    @app.get("/api/games/{gid}/as/{eid}/view")
    def as_view(gid: str, eid: int, turn: Optional[int] = Query(default=None, ge=0),
                x_seat_token: Optional[str] = Header(default=None)):
        g = get(gid)
        with g.lock:
            return do_view(g, as_seat(g, x_seat_token, eid, "view", turn), turn, view_as=True)

    @app.get("/api/games/{gid}/as/{eid}/orders")
    def as_orders(gid: str, eid: int, x_seat_token: Optional[str] = Header(default=None)):
        g = get(gid)
        with g.lock:
            return do_orders(g, as_seat(g, x_seat_token, eid, "orders"))

    @app.get("/api/games/{gid}/as/{eid}/stats")
    def as_stats(gid: str, eid: int, x_seat_token: Optional[str] = Header(default=None)):
        g = get(gid)
        with g.lock:
            return do_stats(g, as_seat(g, x_seat_token, eid, "stats"))

    @app.get("/api/games/{gid}/as/{eid}/turns")
    def as_turns(gid: str, eid: int, x_seat_token: Optional[str] = Header(default=None)):
        g = get(gid)
        with g.lock:
            as_seat(g, x_seat_token, eid, "turns")
            return do_turns(g)

    @app.get("/api/games/{gid}/as/{eid}/chat")
    def as_chat(gid: str, eid: int, since: int = Query(default=0, ge=0),
                limit: int = Query(default=500, ge=1, le=2000),
                x_seat_token: Optional[str] = Header(default=None)):
        g = get(gid)
        with g.lock:
            return do_chat(g, as_seat(g, x_seat_token, eid, "chat"), since, limit)

    @app.post("/api/games/{gid}/as/{eid}/production/preview")
    def as_preview(gid: str, eid: int, body: Optional[PreviewBody] = None,
                   x_seat_token: Optional[str] = Header(default=None)):
        """Read-only: nothing is stored."""
        g = get(gid)
        with g.lock:
            return do_preview(g, as_seat(g, x_seat_token, eid, "preview"), body)

    @app.post("/api/games/{gid}/as/{eid}/production/tweak")
    def as_tweak(gid: str, eid: int, body: Optional[TweakBody] = None,
                 x_seat_token: Optional[str] = Header(default=None)):
        """Read-only: nothing is stored."""
        g = get(gid)
        with g.lock:
            return do_tweak(g, as_seat(g, x_seat_token, eid, "preview"), body)

    @app.get("/api/games/{gid}/as/{eid}/report.txt", response_class=PlainTextResponse)
    def as_report(gid: str, eid: int, turn: Optional[int] = Query(default=None, ge=0),
                  x_seat_token: Optional[str] = Header(default=None)):
        g = get(gid)
        with g.lock:
            return do_report(g, as_seat(g, x_seat_token, eid, "report", turn), turn, view_as=True)

    @app.api_route("/api/games/{gid}/as/{eid}/{rest:path}", methods=["POST", "PUT", "DELETE"])
    def as_write(gid: str, eid: int, rest: str):
        """Viewing as a race is read-only: no drafts, submissions or chat as them."""
        raise HTTPException(403, "Viewing as a race is read-only: the host can't give orders, "
                                 "submit or chat for another race")

    @app.delete("/api/games/{gid}")
    def drop(gid: str, x_seat_token: Optional[str] = Header(default=None)):
        """Delete a game for good.  Any seated player may drop it (or anyone, once nobody holds
        a seat); this is not a host power."""
        g = get(gid)
        with g.lock:
            if any(g.meta["seats"].values()) and not g.host_session(x_seat_token):
                seat_or_401(g, x_seat_token)
            g.dropped = True
            with registry:
                games.pop(gid, None)
            trash = root / f".drop-{gid}-{secrets.token_hex(3)}"
            os.replace(g.dir, trash)
            shutil.rmtree(trash, ignore_errors=True)
        return {"dropped": gid}

    @app.post("/api/games/{gid}/settings")
    def settings(gid: str, body: Settings, x_seat_token: Optional[str] = Header(default=None)):
        """Host only: change the game's settings.  `chatter` (off / quiet / normal) sets how
        much the computer empires boast in the game-wide chat from the next turn on."""
        g = get(gid)
        with g.lock:
            who = host_or_403(g, x_seat_token, "change the settings")
            if body.chatter is not None and body.chatter != g.chatter:
                g.audit("settings", who, chatter=body.chatter)
                g.meta["chatter"] = body.chatter
                g.bump()
                g.save_meta()
                g.system_chat(f"The host set computer chatter to {body.chatter}.")
            return g.summary()

    @app.get("/api/games/{gid}/version")
    def version(gid: str):
        """Cheap poll: refetch the view/chat only when `version` (or `turn`) changes."""
        g = get(gid)
        with g.lock:
            return {"version": g.meta.get("version", 0), "turn": g.state.turn,
                    "submitted": sorted(g.meta["submitted"]), "waiting_for": g.waiting_for(),
                    "chat_last": g.meta.get("chat_next", 1) - 1,
                    "finished": g.state.winner is not None}

    @app.get("/api/games/{gid}/turns")
    def turns(gid: str, x_seat_token: Optional[str] = Header(default=None)):
        g = get(gid)
        with g.lock:
            seat_or_401(g, x_seat_token)
            return do_turns(g)

    def do_turns(g: Game) -> dict:
        return {"current": g.state.turn, "turns": list(range(0, g.state.turn + 1))}

    @app.get("/api/games/{gid}/stats")
    def stats(gid: str, x_seat_token: Optional[str] = Header(default=None)):
        """This seat's statistics, VP and economy for every turn so far (for the graphs)."""
        g = get(gid)
        with g.lock:
            return do_stats(g, seat_or_401(g, x_seat_token))

    def do_stats(g: Game, seat: int) -> dict:
        rows = [g.stats_row(n, seat) for n in range(0, g.state.turn + 1)]
        return {"current": g.state.turn, "turns": [r for r in rows if r is not None]}

    @app.get("/api/games/{gid}/view")
    def get_view(gid: str, turn: Optional[int] = Query(default=None, ge=0),
                 x_seat_token: Optional[str] = Header(default=None)):
        """The fog-of-war view for this browser's seat, for the current turn or an earlier one."""
        g = get(gid)
        with g.lock:
            return do_view(g, seat_or_401(g, x_seat_token), turn)

    def do_view(g: Game, seat: int, turn: Optional[int], view_as: bool = False) -> dict:
        n = g.state.turn if turn is None else turn
        if n > g.state.turn:
            raise HTTPException(404, "No such turn")
        state, results = g.turn_data(n)
        if seat not in state.empires or seat == 0:
            raise HTTPException(404, "No such race")
        v = build_view(state, results, seat)
        info = g.seat_info(seat) if seat in g.human_seats() else None
        v["seat"] = {"seat": seat, "player": info["player"] if info else None,
                     "host": view_as or g.meta.get("host") == seat,
                     "submitted": seat in g.meta["submitted"] and n == g.state.turn,
                     "needs_orders": g.needs_orders(seat) and not view_as,
                     "view_as": view_as}
        v["current_turn"] = g.state.turn
        return v

    @app.get("/api/games/{gid}/report.txt", response_class=PlainTextResponse)
    def report_txt(gid: str, turn: Optional[int] = Query(default=None, ge=0),
                   x_seat_token: Optional[str] = Header(default=None)):
        """The turn's results as the classic 2008-style text report (mhgc/legacy_report.py),
        built from exactly the view /view returns for this seat and turn, so it shows nothing
        more.  The previous turn's own view supplies each system's initial stocks."""
        g = get(gid)
        with g.lock:
            return do_report(g, seat_or_401(g, x_seat_token), turn)

    def do_report(g: Game, seat: int, turn: Optional[int], view_as: bool = False) -> PlainTextResponse:
        v = do_view(g, seat, turn, view_as)
        n = v["game"]["turn"]
        prev = None
        if n > 0:
            try:
                ps, pr = g.turn_data(n - 1)
                if seat in ps.empires:
                    prev = build_view(ps, pr, seat)
            except HTTPException:
                prev = None
        return PlainTextResponse(legacy_report(v, prev), media_type="text/plain; charset=utf-8")

    # ---- orders
    @app.get("/api/games/{gid}/orders")
    def get_orders(gid: str, x_seat_token: Optional[str] = Header(default=None)):
        g = get(gid)
        with g.lock:
            return do_orders(g, seat_or_401(g, x_seat_token))

    def do_orders(g: Game, seat: int) -> dict:
        return {"turn": g.state.turn + 1, "orders": _order_rows(g.draft_orders(seat)),
                "submitted": seat in g.meta["submitted"]}

    @app.put("/api/games/{gid}/orders")
    def put_orders(gid: str, body: OrdersBody,
                   x_seat_token: Optional[str] = Header(default=None)):
        """Replace the draft.  Rejected whole (422) if any order has a syntax error.  Changing
        the draft withdraws a submission."""
        g = get(gid)
        with g.lock:
            seat = seat_or_401(g, x_seat_token)
            need_playing(g, seat)
            if body.orders is None and body.text is None:
                raise HTTPException(422, "Send 'orders' (a list) or 'text'")
            orders, errors, warnings = parse_order_input(body.orders, body.text)
            if errors:
                raise HTTPException(422, {"message": "Some orders are not valid",
                                          "errors": errors, "warnings": warnings})
            g.save_draft(seat, orders)
            aomt_from_orders(g, seat, orders)
            was = seat in g.meta["submitted"]
            if was:
                g.meta["submitted"].remove(seat)
            g.bump()
            g.save_meta()
            return {"turn": g.state.turn + 1, "orders": _order_rows(orders),
                    "warnings": warnings, "submitted": False, "withdrawn": was}

    @app.delete("/api/games/{gid}/orders")
    def clear_orders(gid: str, x_seat_token: Optional[str] = Header(default=None)):
        g = get(gid)
        with g.lock:
            seat = seat_or_401(g, x_seat_token)
            g.draft_path(seat).unlink(missing_ok=True)
            was = seat in g.meta["submitted"]
            if was:
                g.meta["submitted"].remove(seat)
            g.bump()
            g.save_meta()
            return {"turn": g.state.turn + 1, "orders": [], "submitted": False,
                    "withdrawn": was}

    @app.post("/api/games/{gid}/orders/check")
    def check(gid: str, body: Optional[OrdersBody] = None,
              x_seat_token: Optional[str] = Header(default=None)):
        """Dry-run the draft (or the orders in the body) against the current state.  Other
        empires' orders aren't known, so the real turn can differ.  Not a turn preview."""
        g = get(gid)
        with g.lock:
            return do_check(g, seat_or_401(g, x_seat_token), body)

    def do_check(g: Game, seat: int, body: Optional[OrdersBody]) -> dict:
        need_playing(g, seat)
        orders, errors, warnings = orders_for(g, seat, body)
        advice: list = []
        fixes: dict = {}
        results = check_orders(g.state, seat, orders, advice, fixes)
        rows = [dataclasses.asdict(r) for r in results]
        for i, row in enumerate(rows):
            row["advice"] = []
            row["fix"] = fixes.get(i)        # a failed order a Fix would make work (G-20)
        for a in advice:                    # non-blocking warnings (DECISIONS G-20)
            if 0 <= a["index"] < len(rows):
                rows[a["index"]]["advice"].append(a)
        return {"turn": g.state.turn + 1, "results": rows,
                "errors": errors, "warnings": warnings, "advice": advice,
                "ok": not errors and all(r.ok for r in results)}

    @app.post("/api/games/{gid}/production/preview")
    def production_preview_ep(gid: str, body: Optional[PreviewBody] = None,
                              x_seat_token: Optional[str] = Header(default=None)):
        """The Production tab: this seat's systems with their expected end-of-turn production,
        stockpiles and happiness, run by the real engine code on a copy holding only this
        empire's own objects (mhgc/engine/preview.py).  The draft's own orders are included;
        `overrides` tries other profiles.  Nothing is stored."""
        g = get(gid)
        with g.lock:
            return do_preview(g, seat_or_401(g, x_seat_token), body)

    @app.post("/api/games/{gid}/production/tweak")
    def production_tweak_ep(gid: str, body: Optional[TweakBody] = None,
                            x_seat_token: Optional[str] = Header(default=None)):
        """The split tweak (Dave 2026-11-18): for this seat's systems (or `systems`), the split
        within +-max_delta points of the current one (the draft's, then `overrides`) that gives
        the most units without lowering AU, IU or EU (engine/economy.tweak_split), on the same
        own-only copy as the preview.  A suggestion only: nothing is stored."""
        g = get(gid)
        with g.lock:
            return do_tweak(g, seat_or_401(g, x_seat_token), body)

    def do_tweak(g: Game, seat: int, body: Optional[TweakBody]) -> dict:
        overrides = preview_overrides(g, seat, body)
        own = {s.id for s in g.state.systems if s.owner == seat}
        systems = None
        if body is not None and body.systems is not None:
            bad = [x for x in body.systems if x not in own]
            if bad:
                raise HTTPException(422, {"message": "Some profiles are not valid",
                                          "errors": [{"system": str(x),
                                                      "error": "not one of your systems"}
                                                     for x in bad]})
            systems = body.systems
        return production_tweak(g.state, seat, g.draft_orders(seat), overrides, systems,
                                body.max_delta if body is not None else 3)

    def do_preview(g: Game, seat: int, body: Optional[PreviewBody]) -> dict:
        overrides = preview_overrides(g, seat, body)
        return production_preview(g.state, seat, g.draft_orders(seat), overrides)

    def preview_overrides(g: Game, seat: int, body: Optional[PreviewBody]) -> dict:
        need_playing(g, seat)
        own = {s.id for s in g.state.systems if s.owner == seat}
        overrides, errors = {}, []
        for k, v in (body.overrides if body else {}).items():
            try:
                sid = int(k)
                if sid not in own:
                    raise ValueError("not one of your systems")
                overrides[sid] = check_split(v.get("au"), v.get("iu"), v.get("eu"))
            except (ValueError, TypeError, OrderSyntaxError) as exc:
                errors.append({"system": k, "error": str(exc)})
        if errors:
            raise HTTPException(422, {"message": "Some profiles are not valid",
                                      "errors": errors})
        return overrides

    @app.post("/api/games/{gid}/submit")
    def submit(gid: str, body: Optional[OrdersBody] = None,
               x_seat_token: Optional[str] = Header(default=None)):
        """Submit the draft (optionally replacing it with the body first).  When every human seat
        is in, the turn runs straight away."""
        g = get(gid)
        with g.lock:
            seat = seat_or_401(g, x_seat_token)
            need_playing(g, seat)
            if body is not None and (body.orders is not None or body.text is not None):
                orders, errors, warnings = parse_order_input(body.orders, body.text)
                if errors:
                    raise HTTPException(422, {"message": "Some orders are not valid",
                                              "errors": errors, "warnings": warnings})
                g.save_draft(seat, orders)
                aomt_from_orders(g, seat, orders)
            if seat not in g.meta["submitted"]:
                g.meta["submitted"].append(seat)
            g.bump()
            g.save_meta()
            ran = None
            if g.all_in():
                ran = g.run()
            return {"submitted": ran is None, "turn_ran": ran is not None, "turn": g.state.turn,
                    "waiting_for": g.waiting_for()}

    @app.delete("/api/games/{gid}/submit")
    def withdraw(gid: str, x_seat_token: Optional[str] = Header(default=None)):
        g = get(gid)
        with g.lock:
            seat = seat_or_401(g, x_seat_token)
            if seat in g.meta["submitted"]:
                g.meta["submitted"].remove(seat)
                g.bump()
                g.save_meta()
            return {"submitted": False, "turn": g.state.turn, "waiting_for": g.waiting_for()}

    def aomt_from_orders(g: Game, seat: int, orders: list[Order]) -> None:
        """An AOMT order in a saved draft is a race setting: it takes effect at once, so it
        already covers a turn forced before this draft is submitted (W-29).  It runs again
        harmlessly with the turn."""
        last = [o for o in orders if o.code == "AOMT"]
        if last:
            g.set_aomt(seat, last[-1].mode == "ON")

    @app.post("/api/games/{gid}/aomt")
    def set_aomt(gid: str, body: AomtBody, x_seat_token: Optional[str] = Header(default=None)):
        """The race's "Autogenerate orders on missed turn" switch (Dave 2026-11-19, W-29): on, a
        turn the host forces before this race has submitted gets orders written by the computer
        from the race's own view.  Takes effect now and stays until switched off (or the seat is
        left).  Nobody else learns of it."""
        g = get(gid)
        with g.lock:
            seat = seat_or_401(g, x_seat_token)
            need_playing(g, seat)
            if g.set_aomt(seat, body.on):
                g.bump()
                g.save_meta()
            return {"aomt": g.state.empires[seat].aomt, "turn": g.state.turn}

    @app.post("/api/games/{gid}/force")
    def force(gid: str, body: Optional[ForceBody] = None,
              x_seat_token: Optional[str] = Header(default=None)):
        """Host only: run the turn now.  A seat that hasn't submitted plays by AOMT (on by default,
        W-30: its draft runs as if submitted, or the stand-in bot plays an empty draft); with
        AOMT off it gives no orders (W-10).  In a game
        no human gives orders in (W-24) this is "Run turn", the only way it advances; `turns`
        runs up to 20 turns there, one at a time (each committed and logged), stopping at the
        end of the game."""
        g = get(gid)
        with g.lock:
            who = host_or_403(g, x_seat_token, "force the turn")
            want = body.turns if body else 1
            if want > 1 and not g.host_runs():
                raise HTTPException(400, "Several turns at once only in a game no human gives "
                                         "orders in")
            ran = []
            for _ in range(want):
                if g.state.winner is not None and ran:
                    break
                quiet = g.host_runs()
                ran.append(g.run(forced_by=None if quiet else who))
                g.audit("run_turn" if quiet else "force_turn", who, ran=ran[-1])
            return {"turn_ran": True, "turn": g.state.turn, "turns_run": len(ran),
                    "finished": g.state.winner is not None}

    # ---- chat
    def visible(msg: dict, seat: Optional[int]) -> bool:
        return msg.get("to") is None or (seat is not None and seat in (msg["to"], msg["from"]))

    @app.get("/api/games/{gid}/chat")
    def get_chat(gid: str, since: int = Query(default=0, ge=0),
                 limit: int = Query(default=500, ge=1, le=2000),
                 x_seat_token: Optional[str] = Header(default=None)):
        """Game-wide messages, plus private messages to or from this browser's seat."""
        g = get(gid)
        with g.lock:
            return do_chat(g, g.seat_of(x_seat_token), since, limit)

    def do_chat(g: Game, seat: Optional[int], since: int, limit: int) -> dict:
        msgs = [m for m in g.chat if m["id"] > since and visible(m, seat)]
        return {"messages": msgs[-limit:], "last": g.meta.get("chat_next", 1) - 1,
                "recipients": recipients(g, seat) if seat else []}

    def recipients(g: Game, seat: int) -> list[dict]:
        """Who this seat may message privately: human-seat empires it has contact with."""
        me = g.state.empires[seat]
        out = []
        for oid in sorted(me.relations):
            if (oid in g.human_seats() and oid != seat
                    and g.state.empires[oid].kind == M.HUMAN):
                info = g.seat_info(oid)
                out.append({"empire": oid, "race": g.state.empires[oid].name,
                            "player": info["player"] if info else None})
        return out

    @app.post("/api/games/{gid}/chat")
    def post_chat(gid: str, body: ChatBody, x_seat_token: Optional[str] = Header(default=None)):
        """Post to everyone (`to` omitted) or privately to one empire.

        Rules basis: you may only deal with races you have made contact with (rules:710-713),
        and other players' addresses were shown only after contact (rules:242-245).  So a
        private message needs contact with the recipient, exactly like the diplomacy orders;
        game-wide chat is like a broadcast MESSAGE (no names = every race, rules:2585) and is
        always allowed.  Computer empires don't read chat."""
        g = get(gid)
        with g.lock:
            seat = seat_or_401(g, x_seat_token)
            text = body.text.strip()
            if not text:
                raise HTTPException(422, "Empty message")
            me = g.state.empires[seat]
            to_name = None
            if body.to is not None:
                if body.to == seat:
                    raise HTTPException(400, "That's you")
                if body.to not in me.relations:
                    raise HTTPException(403, "You can only message races you have contact with")
                if body.to not in g.human_seats() or g.state.empires[body.to].kind != M.HUMAN:
                    raise HTTPException(400, "Computer empires don't read chat")
                to_name = g.state.empires[body.to].name
            msg = g.add_chat({"from": seat, "from_name": me.name,
                              "player": g.seat_info(seat)["player"], "to": body.to,
                              "to_name": to_name, "text": text, "system": False})
            return msg

    @app.post("/api/games/{gid}/chat/{mid}/accept")
    def accept_offer(gid: str, mid: int, body: Optional[AcceptBody] = None,
                     x_seat_token: Optional[str] = Header(default=None)):
        """Accept a computer empire's trade offer from chat (DECISIONS A-08): add the matching
        TTNPR order to the recipient's draft (once; another alternative of the same offer is
        replaced).  Only the race the offer was made to, and only while it is open (the turn it
        names hasn't run, and the computer empire still holds it).  View as is read-only (the
        /as/ routes refuse every POST)."""
        g = get(gid)
        with g.lock:
            seat = seat_or_401(g, x_seat_token)
            msg = next((m for m in g.chat if m["id"] == mid), None)
            if msg is None or not msg.get("offer"):
                raise HTTPException(404, "No such offer")
            if msg.get("to") != seat:
                raise HTTPException(403, "That offer was made to another race")
            need_playing(g, seat)
            off = msg["offer"]
            alt = (body.alt if body else 0) or 0
            n_alts = 1 if off.get("any") else len(off["wants"])
            if not 0 <= alt < n_alts:
                raise HTTPException(422, "No such alternative")
            mem = g.state.npr_state.get(msg["from"]) or {}
            held = (mem.get("hoffers") or {}).get(str(seat)) or {}
            bot = g.state.empires.get(msg["from"])
            if (g.state.turn >= off["until"] or held.get("id") != off["id"] or bot is None
                    or bot.kind != M.NPR):
                raise HTTPException(409, "That offer has expired")
            if off.get("any"):           # "any <cost> EU tech of yours" (DECISIONS G-23)
                order = order_from_dict({"code": "TTNPR", "give_any_cost": off["any"],
                                         "want": off["give"], "race": bot.name})
            else:
                order = order_from_dict({"code": "TTNPR", "give": off["wants"][alt],
                                         "want": off["give"], "race": bot.name})
            mine = {(w, None, off["give"]) for w in off["wants"]}
            if off.get("any"):
                mine.add((None, off["any"], off["give"]))
            key = lambda o: (o.give, o.give_any_cost, o.want)    # noqa: E731
            orders, added = [], True
            for o in g.draft_orders(seat):
                if o.code == "TTNPR" and key(o) in mine and \
                        str(o.race).lower() == bot.name.lower():
                    if key(o) == key(order):
                        added = False
                        orders.append(o)
                    continue                            # another alternative: replaced
                orders.append(o)
            others = [o for o in orders if o.code == "TTNPR" and o not in (order,)]
            if added:
                orders.append(order)
            g.save_draft(seat, orders)
            was = seat in g.meta["submitted"]
            if was:
                g.meta["submitted"].remove(seat)
            g.bump()
            g.save_meta()
            warn = (["You have another TTNPR in your orders: only one tech trade with a computer "
                     "empire is tried each turn."] if others else [])
            return {"added": added, "order": {**order.to_dict(), "text": order.to_text()},
                    "turn": g.state.turn + 1, "orders": _order_rows(orders),
                    "warnings": warn, "submitted": False, "withdrawn": was}

    register_analysis(app, get)                   # final standings and export (W-16, W-17)

    # ---- static UI
    app.mount("/static", StaticFiles(directory=ROOT / "ui"), name="static")

    @app.get("/")
    def index():
        return FileResponse(ROOT / "ui" / "index.html")

    return app


app = create_app()
