"""API key authentication dependencies."""

import hmac
import ipaddress
from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException, Request


@dataclass
class TenantContext:
    """Resolved tenant info available to request handlers."""
    tenant_id: Optional[str] = None
    tenant_slug: Optional[str] = None


async def require_api_key(
    x_vinzy_api_key: str = Header(..., alias="X-Vinzy-Api-Key"),
) -> str:
    """FastAPI dependency that validates admin API key from header."""
    from vinzy_engine.common.config import get_settings

    settings = get_settings()
    if not hmac.compare_digest(x_vinzy_api_key, settings.api_key):
        raise HTTPException(status_code=403, detail="Invalid API key")
    return x_vinzy_api_key


async def require_super_admin(
    x_vinzy_api_key: str = Header(..., alias="X-Vinzy-Api-Key"),
) -> str:
    """FastAPI dependency that validates super-admin API key from header."""
    from vinzy_engine.common.config import get_settings

    settings = get_settings()
    if not hmac.compare_digest(x_vinzy_api_key, settings.super_admin_key):
        raise HTTPException(status_code=403, detail="Invalid super-admin key")
    return x_vinzy_api_key


async def require_admin_ip(request: Request) -> str:
    """FastAPI dependency that enforces admin IP allowlist.

    When VINZY_ADMIN_IP_ALLOWLIST is set, only listed IPs can access
    admin endpoints. Localhost is always allowed. When empty, all IPs pass.
    """
    from vinzy_engine.common.config import get_settings

    settings = get_settings()
    allowlist = settings.admin_ip_allowlist
    if not allowlist:
        return ""  # No restriction

    client_ip = request.client.host if request.client else "127.0.0.1"
    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid client IP")

    # Always allow localhost
    if addr in ipaddress.ip_network("127.0.0.1/32") or addr in ipaddress.ip_network("::1/128"):
        return client_ip

    for entry in allowlist:
        try:
            if addr in ipaddress.ip_network(entry, strict=False):
                return client_ip
        except ValueError:
            continue

    raise HTTPException(status_code=403, detail=f"IP {client_ip} not in admin allowlist")


async def resolve_tenant(
    x_vinzy_api_key: str = Header(None, alias="X-Vinzy-Api-Key"),
) -> TenantContext:
    """FastAPI dependency that optionally resolves a tenant from API key.

    Returns TenantContext with tenant_id set if a matching tenant is found,
    or empty TenantContext for library/single-tenant mode.
    """
    if not x_vinzy_api_key:
        return TenantContext()

    from vinzy_engine.deps import get_db, get_tenant_service
    svc = get_tenant_service()
    db = get_db()
    async with db.get_session() as session:
        tenant = await svc.resolve_by_raw_key(session, x_vinzy_api_key)
        if tenant:
            return TenantContext(
                tenant_id=tenant.id,
                tenant_slug=tenant.slug,
            )
    return TenantContext()
