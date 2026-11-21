"""Wrap-around board geometry (rules:223-231): a square torus, square (Chebyshev) moves and scans.

The board side is a game parameter (`GameState.board`): 100 for the classic 16-empire map, 75 for
the 3x3-bin maps, 50 for the 2x2 (Dave 2026-11-13 and 11-16, DECISIONS W-13, W-26).  Every function takes `board`, defaulting to
the classic 100, so callers with a game state pass `st.board`.
"""
from __future__ import annotations

from .data.constants import BOARD


def home_rel(board: int = BOARD) -> tuple[int, int]:
    """Where each empire sees its own home: the board centre (50,50 on 100; 37,37 on 75; 25,25 on 50)."""
    return board // 2, board // 2


def wrap(v: int, board: int = BOARD) -> int:
    return v % board


def axis_delta(a: int, b: int, board: int = BOARD) -> int:
    """Signed shortest step from a to b on one axis (-50..50 on 100; a distance of exactly half
    the board goes in the positive direction)."""
    d = (b - a) % board
    return d - board if d > board // 2 else d


def distance(x1: int, y1: int, x2: int, y2: int, board: int = BOARD) -> int:
    """Chebyshev distance on the torus (gcutils.c:377 move_distance)."""
    return max(abs(axis_delta(x1, x2, board)), abs(axis_delta(y1, y2, board)))


def step_axis(loc: int, dest: int, speed: int, board: int = BOARD) -> int:
    """Move up to `speed` squares along one axis by the shortest path (gcutils.c:311 move)."""
    d = axis_delta(loc, dest, board)
    if abs(d) <= speed:
        return wrap(dest, board)
    return wrap(loc + (speed if d > 0 else -speed), board)


def step(x: int, y: int, dx: int, dy: int, speed: int, board: int = BOARD) -> tuple[int, int]:
    return step_axis(x, dx, speed, board), step_axis(y, dy, speed, board)


def to_rel(x: int, y: int, home_x: int, home_y: int, board: int = BOARD) -> tuple[int, int]:
    """Absolute -> empire-relative coordinates (home appears at the board centre; gcutils.c:335
    cxator)."""
    c = board // 2
    return wrap(x + c - home_x, board), wrap(y + c - home_y, board)


def to_abs(rx: int, ry: int, home_x: int, home_y: int, board: int = BOARD) -> tuple[int, int]:
    """Empire-relative -> absolute coordinates (gcutils.c:347 cxrtoa)."""
    c = board // 2
    return wrap(rx - c + home_x, board), wrap(ry - c + home_y, board)
