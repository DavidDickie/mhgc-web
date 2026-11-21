"""Order validation and effects against the game state (rules:1917-2672 and the tech list)."""
import pytest

from mhgc.data import constants as K
from mhgc.engine.turn import check_orders
from mhgc.model import from_dict, to_dict
from mhgc.orders import parse_orders
from tests.conftest import (ScriptedRng, add_leader, add_ship, add_troop, contact, ctx_for, do,
                            make_state, sysn)


@pytest.fixture
def ctx():
    return ctx_for(make_state())


def err(r):
    assert not r.ok, f"expected failure, got ok: {r.messages}"
    return r.error


def ok(r):
    assert r.ok, r.error
    return r


# ---- technology --------------------------------------------------------------------------

def test_pt_one_per_turn_and_cost(ctx):
    e = ctx.emp(1)
    ok(do(ctx, 1, "PT 2"))
    assert 2 in e.techs and e.eu == 900
    e = err(do(ctx, 1, "PT 3"))
    assert "Only one tech a turn" in e and "(PT) earlier this turn" in e


def test_pt_prereqs_and_funds(ctx):
    assert "needs Powered Armor" in err(do(ctx, 1, "PT 8"))         # needs Powered Armor
    ctx.emp(1).eu = 50
    assert "costs" in err(do(ctx, 1, "PT 1"))


def test_crp_twice_cost_unlimited(ctx):
    # rules:278-280; F-09
    ok(do(ctx, 1, "PT 1"))
    ok(do(ctx, 1, "CRP 2"))
    ok(do(ctx, 1, "CRP 3"))
    assert ctx.emp(1).eu == 1000 - 100 - 200 - 200


def test_future_tech_repeatable_once_per_turn(ctx):
    e = ctx.emp(1)
    e.techs |= set(range(51))
    e.eu = 100000
    ok(do(ctx, 1, "PT 51"))
    assert e.future_tech == 1 and e.eu == 100000 - 8000
    assert "only one Future" in err(do(ctx, 1, "CRP 51"))


def test_npr_pays_full_price(ctx):
    ok(do(ctx, 3, "PT 1"))                        # DECISIONS A-01: no NPR discount
    assert ctx.emp(3).eu == 1000 - 100


def test_gift_tech_rules(ctx):
    # rules:2503-2518
    e1, e2 = ctx.emp(1), ctx.emp(2)
    e1.techs |= {1, 8}
    assert "contact" in err(do(ctx, 1, "GT R2 1"))
    contact(ctx.state, 1, 2)
    assert "prerequisite" in err(do(ctx, 1, "GT R2 8"))
    ok(do(ctx, 1, "GT R2 1"))
    assert 1 in e2.techs and e1.eu == 1000 - 50
    assert "already gifted" in err(do(ctx, 1, "GT R2 8"))
    e = err(do(ctx, 2, "PT 2"))     # one tech per turn incl. gifts
    assert "gave you" in e and "Only one tech a turn" in e
    assert ctx.res.events_of(2, "tech_received")


def test_ttnpr_is_a_swap(ctx):
    # rules:2532-2541
    contact(ctx.state, 1, 3)
    me, npr = ctx.emp(1), ctx.emp(3)
    me.techs.add(2)
    npr.techs.add(1)
    ctx.rng = ScriptedRng(chance=True)
    r = ok(do(ctx, 1, "TTNPR 2 1 R3"))
    assert 1 in me.techs and 2 in npr.techs
    assert me.eu == 1000 - 50 and npr.eu == 1000 - 50
    assert "already" in err(do(ctx, 1, "TTNPR 2 1 R3"))


# ---- system orders -----------------------------------------------------------------------

def test_csp_cap_capn(ctx):
    s = sysn(ctx.state, "H1")
    ok(do(ctx, 1, "CSP H1 25 50 25"))
    assert (s.csp_au, s.csp_iu, s.csp_eu) == (25, 50, 25)
    ok(do(ctx, 1, "CAP H1 10"))
    assert (s.au_mode, s.au_value) == ("pct", 10)
    ok(do(ctx, 1, "CAPN H1 10"))
    assert (s.au_mode, s.au_value) == ("num", 10)
    assert "own" in err(do(ctx, 2, "CSP H1 25 50 25"))


