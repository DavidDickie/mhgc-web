"""Scan history: the set of board squares an empire has ever had inside one of its scans.

Stored per empire as `Empire.scan_history`, a board x board bitmask (100x100 on the classic map,
75x75 on the 3x3-bin maps, 50x50 on the 2x2, 125x125 on the 5x5): bit (y * board + x) of a little-endian integer, so square (x, y) is
byte (y*board+x) // 8, bit (y*board+x) % 8 (LSB first).  The bytes are kept as base64 (1668
characters at 100, 940 at 75, 420 at 50, 2608 at 125) so the save stays plain JSON; "" means nothing scanned yet (saves
from before 2026-11-13 load that way).  The view sends the same encoding re-based to the empire's
relative coordinates (`to_relative`).

In memory a mask is a list of `board` row ints (bit x of row y), so marking a scan box is one OR
per row of the box.  Every function takes the board side, defaulting to the classic 100.
"""
from __future__ import annotations

import base64

from .data.constants import BOARD


def nbytes(board: int = BOARD) -> int:
    return (board * board + 7) // 8


NBYTES = nbytes(BOARD)


def _full(board: int) -> int:
    return (1 << board) - 1


def decode(text: str, board: int = BOARD) -> list[int]:
    if not text:
        return [0] * board
    n = int.from_bytes(base64.b64decode(text), "little")
    full = _full(board)
    return [(n >> (y * board)) & full for y in range(board)]


def encode(rows: list[int], board: int = BOARD) -> str:
    n = 0
    full = _full(board)
    for y in range(board - 1, -1, -1):
        n = (n << board) | (rows[y] & full)
    return base64.b64encode(n.to_bytes(nbytes(board), "little")).decode("ascii") if n else ""


def _span(x: int, r: int, board: int = BOARD) -> int:
    """Row bits for columns x-r .. x+r on the torus."""
    full = _full(board)
    if 2 * r + 1 >= board:
        return full
    lo = (x - r) % board
    bits = ((1 << (2 * r + 1)) - 1) << lo
    return (bits | (bits >> board)) & full


def mark(rows: list[int], x: int, y: int, r: int, board: int = BOARD) -> None:
    """Add the square scan box of radius r around (x, y) (rules:229-231, Chebyshev)."""
    r = max(0, r)
    span = _span(x, r, board)
    if 2 * r + 1 >= board:
        ys = range(board)
    else:
        ys = ((y + d) % board for d in range(-r, r + 1))
    for yy in ys:
        rows[yy] |= span


def _rotl(row: int, s: int, board: int = BOARD) -> int:
    s %= board
    return ((row << s) | (row >> (board - s))) & _full(board) if s else row


def to_relative(text: str, home_x: int, home_y: int, board: int = BOARD) -> str:
    """The same mask in the empire's relative coordinates (home at the board centre)."""
    if not text:
        return ""
    rows = decode(text, board)
    c = board // 2
    sx, sy = c - home_x, c - home_y
    out = [0] * board
    for y, row in enumerate(rows):
        out[(y + sy) % board] = _rotl(row, sx, board)
    return encode(out, board)


def is_set(text: str, x: int, y: int, board: int = BOARD) -> bool:
    if not text:
        return False
    return bool(decode(text, board)[y % board] >> (x % board) & 1)


def count(text: str, board: int = BOARD) -> int:
    return sum(bin(r).count("1") for r in decode(text, board))


def union(a: str, b: str, board: int = BOARD) -> str:
    """Every square in either mask."""
    if not a or a == b:
        return b
    if not b:
        return a
    return encode([x | y for x, y in zip(decode(a, board), decode(b, board))], board)
