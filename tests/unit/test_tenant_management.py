"""Comprehensive tests for the tenant management module — CRUD, lookups,
API key handling, config overrides, and edge cases."""

import pytest

from vinzy_engine.common.config import VinzySettings
from vinzy_engine.common.database import DatabaseManager
from vinzy_engine.tenants.models import TenantModel
from vinzy_engine.tenants.schemas import (
    TenantCreate,
    TenantCreateResponse,
    TenantResponse,
    TenantUpdate,
)
from vinzy_engine.tenants.service import TenantService, _hash_api_key


HMAC_KEY = "test-hmac-key-for-unit-tests"


def make_settings(**overrides) -> VinzySettings:
    defaults = {"hmac_key": HMAC_KEY, "db_url": "sqlite+aiosqlite://"}
    defaults.update(overrides)
    return VinzySettings(**defaults)


@pytest.fixture
async def db():
    settings = make_settings()
    manager = DatabaseManager(settings)
    await manager.init()
    await manager.create_all()
    yield manager
    await manager.close()


@pytest.fixture
def svc():
    return TenantService()


# ── Create Tenant ──


class TestCreateTenant:
    """Test tenant creation."""

    async def test_create_tenant_basic(self, db, svc):
        async with db.get_session() as session:
            tenant, raw_key = await svc.create_tenant(
                session, name="Acme Corp", slug="acme"
            )
            assert tenant.name == "Acme Corp"
            assert tenant.slug == "acme"
            assert tenant.id is not None
            assert raw_key.startswith("vzt_")

    async def test_create_tenant_with_config_overrides(self, db, svc):
        config = {"max_licenses": 100, "feature_flags": {"beta": True}}
        async with db.get_session() as session:
            tenant, _ = await svc.create_tenant(
                session, name="Beta Corp", slug="beta",
                config_overrides=config,
            )
            assert tenant.config_overrides == config
            assert tenant.config_overrides["max_licenses"] == 100

    async def test_create_tenant_with_hmac_version(self, db, svc):
        async with db.get_session() as session:
            tenant, _ = await svc.create_tenant(
                session, name="Versioned", slug="versioned",
                hmac_key_version=5,
            )
            assert tenant.hmac_key_version == 5

    async def test_create_tenant_default_hmac_version(self, db, svc):
        async with db.get_session() as session:
            tenant, _ = await svc.create_tenant(
                session, name="Default", slug="default"
            )
            assert tenant.hmac_key_version == 0

    async def test_create_tenant_default_config_overrides(self, db, svc):
        async with db.get_session() as session:
            tenant, _ = await svc.create_tenant(
                session, name="NoConfig", slug="noconfig"
            )
            assert tenant.config_overrides == {}

    async def test_api_key_hash_stored_correctly(self, db, svc):
        async with db.get_session() as session:
            tenant, raw_key = await svc.create_tenant(
                session, name="Hash Test", slug="hashtest"
            )
            expected_hash = _hash_api_key(raw_key)
            assert tenant.api_key_hash == expected_hash

    async def test_api_key_prefix(self, db, svc):
        async with db.get_session() as session:
            _, raw_key = await svc.create_tenant(
                session, name="Prefix", slug="prefix"
            )
            assert raw_key.startswith("vzt_")

    async def test_api_keys_are_unique(self, db, svc):
        keys = []
        for i in range(5):
            async with db.get_session() as session:
                _, raw_key = await svc.create_tenant(
                    session, name=f"Tenant {i}", slug=f"tenant-{i}"
                )
                keys.append(raw_key)
        assert len(set(keys)) == 5  # all unique

    async def test_tenant_id_is_uuid(self, db, svc):
        async with db.get_session() as session:
            tenant, _ = await svc.create_tenant(
                session, name="UUID", slug="uuid-test"
            )
            assert len(tenant.id) == 36
            assert tenant.id.count("-") == 4


# ── Get Tenant by ID ──


