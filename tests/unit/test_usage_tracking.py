"""Comprehensive tests for the usage tracking module — recording, limits,
summaries, aggregation, and edge cases."""

import pytest

from vinzy_engine.common.config import VinzySettings
from vinzy_engine.common.database import DatabaseManager
from vinzy_engine.common.exceptions import (
    LicenseExpiredError,
    LicenseNotFoundError,
    LicenseSuspendedError,
)
from vinzy_engine.licensing.service import LicensingService
from vinzy_engine.usage.models import UsageRecordModel
from vinzy_engine.usage.schemas import UsageRecordRequest, UsageRecordResponse, UsageSummary
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
def licensing_svc():
    return LicensingService(make_settings())


@pytest.fixture
def svc(licensing_svc):
    return UsageService(make_settings(), licensing_svc)


async def _create_license(db, licensing_svc, entitlements=None, status="active"):
    async with db.get_session() as session:
        await licensing_svc.create_product(session, "ZUL", "Zuultimate")
        customer = await licensing_svc.create_customer(
            session, "Test User", "test@example.com"
        )
    async with db.get_session() as session:
        lic, raw_key = await licensing_svc.create_license(
            session, "ZUL", customer.id,
            entitlements=entitlements or {},
        )
    if status != "active":
        async with db.get_session() as session:
            await licensing_svc.update_license(session, lic.id, status=status)
    return lic, raw_key


# ── Record Usage Event ──


