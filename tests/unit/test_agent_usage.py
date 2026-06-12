"""Tests for agent-aware usage aggregation and quota checking."""

import pytest

from vinzy_engine.common.config import VinzySettings
from vinzy_engine.common.database import DatabaseManager
from vinzy_engine.licensing.service import LicensingService
from vinzy_engine.usage.service import UsageService
from vinzy_engine.usage.agent_usage import (
    aggregate_agent_usage,
    check_agent_quota,
    parse_agent_metric,
)


HMAC_KEY = "test-hmac-key-for-unit-tests"


def make_settings(**overrides) -> VinzySettings:
    defaults = {"hmac_key": HMAC_KEY, "db_url": "sqlite+aiosqlite://"}
    defaults.update(overrides)
    return VinzySettings(**defaults)


class TestParseAgentMetric:
    def test_parse_agent_metric(self):
        result = parse_agent_metric("agent.CTO.tokens")
        assert result == ("CTO", "tokens")

    def test_parse_non_agent_metric(self):
        result = parse_agent_metric("api_calls")
        assert result is None

    def test_parse_incomplete(self):
        result = parse_agent_metric("agent.CTO")
        assert result is None


class TestAggregateAgentUsage:
    def test_aggregate_agent_usage(self):
        records = [
            {"metric": "agent.CTO.tokens", "value": 3000},
            {"metric": "agent.CTO.tokens", "value": 2000},
            {"metric": "agent.CTO.delegations", "value": 5},
            {"metric": "agent.CFO.tokens", "value": 1000},
            {"metric": "api_calls", "value": 10},  # not agent-prefixed
        ]
        result = aggregate_agent_usage(records)
        assert result["CTO"]["tokens"] == 5000
        assert result["CTO"]["delegations"] == 5
        assert result["CFO"]["tokens"] == 1000
        assert "api_calls" not in result  # non-agent metrics ignored


class TestCheckAgentQuota:
    def test_check_agent_quota_ok(self):
        usage = {"tokens": 5000, "delegations": 12}
        entitlement = {"token_limit": 10000, "enabled": True}
        result = check_agent_quota(usage, entitlement)
        assert result["within_quota"] is True
        assert result["violations"] == []

    def test_check_agent_quota_violation(self):
        usage = {"tokens": 15000}
        entitlement = {"token_limit": 10000}
        result = check_agent_quota(usage, entitlement)
        assert result["within_quota"] is False
        assert len(result["violations"]) == 1
        assert result["violations"][0]["overage"] == 5000


# Service-level test with real DB

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


async def _create_license(db, licensing_svc):
    async with db.get_session() as session:
        await licensing_svc.create_product(session, "ZUL", "Zuultimate")
        customer = await licensing_svc.create_customer(
            session, "Test", "test@example.com"
        )
    async with db.get_session() as session:
        lic, raw_key = await licensing_svc.create_license(
            session, "ZUL", customer.id
        )
    return lic, raw_key


class TestGetAgentUsageSummary:
    async def test_get_agent_usage_summary(self, db, svc, licensing_svc):
        lic, raw_key = await _create_license(db, licensing_svc)
        # Record some agent-prefixed usage
        async with db.get_session() as session:
            await svc.record_usage(session, raw_key, "agent.CTO.tokens", 3000)
        async with db.get_session() as session:
            await svc.record_usage(session, raw_key, "agent.CTO.tokens", 2000)
        async with db.get_session() as session:
            await svc.record_usage(session, raw_key, "agent.CFO.delegations", 5)
        async with db.get_session() as session:
            await svc.record_usage(session, raw_key, "api_calls", 10)  # not agent
        async with db.get_session() as session:
            summary = await svc.get_agent_usage_summary(session, lic.id)
            assert "CTO" in summary
            assert summary["CTO"]["tokens"] == 5000
            assert "CFO" in summary
            assert summary["CFO"]["delegations"] == 5
            # Non-agent metrics should not appear
            assert "api_calls" not in summary
