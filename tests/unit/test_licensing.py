"""Tests for licensing service — create, validate, CRUD."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from vinzy_engine.common.config import VinzySettings
from vinzy_engine.common.exceptions import (
    InvalidKeyError,
    LicenseExpiredError,
    LicenseNotFoundError,
    LicenseSuspendedError,
)
from vinzy_engine.keygen.generator import generate_key, key_hash
from vinzy_engine.licensing.entitlements import resolve_entitlements
from vinzy_engine.licensing.models import (
    CustomerModel,
    EntitlementModel,
    LicenseModel,
    ProductModel,
)
from vinzy_engine.licensing.service import LicensingService


HMAC_KEY = "test-hmac-key-for-unit-tests"


def make_settings(**overrides) -> VinzySettings:
    defaults = {
        "hmac_key": HMAC_KEY,
        "db_url": "sqlite+aiosqlite://",
    }
    defaults.update(overrides)
    return VinzySettings(**defaults)


# ── Entitlement resolution ──


class TestResolveEntitlements:
    def test_product_features_only(self):
        result = resolve_entitlements(
            {"api_access": True, "exports": {"enabled": True, "limit": 100}},
            {},
        )
        assert len(result) == 2
        api = next(e for e in result if e["feature"] == "api_access")
        assert api["enabled"] is True

    def test_license_overrides(self):
        result = resolve_entitlements(
            {"exports": {"enabled": True, "limit": 100}},
            {"exports": {"enabled": True, "limit": 500}},
        )
        exports = result[0]
        assert exports["limit"] == 500

    def test_license_disables_feature(self):
        result = resolve_entitlements(
            {"advanced": True},
            {"advanced": {"enabled": False}},
        )
        assert result[0]["enabled"] is False

    def test_remaining_calculated(self):
        result = resolve_entitlements(
            {},
            {"tokens": {"enabled": True, "limit": 1000, "used": 300}},
        )
        assert result[0]["remaining"] == 700

    def test_no_limit_means_unlimited(self):
        result = resolve_entitlements(
            {"basic": True},
            {},
        )
        assert result[0]["remaining"] is None

    def test_empty_both(self):
        result = resolve_entitlements({}, {})
        assert result == []

    def test_bool_product_feature(self):
        result = resolve_entitlements({"feat": True}, {})
        assert result[0]["enabled"] is True

    def test_bool_license_override(self):
        result = resolve_entitlements({}, {"feat": False})
        assert result[0]["enabled"] is False


# ── Service with real DB ──


@pytest.fixture
async def db():
    """In-memory SQLite database for service tests."""
    from vinzy_engine.common.database import DatabaseManager

    settings = make_settings()
    manager = DatabaseManager(settings)
    await manager.init()
    await manager.create_all()
    yield manager
    await manager.close()


@pytest.fixture
def svc():
    return LicensingService(make_settings())


class TestLicensingServiceProducts:
    async def test_create_product(self, db, svc):
        async with db.get_session() as session:
            product = await svc.create_product(session, "ZUL", "Zuultimate")
            assert product.code == "ZUL"
            assert product.id is not None

    async def test_get_product_by_code(self, db, svc):
        async with db.get_session() as session:
            await svc.create_product(session, "ZUL", "Zuultimate")
        async with db.get_session() as session:
            found = await svc.get_product_by_code(session, "ZUL")
            assert found is not None
            assert found.name == "Zuultimate"

    async def test_get_product_not_found(self, db, svc):
        async with db.get_session() as session:
            found = await svc.get_product_by_code(session, "XXX")
            assert found is None

    async def test_list_products(self, db, svc):
        async with db.get_session() as session:
            await svc.create_product(session, "ZUL", "Zuultimate")
            await svc.create_product(session, "NXS", "Nexus")
        async with db.get_session() as session:
            products = await svc.list_products(session)
            assert len(products) == 2


class TestLicensingServiceCustomers:
    async def test_create_customer(self, db, svc):
        async with db.get_session() as session:
            customer = await svc.create_customer(
                session, "Test Corp", "test@example.com"
            )
            assert customer.email == "test@example.com"

    async def test_list_customers(self, db, svc):
        async with db.get_session() as session:
            await svc.create_customer(session, "A", "a@example.com")
            await svc.create_customer(session, "B", "b@example.com")
        async with db.get_session() as session:
            customers = await svc.list_customers(session)
            assert len(customers) == 2


class TestLicensingServiceLicenses:
    async def _setup(self, db, svc):
        async with db.get_session() as session:
            product = await svc.create_product(
                session, "ZUL", "Zuultimate", features={"api": True}
            )
            customer = await svc.create_customer(
                session, "Test", "test@example.com"
            )
        return product, customer

    async def test_create_license(self, db, svc):
        product, customer = await self._setup(db, svc)
        async with db.get_session() as session:
            lic, raw_key = await svc.create_license(
                session, "ZUL", customer.id
            )
            assert lic.status == "active"
            assert raw_key.startswith("ZUL-")

    async def test_get_license_by_key(self, db, svc):
        product, customer = await self._setup(db, svc)
        async with db.get_session() as session:
            lic, raw_key = await svc.create_license(
                session, "ZUL", customer.id
            )
        async with db.get_session() as session:
            found = await svc.get_license_by_key(session, raw_key)
            assert found is not None
            assert found.id == lic.id

    async def test_validate_license_ok(self, db, svc):
        product, customer = await self._setup(db, svc)
        async with db.get_session() as session:
            _, raw_key = await svc.create_license(session, "ZUL", customer.id)
        async with db.get_session() as session:
            result = await svc.validate_license(session, raw_key)
            assert result["valid"] is True
            assert result["code"] == "OK"

    async def test_validate_invalid_key(self, db, svc):
        with pytest.raises(InvalidKeyError):
            async with db.get_session() as session:
                await svc.validate_license(session, "bad-key")

    async def test_validate_not_found(self, db, svc):
        # Generate a valid key that's not in DB
        raw_key = generate_key("ZUL", HMAC_KEY)
        with pytest.raises(LicenseNotFoundError):
            async with db.get_session() as session:
                await svc.validate_license(session, raw_key)

    async def test_update_license(self, db, svc):
        product, customer = await self._setup(db, svc)
        async with db.get_session() as session:
            lic, _ = await svc.create_license(session, "ZUL", customer.id)
        async with db.get_session() as session:
            updated = await svc.update_license(
                session, lic.id, status="suspended"
            )
            assert updated.status == "suspended"

    async def test_soft_delete_license(self, db, svc):
        product, customer = await self._setup(db, svc)
        async with db.get_session() as session:
            lic, _ = await svc.create_license(session, "ZUL", customer.id)
        async with db.get_session() as session:
            await svc.soft_delete_license(session, lic.id)
        async with db.get_session() as session:
            found = await svc.get_license_by_id(session, lic.id)
            assert found is None  # soft-deleted, invisible


# ── Uniqueness + Tenant Isolation ──


class TestGlobalUniqueness:
    """Verify partial unique indexes enforce uniqueness when tenant_id IS NULL."""

    async def test_duplicate_product_code_rejected_global(self, db, svc):
        """Two products with same code and NULL tenant_id must fail."""
        from sqlalchemy.exc import IntegrityError

        async with db.get_session() as session:
            await svc.create_product(session, "ZUL", "Zuultimate")
        with pytest.raises(IntegrityError):
            async with db.get_session() as session:
                await svc.create_product(session, "ZUL", "Duplicate")

    async def test_duplicate_customer_email_rejected_global(self, db, svc):
        """Two customers with same email and NULL tenant_id must fail."""
        from sqlalchemy.exc import IntegrityError

        async with db.get_session() as session:
            await svc.create_customer(session, "A", "dup@test.com")
        with pytest.raises(IntegrityError):
            async with db.get_session() as session:
                await svc.create_customer(session, "B", "dup@test.com")

    async def test_same_code_different_tenants_ok(self, db, svc):
        """Same product code under different tenant_ids is allowed."""
        from vinzy_engine.tenants.service import TenantService

        tenant_svc = TenantService()
        async with db.get_session() as session:
            t1, _ = await tenant_svc.create_tenant(session, "T1", "t1")
            t2, _ = await tenant_svc.create_tenant(session, "T2", "t2")
        async with db.get_session() as session:
            p1 = await svc.create_product(session, "ZUL", "Z1", tenant_id=t1.id)
            p2 = await svc.create_product(session, "ZUL", "Z2", tenant_id=t2.id)
            assert p1.id != p2.id

    async def test_tenant_product_isolation(self, db, svc):
        """list_products with tenant_id only returns that tenant's products."""
        from vinzy_engine.tenants.service import TenantService

        tenant_svc = TenantService()
        async with db.get_session() as session:
            t1, _ = await tenant_svc.create_tenant(session, "T1", "t1")
        async with db.get_session() as session:
            await svc.create_product(session, "ZUL", "Global")
            await svc.create_product(session, "NXS", "Tenant", tenant_id=t1.id)
        async with db.get_session() as session:
            global_products = await svc.list_products(session)
            assert len(global_products) == 1
            assert global_products[0].code == "ZUL"
        async with db.get_session() as session:
            tenant_products = await svc.list_products(session, tenant_id=t1.id)
            assert len(tenant_products) == 1
            assert tenant_products[0].code == "NXS"

    async def test_tenant_license_isolation(self, db, svc):
        """list_licenses with tenant_id only returns that tenant's licenses."""
        from vinzy_engine.tenants.service import TenantService

        tenant_svc = TenantService()
        async with db.get_session() as session:
            t1, _ = await tenant_svc.create_tenant(session, "T1", "t1")

        # Global product + customer + license
        async with db.get_session() as session:
            await svc.create_product(session, "ZUL", "Global")
            c = await svc.create_customer(session, "C", "c@g.com")
        async with db.get_session() as session:
            await svc.create_license(session, "ZUL", c.id)

        # Tenant product + customer + license
        async with db.get_session() as session:
            await svc.create_product(session, "NXS", "Tenant", tenant_id=t1.id)
            ct = await svc.create_customer(session, "T", "t@t.com", tenant_id=t1.id)
        async with db.get_session() as session:
            await svc.create_license(session, "NXS", ct.id, tenant_id=t1.id)

        async with db.get_session() as session:
            global_lics, g_count = await svc.list_licenses(session)
            assert g_count == 1
        async with db.get_session() as session:
            tenant_lics, t_count = await svc.list_licenses(session, tenant_id=t1.id)
            assert t_count == 1


