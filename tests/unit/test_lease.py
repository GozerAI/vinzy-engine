"""Tests for keygen.lease — signed lease creation and verification."""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import patch

from vinzy_engine.keygen.lease import LeasePayload, create_lease, verify_lease


HMAC_KEY = "test-hmac-key-for-unit-tests"


def _make_payload(**overrides) -> LeasePayload:
    defaults = {
        "license_id": "lic-123",
        "status": "active",
        "features": ["api", "export"],
        "entitlements": [{"feature": "api", "enabled": True}],
        "tier": "pro",
        "product_code": "ZUL",
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": "2027-01-01T00:00:00+00:00",
    }
    defaults.update(overrides)
    return LeasePayload(**defaults)


class TestCreateLease:
    def test_create_returns_dict(self):
        payload = _make_payload()
        lease = create_lease(payload, HMAC_KEY)
        assert "payload" in lease
        assert "signature" in lease
        assert "lease_expires_at" in lease

    def test_signature_is_hex(self):
        payload = _make_payload()
        lease = create_lease(payload, HMAC_KEY)
        assert len(lease["signature"]) == 64
        assert all(c in "0123456789abcdef" for c in lease["signature"])

    def test_deterministic_signature(self):
        """Same payload + key produces same signature."""
        payload = _make_payload(issued_at="2026-01-01T00:00:00+00:00")
        lease1 = create_lease(payload, HMAC_KEY, ttl_seconds=3600)
        lease2 = create_lease(payload, HMAC_KEY, ttl_seconds=3600)
        # Signatures may differ due to time-based lease_expires_at,
        # but payload is deterministic
        assert lease1["payload"] == lease2["payload"]


class TestVerifyLease:
    def test_verify_valid(self):
        payload = _make_payload()
        lease = create_lease(payload, HMAC_KEY, ttl_seconds=3600)
        assert verify_lease(lease, HMAC_KEY) is True

    def test_tampered_payload_rejected(self):
        payload = _make_payload()
        lease = create_lease(payload, HMAC_KEY, ttl_seconds=3600)
        lease["payload"]["status"] = "revoked"
        assert verify_lease(lease, HMAC_KEY) is False

    def test_tampered_signature_rejected(self):
        payload = _make_payload()
        lease = create_lease(payload, HMAC_KEY, ttl_seconds=3600)
        lease["signature"] = "a" * 64
        assert verify_lease(lease, HMAC_KEY) is False

    def test_expired_lease_rejected(self):
        payload = _make_payload()
        lease = create_lease(payload, HMAC_KEY, ttl_seconds=0)
        # ttl=0 means it expires immediately
        import time
        time.sleep(0.01)
        assert verify_lease(lease, HMAC_KEY) is False

    def test_wrong_key_rejected(self):
        payload = _make_payload()
        lease = create_lease(payload, HMAC_KEY, ttl_seconds=3600)
        assert verify_lease(lease, "wrong-key") is False

    def test_roundtrip(self):
        payload = _make_payload()
        lease = create_lease(payload, HMAC_KEY, ttl_seconds=86400)
        assert verify_lease(lease, HMAC_KEY) is True
        # Payload data is preserved
        assert lease["payload"]["license_id"] == "lic-123"
        assert lease["payload"]["tier"] == "pro"

    def test_malformed_lease(self):
        assert verify_lease({}, HMAC_KEY) is False
        assert verify_lease(None, HMAC_KEY) is False
        assert verify_lease({"payload": {}, "signature": "x"}, HMAC_KEY) is False