class TestRecordUsageEvent:
    """Test basic usage event recording."""

    async def test_record_single_event(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            result = await svc.record_usage(session, raw_key, "api-calls", 1.0)
            assert result["success"] is True
            assert result["metric"] == "api-calls"
            assert result["value_added"] == 1.0
            assert result["code"] == "RECORDED"

    async def test_record_with_metadata(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        metadata = {"endpoint": "/api/v1/data", "method": "GET"}
        async with db.get_session() as session:
            result = await svc.record_usage(
                session, raw_key, "api-calls", 1.0, metadata=metadata
            )
            assert result["success"] is True

    async def test_record_invalid_key_raises(self, db, svc, licensing_svc):
        with pytest.raises(LicenseNotFoundError):
            async with db.get_session() as session:
                await svc.record_usage(session, "invalid-key", "api-calls")

    async def test_record_returns_total_value(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            result = await svc.record_usage(session, raw_key, "tokens", 100.0)
            assert result["total_value"] == 100.0


# ── Usage Counter Increment ──


class TestUsageCounterIncrement:
    """Test that usage accumulates correctly."""

    async def test_accumulation_across_sessions(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await svc.record_usage(session, raw_key, "tokens", 100.0)
        async with db.get_session() as session:
            result = await svc.record_usage(session, raw_key, "tokens", 50.0)
            assert result["total_value"] == 150.0

    async def test_accumulation_same_session(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await svc.record_usage(session, raw_key, "tokens", 100.0)
            result = await svc.record_usage(session, raw_key, "tokens", 200.0)
            assert result["total_value"] == 300.0

    async def test_different_metrics_independent(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await svc.record_usage(session, raw_key, "tokens", 100.0)
        async with db.get_session() as session:
            result = await svc.record_usage(session, raw_key, "api-calls", 5.0)
            assert result["total_value"] == 5.0  # independent from tokens

    async def test_fractional_increments(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await svc.record_usage(session, raw_key, "bytes", 0.5)
        async with db.get_session() as session:
            result = await svc.record_usage(session, raw_key, "bytes", 0.3)
            assert abs(result["total_value"] - 0.8) < 0.001


# ── Usage Limits Enforcement ──


class TestUsageLimitsEnforcement:
    """Test that entitlement limits are reported correctly."""

    async def test_reports_limit_and_remaining(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(
            db, licensing_svc,
            entitlements={"tokens": {"enabled": True, "limit": 1000}},
        )
        async with db.get_session() as session:
            result = await svc.record_usage(session, raw_key, "tokens", 300.0)
            assert result["limit"] == 1000
            assert result["remaining"] == 700.0

    async def test_remaining_decreases_with_usage(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(
            db, licensing_svc,
            entitlements={"tokens": {"enabled": True, "limit": 500}},
        )
        async with db.get_session() as session:
            await svc.record_usage(session, raw_key, "tokens", 200.0)
        async with db.get_session() as session:
            result = await svc.record_usage(session, raw_key, "tokens", 100.0)
            assert result["remaining"] == 200.0

    async def test_no_limit_returns_none(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            result = await svc.record_usage(session, raw_key, "api-calls")
            assert result["limit"] is None
            assert result["remaining"] is None


# ── Overage Detection ──


class TestOverageDetection:
    """Test behavior when usage exceeds limits."""

    async def test_remaining_zero_when_limit_exceeded(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(
            db, licensing_svc,
            entitlements={"tokens": {"enabled": True, "limit": 100}},
        )
        async with db.get_session() as session:
            result = await svc.record_usage(session, raw_key, "tokens", 150.0)
            # remaining should be clamped to 0
            assert result["remaining"] == 0.0
            assert result["total_value"] == 150.0

    async def test_overage_still_records(self, db, svc, licensing_svc):
        """Usage is recorded even when over limit (soft limit, not hard block)."""
        lic, raw_key = await _create_license(
            db, licensing_svc,
            entitlements={"tokens": {"enabled": True, "limit": 10}},
        )
        async with db.get_session() as session:
            result = await svc.record_usage(session, raw_key, "tokens", 50.0)
            assert result["success"] is True
            assert result["total_value"] == 50.0
            assert result["remaining"] == 0.0


# ── Usage Summary ──


class TestUsageSummary:
    """Test usage aggregation and summary."""

    async def test_summary_empty(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            summaries = await svc.get_usage_summary(session, lic.id)
            assert summaries == []

    async def test_summary_single_metric(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await svc.record_usage(session, raw_key, "api-calls", 5.0)
        async with db.get_session() as session:
            await svc.record_usage(session, raw_key, "api-calls", 3.0)
        async with db.get_session() as session:
            summaries = await svc.get_usage_summary(session, lic.id)
            assert len(summaries) == 1
            assert summaries[0]["metric"] == "api-calls"
            assert summaries[0]["total_value"] == 8.0
            assert summaries[0]["record_count"] == 2

    async def test_summary_multiple_metrics(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await svc.record_usage(session, raw_key, "api-calls", 5.0)
        async with db.get_session() as session:
            await svc.record_usage(session, raw_key, "tokens", 100.0)
        async with db.get_session() as session:
            await svc.record_usage(session, raw_key, "bytes", 1024.0)
        async with db.get_session() as session:
            summaries = await svc.get_usage_summary(session, lic.id)
            assert len(summaries) == 3
            metrics = {s["metric"] for s in summaries}
            assert metrics == {"api-calls", "tokens", "bytes"}

    async def test_summary_with_limits(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(
            db, licensing_svc,
            entitlements={"tokens": {"enabled": True, "limit": 1000}},
        )
        async with db.get_session() as session:
            await svc.record_usage(session, raw_key, "tokens", 300.0)
        async with db.get_session() as session:
            summaries = await svc.get_usage_summary(session, lic.id)
            token_summary = [s for s in summaries if s["metric"] == "tokens"][0]
            assert token_summary["limit"] == 1000
            assert token_summary["remaining"] == 700.0

    async def test_summary_record_count(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        for _ in range(7):
            async with db.get_session() as session:
                await svc.record_usage(session, raw_key, "api-calls", 1.0)
        async with db.get_session() as session:
            summaries = await svc.get_usage_summary(session, lic.id)
            assert summaries[0]["record_count"] == 7
            assert summaries[0]["total_value"] == 7.0

    async def test_summary_for_nonexistent_license(self, db, svc, licensing_svc):
        async with db.get_session() as session:
            summaries = await svc.get_usage_summary(session, "nonexistent-id")
            assert summaries == []


# ── Zero Usage Handling ──


class TestZeroUsageHandling:
    """Test edge cases around zero and minimal usage values."""

    async def test_default_value_is_one(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            result = await svc.record_usage(session, raw_key, "api-calls")
            assert result["value_added"] == 1.0

    async def test_small_fractional_value(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            result = await svc.record_usage(session, raw_key, "cpu-seconds", 0.001)
            assert result["value_added"] == 0.001

    async def test_large_value(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            result = await svc.record_usage(session, raw_key, "bytes", 1_000_000.0)
            assert result["value_added"] == 1_000_000.0
            assert result["total_value"] == 1_000_000.0


# ── Usage for Different Feature Types ──


class TestDifferentFeatureTypes:
    """Test usage recording for various metric/feature types."""

    @pytest.mark.parametrize("metric", [
        "api-calls",
        "tokens",
        "bytes",
        "cpu-seconds",
        "storage-gb",
        "queries",
        "agent.CTO.tokens",
    ])
    async def test_various_metric_names(self, db, svc, licensing_svc, metric):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            result = await svc.record_usage(session, raw_key, metric, 10.0)
            assert result["success"] is True
            assert result["metric"] == metric

    async def test_multiple_metrics_per_license(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        metrics = ["tokens", "api-calls", "bytes", "cpu-seconds"]
        for metric in metrics:
            async with db.get_session() as session:
                await svc.record_usage(session, raw_key, metric, 10.0)
        async with db.get_session() as session:
            summaries = await svc.get_usage_summary(session, lic.id)
            assert len(summaries) == len(metrics)


# ── Usage Quota Checks ──


class TestUsageQuotaChecks:
    """Test entitlement-based quota checking."""

    async def test_quota_with_dict_entitlement(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(
            db, licensing_svc,
            entitlements={"api-calls": {"enabled": True, "limit": 100}},
        )
        async with db.get_session() as session:
            result = await svc.record_usage(session, raw_key, "api-calls", 30.0)
            assert result["limit"] == 100
            assert result["remaining"] == 70.0

    async def test_quota_exact_limit(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(
            db, licensing_svc,
            entitlements={"tokens": {"enabled": True, "limit": 100}},
        )
        async with db.get_session() as session:
            result = await svc.record_usage(session, raw_key, "tokens", 100.0)
            assert result["remaining"] == 0.0

    async def test_quota_no_limit_in_entitlement(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(
            db, licensing_svc,
            entitlements={"tokens": {"enabled": True}},
        )
        async with db.get_session() as session:
            result = await svc.record_usage(session, raw_key, "tokens", 9999.0)
            assert result["limit"] is None
            assert result["remaining"] is None

    async def test_summary_remaining_with_overage(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(
            db, licensing_svc,
            entitlements={"tokens": {"enabled": True, "limit": 50}},
        )
        async with db.get_session() as session:
            await svc.record_usage(session, raw_key, "tokens", 80.0)
        async with db.get_session() as session:
            summaries = await svc.get_usage_summary(session, lic.id)
            token_summary = [s for s in summaries if s["metric"] == "tokens"][0]
            assert token_summary["remaining"] == 0.0
            assert token_summary["total_value"] == 80.0


# ── License Status Enforcement ──


class TestLicenseStatusEnforcement:
    """Test that usage is rejected for invalid license statuses."""

    async def test_suspended_license_rejected(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc, status="suspended")
        with pytest.raises(LicenseSuspendedError):
            async with db.get_session() as session:
                await svc.record_usage(session, raw_key, "api-calls")

    async def test_revoked_license_rejected(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc, status="revoked")
        with pytest.raises(LicenseSuspendedError):
            async with db.get_session() as session:
                await svc.record_usage(session, raw_key, "api-calls")

    async def test_expired_license_rejected(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc, status="expired")
        with pytest.raises(LicenseExpiredError):
            async with db.get_session() as session:
                await svc.record_usage(session, raw_key, "api-calls")


# ── Schema Validation ──


class TestUsageSchemas:
    """Test Pydantic schema validation for usage types."""

    def test_usage_record_request_defaults(self):
        req = UsageRecordRequest(key="test-key", metric="api-calls")
        assert req.value == 1.0
        assert req.metadata == {}

    def test_usage_record_request_custom(self):
        req = UsageRecordRequest(
            key="test-key", metric="tokens", value=500.0,
            metadata={"source": "api"},
        )
        assert req.value == 500.0
        assert req.metadata == {"source": "api"}

    def test_usage_record_response(self):
        resp = UsageRecordResponse(
            success=True, metric="tokens", value_added=100.0,
            total_value=500.0, limit=1000, remaining=500.0, code="RECORDED",
        )
        assert resp.success is True
        assert resp.remaining == 500.0

    def test_usage_summary_schema(self):
        summary = UsageSummary(
            metric="tokens", total_value=300.0, record_count=5,
            limit=1000, remaining=700.0,
        )
        assert summary.metric == "tokens"
        assert summary.total_value == 300.0
        assert summary.record_count == 5

    def test_usage_summary_no_limit(self):
        summary = UsageSummary(
            metric="api-calls", total_value=50.0, record_count=50,
        )
        assert summary.limit is None
        assert summary.remaining is None

    def test_usage_record_request_rejects_empty_metric(self):
        with pytest.raises(Exception):
            UsageRecordRequest(key="test-key", metric="")


# ── Agent Usage ──


class TestAgentUsageSummary:
    """Test the agent-specific usage summary."""

    async def test_agent_usage_empty(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            result = await svc.get_agent_usage_summary(session, lic.id)
            assert result == {}

    async def test_agent_usage_records(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        async with db.get_session() as session:
            await svc.record_usage(session, raw_key, "agent.CTO.tokens", 500.0)
        async with db.get_session() as session:
            await svc.record_usage(session, raw_key, "agent.CTO.delegations", 3.0)
        async with db.get_session() as session:
            result = await svc.get_agent_usage_summary(session, lic.id)
            assert "CTO" in result
            assert result["CTO"]["tokens"] == 500.0
            assert result["CTO"]["delegations"] == 3.0
