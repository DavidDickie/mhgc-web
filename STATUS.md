Trade routes, proximity war and AOMT on by default (2026-11-20): computer empires with Decentralized Trading build or take over transports and set up CTT trade routes at the systems of races they are not at war with, valued by the engine's 25% DCT rule (`npr/ctt.py`, DECISIONS A-11); a computer empire declares war on a race whose warships come within one move of its worlds, offers no peace while they stay, and keeps its own warships out of other races' reach (A-12); AOMT is on by default, reset to on when a seat is left or taken, and on a forced turn an unsubmitted non-empty draft now runs as if submitted, the bot standing in only for an empty draft (W-30, amending W-29 and W-10). The Balanced production preset 20/40/40 is confirmed (G-14). Tests `tests/test_npr_ctt_proximity.py` (10) and `tests/test_aomt_handicap.py`; measurements in STATUS-npr.md.

Ship rebalance (2026-11-19): the standard line is a bit stronger, Destroyer 3/5 (was 2/4), Cruiser 7/12 (6/10), Battleship 12/16 (10/14), HvyBattleship 16/18 (14/16), Dreadnought 24/24 (20/20), and the DeathStar much stronger, 45/12 (30/8); fast line, upkeep, costs and all other ships unchanged; ships in old saves get the new stats on load (DECISIONS G-25, `data/ships.py`). The RULEBOOK combat example now has the Groachi with two Scouts so the role shift still happens. The bots' short-line bonus breaks ties STANDARD, DEFENSIVE, OFFENSIVE, FAST (`npr/war.py SHORT_ORDER`), so they now build DeathStars and Eliminators as well as many more Cruisers and Battleships. Tests `tests/test_ship_rebalance.py` (5); measurements in STATUS-npr.md.

Artifact repricing (2026-11-19): static new prices, CB 100/100, VRB 150/150, BF 100/0, AF 75/75, CM and AL 150/150, EHC 75/0, CS 100/100 with upkeep 4, FP 50/50, WT 75/75; tech 42 and Warp Tunnel cost 2000 (WT is now 2 VP); the ANY list is unchanged; built artifacts stay, and the new upkeep applies from the next turn (DECISIONS G-24, `data/artifacts.py`, `data/techs.py`). The bots now build and use farcasters and warp tunnels towards far fronts (`npr/portals.py`). Tests `tests/test_artifact_prices.py` (12); RULEBOOK TECHNOLOGIES and CHARTS; measurements in STATUS-npr.md.

TTNPR ANY (2026-11-19): either side of a tech trade with a computer empire can be `ANY <cost>` (or `ANY:<cost>`), any tech of exactly that list price, picked by the computer empire when the turn runs (of its own, the one it values least that you lack and can use; of yours, the one it values most that it lacks and can use); no eligible tech is a failed check that doesn't use the turn's attempt; Check orders picks nothing and reveals nothing of the NPR's techs; the results name both techs; bots that don't know your techs offer "for any 500 EU technology of yours that we lack", and Accept adds the matching ANY order (DECISIONS G-23, C-07, A-08). Form: "Any tech costing..." with a cost picker. Tests `tests/test_ttnpr_any.py` (27); browser script `~/mhgc/work/uitest/ttnprany.py` (in run_all.sh), all_orders case TTNPR-ANY; RULEBOOK TTNPR section; STATUS-npr.md.

Ship picker groups, AOMT and the host handicap (2026-11-19): the Build ship picker and the Forces type filter list ships by the rules' groups (Scouts, Transports, then the Standard, Offensive, Defensive and Fast lines of the Mixed Fleet Bonus), by tech level then cost within a group (DECISIONS G-22, `data/ships.py SHIP_GROUPS/SHIP_ORDER`); **AOMT** "Autogenerate orders on missed turn", a per-race setting (Empire tab checkbox, `POST /api/games/{gid}/aomt`, or the order `AOMT ON|OFF`): on a forced turn a race that hasn't submitted gets orders written by the bot from its own view, as a caretaker (no diplomacy, messages or renames), its unsubmitted draft ignored, a notice in its report, logged in the host audit and bot logs (W-29, `npr.aomt_orders_traced`, `GameState.aomt_state`); the **host handicap**: the host's own race in a game with another human player can't win, gets no stat-bonus VP and is left out of the ranking pool, shown "(host, unranked)" (W-28, `GameState.unranked` set by `Game.handicapped()` before every turn). Tests `tests/test_aomt_handicap.py` (14); browser script `~/mhgc/work/uitest/aomt.py`; STATUS-ui.md, STATUS-npr.md.

Build counts, check warnings, fleets on the Forces tab (2026-11-18): BS/BCU take an optional count 1-50, built unit by unit with partial results (DECISIONS G-19); Check orders gives non-blocking ⚠ warnings for a cargo order after a warp of the same unit (with a Fix that moves it before the warp), for cargo unloaded where the draft loaded it on a unit that moves, and for names a rename in the draft changes; cargo orders that fail because the unit is still travelling say where it is and when it arrives (amended 2026-11-18: no warning for an ordinary move and load), with a one-click Fix (G-20, `mhgc/engine/advice.py`); the Forces tab lists ships in fleets under their fleet (W-27). Tests `tests/test_build_count_advice.py` (+ ledger cases); browser script `~/mhgc/work/uitest/buildcount.py`; STATUS-ui.md.

