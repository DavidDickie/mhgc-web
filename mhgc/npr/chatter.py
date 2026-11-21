"""Computer empires boast in the game-wide chat (Dave 2026-11-13: "generate chat messages for
accomplishments... like 'Another system settled by the SPOONBOTS' and 'Captured number 1 in
happiness this turn'"; DECISIONS W-14).

`turn_chat(state, results)` runs at the end of each turn (from `npr.observe_turn`, after each
computer empire has stored its own report).  For every computer empire it builds the same
read model a human player gets (`mhgc.view.view` with its own report) and calls
`boasts(view, memory, rng)`, which is pure: it reads only that view and the bot's memory, and
writes only the memory's "brag" section.  So a boast can only state what that empire itself
knows (tests/test_npr_chatter.py scrambles every other empire's hidden state and checks the
messages are identical).

What a bot boasts about, in priority order (rarer and bigger first):
  capture       it took a system in battle (names the loser if it has contact with them), or
                reclaimed one from the rebels
  vp            it passed 25, 50 or 75 victory points
  war           it is at war with a race AND has fought it since (so the enemy knows already)
  peace         a war ended by both sides offering peace (both know)
  alliance      it allied with a race that had asked it to (both know)
  rank          number 1 in a statistic, read from its own ranks (the view's empire.ranks, the
                same figures a human sees in the Report and Stats tabs).  Every race is ranked
                since Dave 2026-11-15 (DECISIONS A-06), so a computer empire knows its own rank
                legitimately; it never sees anyone else's.  Only for a figure above zero and
                from turn 5 (at the start everyone is "first" in everything, tied)
  battle        it destroyed enemy units and lost none
  tech          it bought a technology costing 1000 EU or more, or a Future Technology
  contact       first contact with a race
  settle        it settled (or claimed) an empty system
  improve       a big turn-on-turn gain in one of its own figures: happiness, population, NNP,
                EU stockpile, systems, techs or VP (percentages only, never its stockpile)

Never in a message: coordinates, fleet positions or strengths, or another empire's numbers.
Own figures appear only as milestones (VP) or whole percentages.

Limits (`select`): per bot at most one message a turn; game-wide at most 4 (normal) or 2 (quiet,
which also keeps only priority >= 60: captures, VP milestones, war, peace, alliances, number 1 and
big technologies); common kinds (settle, improve, contact, battle) at most every 3 turns per bot.
"off" posts nothing (memory still tracks what happened, so turning it back on doesn't replay old
news).  Template and tie choices use `Rng(seed, turn, f"chat{eid}")`: deterministic per seed.

`turn_chat` also posts the computer empires' technology trade offers to human races, privately
(`trade.human_offer_candidate`, DECISIONS A-08): not boasts, so "quiet" keeps them and only "off"
stops them; at most `trade.OFFERS_PER_TURN` a turn, one per human race.
"""
from __future__ import annotations

from ..data.techs import FUTURE_TECH, TECHS
from ..model import NPR, GameState
from ..rng import Rng

PRIORITY = {"capture": 90, "vp": 85, "war": 80, "peace": 78, "alliance": 75, "rank": 70,
            "battle": 65, "tech": 60, "contact": 50, "settle": 30, "improve": 20}
COOLDOWN = {"settle": 3, "improve": 3, "contact": 3, "battle": 3}
LIMITS = {"normal": (4, 0), "quiet": (2, 60), "off": (0, 999)}
VP_MILESTONES = (25, 50, 75)
STAT_LABEL = {"HAP": "happiness", "POP": "population", "NNP": "NNP", "GNP": "GNP",
              "WAR": "warships", "NWR": "non-warships", "STP": "starports", "PRD": "productivity",
              "CTS": "combat troops", "GWR": "growth", "TEC": "technology", "SYS": "systems"}
# turn-on-turn gains worth a boast: (stat, minimum base, minimum absolute gain, minimum %)
IMPROVE = (("HAP", 0.2, 0.05, 15), ("POP", 10.0, 4.0, 20), ("NNP", 40.0, 15.0, 20),
           ("EU", 200.0, 150.0, 25), ("SYS", 4.0, 2.0, 20), ("TEC", 5.0, 2.0, 20),
           ("VP", 10.0, 3.0, 20))
IMPROVE_FROM = 5        # every empire starts alike, so early gains are the same for all of them
IMPROVE_WORDS = {"HAP": "happier", "POP": "more numerous", "NNP": "more productive",
                 "EU": "richer", "SYS": "bigger", "TEC": "cleverer", "VP": "more victorious"}

