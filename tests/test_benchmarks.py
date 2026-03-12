"""Performance benchmarks for core Vinzy-Engine operations.

These tests measure throughput and latency of critical paths.
They're not correctness tests — they establish baseline performance
numbers for regression detection.

Run with: pytest tests/test_benchmarks.py -v
"""

import time
import statistics

import pytest

from vinzy_engine.keygen.generator import generate_key
from vinzy_engine.keygen.validator import validate_key, validate_key_multi
from vinzy_engine.keygen.lease import create_lease, verify_lease

from tests.conftest import HMAC_KEY, API_KEY, SUPER_ADMIN_KEY


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BENCH_ITERATIONS = 1000
HMAC_KEYS = {0: HMAC_KEY, 1: "secondary-hmac-key-for-testing"}


def _bench(fn, iterations=BENCH_ITERATIONS):
    """Run fn `iterations` times, return (total_ms, avg_ms, ops_per_sec)."""
    timings = []
    for _ in range(iterations):
        start = time.perf_counter()
        fn()
        timings.append((time.perf_counter() - start) * 1000)
    total = sum(timings)
    avg = statistics.mean(timings)
    ops = iterations / (total / 1000) if total > 0 else 0
    return {
        "iterations": iterations,
        "total_ms": round(total, 2),
        "avg_ms": round(avg, 4),
        "p50_ms": round(statistics.median(timings), 4),
        "p99_ms": round(sorted(timings)[int(iterations * 0.99)], 4),
        "ops_per_sec": round(ops),
    }


# =============================================================================
# Key Generation Benchmarks
# =============================================================================


class TestKeygenBenchmarks:
    """Benchmark key generation throughput."""

    def test_generate_key_throughput(self):
        """Key generation should exceed 10K ops/sec."""
        stats = _bench(lambda: generate_key("TST", HMAC_KEY, version=0))
        assert stats["ops_per_sec"] > 10_000, (
            f"Key generation too slow: {stats['ops_per_sec']} ops/sec"
        )
        print(f"\n  generate_key: {stats['ops_per_sec']:,} ops/sec, "
              f"avg={stats['avg_ms']:.4f}ms, p99={stats['p99_ms']:.4f}ms")

    def test_generate_key_with_version(self):
        """Versioned key generation has negligible overhead."""
        stats_v0 = _bench(lambda: generate_key("TST", HMAC_KEY, version=0))
        stats_v1 = _bench(lambda: generate_key("TST", HMAC_KEY, version=1))
        # Version encoding adds < 20% overhead
        assert stats_v1["avg_ms"] < stats_v0["avg_ms"] * 1.2
        print(f"\n  v0: {stats_v0['avg_ms']:.4f}ms, v1: {stats_v1['avg_ms']:.4f}ms")


# =============================================================================
# Key Validation Benchmarks
# =============================================================================


class TestValidationBenchmarks:
    """Benchmark key validation throughput."""

    @pytest.fixture(autouse=True)
    def setup_keys(self):
        self.valid_key = generate_key("TST", HMAC_KEY, version=0)
        self.invalid_key = "TST-AAAAA-BBBBB-CCCCC-DDDDD-EEEEE-XXXXX-YYYYY"

    def test_validate_key_valid_throughput(self):
        """Valid key validation should exceed 10K ops/sec."""
        stats = _bench(lambda: validate_key(self.valid_key, HMAC_KEY))
        assert stats["ops_per_sec"] > 10_000
        print(f"\n  validate_key (valid): {stats['ops_per_sec']:,} ops/sec, "
              f"avg={stats['avg_ms']:.4f}ms")

    def test_validate_key_invalid_throughput(self):
        """Invalid key rejection should be equally fast."""
        stats = _bench(lambda: validate_key(self.invalid_key, HMAC_KEY))
        assert stats["ops_per_sec"] > 10_000
        print(f"\n  validate_key (invalid): {stats['ops_per_sec']:,} ops/sec")

    def test_validate_key_multi_throughput(self):
        """Multi-key validation with keyring should exceed 5K ops/sec."""
        stats = _bench(lambda: validate_key_multi(self.valid_key, HMAC_KEYS))
        assert stats["ops_per_sec"] > 5_000
        print(f"\n  validate_key_multi: {stats['ops_per_sec']:,} ops/sec, "
              f"avg={stats['avg_ms']:.4f}ms")


# =============================================================================
# Lease Benchmarks
# =============================================================================


