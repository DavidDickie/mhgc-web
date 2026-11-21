# MHGC web: version history

The version is shown at the foot of the ☰ menu (top right), by `/api/health`, and in every
export's `manifest.json` (`app_version`). It lives in `mhgc/__init__.py` (`__version__`,
`__version_date__`) and `pyproject.toml`; bump it with every zip rebuild and add a line here.

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
