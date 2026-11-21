"""Ship rebalance (Dave 2026-11-19, DECISIONS G-25): the standard line D/C/B/HB/DN a bit stronger,
the DeathStar much stronger; the fast line, upkeep, costs and every other stat unchanged."""
from __future__ import annotations

from mhgc import model as M
from mhgc.data.ships import SHIP_TYPES
from mhgc.mapgen import new_game
from mhgc.npr import war
from tests.conftest import make_state
from tests.test_npr_units import NPR_ID, _w

NEW = {"D": (3, 5), "C": (7, 12), "B": (12, 16), "HB": (16, 18), "DN": (24, 24), "DS": (45, 12)}

# everything else as the rules' generated table (rules:3170-3231): attack, defence, scan, move,
# cargo, IU, EU, tech
REST = {
    "D": (3, 4, 0, 40, 40, 15), "C": (4, 4, 0, 60, 60, 29), "B": (4, 5, 0, 80, 80, 39),
    "HB": (4, 5, 0, 90, 90, 45), "DN": (4, 5, 0, 100, 100, 49), "DS": (2, 3, 0, 100, 100, 47),
}
UNCHANGED = {   # attack / defence of the ships Dave left alone
    "S": (0, 1), "T": (0, 1), "F": (1, 2), "MS": (0, 8), "MT": (0, 8), "SS": (0, 1),
    "AT": (4, 6), "FF": (1, 2), "LC": (3, 5), "MCS": (4, 6), "FC": (7, 8), "FB": (9, 12),
    "PA": (2, 5), "DE": (4, 8), "GU": (7, 12), "WS": (11, 17), "MO": (16, 20), "BB": (22, 30),
    "ST": (5, 1), "PO": (8, 2), "MA": (12, 5), "E": (18, 6),
}


def _value(code: str) -> float:
    st = SHIP_TYPES[code]
    return 100 * (st.attack + st.defense) / (st.iu_cost + st.eu_cost)


def test_new_attack_and_defence():
    for code, ad in NEW.items():
        st = SHIP_TYPES[code]
        assert (st.attack, st.defense) == ad, code
        assert (st.scan, st.move, st.cargo, st.iu_cost, st.eu_cost, st.tech) == REST[code], code


def test_other_ships_unchanged():
    assert set(NEW) | set(UNCHANGED) == set(SHIP_TYPES)
    for code, ad in UNCHANGED.items():
        assert (SHIP_TYPES[code].attack, SHIP_TYPES[code].defense) == ad, code


def test_standard_line_still_below_the_defensive_line_per_cost():
    # Dave's measure, (attack + defence) per 100 IU+EU: the trade for movement 4-5 against 2-3
    assert round(_value("C"), 1) == 15.8 and _value("B") == 17.5 and _value("DN") == 24.0
    assert _value("C") < _value("WS")                 # both tech 1000
    assert _value("B") < _value("MO") and _value("HB") < _value("MO")
    assert _value("DN") < _value("MO") < _value("BB")
    # the DeathStar: best value per cost, and half again the Eliminator's attack per cost
    ds = SHIP_TYPES["DS"]
    assert round(_value("DS"), 1) == 28.5 and _value("DS") > max(_value(c) for c in UNCHANGED)
    assert ds.attack / (ds.iu_cost + ds.eu_cost) == 1.5 * 18 / 120


def test_old_save_ships_get_the_new_stats():
    """A save stores only a ship's type, so loaded ships take the current table at once."""
    g = new_game("old", 3, ["Dave"])
    e = g.empires[1]
    for n, t in ((90001, "C"), (90002, "DS")):
        g.ships[n] = M.Ship(number=n, owner=1, type=t, x=e.home_x, y=e.home_y)
    text = M.dumps(g)
    assert '"attack"' not in text and '"defense"' not in text
    st = M.loads(text)
    assert (st.ships[90001].stype.attack, st.ships[90001].stype.defense) == (7, 12)
    assert (st.ships[90002].stype.attack, st.ships[90002].stype.defense) == (45, 12)


def test_bot_builds_a_deathstar_when_the_offensive_and_fast_lines_are_missing():
    # war.SHORT_ORDER: with standard and defensive attack here and neither fast nor offensive,
    # the offensive line takes the short-line bonus (before, the fast line did, and the bots
    # never built a DeathStar)
    st = make_state()
    st.empires[NPR_ID].techs |= set(range(50))
    w = _w(st)
    lines = {"STANDARD": 20, "DEFENSIVE": 20, "FAST": 0, "OFFENSIVE": 0}
    assert war.choose_ship(w, lines) == "DS"
    # with only defensive ships here the standard line comes first: a Dreadnought
    assert war.choose_ship(w, {"DEFENSIVE": 20}) == "DN"
