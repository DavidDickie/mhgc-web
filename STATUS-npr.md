# MHGC web: stage 4, the computer empires (NPRs), 2026-11-12

## Direction

Stage 4 began as a port of the C AI (gcnpr.c / gcnprutils.c). Part way through, Dave changed course: "don't use the C code for the bots, or the cheats. Make a better playing bot." The port was dropped (a copy is kept outside the project, not in the tree). This stage delivers:

- A new bot designed from the rules (`mhgc/npr/`).
- No NPR advantages in the engine (DECISIONS A-01).
- No hidden information: the bot decides only from the player read model (A-02).
- A strength harness that plays the bot against a baseline bot and against itself.

The C code was read only to learn how the game works. None of its strategy or state machine is reused.

## Run

```
~/mhgc/venv/bin/python -m pytest -q -p no:cacheprovider     # 569 tests (2026-11-20), about 170 s
~/mhgc/venv/bin/python -m mhgc.npr.sim npr 1 0 60           # normal game: 16 NPRs, 60 turns
~/mhgc/venv/bin/python -m mhgc.npr.sim npr 2 1 60 random    # 1 random human
~/mhgc/venv/bin/python -m mhgc.npr.sim match 1 100 mix      # 8 bots vs 8 baselines, player seats
~/mhgc/venv/bin/python -m mhgc.npr.sim match 1 110 self     # 16 bots
~/mhgc/venv/bin/python -m mhgc.npr.sim npr 1 1 50 random 8  # an 8-empire game on 75x75 (sizes 4/8/9/12/16)
~/mhgc/venv/bin/python -m mhgc.npr.sim match 1 80 mix 12    # a 12-seat match
```

## Engine changes (DECISIONS A-01 to A-04)

**Computer empires play under exactly the human rules.** These NPR advantages were removed:

| Advantage | Where it was |
|---|---|
| +3 scan range | `engine/scans.py` |
| Leaderless small-system production bonus | `engine/economy.leader_factors` |
| ISNPR income | `turn.run_orders` |
| Ship and CT maintenance discounts | `maintenance.py` |
| 0.7x tech price | `orders_exec._buy_tech` |
| 10000 EU cap | `turn.cleanup` |
| Majority-tech grant | `economy.npr_tech_grant`, deleted |
| Exemption from rebellion | `economy.happiness` |
| SS/SCT starport-capacity exemption | `orders_exec` |

The matching constants are gone. The affected tests now assert the human rule (`test_c_behaviour`, `test_economy`, `test_maintenance_movement`, `test_orders_exec`, `test_spies_events_stats`). `docs/RULEBOOK.md`'s NPR section now says NPRs don't cheat. DECISIONS §2 #8, #17, #36 and #37 are marked superseded.

**Other engine and model changes:**

- `GameState.npr_state`: per-empire bot memory, plain JSON with string keys. A save/load round trip is exact. `view.py` never shows it.
- `turn.run_turn` calls `npr.observe_turn(state, results)` at the end of each turn. This stores each NPR's own report as its "inbox".
- `initial_results` does the same for turn 0.
- Nothing else in `engine/` changed. `app/` and `STATUS.md` were not touched.

**Flagged for Dave (A-04), kept as they are:**

- NPRs are still excluded from rankings and stat-bonus VP, and cannot win (rules:238-239). That was a balance rule for weak, cheating bots, so it may be worth revisiting.
- RESIGN's one-off "autobuff" for dropped players is kept.
- TTNPR stays.

## The bot (`mhgc/npr/`, about 2,100 lines)

### What it sees

`npr_orders(state, eid)` builds `view(state, inbox, eid)`, the same JSON a human's browser gets, then calls `bot_orders(view, memory, rng)`.

- `world.py` turns the view into the bot's picture, in relative coordinates.
- Memory adds what the empire saw earlier: short-scan intel on systems, scouted cells, race standings, observed enemy fleet make-up, missions and a history log.
- `tests/test_npr_units.py::test_bot_orders_depend_only_on_what_the_empire_can_see` proves it uses nothing else. It scrambles, for six NPRs:
  - every other empire's money, techs, stances, memory, leaders, spies and ships;
  - every foreign troop not on the NPR's own worlds;
  - every foreign system's contents and owner.

  The orders and the memory written are byte-identical.
- `bot_orders` works for any seat; the harness plays it in player seats.

### Budget (`plan.py`)

Every order is charged against one budget that mirrors the engine's checks:

- EUs and per-system IUs;
- starport capacity (BS 1, BCU 0.5), and a starport change blocking further builds;
- 2x costs under attack, and interdiction;
- one PT a turn, the militia limit and cargo space.

### Strategy (`brain.py`; spending priority in this order)

1. **Learning and diplomacy** (`diplo.py`), from its own report.
   - **Grievance** builds from:
     - surprise attacks: 25 near home, 8 when it was the one wandering;
     - fights at its systems;
     - ships and troops lost;
     - systems lost (50);
     - spies caught.
   - **Goodwill** builds from gifts, peaceful neighbours, and MESSAGEs asking for peace or alliance. Grudges fade at a per-personality rate.
   - **Warnings:** loitering warships get a warning in Dave's words ("We claim all space within N squares of our systems!"). Staying after the warning counts against their owner.
   - **War** follows a grievance threshold. It is never declared on itself or on the rebels.
   - **Peace** comes when overmatched (enemy warships seen near us outweigh ours by 1.5x), when losing systems, when the war has gone quiet, or when asked. The EWA offer repeats for 3 turns with a MESSAGE, because peace needs both sides' EWA in the same turn.
   - **Alliances** go to races in good standing, never the leader. The leader is the race holding the most systems we know of, well ahead of us. The bar for alliances is halved when such a leader exists.
2. **Arrivals:** colonists land on empty worlds (U P claims them) and cargo is delivered.
3. **War missions** (`war.py`). One at a time, with concentration of force:
   - **Targets:** systems of races at war with us, rebel worlds, or (for aggressive and opportunist bots, after turn 15) a disliked neighbour that recent intel shows is weak.
   - **Gathering:** at a staging system, the bot collects free warships within 3 turns, transports and attack troops. It builds missing ships of the line type it lacks.
   - **Timing:** it launches only when `evalcombat.assault` gives at least the personality's capture chance (0.6, 0.7 or 0.85). That function runs **the engine's own `combat.Combat`** for 8 trials on a synthetic state built from the bot's *estimate*: our ships and the troops to be landed, against the enemy ships scanned at the target, the troops and system weapons from short-scan intel, and the population.
   - **Launch:** LOCT, CF, AF, CFCR OF, CFP AH, MFS.
   - **Assault:** on arrival it lands with LACT. It withdraws if the fleet is beaten, and gives up gathering after 16 turns.
4. **Defence:**
   - **Threat:** foreign warships within 2 turns of each system, weighted by relations; troop carriers count too.
   - **Garrison:** max(1.4x threat, a floor that grows with the turn), built where needed.
   - **Composition:** ship choice weighs attack against defence by the enemy's observed make-up. It favours the line type we're short of, for the Mixed Fleet Bonus (x3 with all four lines; the evaluator confirms mixed fleets beat mono fleets).
   - **Ground troops:** dug-in infantry, with more when carriers are near.
   - **Movement:** surplus warships reinforce the neediest systems, and stragglers go home.
   - **Upkeep:** warship upkeep is capped at a personality share of income (x1.5 at war).
   - **Intercepts:** enemy ships within 8 squares are intercepted only when `evalcombat.fleet_vs_fleet` (the engine again) says we win.
5. **Research** (`econ.py`). One PT a turn, chosen by value per cost:
   - victory points (weighted by personality greed, doubled from 60 VP);
   - economy techs;
   - new ship line types and better ships;
   - defences when threatened;
   - what a tech unlocks.

   Crash research is used for VP when rich. Future Tech comes once everything else is owned.
6. **Development** (`econ.py`):
   - infrastructure up to population (it doubles production);
   - CGR 150;
   - EUS at the 10-pop cap;
   - production artifacts (CB/VRB, CM/AL, BF/AF, EHC/CS) where they pay back in 12 turns;
   - bigger starports where production pays for them.
7. **Expansion** (`expand.py`):
   - **Scouts** sweep a 10x10 grid of cells, nearest first, and visit worlds known only from long-range scans, because only a short scan shows habitability.
   - **Settlers** take 1-2 colonists and 40 IU to the best world by (habitability, MR/AR, artifacts) per turn of travel. Unknown worlds are assumed average.
   - **Transports** are built while there are targets. Idle ones carry people from full systems to roomy ones, and IUs from rich systems to poor ones.
