"""Technology trades between computer empires (Dave 2026-11-15: "bot-to-bot only for now").

A trade is the rules' TTNPR order (rules:2532-2541): the offerer gives one of its technologies for
one of the computer empire's, each side paying half the cost of what it gives; the engine rolls
acceptance from the costs (DECISIONS C-07), an even swap always being accepted.  So that the
receiving bot really agrees (and so that nobody needs to know anyone else's technologies), the two
bots settle the terms first by MESSAGE, exactly as players would:

  turn T    A -> B   "[TRADE-OFFER give=3,12 want=5,14]": techs A can give, techs A could use
  turn T+1  B -> A   "[TRADE-ACCEPT give=5 get=12 due=T+2]" (or "[TRADE-DECLINE]"): B picks one
                     tech it owns from A's wants and one of A's offers it lacks, of the same cost
  turn T+2  A        TTNPR 12 5 B.  B keeps half the cost of tech 5 in hand that turn, buys no
                     technology (the trade is its purchase, rules:274) and doesn't buy tech 12.

A bot has at most one trade open at a time, offers to computer empires it is at peace with and
in good standing, never to the leader (the race holding the most systems it knows of, well
ahead, `diplo.leader`), and accepts only a swap that helps it (its own research valuation,
`econ.tech_score`) from a race that isn't the leader and doesn't threaten it.

Only computer empires take part in this handshake (view race kind "npr").  Human players get
offers in private chat instead (bottom of this module, DECISIONS A-08), judged with the same
valuation.  `swap_for(w, partner, their_give, their_want)` - the acceptance decision - and
`offer_terms(w)` are pure functions of the bot's own view.
"""
from __future__ import annotations

import re

from ..data.techs import FUTURE_TECH, TECHS, missing_prereqs
from .diplo import intruders, leader
from .econ import income, reserve, tech_score
from .memory import log
from .trace import note

TAG = re.compile(r"\[TRADE-(OFFER|ACCEPT|DECLINE)([^\]]*)\]")
OFFER_EVERY = 6               # turns between our offers
MIN_VALUE = 8.0               # a swap must be worth at least this to us (econ.tech_score)


def _nums(s: str, key: str) -> list[int]:
    m = re.search(rf"{key}=([0-9,]*)", s)
    if not m or not m.group(1):
        return []
    return [int(x) for x in m.group(1).split(",") if x.isdigit()]


def tradeable(t: int) -> bool:
    return t in TECHS and t not in (0, FUTURE_TECH)


def offer_terms(w, spare: int = 0) -> tuple[list[int], list[int]]:
    """(what we can give, what we would like) - our own technologies only.  The wish list holds
    what we can't buy outright with `spare` EU (we might buy it before the reply comes) but can
    pay half of."""
    give = sorted(t for t in w.techs if tradeable(t))
    want = sorted((t for t in TECHS if tradeable(t) and t not in w.techs
                   and not missing_prereqs(w.techs, t)
                   and spare < TECHS[t].cost <= 2 * max(0, spare)),
                  key=lambda t: (-tech_score(w, t, False), t))[:20]
    return give, sorted(want)


def _good_partner(w, rid, kind: str = "npr") -> bool:
    if rid not in w.races or w.races[rid]["kind"] != kind or w.at_war(rid):
        return False
    if rid == leader(w):
        return False                           # never feed the leader
    r = w.mem["races"].get(str(rid)) or {}
    if r.get("griev", 0) > 8:
        return False
    # a race whose warships hover near our worlds isn't helped: within 3 squares, or within
    # one move (the A-12 reason for war, which the bot is declaring this turn)
    return not any(c.owner == rid and c.st.attack > 0 and w.dist_to_us(c.x, c.y) <= 3
                   for c in w.contacts) and not intruders(w, rid)


