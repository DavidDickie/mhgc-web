"""Seeded, reproducible randomness.

Each turn gets its own stream derived from (game seed, turn, purpose), so replaying a turn from a
saved state with the same orders gives the same result, and nothing about the stream leaks between
turns.  The C engine seeded `srand(turn)` once per turn (gcrun.c:121); we use Python's Mersenne
Twister seeded with a string, which Python hashes with SHA-512 (stable across platforms).
"""
from __future__ import annotations

import random


class Rng:
    def __init__(self, seed: int, turn: int, purpose: str = "turn"):
        self.seed_text = f"mhgc:{seed}:{turn}:{purpose}"
        self._r = random.Random(self.seed_text)

    # C idioms -------------------------------------------------------------------------------
    def pct(self) -> int:
        """0..99, the C `my_rand() % 100`."""
        return self._r.randrange(100)

    def chance(self, percent: float) -> bool:
        """True with probability percent/100."""
        return self._r.random() * 100.0 < percent

    def below(self, n: int) -> int:
        """0..n-1 (n >= 1)."""
        return self._r.randrange(n)

    def between(self, lo: int, hi: int) -> int:
        """lo..hi inclusive."""
        return self._r.randint(lo, hi)

    def random(self) -> float:
        return self._r.random()

    def choice(self, seq):
        return self._r.choice(seq)

    def shuffle(self, seq) -> None:
        self._r.shuffle(seq)

    def sample(self, seq, k: int):
        return self._r.sample(seq, k)

    def fork(self, purpose: str) -> "Rng":
        """An independent stream (e.g. for order checking) that does not disturb this one."""
        r = Rng.__new__(Rng)
        r.seed_text = f"{self.seed_text}/{purpose}"
        r._r = random.Random(r.seed_text)
        return r

    def new_number(self, used, limit: int) -> int:
        """Random unit number in 1..limit-1 not in `used` (linear probe, as create_ship did,
        gcparser.c:2532)."""
        k = self._r.randrange(1, limit)
        for _ in range(limit):
            if k not in used:
                return k
            k = k + 1 if k + 1 < limit else 1
        raise RuntimeError("unit numbers exhausted")