8. **Spies:** with Biomodification, up to 2 spies go to war targets with stale intel and run SOS (short-scan intel).
9. **Leaders:** good managers become governors of the biggest systems, and a good fighter becomes admiral of the war fleet.
10. **Profiles:** CSP comes from the inverse of the rules' happiness formula. Each system eats enough AU for happiness 0.8 while growing (growth needs more than 0.5), and 0.65 once capped. The rest goes to IU or EU by the system's multipliers and the empire's EU need.
11. **Postures:** unarmed ships are Friendly.

### Personalities (`memory.py`)

There are three: **aggressive**, **builder** and **opportunist**. Each sets aggression (upkeep share), the capture chance needed to attack, VP greed, claim radius, forgiveness, and the war and alliance thresholds. They are assigned in rotation by empire id from a per-game offset, so each one appears 5-6 times in 16 seats.

### The baseline bot (`baseline.py`)

Greedy expansion and random builds, also from the view only:

- random cheap research;
- infrastructure;
- a random unit at each system now and then;
- every idle transport takes a colonist to the nearest empty world;
- scouts and some warships wander.

## Results

### Strength harness

All seats are player seats, so VP and the 100-VP victory count. Bots and baselines decide from their own views. Engine seconds per turn is for 16 empires.

| Match | Ends | Winner | Mean VP, bot vs baseline (final) | Systems, bots vs baselines | Rejections, bot | Engine s/turn mean (max) |
|---|---|---|---|---|---|---|
| mix seed 1 | t77 | bot (opportunist), 101 VP | 54.6 vs 18.2 | 106 vs 70 | 0.08% | 0.14 (0.30) |
| mix seed 2 | t84 | bot (builder), 105 | 57.8 vs 21.4 | 92 vs 83 | 0.08% | 0.21 (0.40) |
| mix seed 3 | t77 | bot (builder), 103 | 60.9 vs 20.6 | 95 vs 80 | 0.01% | 0.12 (0.27) |
| mix seed 4 | t90 | bot (builder), 103 | 79.0 vs 18.2 | 104 vs 70 | 0.03% | 0.21 (0.64) |
| self seed 1 | t98 | aggressive, 103 | mean 79.5 | all 176 held | 0.04% | 0.20 (0.39) |
| self seed 3 | t79 | builder, 100 | mean 60.8 | 175 held | 0.06% | 0.14 (0.34) |
| baselines only, seed 1 | t100 | nobody | mean 23.6 (best 38) | 175 held | (0.75%) | 0.18 (0.35) |

- **Win rate against the baseline: 4/4.** In every mixed match the bots also took at least 7 of the top 8 places.
- **VP curves.** Mean VP every 10 turns, mixed seed 4:
  - bot: 9, 20, 24, 25, 29, 35, 43, 55, 67, 79;
  - baseline: 15, 15, 17, 19, 20, 20, 20, 19, 19, 18.

  The baseline flattens out around turn 40. The bot keeps climbing on technology VP and systems.
- **Personalities.** Builders won 4 of the 6 decided games, an opportunist and an aggressive bot one each.

### Normal games (NPR seats run by `run_turn`)

The bot time is included in the seconds per turn.

| Game | NPR orders | Rejected | NPR systems t1 -> end | Mean NPR VP | s/turn mean (max) |
|---|---|---|---|---|---|
| seed 1, 0 humans, 60 turns | 10,585 | 4 (0.04%) | 16 -> 175 | 2 -> 39 | 0.14 (0.33) |
| seed 2, 1 random human, 60 | 11,247 | 3 (0.03%) | 15 -> 176 | 2 -> 37 | 0.14 (0.24) |
| seed 3, 2 idle humans, 45 | 7,869 | 2 (0.03%) | 14 -> 170 | 2 -> 33 | 0.08 (0.17) |

- **Activity across the three games:** 478 colonies, 15 captures, 51 missions, 32 wars, 20 peaces, 90 alliances, 53 warnings, 567 engine combat evaluations.
- **Every rejection is unforeseeable.** The bot plans before any order runs, and empires' orders run in random order. So:
  - another race may settle the same empty world first (`U`: "use UG");
  - another race may declare war first, so our DW or DA fails;
  - a ship we meant to intercept may be consumed by its owner first (CTT/SS/DS).

  The tests allow only these, below 0.3%.
- **Order mix** (seed 1): CSP 2997, MS 1573, BI 1439, BS 798, BT 751, BCU 501, PT 499, BSP 367, MO 321, L 321, U 321, CGR 175, ML 123, I 71, MESSAGE 59, EWA 56, DA 43, SMV 34, SOS 25, LOCT 14, DW 13.
- **Turn time** is now far below the C-port's 0.5-1.3 s. Real maintenance keeps fleets near 30-50 ships per empire, against about 100 before.

## Tests

### `tests/test_npr_units.py` (13)

- **No hidden information:** the scramble test above.
- **Only memory changes:** planning mutates nothing but the bot's own memory, and its orders validate in a real game.
- **Profiles** add up to 100 with every share at least 10, and feed unhappy systems.
- **Research:** one PT a turn, preferring a new line type when threatened.
- **Development** builds infrastructure and growth.
- **Budget:** capacity, starport blocking and the 2x cost under attack.
- **Engine combat evaluation** separates strong from hopeless assaults, and mixed fleets do at least as well as mono fleets.
- **Ship choice** fills the missing line.
- **Diplomacy:**
  - a surprise attack becomes a grievance, then war, with no self-war or war on the rebels;
  - a bot that is overmatched offers peace;
  - alliances go to races in good standing but not to the leader.
- **Settlers** load, go and settle, with every order validated.
- `bot_orders` works for a player seat.

### `tests/test_npr_sim.py` (16)

- **The three normal games above:**
  - rejection rate below 0.3%, and only the explained kinds;
  - no order-construction bugs;
  - expansion curves;
  - fleets grow;
  - the order mix covers the main codes;
  - warnings, missions and engine evaluations happen;
  - turn time (mean below 1 s).
- **Across the three games:** at least 2 wars, at least 2 captures and at least 1 peace.
- **Bot beats the baseline:** in a mixed match, VP above 1.5x, more systems, and at least 3 of the top 4 places.
- **Determinism:** each seed gives the same game, and a save/load mid-game continues identically.
- **Defence scenario:** a hostile squadron parks at a bot's home. The bot builds defences there, intercepts, destroys the squadron and declares war. It counter-attacks only systems it knows of; otherwise it offers peace once the war goes quiet (fair information).

## Gaps and notes

