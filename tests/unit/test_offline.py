"""Tests for offline operation modules (cache, usage tracker, anomaly detection)."""

import asyncio
import time
import pytest

from vinzy_engine.offline.cache import (
    CachedLicense,
    OfflineLicenseCache,
    _compute_integrity,
)
from vinzy_engine.offline.usage_tracker import (
    OfflineUsageEvent,
    OfflineUsageTracker,
    SyncResult,
    SyncStatus,
)
from vinzy_engine.offline.anomaly import (
    OfflineAnomalyDetector,
    OfflineAnomalyRecord,
)


SIGNING_KEY = "test-signing-key"


# ── OfflineLicenseCache ──

class TestOfflineLicenseCache:

    def _make_result(self, **overrides):
        base = {
            "license": {
                "id": "lic-1",
                "key": "ZUL-ABCDE...",
                "status": "active",
                "tier": "pro",
                "product_code": "TSC",
                "customer_id": "cust-1",
                "machines_limit": 5,
                "machines_used": 2,
                "expires_at": "2027-01-01T00:00:00+00:00",
                "entitlements": {},
            },
            "features": ["feature_a", "feature_b"],
        }
        base.update(overrides)
        return base

    def test_cache_and_validate(self):
        cache = OfflineLicenseCache(ttl_seconds=3600, signing_key=SIGNING_KEY)
        result = self._make_result()
        cache.cache_validation("hash1", result)
        assert cache.size == 1

        validated = cache.validate_offline("hash1")
        assert validated is not None
        assert validated["valid"] is True
        assert validated["offline"] is True
        assert "feature_a" in validated["features"]

    def test_cache_miss(self):
        cache = OfflineLicenseCache(signing_key=SIGNING_KEY)
        assert cache.validate_offline("nonexistent") is None
        assert cache.stats["misses"] == 1

    def test_expired_cache_entry(self):
        cache = OfflineLicenseCache(ttl_seconds=0.0, signing_key=SIGNING_KEY)
        cache.cache_validation("hash1", self._make_result())
        # TTL is 0, so entry expires immediately
        result = cache.validate_offline("hash1")
        assert result is None

    def test_expired_license(self):
        cache = OfflineLicenseCache(ttl_seconds=3600, signing_key=SIGNING_KEY)
        result = self._make_result()
        result["license"]["expires_at"] = "2020-01-01T00:00:00+00:00"
        cache.cache_validation("hash1", result)

        validated = cache.validate_offline("hash1")
        assert validated is not None
        assert validated["valid"] is False
        assert validated["code"] == "EXPIRED"

    def test_suspended_license(self):
        cache = OfflineLicenseCache(ttl_seconds=3600, signing_key=SIGNING_KEY)
        result = self._make_result()
        result["license"]["status"] = "suspended"
        cache.cache_validation("hash1", result)

        validated = cache.validate_offline("hash1")
        assert validated is not None
        assert validated["valid"] is False
        assert validated["code"] == "SUSPENDED"

    def test_revoked_license(self):
        cache = OfflineLicenseCache(ttl_seconds=3600, signing_key=SIGNING_KEY)
        result = self._make_result()
        result["license"]["status"] = "revoked"
        cache.cache_validation("hash1", result)

        validated = cache.validate_offline("hash1")
        assert validated["valid"] is False
        assert validated["code"] == "REVOKED"

    def test_integrity_failure(self):
        cache = OfflineLicenseCache(ttl_seconds=3600, signing_key=SIGNING_KEY)
        cache.cache_validation("hash1", self._make_result())
        # Tamper with the cached entry
        entry = cache._store["hash1"]
        entry.integrity_hash = "tampered"

        validated = cache.validate_offline("hash1")
        assert validated is None
        assert cache.stats["integrity_failures"] == 1

    def test_max_size_eviction(self):
        cache = OfflineLicenseCache(ttl_seconds=3600, max_size=3, signing_key=SIGNING_KEY)
        for i in range(5):
            cache.cache_validation(f"hash{i}", self._make_result())
        assert cache.size == 3
        # Oldest entries evicted
        assert cache.validate_offline("hash0") is None
        assert cache.validate_offline("hash1") is None
        assert cache.validate_offline("hash4") is not None

    def test_invalidate(self):
        cache = OfflineLicenseCache(signing_key=SIGNING_KEY)
        cache.cache_validation("hash1", self._make_result())
        assert cache.invalidate("hash1") is True
        assert cache.invalidate("hash1") is False
        assert cache.size == 0

    def test_clear(self):
        cache = OfflineLicenseCache(signing_key=SIGNING_KEY)
        cache.cache_validation("h1", self._make_result())
        cache.cache_validation("h2", self._make_result())
        cache.clear()
        assert cache.size == 0

    def test_cleanup(self):
        cache = OfflineLicenseCache(ttl_seconds=0.0, signing_key=SIGNING_KEY)
        cache.cache_validation("h1", self._make_result())
        cache.cache_validation("h2", self._make_result())
        removed = cache.cleanup()
        assert removed == 2
        assert cache.size == 0

    def test_stats(self):
        cache = OfflineLicenseCache(ttl_seconds=3600, max_size=100, signing_key=SIGNING_KEY)
        cache.cache_validation("h1", self._make_result())
        cache.validate_offline("h1")
        cache.validate_offline("miss")

        stats = cache.stats
        assert stats["size"] == 1
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5

    def test_hit_rate_zero_when_empty(self):
        cache = OfflineLicenseCache(signing_key=SIGNING_KEY)
        assert cache.stats["hit_rate"] == 0.0


