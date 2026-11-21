"""The classic 2008-style text turn report, rebuilt from one empire's view (Dave 2026-11-15).

`legacy_report(view, prev=None)` turns the read model of `mhgc/view.py` (the very dict the
Report tab's Standard mode renders: this empire's own objects, its scans and this turn's results
for it only) into the plain monospace report the old engine mailed out (player<N>.out, the
archived `turnresults_*.txt`).  It reads nothing else, so it can reveal nothing the view doesn't.

`prev` is optionally the same empire's view of the turn before (what `/view?turn=n-1` gives that
seat).  Only its own systems' stockpiles and population are used, for each system block's
INITIAL STOCKS line, as the classic printed them.  Without it the line shows "--".

Section order follows the latest archived reports (iraq2/archive, Java engine) with the detailed
system blocks of turnresults_35/37:
  header and banner, ORDER PROBLEMS, MESSAGES, REBELLION, MAINTENANCE LISTING (empire lines, the
  system blocks, ship/troop/spy upkeep, final totals), COMBAT DROPS, COMBAT, RANDOM EVENTS, STAFF
  REPORTS (economic, victory points, statistics, relations), LEADER TRANSIT REPORT, INTELLIGENCE
  REPORT, SHIP REPORTS FOR YOUR SHIPS, FLEET REPORTS, HOME WORLD REPORTS, SHIPS SCANNED, FLEETS
  SCANNED, SYSTEMS SCANNED.

Differences from 2008, on purpose: coordinates are the view's (your home is the board centre);
the per-system "OTHER" line nets what the results don't itemise per system (builds paid from the
system, loads, unloads, raids and random events); CGR is gone (G-09), so growth shows 100; races'
e-mail addresses are replaced by "player" / "NPR"; the C's misspellings in section titles are kept.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from .data import constants as K
from .data.artifacts import ARTIFACTS, DISPLAY_ORDER
from .data.ships import SHIP_TYPES
from .data.troops import TROOP_TYPES

BANNER = [
    "                 _/      _/  _/    _/    _/_/_/    _/_/_/",
    "                _/_/  _/_/  _/    _/  _/        _/",
    "               _/  _/  _/  _/_/_/_/  _/  _/_/  _/",
    "              _/      _/  _/    _/  _/    _/  _/",
    "             _/      _/  _/    _/    _/_/_/    _/_/_/",
]
STANCE = {"N": "Neutral", "A": "Allied", "W": "At War", "E": "At War (peace offered)"}
KIND = {"player": "player", "human": "player", "npr": "NPR", "independent": "independent", "extinct": "extinct"}
PHASE_TITLE = {"space": "====SPACE ATTACK EFFECTIVNESS====", "raid": "====SPACE TO GROUND====",
               "ground": "====GROUND TO GROUND====", "capture": "====SYSTEM OWNER CHANGE====",
               "status": "====SYSTEM STATUS===="}

# Column layout: system lines use AU/IU/EU columns of 5 after a 54-character label; empire lines
# use the IU and EU columns of the same grid.
LBL = 54


def _num(n: Any) -> str:
    try:
        return str(int(round(float(n))))
    except (TypeError, ValueError):
        return "--"


def _signed(n: Any) -> str:
    """'+ 61', '- 50', '+160' as in the classic columns (5 wide)."""
    if n is None:
        return "     "
    v = int(round(float(n)))
    return f"{'-' if v < 0 else '+'}{abs(v):>3}".rjust(5)


def _minus(n: Any) -> str:
    """A cost: always '- n' (the classic printed '- 0' for a free artifact or nothing eaten)."""
    return f"-{abs(int(round(float(n or 0)))):>3}".rjust(5)


def _cols(label: str, au: str = "", iu: str = "", eu: str = "") -> str:
    return f"{label:<{LBL}}{au:>5}{iu:>5}{eu:>5}".rstrip()


def _ship_class(t: str) -> str:
    st = SHIP_TYPES.get(t)
    return st.name if st else str(t)


def _troop_name(t: str) -> str:
    tt = TROOP_TYPES.get(t)
    return tt.name if tt else str(t)


def _trend(t: Any) -> str:
    return "^" if (t or 0) > 0 else "v" if (t or 0) < 0 else "-"


def _xr(mr: Any, ar: Any) -> str:
    return "2R" if mr and ar else "MR" if mr else "AR" if ar else "NR"


def _section(out: list[str], title: str, dashes: int = 39) -> None:
    out.extend(["", "", f"{title}{'-' * dashes}", ""])


def _text_lines(text: str, indent: str = "\t") -> list[str]:
    """An event's text, indented; with indent "" only the continuation lines get a tab (the
    classic "WE LOVE THE EMPEROR DAY ON SYSTEM X!!!" / "\tExcited population ..." layout)."""
    lines = str(text).split("\n")
    out = []
    for i, ln in enumerate(lines):
        pre = indent if indent or i == 0 else "\t"
        out.append(pre + ln.lstrip("\t") if ln.strip() else "")
    return out


class _Names:
    """System and race names, from the view only."""

    def __init__(self, v: dict):
        self.sys: dict[int, str] = {}
        for s in v.get("known_systems") or []:
            if s.get("name"):
                self.sys[s["id"]] = s["name"]
        for s in (v.get("scans") or {}).get("systems") or []:
            if s.get("name"):
                self.sys[s["id"]] = s["name"]
        for s in v.get("systems") or []:
            self.sys[s["id"]] = s["name"]
        self.at = {(s["x"], s["y"]): s["name"] for s in v.get("systems") or []}
        # systems whose details this view shows (own, and short-scanned this turn), for the
        # system line in a combat listing
        self.detail = {s["id"]: (v["empire"]["name"], s, s.get("governor")) for s in v.get("systems") or []}
        for s in (v.get("scans") or {}).get("systems") or []:
            if s.get("level") == "short" and s["id"] not in self.detail:
                self.detail[s["id"]] = (s.get("owner_name") or "Unknown", s, s.get("leader"))
        self.me = v["empire"]["name"]
        self.races = {r["id"]: r["name"] for r in v.get("races") or []}
        self.races[v["empire"]["id"]] = self.me
        self.races.setdefault(0, "Rebels")

    def system(self, sid: Optional[int], dflt: str = "----") -> str:
        return self.sys.get(sid, dflt) if sid is not None else dflt


def legacy_report(v: dict, prev: Optional[dict] = None) -> str:
    r = v.get("results") or {}
    names = _Names(v)
    out: list[str] = []
    events = r.get("events") or []

    def evs(*sections: str) -> list[dict]:
        return [e for e in events if (e.get("section") or "general") in sections]

    # ---- header --------------------------------------------------------------------------
    gname = str(v["game"]["name"]).upper().replace(" ", "_")
    out.append(f"MHGC GAME {gname:<12.12} [{'-' * 38}]       TURN {r.get('turn', v['game']['turn'])}")
    out.append("")
    out.extend(BANNER)
    out.append(f"BEGINNING OF TURN REPORT{'-' * 35}")
    out.append(f"{'':16}{names.me} ({KIND.get(v['empire'].get('kind'), v['empire'].get('kind'))})")
    if v["game"].get("winner_name"):
        out.extend(["", f"\t***THE {str(v['game']['winner_name']).upper()} HAVE WON THE GAME!***"])

    # ---- order problems ------------------------------------------------------------------
    _section(out, "ORDER PROBLEMS (if any)", 36)
    for o in r.get("orders") or []:
        if o.get("ok") and not o.get("messages"):
            continue
        out.append("")
        out.extend(str(o.get("text", "")).split("\n"))
        built = o.get("built")
        for m in o.get("messages") or []:
            # a BS / BCU count that built only some of its units (DECISIONS G-19)
            partial = built is not None and str(m).startswith(f"Built {built} of ")
            out.append(f"\t\t***WARNING {m}" if partial else f"\t\t{m}")
        if o.get("error"):
            out.append(f"\t\t***ERROR {o['error']}")
    said = {m for o in r.get("orders") or [] for m in o.get("messages") or []}
    for e in evs("orders"):
        if e["text"] in said:
            continue
        out.append("")
        out.extend(_text_lines(f"***{e['text']}"))

    # ---- messages ------------------------------------------------------------------------
    msgs = r.get("messages") or []
    if msgs or evs("messages"):
        _section(out, "MESSAGES ", 45)
        for m in msgs:
            out.extend(["MESSAGE RECEIVED VIA SUBETHERAL BROADBASE SENSORS:", "", ""])
            if "ambassador" not in str(m.get("text", ""))[:200]:
                out.append(f"The {m.get('from_name') or 'unknown'} ambassador sends the following "
                           f"official notice{' (to every race)' if m.get('broadcast') else ''}:")
                out.append("")
            out.extend(str(m.get("text", "")).split("\n"))
            out.extend(["", ""])
        for e in evs("messages"):
            out.extend(_text_lines(e["text"]))

    # ---- rebellion -----------------------------------------------------------------------
    _section(out, "REBELLION (if any) ", 39)
    for e in evs("rebellion"):
        out.extend(_text_lines(e["text"], ""))

    # ---- maintenance ---------------------------------------------------------------------
    _section(out, "MAINTENANCE LISTING", 39)
    out.extend(_maintenance(v, prev, names))
    for e in evs("maintenance"):
        out.extend(_text_lines(e["text"]))

    # ---- drops and combat ----------------------------------------------------------------
    _section(out, "COMBAT DROPS (if any) ", 38)
    for e in evs("drops"):
        out.extend(_text_lines(e["text"]))
    _section(out, "COMBAT (if any) ", 38)
    for c in r.get("combats") or []:
        out.extend(_combat(c, names))
    for e in evs("combat"):
        out.extend(_text_lines(e["text"]))

    # ---- random events -------------------------------------------------------------------
    _section(out, "RANDOM EVENTS (if any) ", 31)
    for e in evs("random"):
        out.extend(_text_lines(e["text"]))
        out.append("")

    # ---- staff reports -------------------------------------------------------------------
    out.extend(_staff(v, evs("scans", "general")))

    # ---- leaders -------------------------------------------------------------------------
    out.extend(["", "", "LEADER TRANSIT REPORT", ""])
    for ld in sorted(v.get("leaders") or [], key=lambda q: q["id"]):
        if ld.get("status") == "limbo":
            out.append(f"Leader {ld['name']} is awaiting assignment")
        elif ld.get("status") == "transit":
            dest = names.system(ld.get("system"), "its new post")
            out.append(f"Leader {ld['name']} is in transit to "
                       f"{'fleet ' + ld['fleet'] if ld.get('fleet') else 'system ' + dest}"
                       f" and will arrive in {ld.get('transit', 0)} turns")
        elif ld.get("status") == "ice":
            out.append(f"Leader {ld['name']} is on ice ({ld.get('transit', 0)} turns)")
    for e in evs("leaders"):
        out.extend(_text_lines(e["text"], ""))

    # ---- intelligence --------------------------------------------------------------------
    out.extend(["", "", "INTELLIGENCE REPORT", ""])
    for e in evs("spies"):
        out.extend(_text_lines(e["text"], ""))
        out.append("")
    for sp in sorted(v.get("spies") or [], key=lambda q: q["number"]):
        where = names.system(sp.get("system"), "?")
        state = f"in transit to {where} ({sp['transit']} turns)" if sp.get("transit") else f"at {where}"
        mission = f", mission {sp['mission']}{' ' + str(sp['mission_arg']) if sp.get('mission_arg') else ''}" \
            if sp.get("mission") else ""
        out.append(f"\tSpy {sp['number']} is {state}{mission}")

    # ---- own ships, fleets, systems ------------------------------------------------------
    out.extend(_own_ships(v, names))
    out.extend(_own_fleets(v, names))
    out.extend(_home_worlds(v))

    # ---- scans ---------------------------------------------------------------------------
    out.extend(_scans(v, names.races))
    out.append("")
    return "\n".join(ln.rstrip() for ln in out) + "\n"


# ------------------------------------------------------------------------------ maintenance
def _maintenance(v: dict, prev: Optional[dict], names: _Names) -> list[str]:
    r = v.get("results") or {}
    rows = r.get("maintenance") or []
    out: list[str] = []
    if not rows:
        out.append("(no maintenance listing this turn)")
        return out
    by: dict[str, list[dict]] = {}
    for line in rows:
        by.setdefault(line["kind"], []).append(line)
    total = lambda kind, key: sum(int(q.get(key) or 0) for q in by.get(kind, []))  # noqa: E731

    init = by.get("initial", [{"iu": 0, "eu": 0}])[0]
    depot, eu = int(init.get("iu") or 0), int(init.get("eu") or 0)
    out.append(_cols("IU SUPPLY DEPOT / EU STOCKPILE INITIAL:", "", _num(depot), _num(eu)))
    for kind, label in (("purchases", "EU USED IN PURCHASES:"),
                        ("salvage", "SALVAGE REFUNDS (SS, SCT):"),
                        ("gifts_out", "EU GIVEN AS GIFT OR PAID IN TRADES:"),
                        ("gifts_in", "EU RECEIVED AS GIFT:")):
        if kind in by:
            n = total(kind, "eu")
            eu += n
            out.append(_cols(label, "", "", _signed(n)))
            sys_iu = total(kind, "system_iu")
            if sys_iu:
                out.append(_cols("    (IU FROM YOUR SYSTEMS' STOCKPILES)", "", _signed(sys_iu)))
    if "trade" in by:
        n = total("trade", "eu")
        eu += n
        out.append("")
        out.append(_cols("EU GATHERED IN TRADE, TOTAL:", "", "", _signed(n)))

    # ---- system blocks
    out.extend(["", "", _cols("SYSTEM", "AU", "IU", "EU")])
    prev_sys = {s["id"]: s for s in (prev or {}).get("systems") or []}
    art_by_sys: dict[int, list[dict]] = {}
    for line in by.get("artifact", []):
        art_by_sys.setdefault(line.get("system"), []).append(line)
    sisd_by_sys: dict[int, int] = {}
    for line in by.get("sisd", []):
        sisd_by_sys[line.get("system")] = sisd_by_sys.get(line.get("system"), 0) + int(line.get("iu") or 0)
    auto_by_sys: dict[int, int] = {}
    for line in by.get("autosisd", []):
        auto_by_sys[line.get("system")] = auto_by_sys.get(line.get("system"), 0) + int(line.get("iu") or 0)
    listed_eu = 0
    listed = set()
    for s in v.get("systems") or []:
        listed.add(s["id"])
        p = s.get("production") or {}
        prof = s.get("profile") or {}
        ps = prev_sys.get(s["id"])
        out.append("")
        out.append(f"SYSTEM {s['name']:<13}")
        out.append(_cols("       INITIAL STOCKS", _num(ps["au"]) if ps else "--",
                         _num(ps["iu"]) if ps else "--", _num(eu)))
        out.append(_cols("       PROFILE", f"{prof.get('au', 0)}%", f"{prof.get('iu', 0)}%",
                         f"{prof.get('eu', 0)}%"))
        pau, piu, peu = int(p.get("au") or 0), int(p.get("iu") or 0), int(p.get("eu") or 0)
        eaten = int(p.get("eaten") or 0)
        out.append(_cols("       PRODUCTION", _signed(pau), _signed(piu), _signed(peu)))
        pop = ps["pop"] if ps else s.get("pop", 0)
        out.append(_cols(f"       AU EATEN BY {float(pop or 0):6.3f} POPULATION", _minus(eaten)))
        sisd = sisd_by_sys.get(s["id"], 0)
        if sisd:
            out.append(_cols("       SISD TO THE SUPPLY DEPOT", "", _minus(sisd)))
        auto = auto_by_sys.get(s["id"], 0)
        if auto:
            out.append(_cols("       AUTOSISD TO THE SUPPLY DEPOT", "", _minus(auto)))
        if ps:
            o_au = int(s["au"]) - int(ps["au"]) - pau + eaten
            o_iu = int(s["iu"]) - int(ps["iu"]) - piu + sisd + auto
            if o_au or o_iu:
                out.append(_cols("       OTHER (BUILDS, LOADS, UNLOADS, EVENTS)",
                                 _signed(o_au), _signed(o_iu)))
        eu += peu
        listed_eu += peu
        paid = {q.get("artifact"): int(q.get("eu") or 0) for q in art_by_sys.get(s["id"], [])}
        for key in DISPLAY_ORDER:
            if key in (s.get("artifacts") or []) or key in paid:
                n = paid.get(key, 0)
                eu += n
                a = ARTIFACTS.get(key)
                out.append(_cols(f"       ARTIFACT   {a.name if a else key}", "", "",
                                 f"-{abs(n):>2}"))
        out.append(_cols("TOTAL", _num(s.get("au")), _num(s.get("iu")), _num(eu)))
    # EU produced (and artifact upkeep paid) by systems that are no longer ours at the end
    lost_eu = total("production", "eu") - listed_eu
    lost_eu += sum(int(q.get("eu") or 0) for sid, ls in art_by_sys.items() if sid not in listed
                   for q in ls)
    if lost_eu:
        eu += lost_eu
        out.extend(["", _cols("EU FROM SYSTEMS NO LONGER YOURS:", "", "", _signed(lost_eu))])
    depot += sum(sisd_by_sys.values())
    out.extend(["", "", _cols("BEGINNING IU SUPPLIES/EU STOCKPILE", "", _num(depot), _num(eu)), ""])

    # ---- ship, troop and spy upkeep, in the order they were paid
    ship_names = {s["number"]: s.get("class") for s in v.get("ships") or []}
    m_iu = m_eu = 0
    for line in rows:
        k = line["kind"]
        if k == "autosisd":
            out.append(f"\t\t{line.get('iu', 0)} IUs moved from {names.system(line.get('system'))} "
                       f"to IU Stockpile ")
            out.append("\t\tto pay for ship maintenance!")
        elif k == "ship":
            n = line.get("ship")
            cls = ship_names.get(n) or ""
            out.append(_cols(f"       SHIP {n:>4} {cls}", "", _signed(line.get("iu")),
                             _signed(line.get("eu"))))
            m_iu -= int(line.get("iu") or 0)
            m_eu -= int(line.get("eu") or 0)
        elif k == "ct":
            out.append(_cols(f"CT   {line.get('ct', ''):>4}", "", "", _signed(line.get("eu"))))
            m_eu -= int(line.get("eu") or 0)
        elif k == "spy":
            out.append(_cols(f"SPY  {line.get('spy', ''):>4}", "", "", _signed(line.get("eu"))))
            m_eu -= int(line.get("eu") or 0)
    out.extend(["", _cols("COMBINED MAINT COSTS:", "", _num(m_iu), _num(m_eu))])
    fin = by.get("final", [{}])[0]
    out.extend(["", "", _cols("FINAL IU / EU TOTAL:", "", _num(fin.get("iu")), _num(fin.get("eu")))])
    return out


# ------------------------------------------------------------------------------ combat
def _combat(c: dict, names: _Names) -> list[str]:
    pn = c.get("participant_names") or {}
    pname = lambda p: pn.get(str(p)) or pn.get(p) or f"Race {p}"  # noqa: E731
    sid = c.get("system")
    title = f"SYSTEM {names.system(sid, '?')}" if sid is not None else f"COMBAT AT {c['x']:>3} {c['y']:>3}"
    out = ["", f"============COMBAT RESULTS FOR {title} ============", ""]
    for s in c.get("ships") or []:
        out.append(f"*{pname(s['owner']):<16}{s['number']:>8} {_ship_class(s['type']):>14} "
                   f"{c['x']:>3} {c['y']:>3}  {s.get('fleet') or 'STAND':<6} {s.get('posture') or '-'} "
                   f"{s.get('role') or '--'}")
    if sid in names.detail:
        owner, s, leader = names.detail[sid]
        out.append(_system_row(owner, s))
        out.extend(_system_extras({**s, "troops": []}, leader))
    for t in c.get("troops") or []:
        out.append(f"\t\tCT NUM: {t['number']} {pname(t['owner'])} {_troop_name(t['type'])} "
                   f"{_posture(t.get('posture'))}")
    parts = c.get("participants") or []
    out.extend(["", "======CONFLICT RESOLUTION======", "", "====RACE RELATIONS====", "", ""])
    rel = c.get("relations") or {}
    out.append(f"{'':15}|" + "".join(f"{pname(p):>15}|" for p in parts))
    for a in parts:
        cells = []
        for b in parts:
            k = rel.get(f"{a},{b}") or rel.get(f"{b},{a}") if a != b else ""
            cells.append(f"{(k or ('' if a == b else 'NEUTRAL')):^15}|")
        out.append(f"{pname(a):>15}|" + "".join(cells))
    phase = None
    destroyed = False
    for line in c.get("lines") or []:
        if line.get("phase") != phase:
            phase = line.get("phase")
            destroyed = False
            out.extend(["", PHASE_TITLE.get(phase, f"===={str(phase).upper()}===="), ""])
        if phase == "space" and "ship" in line and not destroyed:
            destroyed = True
            out.extend(["", "====SHIPS DESTROYED====", ""])
        out.extend(str(line.get("text", "")).split("\n"))
    out.extend(_ground_after(c, pname))
    out.extend(["", "============END OF THIS COMBAT============", ""])
    return out


def _ground_after(c: dict, pname) -> list[str]:
    """Each side's troops on the ground, before -> after (the log's `ground`, Dave 2026-11-16)."""
    ground = c.get("ground") or []
    if not ground:
        return []
    out = ["", "====GROUND FORCES AFTER THE BATTLE====", ""]
    for g in ground:
        before, after = g.get("before") or {}, g.get("after") or {}
        types = [t for t in TROOP_TYPES if t in before or t in after] + \
                sorted(t for t in set(before) | set(after) if t not in TROOP_TYPES)
        label = pname(g.get("owner"))
        if not types:
            out.append(f"{label:<17}none")
        for t in types:
            n0, n1 = before.get(t, 0), after.get(t, 0)
            lost = f"  ({n0 - n1} lost)" if n1 < n0 else f"  ({n1 - n0} joined)" if n1 > n0 else ""
            out.append(f"{label:<17}{_troop_name(t):<14}{n0:>3} -> {n1:<3}{lost}")
            label = ""
        if before and not after:
            out.append(f"{'':17}NO TROOPS LEFT ON THE GROUND")
    return out


def _posture(p: Any) -> str:
    return {"A": "attack", "D": "defend", "E": "dug in"}.get(p, str(p or ""))


# ------------------------------------------------------------------------------ staff reports
def _staff(v: dict, general: Iterable[dict]) -> list[str]:
    r = v.get("results") or {}
    e = v["empire"]
    econ = r.get("economy") or {}
    prod = econ.get("production") or {}
    st = r.get("stats") or {}
    out = ["", "", f"STAFF REPORTS: {'-' * 35}", "", "ECONOMIC REPORT", ""]
    out.append(f"{e['name']:<17}STOCKPILE/DEPOT:  EU: {_num(econ.get('eu', e.get('eu'))):>4}    "
               f"IU: {_num(econ.get('iu_depot', e.get('iu_depot'))):>4}")
    out.append(f"{'':17}PRODUCTION:       EU: {_num(prod.get('EU', 0)):>4}    IU: {_num(prod.get('IU', 0)):>4}"
               f"    AU: {_num(prod.get('AU', 0)):>4}")
    out.extend(["", "", "VICTORY POINT  REPORT", ""])
    vp = st.get("vp", e.get("vp"))
    need = st.get("vp_needed", v["game"].get("vp_to_win", K.VICTORY_POINTS))
    out.append(f"{'':16}YOU HAVE COLLECTED {_num(vp)} OUT OF {_num(need):>4} VICTORY POINTS")
    out.extend(["", "", "STATISTICS REPORT", ""])
    ranks = st.get("ranks") or {}
    values = st.get("values") or {}
    keys = [k for k in K.STAT_NAMES if k in ranks or k in values]
    heads = [f"{k}{'*' if k in K.VP_STATS else ''}" for k in keys]
    out.append(f"{'':16}" + " ".join(f"{h:>4}" for h in heads))
    out.append(f"{e['name']:<16}" + " ".join(f"{_num(ranks.get(k)) if k in ranks else '-':>4}" for k in keys))
    out.append(f"{'(value)':<16}" + " ".join(f"{_short(values.get(k)):>4}" for k in keys))
    out.append(f"{'':16}* earns victory points for 1st and 2nd place")
    out.extend(["", "", "REPORT ON RELATIONS WITH OTHER EMPIRES", ""])
    for race in v.get("races") or []:
        kind = KIND.get(race.get("kind"), race.get("kind") or "")
        stance = STANCE.get(race.get("our_stance"), race.get("our_stance") or "")
        extra = []
        if race.get("split_trade"):
            extra.append(f"splitting trade {race['split_trade']}%")
        if race.get("deny_trade"):
            extra.append(f"denying trade {race['deny_trade']}%")
        out.append(f"\t{race['name']:<16} ({kind}){'':<{max(1, 38 - len(kind))}}: {stance}"
                   + (f"  ({', '.join(extra)})" if extra else ""))
    for ev in general:
        out.extend(_text_lines(ev["text"]))
    return out


def _short(x: Any) -> str:
    """A statistic's value in 4 characters or so."""
    if x is None:
        return "-"
    f = float(x)
    if abs(f) >= 10000:
        return f"{f / 1000:.0f}k"
    if abs(f) >= 100 or f == int(f):
        return str(int(round(f)))
    return f"{f:.1f}" if abs(f) >= 10 else f"{f:.2f}"


