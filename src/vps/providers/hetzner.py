from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

import requests

from ..models import CreateServerRequest, Offer, Server
from ..provider import ConfigurationError, Provider, ProviderError
from ..utils import dec


class HetznerProvider(Provider):
    name = "hetzner"
    base_url = "https://api.hetzner.cloud/v1"

    def __init__(self, token: str | None = None, session: requests.Session | None = None) -> None:
        self.token = token or os.getenv("HETZNER_TOKEN")
        if not self.token:
            raise ConfigurationError("Set HETZNER_TOKEN.")
        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.session.request(method, f"{self.base_url}{path}", timeout=30, **kwargs)
        if not response.ok:
            raise ProviderError(f"Hetzner API {response.status_code}: {response.text[:1000]}")
        return response.json() if response.content else {}

    def _available_server_type_ids_by_location(self) -> dict[str, set[str]]:
        """Return server type IDs currently orderable in each Hetzner location."""
        data = self._request("GET", "/datacenters")
        result: dict[str, set[str]] = {}
        for datacenter in data.get("datacenters", []):
            location_obj = datacenter.get("location")
            location = location_obj.get("name") if isinstance(location_obj, dict) else location_obj
            if not location:
                continue

            server_types = datacenter.get("server_types") or {}
            available_ids: set[str] = set()
            for item in server_types.get("available") or []:
                value = item.get("id") if isinstance(item, dict) else item
                if value is not None:
                    available_ids.add(str(value))
            result.setdefault(str(location), set()).update(available_ids)
        return result

    def list_offers(self, *, orderable_only: bool = False) -> list[Offer]:
        data = self._request("GET", "/server_types")
        # /pricing is authoritative for the account currency and is also a
        # useful fallback if server-type price objects change shape.
        try:
            pricing_root = self._request("GET", "/pricing").get("pricing") or {}
        except ProviderError:
            pricing_root = {}
        currency = pricing_root.get("currency")
        pricing_by_name = {
            str(item.get("name") or item.get("id")): item.get("prices") or []
            for item in pricing_root.get("server_types", [])
        }
        available_by_location = self._available_server_type_ids_by_location() if orderable_only else None

        result: list[Offer] = []
        for st in data.get("server_types", []):
            key = str(st.get("name") or st.get("id"))
            prices = st.get("prices") or pricing_by_name.get(key) or []
            if not prices:
                if not orderable_only:
                    result.append(self._offer(st, None, currency))
                continue
            for price in prices:
                available = None
                if available_by_location is not None:
                    location = price.get("location")
                    server_type_id = st.get("id")
                    available = (
                        location is not None
                        and server_type_id is not None
                        and str(server_type_id) in available_by_location.get(str(location), set())
                    )
                offer = self._offer(st, price, currency, available=available)
                if not orderable_only or offer.available:
                    result.append(offer)
        return result

    def _offer(
        self,
        st: dict[str, Any],
        price: dict[str, Any] | None,
        account_currency: str | None = None,
        available: bool | None = None,
    ) -> Offer:
        price = price or {}
        monthly_obj = price.get("price_monthly") or {}
        hourly_obj = price.get("price_hourly") or {}
        monthly = dec(monthly_obj.get("gross") if isinstance(monthly_obj, dict) else monthly_obj)
        hourly = dec(hourly_obj.get("gross") if isinstance(hourly_obj, dict) else hourly_obj)
        currency = account_currency or price.get("currency")
        if currency is None and isinstance(monthly_obj, dict):
            currency = monthly_obj.get("currency")
        return Offer(
            provider=self.name,
            id=str(st.get("name") or st.get("id")),
            name=str(st.get("description") or st.get("name") or st.get("id")),
            location=price.get("location"),
            vcpu=st.get("cores"),
            ram_gb=dec(st.get("memory")),
            disk_gb=dec(st.get("disk")),
            architecture=st.get("architecture"),
            monthly_price=monthly,
            hourly_price=hourly,
            currency=currency,
            price_source="server-types-api",
            available=available if available is not None else (True if price else None),
            metadata={
                "server_type_id": st.get("id"),
                "cpu_type": st.get("cpu_type"),
                "storage_type": st.get("storage_type"),
            },
        )

    def list_servers(self) -> list[Server]:
        data = self._request("GET", "/servers", params={"per_page": 50})
        servers: list[Server] = []
        for item in data.get("servers", []):
            public_net = item.get("public_net") or {}
            ipv4 = (public_net.get("ipv4") or {}).get("ip")
            ipv6 = (public_net.get("ipv6") or {}).get("ip")
            location = None
            if isinstance(item.get("location"), dict):
                location = item["location"].get("name")
            elif isinstance(item.get("datacenter"), dict):  # compatibility with older API payloads
                location = (item["datacenter"].get("location") or {}).get("name")
            st = item.get("server_type") or {}
            servers.append(Server(
                provider=self.name,
                id=str(item.get("id")),
                name=str(item.get("name")),
                status=str(item.get("status")),
                location=location,
                offer_id=st.get("name") or (str(st.get("id")) if st.get("id") is not None else None),
                ipv4=ipv4,
                ipv6=ipv6,
                metadata={"labels": item.get("labels") or {}},
            ))
        return servers

    def create_server(self, request: CreateServerRequest) -> Server:
        body: dict[str, Any] = {
            "name": request.name,
            "server_type": request.offer_id,
            "image": request.image or "ubuntu-24.04",
        }
        if request.location:
            body["location"] = request.location
        if request.ssh_keys:
            body["ssh_keys"] = request.ssh_keys
        if request.user_data:
            body["user_data"] = request.user_data
        if "labels" in request.metadata:
            body["labels"] = request.metadata["labels"]
        if "public_net" in request.metadata:
            body["public_net"] = request.metadata["public_net"]

        data = self._request("POST", "/servers", json=body)
        item = data.get("server") or {}
        public_net = item.get("public_net") or {}
        location = None
        if isinstance(item.get("location"), dict):
            location = item["location"].get("name")
        elif isinstance(item.get("datacenter"), dict):
            location = (item["datacenter"].get("location") or {}).get("name")
        return Server(
            provider=self.name,
            id=str(item.get("id")),
            name=str(item.get("name") or request.name),
            status=str(item.get("status") or "creating"),
            location=location or request.location,
            offer_id=request.offer_id,
            ipv4=(public_net.get("ipv4") or {}).get("ip"),
            ipv6=(public_net.get("ipv6") or {}).get("ip"),
            metadata={"root_password_returned": bool(data.get("root_password")), "action": data.get("action")},
        )