Races, passwords and the host (2026-11-15): race passwords and sessions, several races per browser, host reset, migration of old seats (W-21); hand a race to the computer and back (W-22); the host login, host-only games, View as and the host audit log (W-23); games only the host advances, Run turn / Run 5 turns (W-24); the host exports any time (W-17). Code: `app/auth.py`, `app/main.py`, `app/ui/account.js`, `app/ui/lobby.js`; tests `tests/test_auth.py`, `tests/test_host.py`; browser script `~/mhgc/work/uitest/access.py`.

Fleet cleanup and ground aftermath (2026-11-16): empty fleets are disbanded at the end of the turn (a new CF/CFXY fleet gets one turn to receive ships), and battle cards, the selection panel and the classic report show each side's ground forces before → after (DECISIONS G-18; `tests/test_fleet_cleanup.py`; browser script `~/mhgc/work/uitest/aftermath.py`; STATUS-ui.md).

# MHGC web: status after stage 2 (2026-11-12; game sizes and computer chatter added 2026-11-13)

- **Stage 1** delivered the rules decisions, the player rulebook, the game data and a complete first-cut turn engine with structured results.
- **Stage 2** (this stage) delivered the web backend: the per-player read model `mhgc/view.py`, the FastAPI app `app/main.py`, deployment files and API tests. See "Stage 2: web backend" below.
- There is no real UI yet (stage 3), and no NPR AI (stage 4).

The governing rulings are Dave's, dated 2026-11-12:

- The rules (`~/mhgc/mhgc_rules.txt`) are gospel.
- Where the rules are silent, the C code is used.
- Bugs are fixed, and nothing is replicated bit-exactly.

`docs/DECISIONS.md` records every resolution. Its section 1 lists the 12 open questions for Dave, each with the default in use.


Analysis features (2026-11-14): the bot decision log, the all-race standings log, Final standings, Export for analysis with `tools/analyze_game.py`, and the Rules tab. See `STATUS-analysis.md` and DECISIONS A-05 and W-15 to W-18.

## How to run the tests

```
cd ~/mhgc/mhgc-web
~/mhgc/venv/bin/python -m pytest -q -p no:cacheprovider   # 557 tests (2026-11-19), about 160 s, all passing
```

The venv is `~/mhgc/venv` (Python 3.11, made with `uv venv`). It contains pytest, fastapi, uvicorn, httpx and pyflakes. To recreate it:

```
~/.local/bin/uv venv --python 3.11 ~/mhgc/venv
VIRTUAL_ENV=~/mhgc/venv ~/.local/bin/uv pip install -r requirements-dev.txt
```

A quick end-to-end check:

```
~/mhgc/venv/bin/python -c "
from mhgc.mapgen import new_game; from mhgc.engine.turn import run_turn; from mhgc.orders import parse_orders
g = new_game('demo', 1, ['Dave']); h = g.system_at(g.empires[1].home_x, g.empires[1].home_y)
r = run_turn(g, {1: parse_orders(f'BS {h.name} F\nPT 2')}); print([(o.text, o.ok, o.error) for o in r.report(1).orders])"
```

## Done in stage 1

### Documents

| File | Contents |
|---|---|
| `docs/DECISIONS.md` | Resolutions for all 45 key items in ENGINE_MAP §5, every row of the subsystem tables (10.12, 20, 30.7, B.6, 4.12, 50.10), the C bugs fixed (B-01..B-48, M-01..M-08), the web decisions (W-01..W-06) and the implementation notes (C-01..C-07, D-02..D-13). |
| `docs/RULEBOOK.md` | Dave's rules as an edited Markdown copy (1921 lines). Orders are presented as UI actions with their classic codes, the email material is removed, and the turn flow is "submit; the turn runs when everyone is in, or when the host forces it". The tables follow DECISIONS F-01. It was written by a helper agent and spot-checked. See its own caveats below. |

### Game data (`mhgc/data/`)

| Module | Contents |
|---|---|
| `techs.py` | The 52 technologies (ids are the player-visible numbers 0..51), with costs, prerequisites, VP and artifact keys. |
| `ships.py` | 28 ship classes with line types for the Mixed Fleet Bonus. `UN` is gone. |
| `troops.py` | 8 troop types and their postures. |
| `artifacts.py` | 16 artifacts plus the spy (`BT S`). |
| `races.py` | Race naming and empire kinds. |
| `constants.py` | Every tunable value, each annotated with the rule or C line it comes from. |
| `flavour.py` | Dave's report texts: leader descriptions and comments, event texts, combat wording. |

### Core modules

| Module | Contents |
|---|---|
| `model.py` | Dataclasses for System, Ship, Fleet, Troop, Leader, Spy, Empire and GameState, plus JSON save/load (`dumps`/`loads`/`save`/`load`). A round trip is exact, and a reloaded game continues identically (tested). |
| `rng.py` | Seeded per turn from (game seed, turn, purpose), so turns are reproducible. |
| `geometry.py` | Torus distance, square movement, and relative/absolute coordinates (home appears at the board centre to its owner: 50,50 on 100x100, 37,37 on 75x75, 25,25 on 50x50). Every function takes the board side (`st.board`). |
| `orders.py` | Typed order classes generated from one spec table (`ORDER_SPECS`, about 100 codes). They support `make_order`, `order_from_dict`, `to_dict` and `to_text`. The classic parser `parse_line` / `parse_orders_text` handles MESSAGE blocks, comments, the `#U` rule, optional-argument warnings and headers. GM/NPR cheat codes are rejected. `catalogue()` gives a machine-readable list for UI forms. Syntax and range errors raise `OrderSyntaxError` with a clear message. |
| `results.py` | `TurnResults`, holding one `EmpireReport` per empire: per-order `OrderResult`s (ok, error, info lines), typed `Event`s with kind, text, section, system and data, combat ids, the maintenance ledger, the economy summary, scans (foreign ships, fleets and systems at short or long range), stats/ranks/VP, and received messages. Also `CombatLog`s (participants, relations, initial ships and troops, phase-tagged lines, status and owner before/after). Everything is JSON serialisable. |
| `mapgen.py` | `new_game(name, seed, humans, size=16)`. Size 4 (2x2 bins, 50x50, 44 systems, W-26), sizes 8/9 (3x3 bins, 75x75, 99 systems; 8 has the centre bin empty) and 12/16 (4x4 bins, 100x100, 176 systems; 12 has the four centre bins empty), DECISIONS W-13. Human homes are spread out and NPRs fill the remaining seats. Every gcugen bug is fixed. |
| `npr.py` | The NPR interface: `npr_orders(state, empire_id) -> list[Order]`. It is a stub that returns []. The contract is in the docstring. |

