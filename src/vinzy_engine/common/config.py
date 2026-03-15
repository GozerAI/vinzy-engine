"""Vinzy-Engine configuration via pydantic-settings."""

import json
import warnings
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEFAULTS = {
    "secret_key": "insecure-dev-key-change-me",
    "hmac_key": "insecure-hmac-key-change-me",
    "api_key": "insecure-admin-key-change-me",
    "super_admin_key": "insecure-super-admin-key-change-me",
}


class VinzySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VINZY_")

    environment: str = "development"
    secret_key: str = "insecure-dev-key-change-me"
    hmac_key: str = "insecure-hmac-key-change-me"

    # HMAC keyring — JSON dict mapping version (int) to key string.
    # e.g. '{"0": "old-key", "1": "new-key"}'
    # When set, hmac_key is ignored.  When empty, hmac_key is used as version 0.
    hmac_keys: str = ""

    # Database
    db_url: str = "sqlite+aiosqlite:///./data/vinzy.db"

    # API
    api_title: str = "Vinzy-Engine"
    api_version: str = "0.1.0"
    api_key: str = "insecure-admin-key-change-me"
    super_admin_key: str = "insecure-super-admin-key-change-me"
    host: str = "0.0.0.0"
    port: int = 8080
    api_prefix: str = ""
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8000"]

    # Rate limiting
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 60
    rate_limit_public_per_minute: int = 30
    rate_limit_admin_per_minute: int = 120

    # IP allowlist (empty = allow all)
    ip_allowlist_enabled: bool = False
    ip_allowlist: list[str] = []
    admin_ip_allowlist: list[str] = []

    # Licensing defaults
    default_machines_limit: int = 3
    default_license_days: int = 365
    heartbeat_interval: int = 3600  # seconds

    # Lease settings
    lease_ttl: int = 86400  # 24 hours
    lease_offline_ttl: int = 259200  # 72 hours

    # Pagination
    default_page_size: int = 20
    max_page_size: int = 100

    # Zuultimate integration
    zuultimate_base_url: str = ""
    zuultimate_service_token: str = ""

    # Product callback registry — JSON mapping product codes to webhook URLs
    # e.g. '{"ARC": "https://arclane.cloud/api/billing/provision-complete", "TS": "https://trendscope.io/api/webhook"}'
    product_callbacks: str = ""
    product_callback_token: str = ""

    @property
    def hmac_keyring(self) -> dict[int, str]:
        """Return HMAC keyring as {version_int: key_str}.

        If hmac_keys is set, parse it as JSON.
        Otherwise, fall back to scalar hmac_key as version 0.
        """
        if self.hmac_keys:
            try:
                raw = json.loads(self.hmac_keys)
            except (json.JSONDecodeError, TypeError) as exc:
                raise ValueError(
                    f"VINZY_HMAC_KEYS must be valid JSON (e.g. '{{\"0\": \"key\"}}'), got: {self.hmac_keys!r}"
                ) from exc
            return {int(k): v for k, v in raw.items()}
        return {0: self.hmac_key}

    @property
    def current_hmac_version(self) -> int:
        """Return the highest version number in the keyring."""
        return max(self.hmac_keyring.keys())

    @property
    def current_hmac_key(self) -> str:
        """Return the HMAC key for the current (highest) version."""
        ring = self.hmac_keyring
        return ring[max(ring.keys())]

    def validate_for_production(self) -> None:
        """Raise if insecure defaults are used in non-development environments."""
        insecure_fields = [
            field
            for field, default in _INSECURE_DEFAULTS.items()
            if getattr(self, field) == default
        ]

        if self.environment != "development" and insecure_fields:
            env_vars = ", ".join(f"VINZY_{f.upper()}" for f in insecure_fields)
            raise RuntimeError(
                f"Insecure default values detected in '{self.environment}' environment. "
                f"Set these environment variables to secure values: {env_vars}. "
                "Generate secrets with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )

        if insecure_fields:
            warnings.warn(
                "Using insecure default keys — set VINZY_SECRET_KEY, VINZY_HMAC_KEY, "
                "VINZY_API_KEY, VINZY_SUPER_ADMIN_KEY for production",
                UserWarning,
                stacklevel=2,
            )


@lru_cache
def get_settings() -> VinzySettings:
    settings = VinzySettings()
    settings.validate_for_production()
    return settings
