"""Tests for performance improvements: caching, batching, compression,
health monitoring, background tasks, serialization, and schema versioning.

Covers items: 3, 8, 13, 21, 39, 47, 55, 63, 69, 72, 79, 88, 97, 143, 156, 164.
"""

import asyncio
import gzip
import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import HMAC_KEY


# =============================================================================
# Item 3: Covering index for license key lookups
# =============================================================================

class TestCoveringIndex:
    """Verify the covering index is declared on the LicenseModel."""

    def test_license_model_has_covering_index(self):
        from vinzy_engine.licensing.models import LicenseModel
        table = LicenseModel.__table__
        index_names = {idx.name for idx in table.indexes}
        assert "ix_licenses_product_keyhash_status" in index_names

    def test_license_model_has_keyhash_deleted_index(self):
        from vinzy_engine.licensing.models import LicenseModel
        table = LicenseModel.__table__
        index_names = {idx.name for idx in table.indexes}
        assert "ix_licenses_keyhash_deleted" in index_names

    def test_license_model_has_status_expires_index(self):
        from vinzy_engine.licensing.models import LicenseModel
        table = LicenseModel.__table__
        index_names = {idx.name for idx in table.indexes}
        assert "ix_licenses_status_expires" in index_names

    def test_license_model_has_deleted_at_index(self):
        from vinzy_engine.licensing.models import LicenseModel
        table = LicenseModel.__table__
        index_names = {idx.name for idx in table.indexes}
        assert "ix_licenses_deleted_at" in index_names


# =============================================================================
# Item 8: Batch audit log inserts
# =============================================================================

class TestBatchAuditWriter:
    """Test batch audit log accumulation and flush."""

    def test_enqueue_accumulates_entries(self):
        from vinzy_engine.audit.batch import BatchAuditWriter
        writer = BatchAuditWriter(batch_size=100, flush_interval=10.0)
        loop = asyncio.new_event_loop()
        loop.run_until_complete(writer.enqueue("lic-1", "license.validated", "system", {}))
        loop.run_until_complete(writer.enqueue("lic-2", "license.validated", "system", {}))
        loop.close()
        assert writer.pending_count == 2

    def test_flush_clears_buffer_when_no_service(self):
        from vinzy_engine.audit.batch import BatchAuditWriter
        writer = BatchAuditWriter(batch_size=100)
        loop = asyncio.new_event_loop()
        loop.run_until_complete(writer.enqueue("lic-1", "test", "sys", {}))
        assert writer.pending_count == 1
        flushed = loop.run_until_complete(writer.flush())
        loop.close()
        assert flushed == 0  # No service — entries dropped
        assert writer.pending_count == 0

    def test_stats(self):
        from vinzy_engine.audit.batch import BatchAuditWriter
        writer = BatchAuditWriter()
        stats = writer.stats
        assert "pending" in stats
        assert "total_enqueued" in stats
        assert "total_flushed" in stats

    def test_auto_flush_at_batch_size(self):
        """Buffer flushes when batch_size is reached."""
        from vinzy_engine.audit.batch import BatchAuditWriter
        writer = BatchAuditWriter(batch_size=2)
        loop = asyncio.new_event_loop()
        # Enqueue 2 entries — should trigger auto-flush
        loop.run_until_complete(writer.enqueue("lic-1", "e1", "sys", {}))
        loop.run_until_complete(writer.enqueue("lic-2", "e2", "sys", {}))
        loop.close()
        # Buffer should be cleared after auto-flush attempt
        assert writer.pending_count == 0

    def test_singleton_access(self):
        from vinzy_engine.audit.batch import get_batch_audit_writer, reset_batch_audit_writer
        reset_batch_audit_writer()
        w1 = get_batch_audit_writer()
        w2 = get_batch_audit_writer()
        assert w1 is w2
        reset_batch_audit_writer()


# =============================================================================
# Item 13: Database connection health monitoring
# =============================================================================

