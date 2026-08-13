from decimal import Decimal

from vps.models import Offer
from vps.providers.contabo import ContaboProvider


def test_offer_derives_hourly_price_from_monthly_price():
    offer = Offer(provider="demo", id="monthly", name="Monthly", monthly_price=Decimal("73.00"), currency="EUR")

    assert str(offer.hourly_price) == "0.1000"
    assert offer.metadata["hourly_price_derived_from_monthly"] == {
        "monthly_price": "73.00",
        "hours_per_month": "730",
    }


def test_offer_keeps_provider_hourly_price():
    offer = Offer(
        provider="demo",
        id="hourly",
        name="Hourly",
        monthly_price=Decimal("73.00"),
        hourly_price=Decimal("0.1234"),
        currency="EUR",
    )

    assert str(offer.hourly_price) == "0.1234"
    assert "hourly_price_derived_from_monthly" not in offer.metadata


def test_contabo_default_catalog_does_not_fake_prices(monkeypatch):
    monkeypatch.delenv("CONTABO_PRICE_REFERENCE_INSTANCE_ID", raising=False)
    monkeypatch.delenv("CONTABO_PRICE_CATALOG_JSON", raising=False)
    p = ContaboProvider(client_id="a", client_secret="b", api_user="c", api_password="d")
    offers = p.list_offers()
    assert any(o.id == "V153" for o in offers)
    assert all(o.monthly_price is None for o in offers)
    assert all(o.price_source == "price-unavailable-in-new-order-api" for o in offers)