class TestGetTenantById:
    """Test retrieving tenants by ID."""

    async def test_get_existing_tenant(self, db, svc):
        async with db.get_session() as session:
            tenant, _ = await svc.create_tenant(
                session, name="FindMe", slug="findme"
            )
        async with db.get_session() as session:
            found = await svc.get_by_id(session, tenant.id)
            assert found is not None
            assert found.name == "FindMe"
            assert found.slug == "findme"

    async def test_get_nonexistent_tenant(self, db, svc):
        async with db.get_session() as session:
            found = await svc.get_by_id(session, "nonexistent-id")
            assert found is None

    async def test_get_preserves_all_fields(self, db, svc):
        config = {"key": "value"}
        async with db.get_session() as session:
            tenant, raw_key = await svc.create_tenant(
                session, name="Full", slug="full",
                hmac_key_version=3, config_overrides=config,
            )
        async with db.get_session() as session:
            found = await svc.get_by_id(session, tenant.id)
            assert found.name == "Full"
            assert found.slug == "full"
            assert found.hmac_key_version == 3
            assert found.config_overrides == config


# ── Update Tenant Details ──


class TestUpdateTenantDetails:
    """Test updating tenant fields."""

    async def test_update_name(self, db, svc):
        async with db.get_session() as session:
            tenant, _ = await svc.create_tenant(
                session, name="Old Name", slug="update-name"
            )
        async with db.get_session() as session:
            updated = await svc.update_tenant(session, tenant.id, name="New Name")
            assert updated is not None
            assert updated.name == "New Name"

    async def test_update_hmac_version(self, db, svc):
        async with db.get_session() as session:
            tenant, _ = await svc.create_tenant(
                session, name="HMAC", slug="hmac-update"
            )
        async with db.get_session() as session:
            updated = await svc.update_tenant(
                session, tenant.id, hmac_key_version=7
            )
            assert updated.hmac_key_version == 7

    async def test_update_config_overrides(self, db, svc):
        async with db.get_session() as session:
            tenant, _ = await svc.create_tenant(
                session, name="Config", slug="config-update"
            )
        new_config = {"max_licenses": 200, "plan": "enterprise"}
        async with db.get_session() as session:
            updated = await svc.update_tenant(
                session, tenant.id, config_overrides=new_config
            )
            assert updated.config_overrides == new_config

    async def test_update_nonexistent_returns_none(self, db, svc):
        async with db.get_session() as session:
            result = await svc.update_tenant(session, "no-id", name="X")
            assert result is None

    async def test_update_preserves_unchanged_fields(self, db, svc):
        async with db.get_session() as session:
            tenant, _ = await svc.create_tenant(
                session, name="Original", slug="preserve",
                hmac_key_version=2,
                config_overrides={"key": "val"},
            )
        async with db.get_session() as session:
            updated = await svc.update_tenant(session, tenant.id, name="Changed")
            assert updated.name == "Changed"
            assert updated.hmac_key_version == 2
            assert updated.config_overrides == {"key": "val"}

    async def test_update_multiple_fields(self, db, svc):
        async with db.get_session() as session:
            tenant, _ = await svc.create_tenant(
                session, name="Multi", slug="multi-update"
            )
        async with db.get_session() as session:
            updated = await svc.update_tenant(
                session, tenant.id,
                name="Updated Multi",
                hmac_key_version=10,
                config_overrides={"plan": "pro"},
            )
            assert updated.name == "Updated Multi"
            assert updated.hmac_key_version == 10
            assert updated.config_overrides == {"plan": "pro"}


# ── Tenant with Multiple Licenses ──


