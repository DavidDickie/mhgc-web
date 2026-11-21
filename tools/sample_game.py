#!/usr/bin/env python3
"""Play a sample game through the real web API and export it for analysis.

    python tools/sample_game.py OUT.zip [--turns 70] [--size 8] [--seed 7] [--vp 100]

Seat 1 is a "human" seat played by the baseline bot (mhgc/npr/baseline.py) from the same view a
browser gets, submitting its orders through PUT/submit like a player; every other seat is a
computer empire.  The game runs in a temporary SAVE_DIR (or --save-dir) and is exported with
GET /export as the host (allowed: every other seat is a computer empire, DECISIONS W-17).
`--vp` lowers the victory target for a short test game that ends.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def play(out: Path, turns: int = 70, size: int = 8, seed: int = 7, vp: int | None = None,
         save_dir: str | None = None, quiet: bool = False) -> dict:
    from fastapi.testclient import TestClient

    from app.main import create_app
    from mhgc.data import constants as K
    from mhgc.npr.baseline import baseline_orders
    from mhgc.npr.memory import new_memory
    from mhgc.rng import Rng

    old_vp = K.VICTORY_POINTS
    if vp is not None:
        K.VICTORY_POINTS = vp
    try:
        c = TestClient(create_app(save_dir or tempfile.mkdtemp(prefix="mhgc-sample-")))
        r = c.post("/api/games", json={"password": "secret1", "host_password": "secret1",
                                       "name": "Sample: baseline human vs bots", "humans": 1,
                                       "size": size, "player": "Scripted", "race": "Scripties",
                                       "seed": seed, "chatter": "quiet"})
        r.raise_for_status()
        gid, tok = r.json()["id"], r.json()["token"]
        H = {"X-Seat-Token": tok}
        mem = new_memory(seed, 1, 0, "builder")
        times = []
        for _ in range(turns):
            v = c.get(f"/api/games/{gid}/view", headers=H).json()
            if v["game"].get("winner"):
                break
            orders = baseline_orders(v, mem, Rng(seed, v["game"]["turn"], "scripted-human"))
            t0 = time.perf_counter()
            r = c.post(f"/api/games/{gid}/submit", headers=H,
                       json={"orders": [o.to_dict() for o in orders]})
            times.append(time.perf_counter() - t0)
            r.raise_for_status()
            if not quiet and v["game"]["turn"] % 10 == 0:
                print(f"turn {v['game']['turn']}: {len(orders)} orders, "
                      f"{times[-1]:.2f}s", file=sys.stderr)
        r = c.get(f"/api/games/{gid}/export", headers=H)
        r.raise_for_status()
        out.write_bytes(r.content)
        fin = c.get(f"/api/games/{gid}")
        return {"gid": gid, "turn": fin.json()["turn"], "seconds": times,
                "finished": fin.json()["finished"], "client": c, "token": tok}
    finally:
        K.VICTORY_POINTS = old_vp


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--turns", type=int, default=70)
    ap.add_argument("--size", type=int, default=8)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--vp", type=int, default=None)
    ap.add_argument("--save-dir", default=None)
    a = ap.parse_args()
    r = play(a.out, a.turns, a.size, a.seed, a.vp, a.save_dir)
    s = r["seconds"]
    print(f"game {r['gid']}: turn {r['turn']}, finished={r['finished']}, "
          f"{sum(s) / max(1, len(s)):.2f}s per turn; wrote {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