def swap_for(w, partner: int, their_give: list[int], their_want: list[int]):
    """The swap we would accept: (we give, we get), or None.  An even swap (same cost, so the
    engine always accepts) of the most valuable technology we lack against the least valuable one
    they want that we own."""
    if not _good_partner(w, partner):
        return None
    gets = [t for t in their_give if tradeable(t) and t not in w.techs
            and not missing_prereqs(w.techs, t)]
    gives = [t for t in their_want if tradeable(t) and t in w.techs]
    best = None
    for g in gets:
        v = tech_score(w, g, False)
        if v < MIN_VALUE:
            continue
        for y in gives:
            if TECHS[y].cost != TECHS[g].cost:
                continue
            key = (v - 0.5 * tech_score(w, y, False), -g, -y)
            if best is None or key > best[0]:
                best = (key, y, g)
    if best is None:
        return None
    return best[1], best[2]


def hold_due(w, plan) -> None:
    """First thing in the turn: a trade we agreed to is due, so half the cost of what we give
    stays in hand and no technology is bought (the trade is this turn's purchase, rules:274).
    An open offer to a human player (below) keeps half the cost of what we offered in hand, and
    we don't buy any technology we asked for, so the trade can't fail on our side."""
    ho = open_human_offer(w.mem, w.turn)
    if ho is not None:
        plan.no_buy.update(ho["wants"])
        plan.pay(TECHS[ho["give"]].cost // 2, "offer hold")
    acc = w.mem.get("accept")
    if acc and acc["due"] == w.turn:
        plan.pt_done = True
        plan.no_buy.add(acc["get"])
        plan.pay(TECHS[acc["give"]].cost // 2, "trade")
        return
    offer = w.mem.get("offer")
    if not offer or w.turn > offer["until"]:
        return
    # our open offer: an acceptance may have come (carry it out now, before other spending)
    for msg in (w.results.get("messages") or []):
        m = TAG.search(msg.get("text") or "")
        if m and msg.get("from") == offer["with"] and m.group(1) != "OFFER":
            w.mem["offer"] = None
            w.mem.setdefault("silent", {})[str(offer["with"])] = 0
            if m.group(1) == "ACCEPT":
                _execute(w, plan, offer["with"], offer, m.group(2))
            return
    # nothing is held back while we wait (holding money or techs cost research turns): if we
    # can't pay when the acceptance comes, or bought the tech meanwhile, we just don't send it


def plan_trades(w, plan, rng) -> None:
    """Read trade messages; keep a trade we accepted (it is due this turn); carry out a trade the
    other side accepted; answer offers; make an offer now and then."""
    mem = w.mem
    offer, acc = mem.get("offer"), mem.get("accept")
    if offer and w.turn > offer["until"]:
        silent = mem.setdefault("silent", {})       # a race that never answers isn't asked
        silent[str(offer["with"])] = silent.get(str(offer["with"]), 0) + 1   # again and again
        mem["offer"] = offer = None
    if acc and w.turn > acc["due"]:
        mem["accept"] = acc = None
    inbox = []
    for msg in (w.results.get("messages") or []):
        m = TAG.search(msg.get("text") or "")
        rid = msg.get("from")
        if m and isinstance(rid, int) and rid in w.races:
            inbox.append((m.group(1), m.group(2), rid))
    if acc:
        plan.no_buy.add(acc["get"])                 # (hold_due kept the money in hand)
    human_open = open_human_offer(mem, w.turn) is not None   # one trade at a time

    # answer offers: accept the best one we like (one trade at a time), decline the rest
    offers = [(rid, body) for kind, body, rid in inbox if kind == "OFFER"]
    pick = None
    if not mem.get("accept") and not human_open:
        best = None
        for rid, body in offers:
            swap = swap_for(w, rid, _nums(body, "give"), _nums(body, "want"))
            if swap and plan.eu - reserve(w) >= TECHS[swap[0]].cost // 2 + 20:
                v = tech_score(w, swap[1], False)
                if best is None or (v, -rid) > best[0]:
                    best = ((v, -rid), rid, swap)
        if best is not None:
            _, pick, (y, g) = best
            mem["accept"] = {"with": pick, "give": y, "get": g, "due": w.turn + 1}
            plan.no_buy.add(g)
            plan.pay(TECHS[y].cost // 2, "trade hold")   # so it's still there next turn
            plan.message(w.race_name(pick), _accept_text(w, y, g, w.turn + 1),
                         rc="trade.accept")
            note("trade_accept", race=pick, give=y, get=g)
    for rid, _ in offers:
        if rid != pick:
            plan.message(w.race_name(rid), f"The {w.name} have nothing to exchange this time. "
                         "[TRADE-DECLINE]", rc="trade.decline")
    # make an offer now and then
    if mem.get("offer") or human_open or w.turn < 8 or \
            w.turn - mem.get("last_offer", -99) < OFFER_EVERY:
        return
    silent = mem.get("silent", {})
    partners = [rid for rid in w.contacted() if _good_partner(w, rid)
                and (w.mem["races"].get(str(rid)) or {}).get("good", 0) >= 2
                and silent.get(str(rid), 0) < 2]
    if not partners or income(w)[0] < 25:
        return
    give, want = offer_terms(w, plan.eu - reserve(w) - 60)
    if not give or not want:
        return
    rid = partners[rng.below(len(partners))]
    mem["last_offer"] = w.turn
    mem["offer"] = {"with": rid, "offered": give, "wanted": want, "t": w.turn,
                   "until": w.turn + 2}
    plan.message(w.race_name(rid), _offer_text(w, give, want), rc="trade.offer")
    note("trade_offer", race=rid, give=len(give), want=len(want))


def _execute(w, plan, rid, offer, body) -> None:
    """The other side accepted our offer: TTNPR, if it is still sound from our own view."""
    give, get = (_nums(body, "get") or [None])[0], (_nums(body, "give") or [None])[0]
    ok = (give in w.techs and get is not None and get not in w.techs and get in TECHS
          and not missing_prereqs(w.techs, get) and give in offer["offered"]
          and get in offer["wanted"] and not w.at_war(rid)
          and TECHS[give].cost == TECHS[get].cost)
    if not ok or plan.pt_done:
        return
    half = TECHS[give].cost // 2
    if plan.eu - reserve(w) < half:
        return
    plan.add("TTNPR", f"tech trade agreed with the {w.race_name(rid)}", rc="trade.execute",
             give=give, want=get, race=w.race_name(rid))
    plan.pt_done = True
    plan.pay(half, "trade")
    w.techs.add(get)
    mem = w.mem
    mem.setdefault("trades", []).append([w.turn, rid, give, get])
    del mem["trades"][:-10]
    log(mem, w.turn, "trade", race=rid, give=give, get=get)


def _offer_text(w, give, want) -> str:
    return (f"The {w.name} trade ministry proposes a technology exchange: one of ours for one "
            f"of yours of equal value.  [TRADE-OFFER give={','.join(map(str, give))} "
            f"want={','.join(map(str, want))}]")


def _accept_text(w, give, get, due) -> str:
    return (f"The {w.name} accept: our {TECHS[give].name} for your {TECHS[get].name}.  "
            f"[TRADE-ACCEPT give={give} get={get} due={due}]")


# ---- offers to human players, in private chat (Dave 2026-11-15; DECISIONS A-08) ------------
#
# Computer empires don't read chat (W-07), but they may post a trade offer to a contacted human
# race: "The GROACHI offer Core Mining for your Bioengineered Foods.  Accept by this turn's end
# (turn 13)."  The human accepts by giving the matching TTNPR order (the chat's Accept button
# adds it to the draft); the engine then always accepts that exact swap (`offer_open`, read by
# orders_exec._ttnpr), so the bot honours its word.  Made at the end of turn n from the bot's
# own view (`npr.chatter.turn_chat`), valid for the orders of turn n+1 only.
#
# What the bot may know of a human's technologies (`human_techs`): its own SOT reports, the
# TTNPR offers that human made it (what was offered, and on a trade what it got), technologies
# the human gifted it, and trades with it.  If it knows the human has a technology it wants it
# names it; otherwise it offers one of its own for "any 1000 EU technology of yours that we
# lack" (an ANY offer, DECISIONS G-23; until 2026-11-19 it listed up to three it would like).

HUMAN_FROM = 8              # no offers before this turn
HUMAN_EVERY = 6             # turns between one bot's offers to humans
PAIR_GAP = 8                # after an offer to a race closes, turns before it is offered again
REPEAT_GAP = 16             # turns before the same technology is offered to the same race again
OFFERS_PER_TURN = 2         # game-wide, at chatter "normal" or "quiet" (none when "off")
MAX_ALTS = 3
MAX_OVER = 2.0              # we never give a technology costing more than twice what we get
OFFER_TAIL = {"aggressive": "Take it or leave it.", "builder": "A sensible exchange.",
              "opportunist": "A bargain, frankly."}


def open_human_offer(mem: dict, turn: int):
    """Our open offer to a human (one at a time), valid for the orders of `turn`, or None."""
    for o in (mem.get("hoffers") or {}).values():
        if o["t"] < turn <= o["until"]:
            return o
    return None


def offer_open(mem: dict, rid: int, give: int, want: int, turn: int) -> bool:
    """Does this computer empire have an open offer to race `rid` that a `TTNPR give want` from
    that race, executed on `turn`, takes up?  (The engine then always accepts.)  `give` and
    `want` are the technologies actually swapped: for an ANY side, the one picked
    (`any_pick`), so `TTNPR ANY 1000 33 X` takes up an "any 1000 EU technology" offer when the
    pick is one we said we would take."""
    o = open_offer_to(mem, rid, turn)
    return bool(o) and want == o["give"] and give in o["wants"]


def open_offer_to(mem: dict, rid: int, turn: int):
    """Our offer to race `rid` that is open for the orders of `turn`, or None."""
    o = (mem.get("hoffers") or {}).get(str(rid))
    return o if o and o["t"] < turn <= o["until"] else None


# ---- TTNPR "ANY <cost>" (Dave 2026-11-19, DECISIONS G-23) ------------------------------------
#
# The engine resolves an ANY side when the turn runs, with the computer empire's own knowledge
# (its own technologies and the swap it is offered; the player's technologies are what it is
# being shown in the trade).  It values technologies with the same research valuation as every
# other trade (`econ.tech_score`): of its own it gives the one it values least, of the
# player's it takes the one it values most; ties go to the lower tech number.

class _Valuer:
    """The few parts of the world model `econ.tech_score` reads: persona, memory, turn, techs."""

    def __init__(self, mem: dict, techs, turn: int):
        self.mem, self.techs, self.turn = mem, set(techs), turn

    @property
    def persona(self) -> dict:
        return self.mem["persona"]

    def has_tech(self, t: int) -> bool:
        return t == 0 or t in self.techs


def any_pick(mem: dict, techs, turn: int, cands, most: bool):
    """The technology a computer empire with memory `mem` and technologies `techs` picks from
    `cands`: the one it values most (`most`, what it takes) or least (what it gives); None if
    `cands` is empty.  Deterministic: the valuation is, and ties go to the lower number."""
    cands = sorted(cands)
    if not cands:
        return None
    w = _Valuer(mem, techs, turn)
    sign = -1.0 if most else 1.0
    return min(cands, key=lambda t: (sign * tech_score(w, t, False), t))


def human_techs(mem: dict, rid: int) -> tuple[set, bool]:
    """(technologies we know race `rid` owns, whether that is a full list): technologies only
    grow, so every report is a lower bound; an SOT report is complete as of its turn."""
    k = str(rid)
    sot = ((mem.get("spy") or {}).get("techs") or {}).get(k)
    known = set(((mem.get("htechs") or {}).get(k) or {}).get("has", []))
    if sot:
        known |= set(sot["techs"])
    known.discard(0)
    return known, bool(sot)


def _learn_human(mem: dict, races: dict, events: list, turn: int) -> None:
    """What this turn's own report tells us of human races' technologies."""
    for ev in events:
        d = ev.get("data") or {}
        rid = d.get("race")
        if not isinstance(rid, int) or (races.get(rid) or {}).get("kind") != "player":
            continue
        got = []
        if ev.get("kind") == "trade_offered":
            got = [d.get("give")] + ([d.get("want")] if d.get("ok") else [])
        elif ev.get("kind") == "tech_received":
            got = [d.get("tech")]
        got = [t for t in got if isinstance(t, int) and t in TECHS]
        if got:
            h = mem.setdefault("htechs", {}).setdefault(str(rid), {"has": [], "t": turn})
            h["has"] = sorted(set(h["has"]) | set(got))
            h["t"] = turn


def close_human_offers(mem: dict, view: dict) -> None:
    """End of turn n: offers valid up to turn n close (taken or expired), and what the report
    says of human technologies is remembered.  Runs whatever the chatter setting."""
    turn = view["game"]["turn"]
    races = {r["id"]: r for r in view["races"]}
    events = (view.get("results") or {}).get("events") or []
    _learn_human(mem, races, events, turn)
    ho = mem.get("hoffers")
    if not ho:
        return
    for k in [k for k, o in ho.items() if o["until"] <= turn]:
        o = ho.pop(k)
        taken = any(ev.get("kind") == "trade_offered" and (ev.get("data") or {}).get("ok")
                    and (ev.get("data") or {}).get("race") == int(k)
                    and (ev.get("data") or {}).get("want") == o["give"] for ev in events)
        hist = mem.setdefault("hoffer_log", [])
        hist.append({"t": o["t"], "to": int(k), "give": o["give"], "wants": o["wants"],
                     "closed": turn, "taken": taken})
        del hist[:-12]
        if taken:
            log(mem, turn, "trade", race=int(k), give=o["give"], human=True)


def _value_swap(w, x: int, y: int) -> float | None:
    """What getting y for x is worth to us, or None if we wouldn't: even swaps (same cost or
    cheaper for us) or ones our own valuation favours enough to cover the extra cost."""
    cx, cy = TECHS[x].cost, TECHS[y].cost
    if cx > MAX_OVER * cy:
        return None
    v = tech_score(w, y, False)
    if v < MIN_VALUE:
        return None
    net = v - 0.5 * tech_score(w, x, False) - max(0, cx - cy) / 25.0
    return net if net >= MIN_VALUE else None


def human_offer_terms(w, rid: int):
    """The offer we would make race `rid` now, from our own view and memory: {"give": our tech,
    "wants": [their techs we'd take, best first], "known": named from what we know}, or None."""
    if not _good_partner(w, rid, "player"):
        return None
    mem = w.mem
    known, full = human_techs(mem, rid)
    recent = [h for h in mem.get("hoffer_log") or [] if h["to"] == rid]
    if recent and w.turn - max(h["closed"] for h in recent) < PAIR_GAP:
        return None
    stale = {h["give"] for h in recent if w.turn - h["t"] < REPEAT_GAP}
    wants = [t for t in TECHS if tradeable(t) and t not in w.techs
             and not missing_prereqs(w.techs, t)]
    named = [t for t in wants if t in known]
    if named:
        wants = named
    elif full:
        return None                     # we know everything they have: nothing we want
    gives = [t for t in sorted(w.techs) if tradeable(t) and t not in known and t not in stale
             and not (full and missing_prereqs(known | {0}, t))]
    if not named:
        return _any_offer_terms(w, gives, wants)
    best = None
    pairs: dict[int, list] = {}
    for x in gives:
        for y in wants:
            net = _value_swap(w, x, y)
            if net is None:
                continue
            even = TECHS[x].cost <= TECHS[y].cost
            pairs.setdefault(x, []).append((even, net, -y, y))
            key = (even, net, -x, -y)
            if best is None or key > best[0]:
                best = (key, x)
    if best is None:
        return None
    x = best[1]
    if w.eu - reserve(w) < TECHS[x].cost // 2 + 60:
        return None
    alts = [p[3] for p in sorted(pairs[x], reverse=True)][:MAX_ALTS]
    return {"give": x, "wants": alts, "known": bool(named)}


def _any_offer_terms(w, gives: list[int], wants: list[int]):
    """We don't know which of the technologies we want the human has (DECISIONS G-23): offer one
    of ours for "any <cost> EU technology of yours that we lack and can use", the cost whose
    technologies we'd take are, on average, the best swap for it.  "wants" keeps every one of
    that cost we would take (best first): when the turn runs the engine picks the human's one we
    value most, preferring these, and honours the offer if the pick is one of them."""
    best = None
    for x in gives:
        by_cost: dict[int, list] = {}
        for y in wants:
            net = _value_swap(w, x, y)
            if net is not None:
                by_cost.setdefault(TECHS[y].cost, []).append((net, -y, y))
        for c, lst in by_cost.items():
            key = (TECHS[x].cost <= c, sum(n for n, _, _ in lst) / len(lst), len(lst), -x, -c)
            if best is None or key > best[0]:
                best = (key, x, c, lst)
    if best is None:
        return None
    _, x, c, lst = best
    if w.eu - reserve(w) < TECHS[x].cost // 2 + 60:
        return None
    return {"give": x, "wants": [y for *_, y in sorted(lst, reverse=True)], "known": False,
            "any": c}


def _names(ts: list[int], last: str) -> str:
    n = [TECHS[t].name for t in ts]
    return n[0] if len(n) == 1 else ", ".join(n[:-1]) + f" {last} " + n[-1]


def human_offer_text(race_caps: str, persona: str, terms: dict, until: int) -> str:
    x, ys = TECHS[terms["give"]].name, terms["wants"]
    if terms.get("any"):
        what = f"any {terms['any']} EU technology of yours that we lack"
    elif terms["known"]:
        what = "your " + _names(ys, "or your") if len(ys) > 1 else f"your {TECHS[ys[0]].name}"
        what = what.replace(", ", ", your ") if len(ys) > 2 else what
    else:
        what = "any one of: " + _names(ys, "or") if len(ys) > 1 else f"your {TECHS[ys[0]].name}"
    return (f"The {race_caps} offer {x} for {what}. Accept by this turn's end (turn {until}). "
            f"{OFFER_TAIL.get(persona, OFFER_TAIL['builder'])}")


def human_offer_candidate(view: dict, mem: dict, rng):
    """This computer empire's possible offer this turn: {"to", "terms", "tie"} or None.  Pure
    except for the world model's scan bookkeeping, so it is given a copy of the memory."""
    from .world import build
    turn = view["game"]["turn"]
    if turn < HUMAN_FROM or mem.get("hoffers") or mem.get("offer") or mem.get("accept"):
        return None
    if turn - mem.get("last_hoffer", -99) < HUMAN_EVERY:
        return None
    humans = [r["id"] for r in view["races"] if r["kind"] == "player"
              and r["our_stance"] not in ("W", "E")]
    if not humans:
        return None
    import copy
    w = build(view, copy.deepcopy(mem))
    if not w.systems or income(w)[0] < 25:
        return None
    cands = [(rid, t) for rid in humans if (t := human_offer_terms(w, rid)) is not None]
    if not cands:
        return None
    rid, terms = cands[rng.below(len(cands))]
    return {"to": rid, "terms": terms, "tie": rng.random()}


def record_human_offer(mem: dict, eid: int, turn: int, cand: dict) -> dict:
    """Remember the offer we make (so we hold the money and the engine honours it)."""
    t = cand["terms"]
    o = {"id": f"{turn}-{eid}-{cand['to']}", "t": turn, "until": turn + 1, "give": t["give"],
         "wants": list(t["wants"]), "known": t["known"]}
    if t.get("any"):
        o["any"] = t["any"]
    mem.setdefault("hoffers", {})[str(cand["to"])] = o
    mem["last_hoffer"] = turn
    note("trade_offer_human", race=cand["to"], give=t["give"], wants=list(t["wants"]),
         any=t.get("any"))
    return o


__all__ = ["plan_trades", "hold_due", "swap_for", "offer_terms", "TAG", "offer_open",
           "open_human_offer", "human_offer_terms", "human_offer_candidate",
           "record_human_offer", "close_human_offers", "human_techs", "human_offer_text",
           "any_pick", "open_offer_to"]
