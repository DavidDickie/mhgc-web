"""Turn phase 9: spy activities (rules:2741-2843, 2001-2012; gcreport.c:19-400).

Every spy that is at its system and has a mission rolls once for success and once for capture,
independently (rules:2746-2748).  Counter intelligence on the spy's system divides the success
chance and multiplies the capture chance by (EUs/10 + 1) (rules:2001-2005), for all missions.
Spies are never caught on their own empire's systems (gcreport.c own-system tests).
SUP (uprising) already took effect in the order phase (DECISIONS F-11); here it rolls capture.
"""
from __future__ import annotations

from ..data import constants as K
from ..data.artifacts import ARTIFACTS
from ..data.techs import TECHS
from .context import TurnContext
from .leaders import leader_description


def spy_phase(ctx: TurnContext) -> None:
    st = ctx.state
    for sp in list(st.spies.values()):
        if not sp.alive or sp.transit > 0 or not sp.mission:
            continue
        s = st.systems[sp.system]
        mission = sp.mission
        own = s.owner == sp.owner
        ci = ctx.ci[s.id] if s.owner != sp.owner else 1
        key = "SMV" if mission == "SMO_FAIL" else mission
        base_succ, base_catch = K.SPY_ODDS.get(key, (100, 5))
        succ = base_succ / ci
        catch = 0 if own else min(100, base_catch * ci)
        ok = ctx.rng.chance(succ) if mission != "SUP" else bool(sp.mission_arg)
        caught = ctx.rng.chance(catch)
        target = s.owner
        rep = []
        if mission == "SMO_FAIL":
            rep.append("The spy found no system it could infiltrate at those coordinates.")
        elif mission == "SMV":
            rep.append(f"Spy {sp.number} has arrived at {s.name}.")
        elif mission == "SOS":
            ctx.res.report(sp.owner).scans.setdefault("spy_systems", []).append(s.id)
            ctx.extra_scans.append((s.id, sp.owner, "short"))
            rep.append(f"Spy report on {s.name}: a short-range scan (see Scans).")
        elif not ok:
            rep.append({"SOT": "The spy failed to get the technology report.",
                        "SOL": "The spy failed to get the leader report.",
                        "SOE": f"The spy failed to get the economic report on the "
                               f"{ctx.name(target)}.",
                        "SOM": "The spy failed to get the star map.",
                        "SON": "The spy failed to get the statistics report.",
                        "SAL": "The assassination attempt failed.",
                        "SSB": "The sabotage attempt failed.",
                        "SET": "The spy failed to end the trade route.",
                        "SUP": "The spy failed to incite an uprising.",
                        "SVS": "The spy failed to find enemy spies."}.get(mission,
                                                                       "The mission failed."))
        else:
            rep.extend(_success(ctx, sp, s, mission))
        if caught:
            sp.alive = False
            rep.append("The spy was caught by counter-intelligence and killed.")
            if target != sp.owner:
                ctx.res.emit(target, "spy_detected", f"A spy of the {ctx.name(sp.owner)} was "
                             f"caught and executed on {s.name}!", "spies", s.id, race=sp.owner)
        ctx.res.emit(sp.owner, "spy_caught" if caught else "spy_report",
                     f"Spy {sp.number} at {s.name}:\n\t" + "\n\t".join(rep), "spies", s.id,
                     spy=sp.number, mission=mission, success=ok, caught=caught)
        if sp.alive:
            sp.mission, sp.mission_arg = None, None


def _success(ctx, sp, s, mission) -> list[str]:
    st = ctx.state
    target = s.owner
    te = st.empires[target]
    if mission == "SOT":
        names = ", ".join(TECHS[t].name for t in sorted(te.techs) if t)
        return [f"Technologies of the {te.name}: {names or 'none'}."]
    if mission == "SOL":
        gov = st.governor(s.id)
        if gov is None:
            return [f"The leader has left {s.name}, so there was nothing to report."]
        return [f"Leader {gov.name}: management {gov.mgmt}, engineering {gov.eng}, combat "
                f"{gov.combat}, intelligence {gov.intel}, social {gov.social}, age {gov.age}.",
                leader_description(gov)]
    if mission == "SOE":
        return [f"Economy of the {te.name}: EU stockpile {te.eu}, IU supply depot "
                f"{te.iu_depot}.",
                f"Production: EU {ctx.eu_prod[target] + ctx.trade_eu[target]}, "
                f"IU {ctx.iu_prod[target]}, AU {ctx.au_prod[target]}."]
    if mission == "SOM":
        found = []
        for o in st.systems:
            if o.owner == target and target != 0 and ctx.rng.chance(50):
                ctx.extra_scans.append((o.id, sp.owner, "long"))
                found.append(o.name)
        return ["The spy gained access to star locations (long-range scans; see Scans).",
                "Systems: " + (", ".join(found) if found else "none") + "."]
    if mission == "SON":
        ctx.pending_son.append((sp.owner, target))
        return [f"The spy obtained the statistics report of the {te.name}."]
    if mission == "SAL":
        gov = st.governor(s.id)
        if gov is None:
            return [f"The leader has left {s.name}, so the assassination was called off."]
        gov.alive = False
        if gov.owner == s.owner:
            s.happy -= 0.3
        ctx.res.emit(gov.owner, "assassination",
                     f"Leader {gov.name} has been assassinated on {s.name}!",
                     "spies", s.id, leader=gov.id)
        return [f"Leader {gov.name} has been assassinated."]
    if mission == "SSB":
        options = ["IU", "AU"] + (["ART"] if s.artifacts else [])
        pick = ctx.rng.choice(options)
        if pick == "ART":
            a = ctx.rng.choice(sorted(s.artifacts))
            s.artifacts.discard(a)
            what = ARTIFACTS[a].name
        elif pick == "IU":
            s.iu = 0
            what = "IU stockpile"
        else:
            s.au = 0
            what = "AU stockpile"
        ctx.res.emit(target, "sabotage", f"Sabotage on {s.name}! The {what} was destroyed.",
                     "spies", s.id)
        return [f"Sabotage destroyed the {what}."]
    if mission == "SET":
        race = sp.mission_arg
        if race in s.trade_routes:
            s.trade_routes.discard(race)
            ctx.res.emit(race, "trade_route_ended", f"Your trade route with {s.name} has been "
                         f"eliminated by a spy.", "spies", s.id)
            return [f"The trade route of the {ctx.name(race)} has been eliminated."]
        return [f"The {ctx.name(race)} have no trade route with {s.name}."]
    if mission == "SUP":
        return ["The spy incited unrest; the population's happiness has dropped."]
    if mission == "SVS":
        mine = {o.id for o in st.systems if o.owner == sp.owner}
        found = [f"Spy {x.number} at {st.systems[x.system].name}" for x in st.spies.values()
                 if x.alive and x.owner == target and x.system in mine and x.transit == 0]
        return ["Spy vs. spy: " + ("; ".join(found) + "." if found else "no enemy spies found.")]
    return []