### Turn engine (`mhgc/engine/`), in rules order

| Module | Contents |
|---|---|
| `turn.py` | `run_turn(state, orders)`. It runs the phases below, then cleans up, scans and computes stats. `check_orders(state, empire, orders)` is a dry run on a copy, for the UI's "Check orders". |
| `orders_exec.py` | One handler per order code. Each validates against the state and raises `OrderError` before any change. |
| `economy.py` | Production, DCT trade, feeding, happiness, rebellion, uprisings, emperor day, growth, and the NPR majority-tech grant. |
| `maintenance.py` | Trade income, SISD, artifacts, ships (2/2, 5/5, 10/5), AUTOSISD, CTs, spies, the militia cap and the entrenchment countdown. |
| `movement.py` | Fleets (slowest ship or FS), ships, intercept (sweeps), guard, AFXY, drop pods, leader and spy transit. |
| `combat.py` | Flagging, relations table, role shifting, MFB, system weapons, initiative and simultaneous fire, bombardment, raids, ground combat, capture, rebel-join, status (one step a turn), admiral deaths, status decay. |
| `spies.py` | All spy missions, with the rules' odds and counter-intelligence. |
| `events.py` | Plague, IU gain, AU/IU loss, IF loss or population boom, and the CD-ROM reveal. |
| `leaders.py` | Ageing, drift (clamped), death, ice, new leaders and comments. |
| `scans.py` | Ship and system scans, the NPR +3 scan range, contact, `seen_systems` memory, and extinction. |
| `stats.py` | GNP..CTS, ranks among humans, VP and the victory check with the NNP tie-break. |

## What the stage 1 tests cover (184 tests; stage 2 adds `test_view.py` and `test_api.py`)

| File | What it covers |
|---|---|
| `test_data.py` | The tables match the rules' generated table (F-01, F-02). |
| `test_orders_parse.py` | Every "WRONG" example in the rules, comments, ranges, negatives, MESSAGE, round trips, removed and ignored codes. |
| `test_model_mapgen.py` | Geometry, RNG, mapgen invariants and determinism, JSON round trip mid-game. |
| `test_economy.py` | The rules' worked production example (10/5/5), the starport +10% example (22 units), IF doubling, MR and artifacts, UA/INT, leader neutrality at 50, the happiness formula, rebellion, the NPR no-rebel rule, uprising and emperor-day odds, growth and the pop cap, DCT 25%/50%/deny/split, the NPR tech grant. |
| `test_orders_exec.py` | PT/CRP/FT/NPR price, GT, TTNPR, CSP/CAP/CAPN (CGR removed, G-09), BS/BCU starport capacity (militia included), UA doubling, the militia limit, BI/DI, BT/EESS, spies, DT, BSP/DSP, SISD, CI, load/unload capacity, colonisation and its morale bonus, held systems, immigration, SL, LOCT/LACT (allied and hostile), SS 75% and SCT 50%, CTT, relative coordinates, MS needs a scan, fleets (CF/AF/CFP AN/CFCR OF and RO/FS/LF/MFS ownership/FL exact), the full DA/DW/EWA table, GE timing, DD/SD, CRN, MESSAGE, leader and spy orders, check_orders. |
| `test_maintenance_movement.py` | Ship maintenance by distance, demobilisation, AUTOSISD shortfall, NPR discount, CT and spy upkeep, independents, artifact loss, SISD and trade credit, the militia cap, entrenching; movement with wrap, fleet speed and stragglers, intercept chains and circles, guard, AFXY, drop pods (30% +15%), leader 2-turn travel, eviction. |
| `test_combat.py` | The posture table, war and alliance overrides, the MFB example (18), the rules' role-shift example, MR at half on the ground, initiative, simultaneous fire, target order, partial shots, system weapons, the bombardment example (10%), PD halving, the raid example (4%/4%), capture effects, entrenched and defend postures, the tech-capture gate, the 3:1 threshold, one step a turn, neutral ships, ground interdiction, rebel-join, decay, the full COMBAT EXAMPLE scenario. |
| `test_spies_events_stats.py` | Spy odds and CI, home safety, SAL, SSB, SET, SOS, SUP timing; plague (empty systems, ADM, the 3-pop cap), CD-ROM, event start turn; leader death, ice, new leader distribution, the stat clamp; scans (short/long, ESS, NPR bonus), extinction; VP and the victory tie-break. |
| `test_c_behaviour.py` | 14 tests of C behaviour where the rules are silent, each citing its C file:line. |
| `test_turn_integration.py` | 40-turn fuzz games on three seeds, checking invariants every turn; determinism; a full invasion through `run_turn` (combat, one-step status, capture). |