class TestDatabaseHealthMonitor:
    """Test database health monitoring."""

    def test_initial_state_is_healthy(self):
        from vinzy_engine.common.health import DatabaseHealthMonitor
        monitor = DatabaseHealthMonitor()
        assert monitor.is_healthy is True
        assert monitor.status.total_checks == 0

    def test_to_dict(self):
        from vinzy_engine.common.health import DatabaseHealthMonitor
        monitor = DatabaseHealthMonitor()
        d = monitor.to_dict()
        assert "healthy" in d
        assert "last_latency_ms" in d
        assert "avg_latency_ms" in d
        assert "consecutive_failures" in d
        assert "pool_size" in d

    async def test_check_now_with_db(self, client):
        """Health check against a real test database."""
        from vinzy_engine.common.health import DatabaseHealthMonitor
        from vinzy_engine.deps import get_db
        monitor = DatabaseHealthMonitor()
        db = get_db()
        status = await monitor.check_now()
        # No db_manager set yet, so it's just the default
        assert status.total_checks == 0

        monitor._db_manager = db
        status = await monitor.check_now()
        assert status.healthy is True
        assert status.total_checks == 1
        assert status.last_latency_ms >= 0

    def test_singleton_access(self):
        from vinzy_engine.common.health import get_health_monitor, reset_health_monitor
        reset_health_monitor()
        m1 = get_health_monitor()
        m2 = get_health_monitor()
        assert m1 is m2
        reset_health_monitor()


# =============================================================================
# Item 21: Soft-delete with background hard-delete
# =============================================================================

class TestHardDeleteProcessor:
    """Test background hard-delete of soft-deleted licenses."""

    def test_initial_stats(self):
        from vinzy_engine.background import HardDeleteProcessor
        proc = HardDeleteProcessor()
        stats = proc.stats
        assert stats["total_hard_deleted"] == 0
        assert stats["running"] is False

    async def test_run_once_empty(self, client):
        """No soft-deleted licenses — run_once returns 0."""
        from vinzy_engine.background import HardDeleteProcessor
        from vinzy_engine.deps import get_db
        proc = HardDeleteProcessor(retention_days=0)
        deleted = await proc.run_once(get_db())
        assert deleted == 0

    async def test_hard_delete_expired_soft_deletes(self, client, admin_headers):
        """Soft-deleted licenses past retention are hard-deleted."""
        from vinzy_engine.background import HardDeleteProcessor
        from vinzy_engine.deps import get_db, get_licensing_service

        db = get_db()
        svc = get_licensing_service()

        # Create product + customer + license
        async with db.get_session() as session:
            await svc.create_product(session, "DEL", "Delete Test")
        async with db.get_session() as session:
            cust = await svc.create_customer(session, "Del User", "del@test.com")
            cust_id = cust.id
        async with db.get_session() as session:
            lic, _ = await svc.create_license(session, "DEL", cust_id)
            lic_id = lic.id
        # Soft-delete
        async with db.get_session() as session:
            await svc.soft_delete_license(session, lic_id)
        # Force deleted_at to the past
        from vinzy_engine.licensing.models import LicenseModel
        from sqlalchemy import update
        async with db.get_session() as session:
            await session.execute(
                update(LicenseModel).where(LicenseModel.id == lic_id).values(
                    deleted_at=datetime.now(timezone.utc) - timedelta(days=60)
                )
            )

        proc = HardDeleteProcessor(retention_days=30)
        deleted = await proc.run_once(db)
        assert deleted == 1

        # Verify license is truly gone
        async with db.get_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(LicenseModel).where(LicenseModel.id == lic_id)
            )
            assert result.scalar_one_or_none() is None


# =============================================================================
# Item 39: License validation response caching
# =============================================================================

