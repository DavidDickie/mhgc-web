"""Diplomacy for the bot, learned only from its own turn report (view["results"]).

* Standing per race: grievance from fights it started with us, ships and troops we lost, systems
  it took, spies we caught; goodwill from gifts, peaceful neighbourliness and MESSAGEs asking for
  peace or friendship.  Grievance fades by the personality's `forgive`.
* Space claims: armed ships loitering near our worlds get a warning in Dave's words (rules:249-251);
  if they stay, it counts against their owner.
* War when grievance passes the personality's threshold.
* Peace when overmatched: the enemy's observed warships near us outweigh ours, or we keep losing
  systems; or when the war has gone quiet.  Peace needs both sides' EWA in the same turn, so the
  offer is repeated for a few turns with a MESSAGE saying so.
* War-weariness (DECISIONS A-10): a long war with nothing gained, attacking or defending, brings
  a standing peace offer (EWA every turn, a MESSAGE every few turns); sooner against a much
  stronger enemy, later for the aggressive.  After a peace, a truce.
* Proximity war (DECISIONS A-12, Dave 2026-11-20): an armed ship of a race we are not allied
  with, seen within one move (its speed, or its fleet's slowest seen ship) of one of our systems
  and not at one of its own worlds, is a declaration of intent: DW at once, whatever the
  grievance.  No peace is offered (no EWA) while such ships are still within one move.
* Alliances against the leader: the race that holds the most systems we know of (well ahead of
  us) is not offered alliances; races in good standing are, the more readily when there is such a
  leader to stand against.  NPRs and players are treated alike (they play the same rules).
"""
from __future__ import annotations

from collections import Counter

from .econ import style
from .memory import log, race
from .trace import note
from .world import dist

TAUNTS = (
    "Roses are red,\nViolets are blue,\nYour intrusion is a gas,\nand soon your warship will be "
    "too",
    "Your unprovoked aggression is intolerable.\nBe forwarned that this outrage will be met "
    "with appropriate retaliation!",
    "Your ship, which has clearly wandered off course, will be met with\nour warship escort "
    "shortly.  Do not be alarmed if it suddenly vaporizes!",
)
PEACE_WORDS = ("peace", "truce", "ceasefire", "cease fire", "sorry", "apolog", "end war",
               "end the war", "armistice")
ALLY_WORDS = ("ally", "alliance", "friend", "cooperat")
CAP = 100.0


def notice(w, text: str) -> str:
    return f"The {w.name} ambassador sends the following official notice:\n\n{text}"


def grieve(r, amount, turn, why):
    r["griev"] = min(CAP, r["griev"] + amount)
    r["why"].append([turn, round(amount, 1), why])
    del r["why"][:-6]


