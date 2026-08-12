from vpsbroker.models import CreateServerRequest
from vpsbroker.providers.ovhcloud import OVHCloudProvider


class FakeOVH:
    def __init__(self):
        self.configs = []

    def get(self, path, **kwargs):
        if path == "/order/catalog/public/vps":
            return {"plans": [{
                "planCode": "vps-demo",
                "invoiceName": "Demo VPS 2 vCore 4 GB RAM 80 GB NVMe",
                "pricings": [{
                    "capacities": ["renew"], "mode": "default", "interval": 1,
                    "intervalUnit": "month", "duration": "P1M",
                    "price": {"value": 9.99, "currencyCode": "GBP"},
                }],
            }]}
        if path.endswith("/requiredConfiguration"):
            return [{"label": "vps_datacenter", "type": "String", "required": True}]
        if path.endswith("/checkout"):
            return {"prices": {"withTax": {"value": 11.99, "currencyCode": "GBP"}}, "contracts": []}
        raise AssertionError((path, kwargs))

    def post(self, path, **kwargs):
        if path == "/order/cart":
            return {"cartId": "cart-1"}
        if path == "/order/cart/cart-1/assign":
            return None
        if path == "/order/cart/cart-1/vps":
            return {"itemId": 42}
        if path == "/order/cart/cart-1/item/42/configuration":
            self.configs.append(kwargs)
            return {"id": 1, **kwargs}
        if path == "/order/cart/cart-1/checkout":
            return {"orderId": 123, "url": "https://example.invalid/order/123"}
        raise AssertionError((path, kwargs))


def test_ovh_catalog_and_quote():
    client = FakeOVH()
    p = OVHCloudProvider(client=client, subsidiary="GB")
    offer = p.list_offers()[0]
    assert offer.id == "vps-demo"
    assert str(offer.monthly_price) == "9.99"
    assert offer.currency == "GBP"
    assert offer.vcpu == 2
    assert str(offer.ram_gb) == "4"

    quote = p.quote(CreateServerRequest(name="x", offer_id="vps-demo", location="GRA"))
    assert str(quote.due_now) == "11.99"
    assert client.configs == [{"label": "vps_datacenter", "value": "GRA"}]
