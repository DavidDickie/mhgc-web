# MHGC web: stage 3 (UI) notes, 2026-11-12

The browser UI lives in `app/ui/`. It is plain HTML, CSS and ES modules with no build step, no
libraries and no CDN, and is served by the existing `/static` mount (`/` serves `index.html`).
Everything a player sees comes from the API described in STATUS.md, plus two small additions
(below). All game and user text goes into the DOM with `textContent`, never `innerHTML`.

## Files

| File | Contents |
|---|---|
| `index.html` | The shell: the lobby, the game screen (top bar, map pane, dock), and the dialogs (new game, join, order form, help, confirm). |
| `style.css` | A dark theme. Body text contrast is at least 4.5:1 on every surface (checked numerically). There is a visible focus ring everywhere. |
| `core.js` | `api()` (rewrites a host's reads to `/as/<race>/` while viewing as a race), the login store (localStorage `mhgcSeats` = `{gid: {active, races: {seat: {token, player, race}}}}`, seat 0 = the host login; the old `{seat, token, player}` form is read too; the page's race is pinned from `?seat=`), DOM helpers, toasts, the confirm dialog, the event bus, app state `S`, relation colours, and torus geometry (mirroring `mhgc/geometry.py`). |
| `world.js` | The per-square index built from the view (own, scanned and remembered systems; fleets, ships and foreign ships; battles), and the draft's planned moves. |
| `map.js` | `GalaxyMap`: the canvas renderer and its input handling, plus the minimap. |
| `inspector.js` | The selection panel over the map, with context actions. Map-driven moves live here. |
| `orders.js` | Order forms generated from the catalogue, the draft list, check, submit/withdraw, and the classic text pane. |
| `report.js` | The integrated turn report and the battle renderer; "Report: Standard \| Classic text" (2026-11-15). |
| `graphs.js` | Statistics over turns: small multiples with a hover tooltip and a table view. |
| `production.js` | The Production tab (2026-11-13): per-system projection from `/production/preview`, the inline profile editor and "Generate CSP orders". |
| `panels.js` | Empire (economy and systems), Tech, Forces (fleets/ships/troops), Leaders (and spies), Races (diplomacy). Includes a generic sortable, filterable table. |
| `chat.js` | Game-wide and private chat threads. |
| `lobby.js` | The game list, new game (play a race or host only, passwords), the game dialog (log in to a race, take an open seat, host login), leave and drop (W-21, W-23). |
| `account.js` | The top-bar race switcher, View as picker and banner, the ☰ menu (change password, log out, leave, host controls, host password, export), the set-a-password dialog and Host controls (reset password, hand to the computer, open for a human). |
| `help.js` | A small DOM-building Markdown renderer for `docs/RULEBOOK.md`. It powers the help dialog (contents and search) and indexes each order code's rulebook section for contextual help. The screen help is the rulebook's own "PLAYING IN YOUR BROWSER" chapter (2026-11-14). |
| `app.js` | Routing (`/?game=<gid>`), the top bar, the dock tabs, history browsing, polling, and the map wiring. |

## Screens

**Lobby.** This is the game list. Each game shows its turn, its size and when it was last updated,
and a chip for every seat: open, submitted (✓) or waiting, with the host marked ★ and your own seat
highlighted. Each game also says who the turn is waiting for. The buttons are:

- **Play**, for a seat this browser holds;
- **Join**, which opens a seat-picker dialog (the race name can be chosen only at turn 0);
- **Leave**, with a confirmation;
- **Drop**, with a confirmation, shown when you hold a seat or nobody is seated;
- **New game**.

Opening `/?game=<gid>` without a seat shows the lobby and offers to join.

**Game screen** (designed for 1366x768 and up; the dock widens at 1700px or more):