# ── OfflineUsageTracker ──

class TestOfflineUsageTracker:

    def test_record_event(self):
        tracker = OfflineUsageTracker()
        event = tracker.record("lic-1", "api_calls", 5.0)
        assert event.license_id == "lic-1"
        assert event.metric == "api_calls"
        assert event.value == 5.0
        assert event.sync_status == SyncStatus.PENDING
        assert tracker.buffer_size == 1

    def test_record_with_metadata(self):
        tracker = OfflineUsageTracker()
        event = tracker.record("lic-1", "tokens", 100.0, metadata={"model": "gpt-4"})
        assert event.metadata["model"] == "gpt-4"

    def test_buffer_overflow_drops_oldest(self):
        tracker = OfflineUsageTracker(max_buffer_size=3)
        for i in range(5):
            tracker.record("lic-1", "calls", float(i))
        assert tracker.buffer_size == 3
        assert tracker.stats["total_dropped"] == 2

    def test_get_pending_events(self):
        tracker = OfflineUsageTracker()
        tracker.record("lic-1", "a", 1.0)
        tracker.record("lic-2", "b", 2.0)
        tracker.record("lic-1", "c", 3.0)

        all_pending = tracker.get_pending_events()
        assert len(all_pending) == 3

        lic1_pending = tracker.get_pending_events(license_id="lic-1")
        assert len(lic1_pending) == 2

    def test_get_all_events(self):
        tracker = OfflineUsageTracker()
        tracker.record("lic-1", "a", 1.0)
        tracker.record("lic-1", "b", 2.0)
        events = tracker.get_all_events()
        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_sync_success(self):
        tracker = OfflineUsageTracker()
        tracker.record("lic-1", "calls", 5.0)

        class MockUsageService:
            async def record_usage(self, session, raw_key, metric, value, metadata):
                pass

        result = await tracker.sync(MockUsageService(), None)
        assert result.synced == 1
        assert result.failed == 0
        assert tracker.get_pending_count() == 0

    @pytest.mark.asyncio
    async def test_sync_failure_retries(self):
        tracker = OfflineUsageTracker(max_sync_attempts=3)
        tracker.record("lic-1", "calls", 5.0)

        class FailingService:
            async def record_usage(self, session, raw_key, metric, value, metadata):
                raise RuntimeError("DB unavailable")

        result = await tracker.sync(FailingService(), None)
        assert result.failed == 1
        assert result.synced == 0
        assert tracker.get_pending_count() == 1

    @pytest.mark.asyncio
    async def test_sync_by_license(self):
        tracker = OfflineUsageTracker()
        tracker.record("lic-1", "a", 1.0)
        tracker.record("lic-2", "b", 2.0)

        calls = []
        async def callback(metric, value, metadata):
            calls.append((metric, value))

        result = await tracker.sync_by_license("lic-1", callback)
        assert result.synced == 1
        assert len(calls) == 1
        assert calls[0] == ("a", 1.0)

    def test_purge_failed(self):
        tracker = OfflineUsageTracker(max_sync_attempts=1)
        event = tracker.record("lic-1", "a", 1.0)
        event.sync_status = SyncStatus.FAILED
        event.sync_attempts = 1
        removed = tracker.purge_failed()
        assert removed == 1

    def test_clear(self):
        tracker = OfflineUsageTracker()
        tracker.record("lic-1", "a", 1.0)
        tracker.clear()
        assert tracker.buffer_size == 0

    def test_stats(self):
        tracker = OfflineUsageTracker(max_buffer_size=1000)
        tracker.record("lic-1", "a", 1.0)
        stats = tracker.stats
        assert stats["buffer_size"] == 1
        assert stats["total_recorded"] == 1
        assert stats["pending_count"] == 1
        assert stats["is_syncing"] is False

    @pytest.mark.asyncio
    async def test_sync_prevents_concurrent(self):
        tracker = OfflineUsageTracker()
        tracker.record("lic-1", "a", 1.0)

        class SlowService:
            async def record_usage(self, session, raw_key, metric, value, metadata):
                await asyncio.sleep(0.01)

        tracker._is_syncing = True
        result = await tracker.sync(SlowService(), None)
        assert result.total == 0  # skipped because already syncing


