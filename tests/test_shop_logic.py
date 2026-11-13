from types import SimpleNamespace as NS

import pytest

from engine import shop_logic as sl


def test_money():
    assert sl.fmt_money(1500000) == "1 500 000 so‘m"


def test_parse_int():
    assert sl.parse_int("1 500,000") == 1500000
    with pytest.raises(ValueError):
        sl.parse_int("abc")
    with pytest.raises(ValueError):
        sl.parse_int("-5")
    with pytest.raises(ValueError):
        sl.parse_int("0", minimum=1)


def test_parse_variants():
    ok, err = sl.parse_variants("S\nM | 120 000\nL | - | 4\nXL | 130000 | 0\n\n")
    assert ok == [("S", None, None), ("M", 120000, None), ("L", None, 4), ("XL", 130000, 0)] and not err
    ok, err = sl.parse_variants("A | x\n | 5\nB | 1 | 2 | 3\nC")
    assert [v[0] for v in ok] == ["C"] and len(err) == 3 and err[0].startswith("1-qator")


def test_variant_limit():
    ok, err = sl.parse_variants("\n".join(f"v{i}" for i in range(40)))
    assert len(ok) == sl.MAX_VARIANTS and err


def test_prices_and_discount():
    p = NS(price=100, old_price=150, stock=None)
    assert sl.unit_price(p) == 100
    assert sl.unit_price(p, NS(price=120, stock=1)) == 120
    assert sl.unit_price(p, NS(price=None, stock=1)) == 100
    assert sl.discount_percent(p) == 33
    assert sl.discount_percent(NS(price=100, old_price=None)) == 0
    assert sl.discount_percent(NS(price=100, old_price=90)) == 0


def test_availability_and_labels():
    p = NS(price=1, stock=3)
    assert sl.available(p) == 3 and sl.available(p, NS(stock=None)) is None
    assert sl.stock_label(0) == "❌ Tugagan" and sl.stock_label(None) == "✅ Mavjud" and "3 ta" in sl.stock_label(3)


def test_delivery_cost():
    kw = dict(fee=15000, free_from=200000)
    assert sl.delivery_cost("pickup", 1000, **kw) == 0
    assert sl.delivery_cost("delivery", 1000, **kw) == 15000
    assert sl.delivery_cost("delivery", 200000, **kw) == 0
    assert sl.delivery_cost("delivery", 1000, fee=0, free_from=None) == 0
    assert sl.delivery_cost("delivery", 1000, fee=5, free_from=None) == 5
