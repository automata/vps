from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import typer
from rich import box
from rich.console import Console
from rich.table import Table

from .models import CreateServerRequest, Offer, Quote, Server
from .provider import ProviderError
from .registry import configured_providers, make_provider

app = typer.Typer(
    name="vpsctl",
    no_args_is_help=True,
    help="Compare and provision VPS instances across Hetzner, OVHcloud, and Contabo.",
)
console = Console()
err_console = Console(stderr=True)


def _provider_names(values: list[str]) -> list[str]:
    if not values:
        return ["hetzner", "ovhcloud", "contabo"]
    result: list[str] = []
    for value in values:
        result.extend(x.strip() for x in value.split(",") if x.strip())
    return result


def _money(value: Decimal | None, currency: str | None) -> str:
    if value is None:
        return "?"
    return f"{value} {currency or ''}".strip()


def _warn_config(errors: dict[str, str]) -> None:
    for provider, message in errors.items():
        err_console.print(f"[yellow]{provider} skipped:[/yellow] {message}")


def _offers_table(offers: list[Offer]) -> Table:
    table = Table(title="VPS offers", box=box.ASCII, show_lines=False)
    for column, justify in [
        ("Provider", "left"), ("Offer", "left"), ("Location", "left"),
        ("vCPU", "right"), ("RAM GB", "right"), ("Disk GB", "right"),
        ("Monthly", "right"), ("Hourly", "right"), ("Price source", "left"),
    ]:
        table.add_column(column, justify=justify)
    for offer in offers:
        table.add_row(
            offer.provider,
            offer.id,
            offer.location or "-",
            "?" if offer.vcpu is None else str(offer.vcpu),
            "?" if offer.ram_gb is None else str(offer.ram_gb),
            "?" if offer.disk_gb is None else str(offer.disk_gb),
            _money(offer.monthly_price, offer.currency),
            _money(offer.hourly_price, offer.currency),
            offer.price_source,
        )
    return table


def _servers_table(servers: list[Server]) -> Table:
    table = Table(title="Servers", box=box.ASCII)
    for c in ["Provider", "ID", "Name", "Status", "Offer", "Location", "IPv4", "IPv6"]:
        table.add_column(c)
    for s in servers:
        table.add_row(s.provider, s.id, s.name, s.status, s.offer_id or "-", s.location or "-", s.ipv4 or "-", s.ipv6 or "-")
    return table


def _quote_table(quote: Quote) -> Table:
    table = Table(title="Pre-purchase quote", box=box.ASCII)
    table.add_column("Provider")
    table.add_column("Offer")
    table.add_column("Monthly")
    table.add_column("Due now")
    table.add_column("Description")
    table.add_row(
        quote.provider,
        quote.offer_id,
        _money(quote.monthly_price, quote.currency),
        _money(quote.due_now, quote.currency),
        quote.description or "-",
    )
    return table


