"""Spies (rules:2741-2843), random events and leaders (gcrandom.c; rules:619-662), scans,
statistics and victory (rules:197-220)."""
import pytest

from mhgc.data import constants as K
from mhgc.engine import events, leaders, scans, spies, stats
from mhgc.model import Spy
from tests.conftest import (ScriptedRng, add_leader, add_ship, add_troop, contact, ctx_for, do,
                            make_state, sysn)


def _spy(st, owner, sysname, mission=None, arg=None):
    n = max(st.spies, default=0) + 1
    sp = Spy(n, owner, sysn(st, sysname).id, mission=mission, mission_arg=arg)
    st.spies[n] = sp
    return sp


# ---- spies -------------------------------------------------------------------------------

def test_spy_odds_table_and_counter_intelligence():
    st = make_state()
    sp = _spy(st, 1, "H2", "SAL")
    add_leader(st, 2, system=sysn(st, "H2").id)
    rng = ScriptedRng(chance=False)
    ctx = ctx_for(st, rng)
    ctx.ci[sysn(st, "H2").id] = 4                      # CI H2 3 -> x4 (rules:2009-2011)
    spies.spy_phase(ctx)
    assert rng.calls == [30 / 4, 100]                   # SAL 30% success, 30% x4 capture


def test_spy_never_caught_at_home():
    st = make_state()
    _spy(st, 1, "H1", "SOS")
    rng = ScriptedRng(chance=True)
    ctx = ctx_for(st, rng)
    spies.spy_phase(ctx)
    assert rng.calls[1] == 0


def test_assassination_and_capture():
    st = make_state()
    s2 = sysn(st, "H2")
    gov = add_leader(st, 2, system=s2.id)
    sp = _spy(st, 1, "H2", "SAL")
    ctx = ctx_for(st, ScriptedRng(script=[True, True]))
    h0 = s2.happy
    spies.spy_phase(ctx)
    assert not gov.alive and s2.happy == pytest.approx(h0 - 0.3)
    assert not sp.alive
    assert ctx.res.events_of(1, "spy_caught") and ctx.res.events_of(2, "spy_detected")


def test_sabotage_random_target():
    st = make_state()
    s2 = sysn(st, "H2")
    s2.artifacts = {"EHC", "PD"}
    _spy(st, 1, "H2", "SSB")
    rng = ScriptedRng(script=[True, False])
    rng.choice = lambda seq: seq[-1] if "ART" in seq else seq[0]
    ctx = ctx_for(st, rng)
    spies.spy_phase(ctx)
    assert len(s2.artifacts) == 1


def test_set_ends_trade_route_and_sos_scan():
    st = make_state()
    s2 = sysn(st, "H2")
    s2.trade_routes = {3}
    _spy(st, 1, "H2", "SET", 3)
    ctx = ctx_for(st, ScriptedRng(script=[True, False]))
    spies.spy_phase(ctx)
    assert not s2.trade_routes and ctx.res.events_of(3, "trade_route_ended")
    _spy(st, 1, "H2", "SOS")
    ctx = ctx_for(st, ScriptedRng(chance=False))
    spies.spy_phase(ctx)
    assert (s2.id, 1, "short") in ctx.extra_scans


def test_sup_takes_effect_in_order_phase():
    # F-11
    st = make_state()
    st.empires[1].techs.add(14)
    sp = _spy(st, 1, "H2")
    ctx = ctx_for(st, ScriptedRng(chance=True))
    assert do(ctx, 1, f"SUP {sp.number}").ok
    assert ctx.spy_unrest[sysn(st, "H2").id] == 1


# ---- random events -----------------------------------------------------------------------

def test_plague_skips_empty_systems_and_adm_halves():
    st = make_state()
    e1 = sysn(st, "E1")
    ctx = ctx_for(st)
    events.plague(ctx, e1)
    assert e1.pop == 0                                  # C bug gave 1.0 pop
    s = sysn(st, "H1")
    s.pop = 10.0
    st.empires[1].techs.add(26)
    rng = ScriptedRng()
    rng.below = lambda n: 30                            # k = 40 -> 20 with ADM -> 2 pop
    ctx = ctx_for(st, rng)
    events.plague(ctx, s)
    assert s.pop == pytest.approx(8.0)


def test_plague_capped_at_three_pop():
    st = make_state()
    s = sysn(st, "H1")
    s.pop = 10.0
    rng = ScriptedRng()
    rng.below = lambda n: 79                            # k = 89
    events.plague(ctx_for(st, rng), s)
    assert s.pop == pytest.approx(7.0)


def test_cd_rom_reveals_systems():
    # rules:1196-1198 (F-06)
    st = make_state()
    st.turn = 10
    for e in st.empires.values():
        e.seen_systems.clear()
    rng = ScriptedRng()
    rng.below = lambda n: 0
    ctx = ctx_for(st, rng)
    events.cd_rom(ctx)
    ev = [e for p in (1, 2) for e in ctx.res.events_of(p, "cd_rom")]
    assert ev and len(ev[0].data["systems"]) >= 3


def test_events_start_after_turn_ten():
    st = make_state()
    st.turn = 5
    pops = [s.pop for s in st.systems]
    events.random_events(ctx_for(st))
    assert [s.pop for s in st.systems] == pops


# ---- leaders -----------------------------------------------------------------------------

