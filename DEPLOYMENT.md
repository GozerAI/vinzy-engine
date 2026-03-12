# Vinzy-Engine Deployment Guide

---

## Prerequisites

| Component | Version | Required | Notes |
|-----------|---------|----------|-------|
| Python | 3.11+ | Yes | 3.12 recommended |
| Docker / Docker Compose | 24+ / v2 | Optional | For containerized deployment |
| PostgreSQL | 16+ | Production | SQLite is the default for development |
| Stripe account | -- | Optional | For automated provisioning |

---

## Quick Start

### Local Development

```bash
cd vinzy-engine
pip install -e ".[dev]"

# Start with SQLite (default)
vinzy serve

# Or directly with uvicorn
uvicorn vinzy_engine.app:create_app --factory --host 127.0.0.1 --port 8080 --reload
```

Server starts at `http://localhost:8080` with:
- Health check at `/health`
- Admin dashboard at `/dashboard/`

### With GozerAI Docker Stack

Vinzy is included in the gozerai-infra `docker-compose.yml`:

```bash
cd gozerai-infra
docker compose up vinzy
```

Port mapping: `127.0.0.1:8001 → container:8080`

---

## Configuration Reference

All variables use the `VINZY_` prefix (pydantic-settings).

### Core

| Variable | Default | Description |
|----------|---------|-------------|
| `VINZY_ENVIRONMENT` | `development` | `development`, `testing`, `staging`, `production` |
| `VINZY_SECRET_KEY` | *(insecure)* | Session signing secret (**required** in production) |
| `VINZY_HMAC_KEY` | *(insecure)* | HMAC key for key generation (**required** in production) |
| `VINZY_HMAC_KEYS` | *(empty)* | JSON keyring for rotation: `{"0": "old-key", "1": "new-key"}` |

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `VINZY_DB_URL` | `sqlite+aiosqlite:///./data/vinzy.db` | Async database URL |

For production PostgreSQL:
```
VINZY_DB_URL=postgresql+asyncpg://vinzy:password@postgres:5432/vinzy
```

### API

| Variable | Default | Description |
|----------|---------|-------------|
| `VINZY_HOST` | `0.0.0.0` | Bind address |
| `VINZY_PORT` | `8080` | Bind port |
| `VINZY_API_KEY` | *(insecure)* | Admin API key (**required** in production) |
| `VINZY_SUPER_ADMIN_KEY` | *(insecure)* | Super-admin key (**required** in production) |
| `VINZY_API_PREFIX` | *(empty)* | URL prefix for all routes |
| `VINZY_CORS_ORIGINS` | `localhost:3000,8000` | Allowed CORS origins |

### Rate Limiting & Security

| Variable | Default | Description |
|----------|---------|-------------|
| `VINZY_RATE_LIMIT_ENABLED` | `true` | Enable rate limiting |
| `VINZY_RATE_LIMIT_PER_MINUTE` | `60` | Admin requests/min |
| `VINZY_RATE_LIMIT_PUBLIC_PER_MINUTE` | `30` | Public requests/min |
| `VINZY_IP_ALLOWLIST_ENABLED` | `false` | Enable IP allowlist |
| `VINZY_IP_ALLOWLIST` | *(empty)* | Allowed IP addresses |

### Licensing Defaults

| Variable | Default | Description |
|----------|---------|-------------|
| `VINZY_DEFAULT_MACHINES_LIMIT` | `3` | Max machines per license |
| `VINZY_DEFAULT_LICENSE_DAYS` | `365` | Default license duration |
| `VINZY_HEARTBEAT_INTERVAL` | `3600` | Heartbeat interval (seconds) |
| `VINZY_LEASE_TTL` | `86400` | Lease time-to-live (24h) |
| `VINZY_LEASE_OFFLINE_TTL` | `259200` | Offline lease TTL (72h) |

### Zuultimate Integration

| Variable | Default | Description |
|----------|---------|-------------|
| `VINZY_ZUULTIMATE_BASE_URL` | *(empty)* | Zuultimate service URL |
| `VINZY_ZUULTIMATE_SERVICE_TOKEN` | *(empty)* | Service-to-service auth token |

### Stripe Integration

| Variable | Default | Description |
|----------|---------|-------------|
| `VINZY_STRIPE_SECRET_KEY` | *(empty)* | Stripe secret key |
| `VINZY_STRIPE_WEBHOOK_SECRET` | *(empty)* | Stripe webhook signing secret |

---

## Docker Deployment

### Dockerfile

```dockerfile
FROM python:3.12-slim
# Installs with postgres + stripe extras
# Exposes port 8080
# CMD: uvicorn with factory pattern
```

### Health Check

```bash
curl -f http://localhost:8080/health
```

Returns:
```json
{"status": "ok", "version": "0.1.0"}
```

---

## Production Checklist

### Required Environment Variables

These **must** be changed from defaults in production:

| Variable | Why |
|----------|-----|
| `VINZY_SECRET_KEY` | Insecure default rejected in production |
| `VINZY_HMAC_KEY` | Insecure default rejected in production |
| `VINZY_API_KEY` | Admin access control |
| `VINZY_SUPER_ADMIN_KEY` | Tenant management access |
| `VINZY_DB_URL` | Use PostgreSQL, not SQLite |

Generate secrets: `python -c "import secrets; print(secrets.token_hex(32))"`

### Database Migrations

```bash
# Requires PYTHONPATH=src or editable install
cd vinzy-engine
PYTHONPATH=src alembic upgrade head
```

### Security Hardening

1. Set all secrets to strong random values
2. Enable rate limiting (on by default)
3. Consider enabling IP allowlist for admin endpoints
4. Run behind reverse proxy with TLS
5. Use PostgreSQL with strong credentials
6. Bind to `127.0.0.1` externally (Cloudflare tunnel handles external access)

---

## Troubleshooting

### Insecure Defaults Error

**Symptom:** Application refuses to start in production

**Solution:** Set `VINZY_SECRET_KEY`, `VINZY_HMAC_KEY`, `VINZY_API_KEY`, and `VINZY_SUPER_ADMIN_KEY` to strong random values.

### Alembic Import Error

**Symptom:** `ModuleNotFoundError: No module named 'vinzy_engine'`

**Solution:** Run with `PYTHONPATH=src` or install in editable mode (`pip install -e .`).

### Integration Tests Use Bare Paths

**Note:** Default `api_prefix` is empty string. Integration tests use bare paths like `/anomalies/`, not `/api/v1/anomalies/`.

---

## Port Map (GozerAI Stack)

| Service | External Port | Internal Port |
|---------|--------------|---------------|
| Zuultimate | 8000 | 8000 |
| **Vinzy** | **8001** | **8080** |
| Trendscope | 8002 | 8002 |
| ShopForge | 8003 | 8003 |
| BrandGuard | 8004 | 8004 |
| TaskPilot | 8005 | 8005 |
| Nexus | 8008 | 8080 |
| Sentinel | 8009 | 8080 |
| ShandorCode | 8010 | 8765 |
| Harvester | 8011 | 8011 |
| Web | 3000 | 3000 |