def learn(w) -> None:
    """Fold last turn's report into the standings, then let grudges fade."""
    res = w.results
    turn = w.turn
    mem = w.mem
    name_of = {rid: d["name"] for rid, d in w.races.items()}
    for cl in res.get("combats") or []:
        ours = {s["number"] for s in cl.get("ships", []) if s["owner"] == w.eid}
        our_ct = {t["number"] for t in cl.get("troops", []) if t["owner"] == w.eid}
        near_home = w.dist_to_us(cl["x"], cl["y"]) <= w.persona["claim"]
        for b in cl.get("participants", []):
            if b in (0, w.eid) or b not in w.races:
                continue
            key = f"{min(b, w.eid)},{max(b, w.eid)}"
            rtext = (cl.get("relations") or {}).get(key, "")
            lost = sum(1 for ln in cl.get("lines", []) if ln.get("by") == b and
                       ln.get("ship") in ours and "DESTROYED" in ln.get("text", ""))
            lost_ct = sum(1 for ln in cl.get("lines", []) if ln.get("by") == b and
                          ln.get("ct") in our_ct and "destroyed" in ln.get("text", ""))
            g = 0.0
            if rtext == f"SURPRISE ATTACK by {name_of.get(b)}":
                g += 25 if near_home else 8
            elif rtext == "ATTACK" and cl.get("owner_before") == w.eid:
                g += 12
            elif rtext == "ATTACK" and cl.get("owner_before") != b:
                g += 3
            g += 4 * lost + 3 * lost_ct
            if w.at_war(b):
                # the war's battle account (war-weariness, Dave 2026-11-16)
                theirs = {s["number"] for s in cl.get("ships", []) if s["owner"] == b}
                kills = sum(1 for ln in cl.get("lines", []) if ln.get("by") == w.eid and
                            ln.get("ship") in theirs and "DESTROYED" in ln.get("text", ""))
                r = race(mem, b, turn)
                r["w_kills"] = r.get("w_kills", 0) + kills
                r["w_losses"] = r.get("w_losses", 0) + lost
            if g > 0:
                r = race(mem, b, turn)
                grieve(r, g, turn, f"combat {rtext or '?'} at {cl['x']},{cl['y']}")
                r["last_fight"] = turn
    for ev in res.get("events") or []:
        rid = (ev.get("data") or {}).get("race")
        if not isinstance(rid, int) or rid in (0, w.eid) or rid not in w.races:
            continue
        r = race(mem, rid, turn)
        k = ev.get("kind")
        if k == "system_lost":
            grieve(r, 50, turn, f"took system {ev.get('system')}")
            r["last_fight"] = turn
            r["w_lost"] = r.get("w_lost", 0) + 1
            log(mem, turn, "system_lost", race=rid, system=ev.get("system"))
        elif k == "system_captured":
            r["w_caps"] = r.get("w_caps", 0) + 1
            r["w_gain_t"] = turn
        elif k == "eu_received":
            r["good"] += min(40.0, (ev.get("data") or {}).get("amount", 0) / 10.0)
        elif k == "tech_received":
            r["good"] += 30.0
        elif k == "spy_detected":
            grieve(r, 8, turn, "spy caught")
    for msg in res.get("messages") or []:
        rid = msg.get("from")
        if not isinstance(rid, int) or rid in (0, w.eid) or rid not in w.races:
            continue
        text = (msg.get("text") or "").lower()
        r = race(mem, rid, turn)
        if any(x in text for x in PEACE_WORDS):
            r["peace_req"] = turn
        if any(x in text for x in ALLY_WORDS):
            r["ally_req"] = turn
    f = w.persona["forgive"]
    for rid in w.contacted():
        r = race(mem, rid, turn)
        r["griev"] = round(r["griev"] * (1 - f), 3)
        r["good"] = round(r["good"] * 0.98, 3)
        if w.at_war(rid) and r["war_since"] < 0:
            war_start(r, turn)
            grieve(r, 10, turn, "declared war on us")
            log(mem, turn, "war_on_us", race=rid)
        if not w.at_war(rid) and r["war_since"] >= 0:
            r["war_since"] = -1
            r["peace_offer"] = -1
            # a peace settles the score: the grudge that led to the war doesn't restart it the
            # next turn (2026-11-15 runs: peace-war-peace cycles); new grievances do
            r["griev"] = min(r["griev"], w.persona["war_at"] * 0.5)
            r.pop("started", None)
            r["peace_t"] = turn                  # a truce: no war of our choosing for a while
            mem["stats"]["peace"] += 1
            log(mem, turn, "peace", race=rid)


# War-weariness (Dave 2026-11-16, after his turn-45 game: Freepeople and Badhombres spent 35
# turns defending against a stronger human, upkeep over half their income, 7 and 11 techs).
# A war that has gone on WEARY_TURNS turns (by personality) with nothing gained from it lately
# (no system taken from them in the last WEARY_TURNS turns, and not clearly winning the battles)
# makes the bot offer peace, attacking or defending; sooner against a much stronger enemy.  The
# offer (EWA) stands every turn while weary, with a MESSAGE every WEARY_REOFFER turns.
WEARY_TURNS = {"aggressive": 14, "opportunist": 10, "builder": 8}
WEARY_STRONG = 0.6          # x the turns against a much stronger enemy
WEARY_REOFFER = 6
TRUCE = 12                  # turns after a peace in which a war of retaliation needs 2x grievance

WEARY_WORDS = (
    "Roses are red,\nViolets are blue,\nThis war is a bore,\nAnd so, frankly, are you.",
    "Our generals report that the war is going splendidly.  Our accountants report that it is "
    "going splendidly badly.",
    "We have made our point, and you have made yours.  Neither of us appears to be listening.",
)
STRONG_WORDS = (
    "Your warships are many and your manners are few.  We are prepared to overlook both.",
    "It has come to our attention that you have rather a lot of warships.  We would prefer "
    "that they go and be a lot somewhere else.",
)
PEACE_TAIL = "\n\nEnd the war with us (EWA) and there will be peace between us."


def war_start(r, turn) -> None:
    r["war_since"], r["peace_offer"] = turn, -1
    for k in ("w_caps", "w_lost", "w_kills", "w_losses", "weary", "weary_next", "w_pressed"):
        r.pop(k, None)


