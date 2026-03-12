# Commercial Licensing — vinzy-engine

This project is dual-licensed:

- **AGPL-3.0** — Free for open-source use with copyleft obligations
- **Commercial License** — Proprietary use without AGPL requirements

## Tiers

| Feature | Community (Free) | Pro ($149/mo) | Enterprise ($499/mo) |
|---------|:---:|:---:|:---:|
| Key generation & validation | Yes | Yes | Yes |
| Activation & heartbeat | Yes | Yes | Yes |
| Versioned HMAC Keyring | — | Yes | Yes |
| Cross-product Composition | — | Yes | Yes |
| Anomaly Detection | — | Yes | Yes |
| Agent Entitlements | — | — | Yes |
| Signed Leases | — | — | Yes |
| Cryptographic Audit Chain | — | — | Yes |
| Multi-tenancy | — | — | Yes |
| Support SLA | Community | 48h email | 4h priority |

## Getting a License

Visit **https://1450enterprises.com/pricing** or contact sales@1450enterprises.com.

```bash
export VINZY_LICENSE_KEY="your-key-here"
export VINZY_SERVER="https://api.1450enterprises.com"
```

## Feature Flags

| Flag | Tier |
|------|------|
| `vnz.hmac.keyring` | Pro |
| `vnz.hmac.rotation` | Pro |
| `vnz.composition.cross_product` | Pro |
| `vnz.anomaly.detection` | Pro |
| `vnz.agents.entitlements` | Enterprise |
| `vnz.agents.leases` | Enterprise |
| `vnz.audit.chain` | Enterprise |
| `vnz.tenants.multi` | Enterprise |
