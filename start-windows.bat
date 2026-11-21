@echo off
rem Mega Hyper Galactic Conquest: run it on this computer.
rem First run: makes a private Python environment in .venv and installs FastAPI and Uvicorn from the
rem bundled "wheels" folder, so no internet is needed (handy behind a company network).
rem After that it just starts the game. Close this window to stop it.
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (set PY=py -3) else (set PY=python)

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>nul
if errorlevel 1 (
  echo This needs Python 3.10 or newer. Install it from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during the install, then run this again.
  pause
  exit /b 1
)

if not exist .venv\Scripts\python.exe (
  echo Setting up for the first time, this takes a minute...
  %PY% -m venv .venv || goto :fail
)
rem install (or finish a half-done install) whenever the game's packages aren't all there
.venv\Scripts\python -c "import fastapi, uvicorn" 2>nul
if errorlevel 1 (
  echo Installing the game's packages...
  .venv\Scripts\python -m pip install --quiet --no-index --find-links wheels -r requirements.txt || (
    echo The bundled packages didn't fit this Python, trying the internet instead...
    .venv\Scripts\python -m pip install --quiet -r requirements.txt || goto :fail
  )
)

echo.
echo Starting Mega Hyper Galactic Conquest at http://127.0.0.1:8790/
echo Your games are saved in the "saves" folder next to this file.
echo Close this window (or press Ctrl+C) to stop the game.
echo.
start "" http://127.0.0.1:8790/
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8790
exit /b 0

:fail
echo Setup failed. Delete the .venv folder and run this again; the messages above say what went wrong.
pause
exit /b 1
