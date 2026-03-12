# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do not** open a public GitHub issue
2. Email: security@1450enterprises.com
3. Include a detailed description and steps to reproduce

### Response Timeline

- **48 hours**: Acknowledgment of your report
- **5 business days**: Initial assessment
- **30 days**: Target resolution for critical issues

## Security Architecture

Vinzy-Engine uses several cryptographic mechanisms:

- **HMAC-SHA256** key validation with versioned keyring rotation
- **Signed leases** for offline validation
- **API key authentication** on all admin endpoints
- **Super admin key** for tenant management
- **Anomaly detection** with z-score analysis

## Production Deployment Checklist

- [ ] Change all default keys (VINZY_SECRET_KEY, VINZY_HMAC_KEY, VINZY_API_KEY, VINZY_SUPER_ADMIN_KEY)
- [ ] Set VINZY_ENVIRONMENT=production
- [ ] Configure HMAC keyring for key rotation
- [ ] Use a production database (PostgreSQL recommended)
- [ ] Enable HTTPS termination
- [ ] Restrict CORS origins
