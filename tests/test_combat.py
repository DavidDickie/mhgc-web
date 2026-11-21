"""Combat (rules:757-1060)."""
import pytest

from mhgc.data import constants as K
from mhgc.engine import combat
from mhgc.engine.combat import Combat
from tests.conftest import (ScriptedRng, add_leader, add_ship, add_troop, contact, ctx_for, do,
                            make_state, sysn)


def _combat(st, x, y, rng=None, system=True):
    ctx = ctx_for(st, rng)
    s = st.system_at(x, y) if system else None
    c = Combat(ctx, x, y, s)
    c._rel = {}
    return ctx, c


# ---- relations (rules:492-505, 716-754) --------------------------------------------------

def test_hostile_vs_friendly_has_initiative():
    st = make_state()
    a = add_ship(st, 1, "F", 70, 70, posture="H")
    b = add_ship(st, 2, "F", 70, 70, posture="F")
    ctx, c = _combat(st, 70, 70, system=False)
    assert c.relation(1, 2) == ("init", 1)


def test_relation_table():
    st = make_state()
    a = add_ship(st, 1, "F", 70, 70, posture="N")
    b = add_ship(st, 2, "F", 70, 70, posture="F")
    rng = ScriptedRng(chance=True)
    ctx, c = _combat(st, 70, 70, rng, system=False)
    assert c.relation(1, 2) == "mutual" and rng.calls == [10]     # N vs F: 10%
    b.posture = "N"
    rng = ScriptedRng(chance=False)
    ctx, c = _combat(st, 70, 70, rng, system=False)
    assert c.relation(1, 2) is None and rng.calls == [50]         # N vs N: 50%
    a.posture = b.posture = "F"
    ctx, c = _combat(st, 70, 70, system=False)
    assert c.relation(1, 2) is None


def test_war_and_alliance_override_postures():
    st = make_state()
    add_ship(st, 1, "F", 70, 70, posture="F")
    add_ship(st, 2, "F", 70, 70, posture="H")
    contact(st, 1, 2, "W")
    ctx, c = _combat(st, 70, 70, system=False)
    assert c.relation(1, 2) == "mutual"                  # at war: no initiative (rules:750-754)
    contact(st, 1, 2, "A", back="A")
    ctx, c = _combat(st, 70, 70, system=False)
    assert c.relation(1, 2) is None                      # allied both ways
    st.empires[2].relations[1] = "N"
    ctx, c = _combat(st, 70, 70, system=False)
    assert c.relation(1, 2) == ("init", 2)               # one-sided alliance: you are friendly


# ---- roles, MFB --------------------------------------------------------------------------

def test_mixed_fleet_bonus_rules_example():
    # rules:827-832: FF, F, Patroller, Striker, 1/1/2/5 attack -> 18 instead of 9
    st = make_state()
    for t in ("FF", "F", "PA", "ST"):
        add_ship(st, 1, t, 70, 70)
    ctx, c = _combat(st, 70, 70, system=False)
    assert c.mfb(1) == pytest.approx(18 / 9)


def test_role_shift_rules_example():
    # RULEBOOK COMBAT EXAMPLE (2026-11-19 stats, D 3/5): D1 SC + T SC = 3 < 4 Groachi defence
    # (frigate and two scouts), so D2 (GC) shifts at half attack, 3 // 2 = 1
    st = make_state()
    d1 = add_ship(st, 1, "D", 70, 70, posture="N", role="SC")
    d2 = add_ship(st, 1, "D", 70, 70, posture="N", role="GC")
    f1 = add_ship(st, 1, "F", 70, 70, posture="N", role="GC")
    f2 = add_ship(st, 1, "F", 70, 70, posture="N", role="RD")
    t1 = add_ship(st, 1, "T", 70, 70, posture="H", role="SC")
    add_ship(st, 2, "F", 70, 70, posture="F")
    add_ship(st, 2, "S", 70, 70, posture="F")
    add_ship(st, 2, "S", 70, 70, posture="F")
    rng = ScriptedRng(chance=None)
    rng.shuffle = lambda seq: seq.sort(key=lambda s: s.number)    # D2 before F1
    ctx, c = _combat(st, 70, 70, rng, system=False)
    c.assign_roles(1)
    assert c.pool(1, "SC") == 4 and c.pool(1, "GC") == 1 and c.pool(1, "RD") == 1
    assert c.roles[d2.number] == ("SC", 1)


