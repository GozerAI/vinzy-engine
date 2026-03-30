#!/usr/bin/env python3
"""Generate community-tier README for public export."""
import sys

target_path = sys.argv[1]
product = sys.argv[2]

if product == "vinzy-engine":
    content = """# Vinzy-Engine

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://python.org)

Cryptographic license key generator, entitlement manager, and usage metering platform -- part of the [GozerAI](https://gozerai.com) ecosystem.

## Overview

Vinzy-Engine is a self-hosted licensing backend built on FastAPI. It generates HMAC-signed license keys, manages per-feature entitlements, tracks metered usage, and delivers webhook notifications -- all behind a zero-trust API.

## Community Features

- **Cryptographic key generation** -- HMAC-SHA256 signed keys with version-encoded rotation support
- **Entitlement resolution** -- per-feature flags and limits
- **Signed leases** -- offline-capable validation tokens with configurable TTL
- **Usage metering** -- record and aggregate usage by metric, enforce entitlement limits
- **Machine activation** -- activation and heartbeat tracking
- **Webhook dispatch** -- HMAC-signed HTTP deliveries with exponential-backoff retry
- **CLI** -- `vinzy serve`, `vinzy generate`, `vinzy validate`, `vinzy health`
- **Python SDK** -- `LicenseClient` for programmatic validation

## Pro & Enterprise Features

Additional modules are available with a commercial license:

- **Anomaly Detection** (Pro) -- z-score behavioral analysis with severity classification
- **Admin Dashboard** (Pro) -- Jinja2 + htmx web UI for managing all entities
- **Cryptographic Audit Trail** (Enterprise) -- SHA-256 hash-chained, HMAC-signed immutable event log
- **Auto-Provisioning** (Enterprise) -- Stripe/Polar webhook-driven customer and license provisioning
- **Multi-Tenancy** (Enterprise) -- tenant-scoped data isolation with per-tenant API keys

Visit [gozerai.com/pricing](https://gozerai.com/pricing) for details.

## Installation

```bash
pip install vinzy-engine
```

For development:

```bash
git clone https://github.com/GozerAI/vinzy-engine.git
cd vinzy-engine
pip install -e ".[dev]"
```

## Quick Start

Start the server:

```bash
vinzy serve
```

The API is available at `http://localhost:8080`.

Create a product and issue a license:

```bash
# Create a product
curl -X POST http://localhost:8080/products \
  -H "X-Vinzy-Api-Key: $VINZY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"code": "PRD", "name": "My Product"}'

# Create a customer
curl -X POST http://localhost:8080/customers \
  -H "X-Vinzy-Api-Key: $VINZY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "Jane Doe", "email": "jane@example.com"}'

# Issue a license (returns the raw key)
curl -X POST http://localhost:8080/licenses \
  -H "X-Vinzy-Api-Key: $VINZY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"product_code": "PRD", "customer_id": "<customer-id>"}'

# Validate a license (public endpoint, no auth required)
curl -X POST http://localhost:8080/validate \
  -H "Content-Type: application/json" \
  -d '{"key": "PRD-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX"}'
```

### Python SDK

```python
from vinzy_engine import LicenseClient

client = LicenseClient("http://localhost:8080")
result = client.validate("PRD-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX")

if result.valid:
    print(f"License OK -- tier: {result.tier}, features: {result.features}")
```

## Key Format

```
{PRD}-{AAAAA}-{BBBBB}-{CCCCC}-{DDDDD}-{EEEEE}-{HHHHH}-{HHHHH}
  |     |                                         |
  |     +-- 5 random base32 segments               +-- 2 HMAC segments
  +-- 3-char product code
```

The first character of the first random segment encodes the HMAC key version (0-31), enabling seamless key rotation without invalidating existing keys.

## Configuration

All settings use the `VINZY_` environment variable prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `VINZY_SECRET_KEY` | (insecure default) | Session signing secret |
| `VINZY_HMAC_KEY` | (insecure default) | HMAC key for key generation |
| `VINZY_HMAC_KEYS` | `""` | JSON keyring for rotation |
| `VINZY_DB_URL` | `sqlite+aiosqlite:///./data/vinzy.db` | Database URL |
| `VINZY_API_KEY` | (insecure default) | Admin API key |
| `VINZY_HOST` | `0.0.0.0` | Bind host |
| `VINZY_PORT` | `8080` | Bind port |
| `VINZY_LEASE_TTL` | `86400` | Signed lease validity (seconds) |

## API Endpoints

### Public (no auth)
- `POST /validate` -- validate a license key
- `POST /activate` -- activate a machine
- `POST /deactivate` -- deactivate a machine
- `POST /heartbeat` -- machine heartbeat
- `POST /usage/record` -- record usage metric

### Admin (requires `X-Vinzy-Api-Key`)
- `POST /products`, `GET /products` -- product CRUD
- `POST /customers`, `GET /customers` -- customer CRUD
- `POST /licenses`, `GET /licenses`, `PATCH /licenses/{id}`, `DELETE /licenses/{id}` -- license CRUD
- `POST /webhooks`, `GET /webhooks` -- webhook endpoint CRUD

## Testing

```bash
pytest tests/ -q
```

## License

This project is dual-licensed:

- **AGPL-3.0** -- free for open-source use. See [LICENSE](LICENSE).
- **Commercial License** -- for proprietary use. Visit [gozerai.com/pricing](https://gozerai.com/pricing).

Copyright (c) 2025-2026 GozerAI.
"""
else:
    print(f"Unknown product: {product}", file=sys.stderr)
    sys.exit(1)

with open(target_path, "w", newline="\n") as f:
    f.write(content.lstrip())
print(f"README written to {target_path}")