# ------------------------------------------------------------------------------ own objects
def _dest(frm: dict, dst: dict, order: Optional[str], target: Any) -> str:
    if order and str(order).upper().startswith("I") and target is not None:
        return f"I {target:>4}"
    if dst and frm and (dst.get("x"), dst.get("y")) != (frm.get("x"), frm.get("y")):
        return f"{dst['x']:>3} {dst['y']:>3}"
    return " STAND "


def _own_ships(v: dict, names: _Names) -> list[str]:
    out = ["", "", "SHIP REPORTS FOR YOUR SHIPS:", "",
           "AT SYSTEM             NO.      TYPE       X   Y   dx  dy P CR"]
    troops = {t["number"]: t for t in v.get("troops") or []}
    for s in sorted(v.get("ships") or [], key=lambda q: (-q["x"], -q["y"], q["number"])):
        at = names.at.get((s["x"], s["y"]), "----")
        here = {"x": s["x"], "y": s["y"]}
        out.append(f" {at:<16}{s['number']:>8} {s.get('class') or _ship_class(s['type']):>14} "
                   f"{s['x']:>3} {s['y']:>3}  {_dest(here, s.get('dest') or here, s.get('order'), s.get('target')):<7} "
                   f"{s.get('posture') or '-'} {s.get('role') or '--'}")
        cg = s.get("cargo")
        if cg and (cg.get("AU") or cg.get("IU") or cg.get("POP") or cg.get("CT")):
            parts = [f"{k}: {cg[k]:>3}" for k in ("AU", "IU", "POP") if cg.get(k)]
            out.append("\t\t\tCARGO: " + "  ".join(parts))
            for n in cg.get("CT") or []:
                t = troops.get(n)
                if t:
                    out.append(f"\t\tCT NUM: {n} {names.me} {_troop_name(t['type'])} {t.get('posture_name', '')}")
    return out


