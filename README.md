# Vinzy-Engine

**License Management and Entitlement Engine**

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://python.org)

Vinzy-Engine is a self-hosted licensing backend for generating cryptographic license keys, managing per-feature entitlements, tracking machine activations, and metering usage. Built on FastAPI with async SQLAlchemy. Part of the [GozerAI](https://gozerai.com) ecosystem.

---

## Features

- **Cryptographic Key Generation** -- HMAC-SHA256 signed keys with version-encoded rotation support
- **Entitlement Resolution** -- Per-feature flags and limits tied to license tiers
- **Signed Leases** -- Offline-capable validation tokens with configurable TTL
- **Machine Activation** -- Activation, deactivation, and heartbeat tracking
- **Usage Metering** -- Record and aggregate usage by metric, enforce entitlement limits
- **Webhook Dispatch** -- HMAC-signed HTTP deliveries with exponential-backoff retry
- **CLI** -- `vinzy serve`, `vinzy generate`, `vinzy validate`, `vinzy health`
- **Python SDK** -- `LicenseClient` for programmatic validation in your applications

---

## Quick Start

### Installation

```bash
# From PyPI
pip install vinzy-engine

# From source
git clone https://github.com/GozerAI/vinzy-engine.git
cd vinzy-engine
pip install -e ".[dev]"
```

### Start the Server

```bash
vinzy serve
```

The API is available at `http://localhost:8080`.

### Create Products and Issue Licenses

```bash
# Create a product
curl -X POST http://localhost:8080/products \
  -H "X-Vinzy-Api-Key: $VINZY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"code": "MYP", "name": "My Product"}'

# Create a customer
curl -X POST http://localhost:8080/customers \
  -H "X-Vinzy-Api-Key: $VINZY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "Jane Doe", "email": "jane@example.com"}'

# Issue a license (returns the raw key)
curl -X POST http://localhost:8080/licenses \
  -H "X-Vinzy-Api-Key: $VINZY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"product_code": "MYP", "customer_id": "<customer-id>"}'
```

### Validate a License

```bash
# Public endpoint -- no auth required
curl -X POST http://localhost:8080/validate \
  -H "Content-Type: application/json" \
  -d '{"key": "MYP-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX"}'
```

### Activate and Deactivate Machines

```bash
# Activate a machine
curl -X POST http://localhost:8080/activate \
  -H "Content-Type: application/json" \
  -d '{"key": "MYP-XXXXX-...", "machine_id": "machine-001", "hostname": "dev-laptop"}'

# Send heartbeat
curl -X POST http://localhost:8080/heartbeat \
  -H "Content-Type: application/json" \
  -d '{"key": "MYP-XXXXX-...", "machine_id": "machine-001"}'

# Deactivate
curl -X POST http://localhost:8080/deactivate \
  -H "Content-Type: application/json" \
  -d '{"key": "MYP-XXXXX-...", "machine_id": "machine-001"}'
```

### Record Usage

```bash
curl -X POST http://localhost:8080/usage/record \
  -H "Content-Type: application/json" \
  -d '{"key": "MYP-XXXXX-...", "metric": "api_calls", "quantity": 1}'
```

### Python SDK

Integrate license validation into your own application:

```python
from vinzy_engine import LicenseClient

client = LicenseClient("http://localhost:8080")
result = client.validate("MYP-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX")

if result.valid:
    print(f"License OK -- tier: {result.tier}, features: {result.features}")
else:
    print(f"Invalid: {result.reason}")
```

### CLI

```bash
vinzy serve              # Start the API server
vinzy generate MYP       # Generate a license key for product MYP
vinzy validate <key>     # Validate a license key locally
vinzy health             # Check server health
```

---

## Key Format

```
{PRD}-{AAAAA}-{BBBBB}-{CCCCC}-{DDDDD}-{EEEEE}-{HHHHH}-{HHHHH}
  |     |                                         |
  |     +-- 5 random base32 segments               +-- 2 HMAC segments
  +-- 3-char product code
```

The first character of the first random segment encodes the HMAC key version (0-31), enabling seamless key rotation without invalidating existing keys.

---

## API Endpoints

### Public (no auth required)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/validate` | Validate a license key |
| `POST` | `/activate` | Activate a machine |
| `POST` | `/deactivate` | Deactivate a machine |
| `POST` | `/heartbeat` | Machine heartbeat |
| `POST` | `/usage/record` | Record a usage metric |

### Admin (requires `X-Vinzy-Api-Key` header)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/products` | Create a product |
| `GET` | `/products` | List products |
| `POST` | `/customers` | Create a customer |
| `GET` | `/customers` | List customers |
| `POST` | `/licenses` | Issue a license |
| `GET` | `/licenses` | List licenses |
| `PATCH` | `/licenses/{id}` | Update a license |
| `DELETE` | `/licenses/{id}` | Revoke a license |
| `POST` | `/webhooks` | Register a webhook endpoint |
| `GET` | `/webhooks` | List webhook endpoints |

---

## Feature Tiers

| Feature | Community | Pro | Enterprise |
|---------|:---------:|:---:|:----------:|
| Cryptographic key generation | Yes | Yes | Yes |
| License validation & signed leases | Yes | Yes | Yes |
| Machine activation & heartbeat | Yes | Yes | Yes |
| Usage metering & entitlement limits | Yes | Yes | Yes |
| Webhook dispatch (HMAC-signed) | Yes | Yes | Yes |
| CLI & Python SDK | Yes | Yes | Yes |
| Anomaly detection (behavioral analysis) | -- | Yes | Yes |
| Admin dashboard (web UI) | -- | Yes | Yes |
| Cryptographic audit trail | -- | -- | Yes |
| Auto-provisioning (Stripe/Polar webhooks) | -- | -- | Yes |
| Multi-tenant management | -- | -- | Yes |

Community tier provides a fully functional licensing backend. Pro and Enterprise add operational intelligence and enterprise automation.

---

## Configuration

All settings use the `VINZY_` environment variable prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `VINZY_SECRET_KEY` | (insecure default) | Session signing secret -- **change in production** |
| `VINZY_HMAC_KEY` | (insecure default) | HMAC key for license key generation |
| `VINZY_HMAC_KEYS` | `""` | JSON keyring for HMAC key rotation |
| `VINZY_DB_URL` | `sqlite+aiosqlite:///./data/vinzy.db` | Database URL |
| `VINZY_API_KEY` | (insecure default) | Admin API key -- **change in production** |
| `VINZY_HOST` | `0.0.0.0` | Bind host |
| `VINZY_PORT` | `8080` | Bind port |
| `VINZY_LEASE_TTL` | `86400` | Signed lease validity in seconds |

---

## Testing

```bash
pip install -e ".[dev]"
pytest tests/ -q
```

---

## License

Vinzy-Engine is dual-licensed:

- **[AGPL-3.0](LICENSE)** -- Free for open-source use with copyleft obligations
- **Commercial License** -- For proprietary use without AGPL requirements

Visit [gozerai.com/pricing](https://gozerai.com/pricing) for commercial licensing. See [LICENSING.md](LICENSING.md) for details.

---

## Contributing

We welcome contributions. Please see our [Contributing Guide](CONTRIBUTING.md) for details.

---

## Links

- [GozerAI](https://gozerai.com) -- Main site
- [Pricing](https://gozerai.com/pricing) -- License tiers and pricing
- [Issues](https://github.com/GozerAI/vinzy-engine/issues) -- Bug reports and feature requests

Copyright (c) 2025-2026 GozerAI.