class TestTenantWithLicenses:
    """Test tenant integration with the licensing system."""

    async def test_tenant_can_have_licenses(self, db, svc):
        from vinzy_engine.licensing.service import LicensingService

        licensing_svc = LicensingService(make_settings())
        async with db.get_session() as session:
            tenant, _ = await svc.create_tenant(
                session, name="Licensed Corp", slug="licensed"
            )
        async with db.get_session() as session:
            await licensing_svc.create_product(
                session, "ZUL", "Zuultimate", tenant_id=tenant.id
            )
            customer = await licensing_svc.create_customer(
                session, "Customer", "cust@example.com", tenant_id=tenant.id,
            )
        async with db.get_session() as session:
            lic1, _ = await licensing_svc.create_license(
                session, "ZUL", customer.id, tenant_id=tenant.id,
            )
            lic2, _ = await licensing_svc.create_license(
                session, "ZUL", customer.id, tenant_id=tenant.id,
            )
            assert lic1.tenant_id == tenant.id
            assert lic2.tenant_id == tenant.id


# ── Tenant Plan Assignment (Config Overrides) ──


class TestTenantPlanAssignment:
    """Test using config_overrides as plan storage."""

    async def test_assign_starter_plan(self, db, svc):
        async with db.get_session() as session:
            tenant, _ = await svc.create_tenant(
                session, name="Starter", slug="starter",
                config_overrides={"plan": "starter", "max_licenses": 5},
            )
            assert tenant.config_overrides["plan"] == "starter"
            assert tenant.config_overrides["max_licenses"] == 5

    async def test_plan_upgrade(self, db, svc):
        async with db.get_session() as session:
            tenant, _ = await svc.create_tenant(
                session, name="Upgrade", slug="upgrade",
                config_overrides={"plan": "starter", "max_licenses": 5},
            )
        async with db.get_session() as session:
            updated = await svc.update_tenant(
                session, tenant.id,
                config_overrides={"plan": "pro", "max_licenses": 50},
            )
            assert updated.config_overrides["plan"] == "pro"
            assert updated.config_overrides["max_licenses"] == 50

    async def test_plan_downgrade(self, db, svc):
        async with db.get_session() as session:
            tenant, _ = await svc.create_tenant(
                session, name="Downgrade", slug="downgrade",
                config_overrides={"plan": "enterprise", "max_licenses": 999},
            )
        async with db.get_session() as session:
            updated = await svc.update_tenant(
                session, tenant.id,
                config_overrides={"plan": "starter", "max_licenses": 5},
            )
            assert updated.config_overrides["plan"] == "starter"
            assert updated.config_overrides["max_licenses"] == 5


# ── Tenant Deactivation / Reactivation ──


class TestTenantDeactivation:
    """Test tenant deactivation via delete and recreation patterns."""

    async def test_delete_tenant(self, db, svc):
        async with db.get_session() as session:
            tenant, _ = await svc.create_tenant(
                session, name="Deactivate", slug="deactivate"
            )
        async with db.get_session() as session:
            deleted = await svc.delete_tenant(session, tenant.id)
            assert deleted is True
        async with db.get_session() as session:
            found = await svc.get_by_id(session, tenant.id)
            assert found is None

    async def test_delete_nonexistent_returns_false(self, db, svc):
        async with db.get_session() as session:
            result = await svc.delete_tenant(session, "nonexistent")
            assert result is False

    async def test_slug_available_after_delete(self, db, svc):
        async with db.get_session() as session:
            tenant, _ = await svc.create_tenant(
                session, name="Reuse", slug="reuse-slug"
            )
        async with db.get_session() as session:
            await svc.delete_tenant(session, tenant.id)
        async with db.get_session() as session:
            new_tenant, _ = await svc.create_tenant(
                session, name="Reuse 2", slug="reuse-slug"
            )
            assert new_tenant.name == "Reuse 2"
            assert new_tenant.slug == "reuse-slug"


# ── List Tenants with Pagination ──