class TestLeaseBenchmarks:
    """Benchmark lease creation and verification."""

    @staticmethod
    def _make_payload():
        from vinzy_engine.keygen.lease import LeasePayload
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        return LeasePayload(
            license_id="test-license-123",
            status="active",
            features=["basic"],
            entitlements=[],
            tier="standard",
            product_code="TST",
            issued_at=now.isoformat(),
            expires_at=(now + timedelta(days=365)).isoformat(),
        )

    def test_create_lease_throughput(self):
        """Lease creation should exceed 5K ops/sec."""
        payload = self._make_payload()
        stats = _bench(lambda: create_lease(payload, HMAC_KEY, ttl_seconds=3600))
        assert stats["ops_per_sec"] > 5_000
        print(f"\n  create_lease: {stats['ops_per_sec']:,} ops/sec, "
              f"avg={stats['avg_ms']:.4f}ms")

    def test_verify_lease_throughput(self):
        """Lease verification should exceed 10K ops/sec."""
        payload = self._make_payload()
        lease = create_lease(payload, HMAC_KEY, ttl_seconds=3600)
        stats = _bench(lambda: verify_lease(lease, HMAC_KEY))
        assert stats["ops_per_sec"] > 10_000
        print(f"\n  verify_lease: {stats['ops_per_sec']:,} ops/sec, "
              f"avg={stats['avg_ms']:.4f}ms")

    def test_verify_invalid_lease_throughput(self):
        """Invalid lease rejection should be fast."""
        payload = self._make_payload()
        lease = create_lease(payload, HMAC_KEY, ttl_seconds=3600)
        lease["signature"] = "tampered"
        stats = _bench(lambda: verify_lease(lease, HMAC_KEY))
        assert stats["ops_per_sec"] > 10_000
        print(f"\n  verify_lease (invalid): {stats['ops_per_sec']:,} ops/sec")


# =============================================================================
# Database Operation Benchmarks
# =============================================================================


class TestDatabaseBenchmarks:
    """Benchmark database-backed operations."""

    async def test_license_creation_throughput(self, client, admin_headers):
        """License creation via API."""
        # Setup: create product + customer
        await client.post(
            "/products",
            json={"code": "BEN", "name": "Bench Product"},
            headers=admin_headers,
        )
        await client.post(
            "/customers",
            json={"name": "Bench User", "email": "bench@test.com"},
            headers=admin_headers,
        )
        resp = await client.get("/customers", headers=admin_headers)
        customers = resp.json()
        customer_id = customers[0]["id"]

        timings = []
        for i in range(50):
            start = time.perf_counter()
            resp = await client.post(
                "/licenses",
                json={
                    "product_code": "BEN",
                    "customer_id": customer_id,
                    "tier": "standard",
                },
                headers=admin_headers,
            )
            timings.append((time.perf_counter() - start) * 1000)
            assert resp.status_code == 201

        avg = statistics.mean(timings)
        p99 = sorted(timings)[int(len(timings) * 0.99)]
        print(f"\n  license creation API: avg={avg:.1f}ms, p99={p99:.1f}ms")
        assert avg < 100, f"License creation too slow: {avg:.1f}ms avg"

    async def test_validation_api_throughput(self, client):
        """Key validation via public API."""
        # Create a valid key
        key = generate_key("BEN", HMAC_KEY)

        timings = []
        for _ in range(100):
            start = time.perf_counter()
            resp = await client.post("/validate", json={"key": key})
            timings.append((time.perf_counter() - start) * 1000)

        avg = statistics.mean(timings)
        p99 = sorted(timings)[int(len(timings) * 0.99)]
        print(f"\n  validation API: avg={avg:.1f}ms, p99={p99:.1f}ms")
        assert avg < 50, f"Validation API too slow: {avg:.1f}ms avg"


# =============================================================================
# Anomaly Detection Benchmarks
# =============================================================================


class TestAnomalyBenchmarks:
    """Benchmark anomaly detection z-score calculations."""

    def test_zscore_computation_throughput(self):
        """Z-score anomaly detection should be fast."""
        from vinzy_engine.anomaly.detector import compute_z_score, compute_baseline

        # compute_baseline returns (mean, stddev) tuple
        values = [float(50 + i % 20) for i in range(100)]
        mean, stddev = compute_baseline(values)

        stats = _bench(
            lambda: compute_z_score(150.0, mean, stddev),
            iterations=BENCH_ITERATIONS,
        )
        assert stats["ops_per_sec"] > 50_000
        print(f"\n  z-score check: {stats['ops_per_sec']:,} ops/sec, "
              f"avg={stats['avg_ms']:.4f}ms")

    def test_detect_anomalies_throughput(self):
        """Full anomaly detection pipeline throughput."""
        from vinzy_engine.anomaly.detector import detect_anomalies

        values = [float(50 + i % 20) for i in range(100)]

        stats = _bench(
            lambda: detect_anomalies(150.0, values, "tokens"),
            iterations=BENCH_ITERATIONS,
        )
        assert stats["ops_per_sec"] > 10_000
        print(f"\n  detect_anomalies: {stats['ops_per_sec']:,} ops/sec, "
              f"avg={stats['avg_ms']:.4f}ms")