def test_build_ship_costs_and_starport_capacity(ctx):
    # rules:441-444: one ship or two CTs per starport class
    s = sysn(ctx.state, "H1")
    ok(do(ctx, 1, "BS H1 F"))
    sh = [x for x in ctx.state.ships.values() if x.owner == 1][-1]
    assert (sh.type, sh.posture, sh.role, sh.x, sh.y) == ("F", "N", "SC", s.x, s.y)  # rules:2029
    assert s.iu == 470 and ctx.emp(1).eu == 970
    ok(do(ctx, 1, "BCU H1 S"))
    ok(do(ctx, 1, "BCU H1 M"))                              # militia use capacity too
    assert "capacity" in err(do(ctx, 1, "BS H1 S"))


def test_build_requires_tech(ctx):
    assert "You need" in err(do(ctx, 1, "BS H1 D"))
    assert "You need" in err(do(ctx, 1, "BCU H1 J"))


def test_under_attack_costs_double(ctx):
    # rules:419-421
    s = sysn(ctx.state, "H1")
    s.status = K.UNDER_ATTACK
    ok(do(ctx, 1, "BS H1 S"))
    assert s.iu == 460 and ctx.emp(1).eu == 960
    s.status = K.INTERDICTED
    assert "INT" in err(do(ctx, 1, "BCU H1 S"))


def test_militia_limited_by_population(ctx):
    s = sysn(ctx.state, "H1")
    s.starport = 10
    for _ in range(4):
        ok(do(ctx, 1, "BCU H1 M"))
    assert "population" in err(do(ctx, 1, "BCU H1 M"))


def test_bcu_entrench_infantry_only(ctx):
    r = ok(do(ctx, 1, "BCU H1 S E"))
    assert [t.posture for t in ctx.state.troops.values()] == ["E3"]
    ctx.emp(1).techs.add(4)
    r = ok(do(ctx, 1, "BCU H1 C E"))
    assert any("aren't infantry" in m for m in r.messages)


def test_bi_di(ctx):
    s = sysn(ctx.state, "H1")
    ok(do(ctx, 1, "BI H1 3"))
    assert s.infra == 3 and s.iu == 470                    # rules:331 10 IU each
    ok(do(ctx, 1, "DI H1 2"))
    assert s.infra == 1 and ctx.emp(1).eu == 990            # F-03: 5 EU each
    assert "has only" in err(do(ctx, 1, "DI H1 5"))
    s.status = K.UNDER_ATTACK
    assert "UA" in err(do(ctx, 1, "DI H1 1"))               # rules:337-338


def test_bt_artifacts(ctx):
    s = sysn(ctx.state, "H1")
    assert "You need" in err(do(ctx, 1, "BT H1 EHC"))
    ok(do(ctx, 1, "PT 2"))
    ok(do(ctx, 1, "BT H1 EHC"))                             # rules:1726-1731 sequencing
    assert "EHC" in s.artifacts and s.iu == 425             # EHC 75 IU (G-24)
    assert "already has the" in err(do(ctx, 1, "BT H1 EHC"))
    ctx.emp(1).techs |= {42}
    assert "can only be built where there is already" in err(do(ctx, 1, "BT H1 EESS"))   # rules:2989


def test_bt_spy(ctx):
    ctx.emp(1).techs.add(14)
    ok(do(ctx, 1, "BT H1 S"))
    assert len(ctx.state.spies) == 1


def test_dt_needs_normal_status_and_artifact(ctx):
    s = sysn(ctx.state, "H1")
    s.artifacts.add("PD")
    ok(do(ctx, 1, "DT H1 PD"))
    assert "PD" not in s.artifacts
    assert "no Planetary Defenses" in err(do(ctx, 1, "DT H1 PD"))


def test_bsp_cost_and_once_per_turn(ctx):
    # rules:445-461
    s = sysn(ctx.state, "H1")                                # class 2
    ok(do(ctx, 1, "BSP H1"))
    assert s.starport == 3 and s.iu == 450 and ctx.emp(1).eu == 950
    assert "already" in err(do(ctx, 1, "BSP H1"))
    assert "starport" in err(do(ctx, 1, "BS H1 S"))          # can't build after upgrading


def test_bsp_refused_after_build(ctx):
    ok(do(ctx, 1, "BS H1 S"))
    assert "already built" in err(do(ctx, 1, "BSP H1"))


