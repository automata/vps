from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import requests

from ..models import CreateServerRequest, Offer, Server
from ..provider import ConfigurationError, Provider, ProviderError
from ..utils import dec


# Product IDs currently documented by Contabo's Create Instance endpoint.
# Prices are deliberately NOT hard-coded: Contabo does not expose a general
# new-order price catalogue through this API surface.
DOCUMENTED_PRODUCTS: dict[str, tuple[str, int]] = {
    "V153": ("Cloud VPS 4", 100), "V154": ("Cloud VPS 6", 200),
    "V155": ("Cloud VPS 8", 300), "V156": ("Cloud VPS 12", 400),
    "V157": ("Cloud VPS 16", 500), "V158": ("Cloud VPS 18", 600),
    "V159": ("Cloud VPS Plus 4", 150), "V160": ("Cloud VPS Plus 6", 300),
    "V161": ("Cloud VPS Plus 8", 450), "V162": ("Cloud VPS Plus 12", 600),
    "V163": ("Cloud VPS Plus 16", 750), "V164": ("Cloud VPS Plus 18", 900),
    "V93": ("VPS 10 Storage", 300), "V96": ("VPS 20 Storage", 400),
    "V99": ("VPS 30 Storage", 1000), "V102": ("VPS 40 Storage", 1200),
    "V105": ("VPS 50 Storage", 1400),
    "V8": ("VDS S", 180), "V9": ("VDS M", 240), "V10": ("VDS L", 360),
    "V11": ("VDS XL", 480), "V16": ("VDS XXL", 720),
}
REGIONS = ["EU", "US-central", "US-east", "US-west", "SIN", "UK", "AUS", "JPN", "IND"]


