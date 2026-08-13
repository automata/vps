from decimal import Decimal

import pytest

from vps.fx import FxError, convert_offer_prices, fetch_exchange_rates
from vps.models import Offer


class Resp:
    ok = True
    status_code = 200
    text = ""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class FxSession:
    def __init__(self):
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append((url, params, timeout))
        rates = {"GBP": "1.25", "EUR": "1.10"}
        return Resp({"date": "2026-08-12", "rates": {params["to"]: rates[params["from"]]}})


def test_fetch_exchange_rates_and_convert_offers():
    session = FxSession()
    offers = [
        Offer(provider="ovhcloud", id="vps", name="VPS", monthly_price=Decimal("14.76"), currency="GBP"),
        Offer(
            provider="hetzner",
            id="cx23",
            name="CX23",
            monthly_price=Decimal("4.76"),
            hourly_price=Decimal("0.012"),
            currency="EUR",
        ),
        Offer(provider="contabo", id="V153", name="Cloud VPS 4"),
    ]

    rates = convert_offer_prices(offers, "usd", session=session)

    assert rates.target_currency == "USD"
    assert offers[0].currency == "USD"
    assert str(offers[0].monthly_price) == "18.45"
    assert offers[0].metadata["currency_conversion"]["original_currency"] == "GBP"
    assert offers[0].metadata["currency_conversion"]["original_monthly_price"] == "14.76"
    assert str(offers[1].monthly_price) == "5.24"
    assert str(offers[1].hourly_price) == "0.0132"
    assert offers[2].currency is None
    assert [call[1] for call in session.calls] == [
        {"from": "EUR", "to": "USD"},
        {"from": "GBP", "to": "USD"},
    ]


def test_currency_conversion_requires_source_currency():
    with pytest.raises(FxError, match="missing source currency"):
        convert_offer_prices(
            [Offer(provider="x", id="priced", name="priced", monthly_price=Decimal("1.00"))],
            "USD",
            session=FxSession(),
        )


def test_fetch_exchange_rates_skips_target_currency():
    session = FxSession()
    rates = fetch_exchange_rates(["USD"], "USD", session=session)
    assert rates.source_to_target == {"USD": Decimal("1")}
    assert session.calls == []
