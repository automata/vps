from __future__ import annotations

from abc import ABC, abstractmethod

from .models import CreateServerRequest, Offer, Quote, Server


class ProviderError(RuntimeError):
    pass


class ConfigurationError(ProviderError):
    pass


class UnsupportedOperation(ProviderError):
    pass


class Provider(ABC):
    name: str

    @abstractmethod
    def list_offers(self, *, orderable_only: bool = False) -> list[Offer]:
        """Return currently discoverable offers.

        When orderable_only is true, providers should filter to offers they can
        positively determine are currently orderable. Providers without a
        dedicated availability API may return their best-effort catalogue.
        """

    @abstractmethod
    def list_servers(self) -> list[Server]:
        """Return servers in the authenticated account/project."""

    def quote(self, request: CreateServerRequest) -> Quote:
        """Return the best pre-purchase quote the provider API supports."""
        offer = next((o for o in self.list_offers() if o.id == request.offer_id and (not request.location or o.location == request.location)), None)
        if not offer:
            return Quote(self.name, request.offer_id, description="No provider-native pre-purchase quote is available.")
        return Quote(
            provider=self.name,
            offer_id=request.offer_id,
            monthly_price=offer.monthly_price,
            currency=offer.currency,
            description=f"Catalogue/API price for {offer.name}",
        )

    @abstractmethod
    def create_server(self, request: CreateServerRequest) -> Server:
        """Create/order a server. This may incur charges."""