def test_leader_ageing_and_death_chance():
    st = make_state()
    ld = add_leader(st, 1, system=0)
    ld.age = 39
    rng = ScriptedRng()
    rng.pct = lambda: 3                                 # age 40: 4% > roll 3 -> dies
    ctx = ctx_for(st, rng)
    leaders.leader_events(ctx)
    assert not ld.alive and ctx.res.events_of(1, "leader_died")


def test_leader_on_ice_dies_after_five_turns():
    st = make_state()
    ld = add_leader(st, 1)
    ld.status, ld.transit = "ice", 5
    rng = ScriptedRng()
    rng.pct = lambda: 99
    for _ in range(4):
        leaders.leader_events(ctx_for(st, rng))
        assert ld.alive
    leaders.leader_events(ctx_for(st, rng))
    assert not ld.alive


def test_new_leader_distribution_and_description():
    st = make_state()
    ctx = ctx_for(st)
    ld = leaders.new_leader(ctx, 1)
    allowed = {100 - k * k for k in range(1, 10)}
    assert {ld.mgmt, ld.eng, ld.combat, ld.intel, ld.social} <= allowed
    assert ld.status == "limbo" and ld.description.startswith(f"Gov. {ld.name}")


def test_leader_stats_clamped():
    st = make_state()
    ld = add_leader(st, 1, mgmt=98, combat=98, social=98, eng=98, intel=99)
    rng = ScriptedRng()
    seq = [99] + [0, 99] * 4
    rng.pct = lambda: seq.pop(0) if seq else 99
    leaders.leader_events(ctx_for(st, rng))
    assert max(ld.mgmt, ld.combat, ld.social, ld.eng) <= 99


# ---- scans -------------------------------------------------------------------------------

def test_scans_short_long_and_contact():
    st = make_state()
    for e in st.empires.values():
        e.relations.clear()
    add_ship(st, 1, "S", 60, 60)                        # scan 3
    near = add_ship(st, 2, "F", 62, 61)
    same = add_ship(st, 2, "T", 60, 60, cargo_pop=1)
    far = add_ship(st, 2, "F", 70, 70)
    ctx = ctx_for(st)
    scans.do_scans(ctx)
    seen = {d["number"]: d["level"] for d in ctx.res.report(1).scans["ships"]}
    assert seen == {near.number: "long", same.number: "short"}
    short = [d for d in ctx.res.report(1).scans["ships"] if d["level"] == "short"][0]
    assert short["posture"] == "N" and short["cargo"]["POP"] == 1
    assert 2 in st.empires[1].relations and 1 in st.empires[2].relations


def test_system_scan_ranges_and_no_npr_bonus():
    st = make_state()
    s1 = sysn(st, "H1")                                 # (10,10)
    a = add_ship(st, 2, "S", 15, 10)
    ctx = ctx_for(st)
    scans.do_scans(ctx)
    assert not ctx.res.report(1).scans["ships"]         # range 4
    s1.artifacts.add("ESS")
    ctx = ctx_for(st)
    scans.do_scans(ctx)
    assert ctx.res.report(1).scans["ships"]             # range 6
    b = add_ship(st, 1, "S", 37, 30)                    # 7 from NPR home H3 (30,30)
    ctx = ctx_for(st)
    scans.do_scans(ctx)                                 # no NPR bonus (DECISIONS A-01)
    assert not any(d["number"] == b.number for d in ctx.res.report(3).scans["ships"])
    b.x = 34
    ctx = ctx_for(st)
    scans.do_scans(ctx)
    assert any(d["number"] == b.number for d in ctx.res.report(3).scans["ships"])


def test_extinction():
    st = make_state()
    s2 = sysn(st, "H2")
    s2.owner, s2.pop = 0, 0.0
    contact(st, 1, 2)
    ctx = ctx_for(st)
    scans.extinction(ctx)
    assert st.empires[2].kind == "dead" and 2 not in st.empires[1].relations
    assert ctx.res.events_of(1, "extinction")


# ---- stats and victory -------------------------------------------------------------------

def test_victory_points():
    # rules:197-220
    st = make_state()
    e1 = st.empires[1]
    e1.techs |= {1, 18, 27, 37, 49}                     # 0 + 1 + 1 + 2 + 3
    e1.future_tech = 2                                  # 4 each
    ctx = ctx_for(st)
    stats.compute_stats(ctx)
    base = 7 + 8 + 2                                    # techs + FT + 1 system
    assert e1.vp >= base
    bonus = e1.vp - base
    # stat bonuses among every race, computer empires included (Dave 2026-11-15, DECISIONS
    # A-06): 2 for 1st, 1 for 2nd, ties share
    assert bonus == sum(K.VP_STAT_BONUS[e1.ranks[s]] for s in K.VP_STATS)
    assert "VCT" in st.empires[3].stats and st.empires[3].ranks


def test_victory_check_and_nnp_tiebreak():
    st = make_state()
    ctx = ctx_for(st)
    stats.compute_stats(ctx)
    st.empires[1].vp, st.empires[2].vp = 105, 120
    st.empires[1].stats["NNP"], st.empires[2].stats["NNP"] = 300, 200
    stats.check_victory(ctx)
    assert st.winner == 1 and ctx.res.winner == 1       # F-05
    assert ctx.res.events_of(2, "victory")
