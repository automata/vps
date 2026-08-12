from __future__ import annotations

from .provider import Provider
from .providers import ContaboProvider, HetznerProvider, OVHCloudProvider


def make_provider(name: str) -> Provider:
    key = name.strip().lower()
    if key in {"hetzner", "hcloud"}:
        return HetznerProvider()
    if key in {"ovh", "ovhcloud"}:
        return OVHCloudProvider()
    if key == "contabo":
        return ContaboProvider()
    raise ValueError(f"Unknown provider: {name}")


def configured_providers(names: list[str] | None = None) -> tuple[list[Provider], dict[str, str]]:
    names = names or ["hetzner", "ovhcloud", "contabo"]
    providers: list[Provider] = []
    errors: dict[str, str] = {}
    for name in names:
        try:
            providers.append(make_provider(name))
        except Exception as exc:
            errors[name] = str(exc)
    return providers, errors