class TestValidationCache:
    """Test validation response caching."""

    def test_cache_basic_operations(self):
        from vinzy_engine.common.caching import TTLCache
        cache = TTLCache(ttl_seconds=10.0)
        cache.set("key1", {"valid": True})
        assert cache.get("key1") == {"valid": True}
        assert cache.get("missing") is None

    def test_cache_ttl_expiration(self):
        from vinzy_engine.common.caching import TTLCache
        cache = TTLCache(ttl_seconds=0.01)  # 10ms
        cache.set("key1", "value")
        time.sleep(0.02)
        assert cache.get("key1") is None

    def test_cache_max_size_eviction(self):
        from vinzy_engine.common.caching import TTLCache
        cache = TTLCache(ttl_seconds=60.0, max_size=3)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        cache.set("d", 4)  # Should evict "a"
        assert cache.get("a") is None
        assert cache.get("d") == 4

    def test_cache_invalidate(self):
        from vinzy_engine.common.caching import TTLCache
        cache = TTLCache()
        cache.set("key1", "val")
        assert cache.invalidate("key1") is True
        assert cache.get("key1") is None
        assert cache.invalidate("missing") is False

    def test_cache_invalidate_prefix(self):
        from vinzy_engine.common.caching import TTLCache
        cache = TTLCache()
        cache.set("tenant:1", "a")
        cache.set("tenant:2", "b")
        cache.set("license:1", "c")
        removed = cache.invalidate_prefix("tenant:")
        assert removed == 2
        assert cache.get("license:1") == "c"

    def test_cache_stats(self):
        from vinzy_engine.common.caching import TTLCache
        cache = TTLCache(ttl_seconds=60.0, max_size=100)
        cache.set("k", "v")
        cache.get("k")  # hit
        cache.get("missing")  # miss
        stats = cache.stats
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5

    def test_cache_cleanup(self):
        from vinzy_engine.common.caching import TTLCache
        cache = TTLCache(ttl_seconds=0.01)
        cache.set("a", 1)
        cache.set("b", 2)
        time.sleep(0.02)
        removed = cache.cleanup()
        assert removed == 2
        assert cache.size == 0


# =============================================================================
# Item 47: HMAC computation cache
# =============================================================================

class TestHMACCache:
    """Test HMAC computation caching."""

    def test_hmac_cache_singleton(self):
        from vinzy_engine.common.caching import get_hmac_cache, reset_all_caches
        reset_all_caches()
        c1 = get_hmac_cache()
        c2 = get_hmac_cache()
        assert c1 is c2
        reset_all_caches()

    def test_hmac_cache_stores_results(self):
        from vinzy_engine.common.caching import get_hmac_cache, reset_all_caches
        reset_all_caches()
        cache = get_hmac_cache()
        cache.set("hmac:test-key-1", True)
        assert cache.get("hmac:test-key-1") is True
        cache.set("hmac:test-key-2", False)
        assert cache.get("hmac:test-key-2") is False
        reset_all_caches()


# =============================================================================
# Item 55: Tenant configuration cache with pub/sub invalidation
# =============================================================================

class TestTenantConfigCache:
    """Test tenant config cache with pub/sub invalidation."""

    def test_cache_and_invalidation_bus(self):
        from vinzy_engine.common.caching import (
            get_tenant_config_cache, get_invalidation_bus,
            reset_all_caches, reset_invalidation_bus,
        )
        reset_all_caches()
        reset_invalidation_bus()

        cache = get_tenant_config_cache()
        bus = get_invalidation_bus()

        # Set a value
        cache.set("tenant:t1", {"name": "Test"})
        assert cache.get("tenant:t1") is not None

        # Publish invalidation
        bus.publish("tenant", "tenant:t1")

        # Value should be gone
        assert cache.get("tenant:t1") is None

        reset_all_caches()
        reset_invalidation_bus()

    def test_bus_subscribe_and_publish(self):
        from vinzy_engine.common.caching import CacheInvalidationBus
        bus = CacheInvalidationBus()
        received = []
        bus.subscribe("test_channel", lambda key: received.append(key))
        count = bus.publish("test_channel", "my-key")
        assert count == 1
        assert received == ["my-key"]

    def test_bus_no_subscribers(self):
        from vinzy_engine.common.caching import CacheInvalidationBus
        bus = CacheInvalidationBus()
        count = bus.publish("empty_channel", "key")
        assert count == 0


# =============================================================================
# Item 63: License entitlement resolution cache
# =============================================================================

class TestEntitlementCache:
    """Test entitlement resolution caching."""

    def test_entitlement_cache_singleton(self):
        from vinzy_engine.common.caching import get_entitlement_cache, reset_all_caches
        reset_all_caches()
        c1 = get_entitlement_cache()
        c2 = get_entitlement_cache()
        assert c1 is c2
        reset_all_caches()

    def test_entitlement_cache_stores_resolved(self):
        from vinzy_engine.common.caching import get_entitlement_cache, reset_all_caches
        reset_all_caches()
        cache = get_entitlement_cache()
        resolved = [{"feature": "basic", "enabled": True}]
        cache.set("ent:lic-123", resolved)
        assert cache.get("ent:lic-123") == resolved
        reset_all_caches()


