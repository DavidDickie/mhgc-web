# MHGC web: analysis features (2026-11-14)

Dave asked for four things so he can play a game and compare his play with the bots':

- a bot decision log;
- an all-race standings log;
- an end-of-game chart;
- an export with an offline summariser.

A Rules tab (W-18) and combined transport Load and Unload dialogs (W-19, W-20) were added the same day. The decisions are DECISIONS A-05 and W-15 to W-20.

## Files

| File | Contents |
|---|---|
| `mhgc/npr/trace.py` | The decision log. It has the reason-code table `REASONS`, `note()` (a context-variable sink, a no-op when not recording), the `saw`/`strategy`/`record` summaries, and `Tracer`, the `npr_fn` for `run_turn` (whose `finish()` joins in the engine's ok/error). |
| `mhgc/npr/plan.py` | `Plan.area`, plus `Plan.reasons` running parallel to `Plan.orders`. `add(..., rc=None)` records the area, the reason code and the note. |
| `mhgc/npr/brain.py` | `decide(view, mem, rng, record=False)`. It sets `plan.area` before each step. With `record` it builds `plan.record`. |
| `mhgc/npr/memory.py`, `diplo.py`, `war.py`, `econ.py` | `log()` also feeds the trace. Notes are added for war, peace, alliance, warning, mission and research decisions with their reasons. |
| `mhgc/npr/__init__.py` | `npr_orders_traced`. |
| `mhgc/analysis.py` | `standings()` (one `standings.jsonl` line), `spending()` (EU/IU per category from the successful orders) and `personas()`. |
| `app/analysis_api.py` | Writes the logs (`analysis_records`, `write_analysis_logs`, `start_logs`). Reads them back, keeping the last line per key, and rebuilds missing standings from stored states. Also holds the permissions, `/final`, `/export` and the zip builder. |
| `app/main.py` | `Game.run` runs the turn with a `Tracer`. It writes `turns/<n>/orders.json` before the commit and appends the logs after it. `create` writes the turn-0 standings. `register_analysis` adds the two endpoints. |
| `app/ui/final.js`, `app/ui/final.css` | The Final standings dialog and the export download. `final.css` also styles the Rules tab. |
| `app/ui/app.js`, `lobby.js`, `index.html` | Small hooks. `app.js`: the top-bar buttons, opening Final standings automatically once per browser, and the Rules tab. `lobby.js`: the buttons for finished games. `index.html`: the stylesheet link. |
| `app/ui/help.js` | `renderInto` and `wireSearch` are shared by the Help dialog and `renderRules` (the Rules tab). |
| `app/ui/loaddlg.js` | The combined Load dialog (L + LOCT, FL + FLOCT) and Unload dialog (U/UG + LACT, FU/FUG + FLACT, population first at an unowned system), opened from the inspector's Load and Unload buttons. |
| `tools/analyze_game.py` | The offline summary. It uses only the standard library. |
| `tools/sample_game.py` | Plays a game through the API, with the baseline bot in seat 1, and exports it (`--turns`, `--size`, `--seed`, `--vp`). |
| `tests/test_analysis.py` | 8 tests (see below). |
| `~/mhgc/work/uitest/final.py` | Playwright, 25 checks. It runs on `serve_fixture.py`: 15 VP to win, counted from turn 6. |
| `~/mhgc/work/uitest/final_long.py` | Screenshots of a 28-turn game played by the baseline bot against the computer empires. |
| `~/mhgc/work/uitest/rules.py` | Playwright, 12 checks for the Rules tab. |
| `~/mhgc/work/uitest/load.py` | Playwright, 20 checks for the combined Load dialog. |
| `~/mhgc/work/uitest/unload.py` | Playwright, 21 checks for the combined Unload dialog. It restarts its server once, after a fixture edits the save to place ships at unowned and foreign systems. |

## Formats

### `botlog.jsonl`

There is one line per computer empire per turn, with sorted keys:

```
{turn, empire, race, persona,
 saw: {systems, populated, pop, eu, iu_depot, vp, techs, ships, warships, attack, fleets, troops,
       spies, under_attack, known_systems, known_by_owner{race: n},
       contacts{race: {ships, warships, attack, near}}, threatened{system: {attack, carriers}},
       enemy_seen{race: {att, def, t}},
       races{race: {name, stance (before this turn's diplomacy), kind, griev, good, weight}},
       failed_last_turn},
 strategy: {mode, persona, params, budget{eu_start, eu_left, spent{purpose: eu}}, at_war, allied,
            missions[{id, target, race, why, stage, state, start, fleet, est, troops, ships}],
            claims, threatened, vp_push, want_eu, income, upkeep_eu, reserve, leader_race},
 orders: [{i, code, text, area, rc, note, ok, error?}],
 decisions: [{ev, ...}], plan_errors, rejected, after{vp, systems, eu, kind}}
```

The `decisions` entries have these `ev` values:

- `war_reasons`, then `war`;
- `peace_reasons`, then `peace_offer`;
- `alliance` and `alliance_reasons`;
- `alliance_ended`, `warning` and `grievance`;
- `mission_choice` (value, stage, distance, pool, est_capture, need, state) and `mission`;
- `mission_*` and `fleet_launched`;
- `research_choice` (tech, cost, value);
- `colony`, `system_lost`, `war_on_us` and `peace`.

### `standings.jsonl`

There is one line per turn: `{v, turn, winner, empires: [...]}`. Each empire entry has:

- `id`, `name`, `kind`, `human`, `persona`;
- `stats` (the 13 engine stats), `ranks`, `vp`;
- `eu`, `iu_depot`, `systems`, `pop`, `infra`, `techs`, `future_tech`;
- `ships`, `warships`, `attack`, `troops`, `spies`;
- `happiness`, `nnp`, `contacts`, `at_war`, `allied`;
- `spend{category: {eu, iu}}`.

### `turns/<n>/orders.json`

This maps each empire to `[{i, code, ...fields, text, by: human|computer, ok, error}]`.

### Export zip

The zip holds:

- `manifest.json`;
- `standings.jsonl` and `botlog.jsonl`;
- `turns/NNNN/{orders,results}.json`;
- `final_state.json`;
- `README.txt`.

## Permissions

| What | While the game runs | Once it is over |
|---|---|---|
| Own stats and view | Unchanged | Unchanged |
| `/final` | 409 for everyone | Anyone, with or without a seat |
| `/export` | The host, any game (Dave 2026-11-15; else 403; 401 without a login) | Any seated player or the host (401 without a login) |

## Cost

Measured with `/tmp/bench_log.py`, 70 turns, on the same game with and without the log. The orders and memory were identical.

| Game | Time added per turn | Share of the turn | Written per turn |
|---|---|---|---|
| 8 empires | 2.0 ms | 4.4% of 46 ms | about 41 KB |
| 16 empires | 6.6 ms | 3.7% of 181 ms | about 83 KB |

The figures cover the trace, the standings, the spending estimate and the JSON. The written size covers the bot log, standings and orders.

A 70-turn export for 8 empires is 1.5 MB zipped (11.9 MB unzipped, mostly the results).

## Tests

| Where | What it covers |
|---|---|
| `tests/test_analysis.py` | Tracing changes nothing and is deterministic (three copies of a game: with no log, logged and logged again). The record contents. Every order has a reason code, and every note maps to a code. The logged orders are the orders that ran. A rejected order is logged with the engine's error. Standings match the engine stats, the state and the VP every turn. Human orders and spending go into `orders.json`. Nothing leaks while the game runs: both logs are scrambled and every player response stays byte-identical, and `/final`, `/export` and static are closed. The export permissions in solo and two-human games, before and after the end. Export and final-view contents. Old games are rebuilt. `analyze_game.py` runs on a generated game. |
| `final.py` | Two players play through the UI to the end. It checks the auto-open, the table, the 12 charts with 8 lines each, solid versus dashed lines, the map colours, the tooltip, the highlight, colouring by race, the export download, the top-bar button, player B, a spectator from the lobby, and the lobby's Export button. Screenshots: `shots/final-*.png`. |
| `load.py` | Combined Load. The dialog makes the right L/LOCT and FL/FLOCT orders and they pass Check. The turn applies them all. The capacity and stock warnings block. Prefill and replace leave no duplicates. Editing one order uses the single form. L and LOCT are still under Other orders. Screenshots: `shots/load-*.png`. |
| `unload.py` | Combined Unload. At your own system: U and LACT, Check, the turn applies them, prefill and replace, and the over-cargo block. At an unowned system: IU without population is refused; with population the order is U P then U I, and the turn claims the system and lands the IU. At a foreign system: FUG, which the form calls a gift, and the turn unloads it. Screenshots: `shots/unload-*.png`. |
| `final_long.py` | Screenshots only: `shots/final-long-*.png`. |
| `rules.py` | The Rules tab: the whole rulebook, no sideways scroll at panel width, the font size, the contents list jumping, search, the scroll position kept, the same rendering as the Help dialog, and no id clashes. Screenshots: `shots/rules-*.png`. |

## Run

```
~/mhgc/venv/bin/python tools/sample_game.py ~/mhgc/work/sample-70.zip --turns 70 --seed 7
~/mhgc/venv/bin/python tools/analyze_game.py ~/mhgc/work/sample-70.zip --every 10   # [--race NAME]
source ~/.local/chromelibs/env.sh; cd ~/mhgc/work/uitest
~/scratch/sidion/venv/bin/python final.py; ~/scratch/sidion/venv/bin/python rules.py
```

The sample output is in `~/mhgc/work/sample-70-analysis.txt`.

## Notes for Dave

- **Victory points aren't comparable between humans and bots.** Humans' VP include the stat-ranking bonus, because ranks are among humans only (A-04), and computer empires' VP don't. The summary says so.
- **Some declarations of war are rejected harmlessly.** A bot's DW is occasionally rejected with "already at war". This happens when the other side declared war the same turn, earlier in the race order. The log shows the bot's stance was neutral when it decided.