def war_weary(w, rid, r) -> tuple[bool, bool]:
    """(weary, much stronger) for a war with race rid, from our own record of it."""
    if r["war_since"] < 0:
        return False, False
    held = Counter(s.owner for s in w.known.values() if s.owner)
    their_near = sum(c.st.attack for c in w.contacts if c.owner == rid and c.st.attack > 0
                     and w.dist_to_us(c.x, c.y) <= 2 * max(1, c.st.move))
    if their_near > 0:
        r["w_pressed"] = r.get("w_pressed", 0) + 1
    length = w.turn - r["war_since"]
    mine = sum(sh.st.attack for sh in w.ships if sh.st.attack > 0)
    strong = held[rid] >= max(3, 1.3 * len(w.systems)) or their_near > 0.75 * max(1, mine) \
        or r.get("w_pressed", 0) >= 0.6 * max(1, length) and length >= 4
    need = WEARY_TURNS.get(w.persona.get("name"), 10) * (WEARY_STRONG if strong else 1.0)
    if length < need:
        return False, strong
    recent = w.turn - r.get("w_gain_t", -99) <= need
    winning = r.get("w_kills", 0) >= 2 * r.get("w_losses", 0) + 3 and \
        r.get("w_lost", 0) == 0 and any(m.get("race") == rid and m["state"] not in
                                        ("hold", "return") for m in w.mem["missions"])
    net = r.get("w_caps", 0) - r.get("w_lost", 0)
    return not (recent and net > 0) and not winning, strong


def weary_words(w, rng, strong: bool) -> str:
    pool = STRONG_WORDS if strong else WEARY_WORDS
    return pool[rng.below(len(pool))] + PEACE_TAIL


PROXIMITY_GRACE = 1         # turns after a peace in which ships near us are let leave


PROXIMITY_WORDS = (
    "Your warships are within striking distance of our worlds.  We do not wait to be struck.",
    "A warship one jump from our worlds is not a visit, it is a threat.  We have answered it.",
    "You have brought your guns to our doorstep.  Very well: we are at war.",
)
PROXIMITY_TAIL = "\n\nTake your warships out of reach of our worlds before you speak of peace."


def fleet_move(w, c) -> int:
    """How far a scanned ship can go next turn: its own speed, or the slowest ship we see in its
    fleet (a fleet moves at its slowest ship's speed)."""
    if c.fleet:
        mv = [x.st.move for x in w.contacts if x.owner == c.owner and x.fleet == c.fleet]
        if mv:
            return min(mv)
    return c.st.move


def intruders(w, rid=None) -> list:
    """Armed foreign ships (of race rid, or any race) that could reach one of our systems in a
    single turn's move, except those at one of their owner's own worlds (A-12).  Only what we
    see: this turn's scans and our map memory."""
    ours = [(s.x, s.y) for s in w.systems]
    out = []
    for c in w.contacts:
        if c.st.attack <= 0 or c.owner in (0, w.eid) or (rid is not None and c.owner != rid):
            continue
        here = w.system_at(c.x, c.y)
        if here is not None and not here.mine and here.owner == c.owner:
            continue
        mv = fleet_move(w, c)
        if any(dist(c.x, c.y, x, y) <= mv for x, y in ours):
            out.append(c)
    return out


def races_near(w, x: int, y: int, move: int, exclude=frozenset()) -> set:
    """Races (not at war with us, not in `exclude`; allies too) with a known
    world within `move` squares of (x, y), unless (x, y) is one of our own systems: a warship
    of ours stopping there would give them the A-12 reason for war."""
    for s in w.systems:
        if (s.x, s.y) == (x, y):
            return set()
    out = set()
    for k in w.known.values():
        o = k.owner
        if o == w.eid:
            o = -1          # remembered as ours but no longer ours (lost): someone else's now
        # A race we have no contact with yet may well have seen us: its worlds count too.  So
        # do our allies': an alliance (DA) is one-sided and we can't see whether they made one
        # with us, so we can't count on being their ally.
        # at war, they may come and go as they like, unless we are making peace this turn
        if not o or o == w.eid or o in exclude or (w.at_war(o) and o not in w.making_peace) or \
                (o in w.races and w.races[o]["kind"] not in ("player", "npr")):
            continue
        if dist(x, y, k.x, k.y) <= move:
            out.add(o)
    return out


