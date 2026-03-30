"""Tests for behavioral anomaly detection."""

import pytest

from vinzy_engine.common.config import VinzySettings
from vinzy_engine.common.database import DatabaseManager
from vinzy_engine.anomaly.detector import (
    compute_baseline,
    compute_z_score,
    classify_severity,
    detect_anomalies,
)
from vinzy_engine.anomaly.service import AnomalyService
from vinzy_engine.audit.service import AuditService
from vinzy_engine.licensing.service import LicensingService
from vinzy_engine.usage.service import UsageService


HMAC_KEY = "test-hmac-key-for-unit-tests"


def make_settings(**overrides) -> VinzySettings:
    defaults = {"hmac_key": HMAC_KEY, "db_url": "sqlite+aiosqlite://"}
    defaults.update(overrides)
    return VinzySettings(**defaults)


@pytest.fixture
async def db():
    settings = make_settings()
    manager = DatabaseManager(settings)
    await manager.init()
    await manager.create_all()
    yield manager
    await manager.close()


@pytest.fixture
def audit_svc():
    return AuditService(make_settings())


@pytest.fixture
def anomaly_svc(audit_svc):
    return AnomalyService(make_settings(), audit_service=audit_svc)


@pytest.fixture
def licensing_svc():
    return LicensingService(make_settings())


@pytest.fixture
def usage_svc(licensing_svc, audit_svc, anomaly_svc):
    return UsageService(
        make_settings(), licensing_svc,
        audit_service=audit_svc, anomaly_service=anomaly_svc,
    )


async def _create_license_with_usage(db, licensing_svc, usage_svc, metric, values):
    """Helper: create a license and record usage values for a metric."""
    async with db.get_session() as session:
        await licensing_svc.create_product(session, "ZUL", "Zuultimate")
        customer = await licensing_svc.create_customer(
            session, "Test", "test@example.com"
        )
    async with db.get_session() as session:
        lic, raw_key = await licensing_svc.create_license(
            session, "ZUL", customer.id
        )
    # Record baseline usage
    for v in values:
        async with db.get_session() as session:
            await usage_svc.record_usage(session, raw_key, metric, v)
    return lic, raw_key


# ── Detector unit tests ──────────────────────────────────────────


class TestComputeBaseline:
    def test_empty_values(self):
        mean, stddev = compute_baseline([])
        assert mean == 0.0
        assert stddev == 0.0

    def test_single_value(self):
        mean, stddev = compute_baseline([10.0])
        assert mean == 10.0
        assert stddev == 0.0

    def test_normal_values(self):
        values = [10.0, 12.0, 11.0, 13.0, 10.0]
        mean, stddev = compute_baseline(values)
        assert 10.0 < mean < 13.0
        assert stddev > 0.0

    def test_window_limits(self):
        values = list(range(50))
        mean, stddev = compute_baseline(values, window=5)
        # Should only use last 5 values: 45, 46, 47, 48, 49
        assert mean == 47.0


class TestComputeZScore:
    def test_at_mean(self):
        assert compute_z_score(10.0, 10.0, 2.0) == 0.0

    def test_above_mean(self):
        z = compute_z_score(14.0, 10.0, 2.0)
        assert z == 2.0

    def test_below_mean(self):
        z = compute_z_score(6.0, 10.0, 2.0)
        assert z == -2.0

    def test_zero_stddev_at_mean(self):
        assert compute_z_score(10.0, 10.0, 0.0) == 0.0

    def test_zero_stddev_not_at_mean(self):
        z = compute_z_score(15.0, 10.0, 0.0)
        assert z == 999.0


class TestClassifySeverity:
    def test_critical(self):
        assert classify_severity(3.5) == "critical"
        assert classify_severity(-3.5) == "critical"

    def test_high(self):
        assert classify_severity(2.5) == "high"
        assert classify_severity(-2.5) == "high"

    def test_medium(self):
        assert classify_severity(1.7) == "medium"
        assert classify_severity(-1.7) == "medium"

    def test_none(self):
        assert classify_severity(1.0) is None
        assert classify_severity(0.0) is None


class TestDetectAnomalies:
    def test_detect_spike(self):
        history = [10.0, 11.0, 10.0, 12.0, 10.0, 11.0, 10.0, 10.0]
        report = detect_anomalies(50.0, history, "api_calls")
        assert report is not None
        assert report.severity in ("critical", "high", "medium")
        assert report.metric == "api_calls"
        assert report.anomaly_type == "usage_spike"

    def test_normal_value(self):
        history = [10.0, 11.0, 10.0, 12.0, 10.0, 11.0, 10.0, 10.0]
        report = detect_anomalies(11.0, history, "api_calls")
        assert report is None

    def test_empty_history(self):
        # With no history, stddev=0 and value!=mean → z=999.0 → "critical"
        report = detect_anomalies(5.0, [], "api_calls")
        assert report is not None
        assert report.severity == "critical"
        assert report.z_score == 999.0

    def test_single_history_same_value(self):
        # Single history point matching current → z=0 → not anomalous
        report = detect_anomalies(10.0, [10.0], "api_calls")
        assert report is None


