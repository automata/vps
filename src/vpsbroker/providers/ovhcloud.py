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
    def _pricing(plan: dict[str, Any]) -> tuple[Decimal | None, str | None, str, str]:
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
        interval = best.get("interval") or 1
        interval_unit = str(best.get("intervalUnit") or "month").lower()
        if amount is not None and interval_unit.startswith("month") and dec(interval):
            amount = amount / Decimal(str(interval))
        duration = str(best.get("duration") or plan.get("duration") or "P1M")
        pricing_mode = str(best.get("mode") or "default")
        return amount, currency, duration, pricing_mode

    @staticmethod
    def _infer_specs(plan: dict[str, Any]) -> tuple[int | None, Decimal | None, Decimal | None]:
        """Best-effort extraction; OVH catalog generations do not expose specs uniformly."""
        blob = " ".join(str(x) for x in [
            plan.get("invoiceName"), plan.get("product"), plan.get("planCode"), plan.get("description")
        ] if x)
        cpu = ram = disk = None
        cpu_m = re.search(r"(?i)(\d+)\s*(?:v?core|vcpu|cpu)", blob)
        ram_m = re.search(r"(?i)(\d+(?:\.\d+)?)\s*GB\s*(?:RAM|memory)?", blob)
        disk_m = re.search(r"(?i)(\d+(?:\.\d+)?)\s*GB\s*(?:NVMe|SSD|disk|storage)", blob)
        if cpu_m:
            cpu = int(cpu_m.group(1))
        if ram_m:
            ram = dec(ram_m.group(1))
        if disk_m:
            disk = dec(disk_m.group(1))
        return cpu, ram, disk

    def list_offers(self) -> list[Offer]:
        catalog = self._call("get", "/order/catalog/public/vps", ovhSubsidiary=self.subsidiary)
        offers: list[Offer] = []
        for plan in catalog.get("plans", []):
            plan_code = plan.get("planCode")
            if not plan_code:
                continue
            monthly, currency, duration, pricing_mode = self._pricing(plan)
            vcpu, ram, disk = self._infer_specs(plan)
            product = plan.get("product")
            if isinstance(product, dict):
                product_name = product.get("name") or product.get("description")
            else:
                product_name = product
            offers.append(Offer(
                provider=self.name,
                id=str(plan_code),
                name=str(plan.get("invoiceName") or product_name or plan_code),
                location=None,
                vcpu=vcpu,
                ram_gb=ram,
                disk_gb=disk,
                monthly_price=monthly,
                currency=currency,
                price_source="public-vps-catalog",
                available=None,
                metadata={
                    "duration": duration,
                    "pricing_mode": pricing_mode,
                    "subsidiary": self.subsidiary,
                    "catalog_plan": plan,
                },
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
            result.append(Server(
                provider=self.name,
                id=str(service_name),
                name=str(info.get("displayName") or info.get("name") or service_name),
                status=str(info.get("state") or "unknown"),
                location=info.get("zone") or info.get("cluster"),
                offer_id=info.get("model") if isinstance(info.get("model"), str) else None,
                ipv4=ip,
                metadata={"raw_model": info.get("model")},
            ))
        return result

    def _prepare_cart(self, request: CreateServerRequest) -> tuple[str, str, dict[str, Any], Offer | None]:
        offer = next((o for o in self.list_offers() if o.id == request.offer_id), None)
        duration = str(request.metadata.get("duration") or (offer.metadata.get("duration") if offer else None) or "P1M")
        pricing_mode = str(request.metadata.get("pricing_mode") or (offer.metadata.get("pricing_mode") if offer else None) or "default")

        cart = self._call("post", "/order/cart", ovhSubsidiary=self.subsidiary, description=f"vpsbroker:{request.name}")
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