# {R} our race (caps), {X} the other race (caps), {T} a technology, {N} a number we may say
# (a VP milestone or a percentage), {S} a statistic, {W} what improved.
TEMPLATES: dict[str, dict[str, tuple[str, ...]]] = {
    "settle": {
        "aggressive": ("Another system settled by the {R}! Cower, neighbours.",
                       "The {R} flag goes up on another world. Who wants to argue?",
                       "One more rock for the {R}. Next time we take one with people on it."),
        "builder": ("Another system settled by the {R}. Tasteful, well planned, naturally.",
                    "The {R} have opened another lovely colony. Try to keep up.",
                    "Another world joins the {R}. Our architects are frankly too good."),
        "opportunist": ("Another system settled by the {R}. Nobody was using it. Probably.",
                        "Finders keepers: the {R} have a new colony.",
                        "Funny how empty worlds keep turning up {R}.")},
    "capture": {
        "aggressive": ("The {R} have TAKEN a system from the {X}! Who's next?",
                       "Crushed! The {X} just lost a world to the {R}.",
                       "Dear {X}: thanks for the system. Love, the {R}."),
        "builder": ("The {R} have relieved the {X} of a system they clearly weren't using properly.",
                    "A former {X} world is now under sensible {R} management.",
                    "The {X} have donated a system to the {R}. Very generous of them."),
        "opportunist": ("Oops! A {X} system seems to belong to the {R} now.",
                        "The {X} left a system lying around. The {R} picked it up.",
                        "Some {X} real estate changed hands. The {R} got a very good price.")},
    "capture_anon": {
        "aggressive": ("The {R} have conquered another system! Its old owners can come and complain.",),
        "builder": ("A captured system joins the {R}. It will be much better run now.",),
        "opportunist": ("The {R} have acquired a slightly used system. No questions, please.",)},
    "reclaim": {
        "aggressive": ("The {R} have stamped out the rebels and taken their world!",
                       "Rebels? Not any more. That world belongs to the {R}."),
        "builder": ("Order restored: the {R} have reclaimed a world from the rebels.",
                    "A rebel world is back under responsible {R} government."),
        "opportunist": ("The rebels had a lovely world. Had. Ask the {R}.",
                        "The {R} have liberated a rebel system. From the rebels.")},
    "vp": {
        "aggressive": ("{N} victory points for the {R}! Start worrying.",
                       "The {R} hit {N} victory points. The universe should take notes."),
        "builder": ("The {R} have quietly reached {N} victory points. As planned.",
                    "{N} victory points for the {R}. Quality tells."),
        "opportunist": ("Would you look at that: the {R} have {N} victory points.",
                        "{N} victory points and nobody saw the {R} coming.")},
    "war": {
        "aggressive": ("The {R} are AT WAR with the {X}! Hide your ships.",
                       "War with the {X}! The {R} have been waiting for this.",
                       "Attention {X}: the {R} accept your surrender at any time."),
        "builder": ("The {R} regret to announce that the {X} have made war necessary.",
                    "The {R} are at war with the {X}. We did warn them, politely."),
        "opportunist": ("The {R} and the {X} are at war. Nothing personal. Mostly.",
                        "War with the {X}? The {R} were going to do it eventually.")},
    "peace": {
        "aggressive": ("Peace with the {X}. The {R} were just getting warmed up.",
                       "The {X} begged for peace and the {R} were merciful. This time."),
        "builder": ("Peace with the {X} at last. The {R} always preferred building.",
                    "The {R} and the {X} are at peace. Civilisation wins again."),
        "opportunist": ("The {R} have made peace with the {X}. For now.",
                        "Peace with the {X}! The {R} will be keeping the receipts.")},
    "alliance": {
        "aggressive": ("The {R} and the {X} are allies! Everyone else, look out.",
                       "The {X} have wisely joined the {R}. Smart race."),
        "builder": ("The {R} welcome the {X} as allies. Good taste is contagious.",
                    "A fine alliance: the {R} and the {X}."),
        "opportunist": ("The {R} are allied with the {X}. Lovely people. Very useful.",
                        "New friends! The {R} and the {X}. What could go wrong?")},
    "rank": {
        "aggressive": ("Captured number 1 in {S} this turn! The {R} take what they want.",
                       "Number 1 in {S}. Second place is for the {R}'s victims."),
        "builder": ("The {R} are number 1 in {S} this turn. Nobody is surprised.",
                    "Number 1 in {S}. The {R} would like to thank our hard workers."),
        "opportunist": ("Number 1 in {S}? The {R}? How did that happen? (Smile.)",
                        "Captured number 1 in {S} this turn. The {R} were in the right place.")},
    "battle": {
        "aggressive": ("Another glorious victory for the {R} over the {X}!",
                       "The {X} came looking for a fight. The {R} obliged. Not a scratch.",
                       "{X} wreckage is drifting past {R} space. Lovely."),
        "builder": ("The {R} have politely but firmly defeated the {X} in battle.",
                    "A tidy little victory over the {X}. The {R} lost nothing."),
        "opportunist": ("The {X} picked a fight with the {R} and lost. Shame.",
                        "The {R} won a scrap with the {X}. Sorry about the mess.")},
    "tech": {
        "aggressive": ("The {R} now have {T}. Somebody is going to regret this.",
                       "{T}! The {R} armoury grows.",
                       "New toy for the {R}: {T}. Who wants a demonstration?"),
        "builder": ("The {R} have developed {T}. Progress, as usual.",
                    "{T} is now a {R} achievement. Our scientists send their regards.",
                    "The {R} have mastered {T}. You may applaud."),
        "opportunist": ("The {R} have {T}. Don't ask where we got the plans.",
                        "Guess who has {T}? The {R}, that's who.",
                        "{T} acquired. The {R} never pay full price.")},
    "future": {
        "aggressive": ("Future Technology for the {R}! The future is ours to smash.",),
        "builder": ("The {R} have bought another Future Technology. Naturally.",),
        "opportunist": ("Another Future Technology for the {R}. The future is a bargain.",)},
    "contact": {
        "aggressive": ("The {R} have met the {X}. They look breakable.",
                       "First contact with the {X}! The {R} are sizing you up."),
        "builder": ("The {R} have made contact with the {X}. Welcome to civilised space.",
                    "Hello, {X}. The {R} trust you'll be sensible neighbours."),
        "opportunist": ("The {R} have met the {X}. Lovely to meet you. Truly.",
                        "First contact with the {X}! The {R} have so many deals for you.")},
    "improve": {
        "aggressive": ("The {R} are {N}% {W} this turn than last turn. Fear us more.",
                       "{N}% {W} in one turn. The {R} are just getting started."),
        "builder": ("The {R} are {N}% {W} this turn than last turn. Good management.",
                    "A {N}% jump: the {R} are {W}. Steady growth, as planned."),
        "opportunist": ("The {R} are {N}% {W} this turn than last turn. Don't ask how.",
                        "{N}% {W} in one turn! The {R} must be doing something right.")},
}


