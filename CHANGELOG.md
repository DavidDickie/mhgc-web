# MHGC web: version history

The version is shown at the foot of the ☰ menu (top right), by `/api/health`, and in every
export's `manifest.json` (`app_version`). It lives in `mhgc/__init__.py` (`__version__`,
`__version_date__`) and `pyproject.toml`; bump it with every zip rebuild and add a line here.

## 5.0.4 (2026-11-27)
- Renumbered as "big" version 5 (Dave 2026-11-27): MHGC web is the fifth major version of the game. Same code as 1.0.4; earlier builds 1.0.0-1.0.4 correspond to 5.0.0-5.0.4 (exports made with them still say 1.0.x).

## 1.0.4 (2026-11-24)
- G-30 two new game sizes on a 5x5 grid of bins (125x125): 25 empires, and 20 empires with five open bins a knight's move apart, so every empire has exactly two open bins beside it (one side-on, one corner-on).
- Up to 25 empires a game: nine more default race names with their own system names; order coordinates accepted up to 124 (each game still checks its own board).
- The New game dialog shows seven sizes with their bins and board ("5×5, 125×125"); the map's axis labels no longer crowd the seam on the 125 board.
- DEPLOY.md: the full size list, and forced turns play unsubmitted seats by AOMT (W-30).

## 1.0.3 (2026-11-22)
- G-28 the win target is back to 100 VP for new games (supersedes G-26); it is now stored per game, and games created before this version keep 90.
- G-29 transports (Transport, MassTransit) start in the Ground Combat role, when built without a role and at the start of a game; existing ships keep theirs.
- W-32 every dropdown of systems, fleets and races is alphabetical (case-insensitive, natural: Fleet2 before Fleet10); the Production tab stays by population, largest first.

## 1.0.2 (2026-11-21)
- G-27 amended: merging a fleet transfers its admiral to the merged fleet when that fleet has none; a leader on the way to the merged-away fleet goes on to the merged fleet.

## 1.0.1 (2026-11-21)
- G-27 new order `MGF <fleet> <into fleet>`: merge two of your fleets on the same square; "Merge into…" on a fleet's card.
- W-31 the Load and Unload dialogs count the cargo orders already in your draft, so a transport can unload and then load on the same turn (new loads go after the unloads).

## 1.0.0 (2026-11-20)
First numbered build. Everything up to and including:
- A-11 bots set up CTT trade routes with any race they are not at war with.
- A-12 bots declare war when another race's warships come within one move of their worlds.
- W-30 AOMT on by default; an unsubmitted draft runs before the stand-in bot.
- Balanced production preset confirmed at 20/40/40.
