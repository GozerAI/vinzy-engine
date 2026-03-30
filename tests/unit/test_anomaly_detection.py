"""Comprehensive tests for anomaly detection — detector functions and service."""

import pytest

from vinzy_engine.common.config import VinzySettings
from vinzy_engine.common.database import DatabaseManager
from vinzy_engine.anomaly.detector import (
    AnomalyReport,
    classify_severity,
    compute_baseline,
    compute_z_score,
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
    for v in values:
        async with db.get_session() as session:
            await usage_svc.record_usage(session, raw_key, metric, v)
    return lic, raw_key


# ── Normal usage patterns (no anomaly) ──────────────────────────


class TestNormalUsagePatterns:
    """Normal usage values should not trigger anomaly detection."""

    def test_value_at_mean_not_anomalous(self):
        history = [10.0, 10.0, 10.0, 10.0, 10.0]
        report = detect_anomalies(10.0, history, "api_calls")
        assert report is None

    def test_slight_variation_not_anomalous(self):
        history = [10.0, 11.0, 9.5, 10.5, 10.0, 11.0, 10.0, 9.0]
        report = detect_anomalies(10.5, history, "api_calls")
        assert report is None

    def test_value_within_one_stddev_not_anomalous(self):
        history = [10.0, 12.0, 8.0, 11.0, 9.0, 10.0, 11.0, 10.0]
        mean, stddev = compute_baseline(history)
        # Stay within 1 stddev
        safe_value = mean + stddev * 0.5
        report = detect_anomalies(safe_value, history, "api_calls")
        assert report is None

    def test_zero_values_at_zero(self):
        history = [0.0, 0.0, 0.0, 0.0, 0.0]
        report = detect_anomalies(0.0, history, "idle_metric")
        assert report is None


# ── Spike detection ─────────────────────────────────────────────


class TestSpikeDetection:
    """Sudden increases should be detected as anomalies."""

    def test_large_spike_detected(self):
        history = [10.0, 11.0, 10.0, 12.0, 10.0, 11.0, 10.0, 10.0]
        report = detect_anomalies(100.0, history, "api_calls")
        assert report is not None
        assert report.severity in ("critical", "high")
        assert report.observed_value == 100.0

    def test_moderate_spike_detected(self):
        history = [10.0, 11.0, 10.0, 12.0, 10.0, 11.0, 10.0, 10.0]
        mean, stddev = compute_baseline(history)
        # A value at 2.5 stddev should be "high"
        spike = mean + stddev * 2.5
        report = detect_anomalies(spike, history, "api_calls")
        assert report is not None
        assert report.severity in ("critical", "high")

    def test_spike_from_zero_baseline(self):
        history = [0.0, 0.0, 0.0, 0.0, 0.0]
        report = detect_anomalies(50.0, history, "api_calls")
        assert report is not None
        assert report.z_score == 999.0
        assert report.severity == "critical"

    def test_negative_spike_detected(self):
        """A sudden drop below baseline is also anomalous."""
        history = [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0]
        report = detect_anomalies(-50.0, history, "revenue")
        assert report is not None
        assert report.severity in ("critical", "high")

    def test_custom_anomaly_type(self):
        history = [10.0] * 10
        report = detect_anomalies(
            100.0, history, "logins", anomaly_type="geographic_anomaly"
        )
        assert report is not None
        assert report.anomaly_type == "geographic_anomaly"


# ── Velocity anomaly (too many activations too fast) ────────────


class TestVelocityAnomaly:
    """Rapid increases in count-based metrics."""

    def test_rapid_count_increase(self):
        # Normal: 1-3 activations per window
        history = [1.0, 2.0, 1.0, 3.0, 2.0, 1.0, 2.0, 1.0]
        # Sudden: 50 in one window
        report = detect_anomalies(
            50.0, history, "activations", anomaly_type="velocity_anomaly"
        )
        assert report is not None
        assert report.anomaly_type == "velocity_anomaly"

    def test_gradual_increase_not_anomalous(self):
        # Gradually increasing values — next step within 1 stddev
        history = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        mean, stddev = compute_baseline(history)
        # Use a value well within 1.5 stddev of the mean
        safe_value = mean + stddev * 0.5
        report = detect_anomalies(safe_value, history, "activations")
        assert report is None


# ── After-hours usage pattern ───────────────────────────────────


class TestAfterHoursPattern:
    """Usage patterns detected via metric naming convention."""

    def test_unusual_time_spike(self):
        # Normal daytime usage
        history = [100.0, 110.0, 105.0, 95.0, 100.0, 108.0, 102.0, 98.0]
        # Unusual nighttime spike
        report = detect_anomalies(
            500.0, history, "after_hours_requests", anomaly_type="after_hours"
        )
        assert report is not None
        assert report.anomaly_type == "after_hours"
        assert report.metric == "after_hours_requests"


# ── Multiple anomaly types simultaneously ───────────────────────


class TestMultipleAnomalyTypes:
    """Different metrics can each trigger their own anomaly."""

    async def test_multiple_metrics_multiple_anomalies(self, db, licensing_svc, usage_svc, anomaly_svc):
        """Anomalies on different metrics are tracked independently."""
        lic, raw_key = await _create_license_with_usage(
            db, licensing_svc, usage_svc, "api_calls", [10.0] * 10
        )
        # Also record baseline for a second metric
        for v in [5.0] * 10:
            async with db.get_session() as session:
                await usage_svc.record_usage(session, raw_key, "downloads", v)

        # Spike on api_calls
        async with db.get_session() as session:
            a1 = await anomaly_svc.scan_and_record(session, lic.id, "api_calls", 200.0)
        # Spike on downloads
        async with db.get_session() as session:
            a2 = await anomaly_svc.scan_and_record(session, lic.id, "downloads", 100.0)

        assert a1 is not None
        assert a2 is not None
        assert a1.metric == "api_calls"
        assert a2.metric == "downloads"

    def test_detect_anomalies_with_different_types(self):
        history = [10.0] * 10
        r1 = detect_anomalies(100.0, history, "m1", anomaly_type="spike")
        r2 = detect_anomalies(100.0, history, "m2", anomaly_type="geo")
        assert r1.anomaly_type == "spike"
        assert r2.anomaly_type == "geo"


# ── Anomaly severity levels ────────────────────────────────────


class TestAnomalySeverityLevels:
    """Classify severity correctly at boundary z-scores."""

    def test_critical_threshold(self):
        assert classify_severity(3.01) == "critical"
        assert classify_severity(-3.01) == "critical"

    def test_high_threshold(self):
        assert classify_severity(2.01) == "high"
        assert classify_severity(2.99) == "high"
        assert classify_severity(-2.5) == "high"

    def test_medium_threshold(self):
        assert classify_severity(1.51) == "medium"
        assert classify_severity(1.99) == "medium"
        assert classify_severity(-1.6) == "medium"

    def test_not_anomalous_below_threshold(self):
        assert classify_severity(1.49) is None
        assert classify_severity(0.0) is None
        assert classify_severity(-1.0) is None

    def test_exact_boundaries(self):
        # At exactly 3.0, not > 3.0, so it's "high"
        assert classify_severity(3.0) == "high"
        # At exactly 2.0, not > 2.0, so it's "medium"
        assert classify_severity(2.0) == "medium"
        # At exactly 1.5, not > 1.5, so it's None
        assert classify_severity(1.5) is None

    def test_severity_in_anomaly_report(self):
        # Large spike => critical
        history = [10.0] * 10
        report = detect_anomalies(1000.0, history, "m")
        assert report is not None
        assert report.severity == "critical"

    def test_z_score_999_for_zero_stddev(self):
        z = compute_z_score(5.0, 0.0, 0.0)
        assert z == 999.0
        assert classify_severity(z) == "critical"


# ── Anomaly resolution/acknowledgment ──────────────────────────


class TestAnomalyResolution:
    """Resolve/acknowledge detected anomalies."""

    async def test_resolve_sets_resolved_fields(self, db, licensing_svc, usage_svc, anomaly_svc):
        lic, raw_key = await _create_license_with_usage(
            db, licensing_svc, usage_svc, "api_calls", [10.0] * 10
        )
        async with db.get_session() as session:
            anomaly = await anomaly_svc.scan_and_record(session, lic.id, "api_calls", 200.0)
            anomaly_id = anomaly.id

        async with db.get_session() as session:
            resolved = await anomaly_svc.resolve_anomaly(session, anomaly_id, "admin@gozerai.com")
            assert resolved.resolved is True
            assert resolved.resolved_by == "admin@gozerai.com"
            assert resolved.resolved_at is not None

    async def test_resolve_nonexistent_returns_none(self, db, anomaly_svc):
        async with db.get_session() as session:
            result = await anomaly_svc.resolve_anomaly(session, "nonexistent-id", "admin")
            assert result is None

    async def test_filter_resolved_vs_unresolved(self, db, licensing_svc, usage_svc, anomaly_svc):
        lic, raw_key = await _create_license_with_usage(
            db, licensing_svc, usage_svc, "api_calls", [10.0] * 10
        )
        # Create two anomalies
        async with db.get_session() as session:
            a1 = await anomaly_svc.scan_and_record(session, lic.id, "api_calls", 200.0)
            a1_id = a1.id

        # Record more baseline then create another anomaly
        for v in [10.0] * 5:
            async with db.get_session() as session:
                await usage_svc.record_usage(session, raw_key, "api_calls", v)
        async with db.get_session() as session:
            await anomaly_svc.scan_and_record(session, lic.id, "api_calls", 300.0)

        # Resolve only the first
        async with db.get_session() as session:
            await anomaly_svc.resolve_anomaly(session, a1_id, "admin")

        async with db.get_session() as session:
            unresolved = await anomaly_svc.get_anomalies(session, lic.id, resolved=False)
            resolved = await anomaly_svc.get_anomalies(session, lic.id, resolved=True)
            assert len(resolved) == 1
            assert len(unresolved) >= 1

    async def test_list_all_anomalies_with_filters(self, db, licensing_svc, usage_svc, anomaly_svc):
        lic, raw_key = await _create_license_with_usage(
            db, licensing_svc, usage_svc, "api_calls", [10.0] * 10
        )
        async with db.get_session() as session:
            await anomaly_svc.scan_and_record(session, lic.id, "api_calls", 200.0)

        async with db.get_session() as session:
            items, total = await anomaly_svc.list_all_anomalies(session, resolved=False)
            assert total >= 1
            assert len(items) >= 1
            assert all(not item.resolved for item in items)


# ── Baseline computation edge cases ─────────────────────────────


class TestBaselineEdgeCases:
    """Edge cases for compute_baseline."""

    def test_two_identical_values(self):
        mean, stddev = compute_baseline([5.0, 5.0])
        assert mean == 5.0
        assert stddev == 0.0

    def test_two_different_values(self):
        mean, stddev = compute_baseline([0.0, 10.0])
        assert mean == 5.0
        assert stddev > 0.0

    def test_large_history_uses_window(self):
        values = list(range(100))
        mean, stddev = compute_baseline(values, window=10)
        # Last 10: 90..99
        assert mean == 94.5

    def test_window_larger_than_history(self):
        values = [1.0, 2.0, 3.0]
        mean, _ = compute_baseline(values, window=100)
        assert mean == 2.0

    def test_negative_values(self):
        values = [-10.0, -5.0, -8.0, -7.0, -6.0]
        mean, stddev = compute_baseline(values)
        assert mean < 0.0
        assert stddev > 0.0


# ── AnomalyReport dataclass ────────────────────────────────────


class TestAnomalyReport:
    """Verify AnomalyReport fields."""

    def test_report_fields(self):
        report = AnomalyReport(
            anomaly_type="usage_spike",
            severity="high",
            metric="api_calls",
            z_score=2.5,
            baseline_mean=10.0,
            baseline_stddev=2.0,
            observed_value=15.0,
        )
        assert report.anomaly_type == "usage_spike"
        assert report.severity == "high"
        assert report.metric == "api_calls"
        assert report.z_score == 2.5
        assert report.baseline_mean == 10.0
        assert report.baseline_stddev == 2.0
        assert report.observed_value == 15.0


# ── Service minimum-history guard ───────────────────────────────


class TestMinimumHistory:
    """AnomalyService requires at least 3 data points to detect anomalies."""

    async def test_too_few_history_returns_none(self, db, licensing_svc, usage_svc, anomaly_svc):
        """With fewer than 3 historical records, scan_and_record returns None."""
        async with db.get_session() as session:
            await licensing_svc.create_product(session, "ZUL", "Zuultimate")
            customer = await licensing_svc.create_customer(
                session, "Test", "test@example.com"
            )
        async with db.get_session() as session:
            lic, raw_key = await licensing_svc.create_license(
                session, "ZUL", customer.id
            )
        # Record only 2 usage values
        for v in [10.0, 10.0]:
            async with db.get_session() as session:
                await usage_svc.record_usage(session, raw_key, "api_calls", v)

        async with db.get_session() as session:
            result = await anomaly_svc.scan_and_record(session, lic.id, "api_calls", 1000.0)
            assert result is None  # Not enough history

    async def test_exactly_three_history_can_detect(self, db, licensing_svc, usage_svc, anomaly_svc):
        """With exactly 3 historical records, detection is possible."""
        lic, raw_key = await _create_license_with_usage(
            db, licensing_svc, usage_svc, "api_calls", [10.0, 10.0, 10.0]
        )
        async with db.get_session() as session:
            result = await anomaly_svc.scan_and_record(session, lic.id, "api_calls", 1000.0)
            assert result is not None
            assert result.severity in ("critical", "high")
