#!/usr/bin/env bash
# Mega Hyper Galactic Conquest: run it on this computer.
# First run: makes a private Python environment in .venv and installs FastAPI and Uvicorn (needs internet).
# After that it just starts the game. Press Ctrl+C to stop it.
set -e
cd "$(dirname "$0")"

PY=$(command -v python3 || command -v python || true)
if [ -z "$PY" ] || ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "This needs Python 3.10 or newer: https://www.python.org/downloads/"
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "Setting up for the first time, this takes a minute..."
  "$PY" -m venv .venv
fi
# install (or finish a half-done install) whenever the game's packages aren't all there
if ! .venv/bin/python -c 'import fastapi, uvicorn' 2>/dev/null; then
  echo "Installing the game's packages..."
  # the bundled wheels folder is for Windows; elsewhere this falls back to the internet
  .venv/bin/python -m pip install --quiet --no-index --find-links wheels -r requirements.txt 2>/dev/null \
    || .venv/bin/python -m pip install --quiet -r requirements.txt
fi

URL=http://127.0.0.1:8790/
echo
echo "Starting Mega Hyper Galactic Conquest at $URL"
echo "Your games are saved in the 'saves' folder next to this file. Press Ctrl+C to stop."
echo
( sleep 2; (command -v open >/dev/null && open "$URL") || (command -v xdg-open >/dev/null && xdg-open "$URL") || true ) >/dev/null 2>&1 &
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8790
