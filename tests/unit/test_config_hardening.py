"""Tests for VinzySettings configuration hardening."""

import os
import warnings

import pytest

from vinzy_engine.common.config import VinzySettings, _INSECURE_DEFAULTS


HMAC_KEY = "test-hmac-key-for-unit-tests"


def make_settings(**overrides) -> VinzySettings:
    defaults = {"hmac_key": HMAC_KEY, "db_url": "sqlite+aiosqlite://"}
    defaults.update(overrides)
    return VinzySettings(**defaults)


class TestDefaultValues:
    """Verify all default values match expected baseline."""

    def test_default_environment(self):
        s = VinzySettings()
        assert s.environment == "development"

    def test_default_db_url(self):
        s = VinzySettings()
        assert "sqlite" in s.db_url

    def test_default_api_prefix_empty(self):
        s = VinzySettings()
        assert s.api_prefix == ""

    def test_default_api_title(self):
        s = VinzySettings()
        assert s.api_title == "Vinzy-Engine"

    def test_default_api_version(self):
        s = VinzySettings()
        assert s.api_version == "0.1.0"

    def test_default_host(self):
        s = VinzySettings()
        assert s.host == "0.0.0.0"

    def test_default_port(self):
        s = VinzySettings()
        assert s.port == 8080

    def test_default_machines_limit(self):
        s = VinzySettings()
        assert s.default_machines_limit == 3

    def test_default_license_days(self):
        s = VinzySettings()
        assert s.default_license_days == 365

    def test_default_heartbeat_interval(self):
        s = VinzySettings()
        assert s.heartbeat_interval == 3600

    def test_default_lease_ttl(self):
        s = VinzySettings()
        assert s.lease_ttl == 86400

    def test_default_lease_offline_ttl(self):
        s = VinzySettings()
        assert s.lease_offline_ttl == 259200

    def test_default_page_size(self):
        s = VinzySettings()
        assert s.default_page_size == 20
        assert s.max_page_size == 100

    def test_default_rate_limit_enabled(self):
        s = VinzySettings()
        assert s.rate_limit_enabled is True
        assert s.rate_limit_per_minute == 60

    def test_default_ip_allowlist_disabled(self):
        s = VinzySettings()
        assert s.ip_allowlist_enabled is False
        assert s.ip_allowlist == []

    def test_default_zuultimate_integration_empty(self):
        s = VinzySettings()
        assert s.zuultimate_base_url == ""
        assert s.zuultimate_service_token == ""


class TestEnvPrefix:
    """Verify VINZY_ env prefix is honored."""

    def test_env_prefix_overrides_db_url(self, monkeypatch):
        monkeypatch.setenv("VINZY_DB_URL", "sqlite+aiosqlite:///custom.db")
        s = VinzySettings()
        assert s.db_url == "sqlite+aiosqlite:///custom.db"

    def test_env_prefix_overrides_port(self, monkeypatch):
        monkeypatch.setenv("VINZY_PORT", "9090")
        s = VinzySettings()
        assert s.port == 9090

    def test_env_prefix_overrides_api_prefix(self, monkeypatch):
        monkeypatch.setenv("VINZY_API_PREFIX", "/api/v2")
        s = VinzySettings()
        assert s.api_prefix == "/api/v2"

    def test_env_prefix_overrides_environment(self, monkeypatch):
        monkeypatch.setenv("VINZY_ENVIRONMENT", "production")
        monkeypatch.setenv("VINZY_SECRET_KEY", "prod-secret-key-safe")
        monkeypatch.setenv("VINZY_HMAC_KEY", "prod-hmac-key-safe")
        monkeypatch.setenv("VINZY_API_KEY", "prod-api-key-safe")
        monkeypatch.setenv("VINZY_SUPER_ADMIN_KEY", "prod-super-admin-key-safe")
        s = VinzySettings()
        assert s.environment == "production"

    def test_env_prefix_overrides_hmac_key(self, monkeypatch):
        monkeypatch.setenv("VINZY_HMAC_KEY", "my-custom-hmac")
        s = VinzySettings()
        assert s.hmac_key == "my-custom-hmac"

    def test_unprefixed_env_ignored(self, monkeypatch):
        monkeypatch.setenv("DB_URL", "should-be-ignored")
        s = VinzySettings()
        # Should still have the default, not the unprefixed value
        assert "should-be-ignored" not in s.db_url


class TestDatabaseUrlConfiguration:
    """Test database URL handling."""

    def test_custom_db_url(self):
        s = VinzySettings(db_url="sqlite+aiosqlite:///./custom.db")
        assert s.db_url == "sqlite+aiosqlite:///./custom.db"

    def test_postgres_url(self):
        s = VinzySettings(db_url="postgresql+asyncpg://user:pass@localhost/vinzy")
        assert "postgresql" in s.db_url


