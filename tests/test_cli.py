from decimal import Decimal

from vps.cli import _money


def test_money_display_uses_two_decimal_digits():
    assert _money(Decimal("4.2"), "EUR") == "4.20 EUR"
    assert _money(Decimal("0.0137"), "USD") == "0.01 USD"
    assert _money(None, "USD") == "?"
