"""Adversarial tests — security, forgery, tampering, edge cases."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from vinzy_engine.keygen.generator import (
    BASE32_ALPHABET,
    generate_key,
    key_hash,
    verify_hmac,
    verify_hmac_multi,
)
from vinzy_engine.keygen.lease import LeasePayload, create_lease, verify_lease
from vinzy_engine.keygen.validator import validate_key


HMAC_KEY = "test-hmac-key-for-unit-tests"
WRONG_KEY = "completely-wrong-hmac-key"


# ── Key Forgery ──


class TestKeyForgery:
    def test_wrong_hmac_key_rejected(self):
        """Keys signed with the wrong HMAC key must be rejected."""
        key = generate_key("ZUL", WRONG_KEY)
        assert verify_hmac(key, HMAC_KEY) is False

    def test_wrong_keyring_rejected(self):
        """Keys that match no key in the keyring must be rejected."""
        key = generate_key("ZUL", "secret-x")
        keyring = {0: "secret-a", 1: "secret-b", 2: "secret-c"}
        assert verify_hmac_multi(key, keyring) is False


# ── HMAC Truncation ──


class TestHmacTruncation:
    def test_no_accidental_verification(self):
        """1000 random keys must never accidentally verify (statistical)."""
        false_positives = 0
        for _ in range(1000):
            key = generate_key("ZUL", WRONG_KEY)
            if verify_hmac(key, HMAC_KEY):
                false_positives += 1
        # With 50 bits of HMAC, probability of collision is ~1/2^50 per try
        assert false_positives == 0


# ── Tampered Keys ──


class TestTamperedKeys:
    def test_flip_char_in_random_segment(self):
        """Flipping a character in any random segment invalidates the key."""
        key = generate_key("ZUL", HMAC_KEY)
        parts = key.split("-")
        for seg_idx in range(1, 6):  # segments 1-5 are random
            seg = list(parts[seg_idx])
            original_char = seg[2]
            seg[2] = "A" if original_char != "A" else "B"
            tampered_parts = parts.copy()
            tampered_parts[seg_idx] = "".join(seg)
            tampered = "-".join(tampered_parts)
            assert verify_hmac(tampered, HMAC_KEY) is False, f"Segment {seg_idx} tamper not detected"

    def test_flip_char_in_hmac_segment(self):
        """Flipping a character in either HMAC segment invalidates the key."""
        key = generate_key("ZUL", HMAC_KEY)
        parts = key.split("-")
        for seg_idx in (6, 7):  # HMAC segments
            seg = list(parts[seg_idx])
            seg[0] = "A" if seg[0] != "A" else "B"
            tampered_parts = parts.copy()
            tampered_parts[seg_idx] = "".join(seg)
            tampered = "-".join(tampered_parts)
            assert verify_hmac(tampered, HMAC_KEY) is False, f"HMAC segment {seg_idx} tamper not detected"

    def test_swap_random_segments(self):
        """Swapping two random segments invalidates the key."""
        key = generate_key("ZUL", HMAC_KEY)
        parts = key.split("-")
        # Swap segments 1 and 3
        parts[1], parts[3] = parts[3], parts[1]
        tampered = "-".join(parts)
        assert verify_hmac(tampered, HMAC_KEY) is False


# ── Clock Manipulation ──


class TestClockManipulation:
    async def test_expired_license_rejected(self):
        """An expired license is rejected via mocked datetime."""
        from vinzy_engine.common.config import VinzySettings
        from vinzy_engine.common.database import DatabaseManager
        from vinzy_engine.common.exceptions import LicenseExpiredError
        from vinzy_engine.licensing.service import LicensingService

        settings = VinzySettings(hmac_key=HMAC_KEY, db_url="sqlite+aiosqlite://")
        manager = DatabaseManager(settings)
        await manager.init()
        await manager.create_all()

        svc = LicensingService(settings)
        async with manager.get_session() as session:
            await svc.create_product(session, "ZUL", "Zuultimate")
            customer = await svc.create_customer(session, "T", "t@t.com")

        async with manager.get_session() as session:
            lic, raw_key = await svc.create_license(
                session, "ZUL", customer.id, days_valid=1
            )

        # Fast-forward: set license expiry to the past
        async with manager.get_session() as session:
            lic_obj = await svc.get_license_by_key(session, raw_key)
            lic_obj.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
            await session.flush()

        with pytest.raises(LicenseExpiredError):
            async with manager.get_session() as session:
                await svc.validate_license(session, raw_key)

        await manager.close()


# ── Activation Limit Bypass ──


class TestActivationLimitBypass:
    async def test_concurrent_activations_respect_limit(self):
        """Activating more machines than allowed must fail."""
        from vinzy_engine.common.config import VinzySettings
        from vinzy_engine.common.database import DatabaseManager
        from vinzy_engine.common.exceptions import ActivationLimitError
        from vinzy_engine.activation.service import ActivationService
        from vinzy_engine.licensing.service import LicensingService

        settings = VinzySettings(hmac_key=HMAC_KEY, db_url="sqlite+aiosqlite://")
        manager = DatabaseManager(settings)
        await manager.init()
        await manager.create_all()

        lic_svc = LicensingService(settings)
        act_svc = ActivationService(settings, lic_svc)

        async with manager.get_session() as session:
            await lic_svc.create_product(session, "ZUL", "Zuultimate")
            customer = await lic_svc.create_customer(session, "T", "t@t.com")

        async with manager.get_session() as session:
            _, raw_key = await lic_svc.create_license(
                session, "ZUL", customer.id, machines_limit=1
            )

        # First activation succeeds
        async with manager.get_session() as session:
            result = await act_svc.activate(session, raw_key, "fp-1")
            assert result["success"] is True

        # Second activation must fail
        with pytest.raises(ActivationLimitError):
            async with manager.get_session() as session:
                await act_svc.activate(session, raw_key, "fp-2")

        await manager.close()


# ── Fingerprint Replay ──


class TestFingerprintReplay:
    async def test_same_fingerprint_independent_licenses(self):
        """Same fingerprint works independently across different licenses."""
        from vinzy_engine.common.config import VinzySettings
        from vinzy_engine.common.database import DatabaseManager
        from vinzy_engine.activation.service import ActivationService
        from vinzy_engine.licensing.service import LicensingService

        settings = VinzySettings(hmac_key=HMAC_KEY, db_url="sqlite+aiosqlite://")
        manager = DatabaseManager(settings)
        await manager.init()
        await manager.create_all()

        lic_svc = LicensingService(settings)
        act_svc = ActivationService(settings, lic_svc)

        async with manager.get_session() as session:
            await lic_svc.create_product(session, "ZUL", "Zuultimate")
            c1 = await lic_svc.create_customer(session, "A", "a@a.com")
            c2 = await lic_svc.create_customer(session, "B", "b@b.com")

        async with manager.get_session() as session:
            _, key1 = await lic_svc.create_license(session, "ZUL", c1.id)
        async with manager.get_session() as session:
            _, key2 = await lic_svc.create_license(session, "ZUL", c2.id)

        # Same fingerprint on two different licenses
        async with manager.get_session() as session:
            r1 = await act_svc.activate(session, key1, "same-fp")
            assert r1["success"] is True
        async with manager.get_session() as session:
            r2 = await act_svc.activate(session, key2, "same-fp")
            assert r2["success"] is True

        await manager.close()


# ── Admin Endpoint Auth ──


class TestAdminEndpointAuth:
    async def test_create_product_no_auth(self, client):
        resp = await client.post("/products", json={"code": "ZUL", "name": "Z"})
        assert resp.status_code == 422

    async def test_create_product_wrong_auth(self, client):
        resp = await client.post(
            "/products",
            json={"code": "ZUL", "name": "Z"},
            headers={"X-Vinzy-Api-Key": "wrong"},
        )
        assert resp.status_code == 403

    async def test_list_licenses_no_auth(self, client):
        resp = await client.get("/licenses")
        assert resp.status_code == 422

    async def test_get_usage_no_auth(self, client):
        resp = await client.get("/usage/some-id")
        assert resp.status_code == 422

    async def test_validate_no_auth_ok(self, client):
        resp = await client.get("/validate", params={"key": "any"})
        assert resp.status_code == 200


# ── SQL Injection ──


class TestSqlInjection:
    def test_product_code_rejects_injection(self):
        """Pydantic regex on product code rejects SQL injection attempts."""
        from pydantic import ValidationError
        from vinzy_engine.licensing.schemas import ProductCreate

        with pytest.raises(ValidationError):
            ProductCreate(code="'; DROP TABLE--", name="evil")


# ── Key Enumeration ──


class TestKeyEnumeration:
    def test_different_keys_different_hashes(self):
        k1 = generate_key("ZUL", HMAC_KEY)
        k2 = generate_key("ZUL", HMAC_KEY)
        assert key_hash(k1) != key_hash(k2)

    def test_hash_is_64_char_hex(self):
        key = generate_key("ZUL", HMAC_KEY)
        h = key_hash(key)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ── Lease Forgery ──


class TestLeaseForgery:
    def test_tampered_payload_rejected(self):
        payload = LeasePayload(
            license_id="lic-1", status="active", features=["api"],
            entitlements=[], tier="pro", product_code="ZUL",
            issued_at=datetime.now(timezone.utc).isoformat(),
            expires_at="2027-01-01T00:00:00+00:00",
        )
        lease = create_lease(payload, HMAC_KEY, ttl_seconds=3600)
        lease["payload"]["status"] = "revoked"
        assert verify_lease(lease, HMAC_KEY) is False

    def test_forged_signature_rejected(self):
        payload = LeasePayload(
            license_id="lic-1", status="active", features=[],
            entitlements=[], tier="standard", product_code="ZUL",
            issued_at=datetime.now(timezone.utc).isoformat(),
            expires_at="2027-01-01T00:00:00+00:00",
        )
        lease = create_lease(payload, HMAC_KEY, ttl_seconds=3600)
        lease["signature"] = "f" * 64
        assert verify_lease(lease, HMAC_KEY) is False

    def test_expired_lease_rejected(self):
        payload = LeasePayload(
            license_id="lic-1", status="active", features=[],
            entitlements=[], tier="standard", product_code="ZUL",
            issued_at=datetime.now(timezone.utc).isoformat(),
            expires_at="2027-01-01T00:00:00+00:00",
        )
        lease = create_lease(payload, HMAC_KEY, ttl_seconds=0)
        import time
        time.sleep(0.01)
        assert verify_lease(lease, HMAC_KEY) is False
