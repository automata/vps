# vpsbroker / `vpsctl`

A small Python module and CLI that normalizes VPS discovery and provisioning across:

- **Hetzner Cloud**
- **OVHcloud VPS**
- **Contabo VPS/VDS**

It exposes a common `Offer`, `Quote`, `Server`, and `CreateServerRequest` model and prints human-readable **ASCII tables** with Rich. JSON output is available for automation.

> **Important:** `create` / `order` can incur real charges. The CLI refuses billable operations unless `--yes` is supplied. If the provider API cannot establish a price, it additionally requires `--allow-unknown-price`.

## Install

This project is managed with [uv](https://docs.astral.sh/uv/). From the repository root:

```bash
uv sync --no-dev
uv run --no-dev vpsctl --help
```

Development/tests:

```bash
uv sync --group dev
uv run pytest
```

Build distributions:

```bash
uv build
```

## Credentials

Copy `.env.example` to `.env` and fill in the credentials you want to use. The package does not automatically load `.env` files; run commands through uv with `--env-file .env` when you want uv to inject them.

```bash
cp .env.example .env
uv run --no-dev --env-file .env vpsctl prices
```

### Hetzner

```dotenv
HETZNER_TOKEN=...
```

### OVHcloud

```dotenv
OVH_ENDPOINT=ovh-eu
OVH_SUBSIDIARY=GB
OVH_APPLICATION_KEY=...
OVH_APPLICATION_SECRET=...
OVH_CONSUMER_KEY=...
```

The OVH token needs rights for the order/cart endpoints and VPS reads you intend to use.

### Contabo

```dotenv
CONTABO_CLIENT_ID=...
CONTABO_CLIENT_SECRET=...
CONTABO_API_USER=...
CONTABO_API_PASSWORD=...
```

## CLI

The examples below show the console script directly. From a checkout, prefix commands with `uv run --no-dev --env-file .env`, e.g. `uv run --no-dev --env-file .env vpsctl prices`.

### Compare offers/prices

```bash
vpsctl prices
vpsctl prices -p hetzner
vpsctl prices -p hetzner -p ovhcloud --min-ram 8 --max-monthly 20
vpsctl prices --json
```

Example columns:

```text
+----------+----------+----------+------+--------+---------+-------------+-------------+--------------------+
| Provider | Offer    | Location | vCPU | RAM GB | Disk GB | Monthly     | Hourly      | Price source       |
+----------+----------+----------+------+--------+---------+-------------+-------------+--------------------+
| hetzner  | cx23     | nbg1     | 2    | 4      | 40      | ... EUR     | ... EUR     | server-types-api   |
| ovhcloud | ...      | -        | ?    | ?      | ?       | ... GBP/EUR | ?           | public-vps-catalog |
| contabo  | V153     | -        | ?    | ?      | 100     | ?           | ?           | price-unavailable...|
+----------+----------+----------+------+--------+---------+-------------+-------------+--------------------+
```

### List existing servers

```bash
vpsctl servers
vpsctl servers -p hetzner --json
```

### Quote / dry-run

```bash
vpsctl quote hetzner cx23 \
  --name worker-01 \
  --location nbg1 \
  --image ubuntu-24.04
```

OVHcloud uses its cart checkout GET as a provider-native dry-run. If OVH reports required configuration labels that the adapter cannot infer, pass them explicitly:

```bash
vpsctl quote ovhcloud PLAN_CODE \
  --name worker-01 \
  --location GRA \
  --image 'Ubuntu 24.04' \
  --ovh-config SOME_REQUIRED_LABEL=value
```

### Create/order

Hetzner:

```bash
vpsctl create hetzner cx23 \
  --name worker-01 \
  --location nbg1 \
  --image ubuntu-24.04 \
  --ssh-key my-key \
  --user-data-file examples/cloud-init.yaml \
  --max-monthly 10 \
  --yes
```

`order` is an alias of `create`:

```bash
vpsctl order hetzner cx23 --name worker-02 --location nbg1 --image ubuntu-24.04 --yes
```

Contabo (SSH keys are Contabo numeric Secret IDs):

```bash
vpsctl create contabo V153 \
  --name worker-01 \
  --location EU \
  --ssh-key 12345 \
  --user-data-file examples/cloud-init.yaml \
  --allow-unknown-price \
  --yes
```

OVHcloud:

```bash
vpsctl create ovhcloud PLAN_CODE \
  --name worker-01 \
  --location GRA \
  --image 'Ubuntu 24.04' \
  --max-monthly 15 \
  --yes
```

## Python API

```python
from vpsbroker.models import CreateServerRequest
from vpsbroker.providers import HetznerProvider

provider = HetznerProvider()

offers = provider.list_offers()
for offer in offers:
    print(offer.id, offer.location, offer.monthly_price, offer.currency)

request = CreateServerRequest(
    name="worker-01",
    offer_id="cx23",
    location="nbg1",
    image="ubuntu-24.04",
    ssh_keys=["my-key"],
    user_data="#cloud-config\npackage_update: true\n",
)

quote = provider.quote(request)
print(quote)

# Billable:
# server = provider.create_server(request)
```

## Provider behavior and limitations

### Hetzner Cloud

The adapter reads `/server_types` and `/pricing`. Server-type pricing can vary by location; the normalized representation therefore produces one `Offer` per server type/location price combination. Server creation uses `POST /servers`.

### OVHcloud

OVHcloud is normalized around its order/cart model:

1. fetch the public VPS catalogue,
2. create + assign a cart,
3. add a VPS plan,
4. add required item configuration,
5. `GET /order/cart/{cartId}/checkout` for validation/dry-run,
6. `POST /order/cart/{cartId}/checkout` to create the order.

OVH catalogue generations are not uniform about exposing CPU/RAM/disk fields, so the adapter treats those specs as optional and only performs a conservative best-effort parse. Use the plan code as the stable normalized offer ID.

### Contabo

Contabo's Compute API documents product IDs that can be submitted to `POST /v1/compute/instances`, but its public API does **not** expose a general live new-order price catalogue equivalent to Hetzner's `/pricing`. Therefore the default Contabo offers have `monthly_price=None`.

Two optional enrichment modes exist:

1. `CONTABO_PRICE_REFERENCE_INSTANCE_ID`: call the existing-instance upgrade-options endpoint and expose its `vsPrice` values with `price_source=upgrade-reference-api`. These prices/options are **not guaranteed to equal new-order pricing**, and the current product is excluded by that endpoint.
2. `CONTABO_PRICE_CATALOG_JSON`: point to your own normalized JSON catalogue. Those prices are marked `user-catalog-json` and are explicitly not claimed to be provider-verified.

Example JSON:

```json
[
  {
    "id": "V153",
    "name": "Cloud VPS 4",
    "location": "EU",
    "vcpu": 4,
    "ram_gb": 8,
    "disk_gb": 100,
    "monthly_price": "8.50",
    "currency": "EUR"
  }
]
```

## Provider-specific escape hatch

For API fields not normalized yet, `CreateServerRequest.metadata` is intentionally available. From the CLI:

```bash
vpsctl create hetzner cx23 --name demo --metadata-json '{"labels":{"role":"worker"}}' --yes
```

Known metadata keys include:

- Hetzner: `labels`, `public_net`
- OVHcloud: `duration`, `pricing_mode`, `ovh_config`, `auto_pay`, `waive_retractation`
- Contabo: `period`, `default_user`, `root_password_secret_id`, `add_ons`

## API references used for this implementation

- Hetzner Cloud API: https://docs.hetzner.cloud/reference/cloud
- OVHcloud API console: https://api.eu.ovhcloud.com/console/?branch=v1&section=/order
- OVH order-cart configuration guide: https://github.com/ovh/order-cart-examples/blob/master/docs/configuration.en.md
- Contabo API: https://api.contabo.com/
