from vps.providers.hetzner import HetznerProvider


class Resp:
    def __init__(self, payload):
        self._payload = payload
        self.ok = True
        self.status_code = 200
        self.text = ""
        self.content = b"x"

    def json(self):
        return self._payload


class Session:
    def __init__(self):
        self.headers = {}

    def request(self, method, url, **kwargs):
        if url.endswith("/server_types"):
            return Resp({"server_types": [{
                "id": 114, "name": "cx23", "description": "CX23", "cores": 2,
                "memory": 4.0, "disk": 40, "architecture": "x86",
                "prices": [{
                    "location": "nbg1",
                    "price_hourly": {"net": "0.01", "gross": "0.012"},
                    "price_monthly": {"net": "4.00", "gross": "4.76"},
                }],
            }]})
        if url.endswith("/pricing"):
            return Resp({"pricing": {"currency": "EUR", "server_types": []}})
        raise AssertionError(url)


class OrderableSession(Session):
    def request(self, method, url, **kwargs):
        if url.endswith("/server_types"):
            return Resp({"server_types": [
                {
                    "id": 114, "name": "cx23", "description": "CX23", "cores": 2,
                    "memory": 4.0, "disk": 40, "architecture": "x86",
                    "prices": [
                        {
                            "location": "nbg1",
                            "price_hourly": {"gross": "0.012"},
                            "price_monthly": {"gross": "4.76"},
                        },
                        {
                            "location": "fsn1",
                            "price_hourly": {"gross": "0.012"},
                            "price_monthly": {"gross": "4.76"},
                        },
                    ],
                },
                {
                    "id": 115, "name": "cx33", "description": "CX33", "cores": 4,
                    "memory": 8.0, "disk": 80, "architecture": "x86",
                    "prices": [{
                        "location": "nbg1",
                        "price_hourly": {"gross": "0.024"},
                        "price_monthly": {"gross": "9.52"},
                    }],
                },
            ]})
        if url.endswith("/datacenters"):
            return Resp({"datacenters": [
                {"location": {"name": "nbg1"}, "server_types": {"available": [114]}},
                {"location": {"name": "fsn1"}, "server_types": {"available": [115]}},
            ]})
        return super().request(method, url, **kwargs)


def test_hetzner_normalizes_per_location_price():
    p = HetznerProvider(token="token", session=Session())
    offers = p.list_offers()
    assert len(offers) == 1
    o = offers[0]
    assert o.id == "cx23"
    assert o.location == "nbg1"
    assert str(o.monthly_price) == "4.76"
    assert o.currency == "EUR"
    assert o.vcpu == 2


def test_hetzner_orderable_only_filters_using_datacenter_availability():
    p = HetznerProvider(token="token", session=OrderableSession())
    offers = p.list_offers(orderable_only=True)
    assert [(o.id, o.location) for o in offers] == [("cx23", "nbg1")]
    assert offers[0].available is True