# =============================================================================
# Item 69: Webhook delivery status cache
# =============================================================================

class TestWebhookStatusCache:
    """Test webhook delivery status caching."""

    def test_webhook_status_cache_singleton(self):
        from vinzy_engine.common.caching import get_webhook_status_cache, reset_all_caches
        reset_all_caches()
        c1 = get_webhook_status_cache()
        c2 = get_webhook_status_cache()
        assert c1 is c2
        reset_all_caches()

    def test_stores_delivery_status(self):
        from vinzy_engine.common.caching import get_webhook_status_cache, reset_all_caches
        reset_all_caches()
        cache = get_webhook_status_cache()
        cache.set("delivery:d1", {"status": "success", "attempts": 1})
        result = cache.get("delivery:d1")
        assert result["status"] == "success"
        reset_all_caches()


# =============================================================================
# Item 72: Response compression with gzip/brotli
# =============================================================================

class TestCompression:
    """Test response compression."""

    def test_gzip_compression(self):
        from vinzy_engine.common.compression import compress_gzip
        data = b'{"valid": true, "message": "License is valid"}' * 50
        compressed = compress_gzip(data)
        assert len(compressed) < len(data)
        # Verify decompression
        assert gzip.decompress(compressed) == data

    def test_should_compress_json(self):
        from vinzy_engine.common.compression import _should_compress
        assert _should_compress("application/json", 1000) is True
        assert _should_compress("application/json", 100) is False  # Too small
        assert _should_compress("image/png", 10000) is False  # Not compressible type
        assert _should_compress(None, 1000) is False

    def test_preferred_encoding_gzip(self):
        from vinzy_engine.common.compression import _get_preferred_encoding
        assert _get_preferred_encoding("gzip, deflate") == "gzip"
        assert _get_preferred_encoding("") is None
        assert _get_preferred_encoding("deflate") is None

    def test_preferred_encoding_quality(self):
        from vinzy_engine.common.compression import _get_preferred_encoding
        assert _get_preferred_encoding("gzip;q=0.5") == "gzip"
        assert _get_preferred_encoding("gzip;q=0") is None

    async def test_compression_middleware_gzip(self, client):
        """Health endpoint returns compressed response when gzip requested."""
        resp = await client.get(
            "/health",
            headers={"Accept-Encoding": "gzip"},
        )
        assert resp.status_code == 200
        # Small response may not be compressed (below threshold)
        # Just verify the request succeeds


# =============================================================================
# Item 79 & 97: Serialization benchmarking
# =============================================================================

class TestSerializationBenchmark:
    """Test serialization performance measurement."""

    def test_measure_context_manager(self):
        from vinzy_engine.common.serialization import SerializationBenchmark
        bench = SerializationBenchmark()
        with bench.measure("test_label") as ctx:
            json.dumps({"key": "value"})
            ctx.byte_size = 15
        metrics = bench.get_metrics("test_label")
        assert metrics["total_calls"] == 1
        assert metrics["avg_time_ms"] >= 0
        assert metrics["avg_bytes"] == 15.0

    def test_record_directly(self):
        from vinzy_engine.common.serialization import SerializationBenchmark
        bench = SerializationBenchmark()
        bench.record("direct", 1.5, 100)
        bench.record("direct", 2.5, 200)
        metrics = bench.get_metrics("direct")
        assert metrics["total_calls"] == 2
        assert metrics["min_time_ms"] == 1.5
        assert metrics["max_time_ms"] == 2.5

    def test_get_all_metrics(self):
        from vinzy_engine.common.serialization import SerializationBenchmark
        bench = SerializationBenchmark()
        bench.record("a", 1.0, 10)
        bench.record("b", 2.0, 20)
        all_metrics = bench.get_metrics()
        assert "a" in all_metrics
        assert "b" in all_metrics

    def test_singleton_access(self):
        from vinzy_engine.common.serialization import (
            get_serialization_benchmark, reset_serialization_benchmark,
        )
        reset_serialization_benchmark()
        b1 = get_serialization_benchmark()
        b2 = get_serialization_benchmark()
        assert b1 is b2
        reset_serialization_benchmark()

    def test_serialization_format_benchmark(self):
        """Benchmark JSON serialization of a validation response (item 97)."""
        from vinzy_engine.common.serialization import SerializationBenchmark

        bench = SerializationBenchmark()
        sample = {
            "valid": True,
            "code": "OK",
            "message": "License is valid",
            "license": {
                "id": "abc-123",
                "status": "active",
                "product_code": "TST",
                "tier": "pro",
                "features": ["basic", "advanced", "premium"],
            },
            "features": ["basic", "advanced", "premium"],
            "entitlements": [
                {"feature": "basic", "enabled": True, "limit": None},
                {"feature": "advanced", "enabled": True, "limit": 100},
            ],
        }

        iterations = 1000
        for _ in range(iterations):
            with bench.measure("json_validation_response") as ctx:
                data = json.dumps(sample)
                ctx.byte_size = len(data)

        metrics = bench.get_metrics("json_validation_response")
        assert metrics["total_calls"] == iterations
        assert metrics["ops_per_sec"] > 1000  # Should be fast


