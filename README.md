# Vinzy-Engine

Licensing and entitlement control plane for identity-governed applications. Vinzy-Engine generates cryptographic license keys, resolves per-feature entitlements, meters usage, detects anomalies, and maintains a hash-chained audit trail -- all behind a multi-tenant API designed to operate under the identity authority of a zero-trust platform.

## Relationship to Zuultimate

Vinzy-Engine is the licensing counterpart to [Zuultimate](https://github.com/chrisarseno/zuultimate), which handles identity, authentication, and authorization. When a payment webhook arrives (Stripe or Polar), Vinzy-Engine creates the license and then provisions a tenant in Zuultimate via service token, returning credentials and an API key scoped to the customer's plan tier. The full integration contract is documented in [ZUULTIMATE_CONTRACT.md](docs/integration/ZUULTIMATE_CONTRACT.md). Vinzy-Engine degrades gracefully if Zuultimate is unreachable -- license creation proceeds, and tenant provisioning retries on the next opportunity.

## Capability Map

| Capability | Status |
|---|---|
| License Key Generation (HMAC) | GA |
| Entitlement Resolution | GA |
| Multi-License Composition | GA |
| Machine Activation | GA |
| Usage Metering | GA |
| Anomaly Detection | GA |
| Audit Trail (hash-chained) | GA |
| Webhook Dispatch | GA |
| Multi-Tenant Isolation | GA |
| Zuultimate Integration | GA |
| Admin Dashboard | GA |
| Stripe/Polar Webhooks | GA |

## Quickstart

```bash
# Install
pip install -e ".[dev]"

# Start the server
vinzy serve

# Create a product
curl -X POST http://localhost:8080/products \
  -H "X-Vinzy-Api-Key: $VINZY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"code": "PRD", "name": "My Product"}'

# Issue a license
curl -X POST http://localhost:8080/licenses \
  -H "X-Vinzy-Api-Key: $VINZY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"product_code": "PRD", "customer_id": "<customer-id>"}'

# Validate (public, no auth)
curl -X POST http://localhost:8080/validate \
  -H "Content-Type: application/json" \
  -d '{"key": "PRD-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX"}'
```

The admin dashboard is available at `http://localhost:8080/dashboard`.

## Key Format

```
{PRD}-{AAAAA}-{BBBBB}-{CCCCC}-{DDDDD}-{EEEEE}-{HHHHH}-{HHHHH}
  |     |                                         |
  |     +-- 5 random base32 segments               +-- 2 HMAC segments
  +-- 3-char product code
```

The first character of the first random segment encodes the HMAC key version (0-31), enabling seamless key rotation without invalidating existing keys.

## Testing

```bash
pytest tests/ -q
```

449 tests covering key generation, licensing, activation, usage, audit chain integrity, anomaly detection, webhooks, multi-tenancy, provisioning, and the admin dashboard.

## License

This project is dual-licensed:

- **AGPL-3.0** -- free for open-source use. See [LICENSE](LICENSE).
- **Commercial License** -- for proprietary use without AGPL obligations. See [COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md).

For commercial licensing inquiries, contact **info@1450enterprises.com**.

Copyright (c) 2025-2026 Chris Arsenault / 1450 Enterprises.
