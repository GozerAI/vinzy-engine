"""In-memory caching utilities for Vinzy-Engine.

Provides TTL-based caches for license validation, HMAC computations,
entitlement resolution, tenant configuration, and webhook delivery status.
"""

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable, Optional

logger = logging.getLogger(__name__)


class TTLCache:
    """Thread-safe in-memory cache with TTL expiration and max-size eviction.

    Entries are evicted on access (lazy) and via periodic cleanup.
    When max_size is reached, the oldest entry is evicted (LRU-like via OrderedDict).
    """

    def __init__(self, ttl_seconds: float = 60.0, max_size: int = 10_000):
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        """Retrieve a value if it exists and hasn't expired."""
        entry = self._store.get(key)
        if entry is None:
            self._misses += 1
            return None

        expires_at, value = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            self._misses += 1
            return None

        # Move to end for LRU ordering
        self._store.move_to_end(key)
        self._hits += 1
        return value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Store a value with optional per-entry TTL override."""
        effective_ttl = ttl if ttl is not None else self._ttl
        expires_at = time.monotonic() + effective_ttl

        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = (expires_at, value)

        # Evict oldest if over max size
        while len(self._store) > self._max_size:
            self._store.popitem(last=False)

    def invalidate(self, key: str) -> bool:
        """Remove a specific key. Returns True if it existed."""
        if key in self._store:
            del self._store[key]
            return True
        return False

    def invalidate_prefix(self, prefix: str) -> int:
        """Remove all keys starting with prefix. Returns count removed."""
        to_remove = [k for k in self._store if k.startswith(prefix)]
        for k in to_remove:
            del self._store[k]
        return len(to_remove)

    def clear(self) -> None:
        """Remove all entries."""
        self._store.clear()

    def cleanup(self) -> int:
        """Remove all expired entries. Returns count removed."""
        now = time.monotonic()
        expired = [k for k, (exp, _) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]
        return len(expired)

    @property
    def size(self) -> int:
        return len(self._store)

    @property
    def stats(self) -> dict[str, Any]:
        total = self._hits + self._misses
        return {
            "size": self.size,
            "max_size": self._max_size,
            "ttl_seconds": self._ttl,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 4) if total > 0 else 0.0,
        }


# ---------------------------------------------------------------------------
# Singleton caches for different domains
# ---------------------------------------------------------------------------

_validation_cache: TTLCache | None = None
_hmac_cache: TTLCache | None = None
_entitlement_cache: TTLCache | None = None
_tenant_config_cache: TTLCache | None = None
_webhook_status_cache: TTLCache | None = None


def get_validation_cache() -> TTLCache:
    """Cache for license validation responses (keyed by key_hash)."""
    global _validation_cache
    if _validation_cache is None:
        _validation_cache = TTLCache(ttl_seconds=30.0, max_size=10_000)
    return _validation_cache


def get_hmac_cache() -> TTLCache:
    """Cache for HMAC computation results (keyed by key string)."""
    global _hmac_cache
    if _hmac_cache is None:
        _hmac_cache = TTLCache(ttl_seconds=300.0, max_size=50_000)
    return _hmac_cache


def get_entitlement_cache() -> TTLCache:
    """Cache for resolved entitlements (keyed by license_id or customer_id)."""
    global _entitlement_cache
    if _entitlement_cache is None:
        _entitlement_cache = TTLCache(ttl_seconds=60.0, max_size=10_000)
    return _entitlement_cache


def get_tenant_config_cache() -> TTLCache:
    """Cache for tenant configuration (keyed by tenant_id)."""
    global _tenant_config_cache
    if _tenant_config_cache is None:
        _tenant_config_cache = TTLCache(ttl_seconds=120.0, max_size=1_000)
    return _tenant_config_cache


def get_webhook_status_cache() -> TTLCache:
    """Cache for webhook delivery statuses (keyed by delivery_id)."""
    global _webhook_status_cache
    if _webhook_status_cache is None:
        _webhook_status_cache = TTLCache(ttl_seconds=60.0, max_size=10_000)
    return _webhook_status_cache


def reset_all_caches() -> None:
    """Reset all singleton caches (for testing)."""
    global _validation_cache, _hmac_cache, _entitlement_cache
    global _tenant_config_cache, _webhook_status_cache
    _validation_cache = None
    _hmac_cache = None
    _entitlement_cache = None
    _tenant_config_cache = None
    _webhook_status_cache = None


# ---------------------------------------------------------------------------
# Pub/Sub for cache invalidation (in-process)
# ---------------------------------------------------------------------------

class CacheInvalidationBus:
    """Simple in-process pub/sub for cache invalidation signals.

    Subscribers register for specific channels (e.g., 'tenant', 'license').
    When a publisher sends an invalidation event, all subscribers on that
    channel are notified with the key to invalidate.
    """

    def __init__(self):
        self._subscribers: dict[str, list[Callable[[str], None]]] = {}

    def subscribe(self, channel: str, callback: Callable[[str], None]) -> None:
        """Register a callback for invalidation events on a channel."""
        if channel not in self._subscribers:
            self._subscribers[channel] = []
        self._subscribers[channel].append(callback)

    def publish(self, channel: str, key: str) -> int:
        """Publish an invalidation event. Returns number of subscribers notified."""
        callbacks = self._subscribers.get(channel, [])
        for cb in callbacks:
            try:
                cb(key)
            except Exception:
                logger.exception("Cache invalidation callback failed for channel=%s key=%s", channel, key)
        return len(callbacks)

    def clear(self) -> None:
        """Remove all subscriptions."""
        self._subscribers.clear()


_invalidation_bus: CacheInvalidationBus | None = None


def get_invalidation_bus() -> CacheInvalidationBus:
    """Get the singleton invalidation bus."""
    global _invalidation_bus
    if _invalidation_bus is None:
        _invalidation_bus = CacheInvalidationBus()
        # Wire up default subscriptions
        _wire_default_subscriptions(_invalidation_bus)
    return _invalidation_bus


def _wire_default_subscriptions(bus: CacheInvalidationBus) -> None:
    """Set up default invalidation routes."""

    def _invalidate_tenant_config(key: str) -> None:
        cache = get_tenant_config_cache()
        cache.invalidate(key)

    def _invalidate_license_validation(key: str) -> None:
        cache = get_validation_cache()
        cache.invalidate(key)

    def _invalidate_entitlements(key: str) -> None:
        cache = get_entitlement_cache()
        cache.invalidate(key)
        # Also invalidate validation cache for this license
        cache2 = get_validation_cache()
        cache2.invalidate_prefix(f"license:{key}")

    bus.subscribe("tenant", _invalidate_tenant_config)
    bus.subscribe("license", _invalidate_license_validation)
    bus.subscribe("entitlement", _invalidate_entitlements)


def reset_invalidation_bus() -> None:
    """Reset the singleton bus (for testing)."""
    global _invalidation_bus
    _invalidation_bus = None
