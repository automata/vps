from vps.models import CreateServerRequest
from vps.providers.ovhcloud import OVHCloudProvider


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
            return {"prices": {"withTax": {"value": 1199000000, "currencyCode": "GBP"}}, "contracts": []}
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


class FakeOVHTriplets:
    def get(self, path, **kwargs):
        if path == "/order/catalog/public/vps":
            pricing = {
                "capacities": ["renew"], "mode": "default", "interval": 1,
                "intervalUnit": "month", "duration": "P1M",
                "price": 1230000000,
                "tax": 246000000,
            }
            return {"locale": {"currencyCode": "GBP"}, "plans": [
                {
                    "planCode": "vps-comfort-4-16-160-vps-2025-model3",
                    "invoiceName": "VPS-3 2026",
                    "product": "vps-2020v2-model3",
                    "pricings": [pricing],
                    "configurations": [{"name": "vps_datacenter", "values": ["GRA", "SBG"]}],
                },
                {
                    "planCode": "vps-value-1-2-40-vps-2025-model1-degressivity24-10percent",
                    "invoiceName": "VPS-1 2026",
                    "product": "vps-2020v2-model1",
                    "pricings": [pricing],
                },
            ]}
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
    assert str(offer.disk_gb) == "80"
    assert str(offer.hourly_price) == "0.0137"

    quote = p.quote(CreateServerRequest(name="x", offer_id="vps-demo", location="GRA"))
    assert str(quote.due_now) == "11.99"
    assert client.configs == [{"label": "vps_datacenter", "value": "GRA"}]


def test_ovh_parses_specs_from_plan_codes_and_names():
    p = OVHCloudProvider(client=FakeOVHTriplets(), subsidiary="GB")
    offers = p.list_offers()

    comfort = [o for o in offers if o.id == "vps-comfort-4-16-160-vps-2025-model3"]
    assert [(o.location, o.vcpu, str(o.ram_gb), str(o.disk_gb), str(o.monthly_price), str(o.hourly_price), o.currency) for o in comfort] == [
        ("GRA", 4, "16", "160", "14.76", "0.0202", "GBP"),
        ("SBG", 4, "16", "160", "14.76", "0.0202", "GBP"),
    ]

    value = next(o for o in offers if o.id == "vps-value-1-2-40-vps-2025-model1-degressivity24-10percent")
    assert value.location is None
    assert value.vcpu == 1
    assert str(value.ram_gb) == "2"
    assert str(value.disk_gb) == "40"