def _own_fleets(v: dict, names: _Names) -> list[str]:
    fleets = v.get("fleets") or []
    out = ["", "", "FLEET REPORTS", ""]
    if not fleets:
        return out
    out.append("SYSTEM AT           FLEET NAME     X   Y   dx  dy  P  CR S ATTK  DEF")
    ships = {s["number"]: s for s in v.get("ships") or []}
    for f in sorted(fleets, key=lambda q: q["name"]):
        at = names.at.get((f["x"], f["y"]), "----")
        members = [ships[n] for n in f.get("ships") or [] if n in ships]
        att = sum(SHIP_TYPES[s["type"]].attack for s in members if s["type"] in SHIP_TYPES)
        dfn = sum(SHIP_TYPES[s["type"]].defense for s in members if s["type"] in SHIP_TYPES)
        here = {"x": f["x"], "y": f["y"]}
        out.append(f"*{at:<19}{f['name']:<13}{f['x']:>4} {f['y']:>3}  "
                   f"{_dest(here, f.get('dest') or here, f.get('order'), f.get('target')):<8}"
                   f"{f.get('posture') or '-':>2}  {f.get('role') or '--':<2} {f.get('speed', 'A')} {att:>4} {dfn:>4}")
        if f.get("admiral"):
            out.append(f"\tLEADER:  {f['admiral']}")
        by: dict[str, list[int]] = {}
        for s in members:
            by.setdefault(s.get("class") or _ship_class(s["type"]), []).append(s["number"])
        for cls, nums in by.items():
            out.append(f"   {cls:<13}: " + " ".join(f"{n:>4}" for n in nums))
    return out


