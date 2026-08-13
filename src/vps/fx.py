from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable

import requests

from .models import Offer
from .utils import dec

FRANKFURTER_URL = "https://api.frankfurter.app/latest"
MONTHLY_QUANT = Decimal("0.01")
HOURLY_QUANT = Decimal("0.0001")


class FxError(RuntimeError):
    pass


def normalize_currency(value: str | None) -> str | None:
    if value is None:
        return None
    currency = value.strip().upper()
    return currency or None


@dataclass(frozen=True)
class ExchangeRates:
    target_currency: str
    source_to_target: dict[str, Decimal]
    dates: dict[str, str]
    provider: str = "frankfurter.app"

    def convert(self, amount: Decimal, source_currency: str) -> Decimal:
        source_currency = normalize_currency(source_currency) or ""
        target_currency = normalize_currency(self.target_currency) or ""
        if source_currency == target_currency:
            return amount
        try:
            rate = self.source_to_target[source_currency]
        except KeyError as exc:
            raise FxError(f"No FX rate for {source_currency} -> {target_currency}.") from exc
        return amount * rate

    def rate_date(self, source_currency: str) -> str | None:
        return self.dates.get(normalize_currency(source_currency) or "")


def _json_response(response: Any) -> dict[str, Any]:
    ok = getattr(response, "ok", True)
    if not ok:
        status = getattr(response, "status_code", "?")
        text = getattr(response, "text", "")
        raise FxError(f"FX API {status}: {str(text)[:500]}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise FxError("FX API returned a non-object response.")
    return payload


def fetch_exchange_rates(
    source_currencies: Iterable[str],
    target_currency: str,
    *,
    session: requests.Session | None = None,
) -> ExchangeRates:
    """Fetch source->target FX rates from Frankfurter.

    Frankfurter is a public ECB-backed exchange-rate API. It does not provide
    all possible currencies, so unsupported provider currencies fail loudly
    instead of silently mixing currencies in one table.
    """
    target = normalize_currency(target_currency)
    if target is None:
        raise FxError("Target currency cannot be empty.")

    sources = sorted({currency for value in source_currencies if (currency := normalize_currency(value))})
    client = session or requests.Session()
    rates: dict[str, Decimal] = {target: Decimal("1")}
    dates: dict[str, str] = {}

    for source in sources:
        if source == target:
            continue
        try:
            response = client.get(FRANKFURTER_URL, params={"from": source, "to": target}, timeout=15)
            payload = _json_response(response)
        except requests.RequestException as exc:
            raise FxError(f"Could not fetch FX rate {source} -> {target}: {exc}") from exc

        rate = dec((payload.get("rates") or {}).get(target))
        if rate is None:
            raise FxError(f"FX API did not return a rate for {source} -> {target}.")
        rates[source] = rate
        if payload.get("date"):
            dates[source] = str(payload["date"])

    return ExchangeRates(target_currency=target, source_to_target=rates, dates=dates)


def _quantize(value: Decimal, quantum: Decimal) -> Decimal:
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def convert_offer_prices(
    offers: list[Offer],
    target_currency: str,
    *,
    session: requests.Session | None = None,
) -> ExchangeRates:
    """Convert all priced offers in-place to target_currency.

    Original values are preserved in offer.metadata["currency_conversion"].
    Offers without any known price are left alone. Offers with a price but no
    source currency fail because they cannot be safely compared in one currency.
    """
    target = normalize_currency(target_currency)
    if target is None:
        raise FxError("Target currency cannot be empty.")

    sources: set[str] = set()
    for offer in offers:
        has_price = offer.monthly_price is not None or offer.hourly_price is not None
        if not has_price:
            continue
        source = normalize_currency(offer.currency)
        if source is None:
            raise FxError(f"Cannot convert priced offer {offer.provider}/{offer.id}: missing source currency.")
        sources.add(source)

    rates = fetch_exchange_rates(sources, target, session=session)

    for offer in offers:
        has_price = offer.monthly_price is not None or offer.hourly_price is not None
        if not has_price:
            continue
        source = normalize_currency(offer.currency)
        if source is None:
            continue

        if source == target:
            offer.currency = target
            continue

        original_monthly = offer.monthly_price
        original_hourly = offer.hourly_price
        if offer.monthly_price is not None:
            offer.monthly_price = _quantize(rates.convert(offer.monthly_price, source), MONTHLY_QUANT)
        if offer.hourly_price is not None:
            offer.hourly_price = _quantize(rates.convert(offer.hourly_price, source), HOURLY_QUANT)
        offer.currency = target
        offer.metadata["currency_conversion"] = {
            "provider": rates.provider,
            "source_currency": source,
            "target_currency": target,
            "source_to_target_rate": str(rates.source_to_target.get(source, Decimal("1"))),
            "rate_date": rates.rate_date(source),
            "original_monthly_price": None if original_monthly is None else str(original_monthly),
            "original_hourly_price": None if original_hourly is None else str(original_hourly),
            "original_currency": source,
        }

    return rates