## Stage 2: web backend (done)

### Files

| File | Contents |
|---|---|
| `mhgc/view.py` | `view(state, results, empire)`: the fog-of-war read model. It is the only game-world data that reaches a browser. |
| `mhgc/engine/turn.py` | New: `initial_results(state)`, the "turn 0" scans, stats and map memory for a new game. |
| `app/main.py` | The FastAPI app (`create_app(save_dir)`; module-level `app` for uvicorn). It covers games, seats, orders, turns, history, polling and chat, plus the static UI. |
| `app/catalogue.py` | The order catalogue for UI forms (fields, kinds, choices with labels, help) and the reference tables (techs, ships, troops, artifacts). |
| `app/ui/index.html` | A placeholder page that lists games and points to `/docs`. |
| `render.yaml`, `DEPLOY.md`, `README.md`, `.gitignore` | Render deployment (Starter plan plus a 1 GB disk at `/var/data`, `SAVE_DIR=/var/data/saves`, health check `/api/health`), adapted from Sidion. |
| `tests/test_view.py` (7 tests) | View-model correctness and non-leakage. |
| `tests/test_api.py` (12 tests) | The API through TestClient. |
| `docs/DECISIONS.md` W-03, W-07..W-11 | The web decisions made in this stage: chat rules, open seats, the seat lifecycle, drafts, and lobby information. |

### Run locally

```
~/mhgc/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8790     # SAVE_DIR defaults to ./saves
```

The interactive API reference (OpenAPI) is at `/docs`. The smoke test was run on port 8790 with curl:

- create, join, put orders, check, and submit, after which the turn auto-ran;
- chat, force, and history;
- 401 without a token, and `/docs`;
- a restart, after which the game reloaded at the same turn and version.

The server was then stopped by PID.

### The view model (`mhgc/view.py`)

The view is built from whitelisted fields, never from `model.to_dict`, so new state fields stay private unless they are added on purpose.

- **Own objects, in full:**
  - systems, with this turn's production;
  - ships, with cargo and the troops aboard;
  - fleets, with members and admiral;
  - troops, leaders and spies;
  - EU, the IU depot, techs, preferences, stats, ranks and VP.
- **Foreign objects:** only this turn's scans (`results.reports[e].scans`, which engine/scans.py builds at short or long range), the map memory (`seen_systems`: name and owner when last seen, plus the fixed position), and foreign troops standing on the empire's own systems.
- **Other empires:** listed only once contacted, with id, name, kind (`player`, `npr`, `independent` or `extinct`) and **our** stance. Never their stance towards us (rules:735-737).
- **Results:** this empire's report only, covering orders, events, MESSAGE orders addressed to it, maintenance, economy, stats, and the combat logs of battles it took part in or that hit its systems.
- **Coordinates:** every coordinate is relative (home = the board centre, 50,50 or 37,37). Absolute coordinates, including the empire's own home position, are never sent.

Non-leakage evidence:

| Test file | Evidence |
|---|---|
| `tests/test_view.py` | **Marker test:** B's ships, fleets, leader, ECHO text, MESSAGE to a third race, EU, IU depot and stockpiles are set to distinctive values. None of them appears in A's view JSON, for any turn's results. Nor do B's system ids or B's home position in A's coordinates. |
| `tests/test_view.py` | **Differential test:** everything about B that A hasn't scanned is scrambled (B's stance towards A, money, techs, systems, ships, leaders, spies, map memory, and B's whole report). A's view stays byte-identical. |
| `tests/test_view.py` | **Positive tests:** a B ship in long-scan range appears without posture or cargo, the same square gives a short scan, and scanning makes contact. Combat logs go to participants only and use relative coordinates. MESSAGE orders reach only their recipients. |
| `tests/test_api.py` | The same checks over HTTP: seat 1's `/view` contains none of seat 2's ids, names, fleet, ECHO text or system ids. |

### API reference (all JSON; the seat token goes in the `X-Seat-Token` header)