SYS_HEAD = "       OWNER     SYSTEM NAME   X   Y  HA  SP  STAT  BI  IF HB XR  AU   IU   GR"


def _system_row(owner: str, s: dict, mark: str = " ") -> str:
    band = s.get("happy_band", s.get("happy")) or "--"
    if not isinstance(band, str):
        band = K.happiness_band(band)
    return (f"{mark}{owner:<15} {s.get('name') or '?':<13}{s['x']:>3} {s['y']:>3} "
            f"{band}{_trend(s.get('trend'))} {_num(s.get('starport')):>2}  {s.get('status') or '----':>4} "
            f"{float(s.get('pop') or 0):4.1f} {_num(s.get('infra')):>2} {str(s.get('hab') or '--'):<2} "
            f"{_xr(s.get('mr'), s.get('ar'))} {_num(s.get('au')):>4} {_num(s.get('iu')):>4} 100")


def _system_extras(s: dict, leader: Optional[str], races: Optional[dict] = None) -> list[str]:
    out = []
    arts = [k for k in DISPLAY_ORDER if k in (s.get("artifacts") or [])]
    if arts:
        out.append("\t\t\tTECH: " + " ".join(arts) + " ")
    if leader:
        out.append(f"\t\t\tLEADER: {leader}")
    for t in s.get("troops") or []:
        owner = t.get("owner_name") or (races or {}).get(t.get("owner"), "Unknown")
        out.append(f"\t\tCT NUM: {t['number']} {owner} {_troop_name(t['type'])} "
                   f"{t.get('posture_name') or t.get('posture') or ''}".rstrip())
    return out


