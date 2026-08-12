from vpsbroker.providers.contabo import ContaboProvider


def test_contabo_default_catalog_does_not_fake_prices(monkeypatch):
    monkeypatch.delenv("CONTABO_PRICE_REFERENCE_INSTANCE_ID", raising=False)
    monkeypatch.delenv("CONTABO_PRICE_CATALOG_JSON", raising=False)
    p = ContaboProvider(client_id="a", client_secret="b", api_user="c", api_password="d")
    offers = p.list_offers()
    assert any(o.id == "V153" for o in offers)
    assert all(o.monthly_price is None for o in offers)
    assert all(o.price_source == "price-unavailable-in-new-order-api" for o in offers)