# ── OfflineAnomalyDetector ──

class TestOfflineAnomalyDetector:

    def test_observe_normal(self):
        detector = OfflineAnomalyDetector(min_history=3)
        # Seed some normal history
        for v in [10.0, 11.0, 10.5, 10.2, 10.8]:
            result = detector.observe("lic-1", "calls", v)
        # Normal value should not trigger anomaly
        result = detector.observe("lic-1", "calls", 10.3)
        assert result is None

    def test_observe_anomaly(self):
        detector = OfflineAnomalyDetector(min_history=3)
        for v in [10.0, 10.0, 10.0, 10.0, 10.0]:
            detector.observe("lic-1", "calls", v)
        # Huge spike
        result = detector.observe("lic-1", "calls", 1000.0)
        assert result is not None
        assert result.severity in ("medium", "high", "critical")
        assert result.license_id == "lic-1"

    def test_observe_insufficient_history(self):
        detector = OfflineAnomalyDetector(min_history=10)
        result = detector.observe("lic-1", "calls", 100.0)
        assert result is None  # not enough history

    def test_bulk_observe(self):
        detector = OfflineAnomalyDetector(min_history=3)
        # Seed
        detector.seed_history("lic-1", "calls", [10.0] * 10)
        anomalies = detector.bulk_observe("lic-1", "calls", [10.0, 10.1, 500.0])
        assert len(anomalies) >= 1  # at least the 500.0 spike

    def test_seed_history(self):
        detector = OfflineAnomalyDetector()
        detector.seed_history("lic-1", "m", [1.0, 2.0, 3.0])
        history = detector.get_history("lic-1", "m")
        assert history == [1.0, 2.0, 3.0]

    def test_get_baseline(self):
        detector = OfflineAnomalyDetector()
        detector.seed_history("lic-1", "m", [10.0, 10.0, 10.0])
        mean, stddev = detector.get_baseline("lic-1", "m")
        assert mean == 10.0
        assert stddev == 0.0  # all same values

    def test_get_baseline_empty(self):
        detector = OfflineAnomalyDetector()
        mean, stddev = detector.get_baseline("nonexistent", "m")
        assert mean == 0.0 and stddev == 0.0

    def test_get_anomalies_filtered(self):
        detector = OfflineAnomalyDetector(min_history=3)
        detector.seed_history("lic-1", "calls", [10.0] * 10)
        detector.observe("lic-1", "calls", 1000.0)
        detector.seed_history("lic-2", "calls", [5.0] * 10)
        detector.observe("lic-2", "calls", 500.0)

        all_records = detector.get_anomalies()
        assert len(all_records) >= 2

        lic1_only = detector.get_anomalies(license_id="lic-1")
        assert all(r.license_id == "lic-1" for r in lic1_only)

    def test_get_unsynced_and_mark_synced(self):
        detector = OfflineAnomalyDetector(min_history=3)
        detector.seed_history("lic-1", "calls", [10.0] * 10)
        detector.observe("lic-1", "calls", 1000.0)

        unsynced = detector.get_unsynced_records()
        assert len(unsynced) >= 1
        assert all(not r.synced for r in unsynced)

        count = detector.mark_synced(unsynced)
        assert count >= 1
        assert len(detector.get_unsynced_records()) == 0

    def test_window_size_trimming(self):
        detector = OfflineAnomalyDetector(window_size=5)
        for v in range(20):
            detector.observe("lic-1", "m", float(v))
        history = detector.get_history("lic-1", "m")
        assert len(history) == 5

    def test_clear(self):
        detector = OfflineAnomalyDetector()
        detector.seed_history("lic-1", "m", [1.0, 2.0])
        detector.observe("lic-1", "m", 100.0)
        detector.clear()
        assert detector.get_history("lic-1", "m") == []
        assert detector.stats["stored_records"] == 0

    def test_clear_history_by_license(self):
        detector = OfflineAnomalyDetector()
        detector.seed_history("lic-1", "m", [1.0])
        detector.seed_history("lic-2", "m", [2.0])
        detector.clear_history("lic-1")
        assert detector.get_history("lic-1", "m") == []
        assert detector.get_history("lic-2", "m") == [2.0]

    def test_stats(self):
        detector = OfflineAnomalyDetector()
        detector.seed_history("lic-1", "m", [10.0] * 5)
        detector.observe("lic-1", "m", 10.0)

        stats = detector.stats
        assert stats["tracked_pairs"] >= 1
        assert stats["total_scanned"] >= 1

    def test_max_records_limit(self):
        detector = OfflineAnomalyDetector(min_history=3, max_records=5)
        detector.seed_history("lic-1", "m", [10.0] * 10)
        for _ in range(20):
            detector.observe("lic-1", "m", 1000.0)
        assert len(detector._records) <= 5
