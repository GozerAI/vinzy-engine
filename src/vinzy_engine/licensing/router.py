"""Licensing API router."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from vinzy_engine.common.rate_limiting import limiter, _public_limit
from vinzy_engine.common.exceptions import (
    InvalidKeyError,
    LicenseExpiredError,
    LicenseNotFoundError,
    LicenseSuspendedError,
    VinzyError,
)
from vinzy_engine.common.security import require_api_key
from vinzy_engine.licensing.schemas import (
    AgentEntitlementResponse,
    AgentValidationRequest,
    AgentValidationResponse,
    ComposedEntitlementsResponse,
    CustomerCreate,
    CustomerResponse,
    LicenseCreate,
    LicenseResponse,
    LicenseSummary,
    LicenseUpdate,
    ProductCreate,
    ProductResponse,
    ValidationRequest,
    ValidationResponse,
)

router = APIRouter()


def _get_service():
    from vinzy_engine.deps import get_licensing_service
    return get_licensing_service()


def _get_db():
    from vinzy_engine.deps import get_db
    return get_db()


# ── Products ──

@router.post("/products", response_model=ProductResponse, status_code=201)
async def create_product(body: ProductCreate, _=Depends(require_api_key)):
    svc = _get_service()
    db = _get_db()
    async with db.get_session() as session:
        product = await svc.create_product(
            session, body.code, body.name,
            description=body.description,
            default_tier=body.default_tier,
            features=body.features,
            metadata=body.metadata,
        )
        return ProductResponse(
            id=product.id,
            code=product.code,
            name=product.name,
            description=product.description,
            default_tier=product.default_tier,
            features=product.features or {},
            metadata=product.metadata_ or {},
            created_at=product.created_at,
        )


@router.get("/products", response_model=list[ProductResponse])
async def list_products(_=Depends(require_api_key)):
    svc = _get_service()
    db = _get_db()
    async with db.get_session() as session:
        products = await svc.list_products(session)
        return [
            ProductResponse(
                id=p.id, code=p.code, name=p.name,
                description=p.description, default_tier=p.default_tier,
                features=p.features or {}, metadata=p.metadata_ or {},
                created_at=p.created_at,
            )
            for p in products
        ]


# ── Customers ──

@router.post("/customers", response_model=CustomerResponse, status_code=201)
async def create_customer(body: CustomerCreate, _=Depends(require_api_key)):
    svc = _get_service()
    db = _get_db()
    async with db.get_session() as session:
        customer = await svc.create_customer(
            session, body.name, body.email,
            company=body.company,
            metadata=body.metadata,
        )
        return CustomerResponse(
            id=customer.id, name=customer.name, email=customer.email,
            company=customer.company, metadata=customer.metadata_ or {},
            created_at=customer.created_at,
        )


@router.get("/customers", response_model=list[CustomerResponse])
async def list_customers(_=Depends(require_api_key)):
    svc = _get_service()
    db = _get_db()
    async with db.get_session() as session:
        customers = await svc.list_customers(session)
        return [
            CustomerResponse(
                id=c.id, name=c.name, email=c.email,
                company=c.company, metadata=c.metadata_ or {},
                created_at=c.created_at,
            )
            for c in customers
        ]


# ── Licenses ──

@router.post("/licenses", response_model=LicenseResponse, status_code=201)
async def create_license(body: LicenseCreate, _=Depends(require_api_key)):
    svc = _get_service()
    db = _get_db()
    try:
        async with db.get_session() as session:
            license_obj, raw_key = await svc.create_license(
                session,
                product_code=body.product_code,
                customer_id=body.customer_id,
                tier=body.tier,
                machines_limit=body.machines_limit,
                days_valid=body.days_valid,
                features=body.features,
                entitlements=body.entitlements,
                metadata=body.metadata,
            )
            # Load product code
            from vinzy_engine.licensing.models import ProductModel
            product = await session.get(ProductModel, license_obj.product_id)
            product_code = product.code if product else body.product_code

            return LicenseResponse(
                id=license_obj.id,
                key=raw_key,
                status=license_obj.status,
                product_code=product_code,
                customer_id=license_obj.customer_id,
                tier=license_obj.tier,
                machines_limit=license_obj.machines_limit,
                machines_used=license_obj.machines_used,
                expires_at=license_obj.expires_at,
                features=license_obj.features or {},
                entitlements=license_obj.entitlements or {},
                metadata=license_obj.metadata_ or {},
                created_at=license_obj.created_at,
            )
    except VinzyError as e:
        raise HTTPException(status_code=404, detail=e.message)


@router.get("/licenses", response_model=list[LicenseSummary])
async def list_licenses(
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _=Depends(require_api_key),
):
    svc = _get_service()
    db = _get_db()
    offset = (page - 1) * page_size
    async with db.get_session() as session:
        items, total = await svc.list_licenses(
            session, status=status, offset=offset, limit=page_size
        )
        result = []
        for lic in items:
            from vinzy_engine.licensing.models import ProductModel
            product = await session.get(ProductModel, lic.product_id)
            result.append(LicenseSummary(
                id=lic.id,
                status=lic.status,
                product_code=product.code if product else "",
                customer_id=lic.customer_id,
                tier=lic.tier,
                machines_used=lic.machines_used,
                machines_limit=lic.machines_limit,
                expires_at=lic.expires_at,
                created_at=lic.created_at,
            ))
        return result


@router.get("/licenses/{license_id}", response_model=LicenseSummary)
async def get_license(license_id: str, _=Depends(require_api_key)):
    svc = _get_service()
    db = _get_db()
    async with db.get_session() as session:
        lic = await svc.get_license_by_id(session, license_id)
        if lic is None:
            raise HTTPException(status_code=404, detail="License not found")
        from vinzy_engine.licensing.models import ProductModel
        product = await session.get(ProductModel, lic.product_id)
        return LicenseSummary(
            id=lic.id,
            status=lic.status,
            product_code=product.code if product else "",
            customer_id=lic.customer_id,
            tier=lic.tier,
            machines_used=lic.machines_used,
            machines_limit=lic.machines_limit,
            expires_at=lic.expires_at,
            created_at=lic.created_at,
        )


@router.patch("/licenses/{license_id}", response_model=LicenseSummary)
async def update_license(license_id: str, body: LicenseUpdate, _=Depends(require_api_key)):
    svc = _get_service()
    db = _get_db()
    try:
        async with db.get_session() as session:
            lic = await svc.update_license(
                session, license_id, **body.model_dump(exclude_none=True)
            )
            from vinzy_engine.licensing.models import ProductModel
            product = await session.get(ProductModel, lic.product_id)
            return LicenseSummary(
                id=lic.id,
                status=lic.status,
                product_code=product.code if product else "",
                customer_id=lic.customer_id,
                tier=lic.tier,
                machines_used=lic.machines_used,
                machines_limit=lic.machines_limit,
                expires_at=lic.expires_at,
                created_at=lic.created_at,
            )
    except LicenseNotFoundError:
        raise HTTPException(status_code=404, detail="License not found")


@router.delete("/licenses/{license_id}", status_code=204)
async def delete_license(license_id: str, _=Depends(require_api_key)):
    svc = _get_service()
    db = _get_db()
    try:
        async with db.get_session() as session:
            await svc.soft_delete_license(session, license_id)
    except LicenseNotFoundError:
        raise HTTPException(status_code=404, detail="License not found")


# ── Validation ──

@router.get("/validate", response_model=ValidationResponse, deprecated=True)
@limiter.limit(_public_limit)
async def validate_license_get(
    request: Request,
    key: str = Query(...),
    fingerprint: str | None = Query(None),
):
    """Validate a license key. Deprecated: use POST /validate instead to avoid leaking keys in logs."""
    svc = _get_service()
    db = _get_db()
    try:
        async with db.get_session() as session:
            result = await svc.validate_license(session, key, fingerprint)
            return result
    except InvalidKeyError as e:
        return ValidationResponse(valid=False, code=e.code, message=e.message)
    except LicenseNotFoundError as e:
        return ValidationResponse(valid=False, code=e.code, message=e.message)
    except LicenseExpiredError as e:
        return ValidationResponse(valid=False, code=e.code, message=e.message)
    except LicenseSuspendedError as e:
        return ValidationResponse(valid=False, code=e.code, message=e.message)


@router.post("/validate", response_model=ValidationResponse)
@limiter.limit(_public_limit)
async def validate_license(request: Request, body: ValidationRequest):
    """Validate a license key via POST body (preferred — avoids key leakage in logs)."""
    svc = _get_service()
    db = _get_db()
    try:
        async with db.get_session() as session:
            result = await svc.validate_license(session, body.key, body.fingerprint)
            return result
    except InvalidKeyError as e:
        return ValidationResponse(valid=False, code=e.code, message=e.message)
    except LicenseNotFoundError as e:
        return ValidationResponse(valid=False, code=e.code, message=e.message)
    except LicenseExpiredError as e:
        return ValidationResponse(valid=False, code=e.code, message=e.message)
    except LicenseSuspendedError as e:
        return ValidationResponse(valid=False, code=e.code, message=e.message)


# ── Agent Entitlements ──

@router.get("/licenses/{license_id}/agents", response_model=list[AgentEntitlementResponse])
async def list_entitled_agents(license_id: str, _=Depends(require_api_key)):
    svc = _get_service()
    db = _get_db()
    async with db.get_session() as session:
        lic = await svc.get_license_by_id(session, license_id)
        if lic is None:
            raise HTTPException(status_code=404, detail="License not found")
        from vinzy_engine.licensing.models import ProductModel
        product = await session.get(ProductModel, lic.product_id)
        product_features = product.features if product else {}
        from vinzy_engine.licensing.agent_entitlements import resolve_agent_entitlements
        agents = resolve_agent_entitlements(product_features, lic.entitlements or {})
        return [
            AgentEntitlementResponse(
                agent_code=ent.agent_code,
                enabled=ent.enabled,
                token_limit=ent.token_limit,
                model_tier=ent.model_tier,
            )
            for ent in agents.values()
        ]


@router.get("/validate/agent", response_model=AgentValidationResponse, deprecated=True)
async def validate_agent_get(
    key: str = Query(...),
    agent_code: str = Query(...),
):
    """Validate agent entitlement. Deprecated: use POST /validate/agent instead."""
    svc = _get_service()
    db = _get_db()
    try:
        async with db.get_session() as session:
            result = await svc.check_agent_entitlement(session, key, agent_code)
            return result
    except InvalidKeyError as e:
        return AgentValidationResponse(valid=False, code=e.code, message=e.message, agent_code=agent_code)
    except LicenseNotFoundError as e:
        return AgentValidationResponse(valid=False, code=e.code, message=e.message, agent_code=agent_code)
    except LicenseExpiredError as e:
        return AgentValidationResponse(valid=False, code=e.code, message=e.message, agent_code=agent_code)
    except LicenseSuspendedError as e:
        return AgentValidationResponse(valid=False, code=e.code, message=e.message, agent_code=agent_code)


@router.post("/validate/agent", response_model=AgentValidationResponse)
async def validate_agent(body: AgentValidationRequest):
    """Validate agent entitlement via POST body (preferred)."""
    svc = _get_service()
    db = _get_db()
    try:
        async with db.get_session() as session:
            result = await svc.check_agent_entitlement(session, body.key, body.agent_code)
            return result
    except InvalidKeyError as e:
        return AgentValidationResponse(valid=False, code=e.code, message=e.message, agent_code=body.agent_code)
    except LicenseNotFoundError as e:
        return AgentValidationResponse(valid=False, code=e.code, message=e.message, agent_code=body.agent_code)
    except LicenseExpiredError as e:
        return AgentValidationResponse(valid=False, code=e.code, message=e.message, agent_code=body.agent_code)
    except LicenseSuspendedError as e:
        return AgentValidationResponse(valid=False, code=e.code, message=e.message, agent_code=body.agent_code)


# ── Composition ──

@router.get("/entitlements/composed/{customer_id}", response_model=ComposedEntitlementsResponse)
async def get_composed_entitlements(customer_id: str, _=Depends(require_api_key)):
    svc = _get_service()
    db = _get_db()
    async with db.get_session() as session:
        result = await svc.get_composed_entitlements(session, customer_id)
        return result