def test_mr_bombards_at_half_without_enemy_ships():
    st = make_state()
    s2 = sysn(st, "H2")
    add_ship(st, 1, "C", s2.x, s2.y, posture="H", role="MR")       # attack 7, halved down
    ctx, c = _combat(st, s2.x, s2.y)
    c.assign_roles(1)
    assert c.pool(1, "GC") == 3 and c.pool(1, "SC") == 0


# ---- space combat ------------------------------------------------------------------------

def test_initiative_kills_do_not_fire_back():
    st = make_state()
    a = add_ship(st, 1, "C", 70, 70, posture="H")        # attack 7
    b = add_ship(st, 2, "F", 70, 70, posture="F")        # defence 2, attack 1
    rng = ScriptedRng(chance=True, roll_max=True)
    ctx, c = _combat(st, 70, 70, rng, system=False)
    c.space_combat()
    assert not b.alive and a.alive


def test_mutual_fire_is_simultaneous():
    st = make_state()
    a = add_ship(st, 1, "ST", 70, 70, posture="H")       # strikers: 5 attack, 1 defence
    b = add_ship(st, 2, "ST", 70, 70, posture="H")
    rng = ScriptedRng(chance=True, roll_max=True)
    ctx, c = _combat(st, 70, 70, rng, system=False)
    c.space_combat()
    assert not a.alive and not b.alive                  # both fire before removal


def test_targets_ordered_by_role():
    st = make_state()
    add_ship(st, 1, "D", 70, 70, posture="H")            # attack 3
    sc = add_ship(st, 2, "S", 70, 70, posture="F", role="SC")
    rd = add_ship(st, 2, "S", 70, 70, posture="F", role="RD")
    rng = ScriptedRng(chance=False)
    rng.between = lambda lo, hi: 1                      # effective attack 1
    ctx, c = _combat(st, 70, 70, rng, system=False)
    c.space_combat()
    assert not sc.alive and rd.alive                    # SC role is shot first


def test_partial_shot_chance():
    # rules:813-814: remaining SC / defence chance
    st = make_state()
    add_ship(st, 1, "F", 70, 70, posture="H")            # attack 1
    tgt = add_ship(st, 2, "D", 70, 70, posture="F")      # defence 5
    rng = ScriptedRng(chance=None)
    rng.between = lambda lo, hi: 1
    rng.random = lambda: 0.19                           # roll 19 < 20 -> kill
    ctx, c = _combat(st, 70, 70, rng, system=False)
    c.space_combat()
    assert not tgt.alive


def test_system_weapons():
    # rules:2697 PD -1, 2892 SW -5 and +1 attack, 3001 APD 5 attack
    st = make_state()
    s2 = sysn(st, "H2")
    s2.artifacts |= {"PD", "SW", "APD"}
    add_ship(st, 1, "C", s2.x, s2.y, posture="H")        # 7 attack
    ctx, c = _combat(st, s2.x, s2.y)
    assert c.space_attack(1) == 1                        # 7 - PD 1 - SW 5
    assert c.space_attack(2) == 6                        # SW 1 + APD 5, no ships


# ---- ship to ground ----------------------------------------------------------------------

def test_bombardment_partial_chance_rules_example():
    # rules:1036-1040: frigate (GC, 1 attack) vs militia in Defend (2) -> 1/(5*2) = 10%
    st = make_state()
    s2 = sysn(st, "H2")
    add_ship(st, 1, "F", s2.x, s2.y, posture="H", role="GC")
    m = add_troop(st, 2, "M", system=s2.id, posture="D")
    rng = ScriptedRng(chance=None)
    rng.random = lambda: 0.5
    ctx, c = _combat(st, s2.x, s2.y, rng)
    c.bombardment()
    assert m.alive
    assert any("[50/10]" in ln["text"] for ln in c.log.lines)


