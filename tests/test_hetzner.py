from vpsbroker.providers.hetzner import HetznerProvider


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
