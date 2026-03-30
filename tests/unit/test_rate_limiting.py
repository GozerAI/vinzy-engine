"""Tests for rate limiting middleware."""

import os
import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def _rate_limit_env(monkeypatch):
    monkeypatch.setenv("VINZY_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("VINZY_RATE_LIMIT_PER_MINUTE", "60")
    monkeypatch.setenv("VINZY_RATE_LIMIT_PUBLIC_PER_MINUTE", "5")


class TestRateLimitingConfig:
    def test_settings_have_rate_limit_fields(self):
        from vinzy_engine.common.config import VinzySettings
        s = VinzySettings(
            rate_limit_enabled=True,
            rate_limit_per_minute=120,
            rate_limit_public_per_minute=20,
        )
        assert s.rate_limit_enabled is True
        assert s.rate_limit_per_minute == 120
        assert s.rate_limit_public_per_minute == 20

    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("VINZY_RATE_LIMIT_PUBLIC_PER_MINUTE", raising=False)
        from vinzy_engine.common.config import VinzySettings
        s = VinzySettings()
        assert s.rate_limit_enabled is True
        assert s.rate_limit_per_minute == 60
        assert s.rate_limit_public_per_minute == 30


class TestRateLimitModule:
    def test_limiter_importable(self):
        from vinzy_engine.common.rate_limiting import limiter
        assert limiter is not None

    def test_public_limit_returns_string(self):
        from vinzy_engine.common.rate_limiting import _public_limit
        result = _public_limit()
        assert "/minute" in result

    def test_default_limit_returns_string(self):
        from vinzy_engine.common.rate_limiting import _default_limit
        result = _default_limit()
        assert "/minute" in result


class TestRateLimitOnPublicEndpoints:
    """Verify that public endpoints enforce stricter rate limits."""

    async def test_validate_has_rate_limit(self, client):
        """Hit validate many times — should eventually get 429."""
        # With VINZY_RATE_LIMIT_PUBLIC_PER_MINUTE=5, 6th request should fail
        for i in range(5):
            resp = await client.post("/validate", json={"key": "test"})
            assert resp.status_code == 200

        resp = await client.post("/validate", json={"key": "test"})
        assert resp.status_code == 429

    async def test_activate_has_rate_limit(self, client):
        for i in range(5):
            resp = await client.post(
                "/activate", json={"key": "test", "fingerprint": "fp"}
            )
            assert resp.status_code == 200

        resp = await client.post(
            "/activate", json={"key": "test", "fingerprint": "fp"}
        )
        assert resp.status_code == 429

    async def test_heartbeat_has_rate_limit(self, client):
        for i in range(5):
            resp = await client.post(
                "/heartbeat", json={"key": "test", "fingerprint": "fp"}
            )
            assert resp.status_code == 200

        resp = await client.post(
            "/heartbeat", json={"key": "test", "fingerprint": "fp"}
        )
        assert resp.status_code == 429
