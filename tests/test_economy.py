"""Production, happiness, rebellion, growth, trade (rules:296-434, 665-706)."""
import math

import pytest

from mhgc.data import constants as K
from mhgc.engine import economy
from tests.conftest import ScriptedRng, add_leader, add_troop, ctx_for, make_state, sysn


def _one_system(st, **kw):
    s = sysn(st, "H1")
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def test_rules_production_example():
    # rules:412-417: 4 pop, defaults, no tech or bonuses -> 10 AU, 5 IU, 5 EU
    st = make_state()
    s = _one_system(st, starport=0, au=0, iu=0)
    ctx = ctx_for(st)
    eu0 = st.empires[1].eu
    economy.produce(ctx)
    ec = ctx.econ[s.id]
    assert (ec.prod_au, ec.prod_iu, ec.prod_eu) == (10, 5, 5)
    assert s.au == 10 and s.iu == 5 and st.empires[1].eu == eu0 + 5


def test_starport_adds_ten_percent_per_class():
    # rules:452-454: class 1 starport, 4 pop -> 22 units instead of 20
    st = make_state()
    s = _one_system(st, starport=1)
    ctx = ctx_for(st)
    economy.produce(ctx)
    ec = ctx.econ[s.id]
    assert (ec.prod_au, ec.prod_iu, ec.prod_eu) == (11, 5, 5)   # 22 * 50/25/25%, truncated


def test_infrastructure_doubles_up_to_population():
    # rules:332-335: 1 IF doubles one billion pop's production; more IF than pop doesn't help
    st = make_state()
    s = _one_system(st, starport=0, infra=2)
    ctx = ctx_for(st)
    economy.produce(ctx)
    assert ctx.econ[s.id].prod_au == 15            # 4 pop * 5 * 1.5 * 50%
    st2 = make_state()
    s2 = _one_system(st2, starport=0, infra=10)
    ctx2 = ctx_for(st2)
    economy.produce(ctx2)
    assert ctx2.econ[s2.id].prod_au == 20          # capped at x2


def test_metal_rich_and_artifacts():
    st = make_state()
    s = _one_system(st, starport=0, mr=True, artifacts={"CM", "AL", "CB", "VRB", "BF", "AF"})
    ctx = ctx_for(st)
    economy.produce(ctx)
    ec = ctx.econ[s.id]
    assert ec.prod_iu == int(20 * 0.25 * 2 * 1.5 * 1.5)       # MR doubles; CM, AL +50% each
    assert ec.prod_eu == int(20 * 0.25 * 1.5 * 1.5)           # CB+VRB = +125% (rules:2927)
    assert ec.prod_au == int(20 * 0.5 * 1.5 * 1.5)            # BF+AF = +125% (rules:2953)


def test_status_effects_on_production():
    # rules:419-425: UA half, INT none (and trade routes lost)
    st = make_state()
    s = _one_system(st, starport=0, status=K.UNDER_ATTACK)
    ctx = ctx_for(st)
    economy.produce(ctx)
    assert ctx.econ[s.id].prod_au == 5
    st = make_state()
    s = _one_system(st, starport=0, status=K.INTERDICTED, trade_routes={2})
    ctx = ctx_for(st)
    economy.produce(ctx)
    assert ctx.econ[s.id].prod_au == 0 and not s.trade_routes


def test_leader_management_50_is_neutral():
    # rules:658-660: 50 = neutral
    st = make_state()
    s = _one_system(st, starport=0)
    add_leader(st, 1, system=s.id, mgmt=50, social=50)
    ctx = ctx_for(st)
    economy.produce(ctx)
    assert ctx.econ[s.id].prod_au == 10
    st = make_state()
    s = _one_system(st, starport=0)
    add_leader(st, 1, system=s.id, mgmt=90)
    ctx = ctx_for(st)
    economy.produce(ctx)
    assert ctx.econ[s.id].prod_au == 14            # x1.4 (C ratio 0.7/0.5)


def test_happiness_formula_matches_c():
    # gcrun.c:516-560 (ENGINE_MAP 20.5) with D-04 (real division for the starport)
    st = make_state()
    s = _one_system(st, au=100, au_value=33, happy=0.5, hab=3, starport=2,
                    artifacts={"EHC", "PD"})
    ctx = ctx_for(st, ScriptedRng(chance=False))
    economy.happiness(ctx)
    eat = 33
    a = math.sqrt(eat / 5.0) / math.sqrt(2.25 * 4 * 1.2)
    b = (3 + (0.5 * 4 - 2) + 1.0 + 0.5) / 8
    target = a + b - 0.2
    assert s.au == 100 - eat
    assert s.happy == pytest.approx(0.5 + (target - 0.5) / 2)
    assert s.trend == 1