def test_bombardment_full_kills_and_pd_halving():
    st = make_state()
    s2 = sysn(st, "H2")
    add_ship(st, 1, "C", s2.x, s2.y, posture="H", role="GC")    # 6 attack
    add_ship(st, 1, "C", s2.x, s2.y, posture="H", role="GC")    # 12 total
    t1 = add_troop(st, 2, "S", system=s2.id)                    # def 2 -> 8 points
    rng = ScriptedRng(chance=False)                             # no caves
    ctx, c = _combat(st, s2.x, s2.y, rng)
    c.bombardment()
    assert not t1.alive
    st = make_state()
    s2 = sysn(st, "H2")
    s2.artifacts.add("PD")
    add_ship(st, 1, "C", s2.x, s2.y, posture="H", role="GC")
    add_ship(st, 1, "C", s2.x, s2.y, posture="H", role="GC")
    t1 = add_troop(st, 2, "S", system=s2.id)                    # PD: 16 points needed
    rng = ScriptedRng(chance=False)
    rng.random = lambda: 0.99
    ctx, c = _combat(st, s2.x, s2.y, rng)
    c.bombardment()
    assert t1.alive


def test_raid_rules_example():
    # rules:1040-1046: 1 raid point: 1/25 = 4% pop, 1*2/cost vs EHC.  The rules' example
    # has EHC at 50 IU (4%); repriced to 75 IU (Dave 2026-11-19, DECISIONS G-24): 2.67%
    st = make_state()
    s2 = sysn(st, "H2")
    s2.artifacts = {"EHC"}
    add_ship(st, 1, "F", s2.x, s2.y, posture="H", role="RD")
    rng = ScriptedRng(chance=True, below=[3])
    ctx, c = _combat(st, s2.x, s2.y, rng)
    c.raid()
    assert rng.calls == [4.0, pytest.approx(100 * 2 / 75)]
    assert s2.pop == 3 and not s2.artifacts


def test_raid_full_points():
    st = make_state()
    s2 = sysn(st, "H2")
    s2.infra = 5
    for _ in range(5):
        add_ship(st, 1, "PA", s2.x, s2.y, posture="H", role="RD")     # 10 raid points
    rng = ScriptedRng(chance=False, below=[0, 1])
    ctx, c = _combat(st, s2.x, s2.y, rng)
    c.raid()
    assert s2.infra == 4 and s2.iu == 490


# ---- ground combat, capture, status ------------------------------------------------------

def test_ground_capture():
    # rules:952-966
    st = make_state()
    s2 = sysn(st, "H2")
    s2.au = 40
    gov = add_leader(st, 2, system=s2.id)
    for _ in range(3):
        add_troop(st, 1, "J", system=s2.id)
    m = add_troop(st, 2, "M", system=s2.id, posture="D")
    rng = ScriptedRng(chance=False, roll_max=True)
    ctx, c = _combat(st, s2.x, s2.y, rng)
    c.ground_combat()
    assert not m.alive
    c.check_capture()
    assert s2.owner == 1 and s2.au == 0 and s2.iu == 0 and not gov.alive
    assert 2.0 <= s2.pop <= 3.6
    assert ctx.res.events_of(2, "system_lost") and ctx.res.events_of(1, "system_captured")
    assert st.empires[1].systems_captured == s2.hab and st.empires[2].systems_captured == -s2.hab


def test_defending_troops_have_no_attack_entrenched_half():
    st = make_state()
    s2 = sysn(st, "H2")
    a = add_troop(st, 1, "O", system=s2.id, posture="E")       # attack 15 -> 7
    d = add_troop(st, 2, "O", system=s2.id, posture="D")
    rng = ScriptedRng(chance=False, roll_max=True)
    ctx, c = _combat(st, s2.x, s2.y, rng)
    c.ground_combat()
    assert any("WUSSY" in ln["text"] and "R2" in ln["text"] for ln in c.log.lines)
    assert d.alive                                            # 7 vs ceil(1.5*20)=30


def test_tech_capture_only_from_better_teched_race():
    st = make_state()
    s2 = sysn(st, "H2")
    st.empires[2].techs |= {1, 2, 3, 4, 5}
    ctx = ctx_for(st)
    combat.change_owner(ctx, s2, 1, "capture")
    assert any(t in st.empires[1].techs for t in (1, 2, 3, 4, 5))
    st = make_state()
    s2 = sysn(st, "H2")
    st.empires[2].techs |= {1, 2, 3}
    ctx = ctx_for(st)
    combat.change_owner(ctx, s2, 1, "capture")
    assert st.empires[1].techs == {0}


