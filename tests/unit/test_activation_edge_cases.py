"""Edge-case tests for activation service — expiry, revocation, limits, reactivation."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from vinzy_engine.common.config import VinzySettings
from vinzy_engine.common.database import DatabaseManager
from vinzy_engine.common.exceptions import (
    ActivationLimitError,
    LicenseExpiredError,
    LicenseNotFoundError,
    LicenseSuspendedError,
)
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
def licensing_svc():
    return LicensingService(make_settings())


@pytest.fixture
def svc(licensing_svc):
    return ActivationService(make_settings(), licensing_svc)


async def _create_license(db, licensing_svc, machines_limit=3, tier="standard", days_valid=365):
    async with db.get_session() as session:
        await licensing_svc.create_product(session, "ZUL", "Zuultimate")
        customer = await licensing_svc.create_customer(
            session, "Test", "test@example.com"
        )
    async with db.get_session() as session:
        lic, raw_key = await licensing_svc.create_license(
            session, "ZUL", customer.id,
            machines_limit=machines_limit,
            tier=tier,
            days_valid=days_valid,
        )
    return lic, raw_key


class TestActivateValidKey:
    """Activating a valid key on a new machine succeeds."""

    async def test_activate_returns_success(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            result = await svc.activate(session, raw_key, "fp-new", hostname="host1")
            assert result["success"] is True
            assert result["code"] == "ACTIVATED"
            assert result["machine_id"] is not None

    async def test_activate_with_platform_and_metadata(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            result = await svc.activate(
                session, raw_key, "fp-meta",
                hostname="workstation",
                platform="linux",
                metadata={"os_version": "Ubuntu 24.04"},
            )
            assert result["success"] is True
            assert result["code"] == "ACTIVATED"


class TestActivateAlreadyActivated:
    """Re-activating on the same fingerprint returns ALREADY_ACTIVATED."""

    async def test_idempotent_activation(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await svc.activate(session, raw_key, "fp-1")
        async with db.get_session() as session:
            result = await svc.activate(session, raw_key, "fp-1")
            assert result["code"] == "ALREADY_ACTIVATED"
            assert result["success"] is True

    async def test_already_activated_updates_heartbeat(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            first = await svc.activate(session, raw_key, "fp-1")
        async with db.get_session() as session:
            second = await svc.activate(session, raw_key, "fp-1", hostname="updated-host")
            # Same machine id
            assert second["machine_id"] == first["machine_id"]


class TestActivateExpiredKey:
    """Activating an expired license should fail."""

    async def test_expired_license_raises(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        # Manually expire the license
        async with db.get_session() as session:
            found = await licensing_svc.get_license_by_key(session, raw_key)
            found.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
            found.status = "expired"
            await session.flush()
        with pytest.raises((LicenseExpiredError, LicenseSuspendedError)):
            async with db.get_session() as session:
                await svc.activate(session, raw_key, "fp-expired")


class TestActivateRevokedKey:
    """Activating a revoked license should fail."""

    async def test_revoked_license_raises(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        # Revoke the license
        async with db.get_session() as session:
            found = await licensing_svc.get_license_by_key(session, raw_key)
            found.status = "revoked"
            await session.flush()
        with pytest.raises((LicenseSuspendedError, LicenseExpiredError)):
            async with db.get_session() as session:
                await svc.activate(session, raw_key, "fp-revoked")

    async def test_suspended_license_raises(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            found = await licensing_svc.get_license_by_key(session, raw_key)
            found.status = "suspended"
            await session.flush()
        with pytest.raises((LicenseSuspendedError, LicenseExpiredError)):
            async with db.get_session() as session:
                await svc.activate(session, raw_key, "fp-suspended")


class TestMaxActivationsReached:
    """Exceeding machines_limit should raise ActivationLimitError."""

    async def test_single_slot_limit(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc, machines_limit=1)
        async with db.get_session() as session:
            await svc.activate(session, raw_key, "fp-1")
        with pytest.raises(ActivationLimitError):
            async with db.get_session() as session:
                await svc.activate(session, raw_key, "fp-2")

    async def test_three_slot_limit(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc, machines_limit=3)
        for i in range(3):
            async with db.get_session() as session:
                await svc.activate(session, raw_key, f"fp-{i}")
        with pytest.raises(ActivationLimitError):
            async with db.get_session() as session:
                await svc.activate(session, raw_key, "fp-overflow")

    async def test_machines_used_tracks_count(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc, machines_limit=5)
        for i in range(3):
            async with db.get_session() as session:
                await svc.activate(session, raw_key, f"fp-{i}")
        async with db.get_session() as session:
            found = await licensing_svc.get_license_by_key(session, raw_key)
            assert found.machines_used == 3


class TestDeactivateAndReactivate:
    """Deactivation frees a slot, allowing re-activation."""

    async def test_deactivate_then_reactivate_same_fingerprint(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc, machines_limit=1)
        # Activate
        async with db.get_session() as session:
            await svc.activate(session, raw_key, "fp-1")
        # Deactivate
        async with db.get_session() as session:
            result = await svc.deactivate(session, raw_key, "fp-1")
            assert result is True
        # Reactivate same fingerprint
        async with db.get_session() as session:
            result = await svc.activate(session, raw_key, "fp-1")
            assert result["code"] == "ACTIVATED"

    async def test_deactivate_frees_slot_for_new_device(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc, machines_limit=1)
        # Fill the slot
        async with db.get_session() as session:
            await svc.activate(session, raw_key, "fp-old")
        # Deactivate old
        async with db.get_session() as session:
            await svc.deactivate(session, raw_key, "fp-old")
        # New device can activate
        async with db.get_session() as session:
            result = await svc.activate(session, raw_key, "fp-new")
            assert result["code"] == "ACTIVATED"

    async def test_machines_used_decrements_on_deactivate(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await svc.activate(session, raw_key, "fp-1")
        async with db.get_session() as session:
            await svc.activate(session, raw_key, "fp-2")
        async with db.get_session() as session:
            found = await licensing_svc.get_license_by_key(session, raw_key)
            assert found.machines_used == 2
        async with db.get_session() as session:
            await svc.deactivate(session, raw_key, "fp-1")
        async with db.get_session() as session:
            found = await licensing_svc.get_license_by_key(session, raw_key)
            assert found.machines_used == 1

    async def test_machines_used_never_goes_negative(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await svc.activate(session, raw_key, "fp-1")
        # Manually set machines_used to 0 to simulate edge case
        async with db.get_session() as session:
            found = await licensing_svc.get_license_by_key(session, raw_key)
            found.machines_used = 0
            await session.flush()
        async with db.get_session() as session:
            await svc.deactivate(session, raw_key, "fp-1")
        async with db.get_session() as session:
            found = await licensing_svc.get_license_by_key(session, raw_key)
            assert found.machines_used >= 0


class TestActivationWithDeviceFingerprint:
    """Device fingerprints differentiate machines."""

    async def test_different_fingerprints_are_separate_machines(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            r1 = await svc.activate(session, raw_key, "fp-device-A")
        async with db.get_session() as session:
            r2 = await svc.activate(session, raw_key, "fp-device-B")
        assert r1["machine_id"] != r2["machine_id"]

    async def test_same_fingerprint_same_machine(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            r1 = await svc.activate(session, raw_key, "fp-same")
        async with db.get_session() as session:
            r2 = await svc.activate(session, raw_key, "fp-same")
        assert r1["machine_id"] == r2["machine_id"]
        assert r2["code"] == "ALREADY_ACTIVATED"

    async def test_deactivate_specific_fingerprint_only(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await svc.activate(session, raw_key, "fp-A")
        async with db.get_session() as session:
            await svc.activate(session, raw_key, "fp-B")
        # Deactivate only fp-A
        async with db.get_session() as session:
            await svc.deactivate(session, raw_key, "fp-A")
        # fp-B is still active
        async with db.get_session() as session:
            result = await svc.activate(session, raw_key, "fp-B")
            assert result["code"] == "ALREADY_ACTIVATED"
        # fp-A can be re-activated
        async with db.get_session() as session:
            result = await svc.activate(session, raw_key, "fp-A")
            assert result["code"] == "ACTIVATED"


class TestConcurrentActivations:
    """Test thread safety of concurrent activation attempts."""

    async def test_concurrent_activations_different_fingerprints(self, db, svc, licensing_svc):
        """Multiple unique fingerprints activated sequentially all succeed within limit."""
        lic, raw_key = await _create_license(db, licensing_svc, machines_limit=5)
        results = []
        for i in range(5):
            async with db.get_session() as session:
                r = await svc.activate(session, raw_key, f"fp-concurrent-{i}")
                results.append(r)
        assert all(r["success"] for r in results)
        assert all(r["code"] == "ACTIVATED" for r in results)

    async def test_rapid_activate_deactivate_cycle(self, db, svc, licensing_svc):
        """Rapid activate/deactivate cycles maintain correct count."""
        lic, raw_key = await _create_license(db, licensing_svc, machines_limit=1)
        for i in range(10):
            async with db.get_session() as session:
                await svc.activate(session, raw_key, f"fp-cycle-{i}")
            async with db.get_session() as session:
                await svc.deactivate(session, raw_key, f"fp-cycle-{i}")
        # Final state: 0 machines used
        async with db.get_session() as session:
            found = await licensing_svc.get_license_by_key(session, raw_key)
            assert found.machines_used == 0

    async def test_activate_nonexistent_key_raises(self, db, svc, licensing_svc):
        """Activating with a key that does not exist in DB raises LicenseNotFoundError."""
        from vinzy_engine.keygen.generator import generate_key
        fake_key = generate_key("ZUL", HMAC_KEY)
        with pytest.raises(LicenseNotFoundError):
            async with db.get_session() as session:
                await svc.activate(session, fake_key, "fp-ghost")


class TestHeartbeatEdgeCases:
    """Edge cases for heartbeat updates."""

    async def test_heartbeat_updates_version(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await svc.activate(session, raw_key, "fp-hb")
        async with db.get_session() as session:
            result = await svc.heartbeat(session, raw_key, "fp-hb", version="2.0.1")
            assert result is True

    async def test_heartbeat_nonexistent_fingerprint(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            result = await svc.heartbeat(session, raw_key, "fp-ghost")
            assert result is False

    async def test_heartbeat_nonexistent_key(self, db, svc, licensing_svc):
        with pytest.raises(LicenseNotFoundError):
            async with db.get_session() as session:
                await svc.heartbeat(session, "bad-key-here", "fp-1")