# ── Service integration tests ────────────────────────────────────


class TestAnomalyService:
    async def test_scan_and_record_creates_anomaly(self, db, licensing_svc, usage_svc, anomaly_svc):
        """A spike after normal usage should create an anomaly record."""
        # Build baseline: 10 normal values
        lic, raw_key = await _create_license_with_usage(
            db, licensing_svc, usage_svc, "api_calls",
            [10.0] * 10,
        )
        # Now scan a big spike
        async with db.get_session() as session:
            anomaly = await anomaly_svc.scan_and_record(
                session, lic.id, "api_calls", 100.0,
            )
            assert anomaly is not None
            assert anomaly.severity in ("critical", "high")
            assert anomaly.metric == "api_calls"
            assert anomaly.license_id == lic.id
            assert anomaly.resolved is False

    async def test_scan_normal_returns_none(self, db, licensing_svc, usage_svc, anomaly_svc):
        """A value within normal range should not create an anomaly."""
        lic, raw_key = await _create_license_with_usage(
            db, licensing_svc, usage_svc, "api_calls",
            [10.0, 11.0, 10.0, 12.0, 10.0],
        )
        async with db.get_session() as session:
            anomaly = await anomaly_svc.scan_and_record(
                session, lic.id, "api_calls", 11.0,
            )
            assert anomaly is None

    async def test_get_anomalies(self, db, licensing_svc, usage_svc, anomaly_svc):
        """List anomalies for a license."""
        lic, raw_key = await _create_license_with_usage(
            db, licensing_svc, usage_svc, "api_calls",
            [10.0] * 10,
        )
        async with db.get_session() as session:
            await anomaly_svc.scan_and_record(session, lic.id, "api_calls", 100.0)
        async with db.get_session() as session:
            anomalies = await anomaly_svc.get_anomalies(session, lic.id)
            assert len(anomalies) == 1
            assert anomalies[0].severity in ("critical", "high")

    async def test_resolve_anomaly(self, db, licensing_svc, usage_svc, anomaly_svc):
        """Resolve a detected anomaly."""
        lic, raw_key = await _create_license_with_usage(
            db, licensing_svc, usage_svc, "api_calls",
            [10.0] * 10,
        )
        async with db.get_session() as session:
            anomaly = await anomaly_svc.scan_and_record(session, lic.id, "api_calls", 100.0)
            anomaly_id = anomaly.id
        async with db.get_session() as session:
            resolved = await anomaly_svc.resolve_anomaly(session, anomaly_id, "admin@test.com")
            assert resolved is not None
            assert resolved.resolved is True
            assert resolved.resolved_by == "admin@test.com"
            assert resolved.resolved_at is not None

    async def test_resolve_nonexistent_returns_none(self, db, anomaly_svc):
        """Resolving a nonexistent anomaly returns None."""
        async with db.get_session() as session:
            result = await anomaly_svc.resolve_anomaly(session, "fake-id", "admin")
            assert result is None

    async def test_get_anomalies_filter_severity(self, db, licensing_svc, usage_svc, anomaly_svc):
        """Filter anomalies by severity."""
        lic, raw_key = await _create_license_with_usage(
            db, licensing_svc, usage_svc, "api_calls",
            [10.0] * 10,
        )
        async with db.get_session() as session:
            await anomaly_svc.scan_and_record(session, lic.id, "api_calls", 100.0)
        async with db.get_session() as session:
            # Filter for a severity that doesn't match
            none_found = await anomaly_svc.get_anomalies(session, lic.id, severity="medium")
            # The spike of 100 vs mean of 10 should be critical, not medium
            all_found = await anomaly_svc.get_anomalies(session, lic.id)
            assert len(all_found) >= 1
            # If the anomaly is critical, filtering by medium should return empty
            if all_found[0].severity == "critical":
                assert len(none_found) == 0

    async def test_get_anomalies_filter_resolved(self, db, licensing_svc, usage_svc, anomaly_svc):
        """Filter anomalies by resolved status."""
        lic, raw_key = await _create_license_with_usage(
            db, licensing_svc, usage_svc, "api_calls",
            [10.0] * 10,
        )
        async with db.get_session() as session:
            anomaly = await anomaly_svc.scan_and_record(session, lic.id, "api_calls", 100.0)
            anomaly_id = anomaly.id
        async with db.get_session() as session:
            await anomaly_svc.resolve_anomaly(session, anomaly_id, "admin")
        async with db.get_session() as session:
            unresolved = await anomaly_svc.get_anomalies(session, lic.id, resolved=False)
            resolved = await anomaly_svc.get_anomalies(session, lic.id, resolved=True)
            assert len(unresolved) == 0
            assert len(resolved) == 1
