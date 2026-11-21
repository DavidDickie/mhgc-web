"""Game data matches the rules' generated tables (DECISIONS F-01, F-02)."""
from mhgc.data import ARTIFACTS, SHIP_TYPES, TECHS, TROOP_TYPES, tech_vp
from mhgc.data.techs import FUTURE_TECH, all_prereqs, missing_prereqs


def test_52_technologies():
    assert len(TECHS) == 52 and set(TECHS) == set(range(52))


def test_tech_costs_follow_generated_table():
    # rules:3176-3231 "TECHS GROUPED BY COST"
    assert TECHS[1].cost == 100 and TECHS[8].cost == 250 and TECHS[18].cost == 500
    assert TECHS[27].cost == 1000 and TECHS[37].cost == 2000 and TECHS[43].cost == 3000
    assert TECHS[49].cost == 4000
    # repriced (Dave 2026-11-19, DECISIONS G-24): EESS's tech 3000 -> 2000, Warp Tunnel 4000 -> 2000
    assert TECHS[42].cost == 2000 and TECHS[50].cost == 2000


def test_prereqs_follow_generated_table():
    assert TECHS[19].prereqs == (9, 4)        # NES: AMT + Cybernetic Tanks
    assert TECHS[44].prereqs == (32, 41)      # APD: Farcaster + Tachyon
    assert TECHS[50].prereqs == (43, 44)      # Warp Tunnel: Alchemy + APD
    assert TECHS[41].prereqs == (32, 25)      # Tachyon: Farcaster + IE II


def test_future_tech_f02():
    ft = TECHS[FUTURE_TECH]
    assert ft.cost == 8000 and ft.prereqs == (45, 50)
    assert tech_vp(FUTURE_TECH) == 4


def test_tech_vp_table():
    # rules:212-216
    assert [tech_vp(t) for t in (1, 8, 18, 27, 37, 42, 49)] == [0, 0, 1, 1, 2, 2, 3]


def test_transitive_prereqs():
    assert all_prereqs(18) == {8, 1}
    assert missing_prereqs({0, 8}, 18) == [1]
    assert missing_prereqs({0, 1, 8}, 18) == []


def test_ship_chart():
    assert len(SHIP_TYPES) == 28 and "UN" not in SHIP_TYPES
    s = SHIP_TYPES
    assert (s["S"].attack, s["S"].defense, s["S"].scan, s["S"].move, s["S"].cargo) == (0, 1, 3, 4, 0)
    assert (s["T"].cargo, s["T"].iu_cost, s["T"].eu_cost) == (3, 20, 20)
    assert (s["F"].attack, s["F"].defense, s["F"].iu_cost) == (1, 2, 30)
    assert (s["D"].iu_cost, s["D"].eu_cost) == (40, 40)          # F-01
    assert s["GU"].move == 3 and s["FB"].cargo == 1
    assert (s["FC"].attack, s["FC"].defense, s["FC"].scan, s["FC"].move) == (7, 8, 3, 7)


def test_troop_chart():
    t = TROOP_TYPES
    assert (t["M"].attack, t["M"].defense, t["M"].maint_eu, t["M"].transportable) == (1, 1, 2, False)
    assert (t["S"].infantry, t["S"].maint_eu) == (True, 2)       # F-08
    assert (t["C"].attack, t["C"].defense) == (5, 3)              # F-01
    assert (t["O"].attack, t["O"].defense, t["O"].tech) == (15, 20, 35)


def test_artifact_costs():
    a = ARTIFACTS
    assert (a["PD"].iu_cost, a["PD"].eu_cost, a["PD"].maint_eu) == (25, 25, 3)
    assert (a["CS"].iu_cost, a["CS"].eu_cost) == (100, 100)
    assert (a["APD"].iu_cost, a["APD"].maint_eu) == (100, 5)
    assert a["EHC"].maint_eu == 2 and a["BF"].maint_eu == 0