class TestListTenants:
    """Test listing tenants."""

    async def test_list_empty(self, db, svc):
        async with db.get_session() as session:
            tenants = await svc.list_tenants(session)
            assert tenants == []

    async def test_list_multiple(self, db, svc):
        async with db.get_session() as session:
            await svc.create_tenant(session, name="A", slug="a")
            await svc.create_tenant(session, name="B", slug="b")
            await svc.create_tenant(session, name="C", slug="c")
        async with db.get_session() as session:
            tenants = await svc.list_tenants(session)
            assert len(tenants) == 3
            names = {t.name for t in tenants}
            assert names == {"A", "B", "C"}

    async def test_list_after_delete(self, db, svc):
        async with db.get_session() as session:
            t1, _ = await svc.create_tenant(session, name="Keep", slug="keep")
            t2, _ = await svc.create_tenant(session, name="Remove", slug="remove")
        async with db.get_session() as session:
            await svc.delete_tenant(session, t2.id)
        async with db.get_session() as session:
            tenants = await svc.list_tenants(session)
            assert len(tenants) == 1
            assert tenants[0].name == "Keep"


# ── Search Tenants by Name/Slug ──


class TestSearchTenants:
    """Test finding tenants by slug and resolving by API key."""

    async def test_get_by_slug(self, db, svc):
        async with db.get_session() as session:
            await svc.create_tenant(session, name="Alpha Corp", slug="alpha")
        async with db.get_session() as session:
            found = await svc.get_by_slug(session, "alpha")
            assert found is not None
            assert found.name == "Alpha Corp"

    async def test_get_by_slug_not_found(self, db, svc):
        async with db.get_session() as session:
            found = await svc.get_by_slug(session, "nonexistent")
            assert found is None

    async def test_get_by_slug_case_sensitive(self, db, svc):
        async with db.get_session() as session:
            await svc.create_tenant(session, name="Case", slug="case-test")
        async with db.get_session() as session:
            found_lower = await svc.get_by_slug(session, "case-test")
            found_upper = await svc.get_by_slug(session, "Case-Test")
            assert found_lower is not None
            assert found_upper is None  # slugs are case-sensitive

    async def test_resolve_by_raw_key(self, db, svc):
        async with db.get_session() as session:
            tenant, raw_key = await svc.create_tenant(
                session, name="Resolve", slug="resolve"
            )
        async with db.get_session() as session:
            found = await svc.resolve_by_raw_key(session, raw_key)
            assert found is not None
            assert found.id == tenant.id

    async def test_resolve_by_wrong_key(self, db, svc):
        async with db.get_session() as session:
            found = await svc.resolve_by_raw_key(session, "vzt_wrong_key")
            assert found is None

    async def test_get_by_api_key_hash(self, db, svc):
        async with db.get_session() as session:
            tenant, raw_key = await svc.create_tenant(
                session, name="Hash Lookup", slug="hash-lookup"
            )
        key_hash = _hash_api_key(raw_key)
        async with db.get_session() as session:
            found = await svc.get_by_api_key_hash(session, key_hash)
            assert found is not None
            assert found.id == tenant.id


# ── Tenant Metadata Storage ──


class TestTenantMetadata:
    """Test config_overrides as metadata storage."""

    async def test_empty_config_overrides(self, db, svc):
        async with db.get_session() as session:
            tenant, _ = await svc.create_tenant(
                session, name="Empty", slug="empty-meta"
            )
            assert tenant.config_overrides == {}

    async def test_nested_config_overrides(self, db, svc):
        config = {
            "plan": "enterprise",
            "limits": {"licenses": 100, "api_calls": 10000},
            "features": {"sso": True, "audit_log": True},
            "tags": ["premium", "priority-support"],
        }
        async with db.get_session() as session:
            tenant, _ = await svc.create_tenant(
                session, name="Nested", slug="nested-meta",
                config_overrides=config,
            )
            assert tenant.config_overrides["limits"]["licenses"] == 100
            assert tenant.config_overrides["features"]["sso"] is True
            assert "premium" in tenant.config_overrides["tags"]

    async def test_update_preserves_nested_config(self, db, svc):
        config = {"plan": "starter", "limits": {"licenses": 5}}
        async with db.get_session() as session:
            tenant, _ = await svc.create_tenant(
                session, name="Preserve", slug="preserve-meta",
                config_overrides=config,
            )
        async with db.get_session() as session:
            updated = await svc.update_tenant(session, tenant.id, name="Updated")
            assert updated.config_overrides == config

    async def test_replace_config_overrides(self, db, svc):
        async with db.get_session() as session:
            tenant, _ = await svc.create_tenant(
                session, name="Replace", slug="replace-meta",
                config_overrides={"old_key": "old_val"},
            )
        new_config = {"new_key": "new_val", "count": 42}
        async with db.get_session() as session:
            updated = await svc.update_tenant(
                session, tenant.id, config_overrides=new_config
            )
            assert updated.config_overrides == new_config
            assert "old_key" not in updated.config_overrides

    async def test_zuultimate_tenant_id_field(self, db, svc):
        async with db.get_session() as session:
            tenant, _ = await svc.create_tenant(
                session, name="ZuulLinked", slug="zuul-linked"
            )
            # zuultimate_tenant_id defaults to None
            assert tenant.zuultimate_tenant_id is None


