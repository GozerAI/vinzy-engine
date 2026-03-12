"""Tests for tier template definitions and resolution."""

import pytest

from vinzy_engine.licensing.tier_templates import (
    PRODUCT_CODES,
    PRODUCT_SEEDS,
    USAGE_LIMITS,
    get_machines_limit,
    get_tier_limits,
    resolve_tier_features,
)


class TestResolveTierFeatures:
    """Test resolve_tier_features for all product/tier combos."""

    def test_community_returns_empty(self):
        for code in PRODUCT_CODES:
            features = resolve_tier_features(code, "community")
            assert features == {}, f"{code} community should have no features"

    def test_pro_has_features(self):
        for code in PRODUCT_CODES:
            features = resolve_tier_features(code, "pro")
            assert len(features) > 0, f"{code} pro should have features"

    def test_enterprise_superset_of_pro(self):
        for code in PRODUCT_CODES:
            pro = resolve_tier_features(code, "pro")
            ent = resolve_tier_features(code, "enterprise")
            for key in pro:
                assert key in ent, f"{code} enterprise missing pro feature: {key}"
            assert len(ent) >= len(pro), f"{code} enterprise should have >= pro features"

    def test_unknown_product_raises(self):
        with pytest.raises(ValueError, match="Unknown product code"):
            resolve_tier_features("XXX", "pro")

    def test_unknown_tier_raises(self):
        with pytest.raises(ValueError, match="Unknown tier"):
            resolve_tier_features("AGW", "gold")

    def test_case_insensitive(self):
        assert resolve_tier_features("agw", "PRO") == resolve_tier_features("AGW", "pro")

    # ── AGW specifics ──

    def test_agw_pro_has_learning(self):
        f = resolve_tier_features("AGW", "pro")
        assert f["agw.learning.pipeline"] is True
        assert f["agw.learning.self_architect"] is True
        assert "agw.vls.pipeline" not in f

    def test_agw_enterprise_has_vls(self):
        f = resolve_tier_features("AGW", "enterprise")
        assert f["agw.vls.pipeline"] is True
        assert f["agw.distributed.fleet"] is True
        assert f["agw.metacognition.advanced"] is True

    # ── ZUL specifics ──

    def test_zul_pro_has_rbac_sso(self):
        f = resolve_tier_features("ZUL", "pro")
        assert f["zul.rbac.matrix"] is True
        assert f["zul.sso.oidc"] is True
        assert "zul.gateway.middleware" not in f

    def test_zul_enterprise_has_gateway(self):
        f = resolve_tier_features("ZUL", "enterprise")
        assert f["zul.gateway.middleware"] is True
        assert f["zul.injection.patterns"] is True

    # ── VNZ specifics ──

    def test_vnz_pro_has_hmac(self):
        f = resolve_tier_features("VNZ", "pro")
        assert f["vnz.hmac.keyring"] is True
        assert "vnz.agents.entitlements" not in f

    def test_vnz_enterprise_has_agents(self):
        f = resolve_tier_features("VNZ", "enterprise")
        assert f["vnz.agents.entitlements"] is True
        assert f["vnz.tenants.multi"] is True

    # ── CSM specifics ──

    def test_csm_pro_has_distillation(self):
        f = resolve_tier_features("CSM", "pro")
        assert f["csm.distillation.multi_teacher"] is True

    def test_csm_enterprise_has_executives(self):
        f = resolve_tier_features("CSM", "enterprise")
        assert f["csm.executives.personalities"] is True

    # ── STD specifics ──

    def test_std_pro_has_advanced(self):
        f = resolve_tier_features("STD", "pro")
        assert f["std.trendscope.advanced"] is True

    def test_std_enterprise_has_enterprise(self):
        f = resolve_tier_features("STD", "enterprise")
        assert f["std.trendscope.enterprise"] is True


class TestGetTierLimits:
    def test_pro_limits(self):
        limits = get_tier_limits("pro")
        assert limits["agent_operations"] == 100_000
        assert limits["machine_activations"] == 3
        assert limits["security_scans"] == 10_000

    def test_enterprise_limits(self):
        limits = get_tier_limits("enterprise")
        assert limits["agent_operations"] == 1_000_000
        assert limits["vls_launches"] == 10

    def test_community_empty(self):
        assert get_tier_limits("community") == {}

    def test_unknown_tier_empty(self):
        assert get_tier_limits("gold") == {}


class TestGetMachinesLimit:
    def test_pro(self):
        assert get_machines_limit("pro") == 3

    def test_enterprise_unlimited(self):
        assert get_machines_limit("enterprise") == 0

    def test_community(self):
        assert get_machines_limit("community") == 1


class TestProductSeeds:
    def test_five_products(self):
        assert len(PRODUCT_SEEDS) == 5

    def test_all_codes_present(self):
        codes = {s["code"] for s in PRODUCT_SEEDS}
        assert codes == {"AGW", "ZUL", "VNZ", "CSM", "STD"}

    def test_seeds_have_required_fields(self):
        for seed in PRODUCT_SEEDS:
            assert "code" in seed
            assert "name" in seed
            assert "description" in seed
            assert "default_tier" in seed