def test_dsp(ctx):
    s = sysn(ctx.state, "H1")
    ok(do(ctx, 1, "DSP H1"))
    assert s.starport == 1 and ctx.emp(1).eu == 990
    assert "already" in err(do(ctx, 1, "DSP H1"))


def test_sisd_sets_desired_amount(ctx):
    # rules:1980-1984: sets (doesn't add) the desired number
    s = sysn(ctx.state, "H1")
    ok(do(ctx, 1, "SISD H1 20"))
    ok(do(ctx, 1, "SISD H1 30"))
    assert ctx.econ[s.id].sisd == 30


def test_ci(ctx):
    s = sysn(ctx.state, "H1")
    ok(do(ctx, 1, "CI H1 3"))
    assert ctx.ci[s.id] == 4 and ctx.emp(1).eu == 970       # rules:2009-2011


# ---- cargo, colonisation ----------------------------------------------------------------

def test_load_unload_capacity(ctx):
    st = ctx.state
    sh = add_ship(st, 1, "T", 10, 10)
    s = sysn(st, "H1")
    ok(do(ctx, 1, f"L {sh.number} P 2"))
    ok(do(ctx, 1, f"L {sh.number} I 20"))
    assert "room for only" in err(do(ctx, 1, f"L {sh.number} A 1"))   # 2 pop + 1 point of IU = 3
    assert s.pop == 2.0 and s.iu == 480
    ok(do(ctx, 1, f"U {sh.number} I 20"))
    assert "carries only" in err(do(ctx, 1, f"U {sh.number} P 3"))


def test_unload_pop_captures_unowned_system(ctx):
    # rules:427-433, 1707-1711
    st = ctx.state
    e1 = sysn(st, "E1")
    sh = add_ship(st, 1, "T", e1.x, e1.y, cargo_pop=2, cargo_iu=20)
    # not ours yet: the error says to land population first (Dave 2026-11-12)
    assert err(do(ctx, 1, f"U {sh.number} I 20")) == (
        "E1 isn't yours yet. Unload population first to claim it, then unload IU/AU in a "
        "later order.")
    assert "isn't yours yet" in err(do(ctx, 1, f"U {sh.number} A 0"))
    r = ok(do(ctx, 1, f"U {sh.number} P 1"))
    assert e1.owner == 1 and e1.pop == 1 and e1.happy == 0.2
    assert ctx.emp(1).systems_captured == e1.hab // 4
    ok(do(ctx, 1, f"U {sh.number} I 20"))
    ok(do(ctx, 1, "BI E1 2"))


def test_unload_on_held_empty_system_needs_assault(ctx):
    st = ctx.state
    e1 = sysn(st, "E1")
    e1.owner = 2
    add_troop(st, 2, "S", system=e1.id)
    sh = add_ship(st, 1, "T", e1.x, e1.y, cargo_pop=2)
    assert "held" in err(do(ctx, 1, f"UG {sh.number} P 1"))


def test_immigration_unhappiness(ctx):
    st = ctx.state
    s = sysn(st, "H2")
    s.happy = 0.3
    sh = add_ship(st, 1, "T", s.x, s.y, cargo_pop=3)
    assert "UG" in err(do(ctx, 1, f"U {sh.number} P 3"))
    h = 4 * 4 * 3 / (3 * 150.0)
    r = ok(do(ctx, 1, f"UG {sh.number} P 3"))
    assert s.pop == 7 and s.happy == pytest.approx(0.3 - h)


def test_sl_loads_anyones_ship(ctx):
    st = ctx.state
    s = sysn(st, "H1")
    sh = add_ship(st, 2, "T", s.x, s.y)
    ok(do(ctx, 1, f"SL {sh.number} I 15"))
    assert sh.cargo_iu == 15


def test_loct_lact(ctx):
    st = ctx.state
    s = sysn(st, "H1")
    sh = add_ship(st, 1, "T", s.x, s.y)
    t = add_troop(st, 1, "S", system=s.id, posture="E")
    m = add_troop(st, 1, "M", system=s.id)
    assert "Militia" in err(do(ctx, 1, f"LOCT {sh.number} {m.number}"))
    ok(do(ctx, 1, f"LOCT {sh.number} {t.number}"))
    assert t.ship == sh.number and t.posture == "A"
    h2 = sysn(st, "H2")
    sh.x, sh.y = h2.x, h2.y
    ok(do(ctx, 1, f"LACT {sh.number} {t.number}"))
    assert t.system == h2.id and sh.posture == "H"            # rules:509-516