def test_capn_feeds_fixed_amount():
    st = make_state()
    s = _one_system(st, au=7, au_mode="num", au_value=10)
    ctx = ctx_for(st, ScriptedRng(chance=False))
    economy.happiness(ctx)
    assert ctx.econ[s.id].eaten == 7 and s.au == 0


def test_rebellion_at_zero_happiness():
    # rules:692-693: system and its CTs become NPR (the independents)
    st = make_state()
    s = _one_system(st, happy=-0.5, au=0)
    t = add_troop(st, 1, "S", system=s.id)
    ctx = ctx_for(st, ScriptedRng(chance=False))
    economy.happiness(ctx)
    assert s.owner == 0 and t.owner == 0
    assert ctx.res.events_of(1, "rebellion")


def test_npr_systems_rebel_like_players():
    # DECISIONS A-01: the C exempted NPRs (gcrun.c:567); computer empires now follow human rules
    st = make_state()
    s = sysn(st, "H3")                      # empire 3 is an NPR
    s.happy, s.au = -0.5, 0
    ctx = ctx_for(st, ScriptedRng(chance=True))
    economy.happiness(ctx)
    assert s.owner == 0


def test_no_rebellion_while_under_attack():
    # rules:696-699
    st = make_state()
    s = _one_system(st, happy=-0.5, au=0, status=K.UNDER_ATTACK)
    ctx = ctx_for(st, ScriptedRng(chance=True))
    economy.happiness(ctx)
    assert s.owner == 1


def test_uprising_odds_follow_rules():
    # rules:677-685: UNHAPPY 50%, NOT HAPPY 10%; militia 1 in 10
    st = make_state()
    s = _one_system(st, happy=0.1, au=0)
    rng = ScriptedRng(script=[True, True])      # uprising, militia
    ctx = ctx_for(st, rng)
    economy.happiness(ctx)
    assert rng.calls[:2] == [K.UPRISING_CHANCE_UH, K.UPRISING_MILITIA]
    assert any(t.owner == 0 and t.type == "M" for t in st.troops_at(s.id))
    st = make_state()
    s = _one_system(st, happy=0.4, au=0)
    rng = ScriptedRng(chance=False)
    ctx = ctx_for(st, rng)
    economy.happiness(ctx)
    assert 0.2 <= s.happy < 0.4 and rng.calls[0] == K.UPRISING_CHANCE_NH


def test_emperor_day_odds():
    # rules:687-690: VH 10%, EH 50%
    st = make_state()
    s = _one_system(st, happy=1.6, au=200)
    rng = ScriptedRng(script=[True, True])      # day, free starport
    ctx = ctx_for(st, rng)
    sp = s.starport
    economy.happiness(ctx)
    assert rng.calls[0] == K.EMPEROR_DAY_EH and s.starport == sp + 1


def test_growth_formula_and_cap():
    # gcrun.c:711-738
    st = make_state()
    s = _one_system(st, happy=1.0, hab=3)
    ctx = ctx_for(st)
    economy.grow(ctx)
    assert s.pop == pytest.approx(4 + min(1.0, 1.0 * 1.0 * 3 / 4))
    s.pop, s.happy = 9.9, 1.25
    economy.grow(ctx)
    assert s.pop == 10.0                      # rules:432 cap without EUS
    s.artifacts.add("EUS")
    economy.grow(ctx)
    assert s.pop > 10.0


def test_unhappy_systems_dont_grow():
    st = make_state()
    s = _one_system(st, happy=0.4)
    ctx = ctx_for(st)
    economy.grow(ctx)
    assert s.pop == 4.0


def test_dct_trade_25_percent_and_cap():
    # rules:319-327
    st = make_state()
    s = _one_system(st)
    s.trade_routes = {2}
    ctx = ctx_for(st)
    economy.trade(ctx, s, 100)
    assert ctx.trade_eu[2] == 25 and ctx.trade_eu[1] == 0
    ctx = ctx_for(st)
    s.trade_routes = {2, 3, 4}
    st.empires[4] = st.empires[3].__class__(4, "R4")
    economy.trade(ctx, s, 100)
    assert sum(ctx.trade_eu.values()) <= 50          # 3 x 25 prorated to 50
    assert ctx.trade_eu[2] == ctx.trade_eu[3]


def test_dct_deny_and_split():
    st = make_state()
    s = _one_system(st)
    s.trade_routes = {2}
    st.empires[1].deny_trade[2] = 50
    st.empires[2].split_trade[1] = 40
    ctx = ctx_for(st)
    economy.trade(ctx, s, 100)
    assert ctx.trade_eu[2] == 8 and ctx.trade_eu[1] == 5   # 12.5 split 60/40
