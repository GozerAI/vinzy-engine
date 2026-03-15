"""Self-healing license validation.

Provides fallback validation when the database is unavailable,
using cached results and tracking DB health state."""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from vinzy_engine.common.caching import get_validation_cache
from vinzy_engine.keygen.generator import key_hash

logger = logging.getLogger(__name__)


@dataclass
class ValidationFallbackResult:
    """Result of a self-healing validation attempt."""
    valid: bool
    source: str  # "database" or "cache"
    data: dict[str, Any] = field(default_factory=dict)
    db_healthy: bool = True
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "source": self.source,
            "data": self.data,
            "db_healthy": self.db_healthy,
            "error": self.error,
        }


class SelfHealingValidator:
    """Self-healing license validator with DB fallback to cache.

    Tracks database health state and automatically falls back to cached
    validation results when the DB is unavailable. Periodically probes
    the DB to detect recovery."""

    def __init__(self, health_check_interval: float = 30.0):
        self._db_healthy = True
        self._last_health_check = 0.0
        self._health_check_interval = health_check_interval
        self._consecutive_failures = 0
        self._total_fallbacks = 0
        self._last_fallback_at: datetime | None = None

    @property
    def db_healthy(self) -> bool:
        return self._db_healthy

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "db_healthy": self._db_healthy,
            "consecutive_failures": self._consecutive_failures,
            "total_fallbacks": self._total_fallbacks,
            "last_fallback_at": self._last_fallback_at.isoformat() if self._last_fallback_at else None,
        }

    def _should_probe_db(self) -> bool:
        """Check if enough time has passed to re-probe the database."""
        if self._db_healthy:
            return True
        return (time.monotonic() - self._last_health_check) >= self._health_check_interval

    def _mark_db_healthy(self) -> None:
        if not self._db_healthy:
            logger.info("Database connection restored after %d failures", self._consecutive_failures)
        self._db_healthy = True
        self._consecutive_failures = 0
        self._last_health_check = time.monotonic()

    def _mark_db_unhealthy(self, error: str) -> None:
        self._db_healthy = False
        self._consecutive_failures += 1
        self._last_health_check = time.monotonic()
        if self._consecutive_failures == 1:
            logger.error("Database became unavailable: %s", error)
        elif self._consecutive_failures % 10 == 0:
            logger.error("Database still unavailable after %d failures: %s", self._consecutive_failures, error)

    async def validate(self, raw_key: str, licensing_service=None, session=None) -> ValidationFallbackResult:
        """Validate a license key with DB fallback to cache.

        Tries the database first via licensing_service.validate_license().
        If the DB is unavailable, falls back to cached validation results."""
        hashed = key_hash(raw_key)
        cache = get_validation_cache()

        # Try DB validation if healthy or probe interval elapsed
        if licensing_service is not None and session is not None and self._should_probe_db():
            try:
                result = await licensing_service.validate_license(session, raw_key)
                self._mark_db_healthy()
                # Cache the result for future fallback
                cache.set(f"val:{hashed}", result)
                return ValidationFallbackResult(
                    valid=result.get("valid", False),
                    source="database",
                    data=result,
                    db_healthy=True,
                )
            except Exception as exc:
                error_str = str(exc)
                # Distinguish validation errors from DB errors
                from vinzy_engine.common.exceptions import (
                    InvalidKeyError, LicenseExpiredError, LicenseNotFoundError, LicenseSuspendedError,
                )
                if isinstance(exc, (InvalidKeyError, LicenseNotFoundError, LicenseExpiredError, LicenseSuspendedError)):
                    # These are legitimate validation failures, DB is fine
                    self._mark_db_healthy()
                    return ValidationFallbackResult(
                        valid=False, source="database", db_healthy=True, error=error_str,
                    )
                # DB connectivity error -- fall through to cache
                self._mark_db_unhealthy(error_str)

        # Fallback to cache
        cached = cache.get(f"val:{hashed}")
        if cached is not None:
            self._total_fallbacks += 1
            self._last_fallback_at = datetime.now(timezone.utc)
            logger.warning("Using cached validation for key %s... (DB unavailable)", raw_key[:8])
            return ValidationFallbackResult(
                valid=cached.get("valid", False),
                source="cache",
                data=cached,
                db_healthy=self._db_healthy,
            )

        # No cache entry available
        return ValidationFallbackResult(
            valid=False, source="none", db_healthy=self._db_healthy,
            error="Database unavailable and no cached result",
        )


_self_healing_validator: SelfHealingValidator | None = None


def get_self_healing_validator() -> SelfHealingValidator:
    """Get the singleton self-healing validator."""
    global _self_healing_validator
    if _self_healing_validator is None:
        _self_healing_validator = SelfHealingValidator()
    return _self_healing_validator


def reset_self_healing_validator() -> None:
    """Reset singleton (for testing)."""
    global _self_healing_validator
    _self_healing_validator = None