def test_loct_from_allied_system(ctx):
    # rules:2209-2210
    st = ctx.state
    s2 = sysn(st, "H2")
    contact(st, 1, 2)
    st.empires[2].relations[1] = "A"
    sh = add_ship(st, 1, "T", s2.x, s2.y)
    t = add_troop(st, 1, "S", system=s2.id)
    ok(do(ctx, 1, f"LOCT {sh.number} {t.number}"))


def test_ss_and_sct_refunds(ctx):
    st = ctx.state
    s = sysn(st, "H1")
    sh = add_ship(st, 1, "F", s.x, s.y)
    ok(do(ctx, 1, f"SS {sh.number}"))
    assert s.iu == 500 + 22 and ctx.emp(1).eu == 1000 + 22    # 75% (rules:577)
    t = add_troop(st, 1, "J", system=s.id)
    ok(do(ctx, 1, f"SCT {t.number}"))
    assert s.iu == 522 + 10 and ctx.emp(1).eu == 1022 + 10    # 50% (rules:606)
    t2 = add_troop(st, 1, "S", system=s.id)
    assert "capacity" in err(do(ctx, 1, f"SCT {t2.number}"))  # SS + SCT used 2 builds


def test_ctt_trade_route(ctx):
    st = ctx.state
    s2 = sysn(st, "H2")
    sh = add_ship(st, 1, "T", s2.x, s2.y)
    assert "Decentralized" in err(do(ctx, 1, f"CTT {sh.number}"))
    ctx.emp(1).techs.add(21)
    ok(do(ctx, 1, f"CTT {sh.number}"))
    assert 1 in s2.trade_routes and not sh.alive
    sh2 = add_ship(st, 1, "T", s2.x, s2.y)
    assert "already" in err(do(ctx, 1, f"CTT {sh2.number}"))


# ---- movement orders, fleets -------------------------------------------------------------

def test_mo_uses_relative_coordinates(ctx):
    st = ctx.state
    sh = add_ship(st, 1, "S", 10, 10)                       # empire 1 home is at (10,10)
    ok(do(ctx, 1, f"MO {sh.number} 52 47"))
    assert (sh.dx, sh.dy) == (12, 7)


def test_ms_requires_scanned_system(ctx):
    st = ctx.state
    sh = add_ship(st, 1, "S", 10, 10)
    st.empires[1].seen_systems.pop(sysn(st, "E2").id)
    assert "scanned" in err(do(ctx, 1, f"MS {sh.number} E2"))
    ok(do(ctx, 1, f"MS {sh.number} E1"))


def test_fleets(ctx):
    st = ctx.state
    a = add_ship(st, 1, "F", 10, 10)
    b = add_ship(st, 1, "T", 10, 10)
    ok(do(ctx, 1, "CF Task 50 50"))
    assert "already have a fleet called Task" in err(do(ctx, 1, "CF Task 50 50"))
    ok(do(ctx, 1, f"AF Task {a.number} {b.number}"))
    f = st.fleet_named("Task")
    assert a.fleet == b.fleet == f.number
    ok(do(ctx, 1, "CFP Task AN"))                           # B-12
    assert (a.posture, b.posture) == ("N", "F")
    ok(do(ctx, 1, "CFCR Task OF"))
    assert (a.role, b.role) == ("MR", "SC")
    assert "don't have a fleet" in err(do(ctx, 2, "MFS Task E1"))           # B-11
    ok(do(ctx, 1, "FS Task 3"))
    assert f.speed == 3
    ok(do(ctx, 1, f"LF Task {b.number}"))
    assert b.fleet is None


def test_cfcr_ro(ctx):
    st = ctx.state
    ships = [add_ship(st, 1, t, 10, 10) for t in ("F", "F", "F", "S")]
    tr = add_ship(st, 1, "T", 10, 10)
    add_troop(st, 1, "S", ship=tr.number)
    ok(do(ctx, 1, "CF Task 50 50"))
    ok(do(ctx, 1, "AF Task " + " ".join(str(s.number) for s in ships + [tr])))
    ok(do(ctx, 1, "CFCR Task RO 1 1 SC"))
    assert [s.role for s in ships] == ["GC", "RD", "MR", "SC"]
    assert tr.role == "RD" and tr.posture == "N"