def _home_worlds(v: dict) -> list[str]:
    out = ["", "", "HOME WORLD REPORTS:", "", SYS_HEAD]
    me = v["empire"]["name"]
    for s in v.get("systems") or []:
        out.append(_system_row(me, s, "*" if s.get("status") not in ("Norm", None) else " "))
        out.extend(_system_extras(s, s.get("governor")))
    return out


def _scans(v: dict, races: dict) -> list[str]:
    sc = v.get("scans") or {}
    out = ["", "", "SHIPS SCANNED:", "", "OWNER                NO.    TYPE       X   Y   ox  oy P CR"]
    for s in sorted(sc.get("ships") or [], key=lambda q: (str(q.get("owner_name")), -q["x"], -q["y"])):
        short = s.get("level") == "short"
        frm = {"x": s.get("ox", s["x"]), "y": s.get("oy", s["y"])}
        moved = (frm["x"], frm["y"]) != (s["x"], s["y"])
        origin = f"{frm['x']:>3} {frm['y']:>3}" if moved else " STAND "
        out.append(f"{'*' if short else ' '}{s.get('owner_name') or '?':<16}{s['number']:>8} "
                   f"{_ship_class(s['type']):>14} {s['x']:>3} {s['y']:>3}  "
                   f"{origin:<7} "
                   f"{(s.get('posture') or '-') if short else '-'} {(s.get('role') or '--') if short else '--'}")
        cg = s.get("cargo") if short else None
        if cg:
            parts = [f"{k}: {cg[k]:>3}" for k in ("AU", "IU", "POP") if cg.get(k)]
            out.append("\t\t\tCARGO: " + "  ".join(parts))
            for t in cg.get("CT") or []:
                out.append(f"\t\tCT NUM: {t['number']} {s.get('owner_name') or ''} "
                           f"{_troop_name(t['type'])} {t.get('posture', '')}")
    out.extend(["", "", "FLEETS SCANNED", "", " OWNER              FLEET NAME     X   Y"])
    for f in sc.get("fleets") or []:
        out.append(f" {f.get('owner_name') or '?':<19}{f['name']:<13}{f['x']:>4} {f['y']:>3}")
        types: dict[str, list[int]] = {}
        stypes = {s["number"]: s["type"] for s in sc.get("ships") or []}
        for n in f.get("ships") or []:
            types.setdefault(_ship_class(stypes.get(n, "?")), []).append(n)
        for cls, nums in types.items():
            out.append(f"   {cls:<13}: " + " ".join(f"{n:>4}" for n in nums))
    out.extend(["", "", "SYSTEMS SCANNED:", "", SYS_HEAD])
    for s in sc.get("systems") or []:
        owner = s.get("owner_name") or "Unknown"
        if s.get("level") == "short":
            out.append(_system_row(owner, s, "*"))
            out.extend(_system_extras(s, s.get("leader"), races))
        else:
            out.append(f" {owner:<15} {s.get('name') or '?':<13}{s['x']:>3} {s['y']:>3}")
    return out
