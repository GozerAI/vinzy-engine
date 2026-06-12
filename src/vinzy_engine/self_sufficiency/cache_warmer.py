"""License cache warming on startup.

Pre-loads frequently accessed licenses and tenant configurations
into the in-memory TTL cache to avoid cold-start latency."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vinzy_engine.activation.models import MachineModel
from vinzy_engine.common.caching import get_tenant_config_cache, get_validation_cache
from vinzy_engine.licensing.models import LicenseModel, ProductModel
from vinzy_engine.tenants.models import TenantModel

logger = logging.getLogger(__name__)


@dataclass
class CacheWarmResult:
    """Result of a cache warming operation."""
    licenses_warmed: int = 0
    tenants_warmed: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0

    @property
    def success(self) -> bool:
        return len(self.errors) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "licenses_warmed": self.licenses_warmed,
            "tenants_warmed": self.tenants_warmed,
            "errors": self.errors,
            "duration_ms": self.duration_ms,
            "success": self.success,
        }


class CacheWarmer:
    """Pre-loads license and tenant data into caches on startup."""

    def __init__(self, top_n: int = 1000):
        self._top_n = top_n
        self._last_warm: datetime | None = None

    @property
    def last_warm(self) -> datetime | None:
        return self._last_warm

    async def warm_licenses(self, session: AsyncSession) -> int:
        """Pre-load top N most-accessed licenses into the validation cache.

        Ranks licenses by activation count (machines_used) and caches
        a lightweight validation-ready dict for each."""
        cache = get_validation_cache()
        query = (
            select(LicenseModel)
            .where(LicenseModel.is_deleted == False, LicenseModel.status == "active")
            .order_by(LicenseModel.machines_used.desc())
            .limit(self._top_n)
        )
        result = await session.execute(query)
        licenses = list(result.scalars().all())
        warmed = 0
        for lic in licenses:
            product = await session.get(ProductModel, lic.product_id)
            product_code = product.code if product else ""
            cache_entry = {
                "valid": True,
                "license": {
                    "id": lic.id,
                    "status": lic.status,
                    "product_code": product_code,
                    "tier": lic.tier,
                    "machines_limit": lic.machines_limit,
                    "machines_used": lic.machines_used,
                    "expires_at": lic.expires_at,
                    "features": lic.features or {},
                },
            }
            cache.set(f"val:{lic.key_hash}", cache_entry)
            warmed += 1
        logger.info("Warmed %d licenses into validation cache", warmed)
        return warmed

    async def warm_tenants(self, session: AsyncSession) -> int:
        """Pre-load active tenant configurations into the tenant config cache."""
        cache = get_tenant_config_cache()
        result = await session.execute(select(TenantModel))
        tenants = list(result.scalars().all())
        warmed = 0
        for tenant in tenants:
            cache.set(tenant.id, {
                "id": tenant.id,
                "name": tenant.name,
                "slug": tenant.slug,
                "hmac_key_version": tenant.hmac_key_version,
                "config_overrides": tenant.config_overrides or {},
            })
            warmed += 1
        logger.info("Warmed %d tenants into config cache", warmed)
        return warmed

    async def warm_on_startup(self, session: AsyncSession) -> CacheWarmResult:
        """Run all warming tasks. Suitable for calling during app startup."""
        import time
        start = time.monotonic()
        result = CacheWarmResult()
        try:
            result.licenses_warmed = await self.warm_licenses(session)
        except Exception as exc:
            logger.exception("Failed to warm licenses")
            result.errors.append(f"licenses: {exc}")
        try:
            result.tenants_warmed = await self.warm_tenants(session)
        except Exception as exc:
            logger.exception("Failed to warm tenants")
            result.errors.append(f"tenants: {exc}")
        elapsed = (time.monotonic() - start) * 1000
        result.duration_ms = round(elapsed, 2)
        self._last_warm = datetime.now(timezone.utc)
        logger.info("Cache warming complete: %d licenses, %d tenants in %.1fms", result.licenses_warmed, result.tenants_warmed, elapsed)
        return result


_cache_warmer: CacheWarmer | None = None


def get_cache_warmer() -> CacheWarmer:
    """Get the singleton cache warmer."""
    global _cache_warmer
    if _cache_warmer is None:
        _cache_warmer = CacheWarmer()
    return _cache_warmer


def reset_cache_warmer() -> None:
    """Reset singleton (for testing)."""
    global _cache_warmer
    _cache_warmer = None