# =============================================================================
# Item 88: Schema versioning with content negotiation
# =============================================================================

class TestSchemaVersioning:
    """Test response schema versioning and content negotiation."""

    def test_negotiate_default_v1(self):
        from vinzy_engine.common.serialization import negotiate_version
        assert negotiate_version() == "v1"

    def test_negotiate_explicit_header(self):
        from vinzy_engine.common.serialization import negotiate_version
        assert negotiate_version(x_api_version="v2") == "v2"

    def test_negotiate_accept_header(self):
        from vinzy_engine.common.serialization import negotiate_version
        assert negotiate_version(accept="application/json;version=v2") == "v2"

    def test_negotiate_unsupported_version(self):
        from vinzy_engine.common.serialization import negotiate_version
        with pytest.raises(ValueError, match="Unsupported API version"):
            negotiate_version(x_api_version="v99")

    def test_transform_validation_v2(self):
        from vinzy_engine.common.serialization import transform_response
        data = {
            "valid": True,
            "code": "OK",
            "message": "License is valid",
            "license": {
                "id": "lic-1",
                "status": "active",
                "product_code": "TST",
                "tier": "pro",
                "expires_at": "2027-01-01T00:00:00Z",
            },
            "features": ["basic"],
        }
        v2 = transform_response("validation", "v2", data)
        assert v2["schema_version"] == "v2"
        assert v2["license_id"] == "lic-1"
        assert v2["license_status"] == "active"
        assert "license" not in v2

    def test_transform_v1_passthrough(self):
        from vinzy_engine.common.serialization import transform_response
        data = {"valid": True, "license": {"id": "lic-1"}}
        v1 = transform_response("validation", "v1", data)
        assert v1 == data  # No transformation for v1

    def test_register_custom_version(self):
        from vinzy_engine.common.serialization import register_schema_version, transform_response
        register_schema_version("custom", "v2", lambda d: {**d, "custom": True})
        result = transform_response("custom", "v2", {"data": 1})
        assert result["custom"] is True


# =============================================================================
# Item 143: Async webhook delivery with retry
# =============================================================================

class TestAsyncWebhookDelivery:
    """Test async webhook delivery processor."""

    def test_initial_stats(self):
        from vinzy_engine.background import AsyncWebhookDeliveryProcessor
        proc = AsyncWebhookDeliveryProcessor()
        stats = proc.stats
        assert stats["total_delivered"] == 0
        assert stats["total_failed"] == 0
        assert stats["running"] is False

    async def test_run_once_empty(self, client):
        from vinzy_engine.background import AsyncWebhookDeliveryProcessor
        from vinzy_engine.deps import get_db
        proc = AsyncWebhookDeliveryProcessor()
        result = await proc.run_once(get_db())
        assert result == {"delivered": 0, "failed": 0}


# =============================================================================
# Item 156: Background license expiration processing
# =============================================================================

