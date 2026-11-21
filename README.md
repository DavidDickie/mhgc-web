# Mega Hyper Galactic Conquest (web)

A web version of Dave's 2008 play-by-email strategy game. The rules are `docs/RULEBOOK.md`
(edited from Dave's original rules); every rules decision is in `docs/DECISIONS.md`; progress and
the API summary are in `STATUS.md`.

## Run it locally
```
cd ~/mhgc/mhgc-web
~/mhgc/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8790
```
Then open http://127.0.0.1:8790/ (in Coder, forward the port). The interactive API documentation
is at `/docs`. Games are saved under `./saves` unless `SAVE_DIR` says otherwise.

To make the venv from scratch:
```
~/.local/bin/uv venv --python 3.11 ~/mhgc/venv   # 3.10 works too
VIRTUAL_ENV=~/mhgc/venv ~/.local/bin/uv pip install -r requirements-dev.txt
```
Any Python 3.10+ with `pip install -r requirements-dev.txt` works too.

## Tests
```
~/mhgc/venv/bin/python -m pytest -q
```

## Layout
```
mhgc/            the game engine (pure Python, no web code)
  mapgen.py      new games: 8/9 empires on 75x75 or 12/16 on 100x100
  orders.py      order types, the classic text parser and the order catalogue
  engine/        the turn: run_turn(state, orders) -> TurnResults, check_orders(...)
  view.py        the per-player fog-of-war read model sent to browsers
app/main.py      FastAPI server: games, seats, orders, turns, chat, history (JSON under /api)
app/catalogue.py order catalogue and reference tables for the UI
app/ui/          the browser UI (placeholder until stage 3)
tests/           engine, view and API tests
render.yaml      Render blueprint (see DEPLOY.md)
```

## How a game works
- A game has 4, 8 (the default), 9, 12 or 16 empires on a wrap-around board (50x50 for 4,
  75x75 for 8 and 9, 100x100 for 12 and 16). The creator picks the size and how many are human seats; the rest are
  computer empires, which name their worlds and boast in the chat (off / quiet / normal).
- A seat is tied to the browser that took it (a random token in localStorage, sent as the
  `X-Seat-Token` header). No passwords.
- Players draft orders, check them against the current state, and submit. A turn runs as soon as
  every human seat is taken and submitted; the host (the creator) can force it.
- The browser only ever sees its own empire plus what its scans show, in coordinates relative to
  its home (the board centre: 50,50, or 37,37 on 75x75).