| Method and path | Token | Purpose |
|---|---|---|
| `GET /api/health` | no | `{ok, games}` (the Render health check) |
| `GET /api/orders/catalogue?board=` | no | `board` 100 (default), 75 or 50 sets the coordinate fields' `hi`. `{board, orders: [{code, category, category_label, help, usage, args: [{name, kind, optional, choices, labels, lo, hi, help}]}], kinds, categories, notes}` |
| `GET /api/reference` | no | `techs`, `ships`, `troops`, `artifacts` tables, plus `status_names`, `hab_names`, `stat_names`, `victory_points`, `board`, `home` |
| `GET /api/games` | no | Lobby: a list of game summaries, most recently updated first |
| `POST /api/games` | no | `{name?, size?: 4 / 8 (default) / 9 / 12 / 16, humans: 1..size, computers?: must equal size-humans (without `size`, humans+computers is the size), player, race?, seed?, chatter?: normal (default) / quiet / off, password, host_password (required, Dave 2026-11-15; may equal password), host_only?}` returns `{id, seat: 1, token, game}`. The creator is the host. 400 without a host password. |
| `POST /api/games/{gid}/settings` | host | `{chatter: off/quiet/normal}`: how much the computer empires boast in chat, from the next turn (W-14). Returns the summary. |
| `GET /api/games/{gid}` | optional | The summary, plus `you` (your seat or null) |
| `POST /api/games/{gid}/join` | no | `{seat, player, race?, password}` returns `{id, seat, token, game}`. 409 if the seat is taken or is a computer empire. The race name can be chosen only at turn 0. |
| `POST /api/games/{gid}/login` | no | `{seat, password}` returns `{token, seat, race, player, must_set_password, game}`; 403 wrong password (no limit on tries), 409 no password yet (W-21). |
| `POST /api/games/{gid}/password` | session | `{new, current?}`: change (or, when required, set) the race password; logs out the race's other browsers. |
| `POST /api/games/{gid}/logout` | session | `{everywhere?}`: end this browser's session (or all of the race's). |
| `POST /api/games/{gid}/seats/{n}/reset-password` | host | `{password}`: a temporary password; the race must set a new one at its next login (W-21). |
| `POST /api/games/{gid}/seats/{n}/computer` | host | Hand a human race to the computer (W-22). |
| `POST /api/games/{gid}/seats/{n}/human` | host | Open a computer empire as a human seat (W-22). |
| `POST /api/games/{gid}/host/login`, `/host/logout`, `/host/password`; `GET /host/races` | host password / host | The host login (W-23). |
| `GET /api/games/{gid}/as/{race}/view` (`orders`, `stats`, `turns`, `chat`; `POST production/preview`) | host login | View as, read-only and audited (W-23); writes under `/as/` are 403. |
| `POST /api/games/{gid}/leave` | yes | Frees your seat and clears its password. The host role passes on if the host leaves (unless a host password exists, W-23). |
| `DELETE /api/games/{gid}` | yes* | Drops the game. *Any seated player, or anyone if no seat is taken. |
| `GET /api/games/{gid}/version` | no | Cheap poll: `{version, turn, submitted, waiting_for, chat_last, finished}` |
| `GET /api/games/{gid}/turns` | yes | `{current, turns: [0..current]}` |
| `GET /api/games/{gid}/view?turn=n` | yes | The view JSON (below) for the current turn, or for any earlier turn (history) |
| `GET /api/games/{gid}/orders` | yes | The draft: `{turn, orders: [{code, ...args, text}], submitted}` |
| `PUT /api/games/{gid}/orders` | yes | `{orders: [order dicts]}` or `{text: "classic orders"}`. It replaces the draft and withdraws a submission. 422 `{detail: {errors: [{line or index, text, error}], warnings}}` if any order is bad. |
| `DELETE /api/games/{gid}/orders` | yes | Clears the draft and withdraws a submission |
| `POST /api/games/{gid}/orders/check` | yes | Runs `check_orders` on the draft (or on the body, if given). Returns `{results: [OrderResult], errors, warnings, ok}`. |
| `POST /api/games/{gid}/production/preview` | yes | The Production tab's own-economy estimate: `{overrides: {system id: {au, iu, eu}}}` returns per-system production, stockpiles, happiness, flags, totals and the projected maintenance listing. Stores nothing (DECISIONS W-12, STATUS-ui.md). |
| `POST /api/games/{gid}/submit` | yes | Optional body as for PUT. Returns `{submitted, turn_ran, turn, waiting_for}`. The turn runs when every human seat is taken and in. |
| `DELETE /api/games/{gid}/submit` | yes | Withdraws the submission |
| `POST /api/games/{gid}/aomt` | session | `{on}`: the race's AOMT setting, at once (W-29). Returns `{aomt, turn}`. |
| `POST /api/games/{gid}/force` | host | `{turns?}` Runs the turn now. Returns `{turn_ran, turn, turns_run, finished}`. Non-submitters give no orders; with AOMT on (the default) their unsubmitted draft runs, or with an empty draft the bot writes theirs (W-29, W-30). `turns` (1..20) only in a game no human gives orders in (W-24). |
| `GET /api/games/{gid}/chat?since=id&limit=` | optional | `{messages, last, recipients}`. Messages are the game-wide ones plus private ones to or from you. `recipients` lists the empires you may message privately. |
| `POST /api/games/{gid}/chat` | yes | `{text, to?: empire id}`. Private messages need contact (403 otherwise). 400 if the recipient is a computer empire or yourself. |
| `GET /`, `/static/*` | no | The UI in `app/ui/` |

Response shapes:

- **Game summary:** `{id, name, turn, created, updated, humans, computers, size, board, bins, empty_bins, chatter, host_seat, host_handicap (W-28), seats: [{seat, race, player, open, host, submitted, needs_orders}], open_seats, waiting_for, finished, winner, version}`.
- **Chat message:** `{id, turn, time, from, from_name, player, to, to_name, text, system, bot?, kind?}`. `system: true` marks server notices: joins, leaves, "Turn n has run", and the winner. `bot: true` marks a computer empire's boast (`from` is its empire id, `kind` the boast type; W-14).

Errors use FastAPI's `{detail: ...}`:

| Code | Meaning |
|---|---|
| 401 | No seat in this game |
| 403 | Not the host, or no contact |
| 404 | No such game or turn |
| 409 | Seat taken, game over, or your empire is out |
| 422 | Bad input |

### The view JSON (`GET /view`)

