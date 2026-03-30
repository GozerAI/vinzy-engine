# Vinzy-Engine <-> Zuultimate Integration Contract v1.0

## Boundary Definition
- vinzy-engine: commercial licensing and entitlement control plane
- zuultimate: identity, policy, security, and governance platform
- vinzy-engine is a TENANT of zuultimate, not a dependent service

## Provisioning Flow
1. New customer onboards to vinzy-engine
2. vinzy-engine calls zuultimate POST /v1/tenants/provision
3. zuultimate returns opaque tenant_id
4. vinzy-engine stores tenant_id, uses for all subsequent identity calls
5. Identity operations (auth, policy, audit) route through zuultimate using tenant_id

## Failure Modes
- zuultimate unavailable: vinzy-engine queues provisioning, retries with backoff
- tenant_id not found: vinzy-engine treats as provisioning gap, re-provisions
- auth token expired: vinzy-engine uses service account refresh flow

## Data Boundary
- vinzy-engine NEVER sends PII to zuultimate
- zuultimate NEVER returns raw user identifiers to vinzy-engine
- All cross-service references use opaque UUIDs only

## Authentication
- Service-to-service: X-Service-Token header
- Per-tenant API keys: gzr_ prefix, validated via zuultimate auth/validate

## Versioning
- This contract follows semver
- Breaking changes require major version bump
- Both sides validate contract version on startup