# ── Agent Entitlements via Validate ──


class TestAgentLicensing:
    async def test_validate_returns_agents(self, db, svc):
        async with db.get_session() as session:
            await svc.create_product(
                session, "ZUL", "Zuultimate",
                features={
                    "api": True,
                    "agents": {
                        "CTO": {"enabled": True, "token_limit": 50000, "model_tier": "premium"},
                        "CFO": {"enabled": True, "token_limit": 20000},
                    },
                },
            )
            customer = await svc.create_customer(session, "Test", "test@a.com")
        async with db.get_session() as session:
            _, raw_key = await svc.create_license(session, "ZUL", customer.id)
        async with db.get_session() as session:
            result = await svc.validate_license(session, raw_key)
            assert "agents" in result
            agents = {a["agent_code"]: a for a in result["agents"]}
            assert "CTO" in agents
            assert agents["CTO"]["token_limit"] == 50000
            assert agents["CTO"]["model_tier"] == "premium"
            assert agents["CFO"]["token_limit"] == 20000

    async def test_check_agent_entitlement(self, db, svc):
        async with db.get_session() as session:
            await svc.create_product(
                session, "ZUL", "Zuultimate",
                features={
                    "agents": {
                        "CTO": {"enabled": True, "token_limit": 50000},
                        "CSecO": {"enabled": False},
                    },
                },
            )
            customer = await svc.create_customer(session, "Test", "test@b.com")
        async with db.get_session() as session:
            _, raw_key = await svc.create_license(session, "ZUL", customer.id)
        async with db.get_session() as session:
            result = await svc.check_agent_entitlement(session, raw_key, "CTO")
            assert result["valid"] is True
            assert result["agent_code"] == "CTO"
            assert result["enabled"] is True
        async with db.get_session() as session:
            result = await svc.check_agent_entitlement(session, raw_key, "CSecO")
            assert result["valid"] is False
            assert result["code"] == "AGENT_NOT_ENTITLED"


class TestComposedEntitlements:
    async def test_get_composed_entitlements(self, db, svc):
        async with db.get_session() as session:
            await svc.create_product(
                session, "ZUL", "Zuultimate",
                features={"api": True, "agents": {"CTO": {"enabled": True, "token_limit": 50000}}},
            )
            await svc.create_product(
                session, "NXS", "Nexus",
                features={"api": True, "agents": {"CTO": {"enabled": True, "token_limit": 30000}}},
            )
            customer = await svc.create_customer(session, "Multi", "multi@test.com")
        async with db.get_session() as session:
            await svc.create_license(session, "ZUL", customer.id)
        async with db.get_session() as session:
            await svc.create_license(session, "NXS", customer.id)
        async with db.get_session() as session:
            result = await svc.get_composed_entitlements(session, customer.id)
            assert result["customer_id"] == customer.id
            assert result["total_products"] == 2
            assert "agents" in result
            assert result["agents"]["CTO"]["token_limit"] == 80000