def path_provokes(w, move: int, x: int, y: int, dx: int, dy: int, exclude=frozenset()) -> set:
    """The races a warship (or fleet) of speed `move` sailing from (x, y) to (dx, dy) would
    provoke at one of the places it stops at the end of a turn (A-12), the destination too."""
    from ..geometry import step
    from .world import board
    out: set = set()
    b = board()
    for _ in range(60):
        if (x, y) == (dx, dy):
            break
        x, y = step(x, y, dx, dy, max(1, move), b)
        out |= races_near(w, x, y, move, exclude)
    return out


def leader(w):
    """The race holding the most systems we know of, if well ahead of us."""
    held = Counter(s.owner for s in w.known.values() if s.owner)
    if not held:
        return None
    rid, n = held.most_common(1)[0]
    if n >= max(6, int(len(w.systems) * 1.3)):
        return rid
    return None


def plan(w, plan_, rng) -> None:
    p = w.persona
    lead = leader(w)
    my_att = sum(sh.st.attack for sh in w.ships)
    close = {}
    for c in intruders(w):
        close.setdefault(c.owner, []).append(c)
    for rid in w.contacted():
        r = race(w.mem, rid, w.turn)
        rname = w.race_name(rid)
        stance = w.stance(rid)
        intr = close.get(rid, [])
        if intr and not w.at_war(rid) and not w.allied(rid) and \
                w.turn - r.get("peace_t", -99) <= PROXIMITY_GRACE:
            # the peace was made last turn: their ships get a turn to leave
            note("proximity_grace", race=rid, ships=[c.number for c in intr])
        elif intr and not w.at_war(rid) and not w.allied(rid):
            # warships within one move of our worlds: war, whatever the grudge (A-12)
            note("war_reasons", race=rid, why=["proximity"], ships=[c.number for c in intr],
                 types=sorted({c.type for c in intr}), griev=round(r["griev"], 1))
            r["prox_t"] = w.turn
            declare(w, plan_, rid, "proximity",
                    PROXIMITY_WORDS[rng.below(len(PROXIMITY_WORDS))] + PROXIMITY_TAIL)
            continue
        near = [c for c in w.contacts if c.owner == rid and c.st.attack > 0
                and w.dist_to_us(c.x, c.y) <= p["claim"]
                and not (w.system_at(c.x, c.y) and w.system_at(c.x, c.y).owner == rid)]
        if near and stance not in ("A", "W", "E"):
            r["intrude"] += 1
            if r["warned"] < 0 or w.turn - r["warned"] >= 10:
                plan_.message(rname, notice(
                    w, TAUNTS[rng.below(len(TAUNTS))] +
                    f"\n\nWe claim all space within {p['claim']} squares of our systems!"),
                    rc="diplo.warning")
                r["warned"] = w.turn
                w.mem["stats"]["warnings"] += 1
                note("warning", race=rid, ships=len(near), claim=p["claim"])
            elif r["intrude"] > 2:
                grieve(r, min(6, 2 * len(near)), w.turn, "warships loitering in our space")
                note("grievance", race=rid, why="warships loitering after a warning",
                     griev=round(r["griev"], 1))
        else:
            r["intrude"] = 0
            if stance == "N" and r["griev"] < 1:
                r["good"] = min(20.0, r["good"] + 0.6)
        if w.at_war(rid):
            their = sum(c.st.attack for c in w.contacts if c.owner == rid)
            overmatched = their > 1.5 * max(1, my_att) and their > 6
            losing = any(h["ev"] == "system_lost" and h.get("race") == rid and
                         w.turn - h["t"] <= 3 for h in w.mem["history"])
            quiet = w.turn - max(r["last_fight"], r["war_since"])
            asked = r["peace_req"] >= 0 and w.turn - r["peace_req"] <= 3
            # a war we have no fleet in any more costs garrisons and upkeep for nothing: after a
            # conquest, peace sooner (keeping what we took) unless we hold a grudge
            idle = not any(m.get("race") == rid and m["state"] not in ("hold", "return")
                           for m in w.mem["missions"])
            settled = idle and r["griev"] < p["war_at"] / 2 and quiet >= 3
            # a war that isn't paying (Dave 2026-11-15, second round: "fight less"): no fleet
            # against them now and nothing taken from them in the last 10 turns, after 8 turns of
            # war; or any request for peace while we hold no strong grudge
            gained = any(h["ev"] == "mission_captured" and h.get("race") == rid and
                         w.turn - h["t"] <= 10 for h in w.mem["history"])
            unpaid = idle and not gained and r["war_since"] >= 0 and \
                w.turn - r["war_since"] >= 8 and r["griev"] < p["war_at"]
            weary, strong = war_weary(w, rid, r)
            if weary:
                r["weary"] = r.get("weary", 0) + 1
            else:
                r["weary"] = 0
            # a bot that is weary of a war takes a request for peace whatever its grudge
            take = asked and (r["griev"] < p["war_at"] * 1.5 or weary)
            reoffer = weary and w.turn >= r.get("weary_next", -1)
            if intr:
                # their warships are still within one move of our worlds (A-12): no peace
                # offer, no EWA (so no peace-then-war loop); the normal logic resumes once
                # they have gone
                note("peace_blocked", race=rid, ships=[c.number for c in intr])
                if weary:
                    r["weary_next"] = min(r.get("weary_next", w.turn), w.turn + 1)
                continue
            if (not weary and r["peace_offer"] < w.turn and
                    (overmatched or losing or take or quiet >= 7 or settled or unpaid)) or reoffer:
                r["peace_offer"] = w.turn + 3
                if weary:
                    r["weary_next"] = w.turn + WEARY_REOFFER
                    r["weary_offers"] = r.get("weary_offers", 0) + 1
                    text = weary_words(w, rng, strong)
                else:
                    text = "We are weary of this war.  End the war with us (EWA) and there " \
                        "will be peace between us."
                plan_.message(rname, notice(w, text), rc="diplo.peace_message")
                note("peace_reasons", race=rid, overmatched=overmatched, losing=losing,
                     asked=asked, quiet_turns=quiet, their_attack=their, our_attack=my_att,
                     weary=weary, stronger=strong)
                log(w.mem, w.turn, "peace_offer", race=rid,
                    why="overmatched" if overmatched else "losing" if losing else
                    "weary" if weary else "unpaid" if unpaid and quiet < 7 else "quiet")
            # weary: the offer stands every turn (EWA costs nothing; both sides must EWA in the
            # same turn, rules:739-741), the MESSAGE is repeated every WEARY_REOFFER turns
            if (r["peace_offer"] >= w.turn or weary) and stance == "W":
                plan_.add("EWA", "offer to end the war", race=rname)
                w.making_peace.add(rid)      # our warships keep out of their reach (A-12)
            continue
        if stance == "A":
            if r["griev"] >= p["war_at"] / 2 or rid == lead:
                plan_.add("EWA", "end the alliance", race=rname)
                w.races[rid]["stance"] = "N"
                log(w.mem, w.turn, "alliance_ended", race=rid)
            continue
        war_at = p["war_at"] * style(w.mem)["war_at_x"]     # slower to take offence
        if w.turn - r.get("peace_t", -99) < TRUCE:
            war_at *= 2                          # a fresh peace takes a real outrage to break
        if r["griev"] >= war_at:
            note("war_reasons", race=rid, griev=round(r["griev"], 1), war_at=war_at,
                 why=[x[2] for x in r["why"][-3:]])
            declare(w, plan_, rid, "retaliation", TAUNTS[1])
            continue
        standing = r["good"] - r["griev"]
        asked = r["ally_req"] >= 0 and w.turn - r["ally_req"] <= 3
        bar = p["ally_at"] * (0.5 if lead is not None and lead != rid else 1.0)
        if rid != lead and (standing >= bar or (asked and standing >= bar / 2)):
            plan_.add("DA", "an alliance", race=rname)
            w.races[rid]["stance"] = "A"
            w.mem["stats"]["alliances"] += 1
            log(w.mem, w.turn, "alliance", race=rid)
            note("alliance_reasons", race=rid, standing=round(standing, 1), bar=bar,
                 asked=asked, leader=lead)


def declare(w, plan_, rid, why, text="") -> bool:
    if rid in (0, w.eid) or rid not in w.races or w.at_war(rid):
        return False
    rname = w.race_name(rid)
    if w.allied(rid):
        plan_.add("EWA", "end the alliance before war", race=rname)
    plan_.add("DW", why, race=rname)
    w.races[rid]["stance"] = "W"
    r = race(w.mem, rid, w.turn)
    war_start(r, w.turn)
    r["started"] = w.turn                    # our war (war.plan_missions paces these)
    w.mem["stats"]["wars"] += 1
    log(w.mem, w.turn, "war", race=rid, why=why)
    if text:
        plan_.message(rname, notice(w, text), rc="diplo.war_notice")
    return True


__all__ = ["learn", "plan", "declare", "leader", "war_weary", "war_start", "dist", "intruders",
           "fleet_move", "races_near", "path_provokes"]
