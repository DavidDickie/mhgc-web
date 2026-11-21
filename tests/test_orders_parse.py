"""Order model and classic text parser (rules:1636-1755)."""
import pytest

from mhgc.orders import (OrderSyntaxError, catalogue, make_order, order_from_dict,
                         parse_line, parse_orders, parse_orders_text)


def test_basic_parse_and_roundtrip():
    o = parse_line("MO 32 10 10")
    assert (o.code, o.ship, o.x, o.y) == ("MO", 32, 10, 10)
    assert o.to_text() == "MO 32 10 10"
    assert order_from_dict(o.to_dict()) == o


@pytest.mark.parametrize("bad", ["U 32 6 P", "U 32 P = 6", "U 32 P,6", "U32 P6", "u 32 P 6",
                                 "M0 32 10 10"])
def test_rules_wrong_examples(bad):
    # rules:1645-1657
    with pytest.raises(OrderSyntaxError):
        parse_line(bad)


def test_trailing_comments_ignored():
    o = parse_line("U 32 P 6 # unload pop")
    assert (o.ship, o.item, o.amount) == (32, "P", 6)
    assert parse_line("# U 32 A 1  this order won't be processed") is None


def test_hash_word_is_unknown_order():
    # rules:1688-1689: "#U 32 A 1  This order should generate an error"
    with pytest.raises(OrderSyntaxError, match="Unknown order code #U"):
        parse_line("#U 32 A 1")


def test_bs_optional_posture_role_either_order():
    a = parse_line("BS Earth D H MR")
    b = parse_line("BS Earth D MR H")
    assert (a.posture, a.role) == (b.posture, b.role) == ("H", "MR")
    c = parse_line("BS Earth F oops")
    assert c.posture is None and c.warnings


def test_ranges():
    with pytest.raises(OrderSyntaxError):
        parse_line("CAPN Hum 101")              # rules:1960 0-100
    with pytest.raises(OrderSyntaxError):
        parse_line("DD Bugs 20")                # rules:2473 minimum 25
    with pytest.raises(OrderSyntaxError):
        parse_line("CSP Hum 50 40 20")          # must add to 100
    with pytest.raises(OrderSyntaxError):
        parse_line("CSP Hum 85 5 10")           # each >= 10
    with pytest.raises(OrderSyntaxError):
        parse_line("MO 1 100 5")                # board is 0..99


@pytest.mark.parametrize("line", ["DI Hum -3", "BI Hum -1", "U 3 A -5", "UG 3 I -50",
                                  "CI Hum -1", "GE Bugs -10", "SISD Hum -2"])
def test_negative_amounts_rejected(line):
    with pytest.raises(OrderSyntaxError, match="negative"):
        parse_line(line)


def test_removed_and_ignored_codes():
    for line in ("MHGC_ORDERS game race pw", "END_ORDERS", "HOLD", "NMC", "SPW secret",
                 "EMAIL a@b"):
        assert parse_line(line) is None
    for code in ("BANG 10 50 50 x", "LDD Hum 5", "ISNPR", "ATTP 3 race pw"):
        with pytest.raises(OrderSyntaxError, match="isn't available"):
            parse_line(code)


def test_retired_display_options_give_a_clear_error():
    """Dave 2026-11-12: AUTOFLEET, NOAUTOFLEET, TRACKSCAN and NOTRACKSCAN are gone.  Typing one
    is a clear error, from the classic text, the JSON order form and a whole order block."""
    from mhgc.orders import ORDER_SPECS, order_from_dict
    for code in ("AUTOFLEET", "NOAUTOFLEET", "TRACKSCAN", "NOTRACKSCAN", "CGR"):
        assert code not in ORDER_SPECS
        with pytest.raises(OrderSyntaxError, match=f"{code} no longer exists"):
            parse_line(code)
        with pytest.raises(OrderSyntaxError, match=f"{code} no longer exists"):
            parse_line(f"{code} Humbug 50")
        with pytest.raises(OrderSyntaxError, match="no longer exists"):
            order_from_dict({"code": code})
        bad = [p for p in parse_orders_text(f"PT 2\n{code}\n") if p.error]
        assert len(bad) == 1 and bad[0].lineno == 2 and "removed" in bad[0].error


def test_message_block():
    res = parse_orders_text("MESSAGE Blutos Mangos\nMESSAGE Ratfinks\nRoses are Red,\n"
                            "Violets are Blue.\n.\nPT 2\n")
    msg = res[0].order
    assert msg.recipients == ["Blutos", "Mangos", "Ratfinks"]
    assert msg.text == "Roses are Red,\nViolets are Blue."
    assert res[1].order.code == "PT"
    bad = parse_orders_text("MESSAGE x\nno terminator\n")
    assert bad[0].error


def test_parse_orders_skips_bad_lines():
    out = parse_orders("PT 2\nU32 P6\nBT Hum EHC\n")
    assert [o.code for o in out] == ["PT", "BT"]


def test_variadic_ships_and_cfcr_ro():
    o = parse_line("AF Task 34 877 134")
    assert o.ships == [34, 877, 134]
    o = parse_line("CFCR Task RO 5 3 SC")
    assert (o.gc, o.rd, o.other) == (5, 3, "SC")
    with pytest.raises(OrderSyntaxError):
        parse_line("CFCR Task RO 5")
    assert parse_line("FS Task A").speed == "A" and parse_line("FS Task 4").speed == 4


def test_names_length():
    with pytest.raises(OrderSyntaxError):
        parse_line("NSY Hum ThirteenChars1")
    with pytest.raises(OrderSyntaxError):
        make_order("CRN", name="unknown")


def test_catalogue_covers_codes():
    codes = {c["code"] for c in catalogue()}
    for c in ("MO", "BS", "PT", "TTNPR", "GS", "DOCT", "SOM", "CRP", "MESSAGE"):
        assert c in codes
