"""Tests for usage service — record and query usage."""

import pytest

from vinzy_engine.common.config import VinzySettings
from vinzy_engine.common.database import DatabaseManager
from vinzy_engine.common.exceptions import LicenseNotFoundError
from vinzy_engine.licensing.service import LicensingService
from vinzy_engine.usage.service import UsageService


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
def licensing_svc():
    return LicensingService(make_settings())


@pytest.fixture
def svc(licensing_svc):
    return UsageService(make_settings(), licensing_svc)


async def _create_license(db, licensing_svc, entitlements=None):
    async with db.get_session() as session:
        await licensing_svc.create_product(session, "ZUL", "Zuultimate")
        customer = await licensing_svc.create_customer(
            session, "Test", "test@example.com"
        )
    async with db.get_session() as session:
        lic, raw_key = await licensing_svc.create_license(
            session, "ZUL", customer.id,
            entitlements=entitlements or {},
        )
    return lic, raw_key


class TestRecordUsage:
    async def test_record_basic(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            result = await svc.record_usage(session, raw_key, "api-calls", 1.0)
            assert result["success"] is True
            assert result["metric"] == "api-calls"
            assert result["value_added"] == 1.0
            assert result["total_value"] == 1.0

    async def test_record_accumulates(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await svc.record_usage(session, raw_key, "tokens", 100.0)
        async with db.get_session() as session:
            result = await svc.record_usage(session, raw_key, "tokens", 50.0)
            assert result["total_value"] == 150.0

    async def test_record_with_limit(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(
            db, licensing_svc,
            entitlements={"tokens": {"enabled": True, "limit": 1000}},
        )
        async with db.get_session() as session:
            result = await svc.record_usage(session, raw_key, "tokens", 300.0)
            assert result["limit"] == 1000
            assert result["remaining"] == 700.0

    async def test_record_bad_key(self, db, svc, licensing_svc):
        with pytest.raises(LicenseNotFoundError):
            async with db.get_session() as session:
                await svc.record_usage(session, "bad-key", "api-calls")

    async def test_record_custom_value(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            result = await svc.record_usage(session, raw_key, "bytes", 1024.5)
            assert result["value_added"] == 1024.5

    async def test_record_no_limit(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            result = await svc.record_usage(session, raw_key, "api-calls")
            assert result["limit"] is None
            assert result["remaining"] is None


class TestUsageSummary:
    async def test_summary_empty(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            summaries = await svc.get_usage_summary(session, lic.id)
            assert summaries == []

    async def test_summary_multiple_metrics(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await svc.record_usage(session, raw_key, "api-calls", 5.0)
        async with db.get_session() as session:
            await svc.record_usage(session, raw_key, "tokens", 100.0)
        async with db.get_session() as session:
            summaries = await svc.get_usage_summary(session, lic.id)
            assert len(summaries) == 2
            metrics = {s["metric"] for s in summaries}
            assert metrics == {"api-calls", "tokens"}

    async def test_summary_record_count(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await svc.record_usage(session, raw_key, "api-calls", 1.0)
        async with db.get_session() as session:
            await svc.record_usage(session, raw_key, "api-calls", 1.0)
        async with db.get_session() as session:
            await svc.record_usage(session, raw_key, "api-calls", 1.0)
        async with db.get_session() as session:
            summaries = await svc.get_usage_summary(session, lic.id)
            assert summaries[0]["record_count"] == 3
            assert summaries[0]["total_value"] == 3.0
