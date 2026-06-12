"""Offline license validation cache.

Caches validated license data locally so that license checks can succeed
even when the database or upstream service is unreachable.  Each cached
entry includes the full validation payload, a TTL, and HMAC integrity
verification to prevent tampering.
"""

import hashlib
import hmac
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class CachedLicense:
    """A locally cached license validation result."""

    license_id: str
    key_hash: str
    status: str
    tier: str
    product_code: str
    customer_id: str
    features: list[str]
    entitlements: dict[str, Any]
    machines_limit: int
    machines_used: int
    expires_at: Optional[str]
    cached_at: float = field(default_factory=time.monotonic)
    cache_expires_at: float = 0.0
    integrity_hash: str = ""

    def is_expired(self) -> bool:
        return time.monotonic() > self.cache_expires_at

    def is_license_expired(self) -> bool:
        if not self.expires_at:
            return False
        try:
            exp = datetime.fromisoformat(self.expires_at)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            return exp < datetime.now(timezone.utc)
        except (ValueError, TypeError):
            return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "license_id": self.license_id,
            "key_hash": self.key_hash,
            "status": self.status,
            "tier": self.tier,
            "product_code": self.product_code,
            "customer_id": self.customer_id,
            "features": self.features,
            "entitlements": self.entitlements,
            "machines_limit": self.machines_limit,
            "machines_used": self.machines_used,
            "expires_at": self.expires_at,
            "cached_at": self.cached_at,
            "cache_expires_at": self.cache_expires_at,
        }

    @classmethod
    def from_validation_result(
        cls, result: dict[str, Any], ttl_seconds: float, signing_key: str,
    ) -> "CachedLicense":
        lic = result.get("license", {})
        now = time.monotonic()
        expires_at_raw = lic.get("expires_at")
        if isinstance(expires_at_raw, datetime):
            expires_at_str = expires_at_raw.isoformat()
        elif expires_at_raw is not None:
            expires_at_str = str(expires_at_raw)
        else:
            expires_at_str = None

        entry = cls(
            license_id=lic.get("id", ""),
            key_hash=lic.get("key", ""),
            status=lic.get("status", ""),
            tier=lic.get("tier", ""),
            product_code=lic.get("product_code", ""),
            customer_id=lic.get("customer_id", ""),
            features=result.get("features", []),
            entitlements=lic.get("entitlements", {}),
            machines_limit=lic.get("machines_limit", 0),
            machines_used=lic.get("machines_used", 0),
            expires_at=expires_at_str,
            cached_at=now,
            cache_expires_at=now + ttl_seconds,
        )
        entry.integrity_hash = _compute_integrity(entry, signing_key)
        return entry


def _compute_integrity(entry: CachedLicense, signing_key: str) -> str:
    payload = (
        f"{entry.license_id}:{entry.key_hash}:{entry.status}:"
        f"{entry.tier}:{entry.product_code}:{entry.customer_id}"
    )
    return hmac.new(
        signing_key.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _verify_integrity(entry: CachedLicense, signing_key: str) -> bool:
    expected = _compute_integrity(entry, signing_key)
    return hmac.compare_digest(expected, entry.integrity_hash)


class OfflineLicenseCache:
    """In-memory cache of validated licenses for offline use.

    Entries have a configurable TTL (default 72h) and are integrity-signed
    with an HMAC to prevent local tampering.
    """

    def __init__(
        self,
        ttl_seconds: float = 259_200.0,
        max_size: int = 50_000,
        signing_key: str = "",
    ):
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._signing_key = signing_key
        self._store: OrderedDict[str, CachedLicense] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._integrity_failures = 0

    def cache_validation(self, key_hash: str, result: dict[str, Any]) -> CachedLicense:
        entry = CachedLicense.from_validation_result(result, self._ttl, self._signing_key)
        if key_hash in self._store:
            self._store.move_to_end(key_hash)
        self._store[key_hash] = entry
        while len(self._store) > self._max_size:
            self._store.popitem(last=False)
        return entry

    def validate_offline(self, key_hash: str) -> Optional[dict[str, Any]]:
        entry = self._store.get(key_hash)
        if entry is None:
            self._misses += 1
            return None
        if entry.is_expired():
            del self._store[key_hash]
            self._misses += 1
            return None
        if not _verify_integrity(entry, self._signing_key):
            del self._store[key_hash]
            self._integrity_failures += 1
            self._misses += 1
            logger.warning("Integrity check failed for cached license %s", entry.license_id)
            return None
        if entry.is_license_expired():
            self._misses += 1
            return {"valid": False, "code": "EXPIRED", "message": "License has expired (offline cache)", "offline": True, "license": entry.to_dict()}
        if entry.status in ("suspended", "revoked", "expired"):
            self._misses += 1
            return {"valid": False, "code": entry.status.upper(), "message": f"License is {entry.status} (offline cache)", "offline": True, "license": entry.to_dict()}
        self._store.move_to_end(key_hash)
        self._hits += 1
        return {"valid": True, "code": "OK", "message": "License is valid (offline cache)", "offline": True, "license": entry.to_dict(), "features": entry.features, "entitlements": entry.entitlements}

    def invalidate(self, key_hash: str) -> bool:
        if key_hash in self._store:
            del self._store[key_hash]
            return True
        return False

    def clear(self) -> None:
        self._store.clear()

    def cleanup(self) -> int:
        expired = [k for k, v in self._store.items() if v.is_expired()]
        for k in expired:
            del self._store[k]
        return len(expired)

    @property
    def size(self) -> int:
        return len(self._store)

    @property
    def stats(self) -> dict[str, Any]:
        total = self._hits + self._misses
        return {"size": self.size, "max_size": self._max_size, "ttl_seconds": self._ttl, "hits": self._hits, "misses": self._misses, "hit_rate": round(self._hits / total, 4) if total > 0 else 0.0, "integrity_failures": self._integrity_failures}