class TestApiPrefixDefault:
    """API prefix defaults to empty string."""

    def test_default_is_empty(self):
        s = VinzySettings()
        assert s.api_prefix == ""

    def test_can_be_set(self):
        s = VinzySettings(api_prefix="/v1")
        assert s.api_prefix == "/v1"


class TestSecretKeyRequirements:
    """Secret keys have insecure defaults that trigger warnings/errors."""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        """Remove VINZY_ env vars that leak from other test fixtures."""
        for key in list(os.environ):
            if key.startswith("VINZY_"):
                monkeypatch.delenv(key, raising=False)

    def test_insecure_defaults_exist(self):
        s = VinzySettings()
        assert s.secret_key == _INSECURE_DEFAULTS["secret_key"]
        assert s.hmac_key == _INSECURE_DEFAULTS["hmac_key"]
        assert s.api_key == _INSECURE_DEFAULTS["api_key"]
        assert s.super_admin_key == _INSECURE_DEFAULTS["super_admin_key"]

    def test_development_warns_on_insecure_defaults(self):
        s = VinzySettings(environment="development")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            s.validate_for_production()
            assert len(w) == 1
            assert "insecure" in str(w[0].message).lower()

    def test_production_raises_on_insecure_defaults(self):
        s = VinzySettings(environment="production")
        with pytest.raises(RuntimeError, match="Insecure default values"):
            s.validate_for_production()

    def test_staging_raises_on_insecure_defaults(self):
        s = VinzySettings(environment="staging")
        with pytest.raises(RuntimeError, match="Insecure default values"):
            s.validate_for_production()

    def test_production_ok_with_secure_keys(self):
        s = VinzySettings(
            environment="production",
            secret_key="secure-secret-key-abc",
            hmac_key="secure-hmac-key-xyz",
            api_key="secure-api-key-123",
            super_admin_key="secure-super-admin-456",
        )
        # Should not raise
        s.validate_for_production()

    def test_error_message_lists_insecure_fields(self):
        s = VinzySettings(
            environment="production",
            secret_key="secure-one",
            # Leave hmac_key, api_key, super_admin_key at defaults
        )
        with pytest.raises(RuntimeError) as exc_info:
            s.validate_for_production()
        msg = str(exc_info.value)
        assert "VINZY_HMAC_KEY" in msg
        assert "VINZY_API_KEY" in msg
        assert "VINZY_SECRET_KEY" not in msg  # This one was set securely


class TestCorsSettings:
    """CORS origins configuration."""

    def test_default_cors_origins(self):
        s = VinzySettings()
        assert "http://localhost:3000" in s.cors_origins
        assert "http://localhost:8000" in s.cors_origins

    def test_custom_cors_origins(self):
        s = VinzySettings(cors_origins=["https://gozerai.com"])
        assert s.cors_origins == ["https://gozerai.com"]


class TestHmacKeyring:
    """Test HMAC keyring (multi-version) configuration."""

    def test_default_keyring_from_scalar(self):
        s = VinzySettings(hmac_key="my-key")
        ring = s.hmac_keyring
        assert ring == {0: "my-key"}

    def test_keyring_from_json(self):
        s = VinzySettings(hmac_keys='{"0": "old-key", "1": "new-key"}')
        ring = s.hmac_keyring
        assert ring == {0: "old-key", 1: "new-key"}

    def test_current_hmac_version(self):
        s = VinzySettings(hmac_keys='{"0": "old", "2": "newest"}')
        assert s.current_hmac_version == 2

    def test_current_hmac_key(self):
        s = VinzySettings(hmac_keys='{"0": "old", "1": "new"}')
        assert s.current_hmac_key == "new"

    def test_invalid_json_raises(self):
        s = VinzySettings(hmac_keys="not-json")
        with pytest.raises(ValueError, match="VINZY_HMAC_KEYS must be valid JSON"):
            _ = s.hmac_keyring

    def test_empty_hmac_keys_falls_back_to_scalar(self):
        s = VinzySettings(hmac_key="fallback-key", hmac_keys="")
        ring = s.hmac_keyring
        assert ring == {0: "fallback-key"}


class TestRateLimitSettings:
    """Rate limiting configuration."""

    def test_rate_limit_defaults(self):
        s = VinzySettings()
        assert s.rate_limit_enabled is True
        assert s.rate_limit_per_minute == 60
        assert s.rate_limit_public_per_minute == 30
        assert s.rate_limit_admin_per_minute == 120

    def test_rate_limit_can_be_disabled(self):
        s = VinzySettings(rate_limit_enabled=False)
        assert s.rate_limit_enabled is False
