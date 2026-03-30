"""Tenant CRUD service."""

import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vinzy_engine.common.caching import get_invalidation_bus, get_tenant_config_cache
from vinzy_engine.tenants.models import TenantModel


def _hash_api_key(raw_key: str) -> str:
    """SHA-256 hash of a raw API key for storage."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


class TenantService:
    """Tenant management operations."""

    async def create_tenant(
        self,
        session: AsyncSession,
        name: str,
        slug: str,
        hmac_key_version: int = 0,
        config_overrides: dict | None = None,
    ) -> tuple[TenantModel, str]:
        """Create a tenant and generate its API key. Returns (model, raw_api_key)."""
        raw_api_key = f"vzt_{secrets.token_urlsafe(32)}"
        tenant = TenantModel(
            name=name,
            slug=slug,
            api_key_hash=_hash_api_key(raw_api_key),
            hmac_key_version=hmac_key_version,
            config_overrides=config_overrides or {},
        )
        session.add(tenant)
        await session.flush()
        return tenant, raw_api_key

    async def get_by_api_key_hash(
        self, session: AsyncSession, api_key_hash: str
    ) -> TenantModel | None:
        result = await session.execute(
            select(TenantModel).where(TenantModel.api_key_hash == api_key_hash)
        )
        return result.scalar_one_or_none()

    async def get_by_slug(
        self, session: AsyncSession, slug: str
    ) -> TenantModel | None:
        result = await session.execute(
            select(TenantModel).where(TenantModel.slug == slug)
        )
        return result.scalar_one_or_none()

    async def get_by_id(
        self, session: AsyncSession, tenant_id: str
    ) -> TenantModel | None:
        # Check tenant config cache
        cache = get_tenant_config_cache()
        cached = cache.get(f"tenant:{tenant_id}")
        if cached is not None:
            return cached
        tenant = await session.get(TenantModel, tenant_id)
        if tenant is not None:
            cache.set(f"tenant:{tenant_id}", tenant)
        return tenant

    async def list_tenants(self, session: AsyncSession) -> list[TenantModel]:
        result = await session.execute(select(TenantModel))
        return list(result.scalars().all())

    async def update_tenant(
        self, session: AsyncSession, tenant_id: str, **updates
    ) -> TenantModel | None:
        tenant = await session.get(TenantModel, tenant_id)
        if tenant is None:
            return None
        for field in ("name", "hmac_key_version", "config_overrides"):
            if field in updates and updates[field] is not None:
                setattr(tenant, field, updates[field])
        await session.flush()
        # Invalidate tenant config cache via pub/sub
        bus = get_invalidation_bus()
        bus.publish("tenant", f"tenant:{tenant_id}")
        return tenant

    async def delete_tenant(
        self, session: AsyncSession, tenant_id: str
    ) -> bool:
        tenant = await session.get(TenantModel, tenant_id)
        if tenant is None:
            return False
        await session.delete(tenant)
        await session.flush()
        # Invalidate tenant config cache via pub/sub
        bus = get_invalidation_bus()
        bus.publish("tenant", f"tenant:{tenant_id}")
        return True

    async def resolve_by_raw_key(
        self, session: AsyncSession, raw_api_key: str
    ) -> TenantModel | None:
        """Resolve a tenant from a raw API key by hashing and looking up."""
        key_hash = _hash_api_key(raw_api_key)
        return await self.get_by_api_key_hash(session, key_hash)