class ContaboProvider(Provider):
    name = "contabo"
    base_url = "https://api.contabo.com/v1"
    token_url = "https://auth.contabo.com/auth/realms/contabo/protocol/openid-connect/token"

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        api_user: str | None = None,
        api_password: str | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.client_id = client_id or os.getenv("CONTABO_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("CONTABO_CLIENT_SECRET")
        self.api_user = api_user or os.getenv("CONTABO_API_USER")
        self.api_password = api_password or os.getenv("CONTABO_API_PASSWORD")
        if not all((self.client_id, self.client_secret, self.api_user, self.api_password)):
            raise ConfigurationError(
                "Set CONTABO_CLIENT_ID, CONTABO_CLIENT_SECRET, CONTABO_API_USER, and CONTABO_API_PASSWORD."
            )
        self.session = session or requests.Session()
        self._token: str | None = None
        self._token_expires_at = 0.0

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token
        response = self.session.post(
            self.token_url,
            data={
                "grant_type": "password",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "username": self.api_user,
                "password": self.api_password,
            },
            timeout=30,
        )
        if not response.ok:
            raise ProviderError(f"Contabo authentication {response.status_code}: {response.text[:1000]}")
        data = response.json()
        self._token = data["access_token"]
        self._token_expires_at = time.time() + int(data.get("expires_in", 300))
        return self._token

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = kwargs.pop("headers", {})
        headers.update({
            "Authorization": f"Bearer {self._access_token()}",
            "Content-Type": "application/json",
            "x-request-id": str(uuid.uuid4()),
        })
        response = self.session.request(method, f"{self.base_url}{path}", headers=headers, timeout=30, **kwargs)
        if not response.ok:
            raise ProviderError(f"Contabo API {response.status_code}: {response.text[:1000]}")
        return response.json() if response.content else {}

    def _file_catalog(self) -> list[Offer] | None:
        path = os.getenv("CONTABO_PRICE_CATALOG_JSON")
        if not path:
            return None
        payload = json.loads(Path(path).read_text())
        offers: list[Offer] = []
        for item in payload:
            offers.append(Offer(
                provider=self.name,
                id=str(item["id"]),
                name=str(item.get("name", item["id"])),
                location=item.get("location"),
                vcpu=item.get("vcpu"),
                ram_gb=dec(item.get("ram_gb")),
                disk_gb=dec(item.get("disk_gb")),
                monthly_price=dec(item.get("monthly_price")),
                currency=item.get("currency"),
                price_source="user-catalog-json",
                available=item.get("available"),
                metadata={"warning": "Price supplied by CONTABO_PRICE_CATALOG_JSON, not verified by Contabo API."},
            ))
        return offers

    def list_offers(self, *, orderable_only: bool = False) -> list[Offer]:
        file_catalog = self._file_catalog()
        if file_catalog is not None:
            return file_catalog

        reference = os.getenv("CONTABO_PRICE_REFERENCE_INSTANCE_ID")
        if reference:
            data = self._request("GET", f"/compute/instances/{reference}/products/available")
            offers = []
            for item in data.get("data", []):
                offers.append(Offer(
                    provider=self.name,
                    id=str(item.get("productId")),
                    name=str(item.get("name") or item.get("productId")),
                    location=None,
                    vcpu=item.get("cpuCores"),
                    ram_gb=dec(item.get("ramSizeGb")),
                    disk_gb=dec(item.get("diskSizeGb")),
                    monthly_price=dec(item.get("vsPrice")),
                    currency=None,
                    price_source="upgrade-reference-api",
                    available=True,
                    metadata={
                        "reference_instance_id": reference,
                        "offer_id": item.get("offerId"),
                        "original_price": item.get("vsOriginalPrice"),
                        "warning": "Upgrade price/options for a reference instance; not guaranteed to equal a new-order catalogue.",
                    },
                ))
            return offers

        offers: list[Offer] = []
        for product_id, (name, disk) in DOCUMENTED_PRODUCTS.items():
            offers.append(Offer(
                provider=self.name,
                id=product_id,
                name=name,
                disk_gb=dec(disk),
                monthly_price=None,
                currency=None,
                price_source="price-unavailable-in-new-order-api",
                available=None,
                metadata={"regions": REGIONS, "warning": "Contabo Compute API documents the product as orderable but not a general live new-order price."},
            ))
        return offers

    def list_servers(self) -> list[Server]:
        data = self._request("GET", "/compute/instances", params={"size": 100})
        result = []
        for item in data.get("data", []):
            ip = item.get("ipConfig") or {}
            result.append(Server(
                provider=self.name,
                id=str(item.get("instanceId")),
                name=str(item.get("displayName") or item.get("name") or item.get("instanceId")),
                status=str(item.get("status")),
                location=item.get("region") or item.get("dataCenter"),
                offer_id=item.get("productId"),
                ipv4=(ip.get("v4") or {}).get("ip"),
                ipv6=(ip.get("v6") or {}).get("ip"),
                metadata={"product_name": item.get("productName"), "os_type": item.get("osType")},
            ))
        return result

    def create_server(self, request: CreateServerRequest) -> Server:
        ssh_keys: list[int] = []
        for key in request.ssh_keys:
            try:
                ssh_keys.append(int(key))
            except ValueError as exc:
                raise ConfigurationError("Contabo --ssh-key values must be numeric secret IDs.") from exc

        body: dict[str, Any] = {
            "productId": request.offer_id,
            "region": request.location or "EU",
            "imageId": request.image or "afecbb85-e2fc-46f0-9684-b46b1faf00bb",
            "period": int(request.metadata.get("period", 1)),
            "displayName": request.name,
            "defaultUser": request.metadata.get("default_user", "admin"),
        }
        if ssh_keys:
            body["sshKeys"] = ssh_keys
        if request.user_data:
            body["userData"] = request.user_data
        if request.metadata.get("root_password_secret_id") is not None:
            body["rootPassword"] = int(request.metadata["root_password_secret_id"])
        if request.metadata.get("add_ons") is not None:
            body["addOns"] = request.metadata["add_ons"]

        data = self._request("POST", "/compute/instances", json=body)
        item = (data.get("data") or [{}])[0]
        return Server(
            provider=self.name,
            id=str(item.get("instanceId")),
            name=request.name,
            status=str(item.get("status") or "provisioning"),
            location=item.get("region") or request.location or "EU",
            offer_id=item.get("productId") or request.offer_id,
            metadata={"created_date": item.get("createdDate")},
        )
