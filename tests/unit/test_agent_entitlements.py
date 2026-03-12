"""Tests for agent-specific entitlement resolution."""

import pytest

from vinzy_engine.licensing.agent_entitlements import (
    AgentEntitlement,
    get_agent_quota,
    get_entitled_agents,
    is_agent_entitled,
    resolve_agent_entitlements,
)


class TestResolveAgentEntitlements:
    def test_resolve_product_only(self):
        product = {
            "agents": {
                "CTO": {"enabled": True, "token_limit": 50000, "model_tier": "premium"},
                "CFO": {"enabled": True, "token_limit": 20000},
            }
        }
        result = resolve_agent_entitlements(product, {})
        assert "CTO" in result
        assert result["CTO"].token_limit == 50000
        assert result["CTO"].model_tier == "premium"
        assert result["CFO"].token_limit == 20000
        assert result["CFO"].model_tier == "standard"

    def test_resolve_with_overrides(self):
        product = {
            "agents": {
                "CTO": {"enabled": True, "token_limit": 50000, "model_tier": "premium"},
            }
        }
        license_ent = {
            "agents": {
                "CTO": {"token_limit": 100000},
                "CDO": {"enabled": True, "token_limit": 30000},
            }
        }
        result = resolve_agent_entitlements(product, license_ent)
        assert result["CTO"].token_limit == 100000  # overridden
        assert result["CTO"].model_tier == "premium"  # kept from product
        assert "CDO" in result
        assert result["CDO"].token_limit == 30000

    def test_agent_disabled(self):
        product = {
            "agents": {
                "CSecO": {"enabled": False},
            }
        }
        result = resolve_agent_entitlements(product, {})
        assert result["CSecO"].enabled is False

    def test_model_tier_override(self):
        product = {
            "agents": {"CTO": {"model_tier": "standard"}}
        }
        license_ent = {
            "agents": {"CTO": {"model_tier": "premium"}}
        }
        result = resolve_agent_entitlements(product, license_ent)
        assert result["CTO"].model_tier == "premium"

    def test_empty_agents(self):
        result = resolve_agent_entitlements({}, {})
        assert result == {}


class TestIsAgentEntitled:
    def test_is_agent_entitled_true(self):
        product = {"agents": {"CTO": {"enabled": True}}}
        assert is_agent_entitled(product, {}, "CTO") is True

    def test_is_agent_entitled_false(self):
        product = {"agents": {"CSecO": {"enabled": False}}}
        assert is_agent_entitled(product, {}, "CSecO") is False

    def test_is_agent_entitled_missing(self):
        assert is_agent_entitled({}, {}, "CTO") is False


class TestGetAgentQuota:
    def test_get_agent_quota(self):
        product = {"agents": {"CTO": {"token_limit": 50000}}}
        assert get_agent_quota(product, {}, "CTO", "token_limit") == 50000

    def test_get_agent_quota_missing_agent(self):
        assert get_agent_quota({}, {}, "CTO", "token_limit") is None


class TestGetEntitledAgents:
    def test_get_entitled_agents(self):
        product = {
            "agents": {
                "CTO": {"enabled": True},
                "CFO": {"enabled": True},
                "CSecO": {"enabled": False},
            }
        }
        agents = get_entitled_agents(product, {})
        assert set(agents) == {"CTO", "CFO"}