def test_status_thresholds_and_one_step():
    # rules:920-950
    st = make_state()
    s2 = sysn(st, "H2")
    for _ in range(2):
        add_ship(st, 1, "D", s2.x, s2.y, posture="H")         # 6 attack
    add_ship(st, 2, "F", s2.x, s2.y)                          # 2 defence -> exactly 3:1
    ctx, c = _combat(st, s2.x, s2.y)
    assert c.determine_status()[0] == K.UNDER_ATTACK          # F-04: needs more than 3x
    add_ship(st, 1, "D", s2.x, s2.y, posture="H")
    ctx, c = _combat(st, s2.x, s2.y)
    assert c.determine_status()[0] == K.INTERDICTED
    c.set_status()
    assert s2.status == K.UNDER_ATTACK                        # one category a turn


def test_neutral_ships_do_not_attack_systems():
    st = make_state()
    s2 = sysn(st, "H2")
    add_ship(st, 1, "C", s2.x, s2.y, posture="N")
    ctx, c = _combat(st, s2.x, s2.y)
    assert c.determine_status()[0] == K.NORMAL


def test_ground_interdiction():
    st = make_state()
    s2 = sysn(st, "H2")
    add_troop(st, 1, "J", system=s2.id)                       # attack 3
    add_troop(st, 2, "S", system=s2.id)                       # defence 2
    ctx, c = _combat(st, s2.x, s2.y)
    assert c.determine_status() == (K.INTERDICTED, "int_ground")


def test_rebel_join():
    # rules:700-701
    st = make_state()
    s2 = sysn(st, "H2")
    s2.happy = -0.2
    s2.status = K.UNDER_ATTACK
    add_ship(st, 1, "F", s2.x, s2.y, posture="H")
    add_troop(st, 2, "S", system=s2.id)
    rng = ScriptedRng(chance=True)
    ctx, c = _combat(st, s2.x, s2.y, rng)
    c.check_capture()
    assert s2.owner == 1 and rng.calls[0] == K.REBEL_JOIN_CHANCE
    assert all(t.owner == 1 for t in st.troops_at(s2.id))


def test_status_decay_outside_combat():
    st = make_state()
    s = sysn(st, "H1")
    s.status = K.INTERDICTED
    ctx = ctx_for(st)
    combat.status_decay(ctx)
    assert s.status == K.UNDER_ATTACK


def test_find_combats_and_contact():
    st = make_state()
    add_ship(st, 1, "S", 70, 70)
    add_ship(st, 2, "S", 70, 70)
    ctx = ctx_for(st)
    combat.find_combats(ctx)
    assert len(ctx.res.combats) == 1 and 2 in st.empires[1].relations
    assert ctx.res.report(1).combats == [0]


def test_rules_combat_example_scenario():
    """rules:985-1060.  Porkines (empire 1) land troops at a Groachi (empire 2) system with
    D1 N/SC, D2 N/GC, F1 N/GC, F2 N/RD and a transport F/SC; the Groachi have a friendly
    frigate and two scouts (RULEBOOK, 2026-11-19 stats).  Landing troops makes the Porkines hostile, so they fire first, and the
    system can only move one step (to UNDER ATTACK) this turn."""
    st = make_state()
    g = sysn(st, "H2")
    g.mr = True
    g.pop = 8.0
    contact(st, 1, 2)
    ctx = ctx_for(st)
    for t, p, r in (("D", "N", "SC"), ("D", "N", "GC"), ("F", "N", "GC"), ("F", "N", "RD")):
        add_ship(st, 1, t, g.x, g.y, posture=p, role=r)
    tr = add_ship(st, 1, "T", g.x, g.y, posture="F", role="SC")
    jumps = [add_troop(st, 1, "J", ship=tr.number) for _ in range(3)]
    for _ in range(3):
        add_troop(st, 2, "M", system=g.id, posture="D")
        add_troop(st, 2, "S", system=g.id, posture="D")
    add_ship(st, 2, "F", g.x, g.y, posture="F")
    add_ship(st, 2, "S", g.x, g.y, posture="F")
    add_ship(st, 2, "S", g.x, g.y, posture="F")
    for j in jumps:
        assert do(ctx, 1, f"LACT {tr.number} {j.number}").ok
    assert tr.posture == "H"
    c = Combat(ctx, g.x, g.y, g)
    c.run()
    assert c.log.relations["1,2"] == "SURPRISE ATTACK by R1"
    assert g.status == K.UNDER_ATTACK or g.owner == 1
    assert ctx.res.combats and ctx.res.report(2).combats
