from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

HOURS_PER_MONTH = Decimal("730")
DERIVED_HOURLY_QUANT = Decimal("0.0001")


@dataclass(slots=True)
class Offer:
    provider: str
    id: str
    name: str
    location: str | None = None
    vcpu: int | None = None
    ram_gb: Decimal | None = None
    disk_gb: Decimal | None = None
    architecture: str | None = None
    monthly_price: Decimal | None = None
    hourly_price: Decimal | None = None
    currency: str | None = None
    price_source: str = "provider-api"
    available: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.hourly_price is None and self.monthly_price is not None:
            self.hourly_price = (self.monthly_price / HOURS_PER_MONTH).quantize(
                DERIVED_HOURLY_QUANT,
                rounding=ROUND_HALF_UP,
            )
            self.metadata.setdefault(
                "hourly_price_derived_from_monthly",
                {
                    "monthly_price": str(self.monthly_price),
                    "hours_per_month": str(HOURS_PER_MONTH),
                },
            )

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("ram_gb", "disk_gb", "monthly_price", "hourly_price"):
            value = data[key]
            data[key] = None if value is None else str(value)
        return data


@dataclass(slots=True)
class Server:
    provider: str
    id: str
    name: str
    status: str
    location: str | None = None
    offer_id: str | None = None
    ipv4: str | None = None
    ipv6: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CreateServerRequest:
    name: str
    offer_id: str
    location: str | None = None
    image: str | None = None
    ssh_keys: list[str] = field(default_factory=list)
    user_data: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Quote:
    provider: str
    offer_id: str
    monthly_price: Decimal | None = None
    due_now: Decimal | None = None
    currency: str | None = None
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["monthly_price"] = None if self.monthly_price is None else str(self.monthly_price)
        data["due_now"] = None if self.due_now is None else str(self.due_now)
        return data