def test_fleet_load_exact(ctx):
    # B-14: FL loads exactly n
    st = ctx.state
    t1, t2 = add_ship(st, 1, "T", 10, 10), add_ship(st, 1, "T", 10, 10)
    ok(do(ctx, 1, "CF Task 50 50"))
    ok(do(ctx, 1, f"AF Task {t1.number} {t2.number}"))
    ok(do(ctx, 1, "FL Task P 4"))
    assert t1.cargo_pop + t2.cargo_pop == 4 and sysn(st, "H1").pop == 0
    assert "room for only" in err(do(ctx, 1, "FL Task I 100"))


# ---- diplomacy ---------------------------------------------------------------------------

def test_alliance_table(ctx):
    # rules:734-743
    st = ctx.state
    contact(st, 1, 2)
    e1, e2 = st.empires[1], st.empires[2]
    ok(do(ctx, 1, "DA R2"))
    assert (e1.relations[2], e2.relations[1]) == ("A", "N")
    assert "already allied" in err(do(ctx, 1, "DA R2"))
    ok(do(ctx, 1, "EWA R2"))
    assert e1.relations[2] == "N"
    assert "neither at war nor allied" in err(do(ctx, 1, "EWA R2"))
    ok(do(ctx, 2, "DW R1"))
    assert (e1.relations[2], e2.relations[1]) == ("W", "W")
    assert "already at war" in err(do(ctx, 1, "DW R2"))
    assert "at war" in err(do(ctx, 1, "DA R2"))
    ok(do(ctx, 1, "EWA R2"))
    assert e1.relations[2] == "E"
    ok(do(ctx, 2, "EWA R1"))
    assert (e1.relations[2], e2.relations[1]) == ("N", "N")


def test_gift_eus(ctx):
    st = ctx.state
    assert "contact" in err(do(ctx, 1, "GE R2 100"))
    contact(st, 1, 2)
    ctx.orders_done.add(2)
    ok(do(ctx, 1, "GE R2 100"))
    assert st.empires[1].eu == 900 and st.empires[2].eu == 1100
    ev = ctx.res.events_of(2, "eu_received")[0]
    assert ev.data["late"]


def test_dd_sd(ctx):
    contact(ctx.state, 1, 2)
    ok(do(ctx, 1, "DD R2 50"))
    ok(do(ctx, 1, "SD R2 30"))
    assert ctx.emp(1).deny_trade[2] == 50 and ctx.emp(1).split_trade[2] == 30


def test_crn_once_and_unique(ctx):
    ok(do(ctx, 1, "CRN Blow_Hards"))
    assert ctx.emp(1).name == "Blow_Hards"
    assert "already renamed" in err(do(ctx, 1, "CRN Other"))
    assert "taken" in err(do(ctx, 2, "CRN Blow_Hards"))


def test_message_order(ctx):
    from mhgc.engine.turn import deliver_messages
    from mhgc.orders import parse_orders_text
    from mhgc.engine.orders_exec import execute
    o = parse_orders_text("MESSAGE R2\nPrepare to die, alien scum!\n.\n")[0].order
    ok(execute(ctx, 1, o, 0))
    deliver_messages(ctx)
    assert ctx.res.report(2).messages[0]["text"] == "Prepare to die, alien scum!"
    assert not ctx.res.report(3).messages


# ---- leaders, spies ----------------------------------------------------------------------

def test_leader_orders(ctx):
    st = ctx.state
    ld = add_leader(st, 1, system=sysn(st, "H1").id)
    ok(do(ctx, 1, f"CLN {ld.name} Galrond"))
    assert "already renamed" in err(do(ctx, 1, "CLN Galrond Other"))
    assert "don't own a system" in err(do(ctx, 1, "ML Galrond H2"))
    ok(do(ctx, 1, "ML Galrond H1"))
    assert (ld.status, ld.transit) == ("transit", 2)
    ok(do(ctx, 1, "PLOI Galrond"))
    assert (ld.status, ld.transit) == ("ice", 5)


def test_spy_orders(ctx):
    st = ctx.state
    st.empires[1].techs.add(14)
    ok(do(ctx, 1, "BT H1 S"))
    sp = next(iter(st.spies.values()))
    contact(st, 1, 2)
    ok(do(ctx, 1, f"SMV {sp.number} H2"))
    assert sp.system == sysn(st, "H2").id and sp.transit == max(1, int(10 / 6 + 0.5))
    assert "still travelling" in err(do(ctx, 1, f"SOS {sp.number}"))
    sp.transit = 0
    assert "no leader" in err(do(ctx, 1, f"SAL {sp.number}"))
    ok(do(ctx, 1, f"SOT {sp.number}"))
    assert sp.mission == "SOT"