- **Bigger saves.** A turn's `state.json` is about 560 KB at turn 50, of which about 210 KB is bot memory: intel on every system it has seen (per NPR), plus the inbox, about 70 KB. Intel could be pruned.
- **Not used:** gifts (GT, GE), tech trades with *players* (bot-to-bot TTNPR since 2026-11-15), DCT trade routes, warp tunnels and farcasters, assassination spies (SAL/SOL: whether a governor is there can't be known safely), SL, or fleet admirals beyond the first war fleet.
- **War fleets:** one before the aggression ramp, up to 3/2/1 after it (2026-11-15). There are no combined operations with allies, and no deliberate timing against an enemy fleet that is away.
- ~~**It is not told about NPRs.** NPRs can't win (A-04)~~: since A-06 (2026-11-15) every race is ranked and computer empires can win, so normal games count too.
- **Messages to bots are read for keywords only** (peace, alliance). There is no richer negotiation. Chat to computer empires is still refused by the app (W-07).
- **Turn 1 of a normal game:** an NPR without an `initial_results` inbox plans from its own objects only. The app does call `initial_results`.
- **The C comparison** asked for in the original brief became moot with Dave's change. The early C-port did match the C's order mix from `c-ref` (demo turn 13: CSCR, CSP, DA, MO, EWA, BI, CGR ...). The new bot's mix differs by design (no DA spam, no EWA-to-intercept, no cheat orders).
- `app/main.py` and `app/ui/` were not touched. When stage 4 began, `tests/test_api_ui.py` (the UI agent's) had 2 failures; they pass now.

## 2026-11-13: game sizes, system names and chat boasts (DECISIONS W-13, W-14)

### Any board size

The bot reads the board side from its view (`game.board`) and keeps it in a context variable for `world.dist` (so concurrent server threads running games of different sizes don't interfere). Its home is `world.home_xy()` (the board centre), and the scout grid has about 10 squares a cell (10x10 cells at 100, 8x8 at 75). `sim.simulate(..., size=)` and `sim.match(..., size=)` play any size. Nothing else in the strategy depended on the board.

| Size | Seed, humans, 40 turns | NPR orders | Rejected | s/turn mean (max) |
|---|---|---|---|---|
| 8 | 11, 1 random | 3,546 | 0 (0.00%) | 0.026 (0.050) |
| 9 | 12, none | 4,858 | 6 (0.12%) | 0.041 (0.075) |
| 12 | 13, 2 random | 5,596 | 5 (0.09%) | 0.065 (0.199) |
| 16 | 14, 1 random | 7,700 | 6 (0.08%) | 0.093 (0.195) |

All rejections are the known unforeseeable kinds (`tests/test_sizes.py::test_bot_games_at_every_size` checks them, expansion, fleets and time at every size).

### Naming systems (`naming.py`, `data/system_names.py`)

The last step of `decide`: each owned system with a generated name (capital + three digits) gets a themed name by NSY, one a turn, two when four or more wait. The NSY orders go last, so no earlier order of the same turn uses the old name. Names: 20 per default race (Porkines: Hamburgia, Sty_Prime, Truffleton, Boarzilla; Groachi: Scuttleton, Grumblehive, Unsquished; Barnacle_Boys: Hullhugger, Scuttlebutt, Keelhaul; Grunts: Fort_Sarge, Latrine_Dig, Hup_Two; Hopeless: Why_Bother, Gloomhaven, Meh, Oh_Well; Ratfinks: Snitchville, Double_Cross, Stoolpigeon ...), and 32 per personality for other race names (aggressive Doomspire, Skullcrag, Thunderdome; builder Smugsworth, Picket_Fence, Our_Best_One; opportunist Loophole, Fine_Print, Rugpull), 416 in all, all distinct; then _II.._X variants, then numbered names. Shuffled once per game (memory `names`). Never a name it can see on any system, used before, or refused before. Proper home names are kept. In the 40-turn games above, 90-161 renames and not one refused; over 90% of bot-held systems carry names by the end.

Engine support: `orders_exec._known_system` also accepts the name in the orderer's own map memory, so MS/MFS/SMV orders to a renamed system still work by the old name (for players and bots alike).

### Boasts (`chatter.py`)

`observe_turn` calls `turn_chat(state, results)` after storing each NPR's inbox: per NPR, `boasts(view, memory, rng)` on the same read model the bot plays from; `select` applies the limits; the result is `TurnResults.chat`, which the app posts. Memory: `brag` (last stats, techs, stances, battles fought per race, announced wars and alliances, VP milestones said, last turn per kind). The kinds, rules, thresholds and limits are in the module docstring and DECISIONS W-14. Summary:

- **Kinds by priority:** capture 90 (reclaim from rebels 88), VP milestones 85-88, war 80, peace 78, alliance 75, number 1 in a stat 70 (player seats only), battle 65, technology 60 (1000-EU techs 40; Future Tech 62), first contact 50, settled 30, turn-on-turn gain 20.
- **Own knowledge only:** the no-leak test scrambles everything the bot can't see (as for orders) and checks boasts and `brag` are identical. War is announced only after a battle with that race since the war began; peace only after the mutual EWA; alliances only with a race that asked. Number 1 in a stat never fires for NPRs (not ranked, rules:238-239; nobody sees others' stats).
- **No private numbers:** no coordinates, fleets or other empires' numbers; own figures only as VP milestones or whole percentages (gains from turn 5, with minimum bases and absolute gains; never the EU stockpile itself).
- **Limits:** one per bot per turn, 4 a turn game-wide (normal) or 2 with priority 60+ (quiet), none (off); settle, gain, contact and battle at most every 3 turns per bot. The setting doesn't change play (tested: normal and off play byte-identical games apart from `brag`).
- **Style:** race names in capitals; 2-3 templates per kind per personality (aggressive taunts, builder smug, opportunist sly), from `Rng(seed, turn, "chat<id>")`.
- **Volume:** 70 turns gave 269 messages (16 empires: battles 55, contacts 46, settled 34, techs 36, peace 28, war 25, VP 20, gains 14, captures 11) and 225 (8 empires). Alliances are rare because bots seldom ask each other; they appear when a player asks a bot by MESSAGE and the bot accepts.

Sample (70-turn games, size 16 seed 2 and size 8 seed 5):

```
T 3 Grunts        [settle]  One more rock for the GRUNTS. Next time we take one with people on it.
T 6 Boviners      [contact] The BOVINERS have met the MANGOS. They look breakable.
T12 Mangos        [battle]  The GOOGLY EYES picked a fight with the MANGOS and lost. Shame.
T13 Badhombres    [improve] A 21% jump: the BADHOMBRES are more productive. Steady growth, as planned.
T16 Gollywogs     [vp]      The GOLLYWOGS hit 25 victory points. The universe should take notes.
T18 Hopeless      [capture] The HOPELESS have TAKEN a system from the HALDERMEN! Who's next?
T20 Haldermen     [peace]   The HALDERMEN have made peace with the HOPELESS. For now.
T22 Haldermen     [capture] Oops! A HOPELESS system seems to belong to the HALDERMEN now.
T29 Groachi       [improve] The GROACHI are 33% richer this turn than last turn. Good management.
T37 Gollywogs     [tech]    Improved Weapons II! The GOLLYWOGS armoury grows.
T11 Freepeople    [war]     Attention HUMAN1: the FREEPEOPLE accept your surrender at any time.
T22 Haldermen     [war]     The HALDERMEN are at war with the PORKINES. We did warn them, politely.
T27 Freepeople    [capture] The FREEPEOPLE have conquered another system! Its old owners can come and complain.
```

Tests: `tests/test_npr_chatter.py` (20).

## 2026-11-15: rank everyone, spies, starports, aggression ramp, bot-to-bot trades (DECISIONS A-06, A-07)

Dave's brief after his exported game (seed 740601768, 16 empires, one human, turn 27; `~/mhgc/work/analysis/087fd598`).

### What changed

1. **Everyone is ranked (A-06).** `engine/stats.py` ranks every live race and gives all of them the stat-bonus VP; `check_victory` lets a computer empire win. Each empire still sees only its own ranks. The "number 1" boast now fires for computer empires (own ranks, figure above zero, from turn 5). `analyze_game.py` says which rule an export used. RULEBOOK VICTORY/NPRs/TURN RESULTS and the two UI hints (`report.js`, `graphs.js`) updated. Tests that assumed human-only ranks now assert the new rule (`test_spies_events_stats`, `test_analysis` export/final: the NNP tie-break may crown a bot).
2. **Spies** (`npr/spycraft.py`): BT S with Biomodification, up to 3/4/2 spies (aggressive/opportunist/builder; one before the ramp unless at war) within a `spy_share` of EU income (5/8/3%). Missions from its own view: SOS on war-fleet targets with intel older than 2 turns, SOS/SUP (SSB for aggressive where artifacts are known) on races at war, SOS on stale neighbours (conquest prospects), SOT on computer empires every 20 turns (the report is parsed into memory). CI 1-2 points on systems where an enemy spy was caught or that a race at war threatens. No steal-tech mission exists in the rules; SAL/SOL are not used (a governor's presence can't be known safely).
3. **Starports** (`econ.development`): while infrastructure, a paying artifact or the tech it is saving for (best value per cost, out of reach this turn, within two turns' income) is pending, a starport grows only where its own builds ran out of capacity in the last 3 turns, to class 4 at threatened systems and the main shipyards (home, war-fleet stages), and to class 3 on the frontier after the ramp; otherwise the old 15-turn payback (25 for those systems). Early (turn <= 30) starport share of spending: 19-20% -> 11-12%.
4. **Aggression ramps with technology** (`war.py`, `econ.ramped`, `memory.WAR_STYLE`): see "Root cause" and A-07. Gate: a warship tech of the LightCruiser's cost (tech 18 High Energy Physics, 500 EU; Guardian/Mauler too); builders need the 1000-EU tier or turn 50. Before: upkeep share x0.8, wars only when at war, rebels, or a 90%+ easy prey close by. After: 3/2/1 fleets, capture odds 0.55/0.62/0.72, conquest declared by DW at launch, peace sooner once no fleet is engaged against that race.
5. **Tech trades, bot-to-bot** (`npr/trade.py`): MESSAGE handshake (offer, accept, TTNPR the next turn), even swaps only (always accepted by the engine), never with the leader, a threatening race, or one that ignored two offers; the acceptor keeps half the cost in hand and buys no tech that turn. `swap_for`/`offer_terms` are pure and reusable for human-facing offers (not built). 2-8 trades per 80-turn game, no TTNPR rejections.
6. Smaller: crash research when EU piles up beyond a PT (rarely fires: late techs cost 3000-4000); assault troops chosen by attack per cost including transport space; returning fleets unload troops at home; two fleets can't load the same troop.

### Root cause of the idle militaries

Instrumented replays of the old bot (2 games, 16 empires, 60 turns, 960 bot-turns):

- **Any foreign warship blocked every new mission.** `plan_missions` returned if *any* system had threat > 0, and neutral ships count at weight 0.35: 231-246 of ~700 well-armed bot-turns were blocked this way.
- **One mission at a time, and it got stuck.** 221-274 armed bot-turns were spent inside the single mission, often in "build" state against a target estimated at 0-25% for up to 16 turns (Badhombres in Dave's game: est 0.0-0.25 from T20 to T27).
- **No candidates** for 80-117 armed bot-turns: builders never conquered; others needed standing < 6/2 and short-scan intel under 15 turns old (nothing refreshed it: no spies).
- **Slow fleets.** War fleets were mostly Patrollers (move 2): in Dave's game Blutos' and Groachi's fleets (11-13 PA) launched on turn 22 and only reached their targets on turn 27.
- **Landings failed.** Of 10/17 launches, 3/10 captured. Fleets launched with as few as 2-3 Shock troops on stale intel; when the transports appeared the defender dug in 2 troops a starport class a turn, and the landing died (`aboard 0, landed 0` at the target). The estimate ignored that reaction.

Fixed by: pressure test on hostile/grudge warships vs half our attack; several fleets after the ramp; hopeless targets set aside 8-10 turns (the race for conquests); slow ships kept off long trips; the defender's reaction and intel age in the estimate; launch only fully loaded, troops +3 when space is won; land only on a fresh estimate at the target, otherwise withdraw; spies refresh mission intel; warships built for a fleet only while space isn't won, troops only once it looks winnable.

### Measurements (`tools/bot_games.py`; runs in `~/mhgc/work/runs/{before,after,h2h,h2h120,*-dave}`)

`before` = the bot and engine as of this morning (snapshot `~/mhgc/work/bot-before`); NPR VP in "before" have no stat bonus. 80 turns, seeds 1-3, means of 3. s/turn with 12 games in parallel.

| Set | Captures/game | Fleets launched | Wars | Spy orders | Trades | Starports % (T<=30) | Ships % | Bot NNP | Bot VP | Won | Rejected | s/turn |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 8 bots, before | 3.7 | 5.7 | 20 | 79 | 0 | 5.4 (19.0) | 11 | 4135 | 56.2 | 0 | 0.06% | 0.07 |
| 8 bots, after | 14.3 | 20.3 | 48 | 651 | 1.7 | 5.9 (10.9) | 35 | 3136 | 47.2 | 0 | 0.06% | 0.11 |
| 16 bots, before | 6.7 | 10.7 | 43 | 159 | 0 | 5.7 (20.0) | 15 | 4046 | 51.5 | 0 | 0.04% | 0.23 |
| 16 bots, after | 23.3 | 40.0 | 91 | 1203 | 2.7 | 6.3 (11.5) | 32 | 3093 | 42.9 | 0 | 0.07% | 0.29 |
| 8, baseline human, before | 9.0 | 10.0 | 15 | 97 | 0 | 5.6 (19.0) | 16 | 3808 | 52.7 | 0 | 0.05% | 0.07 |
| 8, baseline human, after | 17.7 | 21.0 | 44 | 517 | 1.0 | 6.1 (12.0) | 31 | 3010 | 47.1 | 1 (bot T76) | 0.05% | 0.10 |
| 16, baseline human, before | 9.0 | 12.7 | 36 | 127 | 0 | 5.5 (19.5) | 14 | 4146 | 52.8 | 0 | 0.05% | 0.21 |
| 16, baseline human, after | 23.7 | 36.3 | 75 | 926 | 1.3 | 6.0 (12.1) | 28 | 3058 | 42.3 | 2 (bots T71, T74) | 0.05% | 0.26 |

Mean bot curve, 16 bots seed 1 (systems/NNP/VP every 20 turns): before T20 9.3/754/19, T40 10.7/1387/25, T60 10.9/2588/38, T80 11.0/3886/52; after T20 9.4/717/22, T40 10.8/1370/28, T60 10.9/2167/35, T80 11.0/2993/43. Wars cost: more fighting means a quarter less NNP when every seat fights.

**Head to head** (every seat a computer empire; even seats new and odd old, then swapped; seeds 1-3; per empire):

| Size, turns | New VP | Old VP | New systems | Old systems | New captures | Old captures | Top-4 new/old | Wins new/old |
|---|---|---|---|---|---|---|---|---|
| 8, 80 | 51.3 | 51.9 | 12.9 | 11.7 | 2.1 | 0.5 | 54% / 46% | - |
| 16, 80 | 49.4 | 49.1 | 11.7 | 10.2 | 1.6 | 0.5 | 21% / 29% | 1 / 0 |
| 8, to the end (130) | 60.1 | 57.5 | 13.1 | 11.5 | 2.5 | 0.5 | 58% / 42% | 3 / 3 |
| 16, to the end (130) | 54.6 | 54.6 | 11.8 | 10.1 | 1.8 | 0.5 | 19% / 31% | 2 / 4 |

The new bot takes more systems everywhere, but converts it into VP only at 8 empires; at 16 it is level on VP and wins fewer games (old opportunists won seed 1 in both seatings). Tried and not better (6-12 games each, all within +-2 VP): lower upkeep shares, fewer fleets, fewer spies/no CI, smaller garrisons, no starport holdback, conquest only at 85%, conquest only against the leader. The cost is research: the war upkeep and garrisons leave about 20% less EU for technologies.

**Against the baseline** (`sim match 5 60 mix`, player seats): bot 35.6 VP vs baseline 19.0 (1.9x; the old bot: 34.0 vs 20.5), systems 102 vs 73, top 4 all bots.

**Dave's seed** (740601768, 16 empires, seat 1 the baseline bot as "GrossBeaks", 80 turns):

| | Human VP | Human systems | Human lost wars | Bot captures | Bot mean VP | Bot NNP |
|---|---|---|---|---|---|---|
| before | 32 (with the human-only stat bonus) | 7 | 0 | 7 | 54.3 | 4302 |
| after | 8 | 3 (settled 7, lost 5) | 3 | 27 | 43.6 | 3241 |

The under-defended human is now a target: three wars lost, five systems taken.

### Tests

373 passing (`~/mhgc/venv/bin/python -m pytest -q -p no:cacheprovider`, about 130 s). New `tests/test_npr_war_spies_trade.py` (11): ranks and victory over every race; a lone human gets no free bonus; the ramp gate per personality; targets before and after the ramp; a neutral passer-by doesn't block missions; the starport rule; spies built, sent, SOS then SUP, all orders valid; SOT parsing; two computer empires agree and trade through `run_turn`; no trade with a race at war; and the no-hidden-information scramble at turn 37 (ramped bots, spies and trades active). Updated: `test_npr_sim` VP growth measured from turn 10 (everyone starts tied first, ~20 VP); `test_npr_chatter` rank boast and "number 1" allowed; `test_spies_events_stats`, `test_analysis` as in item 1.

## 2026-11-15: computer empires offer tech trades to human players, in chat (DECISIONS A-08)

Dave: "computer empires offer technology trades to human players, in the chat".

- **Offers** (`npr/trade.py`, bottom; posted from `chatter.turn_chat`): from turn 8 a computer empire with no trade open may post one private message to a contacted human race (not at war, not the leader, not threatening it, no big grievance). Same valuation as bot-to-bot (`econ.tech_score`, `MIN_VALUE`): an even swap, or one its own valuation favours enough to cover the extra cost (at most twice the cost of what it gets). It names the human's technologies only if it knows them (its SOT reports; the human's TTNPR offers to it, now a `trade_offered` event in the bot's own report; gifts; trades), else offers its tech "for any 500 EU technology of yours that we lack" (a TTNPR ANY, 2026-11-19, DECISIONS G-23; until then it listed up to three it wanted). Limits: one open offer per bot, 6 turns between a bot's offers, 8 before the same human again, 16 before the same tech again, 2 a turn game-wide (one per human). Chatter off = no offers; quiet = same offers as normal.
- **Example** (seed 3, 8 empires, 2 humans): `T16 Grunts (private): The GRUNTS offer Missile Technology for any one of: Improved Engines I, Cybernetic Banking or Solar Collectors. Accept by this turn's end (turn 17). A bargain, frankly.` 11 offers in 40 turns of that game.
- **Accept**: `POST /api/games/{gid}/chat/{id}/accept {alt}` puts `TTNPR <theirs> <ours> <race>` in the recipient's draft once (another alternative replaces it); 403 for other races and for view as, 409 once expired. The chat shows one Accept button per alternative on the current turn only; expired/superseded offers show disabled buttons and "Expired". No "No thanks" button: an offer not taken acts as the decline (not repeated for 16 turns). An ANY offer has one Accept, which adds `TTNPR ANY <cost> <theirs> <race>`.
- **Honoured**: while open the bot holds half the cost of its tech and buys none of the asked-for techs, and makes/accepts no bot-to-bot trade; the engine (`orders_exec._npr_offered` -> `trade.offer_open`) accepts that exact TTNPR on that turn without the roll. Unsolicited TTNPRs roll as before. The offer closes at the end of its turn (`hoffer_log`, taken or not).
- **TTNPR ANY** (2026-11-19, DECISIONS G-23): either side of a TTNPR may be `ANY <cost>` (or `ANY:<cost>`), a tech of exactly that list price (100/250/500/1000/2000/3000/4000). The engine picks at turn run with the bot's own valuation (`trade.any_pick` over `econ.tech_score`, the NPR's own techs and memory): of its own techs the player lacks and can use, the one it values least; of the player's it lacks and can use, the one it values most, preferring those an open ANY offer said it would take (then the offer is honoured without the roll, `offer_open` on the picks). Nothing eligible = a failed check that doesn't use the attempt. Check orders picks nothing and checks only what the player can know. Bot-side change: `human_offer_terms` makes an ANY offer (`_any_offer_terms`) when it doesn't know the human's techs; the hold (`hold_due`) is unchanged (half the cost of what it gives, no buying of the techs it would take). Also: `Plan.happy` so two colonist deliveries to one system in a turn don't overrun its happiness (a rejected U in `s2_h1_random_60` after the offer change).
- Tests: `tests/test_npr_trade_offers.py` (12): recipients and limits in a real game, chatter off/quiet, no offer to the leader / at war / uncontacted, known vs unknown technologies, the no-leak scramble, an offered 1000-for-250 swap always accepted while the same swap unsolicited is refused, the exact-swap check, a generated offer accepted at the turn (both techs move, offer closed as taken), expiry, determinism with save/load, and the Accept API (recipient only, de-dup, alternatives, view as, 409 after expiry). `test_npr_chatter`: boast tests ignore offers; the levels test compares normal with quiet (and off only when no offer was made). Playwright: `~/mhgc/work/uitest/tradeoffer.py` (11 checks; shots `tradeoffer-0[1-3]-*.png`).

## 2026-11-15 (later): economy first, "Fight less, research more" (DECISIONS A-09)

Dave's brief after the aggression round: the new bot made about 4x the captures and twice the wars, spent about 20% less on research, and only drew with the old idle bot head to head. Now the bots should fight less and research more. The fixes that made attacks competent stay (passer-by, fresh-intel landings, fast fleets, holding captures).

### What changed (`npr/econ.py`, `war.py`, `diplo.py`, `spycraft.py`; numbers in A-09)

1. **The real waste was idle money.** Every bot, old and new, finished with 2,000-9,000 EU and 30,000-130,000 IU unused. Research was capped at one PT a turn, and crash research almost never fired. Now research buys a PT and then crash programmes with whatever is left over, up to 5 technologies a turn, with the dearest of the set as the PT. Any system whose IU stockpile is idle turns its profile to EU. This alone took the bot from level to far ahead of both older versions.
2. **Fewer, better wars.** One war fleet at a time. A higher capture chance is needed to launch. Smaller upkeep shares. After an attack of the bot's own choosing, a pause of 12/16/20 turns. The aggression ramp is not before turn 30/34/45. A conquest is only aimed at a clearly smaller race. Targets are scored by value for the cost.
3. **Peace sooner.** Peace is offered when a war isn't paying, and after fewer quiet turns. Making peace settles the grudge: in the first try (c1), peace-war-peace cycles raised the war count. Retaliation needs a little more grievance.
4. Spies scout neighbours less often. Production artifacts get a longer payback. There is less research pull towards light cruisers.

### Measurements (`~/mhgc/work/runs/econ`; candidates c1-c10 in `~/mhgc/work/cand`, the final one is c10 = this tree)

`aggr` = this morning's ramped bot (snapshot `~/mhgc/work/bot-aggressive`), `idle` = `~/mhgc/work/bot-before` (its own engine, so its VP have no NPR stat bonus). The runs are 80 turns, seeds 1-6, means per set. The new bot often wins around turns 65-78, so the counts are taken at turn 70 (`at_turn.py`). NNP, techs and the spending mix are taken at turn 60, when every game is still running.

| Set | Captures T70 idle / aggr / new | Wars T70 idle / aggr / new | War-turns per empire T70 | Techs T60 | NNP T60 | Ships / troops / research % T60 (aggr -> new) | New-bot wins (of 6) |
|---|---|---|---|---|---|---|---|
| 8 bots | 3.2 / 10.3 / 7.7 | 17.7 / 38.7 / 24.7 | 30 / 50 / 30 | 30.0 / 27.2 / 40.3 | 2532 / 2141 / 3039 | 26 / 9 / 39 -> 13 / 4 / 64 | 6 |
| 16 bots | 7.3 / 17.8 / 12.5 | 37.3 / 75.7 / 39.3 | 31 / 53 / 23 | 29.1 / 27.4 / 40.5 | 2492 / 2145 / 3044 | 24 / 9 / 41 -> 12 / 3 / 66 | 5 |
| 8, baseline human | 6.0 / 13.0 / 6.7 | 18.5 / 33.8 / 20.3 | 43 / 61 / 34 | 29.1 / 27.4 / 39.7 | 2497 / 2239 / 3065 | 24 / 9 / 39 -> 13 / 4 / 62 | 6 |
| 16, baseline human | 8.3 / 20.7 / 12.7 | 34.7 / 69.2 / 39.7 | 38 / 57 / 31 | 28.6 / 27.1 / 40.4 | 2551 / 2188 / 3026 | 23 / 9 / 42 -> 12 / 3 / 65 | 6 |

Captures are down 25-50% from aggr and wars down 35-50%. Both stay above the idle bot, except that war-turns are below it: peace comes sooner. Spy orders are about 10-20% fewer (T70: 405 vs 476 at 8 bots, 742 vs 930 at 16). Starports are 3.5-4.7% of spending (aggr 7-8%) and artifacts 12-14% (unchanged). Rejected orders are 0.01-0.04%.

**Head to head** (even seats new and odd old, then swapped; seeds 1-8, played to the end; per empire):

| Opponent, size | New VP | Old VP | New wins | Old wins | Top-4 new / old | Captures new / old | Wars new / old | Techs new / old | Research % new / old |
|---|---|---|---|---|---|---|---|---|---|
| idle, 8 | 80.1 | 50.5 | 15 | 1 | 77% / 23% | 1.11 / 0.52 | 3.3 / 4.2 | 46.7 / 35.9 | 66 / 55 |
| idle, 16 | 71.3 | 44.4 | 16 | 0 | 43% / 7% | 0.97 / 0.38 | 3.1 / 3.1 | 45.5 / 34.0 | 71 / 55 |
| aggr, 8 | 75.6 | 47.0 | 15 | 1 | 78% / 22% | 1.23 / 1.30 | 4.6 / 5.0 | 45.7 / 32.7 | 63 / 38 |
| aggr, 16 | 70.1 | 42.8 | 16 | 0 | 45% / 5% | 1.10 / 1.30 | 4.3 / 5.4 | 45.4 / 33.0 | 65 / 42 |

For reference, aggr vs idle on the same 8 seeds: 61.6 vs 63.2 VP and 7 vs 9 wins at 8 empires; 53.3 vs 55.2 VP and 7 vs 9 wins at 16 empires.

**Against the baseline** (`sim match N 60 mix`, seeds 1-5): new 58.3 VP vs baseline 20.0 (2.9x), systems 97 vs 76, the top 4 are all bots in every game. aggr scored 38.0 vs 19.1 (2.0x) and idle 37.4 vs 20.8 (1.8x).

**Dave's seed** (740601768, 16 empires, seat 1 the baseline bot as "GrossBeaks", 80 turns):

| | Human VP | Human systems (peak) | Systems lost | Bot captures | Bot mean VP | Bot NNP | End |
|---|---|---|---|---|---|---|---|
| idle (old engine) | 32 | 7 (8) | 0 | 7 | 54.3 | 4302 | T80 |
| aggr | 8 | 3 (8) | 5 | 27 | 43.6 | 3241 | T80 |
| new | 14 | 5 (8) | 3 | 15 | 69.6 | 4129 | bot 11 wins at T77 |

The human is pressured but survives. It is at war with two neighbours from turns 30-40. It holds 8 systems until turn 40, then 7, 6 and 5, and is never knocked out.

### Tests

391 passing. New in `tests/test_npr_war_spies_trade.py` (6):
- leftover EU buys crash research, the dearest technology is the PT, and the engine accepts every purchase;
- a trade hold is respected;
- idle IU turns a profile to EU;
- a peace settles the grudge;
- the ramp waits for its turn by personality;
- aggressive is still the most warlike but less than before.

Updated: the ramp tests set a turn past `ramp_min`.

## 2026-11-16: war-weariness, upkeep cap, research floor (DECISIONS A-10)

Dave's game at turn 45 (`~/mhgc/work/analysis/087fd598-t45`): Freepeople (aggressive, at war with him since T10) and Badhombres (at war with Grunts, then him from T42) had spent ~35 turns in defend mode, upkeep 200-250 EU of 320-470 income, 7 and 11 techs (bot mean 22.7), 61 and 71 warships.

### Root cause (botlog)

- Freepeople offered peace twice ("losing", T20 and T31) and Dave didn't EWA. After that no peace rule could fire: its grudge stayed at 92-96 (every lost ship adds grievance, the cap is 100) so `unpaid` and `asked` failed; there was fighting every turn so `quiet` was 0; the human's ships near it (attack 9-39) never outweighed its own 1.5x; a war mission stuck in "return" since T40 kept `idle` false. The A-09 rule only ends wars the bot isn't fighting.
- `war.defend` ignored the upkeep room at any threatened system (`room > 0 or hot`), and `threats` counts every enemy ship at every system within two turns: the human's 9 warships (attack 39) threatened 6-8 systems, each wanting 1.4x that. So every turn went to garrison warships, before research.

### What changed (`npr/diplo.py`, `war.py`, `econ.py`, `brain.py`; numbers in A-10)

1. **War-weariness**: after 8/10/14 turns (builder/opportunist/aggressive; x0.6 against a much stronger enemy) with no net gain and not clearly winning, the bot offers peace, attacking or defending: EWA every turn, a MESSAGE every 6 turns ("Roses are red, / Violets are blue, / This war is a bore, / And so, frankly, are you." ... "End the war with us (EWA) and there will be peace between us."). It accepts a peace request whatever its grudge and starts no new attack on that race. After peace: the grudge cap stays, a 12-turn truce (retaliation needs 2x grievance), no war of its choosing on that race for 20 turns.
2. **Upkeep cap**: warships + troops at most 40% of EU income in every mode; over 1.2x, salvage (SS) up to 4 of the weakest/obsolete warships a turn where the garrison allows.
3. **Research floor**: 25% of income held back before missions and defence, saved (`rsave`) when no technology is affordable yet; not when home is under attack.
4. **Defence**: a fleet counts in full only at the systems it reaches first (a quarter elsewhere); PD/SW/APD count and are built first at threatened systems. A war fleet stuck returning more than 8 turns is disbanded.
5. `tools/bot_games.py --accept-peace`: the baseline human EWAs when asked (it has no diplomacy).

### Measurements (`~/mhgc/work/runs/peace`; `retuned` = snapshot `~/mhgc/work/bot-retuned`, `new` = `~/mhgc/work/cand/peace2` = this bot on the same engine)

80 turns, seeds 1-6, means per game (`measure.py`). "Long-war bots" = at war 20+ turns. Upkeep = all EU upkeep / EU income over bot-turns at war.

| Set | Wars | Mean / max length | Ended in peace | War-turns per bot | Long-war bots: n, techs, NNP | All bots techs / NNP / VP | Upkeep at war | Captures | Won |
|---|---|---|---|---|---|---|---|---|---|
| 8 bots, retuned | 13.5 | 10.1 / 27.0 | 9.3 | 32.2 | 5.7, 43.8, 3621 | 45.1 / 3741 / 71.5 | 20% | 9.0 | 6/6 |
| 8 bots, new | 12.5 | 5.8 / 10.5 | 10.0 | 17.5 | 3.0, 42.1, 3096 | 45.0 / 3564 / 71.5 | 20% | 8.3 | 6/6 |
| 16 bots, retuned | 21.5 | 9.5 / 34.5 | 14.5 | 25.9 | 9.3, 43.2, 3449 | 44.5 / 3503 / 66.4 | 20% | 14.2 | 5/6 |
| 16 bots, new | 23.3 | 6.5 / 18.5 | 19.5 | 18.5 | 6.3, 44.3, 3591 | 46.0 / 3736 / 68.1 | 20% | 14.3 | 6/6 |
| 8, baseline human, retuned | 11.7 | 17.9 / 44.0 | 5.3 | 41.5 | 5.7, 46.2, 3948 | 46.6 / 3920 / 76.6 | 19% | 8.7 | 6/6 |
| 8, baseline human, new | 12.7 | 14.7 / 49.0 | 7.3 | 34.5 | 4.2, 47.6, 4166 | 47.8 / 4154 / 79.9 | 19% | 7.7 | 4/6 |
| 16, baseline human, retuned | 25.2 | 12.5 / 44.7 | 14.5 | 35.7 | 10.8, 43.9, 3561 | 45.1 / 3673 / 68.1 | 20% | 16.2 | 6/6 |
| 16, baseline human, new | 21.2 | 9.1 / 40.5 | 15.3 | 20.4 | 6.8, 44.6, 3686 | 45.2 / 3648 / 66.6 | 19% | 13.3 | 6/6 |

Wars with the baseline human never end (it never EWAs), so the long ones in human games are those. In self-play the upkeep cap and salvage almost never bind (military upkeep is 10-20% of income); they are for Dave's case. Rejected orders 0.02-0.04% (retuned 0.01-0.03%).

**Head to head** vs retuned (even/odd seats then swapped, seeds 1-12, to the end; per empire):

| Size | New VP | Old VP | Wins new / old | Top-4 new / old | NNP new / old | Techs | War-turns | Ships % of spending |
|---|---|---|---|---|---|---|---|---|
| 8 | 74.0 | 72.3 | 14 / 10 | 52% / 48% | 3799 / 3611 | 46.3 / 45.7 | 21.7 / 25.1 | 11.5 / 15.4 |
| 16 | 69.7 | 67.5 | 13 / 11 | 26% / 24% | 3816 / 3553 | 45.9 / 45.0 | 23.9 / 26.6 | 12.4 / 16.5 |

**Against the baseline** (`sim match N 60 mix`, seeds 1-5): new 58.2 VP vs 19.9 (2.92x; retuned 58.0 vs 20.0), systems 98 vs 76, top 4 all bots in every game.

**Dave's seed** (740601768, 16 empires, baseline as GrossBeaks, 80 turns): with the passive baseline no bot collapses in either version (the baseline doesn't press anyone). Bots at war with the human: retuned 2 (57 and 49 turns, never ended), new 4 (26-47 turns, never ended: the baseline doesn't EWA); with `--accept-peace` new 4 wars of 9-26 turns, all ended in peace. Their techs 46.8-47.8 and NNP 4722-4922 vs 47.0-47.5 / 3522-3876 for the other bots. Human 13 VP / 5 systems (retuned 14 / 6); bot 6 wins at T71-72 (retuned: none / T79).

**Dave's turn-45 state, 20 more turns** (`resume.py`; the human seat passes, or `--accept`):

| | Freepeople techs | warships | research % of income | upkeep T46-50 / T61-65 | BS / SS | peace |
|---|---|---|---|---|---|---|
| retuned, pass | 8 -> 13 | 61 -> 121 | 10% | 57% / 66% | 72 / 0 | still at war |
| new, pass | 8 -> 21 | 61 -> 85 | 35% | 44% / 43% | 34 / 1 | offers T46, 52, 58, 64 (EWA every turn); still at war |
| retuned, accept | 8 -> 17 | 61 -> 104 | 22% | 57% / 50% | 53 / 0 | offer T48 ("losing"), peace T49 |
| new, accept | 8 -> 22 | 61 -> 73 | 35% | 44% / 63%* | 24 / 3 | weary offer T46, peace T47 |

\* a conquest fleet against Groachi at T60-63 (ships away cost 5 EU), back under the cap at T64. Badhombres changes little (it was already buying a PT most turns): techs 12 -> 27-28 in both versions, peace with Grunts T47; to GrossBeaks it offers peace T47 ("quiet") and then weary T53, 56, 62, and with `--accept` the war ends T54.

### Tests

452 passing. New `tests/test_npr_peace.py` (11): weary offer by personality despite a grudge and ongoing fighting; sooner against a stronger enemy; EWA every turn, MESSAGE every 6; not weary while the war pays (and weary again when more is lost than taken); truce and no conquest after peace; no warship over the cap even when threatened (troops still dig in); salvage of the weakest, engine-valid; focused threats; the research floor and its home-attack exception; two computer empires make peace through `run_turn`; the no-hidden-information scramble during a war.

## 2026-11-18: the split tweak on the bot's profiles (DECISIONS G-21)

- **`econ.profiles`**: the final step tweaks (±3, `econ.TWEAK_DELTA`) the AU/IU/EU split the bot chose with `engine/economy.tweak_split`, so no resource goes down and rounding waste is recovered. Applied only when the bot issues a CSP anyway (the 20-point / hungry rule is unchanged). `econ.split_context(w, plan, s)` builds the engine's `SplitContext` from the bot's own view: the system (population as the view shows it, 3 decimals), its own posted governor, and this turn's planned BI, BSP/DSP, colonists moved (`plan.pop`) and installs (the plan's copy of the artifacts). `econ.tweak` wraps it. The re-issue option (`TWEAK_REISSUE_GAIN`: re-issue a kept profile tweaked when that gains ≥ n units, reason code `econ.profile_tweak`) exists but is **off** (None).
- **Measured** (`~/mhgc/work/tweak`, `scripts/measure.py` wraps `tools/bot_games.py play` and records every system's production against the untruncated value; 6 seeds x 70 turns, size 16, all computer empires; baseline = a copy of the previous tree, `pre_root`):

| variant | rounding waste (% of production) | CSP orders | per empire-turn | tweak-only CSPs |
|---|---|---|---|---|
| before | 0.717% | 20,074 | 3.05 | - |
| **tweak issued CSPs (chosen)** | **0.661%** | 19,530 | 3.01 | 0 |
| + re-issue at gain ≥ 2 | 0.643% | 22,971 | 3.49 | 2,521 |
| + re-issue at gain ≥ 1 | 0.622% | 27,462 | 4.26 | 6,346 |

  About 8% of the waste is recovered (~0.06% of all output, about a unit per empire per turn) with no extra orders; most of the bots' production is in systems of 100+ units before the split, where nothing can be gained. Total units per game vary by ±5% between seeds as the games diverge, so the waste ratio is the measure. The bot's predicted outputs equal the engine's for 99.5% of tweaked CSPs (27,559 / 27,691, `scripts/accuracy.py`). Head-to-head against the previous bot (`--mode h2h --old pre_root/mhgc/npr`, 4 seeds x both seatings): wins 3 vs 2, mean final NNP 3538 vs 3386, VP 65.1 vs 63.9, within noise.
- **Tests** (`tests/test_split_tweak.py`): the bot's context equals the engine's (multipliers exactly, base within the view's population rounding); over 20 turns of an 8-empire game every bot CSP is valid and executes, ≥ 97% produce exactly what the bot predicted and ≤ 1% fall below the untweaked split; the re-issue option issues exactly the tweaked split at its threshold and nothing below it. The existing determinism and no-hidden-information tests pass unchanged.

## 2026-11-19: static artifact repricing, and farcasters and warp tunnels (DECISIONS G-24)

Prices (Dave): CB 100/100, VRB 150/150, BF 100/0, AF 75/75 (3), CM 150/150, AL 150/150, EHC 75/0 (2), CS 100/100 (**upkeep 4**), FP 50/50, WT 75/75; tech 42 and Warp Tunnel (50) cost 2000. Built artifacts stay; upkeep is at the current rate from the next turn.

- **Payback rule** (`econ.ARTIFACT_PAYBACK` 18) re-checked and kept: at 12 the bots lost 5-10% NNP by T50-T70; at 24 within noise of 18. Small colonies no longer qualify; mid-game systems still do.
- **`npr/portals.py`** (new): FP at home + up to 3 far fronts (own system, pop 3+, starport, 10+ squares from home, frontier / stage / threatened; once at war, ramped or staging); WT at home + up to 2 far fronts (trip 3+ turns at the warships' median speed; at war or 2+ such fronts). TP: spare troops (not militia, not dug in, sender keeps its ground target) to a war-fleet stage, the stage's missing assault troops built at the hub when its starport runs out (farcast next turn), spare troops to a threatened FP system. WTP: spare hub warships to a WT stage, spare warships to a WT system short of its garrison, when sailing takes 3+ turns. Stages with a portal preferred up to 3 squares further. Research pull: +6 (tech 32), +10 (tech 50) with a far front. Caps 6 TP, 6 WTP a turn. Reason codes `portal.*`.
- **Spy fix** (`spycraft.learn`): an SMV refused for want of contact (the target changed hands to a race not yet met) is not repeated; the target is skipped 20 turns. `tests/test_npr_sim.py` lists that refusal as unforeseeable.

### Measurements (`~/mhgc/work/artprice`: `runs/{before,pricesonly,final,pb12,pb24,h2hfinal}`, `scripts/measure.py`; 6 seeds x 75 turns; `before` = old prices + old bot, `pricesonly` = new prices + old bot, `final` = this tree)

| | 8 before | 8 after | 16 before | 16 after |
|---|---|---|---|---|
| production artifacts installed / empire (CB VRB CM AL BF AF EHC CS) | 10.1 8.3 7.5 4.2 9.8 8.2 9.1 9.0 | 9.1 7.4 6.7 3.0 8.9 6.7 8.5 7.1 | 9.2 7.7 7.0 4.4 9.1 7.7 8.6 8.3 | 8.2 6.7 6.2 3.0 8.2 6.5 8.1 6.8 |
| FP / WT built (all empires) | 0 / 0 | 150 / 34 | 0 / 0 | 260 / 50 |
| TP / WTP ok (rejected) | 0 / 0 | 81 / 7 (0) | 0 / 0 | 150 / 7 (0) |
| spending: research / artifacts / ships | 68.8 / 12.2 / 10.3% | 62.8 / 18.1 / 10.0% | 69.7 / 11.5 / 10.3% | 65.1 / 16.9 / 9.6% |
| NNP T30 / T50 / T70 | 1105 / 2383 / 3606 | 1061 / 1934 / 3253 | 1132 / 2432 / 3704 | 1033 / 1987 / 3210 |
| techs T50 / T70 | 33.7 / 45.4 | 30.8 / 43.4 | 34.5 / 46.1 | 31.2 / 43.9 |
| VP T50 / T70 | 46.9 / 70.8 | 43.0 / 64.6 | 43.7 / 68.8 | 39.0 / 61.5 |
| games won by T75 (win turns) | 6/6 (58-73, mean 69.3) | 2/6 (67, 74) | 6/6 (62-73, mean 68.8) | 2/6 (71, 71) |
| rejected orders | 0.031% | 0.014% | 0.022% | 0.033% |

The slower economy is the price change itself (`pricesonly` is within 1-2% of `final` on every curve): artifacts take 5-6 points more of spending, research 4-6 fewer, NNP is ~15-18% lower at T50 and ~10-13% at T70, and most games now run past turn 75. The bots don't stall (artifact counts fall only ~10-25%, AL most, and NNP still rises steadily) and don't overbuild (a shorter payback is worse).

**Head-to-head, both on the new prices** (24 games: 6 seeds x 8/16 empires, each with seats swapped; new bot on even seats, old on odd, then reversed): wins new 6, old 1 (17 undecided at T75); 8 empires VP 69.0 vs 68.5, NNP 3523 vs 3460, captures 1.15 vs 1.08; 16 empires VP 66.6 vs 66.5, NNP 3493 vs 3480. A small edge, as intended for a modest feature; the rejection rate is unchanged (0.027% vs 0.026%).

**Dave's turn-73 state, 5 more turns** (`scripts/t73_replay.py`, the human seat passes): production artifacts built T74-78: old prices + old bot 47 (CB 2, VRB 9, AF 7, AL 7, BF 5, CS 2, ...), new prices + old bot 20, new prices + this bot 21 (no CB/BF/CS/CM at all: the systems that lacked them don't pay back), plus 25 FP and 13 WT (the techs were already owned) and 3 TP; 0 rejected orders in 1224.

### Tests

`tests/test_artifact_prices.py` (12): the table; tech costs, VP (WT 2) and the ANY list; Warp Tunnel's prerequisites and CRP price; BT at the new price, doubled under attack, and its ledger lines; an old save keeps its artifacts and pays CS 4; the bot builds FP/WT at home and a far front and not without one; TP to a stage and to a threatened system and WTP validate in the engine; warping in defence; no hidden information. Updated for the new prices: `test_data`, `test_orders_exec::test_bt_artifacts`, `test_production_preview` (colony IU), `test_combat::test_raid_rules_example` (EHC 2/75).

## AOMT: the bot as a stand-in for a human race (2026-11-19, DECISIONS W-29)

`npr.aomt_orders_traced(state, eid, results)` runs the normal bot (`brain.decide`, `record=True`) for a **human** race on a forced turn it hasn't submitted, when its AOMT setting is on. Inputs are only the race's own view, `view(state, inbox, eid)`, where the inbox comes from the race's stored last report (`npr.stored_inbox`, shared with W-22's `adopt`); so A-02 holds (tested with the scramble test in `tests/test_aomt_handicap.py`). Memory: `GameState.aomt_state[eid]`, separate from `npr_state`, kept while the missed turns are consecutive (`aomt_last`) and new otherwise; RNG purpose `aomt<id>`. Caretaker filter `npr.AOMT_SKIP` drops MESSAGE, NSY, CRN, DA, DW, EWA, GE, GT, TTNPR, DD, SD, UG, RESIGN and AOMT (the bot's record keeps them in `aomt_dropped`), so nothing visible to others gives the stand-in away and no diplomacy is made for the player. `trace.Tracer(aomt_results=...)` has `stand_in` (the `aomt_fn` for `run_turn`); records are marked `aomt: true`; orders.json marks the orders `by: "aomt"`. The bot code itself is unchanged. Since 2026-11-20 (W-30) the stand-in runs only when the race's unsubmitted draft is empty; a non-empty draft runs as if submitted. In a sample 4-turn run (seed 5, size 8) the stand-in gave 7-9 orders a turn, all accepted: settling, transports, infrastructure, profiles, scouting.


## 2026-11-19: ship rebalance, and the short-line tie order (DECISIONS G-25)

Dave's stat change: Destroyer 3/5, Cruiser 7/12, Battleship 12/16, HvyBattleship 16/18, Dreadnought 24/24, DeathStar 45/12 (`data/ships.py`); fast line, upkeep and costs unchanged. The bots read the stats from the table, so no code change was needed to use them, and they took to the standard line at once. They still built no DeathStars, although 106 of 156 empires had tech 47 by T75 (for its solar collectors). `war.choose_ship` multiplies the value of the line a system is shortest of by 1.6, and ties went in table order (STANDARD, DEFENSIVE, FAST, OFFENSIVE): with standard and defensive ships present, the fast line took the bonus and lost anyway (FB 9.3 against MO 12.8), so the offensive line never had it. Ties now go STANDARD, DEFENSIVE, OFFENSIVE, FAST (`war.SHORT_ORDER`). A bonus for every tied line was tried (`after2`) and dropped: offensive ships then won almost everywhere and standard builds fell below the old level (1008 against 1565).

### Measurements (`~/mhgc/work/shipstats`: `runs/{before,after,after2,after3,h2h}`, `scripts/shipmix.py`, `before-tree` = the old `mhgc` package; 6 seeds x 75 turns, all-NPR games)

`before` = old stats, old bot; `after` = new stats, old bot; `final` (`after3`) = new stats, tie order.

| | 8 before | 8 after | 8 final | 16 before | 16 after | 16 final |
|---|---|---|---|---|---|---|
| warships built: standard / defensive / offensive / fast | 532 / 2129 / 59 / 1 | 1488 / 2046 / 19 / 0 | 1410 / 1421 / 253 / 0 | 1033 / 3978 / 129 / 9 | 2953 / 3583 / 109 / 5 | 3127 / 3119 / 504 / 0 |
| D / C / B / HB / DN | 53 / 93 / 52 / 140 / 140 | 343 / 578 / 310 / 129 / 74 | 326 / 535 / 247 / 134 / 114 | 92 / 137 / 111 / 261 / 333 | 710 / 1145 / 540 / 217 / 242 | 708 / 1232 / 463 / 335 / 290 |
| E / DS | 0 / 0 | 0 / 0 | 123 / 59 | 1 / 0 | 44 / 1 | 191 / 93 |
| captures / game | 8.8 | 9.5 | 8.2 | 14.0 | 17.2 | 16.7 |
| wars / game | 27.7 | 24.7 | 24.7 | 49.3 | 52.7 | 51.0 |
| ships % of spending | 10.1 | 13.1 | 11.4 | 9.6 | 12.6 | 12.7 |
| NNP T75 (mean empire) | 3520 | 3367 | 3429 | 3451 | 3260 | 3409 |
| techs / VP T75 | 44.8 / 68.8 | 44.4 / 68.0 | 44.3 / 67.8 | 45.4 / 65.7 | 43.9 / 62.4 | 44.0 / 62.9 |
| games won by T75 (turns) | 2/6 (67, 74) | 2/6 (73, 75) | 1/6 (71) | 2/6 (71, 71) | 2/6 (69, 74) | 1/6 (67) |

Stronger standard ships make garrisons cost more (the bots size them against the attack they see), so ships take 1-3 points more of spending, and NNP and VP end a little lower. The tie order gives some of that back: the offensive ships it adds raise the Mixed Fleet Bonus of mixed garrisons.

**Head-to-head, both on the new stats** (12 games: 6 seeds x 16 empires, seats swapped; new = tie order, old = table order): wins new 2, old 3; top-4 22.9% / 27.1%; VP 64.3 / 63.5; NNP 3398 / 3416; captures 0.97 / 0.97 per empire. Even.

### Tests

`tests/test_ship_rebalance.py` (5): the new values and the unchanged rest; value per cost (standard below defensive, DeathStar best); a save of the old code loads with the new stats; the bot picks a DeathStar when the offensive and fast lines are missing, and a Dreadnought where only defensive ships are present. `tests/test_combat.py`: the combat example now has two Groachi scouts, and the role-shift, partial-shot, system-weapons and status-threshold tests use the new numbers.

## 2026-11-20: trade routes (CTT) and the proximity war (DECISIONS A-11, A-12)

### What changed
- **`npr/ctt.py` (new), A-11.** With Decentralized Trading (tech 21) a computer empire sets up CTT trade routes at the populated systems of contacted races it is not at war with (allies included; not rebels or empty worlds), from its own short-scan intel (now also infrastructure and the races with routes there, `world.build`). Route value = the engine's DCT rule (25% of the system's EU production, the 50% cap shared out; `engine/economy.trade`), the production estimated from population, IF and starport with a third to EU. Worth it when the transport and trip pay back within 15 turns (at least 2 EU a turn, at most 7 turns away). At most min(4, 1 + systems/4) on the way at once. `brain.decide`: traders under way are moved (and converted on arrival) before the colony transports; new trade transports are built after development, or idle empty transports taken over once no colony target is left. `expand._transports` leaves traders alone. Research values tech 21 by the routes it could set up; `econ.income` counts last turn's trade EU.
- **`npr/diplo.py`, A-12.** `intruders`: armed ships of a non-allied race that could reach one of our systems in one move (ship speed, or the slowest seen ship of its fleet), not at their own world. Such a race gets a DW at once (`diplo.war_proximity`), whatever the grievance; already at war: nothing. No peace offer and no EWA while they stay (`peace_blocked`); a turn of grace after a peace (`proximity_grace`). `races_near`/`path_provokes`: where our warships stopping would give another race the same reason. `trade._good_partner` (A-08) also refuses a race with warships within one move.
- **`npr/war.py`, A-12 avoidance.** Reinforcements, gathering, intercepts and mission targets/launches skip routes that stop within one move of a neutral's (or ally's, or uncontacted race's) worlds; warships left there go back to base (`defend.leave_neutral`); a mission whose target changed hands to a race we're not at war with withdraws. A race we are making peace with this turn (EWA) counts as a neutral for this.

### Measurements (`~/mhgc/work/ctt-war`: `before/` = the pre-change tree `~/mhgc/work/pre-ctt-war/mhgc-web`, `v1/` = the first cut without avoidance, `v8/` = this tree, `h2h/` = new vs old bots; `metrics.py`, `summ.py`, `intruders.py`, `dbg/probe.py`)

8 empires, 80 turns, seeds 1-6, all computer empires:

| | before | after |
|---|---|---|
| CTT routes set up per bot | 0 | 11.1 (5-18; none rejected) |
| Routes still held at the end, per bot | 0 | 10.6 |
| First route | - | turn 28-50 (mean 37) |
| Trade EU as a share of EU income | 0 | 6% at T40, 13% at T50, 19% at T60 |
| First race to 90 VP | T78, 71, 70, 73, 66, none by 80 (mean of 5: 71.6) | T68, 63, 64, 74, 74, 70 (mean 68.8) |
| Techs per bot at the end | 43.8 | 43.6 (games end ~3 turns sooner) |
| Wars declared per game | 12.2 (58 conquest, 15 retaliation) | 10.5 (37 conquest, 9 retaliation, 17 proximity) |
| Repeat declarations (same pair) | 17 | 8 |

The first cut (proximity war, no avoidance; seeds 1-4) had 36 wars a game, four fifths of them proximity, mostly from interceptors chasing enemies past third races' worlds and ships gathering for missions; the avoidance took that to 2.8 proximity wars a game. Most of the rest come from ships the intruder couldn't know about (a world settled or captured that turn, or one it has never scanned) and war fleets at targets next to a third race.

Head to head (8 games, seeds 1-4 each way, 4 new and 4 old bots a game): new bots won 5 of 8, top-4 62.5%, VP 68.9 vs 59.4, NNP 3983 vs 3073, techs 44.5 vs 40.9; new bots declared 75 wars (45 proximity, mostly on old bots, which don't keep their warships out of reach), old bots 36.

### Tests
`tests/test_npr_ctt_proximity.py` (10): the engine's trade income is 25% of the system's EU and the bot's estimate is in range, the bot converts on arrival and remembers the route; builds a trade transport only for a worthwhile route (not without the tech, at war, with a route already, or for a tiny colony); sends an idle transport, the 50% cap shared; tech 21 is worth more with routes to set up; proximity war within one move (not out of reach, not unarmed, a fleet at its slowest ship's speed), not on allies, at war (no second DW) or at their own world; no peace while they stay, peace again once they have gone, and our warships keep out of a race we make peace with; the turn of grace; `races_near`/`path_provokes` and a warship sent back to base; no trade offer to a race with warships within one move. `test_npr_units.test_peace_when_overmatched_or_asked` now puts the enemy fleet out of one move.