def _parse_pairs(pairs: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise typer.BadParameter(f"Expected LABEL=VALUE, got: {pair}")
        key, value = pair.split("=", 1)
        result[key] = value
    return result


def _request(
    name: str,
    offer: str,
    location: str | None,
    image: str | None,
    ssh_key: list[str],
    user_data_file: Path | None,
    ovh_config: list[str],
    period: int,
    metadata_json: str | None,
) -> CreateServerRequest:
    metadata: dict[str, Any] = json.loads(metadata_json) if metadata_json else {}
    if ovh_config:
        metadata["ovh_config"] = _parse_pairs(ovh_config)
    if period:
        metadata["period"] = period
    user_data = user_data_file.read_text() if user_data_file else None
    return CreateServerRequest(
        name=name,
        offer_id=offer,
        location=location,
        image=image,
        ssh_keys=ssh_key,
        user_data=user_data,
        metadata=metadata,
    )


@app.command()
def prices(
    provider: list[str] = typer.Option([], "--provider", "-p", help="Provider(s); repeat or comma-separate. Default: all."),
    location: str | None = typer.Option(None, help="Only this exact normalized location."),
    min_cpu: int | None = typer.Option(None, help="Minimum vCPU count."),
    min_ram: float | None = typer.Option(None, help="Minimum RAM in GB."),
    max_monthly: float | None = typer.Option(None, help="Maximum monthly price; unknown prices are excluded."),
    output_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Fetch and normalize current discoverable offers/prices."""
    providers, errors = configured_providers(_provider_names(provider))
    offers: list[Offer] = []
    for p in providers:
        try:
            offers.extend(p.list_offers())
        except Exception as exc:
            errors[p.name] = str(exc)
    _warn_config(errors)

    if location:
        offers = [o for o in offers if o.location == location]
    if min_cpu is not None:
        offers = [o for o in offers if o.vcpu is not None and o.vcpu >= min_cpu]
    if min_ram is not None:
        min_ram_d = Decimal(str(min_ram))
        offers = [o for o in offers if o.ram_gb is not None and o.ram_gb >= min_ram_d]
    if max_monthly is not None:
        max_monthly_d = Decimal(str(max_monthly))
        offers = [o for o in offers if o.monthly_price is not None and o.monthly_price <= max_monthly_d]

    offers.sort(key=lambda o: (o.monthly_price is None, o.monthly_price or Decimal("Infinity"), o.provider, o.id, o.location or ""))
    if output_json:
        console.print_json(json.dumps([o.as_dict() for o in offers]))
    else:
        console.print(_offers_table(offers))


@app.command()
def servers(
    provider: list[str] = typer.Option([], "--provider", "-p", help="Provider(s); repeat or comma-separate. Default: all."),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """List existing servers across configured providers."""
    providers, errors = configured_providers(_provider_names(provider))
    result: list[Server] = []
    for p in providers:
        try:
            result.extend(p.list_servers())
        except Exception as exc:
            errors[p.name] = str(exc)
    _warn_config(errors)
    if output_json:
        console.print_json(json.dumps([s.as_dict() for s in result]))
    else:
        console.print(_servers_table(result))


@app.command()
def quote(
    provider: str = typer.Argument(...),
    offer: str = typer.Argument(...),
    name: str = typer.Option("vpsbroker-quote", "--name"),
    location: str | None = typer.Option(None, "--location"),
    image: str | None = typer.Option(None, "--image"),
    ssh_key: list[str] = typer.Option([], "--ssh-key"),
    user_data_file: Path | None = typer.Option(None, "--user-data-file", exists=True, dir_okay=False),
    ovh_config: list[str] = typer.Option([], "--ovh-config", help="OVH required config LABEL=VALUE; repeatable."),
    period: int = typer.Option(1, "--period", help="Contabo contract period in months."),
    metadata_json: str | None = typer.Option(None, "--metadata-json"),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """Get the best provider-native pre-purchase quote/dry-run available."""
    p = make_provider(provider)
    req = _request(name, offer, location, image, ssh_key, user_data_file, ovh_config, period, metadata_json)
    q = p.quote(req)
    if output_json:
        console.print_json(json.dumps(q.as_dict()))
    else:
        console.print(_quote_table(q))


@app.command("order")
@app.command("create")
def provision(
    provider: str = typer.Argument(...),
    offer: str = typer.Argument(...),
    name: str = typer.Option(..., "--name"),
    location: str | None = typer.Option(None, "--location"),
    image: str | None = typer.Option(None, "--image"),
    ssh_key: list[str] = typer.Option([], "--ssh-key", help="Hetzner SSH key ID/name; Contabo numeric secret ID."),
    user_data_file: Path | None = typer.Option(None, "--user-data-file", exists=True, dir_okay=False),
    ovh_config: list[str] = typer.Option([], "--ovh-config", help="OVH required config LABEL=VALUE; repeatable."),
    period: int = typer.Option(1, "--period", help="Contabo: 1, 12, or 24 months."),
    metadata_json: str | None = typer.Option(None, "--metadata-json", help="Provider-specific JSON escape hatch."),
    max_monthly: float | None = typer.Option(None, "--max-monthly", help="Refuse if normalized monthly price exceeds this."),
    allow_unknown_price: bool = typer.Option(False, "--allow-unknown-price", help="Allow purchase when API cannot establish a price."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Quote only; do not create/order."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Required to perform a billable create/order."),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """Create/order a VPS. The operation may incur charges."""
    p = make_provider(provider)
    req = _request(name, offer, location, image, ssh_key, user_data_file, ovh_config, period, metadata_json)
    q = p.quote(req)

    if output_json and dry_run:
        console.print_json(json.dumps(q.as_dict()))
        raise typer.Exit()
    if not output_json:
        console.print(_quote_table(q))

    if dry_run:
        return

    if max_monthly is not None:
        if q.monthly_price is None and not allow_unknown_price:
            raise typer.BadParameter("Monthly price is unknown; refusing --max-monthly check. Add --allow-unknown-price to override.")
        max_monthly_d = Decimal(str(max_monthly))
        if q.monthly_price is not None and q.monthly_price > max_monthly_d:
            raise typer.BadParameter(f"Quote monthly price {q.monthly_price} exceeds --max-monthly {max_monthly_d}.")

    if q.monthly_price is None and q.due_now is None and not allow_unknown_price:
        raise typer.BadParameter("Provider API did not establish a price. Refusing purchase unless --allow-unknown-price is supplied.")

    if not yes:
        raise typer.BadParameter("Billable operation refused. Re-run with --yes after reviewing the quote.")

    server = p.create_server(req)
    if output_json:
        console.print_json(json.dumps(server.as_dict()))
    else:
        console.print("[green]Order/create submitted.[/green]")
        console.print(_servers_table([server]))


@app.command()
def providers() -> None:
    """Show credential environment variables and provider price behavior."""
    table = Table(title="Provider configuration", box=box.ASCII)
    table.add_column("Provider")
    table.add_column("Credentials")
    table.add_column("Price discovery")
    table.add_row("hetzner", "HETZNER_TOKEN", "Live server_types prices per location")
    table.add_row("ovhcloud", "OVH_APPLICATION_KEY / SECRET / CONSUMER_KEY; OVH_ENDPOINT; OVH_SUBSIDIARY", "Public VPS catalog + checkout dry-run")
    table.add_row("contabo", "CONTABO_CLIENT_ID / SECRET / API_USER / API_PASSWORD", "New-order API has no general live price catalogue; optional reference-instance/user JSON enrichment")
    console.print(table)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
