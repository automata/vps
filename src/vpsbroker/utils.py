from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def money_from_obj(value: Any) -> tuple[Decimal | None, str | None]:
    """Parse common OVH money shapes: {value, currencyCode} or scalar."""
    if isinstance(value, dict):
        amount = dec(value.get("value"))
        currency = value.get("currencyCode") or value.get("currency")
        return amount, currency
    return dec(value), None
