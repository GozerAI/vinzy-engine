"""Licensing service — create, validate, CRUD operations."""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vinzy_engine.common.config import VinzySettings
from vinzy_engine.common.exceptions import (
    InvalidKeyError,
    LicenseExpiredError,
    LicenseNotFoundError,
    LicenseSuspendedError,
)
from vinzy_engine.keygen.generator import generate_key, key_hash
from vinzy_engine.keygen.lease import LeasePayload, create_lease
from vinzy_engine.keygen.validator import validate_key, validate_key_multi
from vinzy_engine.licensing.agent_entitlements import resolve_agent_entitlements
from vinzy_engine.licensing.entitlements import resolve_entitlements
from vinzy_engine.licensing.tier_templates import (
    get_machines_limit,
    resolve_tier_features,
)
from vinzy_engine.licensing.models import (
    CustomerModel,
    EntitlementModel,
    LicenseModel,
    ProductModel,
)


class LicensingService:
    """Core licensing operations."""

    def __init__(self, settings: VinzySettings, audit_service=None, webhook_service=None):
        self.settings = settings
        self.audit_service = audit_service
        self.webhook_service = webhook_service

    # ── Products ──

    async def create_product(
        self, session: AsyncSession, code: str, name: str,
        tenant_id: str | None = None, **kwargs: Any
    ) -> ProductModel:
        product = ProductModel(
            code=code.upper()[:3],
            name=name,
            tenant_id=tenant_id,
            description=kwargs.get("description", ""),
            default_tier=kwargs.get("default_tier", "standard"),
            features=kwargs.get("features", {}),
            metadata_=kwargs.get("metadata", {}),
        )
        session.add(product)
        await session.flush()
        return product

    async def get_product_by_code(
        self, session: AsyncSession, code: str,
        tenant_id: str | None = None,
    ) -> ProductModel | None:
        query = select(ProductModel).where(ProductModel.code == code.upper())
        if tenant_id is not None:
            query = query.where(ProductModel.tenant_id == tenant_id)
        else:
            query = query.where(ProductModel.tenant_id.is_(None))
        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def list_products(
        self, session: AsyncSession, tenant_id: str | None = None,
    ) -> list[ProductModel]:
        query = select(ProductModel)
        if tenant_id is not None:
            query = query.where(ProductModel.tenant_id == tenant_id)
        else:
            query = query.where(ProductModel.tenant_id.is_(None))
        result = await session.execute(query)
        return list(result.scalars().all())

    # ── Customers ──

    async def create_customer(
        self, session: AsyncSession, name: str, email: str,
        tenant_id: str | None = None, **kwargs: Any
    ) -> CustomerModel:
        customer = CustomerModel(
            name=name,
            email=email,
            tenant_id=tenant_id,
            company=kwargs.get("company", ""),
            metadata_=kwargs.get("metadata", {}),
        )
        session.add(customer)
        await session.flush()
        return customer

    async def get_customer(
        self, session: AsyncSession, customer_id: str,
        tenant_id: str | None = None,
    ) -> CustomerModel | None:
        query = select(CustomerModel).where(CustomerModel.id == customer_id)
        if tenant_id is not None:
            query = query.where(CustomerModel.tenant_id == tenant_id)
        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def list_customers(
        self, session: AsyncSession, tenant_id: str | None = None,
    ) -> list[CustomerModel]:
        query = select(CustomerModel)
        if tenant_id is not None:
            query = query.where(CustomerModel.tenant_id == tenant_id)
        else:
            query = query.where(CustomerModel.tenant_id.is_(None))
        result = await session.execute(query)
        return list(result.scalars().all())

    # ── Licenses ──

    async def create_license(
        self,
        session: AsyncSession,
        product_code: str,
        customer_id: str,
        tier: str = "standard",
        machines_limit: int | None = None,
        days_valid: int = 365,
        features: dict | None = None,
        entitlements: dict | None = None,
        metadata: dict | None = None,
        tenant_id: str | None = None,
    ) -> tuple[LicenseModel, str]:
        """Create a license and generate its key. Returns (model, raw_key).

        When tier is 'community', 'pro', or 'enterprise', the tier template
        features are auto-applied and merged with any explicit overrides.
        machines_limit defaults from the tier template if not specified.
        """
        product = await self.get_product_by_code(session, product_code, tenant_id=tenant_id)
        if product is None:
            raise LicenseNotFoundError(f"Product '{product_code}' not found")

        raw_key = generate_key(
            product_code,
            self.settings.current_hmac_key,
            version=self.settings.current_hmac_version,
        )
        hashed = key_hash(raw_key)

        expires_at = datetime.now(timezone.utc) + timedelta(days=days_valid)

        # Auto-apply tier template features when tier is recognized
        effective_features = {}
        try:
            template_features = resolve_tier_features(product_code, tier)
            effective_features.update(template_features)
        except ValueError:
            pass  # Unknown tier — skip template, use explicit features only
        if features:
            effective_features.update(features)

        # Default machines_limit from tier if not explicitly provided
        if machines_limit is None:
            try:
                machines_limit = get_machines_limit(tier)
            except (ValueError, KeyError):
                machines_limit = 3

        license_obj = LicenseModel(
            key_hash=hashed,
            status="active",
            tier=tier,
            tenant_id=tenant_id,
            product_id=product.id,
            customer_id=customer_id,
            machines_limit=machines_limit,
            machines_used=0,
            expires_at=expires_at,
            features=effective_features,
            entitlements=entitlements or {},
            metadata_=metadata or {},
        )
        session.add(license_obj)
        await session.flush()

        # Create entitlement rows from tier-resolved features
        resolved = resolve_entitlements(
            effective_features, license_obj.entitlements or {}
        )
        for ent in resolved:
            session.add(EntitlementModel(
                license_id=license_obj.id,
                feature=ent["feature"],
                enabled=ent["enabled"],
                limit=ent.get("limit"),
                used=ent.get("used", 0),
            ))
        await session.flush()

        # Audit: license.created
        if self.audit_service:
            await self.audit_service.record_event(
                session, license_obj.id, "license.created", "system",
                {"product_code": product_code, "tier": tier, "customer_id": customer_id},
            )

        # Webhook: license.created
        if self.webhook_service:
            await self.webhook_service.dispatch(
                session, "license.created",
                {"license_id": license_obj.id, "product_code": product_code,
                 "tier": tier, "customer_id": customer_id},
                tenant_id=tenant_id,
            )

        return license_obj, raw_key

    async def get_license_by_key(
        self, session: AsyncSession, raw_key: str
    ) -> LicenseModel | None:
        hashed = key_hash(raw_key)
        result = await session.execute(
            select(LicenseModel).where(
                LicenseModel.key_hash == hashed,
                LicenseModel.is_deleted == False,
            )
        )
        return result.scalar_one_or_none()

    async def get_license_by_id(
        self, session: AsyncSession, license_id: str
    ) -> LicenseModel | None:
        result = await session.execute(
            select(LicenseModel).where(
                LicenseModel.id == license_id,
                LicenseModel.is_deleted == False,
            )
        )
        return result.scalar_one_or_none()

    async def list_licenses(
        self,
        session: AsyncSession,
        status: str | None = None,
        product_code: str | None = None,
        offset: int = 0,
        limit: int = 20,
        tenant_id: str | None = None,
    ) -> tuple[list[LicenseModel], int]:
        """List licenses with optional filtering. Returns (items, total_count)."""
        base_filter = [LicenseModel.is_deleted == False]

        if tenant_id is not None:
            base_filter.append(LicenseModel.tenant_id == tenant_id)
        else:
            base_filter.append(LicenseModel.tenant_id.is_(None))

        if status:
            base_filter.append(LicenseModel.status == status)

        # Count total using func.count()
        count_result = await session.execute(
            select(func.count(LicenseModel.id)).where(*base_filter)
        )
        total = count_result.scalar() or 0

        # Fetch page
        query = select(LicenseModel).where(*base_filter).offset(offset).limit(limit)
        result = await session.execute(query)
        items = list(result.scalars().all())

        return items, total

    async def update_license(
        self, session: AsyncSession, license_id: str, **updates: Any
    ) -> LicenseModel:
        license_obj = await self.get_license_by_id(session, license_id)
        if license_obj is None:
            raise LicenseNotFoundError()

        for field in ("status", "tier", "machines_limit", "features", "entitlements", "metadata_"):
            key = field.rstrip("_")
            if key in updates and updates[key] is not None:
                attr = "metadata_" if key == "metadata" else key
                setattr(license_obj, attr, updates[key])

        await session.flush()

        # Audit: license.updated
        if self.audit_service:
            await self.audit_service.record_event(
                session, license_id, "license.updated", "system",
                {"fields": list(updates.keys())},
            )

        # Webhook: license.updated
        if self.webhook_service:
            await self.webhook_service.dispatch(
                session, "license.updated",
                {"license_id": license_id, "fields": list(updates.keys())},
            )

        return license_obj

    async def soft_delete_license(
        self, session: AsyncSession, license_id: str
    ) -> None:
        license_obj = await self.get_license_by_id(session, license_id)
        if license_obj is None:
            raise LicenseNotFoundError()
        license_obj.is_deleted = True
        license_obj.deleted_at = datetime.now(timezone.utc)
        await session.flush()

        # Audit: license.deleted
        if self.audit_service:
            await self.audit_service.record_event(
                session, license_id, "license.deleted", "system", {},
            )

        # Webhook: license.deleted
        if self.webhook_service:
            await self.webhook_service.dispatch(
                session, "license.deleted",
                {"license_id": license_id},
            )

    # ── Validation ──

    async def validate_license(
        self,
        session: AsyncSession,
        raw_key: str,
        fingerprint: str | None = None,
    ) -> dict:
        """
        Full server-side validation:
        1. Offline HMAC check
        2. DB lookup
        3. Status + expiry checks
        4. Resolve entitlements

        Returns a dict matching ValidationResponse shape.
        """
        # Step 1: Offline check (uses keyring for rotation support)
        offline = validate_key_multi(raw_key, self.settings.hmac_keyring)
        if not offline.valid:
            raise InvalidKeyError(offline.message)

        # Step 2: DB lookup
        license_obj = await self.get_license_by_key(session, raw_key)
        if license_obj is None:
            raise LicenseNotFoundError()

        # Step 3: Status check
        if license_obj.status == "suspended":
            raise LicenseSuspendedError()
        if license_obj.status == "revoked":
            raise LicenseSuspendedError("License has been revoked")
        if license_obj.status == "expired":
            raise LicenseExpiredError()

        # Expiry check — handle naive datetimes from SQLite
        now = datetime.now(timezone.utc)
        expires = license_obj.expires_at
        if expires and expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires and expires < now:
            license_obj.status = "expired"
            await session.flush()
            raise LicenseExpiredError()

        # Step 4: Load product for feature resolution
        product = await session.get(ProductModel, license_obj.product_id)
        product_code = product.code if product else ""
        product_features = product.features if product else {}

        # Use license-level features as the base when present (tier templates
        # populate these with the correct subset). Fall back to product features.
        base_features = license_obj.features if license_obj.features else product_features

        # Resolve entitlements
        resolved = resolve_entitlements(
            base_features, license_obj.entitlements or {}
        )
        feature_names = [e["feature"] for e in resolved if e["enabled"]]

        # Resolve agent entitlements
        agent_ents = resolve_agent_entitlements(
            base_features, license_obj.entitlements or {}
        )
        agents_list = [
            {
                "agent_code": ent.agent_code,
                "enabled": ent.enabled,
                "token_limit": ent.token_limit,
                "model_tier": ent.model_tier,
            }
            for ent in agent_ents.values()
        ]

        # Build signed lease
        expires_at = license_obj.expires_at
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        lease_payload = LeasePayload(
            license_id=license_obj.id,
            status=license_obj.status,
            features=feature_names,
            entitlements=resolved,
            tier=license_obj.tier,
            product_code=product_code,
            issued_at=now.isoformat(),
            expires_at=expires_at.isoformat() if expires_at else "",
        )
        lease = create_lease(
            lease_payload,
            self.settings.current_hmac_key,
            ttl_seconds=self.settings.lease_ttl,
        )

        # Audit: license.validated
        if self.audit_service:
            await self.audit_service.record_event(
                session, license_obj.id, "license.validated", "system",
                {"product_code": product_code, "fingerprint": fingerprint or ""},
            )

        # Webhook: license.validated
        if self.webhook_service:
            await self.webhook_service.dispatch(
                session, "license.validated",
                {"license_id": license_obj.id, "product_code": product_code},
            )

        return {
            "valid": True,
            "code": "OK",
            "message": "License is valid",
            "license": {
                "id": license_obj.id,
                "key": raw_key,
                "status": license_obj.status,
                "product_code": product_code,
                "customer_id": license_obj.customer_id,
                "tier": license_obj.tier,
                "machines_limit": license_obj.machines_limit,
                "machines_used": license_obj.machines_used,
                "expires_at": license_obj.expires_at,
                "features": feature_names,
                "entitlements": license_obj.entitlements or {},
                "metadata": license_obj.metadata_ or {},
            },
            "features": feature_names,
            "entitlements": resolved,
            "agents": agents_list,
            "lease": lease,
        }

    async def check_agent_entitlement(
        self,
        session: AsyncSession,
        raw_key: str,
        agent_code: str,
    ) -> dict:
        """Validate a license and check entitlement for a specific agent."""
        result = await self.validate_license(session, raw_key)

        # validate_license already resolved agents — look up in result
        agent = None
        for a in result.get("agents", []):
            if a["agent_code"] == agent_code:
                agent = a
                break

        entitled = agent is not None and agent.get("enabled", False)

        return {
            "valid": result["valid"] and entitled,
            "code": "OK" if entitled else "AGENT_NOT_ENTITLED",
            "message": (
                f"Agent {agent_code} is entitled"
                if entitled
                else f"Agent {agent_code} is not entitled"
            ),
            "agent_code": agent_code,
            "enabled": entitled,
            "token_limit": agent["token_limit"] if agent else None,
            "model_tier": agent["model_tier"] if agent else None,
        }

    # ── Composition ──

    async def get_composed_entitlements(
        self,
        session: AsyncSession,
        customer_id: str,
        tenant_id: str | None = None,
    ) -> dict:
        """Compose entitlements across all active licenses for a customer."""
        from vinzy_engine.licensing.composition import compose_customer_entitlements

        query = select(LicenseModel).where(
            LicenseModel.customer_id == customer_id,
            LicenseModel.status == "active",
            LicenseModel.is_deleted == False,
        )
        if tenant_id is not None:
            query = query.where(LicenseModel.tenant_id == tenant_id)
        else:
            query = query.where(LicenseModel.tenant_id.is_(None))

        result = await session.execute(query)
        licenses = list(result.scalars().all())

        # Load all referenced products
        product_ids = {lic.product_id for lic in licenses}
        products = []
        for pid in product_ids:
            p = await session.get(ProductModel, pid)
            if p:
                products.append(p)

        composed = compose_customer_entitlements(licenses, products)

        return {
            "customer_id": customer_id,
            "total_products": composed.total_products,
            "features": [
                {
                    "feature": f.feature,
                    "effective_value": f.effective_value,
                    "strategy": f.strategy,
                    "sources": [
                        {"product_code": s.product_code, "license_id": s.license_id, "value": s.value}
                        for s in f.sources
                    ],
                }
                for f in composed.features
            ],
            "agents": composed.agents,
        }