# ── Schema Validation ──


class TestTenantSchemas:
    """Test Pydantic schema validation for tenant types."""

    def test_tenant_create_valid(self):
        tc = TenantCreate(name="Acme", slug="acme")
        assert tc.name == "Acme"
        assert tc.slug == "acme"
        assert tc.hmac_key_version == 0
        assert tc.config_overrides == {}

    def test_tenant_create_with_overrides(self):
        tc = TenantCreate(
            name="Corp", slug="corp",
            hmac_key_version=2,
            config_overrides={"plan": "pro"},
        )
        assert tc.hmac_key_version == 2
        assert tc.config_overrides["plan"] == "pro"

    def test_tenant_create_slug_pattern_valid(self):
        for slug in ["acme", "my-company", "a1b2", "test-123"]:
            tc = TenantCreate(name="T", slug=slug)
            assert tc.slug == slug

    def test_tenant_create_slug_pattern_rejects_invalid(self):
        for invalid in ["UPPER", "with spaces", "-leading", "trailing-", "special!char"]:
            with pytest.raises(Exception):
                TenantCreate(name="T", slug=invalid)

    def test_tenant_create_name_required(self):
        with pytest.raises(Exception):
            TenantCreate(slug="test")  # name is required

    def test_tenant_update_all_optional(self):
        tu = TenantUpdate()
        assert tu.name is None
        assert tu.hmac_key_version is None
        assert tu.config_overrides is None

    def test_tenant_update_partial(self):
        tu = TenantUpdate(name="New Name")
        assert tu.name == "New Name"
        assert tu.hmac_key_version is None

    def test_tenant_response_from_attributes(self, db, svc):
        """TenantResponse model_config has from_attributes=True."""
        assert TenantResponse.model_config.get("from_attributes") is True

    def test_tenant_create_response_includes_api_key(self):
        resp = TenantCreateResponse(
            id="abc", name="T", slug="t", hmac_key_version=0,
            config_overrides={}, created_at="2026-01-01T00:00:00Z",
            api_key="vzt_test_key",
        )
        assert resp.api_key == "vzt_test_key"
        assert resp.id == "abc"


# ── Hash Function ──


class TestHashApiKey:
    """Test the _hash_api_key helper function."""

    def test_hash_is_sha256(self):
        import hashlib
        raw = "vzt_test_key_123"
        expected = hashlib.sha256(raw.encode()).hexdigest()
        assert _hash_api_key(raw) == expected

    def test_hash_is_deterministic(self):
        raw = "vzt_same_key"
        assert _hash_api_key(raw) == _hash_api_key(raw)

    def test_different_keys_different_hashes(self):
        h1 = _hash_api_key("vzt_key1")
        h2 = _hash_api_key("vzt_key2")
        assert h1 != h2

    def test_hash_length_is_64(self):
        h = _hash_api_key("vzt_any_key")
        assert len(h) == 64
