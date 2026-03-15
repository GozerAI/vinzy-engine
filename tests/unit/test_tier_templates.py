"""Tests for tier template definitions and resolution."""

import pytest

from vinzy_engine.licensing.tier_templates import (
    AI_CREDITS,
    BUNDLE_DEFINITIONS,
    FOUNDER_PRICING,
    MODEL_CREDIT_COSTS,
    PHASE_CONFIG,
    PRODUCT_CODES,
    PRODUCT_SEEDS,
    PRICING,
    USAGE_LIMITS,
    _PRODUCT_FEATURE_RESOLVERS,
    get_machines_limit,
    get_tier_limits,
    resolve_tier_features,
)

# Only codes that have feature resolvers
RESOLVER_CODES = list(_PRODUCT_FEATURE_RESOLVERS.keys())


class TestResolveTierFeatures:
    """Test resolve_tier_features for all product/tier combos."""

    def test_community_returns_empty(self):
        for code in RESOLVER_CODES:
            features = resolve_tier_features(code, "community")
            assert features == {}, f"{code} community should have no features"

    def test_pro_has_features(self):
        for code in RESOLVER_CODES:
            features = resolve_tier_features(code, "pro")
            assert len(features) > 0, f"{code} pro should have features"

    def test_scale_superset_of_pro(self):
        for code in RESOLVER_CODES:
            pro = resolve_tier_features(code, "pro")
            scale = resolve_tier_features(code, "scale")
            for key in pro:
                assert key in scale, f"{code} scale missing pro feature: {key}"
            assert len(scale) >= len(pro), f"{code} scale should have >= pro features"

    def test_growth_equals_scale(self):
        for code in RESOLVER_CODES:
            growth = resolve_tier_features(code, "growth")
            scale = resolve_tier_features(code, "scale")
            assert growth == scale, f"{code} growth should equal scale features"

    def test_unknown_product_raises(self):
        with pytest.raises(ValueError, match="Unknown product code"):
            resolve_tier_features("XXX", "pro")

    def test_unknown_tier_raises(self):
        with pytest.raises(ValueError, match="Unknown tier"):
            resolve_tier_features("AGW", "gold")

    def test_case_insensitive(self):
        assert resolve_tier_features("agw", "PRO") == resolve_tier_features("AGW", "pro")

    # ── Backward compat: "business" and "enterprise" still work ──

    def test_business_alias_resolves(self):
        for code in RESOLVER_CODES:
            growth = resolve_tier_features(code, "growth")
            business = resolve_tier_features(code, "business")
            assert growth == business, f"{code} business should alias to growth"

    def test_enterprise_alias_resolves(self):
        for code in RESOLVER_CODES:
            scale = resolve_tier_features(code, "scale")
            enterprise = resolve_tier_features(code, "enterprise")
            assert scale == enterprise, f"{code} enterprise should alias to scale"

    # ── AGW specifics ──

    def test_agw_pro_has_learning(self):
        f = resolve_tier_features("AGW", "pro")
        assert f["agw.learning.pipeline"] is True
        assert f["agw.learning.self_architect"] is True
        assert "agw.vls.pipeline" not in f

    def test_agw_scale_has_vls(self):
        f = resolve_tier_features("AGW", "scale")
        assert f["agw.vls.pipeline"] is True
        assert f["agw.distributed.fleet"] is True
        assert f["agw.metacognition.advanced"] is True

    # ── NXS specifics ──

    def test_nxs_pro_has_reasoning_ensemble(self):
        f = resolve_tier_features("NXS", "pro")
        assert f["nxs.reasoning.advanced"] is True
        assert f["nxs.ensemble.multi_model"] is True
        assert "nxs.discovery.intelligence" not in f

    def test_nxs_scale_has_discovery_strategic(self):
        f = resolve_tier_features("NXS", "scale")
        assert f["nxs.discovery.intelligence"] is True
        assert f["nxs.strategic.analysis"] is True
        assert f["nxs.reasoning.advanced"] is True

    # ── ZUL specifics ──

    def test_zul_pro_has_rbac_sso(self):
        f = resolve_tier_features("ZUL", "pro")
        assert f["zul.rbac.matrix"] is True
        assert f["zul.sso.oidc"] is True
        assert "zul.gateway.middleware" not in f

    def test_zul_scale_has_gateway(self):
        f = resolve_tier_features("ZUL", "scale")
        assert f["zul.gateway.middleware"] is True
        assert f["zul.injection.patterns"] is True

    # ── VNZ specifics ──

    def test_vnz_pro_has_hmac(self):
        f = resolve_tier_features("VNZ", "pro")
        assert f["vnz.hmac.keyring"] is True
        assert "vnz.agents.entitlements" not in f

    def test_vnz_scale_has_agents(self):
        f = resolve_tier_features("VNZ", "scale")
        assert f["vnz.agents.entitlements"] is True
        assert f["vnz.tenants.multi"] is True

    # ── CSM specifics ──

    def test_csm_pro_has_distillation(self):
        f = resolve_tier_features("CSM", "pro")
        assert f["csm.distillation.multi_teacher"] is True

    def test_csm_scale_has_executives(self):
        f = resolve_tier_features("CSM", "scale")
        assert f["csm.executives.personalities"] is True

    # ── STD specifics ──

    def test_std_pro_has_advanced(self):
        f = resolve_tier_features("STD", "pro")
        assert f["std.trendscope.advanced"] is True

    def test_std_scale_has_enterprise_flags(self):
        f = resolve_tier_features("STD", "scale")
        assert f["std.trendscope.enterprise"] is True


