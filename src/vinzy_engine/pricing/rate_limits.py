"""Tiered API rate limits per plan.

Item 263: Different rate limits for different subscription tiers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RateLimitConfig:
    """Rate limit configuration for a tier."""
    requests_per_minute: int
    requests_per_hour: int
    requests_per_day: int
    burst_limit: int  # max concurrent
    throttle_delay_ms: int = 0  # delay added when nearing limit


# Default rate limits per tier
TIER_RATE_LIMITS: dict[str, RateLimitConfig] = {
    "community": RateLimitConfig(
        requests_per_minute=10,
        requests_per_hour=200,
        requests_per_day=1_000,
        burst_limit=5,
    ),
    "pro": RateLimitConfig(
        requests_per_minute=60,
        requests_per_hour=2_000,
        requests_per_day=20_000,
        burst_limit=20,
    ),
    "growth": RateLimitConfig(
        requests_per_minute=200,
        requests_per_hour=10_000,
        requests_per_day=100_000,
        burst_limit=50,
    ),
    "scale": RateLimitConfig(
        requests_per_minute=1_000,
        requests_per_hour=50_000,
        requests_per_day=500_000,
        burst_limit=200,
    ),
}
# Backward compat
TIER_RATE_LIMITS["business"] = TIER_RATE_LIMITS["growth"]
TIER_RATE_LIMITS["enterprise"] = TIER_RATE_LIMITS["scale"]


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""
    allowed: bool
    tier: str
    limit: int
    remaining: int
    reset_at: float  # epoch timestamp
    retry_after_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class _TokenBucket:
    """Simple token-bucket rate limiter."""

    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.tokens = float(capacity)
        self.refill_rate = refill_rate  # tokens per second
        self.last_refill = time.monotonic()

    def consume(self, tokens: int = 1) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    @property
    def remaining(self) -> int:
        return max(0, int(self.tokens))


class TieredRateLimiter:
    """Rate limiter that enforces different limits per subscription tier."""

    def __init__(self, custom_limits: dict[str, RateLimitConfig] | None = None):
        self._limits = dict(TIER_RATE_LIMITS)
        if custom_limits:
            self._limits.update(custom_limits)
        # Per-key token buckets: key = (license_id, window)
        self._buckets: dict[str, _TokenBucket] = {}

    def get_limits(self, tier: str) -> RateLimitConfig:
        return self._limits.get(tier, self._limits["community"])

    def _get_bucket(self, key: str, capacity: int, refill_per_sec: float) -> _TokenBucket:
        if key not in self._buckets:
            self._buckets[key] = _TokenBucket(capacity, refill_per_sec)
        return self._buckets[key]

    def check_rate_limit(self, license_id: str, tier: str) -> RateLimitResult:
        """Check if a request is allowed under the tier's rate limit."""
        config = self.get_limits(tier)

        # Use per-minute bucket as primary limiter
        bucket_key = f"{license_id}:rpm"
        refill_rate = config.requests_per_minute / 60.0
        bucket = self._get_bucket(bucket_key, config.requests_per_minute, refill_rate)

        allowed = bucket.consume(1)
        reset_at = time.time() + (60.0 if not allowed else 0)

        return RateLimitResult(
            allowed=allowed,
            tier=tier,
            limit=config.requests_per_minute,
            remaining=bucket.remaining,
            reset_at=reset_at,
            retry_after_ms=1000 if not allowed else 0,
        )

    def check_burst(self, license_id: str, tier: str) -> RateLimitResult:
        """Check concurrent/burst limit."""
        config = self.get_limits(tier)
        bucket_key = f"{license_id}:burst"
        # Burst bucket refills quickly (1 token per 100ms)
        bucket = self._get_bucket(bucket_key, config.burst_limit, 10.0)
        allowed = bucket.consume(1)
        return RateLimitResult(
            allowed=allowed,
            tier=tier,
            limit=config.burst_limit,
            remaining=bucket.remaining,
            reset_at=time.time() + (0.1 if not allowed else 0),
            retry_after_ms=100 if not allowed else 0,
        )

    def reset(self, license_id: str | None = None) -> None:
        """Reset rate limit state."""
        if license_id:
            keys = [k for k in self._buckets if k.startswith(f"{license_id}:")]
            for k in keys:
                del self._buckets[k]
        else:
            self._buckets.clear()