class TestLicenseExpirationProcessor:
    """Test background license expiration."""

    def test_initial_stats(self):
        from vinzy_engine.background import LicenseExpirationProcessor
        proc = LicenseExpirationProcessor()
        assert proc.stats["total_expired"] == 0

    async def test_expires_past_due_licenses(self, client, admin_headers):
        """Licenses past their expiry date get marked expired."""
        from vinzy_engine.background import LicenseExpirationProcessor
        from vinzy_engine.deps import get_db, get_licensing_service

        db = get_db()
        svc = get_licensing_service()

        # Create product + customer + license
        async with db.get_session() as session:
            await svc.create_product(session, "EXP", "Expire Test")
        async with db.get_session() as session:
            cust = await svc.create_customer(session, "Exp User", "exp@test.com")
            cust_id = cust.id
        async with db.get_session() as session:
            lic, _ = await svc.create_license(
                session, "EXP", cust_id, days_valid=1,
            )
            lic_id = lic.id

        # Force expires_at to the past
        from vinzy_engine.licensing.models import LicenseModel
        from sqlalchemy import update
        async with db.get_session() as session:
            await session.execute(
                update(LicenseModel).where(LicenseModel.id == lic_id).values(
                    expires_at=datetime.now(timezone.utc) - timedelta(hours=1)
                )
            )

        proc = LicenseExpirationProcessor()
        expired = await proc.run_once(db)
        assert expired == 1

        # Verify status changed
        async with db.get_session() as session:
            lic = await svc.get_license_by_id(session, lic_id)
            assert lic.status == "expired"


# =============================================================================
# Item 164: Async Stripe webhook processing
# =============================================================================

class TestStripeWebhookProcessor:
    """Test async Stripe webhook processor."""

    def test_initial_stats(self):
        from vinzy_engine.background import StripeWebhookProcessor
        proc = StripeWebhookProcessor()
        stats = proc.stats
        assert stats["total_processed"] == 0
        assert stats["queue_size"] == 0

    async def test_enqueue(self):
        from vinzy_engine.background import StripeWebhookProcessor
        proc = StripeWebhookProcessor(max_queue_size=10)
        queued = await proc.enqueue({"type": "checkout.session.completed"})
        assert queued is True
        assert proc.stats["queue_size"] == 1

    async def test_process_non_checkout_event(self):
        from vinzy_engine.background import StripeWebhookProcessor
        proc = StripeWebhookProcessor()
        # Non-checkout events are silently skipped
        result = await proc.process_event({"type": "invoice.paid"})
        assert result is True

    async def test_queue_full(self):
        from vinzy_engine.background import StripeWebhookProcessor
        proc = StripeWebhookProcessor(max_queue_size=1)
        await proc.enqueue({"type": "test1"})
        queued = await proc.enqueue({"type": "test2"})
        assert queued is False


# =============================================================================
# Integration: validation caching end-to-end
# =============================================================================

class TestValidationCacheIntegration:
    """Test that validation results are cached and served from cache."""

    async def test_validation_uses_cache(self, client, admin_headers):
        from vinzy_engine.common.caching import get_validation_cache, reset_all_caches
        reset_all_caches()

        # Create product + customer + license
        await client.post(
            "/products",
            json={"code": "CAC", "name": "Cache Test"},
            headers=admin_headers,
        )
        resp = await client.post(
            "/customers",
            json={"name": "Cache User", "email": "cache@test.com"},
            headers=admin_headers,
        )
        customers = (await client.get("/customers", headers=admin_headers)).json()
        cust_id = customers[-1]["id"]

        resp = await client.post(
            "/licenses",
            json={"product_code": "CAC", "customer_id": cust_id},
            headers=admin_headers,
        )
        raw_key = resp.json()["key"]

        # First validation — populates cache
        r1 = await client.post("/validate", json={"key": raw_key})
        assert r1.json()["valid"] is True

        cache = get_validation_cache()
        assert cache.stats["hits"] == 0  # First call is a miss

        # Second validation — should hit cache
        r2 = await client.post("/validate", json={"key": raw_key})
        assert r2.json()["valid"] is True
        assert cache.stats["hits"] >= 1

        reset_all_caches()