class TestGetTierLimits:
    def test_pro_limits(self):
        limits = get_tier_limits("pro")
        assert limits["ai_credits"] == 5_000
        assert limits["machine_activations"] == 3

    def test_growth_limits(self):
        limits = get_tier_limits("growth")
        assert limits["ai_credits"] == 25_000
        assert limits["machine_activations"] == 10

    def test_scale_limits(self):
        limits = get_tier_limits("scale")
        assert limits["ai_credits"] == 80_000
        assert limits["machine_activations"] == 0

    def test_community_empty(self):
        assert get_tier_limits("community") == {}

    def test_unknown_tier_empty(self):
        assert get_tier_limits("gold") == {}

    def test_business_alias(self):
        assert get_tier_limits("business") == get_tier_limits("growth")

    def test_enterprise_alias(self):
        assert get_tier_limits("enterprise") == get_tier_limits("scale")


class TestGetMachinesLimit:
    def test_pro(self):
        assert get_machines_limit("pro") == 3

    def test_growth(self):
        assert get_machines_limit("growth") == 10

    def test_scale_unlimited(self):
        assert get_machines_limit("scale") == 0

    def test_community(self):
        assert get_machines_limit("community") == 1

    def test_business_alias(self):
        assert get_machines_limit("business") == 10

    def test_enterprise_alias(self):
        assert get_machines_limit("enterprise") == 0


class TestProductSeeds:
    def test_product_count(self):
        assert len(PRODUCT_SEEDS) == 7

    def test_core_codes_present(self):
        codes = {s["code"] for s in PRODUCT_SEEDS}
        assert {"AGW", "NXS", "ZUL", "VNZ", "CSM", "STD", "ARC"} <= codes

    def test_seeds_have_required_fields(self):
        for seed in PRODUCT_SEEDS:
            assert "code" in seed
            assert "name" in seed
            assert "description" in seed
            assert "default_tier" in seed


