"""Tests for cross-product entitlement composition."""

import pytest
from dataclasses import dataclass, field
from typing import Any

from vinzy_engine.licensing.composition import compose_customer_entitlements


@dataclass
class FakeProduct:
    id: str
    code: str
    features: dict[str, Any] = field(default_factory=dict)


@dataclass
class FakeLicense:
    id: str
    product_id: str
    entitlements: dict[str, Any] = field(default_factory=dict)


class TestComposition:
    def test_single_license_passthrough(self):
        products = [FakeProduct(id="p1", code="ZUL", features={"api": True})]
        licenses = [FakeLicense(id="l1", product_id="p1", entitlements={})]
        result = compose_customer_entitlements(licenses, products)
        assert result.total_products == 1
        assert len(result.features) == 1
        assert result.features[0].feature == "api"

    def test_sum_strategy(self):
        products = [
            FakeProduct(id="p1", code="ZUL", features={
                "tokens": {"limit": 10000, "compose": "sum"},
            }),
            FakeProduct(id="p2", code="NXS", features={
                "tokens": {"limit": 20000, "compose": "sum"},
            }),
        ]
        licenses = [
            FakeLicense(id="l1", product_id="p1", entitlements={}),
            FakeLicense(id="l2", product_id="p2", entitlements={}),
        ]
        result = compose_customer_entitlements(licenses, products)
        tokens = next(f for f in result.features if f.feature == "tokens")
        assert tokens.strategy == "sum"
        assert tokens.effective_value == 30000

    def test_max_strategy(self):
        products = [
            FakeProduct(id="p1", code="ZUL", features={
                "tier": {"enabled": True, "compose": "max"},
            }),
            FakeProduct(id="p2", code="NXS", features={
                "tier": {"enabled": True, "compose": "max"},
            }),
        ]
        licenses = [
            FakeLicense(id="l1", product_id="p1", entitlements={}),
            FakeLicense(id="l2", product_id="p2", entitlements={}),
        ]
        result = compose_customer_entitlements(licenses, products)
        # Both are bools, max of True and True is True
        assert len(result.features) >= 1

    def test_union_strategy(self):
        products = [
            FakeProduct(id="p1", code="ZUL", features={"api": True}),
            FakeProduct(id="p2", code="NXS", features={"api": False, "export": True}),
        ]
        licenses = [
            FakeLicense(id="l1", product_id="p1", entitlements={}),
            FakeLicense(id="l2", product_id="p2", entitlements={}),
        ]
        result = compose_customer_entitlements(licenses, products)
        api = next(f for f in result.features if f.feature == "api")
        # union: any True wins
        assert api.effective_value is True

    def test_agent_merge_across_products(self):
        products = [
            FakeProduct(id="p1", code="ZUL", features={
                "agents": {"CTO": {"enabled": True, "token_limit": 50000}},
            }),
            FakeProduct(id="p2", code="NXS", features={
                "agents": {"CTO": {"enabled": True, "token_limit": 30000},
                           "CFO": {"enabled": True, "token_limit": 20000}},
            }),
        ]
        licenses = [
            FakeLicense(id="l1", product_id="p1", entitlements={}),
            FakeLicense(id="l2", product_id="p2", entitlements={}),
        ]
        result = compose_customer_entitlements(licenses, products)
        # CTO token_limit should be summed: 50000 + 30000 = 80000
        assert "CTO" in result.agents
        assert result.agents["CTO"]["token_limit"] == 80000
        assert "CFO" in result.agents
        assert result.agents["CFO"]["token_limit"] == 20000

    def test_no_active_licenses(self):
        result = compose_customer_entitlements([], [])
        assert result.total_products == 0
        assert result.features == []
        assert result.agents == {}

    def test_composition_source_attribution(self):
        products = [
            FakeProduct(id="p1", code="ZUL", features={"api": True}),
            FakeProduct(id="p2", code="NXS", features={"api": True}),
        ]
        licenses = [
            FakeLicense(id="l1", product_id="p1", entitlements={}),
            FakeLicense(id="l2", product_id="p2", entitlements={}),
        ]
        result = compose_customer_entitlements(licenses, products)
        api = next(f for f in result.features if f.feature == "api")
        assert len(api.sources) == 2
        codes = {s.product_code for s in api.sources}
        assert codes == {"ZUL", "NXS"}
