from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

OVH_PRICE_SCALE = Decimal("100000000")


def dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def normalize_ovh_amount(value: Any) -> Decimal | None:
    """Normalize OVH fixed-point prices to major currency units.

    OVH's order catalogue and checkout APIs commonly encode money as an
    integer scaled by 1e8 (for example, 350000000 == 3.50). Tests and some
    SDK shapes may already pass major-unit decimals, so only scale large
    integer-like values.
    """
    amount = dec(value)
    if amount is None:
        return None
    if amount == amount.to_integral_value() and abs(amount) >= Decimal("1000000"):
        return amount / OVH_PRICE_SCALE
    return amount


def money_from_obj(value: Any) -> tuple[Decimal | None, str | None]:
    """Parse common OVH money shapes: {value, currencyCode} or scalar."""
    if isinstance(value, dict):
        amount = normalize_ovh_amount(value.get("value"))
        currency = value.get("currencyCode") or value.get("currency")
        return amount, currency
    return normalize_ovh_amount(value), None