# ---- order checking ----------------------------------------------------------------------

def test_check_orders_is_a_dry_run():
    st = make_state()
    before = to_dict(st)
    res = check_orders(st, 1, parse_orders("PT 2\nBT H1 EHC\nBS H1 F\nBT H1 EHC"))
    assert [r.ok for r in res] == [True, True, True, False]
    assert to_dict(st) == before


# ---- GS and war (Dave 2026-11-12) ------------------------------------------------------------

def test_gs_refused_while_at_war_by_our_own_stance():
    from mhgc.engine.turn import run_turn
    for mine, theirs, allowed in (("W", "W", False), ("E", "W", False), ("N", "N", True),
                                  ("A", "N", True), ("N", "W", True)):
        st = make_state()
        contact(st, 1, 2, mine, back=theirs)
        h1 = sysn(st, "H1")
        add_ship(st, 1, "F", h1.x, h1.y, number=501)
        chk = check_orders(st, 1, parse_orders("GS R2 501"))[0]
        res = run_turn(from_dict(to_dict(st)), {1: parse_orders("GS R2 501")}, npr_fn=None)
        got = res.report(1).orders[0]
        assert chk.ok is allowed and got.ok is allowed, (mine, theirs, chk.error, got.error)
        if not allowed:
            # "you are at war" = the giver's stance; the recipient's (hidden) stance is not used
            assert chk.error == got.error and "at war with them" in chk.error
            assert "R2" in chk.error


# ---- messages that must not reveal hidden things ----------------------------------------------

def test_lookup_messages_do_not_reveal_unseen_things(ctx):
    st = ctx.state
    h2 = sysn(st, "H2")
    foreign = add_ship(st, 2, "F", h2.x, h2.y, number=777)
    # a foreign ship and a ship number nobody uses read the same
    assert err(do(ctx, 1, "DS 777")) == "Ship 777 doesn't exist or isn't yours."
    assert err(do(ctx, 1, "DS 778")) == "Ship 778 doesn't exist or isn't yours."
    # SL: a ship at someone else's system reads the same as no ship at all
    assert err(do(ctx, 1, "SL 777 A 1")) == "Ship 777 isn't at one of your systems."
    assert err(do(ctx, 1, "SL 778 A 1")) == "Ship 778 isn't at one of your systems."
    assert foreign.alive
    # an unscanned system and a name that doesn't exist read the same
    st.empires[1].seen_systems.pop(h2.id)
    add_ship(st, 1, "S", 10, 10, number=501)
    assert err(do(ctx, 1, "MS 501 H2")) == "You haven't scanned a system called H2."
    assert err(do(ctx, 1, "MS 501 Nowhere")) == "You haven't scanned a system called Nowhere."
    # someone else's system and a missing one read the same for "your system" orders
    assert err(do(ctx, 1, "CAP H2 50")) == err(do(ctx, 1, "CAP Nowhere 50")).replace(
        "Nowhere", "H2")
    # an existing but uncontacted race and an unknown name read the same
    assert err(do(ctx, 1, "GE R2 1")) == "You haven't made contact with a race called R2."
    assert err(do(ctx, 1, "GE Zz 1")) == "You haven't made contact with a race called Zz."


def test_claim_order_sequence_works_in_one_turn():
    """The UI's "Claim this system" adds U P first, then U I / U A (app/ui/orders.js
    claimOrders); that sequence captures an unowned system and unloads everything, while the
    reverse order fails on the IU line."""
    from mhgc.engine.turn import run_turn
    st = make_state()
    e1 = sysn(st, "E1")
    add_ship(st, 1, "T", e1.x, e1.y, number=501, cargo_pop=1, cargo_iu=10, cargo_au=5)
    bad = check_orders(st, 1, parse_orders("U 501 I 10\nU 501 P 1"))
    assert not bad[0].ok and "Unload population first" in bad[0].error and bad[1].ok
    res = run_turn(st, {1: parse_orders("U 501 P 1\nU 501 I 10\nU 501 A 5")}, npr_fn=None)
    assert all(o.ok for o in res.report(1).orders), [o.error for o in res.report(1).orders]
    assert e1.owner == 1 and e1.iu >= 10 and e1.au >= 5
    assert any(ev.kind == "colonized" and "unowned system E1" in ev.text
               for ev in res.report(1).events)


