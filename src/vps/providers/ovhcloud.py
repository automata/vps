from __future__ import annotations

import os
import re
from decimal import Decimal
from typing import Any

from ..models import CreateServerRequest, Offer, Quote, Server
from ..provider import ConfigurationError, Provider, ProviderError
from ..utils import dec, money_from_obj


class OVHCloudProvider(Provider):
    name = "ovhcloud"

    def __init__(
        self,
        endpoint: str | None = None,
        subsidiary: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.endpoint = endpoint or os.getenv("OVH_ENDPOINT", "ovh-eu")
        self.subsidiary = subsidiary or os.getenv("OVH_SUBSIDIARY", "GB")
        if client is not None:
            self.client = client
            return
        required = ["OVH_APPLICATION_KEY", "OVH_APPLICATION_SECRET", "OVH_CONSUMER_KEY"]
        missing = [key for key in required if not os.getenv(key)]
        if missing:
            raise ConfigurationError("Set " + ", ".join(missing) + ".")
        try:
            import ovh
        except ImportError as exc:
            raise ConfigurationError("Install the ovh package (pip install ovh).") from exc
        self.client = ovh.Client(endpoint=self.endpoint)

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            return getattr(self.client, method)(path, **kwargs)
        except Exception as exc:  # SDK raises provider-specific exception classes
            raise ProviderError(f"OVHcloud API error on {method.upper()} {path}: {exc}") from exc

    @staticmethod
    def _pricing(plan: dict[str, Any], catalog_currency: str | None = None) -> tuple[Decimal | None, str | None, str, str]:
        """Return monthly-ish price, currency, duration, pricing mode from catalogue plan."""
        pricings = plan.get("pricings") or []
        best: dict[str, Any] | None = None
        for pricing in pricings:
            capacities = set(pricing.get("capacities") or [])
            interval_unit = str(pricing.get("intervalUnit") or "").lower()
            mode = str(pricing.get("mode") or "default")
            if "renew" in capacities and interval_unit in {"month", "months"} and mode == "default":
                best = pricing
                break
        if best is None:
            for pricing in pricings:
                if str(pricing.get("mode") or "default") == "default":
                    best = pricing
                    break
        best = best or {}
        amount, currency = money_from_obj(best.get("price"))
        tax, _ = money_from_obj(best.get("tax"))
        if amount is not None and tax is not None:
            # Match Hetzner's normalized prices, which use gross amounts.
            amount += tax
        currency = currency or best.get("currencyCode") or catalog_currency
        interval = best.get("interval") or 1
        interval_unit = str(best.get("intervalUnit") or "month").lower()
        if amount is not None and interval_unit.startswith("month") and dec(interval):
            amount = amount / Decimal(str(interval))
        duration = str(best.get("duration") or plan.get("duration") or "P1M")
        pricing_mode = str(best.get("mode") or "default")
        return amount, currency, duration, pricing_mode

    @classmethod
    def _plan_text(cls, plan: dict[str, Any]) -> str:
        """Text fields that tend to carry OVH VPS sizing hints."""
        values: list[str] = []
        for key in ("invoiceName", "planCode", "product", "description", "name"):
            value = plan.get(key)
            if isinstance(value, dict):
                values.extend(str(v) for v in value.values() if v)
            elif value:
                values.append(str(value))
        commercial = ((plan.get("blobs") or {}).get("commercial") or {}) if isinstance(plan.get("blobs"), dict) else {}
        if isinstance(commercial, dict):
            values.extend(str(commercial.get(key)) for key in ("brick", "line", "range") if commercial.get(key))
        return " ".join(values)

    @staticmethod
    def _sized_decimal(value: str, unit: str = "gb") -> Decimal | None:
        amount = dec(value)
        if amount is None:
            return None
        return amount * Decimal("1024") if unit.lower().startswith("t") else amount

    @staticmethod
    def _first_decimal(patterns: list[str], text: str) -> Decimal | None:
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return OVHCloudProvider._sized_decimal(match.group("value"), match.groupdict().get("unit") or "gb")
        return None

    @staticmethod
    def _locations_from_plan(plan: dict[str, Any]) -> list[str | None]:
        locations: list[str | None] = []
        seen: set[str] = set()
        for config in plan.get("configurations") or []:
            if not isinstance(config, dict):
                continue
            name = str(config.get("name") or "").lower()
            if not any(token in name for token in ("datacenter", "location", "zone")):
                continue
            values = config.get("values") or []
            if isinstance(values, str):
                values = [values]
            for value in values:
                if value and str(value) not in seen:
                    seen.add(str(value))
                    locations.append(str(value))
        return locations or [None]

    @classmethod
    def _infer_specs(cls, plan: dict[str, Any]) -> tuple[int | None, Decimal | None, Decimal | None]:
        """Best-effort extraction from OVH plan names/codes.

        Modern OVH VPS plan codes and invoice names commonly include a
        CPU-RAM-disk triplet as three hyphen-separated numbers, e.g.
        `vps-value-1-2-40-vps-2025-model1-degressivity24-10percent`.
        """
        text = cls._plan_text(plan)
        cpu = ram = disk = None

        triplet = re.search(
            r"(?<![A-Za-z0-9.])(?P<cpu>\d+)-(?P<ram>\d+(?:\.\d+)?)-(?P<disk>\d+(?:\.\d+)?)(?=$|[^A-Za-z0-9.])",
            text,
        )
        if triplet:
            cpu = int(triplet.group("cpu"))
            ram = dec(triplet.group("ram"))
            disk = dec(triplet.group("disk"))

        if cpu is None:
            cpu_match = re.search(r"(?i)\b(?P<value>\d+)\s*(?:v\s*cores?|vcores?|vcpus?|cpus?|cores?)\b", text)
            if cpu_match:
                cpu = int(cpu_match.group("value"))
        if ram is None:
            ram = cls._first_decimal([
                r"(?i)\b(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>tib|tb|gib|gb|t|g)\s*(?:ram|memory|mem)\b",
                r"(?i)\b(?:ram|memory|mem)\s*:\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>tib|tb|gib|gb|t|g)\b",
            ], text)
        if disk is None:
            disk = cls._first_decimal([
                r"(?i)\b(?:disk|storage|ssd|nvme)\s*:?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>tib|tb|gib|gb|t|g)\b",
                r"(?i)\b(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>tib|tb|gib|gb|t|g)\s*(?:nvme|ssd|disk|storage)\b",
            ], text)
        return cpu, ram, disk

    def list_offers(self, *, orderable_only: bool = False) -> list[Offer]:
        catalog = self._call("get", "/order/catalog/public/vps", ovhSubsidiary=self.subsidiary)
        locale = catalog.get("locale") or {}
        catalog_currency = locale.get("currencyCode") if isinstance(locale, dict) else None
        offers: list[Offer] = []
        for plan in catalog.get("plans", []):
            plan_code = plan.get("planCode")
            if not plan_code:
                continue
            monthly, currency, duration, pricing_mode = self._pricing(plan, catalog_currency)
            vcpu, ram, disk = self._infer_specs(plan)
            product = plan.get("product")
            if isinstance(product, dict):
                product_name = product.get("name") or product.get("description")
            else:
                product_name = product
            metadata = {
                "duration": duration,
                "pricing_mode": pricing_mode,
                "subsidiary": self.subsidiary,
                "catalog_plan": plan,
            }
            for offer_location in self._locations_from_plan(plan):
                offers.append(Offer(
                    provider=self.name,
                    id=str(plan_code),
                    name=str(plan.get("invoiceName") or product_name or plan_code),
                    location=offer_location,
                    vcpu=vcpu,
                    ram_gb=ram,
                    disk_gb=disk,
                    monthly_price=monthly,
                    currency=currency,
                    price_source="public-vps-catalog",
                    available=None,
                    metadata=metadata,
                ))
        return offers

    def list_servers(self) -> list[Server]:
        service_names = self._call("get", "/vps")
        result: list[Server] = []
        for service_name in service_names:
            info = self._call("get", f"/vps/{service_name}")
            ip = info.get("ip")
            ips = info.get("ips") or []
            if not ip and ips:
                ip = ips[0]
            model = info.get("model")
            if isinstance(model, dict):
                offer_id = model.get("name") or model.get("id") or model.get("planCode")
            elif isinstance(model, str):
                offer_id = model
            else:
                offer_id = None
            result.append(Server(
                provider=self.name,
                id=str(service_name),
                name=str(info.get("displayName") or info.get("name") or service_name),
                status=str(info.get("state") or "unknown"),
                location=info.get("zone") or info.get("cluster"),
                offer_id=offer_id,
                ipv4=ip,
                metadata={"raw_model": model},
            ))
        return result

    def _prepare_cart(self, request: CreateServerRequest) -> tuple[str, str, dict[str, Any], Offer | None]:
        offer = next((o for o in self.list_offers() if o.id == request.offer_id), None)
        duration = str(request.metadata.get("duration") or (offer.metadata.get("duration") if offer else None) or "P1M")
        pricing_mode = str(request.metadata.get("pricing_mode") or (offer.metadata.get("pricing_mode") if offer else None) or "default")

        cart = self._call("post", "/order/cart", ovhSubsidiary=self.subsidiary, description=f"vps:{request.name}")
        cart_id = str(cart["cartId"])
        self._call("post", f"/order/cart/{cart_id}/assign")
        item = self._call(
            "post",
            f"/order/cart/{cart_id}/vps",
            planCode=request.offer_id,
            duration=duration,
            pricingMode=pricing_mode,
            quantity=1,
        )
        item_id = item.get("itemId") if isinstance(item, dict) else None
        if item_id is None:
            item_ids = self._call("get", f"/order/cart/{cart_id}/item")
            if not item_ids:
                raise ProviderError("OVHcloud cart contains no VPS item after add-to-cart.")
            item_id = item_ids[-1]
        item_id = str(item_id)

        required = self._call("get", f"/order/cart/{cart_id}/item/{item_id}/requiredConfiguration")
        explicit: dict[str, Any] = dict(request.metadata.get("ovh_config") or {})
        for cfg in required:
            label = str(cfg.get("label") or "")
            lower = label.lower()
            if label in explicit:
                value = explicit.pop(label)
            elif request.location and any(token in lower for token in ("datacenter", "location", "zone")):
                value = request.location
            elif request.image and any(token in lower for token in ("os", "image", "distribution")):
                value = request.image
            elif request.name and lower in {"description", "display_name", "displayname"}:
                value = request.name
            elif cfg.get("required"):
                raise ConfigurationError(
                    f"OVHcloud requires configuration '{label}' ({cfg.get('type')}). "
                    f"Pass it through metadata['ovh_config'] / CLI --ovh-config LABEL=VALUE."
                )
            else:
                continue
            self._call("post", f"/order/cart/{cart_id}/item/{item_id}/configuration", label=label, value=value)
        for label, value in explicit.items():
            self._call("post", f"/order/cart/{cart_id}/item/{item_id}/configuration", label=label, value=value)

        checkout = self._call("get", f"/order/cart/{cart_id}/checkout")
        return cart_id, item_id, checkout, offer

    @staticmethod
    def _quote_from_checkout(offer_id: str, checkout: dict[str, Any], offer: Offer | None) -> Quote:
        prices = checkout.get("prices") or {}
        money = prices.get("withTax") or prices.get("withoutTax") or prices.get("price")
        due_now, currency = money_from_obj(money)
        if isinstance(money, dict) and currency is None:
            currency = money.get("currencyCode")
        return Quote(
            provider="ovhcloud",
            offer_id=offer_id,
            monthly_price=offer.monthly_price if offer else None,
            due_now=due_now,
            currency=currency or (offer.currency if offer else None),
            description="OVHcloud cart checkout dry-run",
            metadata={"checkout": checkout},
        )

    def quote(self, request: CreateServerRequest) -> Quote:
        _, _, checkout, offer = self._prepare_cart(request)
        return self._quote_from_checkout(request.offer_id, checkout, offer)

    def create_server(self, request: CreateServerRequest) -> Server:
        cart_id, _, checkout, offer = self._prepare_cart(request)
        # GET checkout above validates the configured cart. POST creates the sales order.
        order = self._call(
            "post",
            f"/order/cart/{cart_id}/checkout",
            autoPayWithPreferredPaymentMethod=bool(request.metadata.get("auto_pay", True)),
            waiveRetractationPeriod=bool(request.metadata.get("waive_retractation", True)),
        )
        order_id = order.get("orderId") if isinstance(order, dict) else None
        status = "order-created"
        return Server(
            provider=self.name,
            id=str(order_id or cart_id),
            name=request.name,
            status=status,
            location=request.location,
            offer_id=request.offer_id,
            metadata={
                "order_id": order_id,
                "order_url": order.get("url") if isinstance(order, dict) else None,
                "checkout": checkout,
                "catalog_monthly_price": str(offer.monthly_price) if offer and offer.monthly_price is not None else None,
            },
        )
