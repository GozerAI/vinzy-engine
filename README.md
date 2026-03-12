# Vinzy-Engine
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://python.org)

Cryptographic license key generator, entitlement manager, and usage metering platform.

## Overview

Vinzy-Engine is a self-hosted licensing backend built on FastAPI. It generates HMAC-signed license keys, manages per-feature and per-agent entitlements, tracks metered usage, detects behavioral anomalies, and delivers webhook notifications — all behind a zero-trust API with multi-tenant isolation.

## Features

- **Cryptographic key generation** — HMAC-SHA256 signed keys with version-encoded rotation support
- **Entitlement resolution** — per-feature flags and limits, per-agent token/model-tier entitlements
- **Cross-product composition** — merge entitlements across multiple licenses (sum/max/union strategies)
- **Signed leases** — offline-capable validation tokens with configurable TTL
- **Usage metering** — record and aggregate usage by metric, enforce entitlement limits
- **Anomaly detection** — z-score behavioral analysis with severity classification
- **Cryptographic audit trail** — SHA-256 hash-chained, HMAC-signed immutable event log
- **Webhook dispatch** — HMAC-signed HTTP deliveries with exponential-backoff retry
- **Multi-tenancy** — tenant-scoped data isolation with per-tenant API keys
- **Admin dashboard** — Jinja2 + htmx web UI at `/dashboard` for managing all entities
- **CLI** — `vinzy serve`, `vinzy generate`, `vinzy validate`, `vinzy health`

## Installation

```bash
pip install vinzy-engine
```

For development:

```bash
git clone https://github.com/chrisarseno/vinzy-engine.git
cd vinzy-engine
pip install -e ".[dev]"
```

## Quick Start

Start the server:

```bash
vinzy serve
```

The API is available at `http://localhost:8080` and the admin dashboard at `http://localhost:8080/dashboard`.

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
    print(f"License OK — tier: {result.tier}, features: {result.features}")
```

## Architecture

```
src/vinzy_engine/
├── common/          Config, database, exceptions, auth
├── keygen/          Key generation, HMAC validation, signed leases
├── licensing/       Products, customers, licenses, entitlements, composition
├── activation/      Machine activation and heartbeat
├── usage/           Metered usage recording and aggregation
├── audit/           Hash-chained cryptographic audit trail
├── anomaly/         Z-score behavioral anomaly detection
├── tenants/         Multi-tenant isolation and API key management
├── webhooks/        Event dispatch with HMAC-signed deliveries
├── dashboard/       Admin web UI (Jinja2 + htmx + Pico CSS)
├── app.py           FastAPI application factory
├── deps.py          Dependency injection singletons
├── cli.py           Typer CLI (serve, generate, validate, health)
└── client.py        Python SDK client
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
| `VINZY_HMAC_KEYS` | `""` | JSON keyring for rotation, e.g. `{"0": "old", "1": "new"}` |
| `VINZY_DB_URL` | `sqlite+aiosqlite:///./data/vinzy.db` | Database URL |
| `VINZY_API_KEY` | (insecure default) | Admin API key |
| `VINZY_SUPER_ADMIN_KEY` | (insecure default) | Super-admin key (tenant management) |
| `VINZY_HOST` | `0.0.0.0` | Bind host |
| `VINZY_PORT` | `8080` | Bind port |
| `VINZY_LEASE_TTL` | `86400` | Signed lease validity (seconds) |

## API Endpoints

### Public (no auth)
- `POST /validate` — validate a license key
- `POST /activate` — activate a machine
- `POST /deactivate` — deactivate a machine
- `POST /heartbeat` — machine heartbeat
- `POST /usage/record` — record usage metric

### Admin (requires `X-Vinzy-Api-Key`)
- `POST /products`, `GET /products` — product CRUD
- `POST /customers`, `GET /customers` — customer CRUD
- `POST /licenses`, `GET /licenses`, `PATCH /licenses/{id}`, `DELETE /licenses/{id}` — license CRUD
- `GET /audit/{license_id}` — audit trail
- `GET /anomalies` — anomaly list
- `POST /anomalies/{id}/resolve` — resolve anomaly
- `POST /webhooks`, `GET /webhooks` — webhook endpoint CRUD

### Super-Admin (requires super-admin key)
- `POST /tenants`, `GET /tenants`, `PATCH /tenants/{id}`, `DELETE /tenants/{id}` — tenant CRUD

### Dashboard
- `GET /dashboard/` — admin web UI (cookie auth)

## Testing

```bash
pytest tests/ -q
```

380+ tests covering key generation, licensing, activation, usage, audit chain integrity, anomaly detection, webhooks, multi-tenancy, and dashboard.

## License

This project is dual-licensed:

- **AGPL-3.0** — free for open-source use. See [LICENSE](LICENSE).
- **Commercial License** — for proprietary use without AGPL obligations. See [COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md).

Copyright (c) 2025-2026 Chris Arsenault / 1450 Enterprises LLC.