def test_release_empties_the_system_like_depopulation(ctx):
    """Dave 2026-11-14 (DECISIONS G-13): SR used to hand a partner the stockpiles,
    infrastructure, starport and artifacts intact; a released system is now emptied exactly as a
    depopulated one is, so the planet-swap gains nothing by releasing instead of dying out."""
    st = ctx.state
    h1 = sysn(st, "H1")
    h1.pop, h1.au, h1.iu, h1.infra, h1.starport = 1.0, 40, 300, 3, 2
    h1.artifacts.add("EUS")
    ok(do(ctx, 1, "SR H1"))
    assert h1.owner == 0 and h1.pop == 0
    assert (h1.au, h1.iu, h1.infra, h1.starport, h1.artifacts) == (0, 0, 0, 0, set())
    # a partner landing population now gets an empty world, the same as after depopulation
    sh = add_ship(st, 2, "T", h1.x, h1.y, cargo_pop=1)
    ok(do(ctx, 2, f"U {sh.number} P 1"))
    assert h1.owner == 2 and (h1.iu, h1.infra, h1.starport, h1.artifacts) == (0, 0, 0, set())


def test_fleet_names_are_unique_per_empire_not_galaxy_wide(ctx):
    """Dave 2026-11-16 (DECISIONS G-16): two races may both have a fleet called Alpha; each
    order means the orderer's own fleet, and only a second Alpha of your own is refused."""
    st = ctx.state
    h1, h2 = sysn(st, "H1"), sysn(st, "H2")
    s1 = add_ship(st, 1, "SC", h1.x, h1.y)
    s2 = add_ship(st, 2, "SC", h2.x, h2.y)
    # orders use coordinates relative to each empire's home, which is 50,50
    ok(do(ctx, 1, "CF Alpha 50 50"))
    ok(do(ctx, 2, "CF Alpha 50 50"))           # no longer "already taken"
    assert "already have a fleet called Alpha" in err(do(ctx, 1, "CF Alpha 50 50"))
    ok(do(ctx, 1, f"AF Alpha {s1.number}"))
    ok(do(ctx, 2, f"AF Alpha {s2.number}"))
    f1, f2 = st.fleet_named("Alpha", 1), st.fleet_named("Alpha", 2)
    assert f1 is not f2 and f1.owner == 1 and f2.owner == 2
    assert s1.fleet == f1.number and s2.fleet == f2.number
    ok(do(ctx, 2, "MF Alpha 53 50"))           # moves race 2's Alpha only
    assert (f2.dx, f2.dy) == (h2.x + 3, h2.y) and (f1.dx, f1.dy) == (h1.x, h1.y)


def test_invalid_ttnpr_does_not_use_the_turns_trade_attempt(ctx):
    """Dave 2026-11-16: a TTNPR that fails its checks (here: they already have the tech) doesn't
    count as the turn's one trade attempt; only an offer that reaches the NPR's decision does."""
    st = ctx.state
    me, npr = st.empires[1], st.empires[3]
    contact(st, 1, 3)
    me.techs |= {0, 2, 3}
    npr.techs |= {0, 2, 5}
    assert "already have that tech" in err(do(ctx, 1, "TTNPR 2 5 R3"))     # they own EHC
    r = do(ctx, 1, "TTNPR 3 5 R3")                                           # a valid offer
    assert "already tried a tech trade" not in (r.error or "")


def test_tech_slot_message_names_what_used_it(ctx):
    """The one-tech-a-turn refusal says which order used the slot and points at CRP."""
    st = ctx.state
    me, npr = st.empires[1], st.empires[3]
    contact(st, 1, 3)
    me.techs |= {0, 3}
    npr.techs |= {0, 5}
    ok(do(ctx, 1, "PT 2"))
    e = err(do(ctx, 1, "TTNPR 3 5 R3"))
    assert "you bought Extended Home Computing (PT) earlier this turn" in e and "CRP" in e
    e2 = err(do(ctx, 1, "PT 1"))
    assert "you bought Extended Home Computing (PT)" in e2
    ok(do(ctx, 1, "CRP 1"))                                                  # crash research is outside the limit
