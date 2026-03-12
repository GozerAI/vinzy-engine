"""Tests for activation service — activate, deactivate, heartbeat."""

import pytest

from vinzy_engine.common.config import VinzySettings
from vinzy_engine.common.database import DatabaseManager
from vinzy_engine.common.exceptions import ActivationLimitError, LicenseNotFoundError
from vinzy_engine.activation.service import ActivationService
from vinzy_engine.licensing.service import LicensingService


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
    settings = make_settings()
    licensing = LicensingService(settings)
    return ActivationService(settings, licensing)


@pytest.fixture
def licensing_svc():
    return LicensingService(make_settings())


async def _create_license(db, licensing_svc, machines_limit=3):
    async with db.get_session() as session:
        await licensing_svc.create_product(session, "ZUL", "Zuultimate")
        customer = await licensing_svc.create_customer(
            session, "Test", "test@example.com"
        )
    async with db.get_session() as session:
        lic, raw_key = await licensing_svc.create_license(
            session, "ZUL", customer.id, machines_limit=machines_limit
        )
    return lic, raw_key


class TestActivation:
    async def test_activate_success(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            result = await svc.activate(
                session, raw_key, "fingerprint-1", hostname="host1"
            )
            assert result["success"] is True
            assert result["code"] == "ACTIVATED"
            assert result["machine_id"] is not None

    async def test_activate_already_activated(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await svc.activate(session, raw_key, "fp-1")
        async with db.get_session() as session:
            result = await svc.activate(session, raw_key, "fp-1")
            assert result["code"] == "ALREADY_ACTIVATED"

    async def test_activate_limit_reached(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc, machines_limit=1)
        async with db.get_session() as session:
            await svc.activate(session, raw_key, "fp-1")
        with pytest.raises(ActivationLimitError):
            async with db.get_session() as session:
                await svc.activate(session, raw_key, "fp-2")

    async def test_activate_increments_machines_used(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await svc.activate(session, raw_key, "fp-1")
        async with db.get_session() as session:
            found = await licensing_svc.get_license_by_key(session, raw_key)
            assert found.machines_used == 1


class TestDeactivation:
    async def test_deactivate_success(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await svc.activate(session, raw_key, "fp-1")
        async with db.get_session() as session:
            result = await svc.deactivate(session, raw_key, "fp-1")
            assert result is True

    async def test_deactivate_decrements_machines_used(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await svc.activate(session, raw_key, "fp-1")
        async with db.get_session() as session:
            await svc.deactivate(session, raw_key, "fp-1")
        async with db.get_session() as session:
            found = await licensing_svc.get_license_by_key(session, raw_key)
            assert found.machines_used == 0

    async def test_deactivate_nonexistent(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            result = await svc.deactivate(session, raw_key, "no-such-fp")
            assert result is False

    async def test_deactivate_bad_key(self, db, svc, licensing_svc):
        with pytest.raises(LicenseNotFoundError):
            async with db.get_session() as session:
                await svc.deactivate(session, "no-such-key", "fp-1")


class TestHeartbeat:
    async def test_heartbeat_success(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await svc.activate(session, raw_key, "fp-1")
        async with db.get_session() as session:
            result = await svc.heartbeat(session, raw_key, "fp-1", version="1.0")
            assert result is True

    async def test_heartbeat_not_activated(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            result = await svc.heartbeat(session, raw_key, "fp-1")
            assert result is False

    async def test_heartbeat_bad_key(self, db, svc, licensing_svc):
        with pytest.raises(LicenseNotFoundError):
            async with db.get_session() as session:
                await svc.heartbeat(session, "bad-key", "fp-1")
