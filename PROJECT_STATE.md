# Vinzy-Engine Project State

> Last Updated: 2026-03-05
> Current Phase: Production-ready, integrated into GozerAI stack

---

## Quick Context

Vinzy-Engine is the cryptographic license key generator, entitlement manager, and usage metering platform for the GozerAI ecosystem. It issues and validates license keys for all products (AGW/ZUL/VNZ/CSM/STD), enforces tier-based feature gates, tracks machine activations, and meters usage — all with a hash-chained audit trail and behavioral anomaly detection.

**Key format:** `{PRD}-{5x5 base32}-{2x5 HMAC}` with version byte encoding for HMAC key rotation.

**Architecture:**
- **FastAPI** application factory (`create_app()`) with async SQLAlchemy
- **Zuultimate integration** for tenant provisioning (graceful degradation)
- **Stripe/Polar** webhook handling for automated provisioning
- **Python SDK** (`LicenseClient`) with retry/backoff and offline validation
- **Admin dashboard** (Jinja2 + htmx + Pico CSS) at `/dashboard/`

---

## Implementation Status

### Core Modules (All Complete)

| Module | Purpose | Key Files |
|--------|---------|-----------|
| `common` | Config, database, auth, security, logging | `config.py`, `database.py`, `auth.py` |
| `keygen` | Key generation, HMAC validation, signed leases | `generator.py`, `validator.py` |
| `licensing` | Products, customers, licenses, entitlements, composition | `service.py`, `router.py`, `models.py` |
| `activation` | Machine activation and heartbeat | `service.py`, `router.py` |
| `usage` | Metered usage recording and aggregation | `service.py`, `router.py` |
| `audit` | Hash-chained cryptographic audit trail | `service.py`, `router.py` |
| `anomaly` | Z-score behavioral anomaly detection | `service.py`, `router.py` |
| `tenants` | Multi-tenant isolation and API key management | `service.py`, `router.py` |
| `webhooks` | Event dispatch with HMAC-signed deliveries | `service.py`, `router.py` |
| `provisioning` | Stripe/Polar webhooks, Zuultimate client, email | `service.py`, `router.py`, `zuultimate_client.py` |
| `dashboard` | Admin web UI | `router.py`, `auth.py`, `templates/` |

### Infrastructure

- [x] Rate limiting (`VINZY_RATE_LIMIT_ENABLED`, slowapi)
- [x] IP allowlist (`VINZY_IP_ALLOWLIST_ENABLED`)
- [x] HMAC key rotation (version-encoded keyring)
- [x] Alembic migrations (1 migration: initial schema)
- [x] DI singletons (`deps.py`) with `reset_singletons()` for testing
- [x] Tier templates: 5 products x 3 tiers (community/pro/enterprise)
- [x] Agent entitlement validation endpoint
- [x] Composition (cross-product entitlement)
- [x] Lease caching with offline TTL (72h default)

### Test Coverage

- **430+ tests** across 34 test files
- 20 unit test files in `tests/unit/`
- 8 integration test files in `tests/integration/`
- Benchmarks in `test_benchmarks.py`
- Dashboard tests in `test_dashboard.py`, `test_dashboard_auth.py`
- Run: `pytest tests/ -q` (asyncio_mode=auto)

---

## Directory Structure

```
F:\Projects\vinzy-engine\
├── src/vinzy_engine/
│   ├── common/          # Config, database, auth, security, logging
│   ├── keygen/          # Key generation, HMAC validation, leases
│   ├── licensing/       # Products, customers, licenses, entitlements
│   ├── activation/      # Machine activation, heartbeat
│   ├── usage/           # Metered usage recording
│   ├── audit/           # Hash-chained audit trail
│   ├── anomaly/         # Z-score anomaly detection
│   ├── tenants/         # Multi-tenant isolation
│   ├── webhooks/        # HMAC-signed event dispatch
│   ├── provisioning/    # Stripe/Polar, Zuultimate integration
│   ├── dashboard/       # Admin UI (Jinja2 + htmx)
│   ├── app.py           # FastAPI factory
│   ├── cli.py           # Typer CLI
│   ├── deps.py          # DI singletons
│   └── client.py        # Python SDK
├── tests/
│   ├── unit/            # 20 test files
│   ├── integration/     # 8 test files
│   └── conftest.py
├── alembic/             # Database migrations
├── Dockerfile
├── pyproject.toml
└── PROJECT_STATE.md     # This file
```

---

## API Endpoints

### Public (no auth)
- `GET /health` — service health
- `POST /validate` — key validation
- `POST /activate` — machine activation
- `POST /heartbeat` — activation heartbeat

### Admin (`VINZY_API_KEY`)
- `POST /products` — create product
- `POST /customers` — create customer
- `POST /licenses` — issue license
- `GET /licenses/{id}` — license details
- `GET /usage` — usage aggregation
- `GET /audit` — audit trail
- `GET /anomalies` — anomaly list
- `POST /webhooks` — register webhook

### Super Admin (`VINZY_SUPER_ADMIN_KEY`)
- `POST /tenants` — create tenant
- `GET /tenants` — list tenants
- `DELETE /tenants/{id}` — remove tenant

### Dashboard
- `/dashboard/` — admin web UI (cookie auth)

---

## CLI Commands

```bash
vinzy serve [--host 0.0.0.0] [--port 8080]   # Start API server
vinzy generate ZUL                             # Generate key offline
vinzy validate <key>                           # Validate key offline
vinzy health [--url http://localhost:8080]      # Check server health
```

---

## Key Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2025-12 | HMAC version byte in key | Enables key rotation without invalidating existing keys |
| 2026-01 | Fail-closed licensing | Community mode when unreachable, not open mode |
| 2026-01 | Zuultimate graceful degradation | Provisioning works even if Zuultimate is down |
| 2026-02 | Rate limiting + IP allowlist | Production hardening for public endpoints |
| 2026-02 | Default `api_prefix` is empty | Simpler routing, no `/api/v1` prefix |

---

## Blockers

None currently.
