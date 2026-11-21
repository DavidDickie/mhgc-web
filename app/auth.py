"""Race passwords and login sessions (Dave 2026-11-15, DECISIONS W-21).

A human seat ("race") in a game has
  pw        {alg: "scrypt", n, r, p, salt, hash} (a salted slow hash; never the password), or
            None: a seat from before passwords (or one whose holder never set one)
  must_set  True when the race must choose a new password before it can play (after a host
            reset, or a pre-password seat on its next visit)
  sessions  [{h, t}]: SHA-256 hashes of the random session tokens (one per logged-in browser),
            sent by the browser in X-Seat-Token.  Tokens are 128 random bits, so a fast hash is
            enough for them; passwords get scrypt.
None of this ever leaves the server: the public seat summary says only whether a password is set.

Sessions are restricted ("must set a password") when the seat has no password or `must_set` is
on; a restricted session can only read the game summary, set its password or log out.

There is no limit on wrong password tries (Dave 2026-11-15: "This isn't a critical security app,
it's just a few players"); passwords are still hashed and compared in constant time.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Optional

PW_MIN = 4
PW_MAX = 200
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}       # ~40 ms, 16 MB
MAX_SESSIONS = 50                              # per race; the oldest are dropped


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_hex(16)


def check_password_rules(pw) -> str:
    """-> the password, or raises ValueError with a message for the player."""
    if not isinstance(pw, str) or len(pw) < PW_MIN:
        raise ValueError(f"A password needs at least {PW_MIN} characters")
    if len(pw) > PW_MAX:
        raise ValueError(f"A password can have at most {PW_MAX} characters")
    return pw


def hash_password(pw: str) -> dict:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode("utf-8"), salt=salt, dklen=32, maxmem=64 * 2 ** 20, **SCRYPT)
    return {"alg": "scrypt", **SCRYPT, "salt": salt.hex(), "hash": h.hex()}


def verify_password(pw: str, rec: Optional[dict]) -> bool:
    if not rec or rec.get("alg") != "scrypt" or not isinstance(pw, str):
        return False
    try:
        h = hashlib.scrypt(pw.encode("utf-8"), salt=bytes.fromhex(rec["salt"]), dklen=32,
                           maxmem=64 * 2 ** 20, n=rec["n"], r=rec["r"], p=rec["p"])
    except (KeyError, ValueError, TypeError):
        return False
    return hmac.compare_digest(h.hex(), rec["hash"])


def migrate_seat(info: Optional[dict]) -> bool:
    """Bring a seat record from before passwords up to date in place: its single browser token
    becomes its one session, and it has no password yet.  -> True if anything changed."""
    if not info:
        return False
    changed = False
    if "sessions" not in info:
        th = info.pop("token_hash", None)
        info["sessions"] = [{"h": th, "t": info.get("joined", 0)}] if th else []
        changed = True
    if "pw" not in info:
        info["pw"] = None
        changed = True
    if "must_set" not in info:
        info["must_set"] = False
        changed = True
    return changed


def add_session(info: dict) -> str:
    tok = new_token()
    info.setdefault("sessions", []).append({"h": token_hash(tok), "t": time.time()})
    del info["sessions"][:-MAX_SESSIONS]
    return tok


def drop_session(info: dict, token: str) -> bool:
    h = token_hash(token)
    before = len(info.get("sessions", []))
    info["sessions"] = [s for s in info.get("sessions", []) if not hmac.compare_digest(s["h"], h)]
    return len(info["sessions"]) != before


def restricted(info: dict) -> bool:
    """The race must set a password before it can play."""
    return info.get("pw") is None or bool(info.get("must_set"))
