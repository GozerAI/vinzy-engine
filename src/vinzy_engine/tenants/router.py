"""Tenant API router — requires super-admin authentication."""

from fastapi import APIRouter, Depends, HTTPException, Request

from vinzy_engine.common.security import require_super_admin, require_admin_ip
from vinzy_engine.common.rate_limiting import limiter, _admin_limit
from vinzy_engine.tenants.schemas import (
    TenantCreate,
    TenantCreateResponse,
    TenantResponse,
    TenantUpdate,
)

router = APIRouter(prefix="/tenants", tags=["tenants"])


def _get_service():
    from vinzy_engine.deps import get_tenant_service
    return get_tenant_service()


def _get_db():
    from vinzy_engine.deps import get_db
    return get_db()


@router.post("", response_model=TenantCreateResponse, status_code=201)
@limiter.limit(_admin_limit)
async def create_tenant(request: Request, body: TenantCreate, _=Depends(require_super_admin), __=Depends(require_admin_ip)):
    svc = _get_service()
    db = _get_db()
    async with db.get_session() as session:
        tenant, raw_key = await svc.create_tenant(
            session,
            name=body.name,
            slug=body.slug,
            hmac_key_version=body.hmac_key_version,
            config_overrides=body.config_overrides,
        )
        return TenantCreateResponse(
            id=tenant.id,
            name=tenant.name,
            slug=tenant.slug,
            hmac_key_version=tenant.hmac_key_version,
            config_overrides=tenant.config_overrides,
            created_at=tenant.created_at,
            api_key=raw_key,
        )


@router.get("", response_model=list[TenantResponse])
@limiter.limit(_admin_limit)
async def list_tenants(request: Request, _=Depends(require_super_admin), __=Depends(require_admin_ip)):
    svc = _get_service()
    db = _get_db()
    async with db.get_session() as session:
        tenants = await svc.list_tenants(session)
        return [
            TenantResponse(
                id=t.id, name=t.name, slug=t.slug,
                hmac_key_version=t.hmac_key_version,
                config_overrides=t.config_overrides,
                created_at=t.created_at,
            )
            for t in tenants
        ]


@router.get("/{tenant_id}", response_model=TenantResponse)
@limiter.limit(_admin_limit)
async def get_tenant(request: Request, tenant_id: str, _=Depends(require_super_admin), __=Depends(require_admin_ip)):
    svc = _get_service()
    db = _get_db()
    async with db.get_session() as session:
        tenant = await svc.get_by_id(session, tenant_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return TenantResponse(
            id=tenant.id, name=tenant.name, slug=tenant.slug,
            hmac_key_version=tenant.hmac_key_version,
            config_overrides=tenant.config_overrides,
            created_at=tenant.created_at,
        )


@router.patch("/{tenant_id}", response_model=TenantResponse)
@limiter.limit(_admin_limit)
async def update_tenant(
    request: Request, tenant_id: str, body: TenantUpdate, _=Depends(require_super_admin), __=Depends(require_admin_ip)
):
    svc = _get_service()
    db = _get_db()
    async with db.get_session() as session:
        tenant = await svc.update_tenant(
            session, tenant_id, **body.model_dump(exclude_none=True)
        )
        if tenant is None:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return TenantResponse(
            id=tenant.id, name=tenant.name, slug=tenant.slug,
            hmac_key_version=tenant.hmac_key_version,
            config_overrides=tenant.config_overrides,
            created_at=tenant.created_at,
        )


@router.delete("/{tenant_id}", status_code=204)
@limiter.limit(_admin_limit)
async def delete_tenant(request: Request, tenant_id: str, _=Depends(require_super_admin), __=Depends(require_admin_ip)):
    svc = _get_service()
    db = _get_db()
    async with db.get_session() as session:
        deleted = await svc.delete_tenant(session, tenant_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Tenant not found")