- **Top bar:**
  - the game name, and your race, player name and host flag;
  - the turn picker (◀ / select / ▶) for history;
  - chips for EU, IU depot, VP, systems, population, ships and techs;
  - your submission state, and who the turn is waiting for;
  - **Check orders**, **Submit turn** / **Withdraw**, **Force turn** (host only, with a confirmation that names the seats that haven't submitted), and **?** for help.
- **Map:**
  - The board is a torus in relative coordinates (home at 50,50; y up, as in the old gcviewer). Pan by dragging, zoom with the wheel or the buttons.
  - The initial zoom fits what the empire knows, within 20 squares of home.
  - What it draws:
    - scan coverage, as shaded squares;
    - a grid with coordinate labels;
    - systems: yours sized by population, with starport notches, a dashed red ring when under attack or interdicted, and a gold ring on home;
    - scanned foreign systems (a hollow ring for a long-range scan);
    - map memory, dimmed and dashed (CD-ROM systems are marked in the tooltip);
    - ship chevrons with counts for ships not in a fleet (yours up and right, foreign down and left); fleets as hexagons with a ship count and name (yours right of the square, scanned foreign fleets left, forming ones dashed; see "Fleets on the map" below);
    - foreign ships' "moved from" trails;
    - battle starbursts;
    - movement paths that follow the engine's per-axis stepping, with a dot per turn and an ETA label. Standing orders are faint blue, this turn's draft moves are dashed yellow, and the focused unit's course is bright.
  - Colours encode the relation to you (yours, allied, neutral, at war, not contacted, rebels, unowned). Sixteen identity hues would be unreadable.
  - The **Layers** menu toggles each layer (remembered in localStorage) and holds the legend.
  - Hovering shows a tooltip with the square's contents. A minimap (click to centre) and a "Go to system…" search with autocomplete complete the pane.
- **Keyboard:** with the map focused:
  - the arrows move a cursor (Ctrl moves 10 squares, Shift pans);
  - Enter selects the square;
  - M moves the focused unit there;
  - H goes home;
  - +/- zoom;
  - Esc cancels.

  Anywhere else, `?` opens help and `/` jumps to the search.
- **Inspector:** click a square to open it.
  - **Own system:** full details, and the draft orders that mention it. The buttons are Build ship, Build troops, Profile (prefilled), Infrastructure, Starport +1, Artifact, AU release, IU to depot and Fleet from ships here, plus a picker for every other system order.
  - **Fleet:** members, speed, posture and role, attack and defence. The buttons are **Move (click map)**, Move to system, Intercept (click a target), Speed, Posture, Role, Load, Unload, Add ships, Remove ships and Disband, plus a picker for every other fleet order.
  - **Ship:** the same idea, with Guard, the cargo and troop orders, and Join fleet.
  - **Loose ships** (2026-11-16): each with a tick box, Select all, **Make fleet** and **Add to fleet** (see below).
  - **Foreign ships:** each has an "Intercept" button when you have a unit focused.
  - **Battles** on the square are rendered in full.
  - **Moving:** a selected fleet or ship stays focused when you click elsewhere, so the inspector offers "Send … here". Right-click (or M) moves it directly. A map move *replaces* that unit's earlier movement order rather than stacking another one.
- **Dock tabs:**
  - **Report:**
    - a digest of tiles (EU, IU, VP, systems, population, NNP, production, warships) with turn-on-turn deltas, and a banner if there were battles;
    - then collapsible sections:
      - messages (MESSAGE orders);
      - order results (✓/✗ with the engine's reason and messages);
      - events grouped by report section, with icons and links to the system on the map;
      - battles: the sides with ships and troops, the relation lines, the phases (space, raid, ground, status, capture) with kills highlighted, the outcome (status and owner change), and "Show on map";
      - the maintenance ledger table;
      - scans: foreign systems and ships, whose rows go to the map;
      - statistics and ranks.
  - **Orders:**
    - the submit bar and an "add any order" picker grouped by category;
    - the draft list, each order with its classic text, a description, the inline check result, and ↑ ↓ ✎ ✕ (drag and drop also reorders) plus "Clear all";
    - the **Classic order text** pane: the textarea starts as the draft, and "Use this text as the draft" sends `{text}` and shows per-line parse errors. What you type survives polling re-renders.
  - **Empire:** economy tiles, the autosupply toggle, Rename race, a sortable and filterable systems table (rows go to the map), artifacts and trade routes.
  - **Tech:** the tree by cost tier. Each tech is shown as owned, can-buy or locked, with its prerequisites (owned ones in green), what it unlocks, its VP, Buy (PT) and Crash (CRP) buttons, and "In your draft". There are All / Can buy / Owned filters.
  - **Forces:** Fleets, Ships and Troops tables, sortable. Ships can be filtered by text, by type and by "idle only", and ships with draft orders are marked ✎. The sub-tab, filters and sorts are kept per browser (see "Filters and sorts persist" below).
  - **Leaders:** each leader with skill bars, a collapsible biography and move, rename and ice orders. Each spy with its post and missions (the picker uses the fuller mission help).
  - **Races** (diplomacy): contacted races with your stance and DCT deny/split. The buttons are Ally, Declare war, Offer peace or End alliance, Gift EU, Gift tech, Trade tech (computer empires only), Message (with orders) and Chat privately (human races).
  - **Stats:** 15 small-multiple line charts (VP, POP, NNP, GNP, SYS, TEC, EU, IU, WAR, NWR, CTS, STP, HAP, PRD, GWR) over every turn. Each has a crosshair tooltip with the value and rank, and there is a table view.
  - **Chat:** an Everyone thread plus one thread per contacted human race, with unread badges on the threads and on the tab. Enter sends. System notices are shown in italics.
- **Order dialog:** generated from the catalogue.
  - **Pickers** come from the view and `/api/reference`:
    - own ships, fleets, troops, spies and leaders;
    - systems: own systems for system orders; any known system, by autocomplete, for MS/MFS/ML/SMV;
    - contacted races;
    - techs, filtered by purpose (buyable first for PT/CRP, owned ones for GT);
    - ship, troop and artifact types, with costs and stats, and those needing a tech grouped and labelled;
    - multi-select ships for AF/LF, and recipients for MESSAGE;
    - coordinates with **Pick on map**.
  - A live classic-text preview, and a running total for CSP.
  - **More from the rulebook** shows that order's section of RULEBOOK.md.
  - Server-side syntax errors (422) show in the dialog, which stays open.
- **Help:** the whole rulebook, rendered, with a contents list and search (highlights, with Enter jumping to the next match). The rulebook's "PLAYING IN YOUR BROWSER" chapter is the screen help (see "Changes of 2026-11-14").
- **History:** picking an earlier turn swaps in that turn's view (map, inspector, report). A banner offers "Back to the current turn". Order buttons are disabled while you look at history.
- **Polling:** every 3 s (and whenever the tab becomes visible), `/version` is polled:
  - When `turn` changes, the view, draft and stats are refetched, a toast appears, and the Report tab opens. If you are browsing history, it stays where you are and the toast tells you.
  - When `version` changes, the lobby summary is refreshed (submissions, joins).
  - When `chat_last` grows, `/chat?since=` is fetched.
  - A 404 (dropped) or 401 (seat gone) returns you to the lobby.

## API changes (app/main.py, app/catalogue.py)

- `GET /api/games/{gid}/stats` (seat token). Returns `{current, turns: [{turn, values, ranks, vp, economy, events, combats}]}`: this seat's own stats line for every turn, read from each turn's `results.json` and cached per past turn. `economy` drops the per-system breakdown, exactly as `view.py` does.
- `GET /api/rulebook`. Returns `docs/RULEBOOK.md` as `text/markdown`.
- `catalogue.py`: the spy missions (SOS, SOT, SOL, SVS, SOE, SOM, SON, SAL, SSB, SUP, SRS, SET) had the help text "Spy mission". They now have one-line help with the rulebook's odds.
- Tests: `tests/test_api_ui.py` (3 tests). They check that the stats series matches `/view` per turn and per seat and survives a restart, the rulebook endpoint, the spy help, and that the UI assets are served. The full suite has 206 tests, all passing.

## Browser test (Playwright)

The flow is `~/mhgc/work/uitest/flow.py`. It needs Playwright and the vendored headless shell, so it is not part of the pytest suite. It starts its own server on port 8791 with a temporary `SAVE_DIR`, and stops it by PID.

```
source ~/.local/chromelibs/env.sh
~/scratch/sidion/venv/bin/python ~/mhgc/work/uitest/flow.py      # 32/32 checks, no console errors
```

The script uses two browser contexts:

1. Create a game with 2 seats.
2. Join from the lobby.
3. A gives orders through the UI:
   - selects the scout on the map and uses **Move (click map)**, giving MO;
   - uses **Build ship** with type F and posture H;
   - sets the **Profile** to 40/30/30;
   - uses **Buy** in the tech tree.
4. A checks the orders: inline ✓/✗, and a typo'd order is caught.
5. A deletes an order and reorders the draft.
6. A submits, then edits an order, which withdraws the submission; A resubmits.
7. B uses the classic text pane (CSP, a MESSAGE block, BI) and a right-click move, then submits.
8. The turn runs in both browsers. The report, its sections and the graphs render, and the history picker works.
9. Game-wide chat reaches B, with an unread badge.
10. Private chat is tested both ways:
    - The two empires are given contact as a test fixture, by editing the saved state while the server is down. Human homes start far apart.
    - A uses the Races tab's "Chat privately"; B sees the message only in the private thread and replies.
11. The host forces a turn after the confirmation.
12. Help: search, and the order form's rulebook section.
13. A 1920x1080 screenshot, and keyboard selection on the map.

The screenshots are `~/mhgc/work/shots/flow-*.png` (22 of them). The `dev-*.png` shots come from a 40-turn seeded game (`seed_game.py`, with a staged battle at turn 38; `tour.py`; `stress.py`).

**Stress test:** the view was inflated to 176 systems, 1,200 own ships with cross-board orders and 400 foreign ships. In headless software rendering a full redraw took about 25 ms zoomed right out, 13 ms at the default zoom and 7 ms zoomed in. Rebuilding the index took 1.5 ms. The map draws only when something changes.

## All-orders sweep (`all_orders.py`, 2026-11-12)

`~/mhgc/work/uitest/all_orders.py` gives every catalogue order through the real UI, one fresh copy of a rich seeded game per order (`seed_orders.py`: transports with and without cargo, fleets Alpha and Bravo, troops on the ground and aboard, a leader in limbo, spies at home and at Bob's home, farcasters and warp tunnels on two systems, a 0.6-pop colony, an empty system, contact with Bob, an NPR and an NPR at war). For each order it opens the dialog the way a player would, tries one invalid value where meaningful, fills the fields with the real controls (selects, checkboxes, Pick on map), checks that the preview matches the expected classic text exactly, reopens it with ✎, runs Check, submits and forces the turn, and then verifies the effect in the saved state. It also runs a sample through the classic text pane. Pass order codes to run a subset; `--keep` keeps the SAVE_DIR.

```
source ~/.local/chromelibs/env.sh
~/scratch/sidion/venv/bin/python ~/mhgc/work/uitest/all_orders.py     # 100/100, about 12 minutes
```

The fixes made from it:
- `orders.js readForm`: `elements.namedItem(name)`. A field named `item` used to return the collection's `item()` method, so L/U/UG/SL/FL/FU/FUG/TP lost their item.
- The Orders tab picker skipped orders with an empty help line (NOAUTOFLEET, NOTRACKSCAN). It now lists every order, and those orders have help text (`mhgc/orders.py`).
- ML, WTP and WTPF pick from your own systems, as the engine requires, instead of autocompleting any known system.
- The troop pickers are filtered: LOCT/FLOCT list troops on the ground (no militia), LACT lists the selected ship's troops, and FLACT the fleet's troops.
- AF/LF re-filter the ship checkboxes when the fleet changes, and LACT/FLACT/TP re-render when the field they depend on changes.
- TP with item C asks for the troop (a picker of troops at the sending system) in place of a number.
- SL also offers other races' ships in orbit at your systems (the point of SL), and only cargo ships of your own.
- The Races tab has Deny trade (DD), Split trade (SD) and Send system info (SSI) buttons.
- The inspector of an own system with your troops has a "Troop orders" picker (DCT, SCT, CCP).
- Field help for TP, SL, ML, WTP and WTPF (`app/catalogue.py CODE_FIELD_HELP`).

## Production tab (2026-11-13)

Dave: "another tab on the info panel called Production". It sits next to Empire in the dock.

- **Table**, one row per own system: name (click = show on map), population (growth in the tooltip), mood now → after feeding (numbers in the tooltip, ▲/▼ trend), the AU/IU/EU profile as three inline number inputs, the projected end-of-turn AU and IU stockpiles (production and feeding in the tooltip), EU produced, and flags: **⚠IF** when infrastructure < population, **★n** when n system technologies can be installed now (hover names them; click opens the row), and **!p%** / **✖RB** for uprising risk or a certain rebellion.
- **Starting profile:** the current profile after the draft's own orders, so a CSP already in the draft is the starting point (dashed inputs mark it).
- **Editing:** the inputs and, in the ▸ detail row, sliders. Since 2026-11-14 each field is independent (no auto-balancing; see "Changes of 2026-11-14"); a row that doesn't total exactly 100 is red and isn't previewed. Changed rows are highlighted and get a ↺ reset; "Reset all" too. Edits are debounced (220 ms) and sent as `overrides`; stale responses are dropped; cells update in place, so focus is kept.
- **Detail row:** sliders, what the system produces and feeds, its emperor-day or uprising odds, and each installable technology with its cost, upkeep and an **Install…** button (BT, prefilled), plus the ones you own but can't afford yet and why.
- **Totals** row (population, AU and IU stockpiles, EU produced) and **Empire after this turn**: EU stockpile and IU depot start → end, and the projected maintenance listing grouped by kind (orders' spending, production, SISD, autosupply, artifact, ship, troop and spy upkeep). Predicted demobilisations are listed in red. Draft orders that fail in the projection, and those not projected (involving another empire), are listed. "What the estimate includes" spells out the scope, and an "Estimate, before random events and combat" note sits under the title.
- **Generate CSP orders (n):** for each changed, valid row (invalid rows are skipped and the toast says how many), replaces the last CSP for that system in the draft (dropping earlier duplicates) or appends one (using the name after any NSY in the draft). Other rows are left alone. The Orders tab and the draft count update at once.
- **API:** `POST /api/games/{gid}/production/preview` (seat token) with `{overrides: {system id: {au, iu, eu}}}`. 401 without a seat, 409 if the empire gives no orders, 422 for a bad profile or a system that isn't yours (one message for both, so ids leak nothing). Nothing is stored. About 7-10 ms. See DECISIONS W-12 for what is and isn't included.
- **Engine refactor (results unchanged):** `economy.system_production`, `feed_amount`, `settle_happiness` and `unrest_risk` were split out of `produce`/`happiness`, and `orders_exec.check_artifact_install` out of BT. `model._decode` now caches `get_type_hints`, which made every state load about 4x faster.
- **Tests:** `tests/test_production_preview.py` (7): no-override projection equals a quiet `run_turn` exactly (all rows, EU, depot, ledger kinds; GT listed as skipped); over 30 turns with NPRs playing, every miss has a left-out event (seeds 11-13: 22-24 of 30 turns exact, the rest emperor days or random events); overrides follow the formulas (the rules' 4-pop 10/5/5 example → 4/8/8 at 20/40/40); tech flags use the stockpiles an install order would pay with (also after a PT in the draft); scrambling other empires changes nothing; seat-only, validation, no mutation (files and version unchanged).
- **Browser:** `~/mhgc/work/uitest/production.py` (port 8792, 40 checks since 2026-11-14): the tab, flags and hover, independent inline and slider edits (red rows, the hint, dimmed projection, not previewed until valid), live totals, EU and happiness, reset and Reset all, Generate CSP skipping an invalid row and then writing both (home CSP replaced, colony CSP added), the Orders tab, then the real turn matches the preview. Screenshots `~/mhgc/work/shots/prod-*.png`.

## Scan history and sticky map memory (2026-11-13)

Dave: "show space that you have scanned but is no longer in scanning distance" and "systems you've seen, you know their rating and whether they are AR/MR, so that information should stick". DECISIONS G-07 and G-08.

- **Engine:** `Empire.scan_history` (base64 100x100 bitmask, `mhgc/scanmask.py`) gains every square inside the empire's ship and populated-system scans each turn. `engine/scans.remember` writes map memory everywhere (scans, capture, colonising, NSY): name, owner and turn of the latest sighting, plus `hab`, `mr`, `ar` and `detail_turn` from the latest short scan only (rules:1174: long scans show owner, name and location).
- **View:** `scan_history.data` (1668 characters, relative coordinates, own empire only); remembered systems and long-scanned ones carry the remembered `hab`, `hab_value`, `mr`, `ar`, `details_turn`.
- **Map:** three tints (inside a scan now: blue; scanned before: grey; never scanned: darkened; see the next section for the values), on the map and, stronger, on the minimap. Layer "Scan history (scanned before / never)". The cursor line says which of the three a square is; the inspector does for an empty square.
- **System sizes by habitability** for every system whose rating you know: radius = base x EH 1.0 / VH 0.86 / H 0.72 / PH 0.6 / MH 0.5, base = clamp(2.6 + 0.3 x zoom, 4.2, 14) px. Unknown rating: a small diamond. Own systems are no longer sized by population: a green population badge sits at the upper left (zoom >= 7) and the tooltip says "pop N". MR = orange square pip, AR = green round pip, lower right; dimmed with remembered systems. Minimap dots are sized by habitability too. The legend has the tints, the sizes, the pips and the badge; the layers panel scrolls rather than covering the minimap.
- **Tooltip and inspector:** "Habitability VH · MR · AR (as of turn N)" for remembered and long-scanned systems; the inspector spells them out ("Very habitable [VH] · Metal rich [MR] · Agriculture rich [AR] (as of turn 3)") with a terraforming caveat; "unknown (needs a short range scan)" otherwise.
- **Tests:** `tests/test_scan_memory.py` (5): history accumulates and is exactly the own scans, relative in the view, round-trips, old saves load empty; B's view is unchanged by A's history; mask helpers wrap; memory keeps hab/MR/AR after leaving range, a long scan keeps them, a short rescan updates them; a never short-scanned system exposes none of them (differential). `test_view.py`'s differential test also scrambles B's history.
- **Browser:** `~/mhgc/work/uitest/scanmem.py` (port 8793, 17 checks): a scout flies onto a VH MR AR system and on past it over five turns; the square shows as scanned before, the system as remembered with the rating, MR/AR and "as of turn 3" in tooltip and inspector; layer toggle and legend; then a fixture where all 176 systems are known. Screenshots `~/mhgc/work/shots/scan-*.png`.

### Scan history: visibility, backfill and an end-to-end check (2026-11-13, later)

Dave: "not seeing previously scanned squares with a faded grey background". It was drawn, but at 14% alpha grey-blue on a near-black map, and games started earlier had no history.

- **Tints** (`map.js TINT`, composited on the map background): never `[0,0,0,150]` (about #04070d, darkest), scanned before `[150,156,168,62]` (a plain grey, about #2a323f), inside a scan now `[70,140,255,110]` (blue, about #21457f, brighter than before). The explored region (now or before) has a thin light outline (`EDGE`, merged edge runs in `cover.edges`, drawn per visible torus copy). Minimap alphas now 190 / 125 / 0. Legend swatches show the composited colours, with the outline on "Scanned before" and a line explaining it. Standing movement paths went from alpha 0.4 to 0.55 so they stay visible on the brighter tints.
- **Fixes found on the way:** the coverage image (and so the history) was drawn only when the "Scan coverage (now)" layer was on, so turning that off hid the history too; it now draws when either layer is on. The UI's "now" marked own unpopulated systems' squares, which the engine doesn't scan from; it now uses the view's `scan_range` (0 for them) as the engine does.
- **Backfill** for games from before scan history: on load, from the stored turn states (DECISIONS G-07). `Game.backfill_scan_history` in `app/main.py`, `scans.rebuild_scan_history` / `mark_area_scans` / `empire_area_scans` in the engine. `do_scans` now marks through `mark_area_scans` too.
- **Tests:** `tests/test_scan_backfill.py` (5): a game played with recording disabled (all turns, or until turn 3: Dave's case, a game that continued after the feature arrived), at 75 and 100, then backfilled, equals the live-recorded game on every turn's state and in the view (current and history); idempotent (a restart and a forced redo write nothing); each empire's mask is exactly its own boxes and moving other empires' units changes nothing; with a turn state deleted and another corrupt, the rest is backfilled. 322 tests.
- **Browser:** `scanmem.py` now 40 checks. For every square, the engine's absolute mask from `state.json`, converted in the test with `geometry.to_rel`, must equal the UI's decoded history, the coverage image pixel at (x, board-1-y), and `coverageOf`; on the 100 board, on a 75 board (8 empires, home 37,37) with the scout on the relative wrap seam (x = 1, its box wrapping to 74) and a server restart midway (history unchanged, then still accumulating), and on a copy of that game with its history blanked on disk and the flag removed, which the backfill restores to equal the live game on all 16 turns. New shots `scan-14-75-wrap-seam.png`, `scan-14b-75-standing-path.png`, `scan-15-75-zoomed-out.png`, `scan-16-75-minimap.png`, `scan-17-backfilled-default-zoom.png`.

## Known rough edges (for Dave to look at first)

1. **Draft rows for ECHO and MESSAGE.** `GET/PUT /orders` rows put the classic text in `text`, which is also the argument name for ECHO and MESSAGE. The UI recovers the argument from the classic text (`orders.js rowToDict`). That works, but the API would be cleaner with a separate key.
2. **Fleet speed `A`** on the map uses the slowest member's `move`. Paths are drawn as the engine steps, but stragglers and intercepts aren't simulated.
3. ~~No scanned-square history.~~ Done 2026-11-13 (scan history, G-07); see "Scan history" above.
4. **The report's order list can be long** (all orders, successes included). Failures are red but are not sorted first or filtered.
5. **Chat is noisy with "Turn n has run" notices.** They are shown in italics in the Everyone thread.
6. **Starting zoom.** The board fits within 20 squares of home, which is quite zoomed in on turn 0 (only two or three systems are known).
7. **Small screens.** The game screen has a 1280px minimum width, so there is no tablet or phone layout.
8. **Private chat in the flow needs injected contact.** Real contact takes many turns of scouting, so a real game hasn't been played far enough through the UI to see private chat arise naturally.
9. **The fuzz-seeded dev game shows empty fleets** (`F1_13 (0)`), because the fuzz order generator creates fleets and then moves their ships away. The UI shows them faithfully. Real players will see this too if they empty a fleet, and may want a hint to disband it. *(2026-11-16: fixed by G-18: an empty fleet is now disbanded at the end of the turn, so these vanish at the save's next turn.)*
10. **Combat logs** list participants' ships by type but not by fleet name (the logs carry internal fleet numbers; STATUS.md "Known gaps").
11. **Spectators.** A browser without a seat sees only the lobby. There is no read-only game-wide-chat view for spectators, although the API allows one.

## Not touched

`mhgc/npr.py`, `tests/test_npr*.py` and STATUS.md were not touched. No git commits were made.

## Four-empire game (2026-11-16)

- **New game dialog:** five size cards; "4 empires, 50x50" with a 2x2 diagram is first, 8 stays the default (`lobby.js GAME_SIZES`, `.size-opts` grid of 5). The human-seat maximum follows the size (4). The lobby line shows `4 empires (50x50)` and a 2x2 mini diagram.
- **Map at 50:** no code change needed: `BOARD`/`HOME` from the view (25,25), the 10-square grid divides 50 evenly, the coverage and minimap images are 50x50, the torus repeats every 50 squares, the zoom-out limit is 62 squares (so the board shows more than once when zoomed right out).
- **Browser:** `flow.py` with `MHGC_SIZE=4` (49/49; it now also checks five cards and the 2x2 card): `flow4-01-new-game.png`, `flow4-22-lobby-after.png`, `flow4-24-board-zoomed-out.png`, `flow4-24b-wrap-seam.png`, `flow4-25-minimap.png`.

## Game sizes and computer chatter (2026-11-13)

DECISIONS W-13 and W-14.

- **New game dialog:** a "Game size" picker of four cards (8 default / 9 / 12 / 16), each with a small diagram of its bins (dashed squares = empty bins, open territory) and the board size; the human-seat field's maximum follows the size and the hint says how many computer empires there will be. A "Computer chatter" select (normal / quiet / off). `lobby.js GAME_SIZES`, `binDiagram`.
- **Lobby:** each game's line shows a mini bin diagram, its size and board (`8 empires (75x75)`).
- **Board-sized map:** `core.js` has live `BOARD` / `HOME` bindings set from `view.game.board` (`setBoard`); `wrap`, distances and paths use them. `map.js`: the scan-history decode, the coverage and minimap images (board x board), the torus copies, the grid, the zoom-out limit (board + 12 squares), the home marker and H key, minimap clicks and the viewport box all use the board; the app's fit-home, goto and zoom-home use HOME. The order forms limit coordinates to 0..board-1; panels and the inspector use HOME for "home".
- **Chat:** computer empires' boasts are race messages (amber name, a "computer" badge, normal text), not italic system notices. The host has a "Computer chatter" select at the top of the Chat tab (`POST /settings`); others see the current setting.
- **Browser tests:** `flow.py` takes `MHGC_SIZE` (default 16) and picks the size in the dialog. New checks: the default size, the four cards and empty-bin diagrams, the seat limit, the game's board/size/home; then 5 more forced turns, boasts in the Everyone thread as race messages with the race in capitals, the host's setting; the board's coverage image and minimap size, the torus repeating every board width, wrap at 0,0, coverage at home and across the wrap, the minimap drawing, a minimap click mapping to board coordinates. 47/47 at size 16 (`flow-*.png`) and 47/47 at size 8 (`flow8-*.png`, including `flow8-01-new-game.png`, `flow8-23-chat-bots.png`, `flow8-24-board-zoomed-out.png`, `flow8-24b-wrap-seam.png`, `flow8-25-minimap.png`). `all_orders.py` (98/98), `production.py` (26/26) and `scanmem.py` (17/17) create 16-empire games and pass.

## Changes of 2026-11-14 (Dave)

DECISIONS G-09, G-10 and G-11.

1. **CGR removed** (G-09). The order is gone from the model, catalogue, engine, preview, bot, view, inspector (the Growth button and "growth N%"), the all-orders sweep and the rulebook. Every system grows at 100; an old save's stored rate is dropped on load. Typing CGR gives the G-01 "no longer exists" error, with its own reason; `all_orders.py`'s classic-pane check now types CGR as well as AUTOFLEET.
2. **Filters and sorts persist.** *Root cause of "idle only unchecks when you click a ship":* every dock panel is rebuilt from scratch on each render, and the Forces panel is re-rendered on every `draft` event (giving the clicked ship an order, check results, submit/withdraw), on a new turn, on history browsing and on switching tabs. `renderForces` created the "idle only" checkbox, the type select and the text box with default values each time, so their state was lost; the sort lived in a module variable (`sortState`, lost on reload) and the Forces sub-tab in another. The Empire systems table's filter box had the same bug. *Fix:* `core.js getPref/setPref` keep UI prefs in localStorage `mhgcPrefs` (per browser, all games): `sort.<table>` for every `dataTable` (fleets, ships, troops, systems, and the report's scans tables, which are now sortable `dataTable`s: `scanSystems`, `scanShips`), `filter.ships` {q, type, idle}, `filter.systems.q` and `filter.forces.tab`. The controls are built from the prefs; a saved ship type with no ships now still shows as an option. `app.js renderTab` also keeps the focus and caret in a filter box across a re-render, so typing isn't interrupted. The other tabs were checked: the Tech filter and the Stats mode were already in localStorage; Leaders, Races, Chat and Production have no filters or sorts. *Browser test:* `~/mhgc/work/uitest/prefs.py` (port 8794, 21 checks): idle only + type + sort on the Ships table survive clicking a ship, an order for it, typing through a re-render (focus kept), polling, a forced turn, history browsing and a reload; the Empire filter and sort survive a draft change, a turn and a reload; the Forces sub-tab is remembered; the scans tables sort and keep it across a reload; no console errors.
3. **Production split editing** (G-10). `production.js`: `rebalance` is replaced by `splitProblem` (null, or the hint). Inputs and sliders set only their own field (`setField(id, key, raw, from)`; the control being used isn't rewritten). A changed invalid row gets `tr.invalid` (red), `#sphint-<id>` "must total 100 (now N)", and `td.stale` (dimmed, italic) on mood, AU, IU, EU and flags; it is left out of `overrides`. "Generate CSP orders (n)" counts valid rows only, stays enabled when only invalid ones exist, and says "N rows don't total 100" (skipped, still red). CSS in `style.css` (`.tbl.prod tr.invalid`, `td.stale`, `.split-hint`).
4. **Web rulebook** (G-11). `docs/RULEBOOK.md` audited for email-turn assumptions. The rules text had already lost the email headers, deadlines and "send to the GM"; what remained were delivery details: the NPR flag "in the relations report", "the turn results screen", spy "printouts", ECHO "versions of your orders", the order-format notes and the old printed-result examples. New chapter **PLAYING IN YOUR BROWSER** (after JOINING A GAME): The game list (seats tied to the browser, New game, Join, Play, Leave, Drop), The game screen, The map and its layers, The selection panel, Giving orders, The classic order text, Check orders / Submit / Withdraw, When the turn runs (the host's force), The Report tab, The other tabs (Empire, Production, Tech, Forces, Leaders, Races, Stats, Chat), Looking at earlier turns. Rewritten in place: the intro, JOINING A GAME, CONVENTIONS, TURN PROCESSING, the NPR flag, TURN RESULTS (which tab shows each part), STATISTICS, ORDER FORMATS (forms, the draft, classic text; a note that the examples show the old printed results), a "where to find these" paragraph at the head of each order group (system, ship, leader, combat troop, fleet, empire, miscellaneous), the spy reports, MESSAGE and ECHO. CGR's Growth Rate profile and order entries are gone (the flavour of basic growth stays, with a note that earlier editions had CGR). Codes stay as references. The help dialog dropped its hard-coded "Using this screen" list. The previous edition is `docs/RULEBOOK-classic.md` (with a note at the top). Screenshots: `~/mhgc/work/shots/help-01-playing-in-your-browser.png`, `help-02-selection-panel-and-orders.png`, `help-03-search-production.png`, `help-04-system-orders.png` (from `~/mhgc/work/scratch/help_shots.py`).
5. **Runs on 2026-11-14:** pytest 322 passed; `flow.py` 47/47; `all_orders.py` 97/97 (CGR gone, was 98; the classic check types CGR and AUTOFLEET and asserts both errors), console errors 0; `production.py` 40/40; `scanmem.py` 40/40; `prefs.py` 21/21.

## Races, passwords and the host (2026-11-15; DECISIONS W-21..W-24)

- **Lobby:** each row has Play (Play the <race> per race held, Host view for a host login), **Open / join** (also a click on the name) for the game dialog: Play an existing race (claimed races, password), Take an open seat (seat, name, race name at turn 0, password twice), I'm the host (host password). New game: "I'll play a race" (race password twice) or "Host only, no race" (0 human seats allowed); a host password is required in both (W-25): "Use my race password as the host password" (ticked by default) or a host password twice, remembered in this browser's localStorage `mhgcHostPw` when "Remember it" is ticked and prefilled next time.
- **Game screen:** race switcher (when several races are held; each switch reloads the page with `?game=&seat=`), ☰ menu, View as picker and banner for the host login (`?seat=0&as=<race>`), Run turn / Run 5 turns in host-run games, "Waiting for the host to run turn N". A restricted login (old seat, or after a host reset) gets the set-a-password dialog before the game opens. The host of a game without a host password gets "Set a host password" (`openPassword("hostmust")`, from `you_must_set_host_password`) before the game opens. A login ended elsewhere (password changed or reset, logged out everywhere, race handed over) returns to the lobby with the game dialog.
- **Browser tests:** `access.py` (37/37): create with a password (mismatch and short caught), take two seats in one browser and switch, the lobby's per-race Play, wrong then right password from a third browser, the menu, host reset with forced new password, change password, hand to the computer, a host-only bot game with View as, Run turn, Run 5 turns, host login from the lobby, the audit log. Screenshots `~/mhgc/work/shots/access-*.png`. `flow.py` (48/48 at 16 and at 8) uses the new create and join; `final.py` (26/26), `all_orders.py` (97/97), `production.py`, `scanmem.py`, `prefs.py`, `rules.py`, `load.py`, `unload.py` pass. Old-format `mhgcSeats` injected by the scripts is still read.

## Host password required, no lockout (2026-11-15; DECISIONS W-25)

- `POST /api/games` needs `host_password` in both modes (400 otherwise). Old games: the host's race gets `you_must_set_host_password`, and host powers answer 403 `set_host_password` until it is set. The login rate limit (`auth.LoginLimiter`, 429, Retry-After) is gone; hashing and constant-time comparison stay.
- **Browser tests:** `access.py` 54/54 (new: the host password section, required in both modes, mismatch, race password as host password, remembered and prefilled, eight wrong race and host passwords without a lockout, an old game's host prompted after a server restart; screenshots `access-12-new-game-remembered.png`, `access-13-set-host-password.png`). `flow.py` 48/48 at 16 and at 8 (unchanged: the default checkbox). The API-driven scripts (`seed_game.py`, `seed_orders.py`, `production.py`, `scanmem.py`, `prefs.py`, `load.py`, `unload.py`) now send `host_password`.


## Production presets and the classic text report (2026-11-15; DECISIONS G-14, G-15)

- **Production tab:** sortable headers (System, Pop, Mood, AU, IU, EU), saved as `sort.production`; the default for a browser with no saved sort is population, largest first; a saved sort is kept. The AU/IU/EU boxes are `calc(3.2ch + .5em + 2px)` of monospace (min 10, max 80, step 1; red styling and hint unchanged). Presets in one table, `production.js PRESETS` (Very early 50/40/10, Early 20/60/20, Balanced 20/40/40, Late 10/10/80, War 10/80/10; Balanced confirmed by Dave 2026-11-20, DECISIONS G-14): a per-row "Preset…" list (arrow only; outlined and titled when the row matches) and "Set all to…" in the toolbar (every row). Both act as typing: changed, live preview, counted by Generate CSP orders. RULEBOOK "THE OTHER TABS" → Production documents them.
- **Classic text report:** the Report tab's "Report:" picker (pref `report.mode`). The server builds it (`mhgc/legacy_report.py`, `legacy_report(view, prev=None)`) from the same view the Standard report uses, plus the seat's previous-turn view for INITIAL STOCKS. Endpoints `GET /api/games/{gid}/report.txt?turn=n` (seat token; 401/403/404 as /view) and `GET /api/games/{gid}/as/{eid}/report.txt` (host login; `core.js api()` rewrites it in View as). The UI caches each turn's text, keeps the scroll position across re-renders, and has Copy, Download (`<Race>_turnresults_<n>.txt`) and Wide view (fixed overlay, Esc closes). History turns and View as work. RULEBOOK "THE REPORT TAB" documents it.
- **Tests:** `tests/test_legacy_report.py` (6): sections in the classic order; the numbers equal the structured results (ledger initial/final, combined upkeep, the running EU and depot reconciling, every system block's profile/production/food/stocks, economic report, VP, ranks, order errors and messages, events, messages, combat lines, races, ships); no foreign markers; the differential test (scramble B, A's text identical); the endpoint returns exactly `legacy_report(/view, /view?turn=n-1)` for current and history turns and both seats; permissions (401 without/bad token, 404 future turn, /as/ needs the host login, the viewed race's report, an NPR's). Browser: `production.py` 63/63 (new: default population order, header sort saved and kept across a reload, a second browser's saved sort kept, the box width measured in ch, min/max/step, Tab order, the per-row presets, Set all, Reset all, Set all to Late + Generate after the turn); `classic_report.py` (port 8799, 23 checks: picker, exact text, section order, monospace, pref across reload, Wide view, Copy via the clipboard, Download name and content, a history turn, back to Standard, View as an NPR). Screenshots `~/mhgc/work/shots/prod-01b-preset-row.png`, `prod-01c-set-all.png`, `prod-06b-generate-late.png`, `classic-*.png` (including `classic-06..09-side-by-side-*.png` against `iraq2/archive/turnresults_35.txt`).
- **Runs on 2026-11-15:** pytest 397 passed (391 + 6); `flow.py` 48/48, `scanmem.py` 40/40, `prefs.py` 21/21, `access.py` 54/54, `final.py` 26/26, `rules.py` 12/12, `load.py` 20/20, `unload.py` 21/21, `tradeoffer.py` 11/11, `production.py` 63/63, `classic_report.py` 23/23. `all_orders.py` first gave 96/97: TTNPR failed with "We already have that tech!" because the friend NPR (5000 EU in the fixture) now buys tech 8 itself (PT 8) in the same turn (bot behaviour, not these UI changes). `seed_orders.py` now gives the friend 200 EU (enough for its 50 EU half of the swap, not for PT 8); TTNPR, SET, PT, CRP and GT pass again, and the full sweep is 97/97 (console errors 0).

## Fleets on the map, Make fleet, the selected-unit ring (2026-11-16)

Dave: "add the ability to select a set of ships at a location and turn it into a fleet. Then show it (and other fleets) as fleets that you can move. If you've selected a ship to move, highlight it or make it blink ... I keep having to click 'move' and then see where the line starts from."

**Engine order of play (checked, no engine change needed).** Orders run in draft order in phase 1, before movement (`turn.run_turn`: `run_orders`, then `movement.move_fleets`/`move_ships`). `CF` creates the fleet at once and `AF` adds ships at once (`orders_exec._cf`, `_af`), so **CF, AF, then MF moves the new fleet the same turn**. `CFXY` only queues its square: the unfleeted ships join in `movement.add_fleet_xy`, *after* movement, so a CFXY fleet has no ships while fleets move and an MF for it is carried out from the next turn. An MF before the CF fails ("You don't have a fleet called ..."). AF doesn't check where the ship is; a ship that joins a fleet loses its own move order (the fleet sets its members' orders). `tests/test_fleet_forming.py` (5 tests) pins all of this: CF+AF+MF moves at the slowest ship's speed this turn; the order checker accepts the sequence and leaves the state alone; MF before CF fails; CFXY forms after movement and moves next turn; a ship's MO is overridden by joining a fleet.

**Draft model (`world.js draftFleets`).** Rebuilt with the map index: `forming` (fleets the draft's CF/CFXY create, with `canMoveNow` = CF), `joins` (AF), `leaves` (LF), `disbanded` (DF), in draft order. `ownFleets()` = the view's fleets plus the forming ones; `findOwnFleet`, `effectiveFleet(ship)`. A CF fleet's members are its AF ships; a CFXY fleet's are a forecast (the unfleeted ships on its square that the draft doesn't put elsewhere). The index puts forming fleets in `q.fleets` and ships the draft adds to a fleet in `q.fleetShips`. Not used for history views. The fleet pickers in the order forms (`orders.js`) and the Load/Unload dialog (`loaddlg.js`) use `ownFleets`/`findOwnFleet`, so forming fleets can be given any fleet order.

**Make fleet (`inspector.js`).** The loose-ship list of a square has a tick box per ship (kept across re-renders while you stay on the square), Select all (with the indeterminate state), **Make fleet (n)** and, when you have fleets there (forming ones included), a fleet picker with **Add n to fleet** (AF, 10 ships a line). Make fleet opens a dialog: the name prefilled with the first free `<system name, 9 chars><n>` (`TF<n>` in deep space); validation (`fleetNameProblem`): not empty, at most 12 characters (also `maxlength`), only `A-Z a-z 0-9 _ - .` (one classic-text token, no `#`), not one of your fleets or forming fleets (case-insensitively, "too close" for a case variant), not a scanned foreign fleet's name; a hint says names are unique galaxy-wide, so an unseen foreign fleet's name fails at turn time. A live preview shows the orders. They are appended to the draft: `CF <name> x y`, then `AF <name> <ships>`. If the ticked ships have their own MO/MS/I/G/WTP orders, a ticked-by-default box drops them. Afterwards the new fleet is selected. The old "Make a fleet of these" (CFXY) button in the ship list is gone; "Fleet from ships here" (CFXY) stays on the system card, for gathering ships built this turn.

**Forming fleets.** Their card is dashed with a "forming" badge and says whether the fleet can move this turn (CF: yes; CFXY: no, a move starts next turn). Members, joining (AF to an existing fleet) and leaving (LF) ships are shown; attack/defence are after the draft. Actions as for a fleet, with **Cancel this fleet** (drops the CF/CFXY and every order naming the fleet) instead of Disband. **Moving:** `moveFocusedTo` replaces the unit's earlier movement order as before, and for a forming fleet keeps the MF after the CF that creates it (moves it after the CF if needed); for a CFXY fleet the toast says it sets off next turn. A ship that is in, or joining, a fleet moves its fleet.

**Fleets on the map (`map.js drawShips`).** Loose ships: the chevron and count (only ships not in a fleet now). Each own fleet: a hexagon in your colour with its ship count (from zoom 8), right of the system (clear of the system's radius), stacked vertically for several, its name to the right from zoom 11 ("(forming)" in italics; forming hexagons are dashed and see-through). Scanned foreign fleets (`view.scans.fleets`): hexagons in the owner's relation colour left of the square, names to the left; their member ships no longer get a separate chevron. Zoomed out (below 9) a square shows one hexagon of each kind plus a "+n" badge. Clicking a hexagon selects that fleet (hit areas from the last frame, `map.hits`). The tooltip lists foreign fleets. Draft paths are drawn for forming fleets too. The legend (Layers) has a "Ships and fleets" section with small drawn keys, including the selected-unit ring.

**The selected unit (`map.js placeHighlight`, `style.css .unit-ring`, `.edge-arrow`).** A DOM overlay, not canvas: a magenta (#ff4fe3, a colour no relation uses) ring with a dark outline and white core, around the selected fleet's own hexagon, or the loose-ship chevron of a selected ship (the square's centre when the glyph isn't drawn), with a CSS pulse (`unit-pulse`, 1.1 s), so the canvas isn't redrawn every frame. While choosing a destination the ring is thicker and a dashed magenta rubber band runs from it to the pointer (or the keyboard cursor), under the engine-path preview (blue, dots per turn at the fleet's speed); the pick banner says "it starts at the pink ring". **Off screen** counts the area under the selection panel as off screen (`freeRect`): an edge arrow (pointing at the unit, "Fleet X · n sq") sits on the edge of the free area; clicking it centres the unit there. **Move (click map)** first pans the unit into the free area if needed (`ensureVisible`). `prefers-reduced-motion: reduce`: no pulse, a steady 6 px ring. The ring and arrow clear when the selection ends (Esc, ✕).

**Browser test** `~/mhgc/work/uitest/fleets.py` (fixture `seed_fleets.py`: the all-orders game plus Bob's fleet Raiders next to home), 52 checks, no console errors: tick boxes and Select all; the dialog's default name and five refusals (existing, case variant, a foreign fleet's name, spaces, empty) and the 12-character limit; the draft holds exactly `CF Hunters 50 50`, `AF Hunters 9001 9002 9006`; the forming fleet in the index, its hexagon (canvas pixel) and card; the ring centred on the hexagon and pulsing; Esc clears it; clicking the hexagon selects the fleet; Move: banner, the ring on the start, the magenta rubber band (canvas pixels), `MF Hunters 58 50` after CF and AF, the planned path with its first-turn dot 4 squares out (the frigate's speed); off screen: the edge arrow on the right edge, clicking it brings the fleet back, Move pans first, Esc leaves the draft alone; reduced motion: no animation, 6 px ring; Raiders indexed and drawn in the Zorgs' amber, in the tooltip; Add to fleet gives `AF Alpha 9003` and Alpha shows it joining; zoomed out, one hexagon on the square; Check passes; after the forced turn Hunters exists with the three ships 4 squares east, still bound for 58,50, and 9003 is in Alpha; then a CFXY fleet ("Fleet from ships here") says it can't move this turn and its move toast says next turn. Shots: `~/mhgc/work/shots/fleets-*.png` (12).

## Empty fleets disband; ground forces after a battle (2026-11-16; DECISIONS G-18)

Dave: "a fleet that has lost all its ships disbands automatically" and "after a ground battle, show which troops are left".

- **Engine.** `turn.disband_empty_fleets` at the very end of the turn: a fleet with none of its owner's ships is disbanded as DF would, "Fleet X has no ships left and was disbanded." in its owner's results (`fleet_disbanded`); its name is free; its admiral (if he survived F-07's roll) and a leader travelling to it return to limbo (`leader_evicted`). A CF/CFXY fleet created this turn that has never held a ship is spared that turn with a `fleet_empty` notice, and goes at the end of the next turn if still empty (also a CFXY whose square was empty). Old saves' empty fleets go at their next turn. The bot needed no change (a mission whose fleet is gone is dropped as `mission_lost`). `tests/test_fleet_cleanup.py` (16 tests).
- **Combat log** `ground`: per side `{owner, before, after}` troop counts by type (`Combat.ground_summary`), for the log's participants only, like the rest of the log.
- **Battle card** (`report.js battle`, used by the Report tab and the selection panel): a "Ground forces after the battle" block, one box per side (yours first, marked "you"), a Troops / Before → After table with the losses (−n) and "n → m troops · none left". Old turns' logs without `ground` show no block.
- **Selection panel** (`inspector.js groundNow`): the system card lists "Troops on the ground (after the battle)": yours from the view's own troops (wherever they stand), other races' on your own systems (the view sends all troops there) and elsewhere only from this turn's short range scan; otherwise a hint says other races' troops need a short scan and the battle report lists those in the battle.
- **Classic text** (`legacy_report._ground_after`): `====GROUND FORCES AFTER THE BATTLE====` before END OF THIS COMBAT, one line per side and type, `3 -> 0  (3 lost)`, and "NO TROOPS LEFT ON THE GROUND".
- **Browser test** `~/mhgc/work/uitest/aftermath.py` (fixture `seed_aftermath.py`: the all-orders game, Terrans at war with the Zorgs; fleet Doomed, one scout, beside six Zorg battleships; three Ogres landed on the Zorg colony Outpost against two militia and a shock trooper), 17 checks, no console errors: Doomed on the map, in the index and the panel before the turn, gone from all of them (and its scout) after, with the disband notice in the results and the Report tab; the Outpost battle card's block per side matches the log (Zorgs 3 → 0, none left); the panel's troops on the ground and its battle card; the classic block. Shots `~/mhgc/work/shots/aftermath-*.png` (7).

## Build counts, check warnings, fleets on the Forces tab (2026-11-18; DECISIONS G-19, G-20, W-27)

- **Forces** (`panels.js renderForces`): Ships lists loose ships only ("Ships (5 loose)"), with "Include ships in fleets" (pref `filter.ships.inFleets`, off by default) adding a Fleet column; Fleets lists own and forming fleets with a ship count and a composition column, and ▸ opens each fleet's ships in a nested sortable table with the ship columns (`dataTable` got a `detail` option for full-width rows under a row, and `counter`). Open fleets are kept in pref `forces.openFleets`; "Show all ships" / "Collapse all". Membership follows the draft via `world.js effectiveFleet`. Ship rows (nested too) select the ship.
- **BS / BCU count**: a number box (default 1) in the order form, and under it the total cost and the starport room left (`orders.js buildSummary`); `classicText` leaves a count of 1 out, as the server does.
- **Warnings** (`orders.js`): after every draft change the draft is checked quietly (`scheduleAdvice`, 250 ms debounce, keyed on the draft text) and `S.advice` drawn under each order as an amber ⚠ line, with a **Fix: Use <name>** button for renames (rewrites the order, then rechecks if Check results were showing). The top bar's Check button and the Orders tab's show "⚠ n"; the Check toast mentions them; Submit is never blocked.
- **Cargo warnings amended (2026-11-18, G-20 (a)):** the general "loads at X before it moves" warning is gone (an ordinary move only sets a destination; the load works where the unit is). Now: `warp_cargo` ⚠ for a cargo order after a WTP/WTPF of the same unit ("Ship 9003 loads at Colony (after the warp in order 1), not at Home."), with **Fix: Move it before order 1** (`fix.move_to`; `applyFix` moves the order instead of rewriting it, title "Move this order to position 1"); a failed cargo order after a warp gets an error naming the warp, and the check result row carries the same move Fix (`results[i].fix`), drawn as a button under the ✗ line (`.chk.err button.fix`); errors for a unit still in transit say where it is and when it arrives; `move_cargo` now only for cargo unloaded where this draft loaded it, on a unit that moves.
- Browser test `~/mhgc/work/uitest/buildcount.py` (39 checks, own server, seed_fleets fixture; section 3 is now: ordinary move+load silent, WTP+L ⚠ and its Fix, WTP+LOCT ✗ with the warp named and its Fix). Screenshots `~/mhgc/work/shots/buildcount-01..10-*.png` (07 `warp-load-warning`, 08 `warp-troop-error`).


## The split Tweak (2026-11-18; DECISIONS G-21)

Dave: a "tweak" button that moves the percentages by up to 3 points to maximise production (output is truncated to whole units, so shares that land just above whole numbers waste less).

- **Engine:** `economy.SplitContext`, `make_split_context` (the one pure builder; `system_production` uses it, results unchanged: seed 1's 70-turn bot game replays byte-identical), `split_context(ctx, s)`, `split_output(sc, split)`, `valid_split`, and `tweak_split(sc, split, max_delta=3)` → `{split, before, after, gain, moved, optimal}`. Exhaustive within ±3 of each share; no resource may go down; most total units, then fewest points moved, then lowest (AU, IU); the current split wins ties. Nothing to gain once production before the split is ≥ 100.
- **API:** `POST /api/games/{gid}/production/tweak` `{overrides, systems?, max_delta: 0-5 (default 3)}` → `{turn, max_delta, gain, systems: [{id, name, split, suggestion, before, after, gain, moved, optimal, changes: [{key, from, to, out_from, out_to}]}]}`. `engine/preview.production_tweak` runs on the preview's own-only copy after the draft's own orders (the preview's step 1 is now `_prepare`, shared). Seat only, 422 for systems or overrides that aren't yours (the preview's message), nothing stored. Host View as: `/as/{eid}/production/tweak` (read-only; `core.js` rewrites it like the preview).
- **Production tab** (`production.js`): a **±** button per row (tooltip explains it) and **± Tweak all** between "Set all to…" and "Reset all". The suggestion is applied as typing (row changed and highlighted, live preview, counted by Generate CSP orders). A note under the split, `#sptweak-<id>`: "+2 units: AU 19→21" (split and outputs on hover) or "Already optimal"; typing, a preset, ↺ or Reset all clears it. An invalid row isn't sent: "Not tweaked: fix the split first" and an error toast. Toasts: per row "Z111: +2 units: AU 19→21. Generate CSP orders…"; Tweak all "+N units on k systems; m already optimal; j skipped". CSS `.tbl.prod .tweak`, `.tweak-note(.gain)`.
- **Tests:** `tests/test_split_tweak.py` (11): the textbook case (42.2 production: 23% → 9 AU, 24% → 10), exhaustive against an independent brute force on 600 random systems and splits (never lowers, 10-80, total 100, ±d), limits and invalid splits, multipliers change the answer, `production_tweak` = the preview's numbers before and after (happiness and feeding never lower, uses the draft's BI/BT/CSP), depends on nothing hidden, the endpoint own-only / validating / not mutating, then Generate-style CSP → Check passes → the preview's base is the suggestion → tweaking again is optimal; the bot (below). Browser `~/mhgc/work/uitest/tweak.py` (port 8800, 22 checks; added to `run_all.sh` after production): buttons and tooltips, an invalid row, an optimal row, Tweak on a row (boxes, note, toast, live AU/IU/EU = the promised outputs, Generate count), typing clears the note, Reset all + Tweak all, Generate writes the tweaked CSP, Check passes, no console errors. Screenshots `~/mhgc/work/shots/tweak-01-buttons.png`, `tweak-02-invalid.png`, `tweak-03-tweak-row.png`, `tweak-03b-row-closeup.png`, `tweak-04-tweak-all.png`, `tweak-05-orders.png`.

## Ship picker groups, AOMT and the host handicap (2026-11-19; DECISIONS G-22, W-28, W-29)

- **Build ship picker** (`orders.js`, the BS branch): one optgroup per rules group from `/api/reference` (`ship_groups`, ships in `SHIP_ORDER` with `group`/`group_label`): "Scouts (3 of 3 available)", "Transports", "Standard line", "Offensive line", "Defensive line", "Fast line"; within a group by the required tech's price, then cost. Classes still needing a technology stay in their place, greyed (`option.locked`) with " - needs <tech>" (chosen over "buildable first" so a group reads as a progression; the header gives the count). BCU keeps Available / Needs a technology. The **Forces** type filter uses the same optgroups. `all_orders.py` picks types by value, so nothing there depended on position.
- **AOMT** (Empire tab, `panels.js renderEmpire`): an "AOMT on/off" tile and the checkbox **Autogenerate orders on missed turn (AOMT)** (`#aomtToggle`, `#aomtRow`) with a one-line explanation; it calls `POST /aomt` at once (no order; disabled when you can't give orders, e.g. View as or history) and toasts. The Report tab shows `#aomtNotice` "Orders generated automatically. You missed turn N; …" (or, since 2026-11-20, "Your draft was run. …" when the event's `source` is "draft", W-30) at the top when the report has an `aomt` event; the checkbox is ticked unless the view says `aomt: false` (on by default since 2026-11-20, W-30) and its hint explains both cases; the generated orders are the order results (each with the bot's `# note`). The order `AOMT ON|OFF` is in the order picker (Empire and diplomacy) with help; `all_orders.py` covers it.
- **Host handicap** (`panels.js hostHandicapNote`, class `.notice.handicap`): on the Empire tab and at the top of the Report tab of the host's race while the summary says `host_handicap` ("As host of a multi-player game your race can't win and earns no ranking VP…"). When the turn's stats are unranked: Report statistics "Victory points: N (host, unranked)…" (`#unrankedNote`) with "–" ranks, the VP chip "N/–" (title explains), the Empire VP tile "N (host, unranked)"; Final standings list it after the ranked races, rank "–", "(host, unranked)".
- **Browser script** `~/mhgc/work/uitest/aomt.py` (30 checks; fixture seed_fleets.py, Dave host + Bob): picker groups and order, locked marks, Forces filter groups, the host's Empire notice, Bob switches AOMT on and leaves an unsubmitted draft, Dave forces, Bob's report has the notice and the generated orders (all ok, draft unused, no diplomacy codes), nothing in Dave's report, Dave's unranked statistics and VP chip, Bob ranked, AOMT off again, the audit and bot-log lines. Screenshots `~/mhgc/work/shots/aomt-01..06-*.png`. Added to `run_all.sh`.