```
view_version: 1
game:    {name, turn, winner, winner_name, vp_to_win, board: 100|75|50, size: 4|8|9|12|16, bins: 2|3|4,
          empty_bins: [[bx, by]]}
current_turn                      # the game's latest turn (differs when browsing history)
seat:    {seat, player, host, submitted, needs_orders}
empire:  {id, name, kind, home: {x: 50, y: 50} (the board centre: 37,37 on 75x75, 25,25 on 50x50), eu, iu_depot, techs: [ids], future_tech, renamed,
          autosisd, aomt (W-29), unranked (W-28), stats: {GNP..CTS}, ranks, vp}
races:   [{id, name, kind: player|npr|independent|extinct, our_stance: N|A|W|E,
          deny_trade, split_trade}]                      # contacted empires only
systems: [{id, name, x, y, pop, happy, happy_band, trend, hab, hab_value, mr, ar, infra,
           status, starport, au, iu, profile: {au, iu, eu}, au_release: {mode, value},
           growth, artifacts, trade_routes: [{race, name}], governor, scan_range,
           troops: [{number, owner, owner_name, type, posture, posture_name}],
           production: {au, iu, eu, eaten}}]             # own systems
ships:   [{number, type, class, x, y, from: {x, y}, dest: {x, y}, order, target, dest_system,
           posture, role, fleet (name), home_system, built_turn, scan, move, cargo_capacity,
           cargo?: {AU, IU, POP, CT: [troop numbers]}, cargo_used?}]
fleets:  [{number, name, x, y, from, dest, order, target, dest_system, posture, role, ro,
           speed, admiral, ships: [numbers]}]
troops:  [{number, type, system, ship, posture, posture_name, built_turn}]
leaders: [{id, name, mgmt, eng, combat, intel, social, age, renamed, status, system,
           fleet (name), transit, description}]
spies:   [{number, system, transit, mission, mission_arg}]
known_systems: [{id, x, y, name, owner, owner_name, owner_kind (unowned|rebels|null), last_seen, via: scan|cdrom, mine,
                 hab?, hab_value?, mr?, ar?, details_turn?}]   # ? = from a short scan, as of details_turn (G-08)
scan_history: {encoding, data}   # base64 board x board bitmask, bit y*board+x LSB first, relative coords (G-07)
scans:   {ships:   [{number, owner, owner_name, type, x, y, ox, oy, level: short|long, moved,
                     fleet?, posture?, role?, cargo?}],          # posture/role/cargo: short only
          fleets:  [{name, owner, owner_name, x, y, ships: [numbers]}],
          systems: [{id, name, x, y, level, owner, owner_name, owner_kind?, pop?, happy?, trend?, starport?,
                     status?, infra?, hab?, mr?, ar?, au?, iu?, growth?, artifacts?,
                     trade_routes?, leader?, troops?, hab_value?, details_turn?}]}
                     # ? = short scan only; a long scan carries hab/hab_value/mr/ar/details_turn
                     # from map memory when an earlier short scan saw them (G-08)
results: {turn, orders: [{index, text, code, ok, messages, error}],
          events: [{kind, text, section, system, data}], messages: [{from, from_name, text,
          broadcast}], maintenance: [ledger lines], economy: {eu, iu_depot, production,
          trade_eu, purchases_eu}, stats: {values, ranks, vp, vp_needed},
          combats: [CombatLog with x, y relative, participant_names]}
```

The event `kind`s are in `mhgc/results.py` EVENT_KINDS, and the report sections in `SECTIONS`.

### Persistence

The files under `SAVE_DIR/games/<gid>/` are:

- `meta.json`: seats with token **hashes**, submissions, version, host and turn. Rewriting it is the commit point of a turn.
- `chat.json`;
- `turns/<n>/state.json` and `results.json`, for every turn from 0;
- `orders/<n>/<seat>.json`: the drafts for turn n.

Other properties:

- Every write is atomic (a temp file, fsync, then rename).
- A turn runs on a copy of the state under the game's lock, so a crash or an engine exception leaves the previous turn current.
- Unreadable games are skipped at start-up.
- Games are not pruned (no deadlines; PBEM games are slow).
- A turn costs about 100 KB on disk.

## Four-empire game (2026-11-16)

Dave: "add a four player game (four quadrants). Resize the map as needed." DECISIONS W-26 (extends W-13); RULEBOOK "THE GAMEBOARD".