class TestPricingStructure:
    def test_platform_tiers_exist(self):
        assert "platform_pro" in PRICING
        assert "platform_growth" in PRICING
        assert "platform_scale" in PRICING

    def test_single_product_tiers_exist(self):
        assert "single_pro" in PRICING
        assert "single_growth" in PRICING

    def test_bundle_tiers_exist(self):
        assert "bundle_small_pro" in PRICING
        assert "bundle_medium_growth" in PRICING

    def test_arclane_pro_exists(self):
        assert "arclane_pro" in PRICING

    def test_yearly_cheaper_than_12x_monthly(self):
        for key, prices in PRICING.items():
            if "yearly" in prices:
                assert prices["yearly"] <= prices["monthly"] * 12, (
                    f"{key} yearly should be <= 12x monthly"
                )

    def test_quarterly_cheaper_than_3x_monthly(self):
        for key, prices in PRICING.items():
            if "quarterly" in prices:
                assert prices["quarterly"] <= prices["monthly"] * 3, (
                    f"{key} quarterly should be <= 3x monthly"
                )

    def test_backward_compat_aliases(self):
        assert PRICING["platform_business"] == PRICING["platform_growth"]
        assert PRICING["platform_enterprise"] == PRICING["platform_scale"]
        assert PRICING["single_business"] == PRICING["single_growth"]


class TestAICredits:
    def test_platform_credits_scale(self):
        assert AI_CREDITS["platform_pro"] < AI_CREDITS["platform_growth"]
        assert AI_CREDITS["platform_growth"] < AI_CREDITS["platform_scale"]

    def test_single_less_than_platform(self):
        assert AI_CREDITS["single_pro"] < AI_CREDITS["platform_pro"]

    def test_model_credit_costs(self):
        assert MODEL_CREDIT_COSTS["haiku"] < MODEL_CREDIT_COSTS["sonnet"]
        assert MODEL_CREDIT_COSTS["sonnet"] < MODEL_CREDIT_COSTS["opus"]

    def test_backward_compat_aliases(self):
        assert AI_CREDITS["platform_business"] == AI_CREDITS["platform_growth"]
        assert AI_CREDITS["platform_enterprise"] == AI_CREDITS["platform_scale"]


class TestBundleDefinitions:
    def test_bundles_exist(self):
        assert len(BUNDLE_DEFINITIONS) >= 3

    def test_bundle_products_are_valid_codes(self):
        for key, bundle in BUNDLE_DEFINITIONS.items():
            for code in bundle["products"]:
                assert code in PRODUCT_CODES, f"Bundle {key} has invalid code: {code}"

    def test_bundle_sizes(self):
        for key, bundle in BUNDLE_DEFINITIONS.items():
            assert bundle["size"] in ("small", "medium"), f"Bundle {key} has invalid size"


class TestFounderPricing:
    def test_founder_prices_below_standard(self):
        for key, founder in FOUNDER_PRICING.items():
            if key in PRICING:
                assert founder["monthly"] < PRICING[key]["monthly"], (
                    f"Founder price for {key} should be below standard"
                )

    def test_founder_monthly_only(self):
        for key, founder in FOUNDER_PRICING.items():
            assert "monthly" in founder
            assert "quarterly" not in founder
            assert "yearly" not in founder


class TestPhaseConfig:
    def test_phases_exist(self):
        assert "founder" in PHASE_CONFIG
        assert "prelaunch" in PHASE_CONFIG
        assert "full" in PHASE_CONFIG

    def test_founder_monthly_only(self):
        assert PHASE_CONFIG["founder"]["billing_cycles"] == ["monthly"]

    def test_full_all_cycles(self):
        assert "monthly" in PHASE_CONFIG["full"]["billing_cycles"]
        assert "quarterly" in PHASE_CONFIG["full"]["billing_cycles"]
        assert "yearly" in PHASE_CONFIG["full"]["billing_cycles"]

    def test_founder_free_and_pro_only(self):
        assert PHASE_CONFIG["founder"]["available_tiers"] == ["free", "pro"]

    def test_prelaunch_adds_growth(self):
        assert "growth" in PHASE_CONFIG["prelaunch"]["available_tiers"]

    def test_full_has_all_tiers(self):
        assert "scale" in PHASE_CONFIG["full"]["available_tiers"]

    def test_mrr_thresholds_ascending(self):
        assert PHASE_CONFIG["founder"]["mrr_threshold"] < PHASE_CONFIG["prelaunch"]["mrr_threshold"]
        assert PHASE_CONFIG["prelaunch"]["mrr_threshold"] < PHASE_CONFIG["full"]["mrr_threshold"]
