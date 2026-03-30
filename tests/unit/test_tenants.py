"""Tests for tenant service — CRUD, scoped uniqueness, HMAC versioning."""

import pytest

from vinzy_engine.common.config import VinzySettings
from vinzy_engine.common.database import DatabaseManager
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


class TestTenantCreate:
    async def test_create_tenant(self, db, svc):
        async with db.get_session() as session:
            tenant, raw_key = await svc.create_tenant(
                session, name="Acme Corp", slug="acme"
            )
            assert tenant.name == "Acme Corp"
            assert tenant.slug == "acme"
            assert raw_key.startswith("vzt_")
            assert tenant.id is not None

    async def test_api_key_hash_stored(self, db, svc):
        async with db.get_session() as session:
            tenant, raw_key = await svc.create_tenant(
                session, name="Test", slug="test"
            )
            expected_hash = _hash_api_key(raw_key)
            assert tenant.api_key_hash == expected_hash

    async def test_hmac_version_default(self, db, svc):
        async with db.get_session() as session:
            tenant, _ = await svc.create_tenant(
                session, name="T", slug="t"
            )
            assert tenant.hmac_key_version == 0

    async def test_hmac_version_custom(self, db, svc):
        async with db.get_session() as session:
            tenant, _ = await svc.create_tenant(
                session, name="T", slug="t", hmac_key_version=3
            )
            assert tenant.hmac_key_version == 3


class TestTenantLookup:
    async def test_get_by_slug(self, db, svc):
        async with db.get_session() as session:
            await svc.create_tenant(session, name="A", slug="alpha")
        async with db.get_session() as session:
            found = await svc.get_by_slug(session, "alpha")
            assert found is not None
            assert found.name == "A"

    async def test_get_by_slug_not_found(self, db, svc):
        async with db.get_session() as session:
            found = await svc.get_by_slug(session, "nope")
            assert found is None

    async def test_resolve_by_raw_key(self, db, svc):
        async with db.get_session() as session:
            tenant, raw_key = await svc.create_tenant(
                session, name="R", slug="resolve"
            )
        async with db.get_session() as session:
            found = await svc.resolve_by_raw_key(session, raw_key)
            assert found is not None
            assert found.id == tenant.id

    async def test_resolve_by_wrong_key(self, db, svc):
        async with db.get_session() as session:
            found = await svc.resolve_by_raw_key(session, "vzt_wrong_key")
            assert found is None

    async def test_list_tenants(self, db, svc):
        async with db.get_session() as session:
            await svc.create_tenant(session, name="A", slug="a")
            await svc.create_tenant(session, name="B", slug="b")
        async with db.get_session() as session:
            tenants = await svc.list_tenants(session)
            assert len(tenants) == 2


class TestTenantUpdate:
    async def test_update_name(self, db, svc):
        async with db.get_session() as session:
            tenant, _ = await svc.create_tenant(session, name="Old", slug="up")
        async with db.get_session() as session:
            updated = await svc.update_tenant(session, tenant.id, name="New")
            assert updated.name == "New"

    async def test_update_not_found(self, db, svc):
        async with db.get_session() as session:
            result = await svc.update_tenant(session, "no-id", name="X")
            assert result is None


class TestTenantDelete:
    async def test_delete_tenant(self, db, svc):
        async with db.get_session() as session:
            tenant, _ = await svc.create_tenant(session, name="D", slug="del")
        async with db.get_session() as session:
            deleted = await svc.delete_tenant(session, tenant.id)
            assert deleted is True
        async with db.get_session() as session:
            found = await svc.get_by_id(session, tenant.id)
            assert found is None

    async def test_delete_not_found(self, db, svc):
        async with db.get_session() as session:
            result = await svc.delete_tenant(session, "no-id")
            assert result is False