- **Size 4** = 2x2 bins on a 50x50 torus, no empty bins, 44 systems, home at 25,25 relative. `constants.GAME_SIZES[4]`; nothing else in the board parameterisation needed changing (checked: geometry/wrap, scans, scan mask (420 base64 chars), view, catalogue `?board=50` -> 0-49, map grid/coverage/minimap/torus copies, the bot's 5x5 scout grid and distances).
- **Home spacing:** homes are within 5 of their bin centre, so always >= 15 apart (200 seeds: 15..25; the torus maximum is 25). Starting scans are 4 (home) and 3 (scout), so nobody starts in another's scans. `mapgen.MIN_HOME_DISTANCE` (9) states it; it never rejects a draw, so the other sizes generate identically (120 seeded maps hashed before/after).
- **Victory** stayed 100 VP here (now 90 since 2026-11-19, DECISIONS G-26): 11 systems an empire as at 9 and 16; bots-only games were won on turns 83-86 at size 4 (72-84 at 16, 63-82 at 8). Stat-bonus VP weigh a little more with 3 rivals (11-14 for the winner vs 4-6 at 16); the smaller map offsets it.
- **Lobby:** a "4" card (2x2 diagram) first in the picker; 8 is still the default; seats capped at 4.
- **Tests:** `tests/test_sizes.py` now 41 (size 4 in every parametrised test, plus 12 seeds of board/bins/44 systems/home spacing/no foreign object in starting scans, geometry/scan mask/view/orders/catalogue at 50, the bot's scout grid at 50, a 60-turn bots-only game; API: size 4, 5 humans refused, 4+1 refused, catalogue 50 ok and 60 refused). Browser: `flow.py` at `MHGC_SIZE=4` 49/49 (`~/mhgc/work/shots/flow4-*.png`), and still 49/49 at 16 and 8.

## Game sizes and computer chatter (2026-11-13)

Dave: "make the default game eight players with one 'square' empty, nine players (nine squares), twelve players with four center squares empty, or sixteen players with appropriately sized maps", and "Have the bots name systems and generate chat messages for accomplishments", plus boasts about big turn-on-turn gains. DECISIONS W-13 and W-14; RULEBOOK "THE GAMEBOARD" and "NPRs".

| Size | Bins | Board | Empty bins | Systems | Home (relative) |
|---|---|---|---|---|---|
| 4 (2026-11-16, W-26) | 2x2 | 50x50 | none (four quadrants) | 44 | 25,25 |
| **8 (default)** | 3x3 | 75x75 | the centre bin | 99 | 37,37 |
| 9 | 3x3 | 75x75 | none | 99 | 37,37 |
| 12 | 4x4 | 100x100 | the 4 centre bins | 176 | 50,50 |
| 16 | 4x4 | 100x100 | none (classic) | 176 | 50,50 |

- **Variable board:** `GameState.board/bins/empty_bins` (old saves load as 100/4/none). Geometry, scans, movement, intercepts, guard, maintenance, spy travel, `scanmask` (board x board), the view (`game.board/size/bins/empty_bins`, home at the centre), the bot (`npr/world.py` reads the board from its view into a context variable; scout cells about 10 squares), the catalogue (`?board=75`: coordinates 0-74) and the map UI all take it. Coordinates of 75+ on a 75 board are refused at check/run with a clear message. The 16-empire game was fingerprinted over 75 seeded bot turns before and after the change: identical.
- **Bots name systems:** `npr/naming.py` + `data/system_names.py` (416 themed names), one or two NSY a turn, last in the orders; homes with proper names kept. Engine: `_known_system` also accepts the name in the orderer's own map memory, so stale names keep working.
- **Bots boast:** `npr/chatter.py`, run from `npr.observe_turn` at the end of the turn, into `TurnResults.chat`; `Game.run` posts them as race messages (`bot: true`). Per-game `chatter` (off/quiet/normal) in `meta.json`, chosen in New game, changed by the host in the Chat tab or `POST /settings`.
- **Tests:** `tests/test_sizes.py` (22: generation at every size and 3 seeds, geometry/scan mask/view/orders at 75, 40-turn bot games at every size, API sizes, old games), `tests/test_npr_chatter.py` (20: names, renames, stale names, every boast kind's rules, limits and levels, determinism and save/load, the no-leak scramble, no coordinates or foreign numbers, the API). `npr.sim` takes a size (`python -m mhgc.npr.sim npr SEED HUMANS TURNS MODE SIZE`).

Bot games, 40 turns (the `test_sizes.py` games; parallel runs, so times are a little pessimistic):

| Size | Seed, humans | NPR orders | Rejected | NSY renames | s/turn mean (max) |
|---|---|---|---|---|---|
| 4 | 10, 1 random | 1,651 | 0 (0.00%) | 38 | 0.009 (0.016) |
| 4, 60 turns | 31, none (bots only) | 2,823 | 0 (0.00%) | 43 | 0.015 (0.024) |
| 8 | 11, 1 random | 3,546 | 0 (0.00%) | 90 | 0.026 (0.050) |
| 9 | 12, none | 4,858 | 6 (0.12%) | 98 | 0.041 (0.075) |
| 12 | 13, 2 random | 5,596 | 5 (0.09%) | 133 | 0.065 (0.199) |
| 16 | 14, 1 random | 7,700 | 6 (0.08%) | 161 | 0.093 (0.195) |

Every rejection is one of the known unforeseeable kinds (another race settled the world first, or declared war first); no NSY was ever refused. The chatter adds 2-6 ms a turn.

## What stage 3 (the UI) needs to know

- **Seats.**
  - Keep `{gid: {seat, token}}` in localStorage, as Sidion does, and send `X-Seat-Token` on every call.
  - Lobby: `GET /api/games`; join open seats with `POST /join`. A browser with no token for a game is a spectator: it gets the lobby summary and the game-wide chat only.
- **Polling.** Poll `GET /version` every few seconds.
  - When `turn` changes, refetch `/view`, `/orders` and `/turns`.
  - When `chat_last` changes, fetch `/chat?since=<last seen id>`.
  - Any other `version` change (submissions, joins) needs only the summary.
- **Map.**
  - Draw the torus from `systems` (own), `known_systems` (memory, with `last_seen`) and `scans` (this turn).
  - All coordinates are relative and wrap at the board side (`game.board`: 100, 75 or 50).
  - Ships stack per square. Foreign fleets come as name plus member numbers.
- **Orders UI.**
  - Build forms from `/api/orders/catalogue`: `kind`, `choices`/`labels`, `lo`/`hi`, `optional`, and per-field `help`.
  - Pickers can be filled from the view: own ship numbers, fleet names, system names, leader names, spy numbers, contacted race names, and techs from `/api/reference`.
  - Send `PUT /orders {orders: [...]}`. The classic text box is `{text}`.
  - Show `/orders/check` results inline per order. A check is a dry run against the current state, not a preview.
  - Changing the draft withdraws the submission, so show "submitted" from the response.
- **Turn results screen.**
  - It is built from `view.results`: orders, then events grouped by `section` in `SECTIONS` order (messages, rebellion, maintenance ledger, drops, combat, spies, random, leaders, scans, general).
  - Combat logs carry `lines[]` with a `phase`.
- **History.** `/turns`, then `/view?turn=n`. The view of turn n is rebuilt from the stored state and results of turn n.
- **Chat.**
  - A game-wide channel, plus private threads with each entry in `recipients` (contacted human empires).
  - Show `system` notices differently.
- **Host.** Show a **Force turn** button when `seat.host` is true. Show `waiting_for` (seat numbers; names come from the summary).
- **Game over.** When `game.winner` is set, order endpoints return 409.
- **Leaving.** `POST /leave`, and drop with `DELETE /api/games/{gid}`.

## Next, in order

### 1. Stage 3: UI

- The map: a torus canvas built from `systems`, `known_systems` and `scans`.
- An order queue built from the catalogue, with check results inline.
- A turn-results screen built from `results`.
- Chat, history browsing, and the lobby (new game, join, leave, drop).
- PORT_PLAN.md §6 is still a good UI concept.
- Update DEPLOY.md's "Play with friends" section to match the real buttons.

### 2. Stage 4: NPR AI

Port `gcnpr.c` / `gcnprutils.c` (ENGINE_MAP section 50) behind `npr.npr_orders`.

- It emits ordinary `Order` objects.
- Don't port the cheat orders. The engine already applies the NPR income bonus, the scan bonus and the leaderless production bonus.
- Use `Rng(state.seed, state.turn, f"npr{eid}")`.
- Until it exists, NPRs give no orders. They still produce, grow, defend with what they have and receive majority techs, but they never expand.

### 3. Later

The majority vote to end the game early (rules:206-209; DECISIONS W-06).

## Known gaps after stage 2

- **Engine error messages are an oracle.** `/orders/check` and turn results return the engine's validation errors. A few of them can confirm facts the player hasn't scanned. For example, a MESSAGE to an unknown race name warns "unknown race", while a real but uncontacted race doesn't. Orders naming a system the player hasn't seen get an error that may differ by owner. The PBEM game behaved the same way. A full audit of `orders_exec.py` messages against fog of war was not done.
- **The lobby shows human race names and seat status** to everyone (W-11). Seat numbers equal empire ids, and seats are 1..humans, so an id tells you an empire is human. This only matters after contact, and by then the view shows `kind` anyway.
- **Renaming at join.** A race renamed at join (turn 0) keeps its old placeholder name ("Open_2") inside turn 0's stored results text.
- **Stale names.** `known_systems.owner_name` uses the owner's *current* race name, not the name when last seen.
- **Results for players who join late.** A player who takes over an open seat after turn 1 gets that empire's existing view and history, including turns played before they joined. Nothing is reset.
- **Combat logs** list the internal fleet numbers of participants' ships (harmless random numbers, but not the fleet names).
- **No rate limiting or size caps** beyond the request models: chat is 2000 characters a message with 20,000 kept per game, and orders are 2000 a turn with 200 KB of text.
- **Stage-1 lint.** pyflakes still reports unused names in stage 1's tests. These are not touched.
- TestClient emits a `StarletteDeprecationWarning` about httpx. It is harmless.

## Known gaps and design notes from stage 1

- **c-ref was not exercised in stage 1.** Formulas come from ENGINE_MAP and the C source. A sanity run against `~/mhgc/work/c-ref/run_turn.sh` for happiness and growth trajectories would be cheap reassurance, but it is not required (no bit-exactness).
- **Coordinates.** The state holds absolute coordinates. Orders (MO, MF, CF, CFXY, AFXY, SMO) take relative ones and convert them with `ctx.abs_xy`. Reports convert back. The UI must always use relative coordinates.
- **Order execution.**
  - Empires go in a random order each turn (`ctx.empire_order`), and each empire's orders run in its own sequence.
  - A failed order changes nothing.
  - `OrderResult.messages` carries acknowledgements and warnings.
- **Entity lifetime.** Destroyed units are flagged `alive=False` during the turn and removed in `turn.cleanup`. Fleets are referenced by number; leaders by id internally and by name in orders.
- **Independents.** Empire 0 is the independents ("Rebels"). It never gives orders, pays no maintenance and is never ranked. Rebel militia belong to it.
- **What `check_orders` does.** It runs only the order phase on a deep copy and never rolls TTNPR or SUP. It is not a turn preview (Dave: no preview).
- **Combat simplifications.**
  - Allies don't pool their attacks.
  - Space fire is split over all targetable enemies sorted by role, then at random (C style).
  - The status attack total is the leader-multiplied raw attack of surviving hostile ships (no MFB, no shift halving).
- **Map memory.** It is only `Empire.seen_systems` (id to last-seen name and owner, or "cdrom"). No scanned-square history is stored (the TRACKSCAN option was dropped, DECISIONS G-01).
- **Delivery.** MESSAGE orders are delivered in the same turn's results (`EmpireReport.messages`). The rules' "no names = broadcast" means every other human and NPR.
- **Not implemented (deliberately):** legacy `.dat` import/export of the old game directories (demo, iraq2). PORT_PLAN's legacy_io was for bit-exact diffing, which Dave rejected. Add it only if Dave wants to resume an old game.
- **Performance.** A 16-empire turn takes a few milliseconds early in the game. A 40-turn fuzz game takes about 0.3 s.
- **RULEBOOK caveats raised by its author.**
  - It says in-game chat is available. That is true since stage 2.
  - It keeps the majority-vote early end (W-06).
  - It states that a forced turn gives non-submitters no orders but they still produce and pay upkeep. That is the engine's behaviour: missing orders are an empty list.

## Not touched

`~/mhgc/c`, `~/mhgc/java` and `~/mhgc/mhgc_rules.txt` were not touched in stage 1 or stage 2. No git commits were made.