def caps(name: str) -> str:
    return (name or "").replace("_", " ").upper()


def _brag(mem: dict) -> dict:
    b = mem.get("brag")
    if b is None:
        b = mem["brag"] = {"t": -1, "techs": None, "ft": 0, "vp_ms": [], "stats": None,
                           "stance": {}, "fought": {}, "war_said": [], "ally_said": [],
                           "rank1": [], "last": {}}
    return b


def boasts(view: dict, mem: dict, rng) -> list[dict]:
    """This turn's candidate boasts of one computer empire, from its own view and memory only.
    Each is {"kind", "priority", "text", "tie"}.  Updates mem["brag"]."""
    b = _brag(mem)
    e = view["empire"]
    me = e["id"]
    turn = view["game"]["turn"]
    persona = (mem.get("persona") or {}).get("name", "builder")
    races = {r["id"]: r for r in view["races"]}
    res = view.get("results") or {}
    events = res.get("events") or []
    R = caps(e["name"])

    def who(rid):
        r = races.get(rid)
        return caps(r["name"]) if r and r["kind"] in ("player", "npr", "extinct") else None

    cands: list[tuple[str, int, dict]] = []      # (kind, priority, fields)

    # captures and settling (this turn's events)
    settled = 0
    for ev in events:
        k, d = ev.get("kind"), ev.get("data") or {}
        if k == "system_captured" and "race" in d:
            if d["race"] == 0:
                cands.append(("reclaim", PRIORITY["capture"] - 2, {}))
            else:
                x = who(d["race"])
                if x:
                    cands.append(("capture", PRIORITY["capture"], {"X": x}))
                else:                                    # a loser we never made contact with
                    cands.append(("capture_anon", PRIORITY["capture"], {}))
        elif k in ("colonized", "system_captured"):
            settled += 1
        elif k == "contact" and d.get("race") in races:
            x = who(d["race"])
            if x:
                cands.append(("contact", PRIORITY["contact"], {"X": x}))
    if settled:
        cands.append(("settle", PRIORITY["settle"], {}))

    # victory point milestones
    vp = int(e.get("vp") or 0)
    for ms in VP_MILESTONES:
        if vp >= ms and ms not in b["vp_ms"]:
            b["vp_ms"].append(ms)
            if b["t"] >= 0:                          # not on the bot's first observed turn
                cands.append(("vp", PRIORITY["vp"] + ms // 25, {"N": str(ms)}))

    # technologies
    techs = set(e.get("techs") or [])
    if b["techs"] is not None:
        for t in sorted(techs - set(b["techs"])):
            cost = TECHS[t].cost if t in TECHS else 0
            if cost >= 1000 and t != FUTURE_TECH:
                pr = PRIORITY["tech"] - (20 if cost < 2000 else 0) + (4 if cost >= 4000 else 0)
                cands.append(("tech", pr, {"T": TECHS[t].name}))
        if int(e.get("future_tech") or 0) > b["ft"]:
            cands.append(("future", PRIORITY["tech"] + 2, {}))
    b["techs"] = sorted(techs)
    b["ft"] = int(e.get("future_tech") or 0)

    # battles: we destroyed enemy units and lost none
    fought_now: set[int] = set()
    for c in res.get("combats") or []:
        owner = {s["number"]: s["owner"] for s in c.get("ships") or []}
        towner = {t["number"]: t["owner"] for t in c.get("troops") or []}
        kills, losses, victims = 0, 0, set()
        for ln in c.get("lines") or []:
            by = ln.get("by")
            if by is None:
                continue
            o = owner.get(ln["ship"]) if ln.get("ship") is not None else \
                towner.get(ln.get("ct")) if ln.get("ct") is not None else None
            if o == me:
                losses += 1
            elif by == me and o is not None:
                kills += 1
                victims.add(o)
        for p in c.get("participants") or []:
            if p not in (me, 0):
                fought_now.add(p)
        if kills and not losses and c.get("owner_after") == c.get("owner_before"):
            named = [who(v) for v in sorted(victims) if v and who(v)]
            if victims and len(named) == len([v for v in victims if v]) and named:
                cands.append(("battle", PRIORITY["battle"], {"X": " and the ".join(named)}))
    for p in fought_now:
        b["fought"][str(p)] = turn

    # diplomacy: our own stance, announced only when the other side already knows
    for rid, r in sorted(races.items()):
        if r["kind"] not in ("player", "npr"):
            continue
        k = str(rid)
        now, before = r["our_stance"], b["stance"].get(k)
        x = caps(r["name"])
        if now in ("W", "E"):
            since = (mem.get("races", {}).get(k) or {}).get("war_since", -1)
            fought = b["fought"].get(k, -1)
            if now == "W" and k not in b["war_said"] and since >= 0 and fought >= since:
                b["war_said"].append(k)
                cands.append(("war", PRIORITY["war"], {"X": x}))
        else:
            if k in b["war_said"]:
                b["war_said"].remove(k)
            if before in ("W", "E") and now == "N":
                cands.append(("peace", PRIORITY["peace"], {"X": x}))
        if now == "A":
            asked = (mem.get("races", {}).get(k) or {}).get("ally_req", -1)
            if k not in b["ally_said"] and asked is not None and asked >= 0:
                b["ally_said"].append(k)
                cands.append(("alliance", PRIORITY["alliance"], {"X": x}))
        elif k in b["ally_said"]:
            b["ally_said"].remove(k)
        b["stance"][k] = now

    # number 1 in a statistic: only from our own ranks (every race is ranked, DECISIONS A-06);
    # a figure of zero, or the first turns when everyone is tied, is not worth a boast
    ranks = e.get("ranks") or {}
    vals = e.get("stats") or {}
    firsts = sorted(s for s, n in ranks.items() if n == 1 and s in STAT_LABEL
                    and (vals.get(s) or 0) > 0 and turn >= IMPROVE_FROM)
    for s in firsts:
        if s not in b["rank1"]:
            cands.append(("rank", PRIORITY["rank"], {"S": STAT_LABEL[s]}))
    b["rank1"] = firsts

    # big turn-on-turn gains in our own figures (whole percentages only)
    st = dict(e.get("stats") or {})
    now_fig = {"HAP": st.get("HAP", 0.0), "POP": st.get("POP", 0.0), "NNP": st.get("NNP", 0.0),
               "EU": float(e.get("eu") or 0), "SYS": st.get("SYS", 0.0),
               "TEC": st.get("TEC", 0.0), "VP": float(vp)}
    prev = b["stats"]
    if prev and turn >= IMPROVE_FROM:
        best = None
        for key, base, gain, pct in IMPROVE:
            a, c = float(prev.get(key, 0.0)), float(now_fig[key])
            if a >= base and c - a >= gain:
                p = int(round(100.0 * (c - a) / a))
                if p >= pct and (best is None or p > best[0]):
                    best = (p, key)
        if best is not None:
            cands.append(("improve", PRIORITY["improve"], {"N": str(best[0]),
                                                            "W": IMPROVE_WORDS[best[1]]}))
    b["stats"] = now_fig
    b["t"] = turn

    out = []
    for kind, pr, f in cands:
        base_kind = {"reclaim": "capture", "capture_anon": "capture",
                     "future": "tech"}.get(kind, kind)
        last = b["last"].get(base_kind, -99)
        if turn - last < COOLDOWN.get(base_kind, 0):
            continue
        tpl = TEMPLATES[kind].get(persona) or TEMPLATES[kind]["builder"]
        text = rng.choice(tpl).format(R=R, **f)
        out.append({"kind": base_kind, "priority": pr, "text": text, "tie": rng.random()})
    return out


def select(cands: dict[int, list[dict]], level: str) -> list[dict]:
    """Apply the limits: one per bot (its best), then the game-wide cap for the level."""
    cap, floor = LIMITS.get(level, LIMITS["normal"])
    best = []
    for eid, lst in sorted(cands.items()):
        lst = [c for c in lst if c["priority"] >= floor]
        if lst:
            c = max(lst, key=lambda c: (c["priority"], c["tie"]))
            best.append(dict(c, **{"from": eid}))
    best.sort(key=lambda c: (-c["priority"], -c["tie"], c["from"]))
    return best[:cap]


def turn_chat(state: GameState, results) -> list[dict]:
    """The computer empires' boasts for the turn just run: [{"from", "kind", "text"}], then
    their technology trade offers to human races, private ({"to", "offer"} too; trade.py)."""
    from ..view import view
    from . import trade
    from .memory import memory
    level = getattr(state, "chatter", "normal") or "normal"
    cands: dict[int, list[dict]] = {}
    offers: list[tuple] = []
    for e in state.empires.values():
        if e.kind != NPR:
            continue
        mem = memory(state, e.id)
        v = view(state, mem.get("inbox"), e.id)
        cands[e.id] = boasts(v, mem, Rng(state.seed, state.turn, f"chat{e.id}"))
        trade.close_human_offers(mem, v)
        if level != "off":
            o = trade.human_offer_candidate(v, mem, Rng(state.seed, state.turn, f"offer{e.id}"))
            if o is not None:
                offers.append((e.id, o, mem))
    chosen = select(cands, level)
    for c in chosen:
        memory(state, c["from"])["brag"]["last"][c["kind"]] = state.turn
    out = [{"from": c["from"], "kind": c["kind"], "text": c["text"]} for c in chosen]
    # offers aren't boasts: "quiet" still allows them; at most one per human race a turn
    offers.sort(key=lambda x: (-x[1]["tie"], x[0]))
    sent: set[int] = set()
    for eid, o, mem in offers:
        if len(sent) >= trade.OFFERS_PER_TURN or o["to"] in sent:
            continue
        sent.add(o["to"])
        rec = trade.record_human_offer(mem, eid, state.turn, o)
        persona = (mem.get("persona") or {}).get("name", "builder")
        out.append({"from": eid, "kind": "offer", "to": o["to"],
                    "text": trade.human_offer_text(caps(state.empires[eid].name), persona,
                                                   o["terms"], rec["until"]),
                    # an ANY offer (G-23) has one Accept, "TTNPR ANY <any> <give>", and
                    # doesn't list what the bot would take
                    "offer": {"id": rec["id"], "give": rec["give"],
                              "wants": [] if rec.get("any") else rec["wants"],
                              "any": rec.get("any"), "until": rec["until"]}})
    return out


__all__ = ["turn_chat", "boasts", "select", "TEMPLATES", "PRIORITY", "caps"]
