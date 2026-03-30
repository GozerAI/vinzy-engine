"""Tier definitions and feature flags for all GozerAI products.

Each product has tiers: community, pro, growth, scale.
Legacy aliases "business" and "enterprise" map to growth and scale respectively.
Feature flags follow the convention: {product}.{module}.{capability}

Enforcement philosophy:
- No license key set → community only
- Key + entitled → allow
- Key + NOT entitled → block with pricing URL
- Server unreachable → community only (fail-closed for gated features)
"""

from typing import Any

# ── Product codes ──
PRODUCT_CODES = {
    "AGW": "ag3ntwerk",
    "NXS": "nexus",
    "ZUL": "zuultimate",
    "VNZ": "vinzy-engine",
    "CSM": "csuite-model",
    "STD": "standalone-bundle",
    "TS": "trendscope",
    "SF": "shopforge",
    "BG": "brandguard",
    "TP": "taskpilot",
    "CS": "claude-swarm",
    "SN": "sentinel",
    "SC": "shandorcode",
    "GO": "gpu-orchestra",
    "ARC": "arclane",
}

# ── Phased rollout ──
PHASE_CONFIG = {
    "founder": {
        "available_tiers": ["free", "pro"],
        "billing_cycles": ["monthly"],
        "mrr_threshold": 0,
    },
    "prelaunch": {
        "available_tiers": ["free", "pro", "growth"],
        "billing_cycles": ["monthly", "quarterly", "yearly"],
        "mrr_threshold": 40_000,
    },
    "full": {
        "available_tiers": ["free", "pro", "growth", "scale"],
        "billing_cycles": ["monthly", "quarterly", "yearly"],
        "mrr_threshold": 80_000,
    },
}

# ── Founder pricing (active during founder phase) ──
FOUNDER_PRICING = {
    "platform_pro": {"monthly": 69},
    "single_pro": {"monthly": 19},
    "bundle_small_pro": {"monthly": 34},
    "bundle_medium_pro": {"monthly": 55},
    "arclane_pro": {"monthly": 69},
}

# ── AI Credit allocations per plan ──
AI_CREDITS = {
    # Platform tiers (all 10 products)
    "platform_pro": 5_000,
    "platform_growth": 25_000,
    "platform_scale": 80_000,
    # Single product tiers
    "single_pro": 1_500,
    "single_growth": 6_000,
    # Bundle tiers (2-3 products)
    "bundle_small_pro": 3_000,
    "bundle_small_growth": 14_000,
    # Bundle tiers (4-6 products)
    "bundle_medium_pro": 5_000,
    "bundle_medium_growth": 22_000,
}
# Backward compat aliases
AI_CREDITS["platform_business"] = AI_CREDITS["platform_growth"]
AI_CREDITS["platform_enterprise"] = AI_CREDITS["platform_scale"]
AI_CREDITS["single_business"] = AI_CREDITS["single_growth"]
AI_CREDITS["bundle_small_business"] = AI_CREDITS["bundle_small_growth"]
AI_CREDITS["bundle_medium_business"] = AI_CREDITS["bundle_medium_growth"]

# ── Credit costs per model ──
MODEL_CREDIT_COSTS = {
    "haiku": 2,
    "sonnet": 5,
    "opus": 10,
    "gpt-4o": 6,
    "gpt-4o-mini": 2,
}

# ── Usage limits per tier ──
USAGE_LIMITS = {
    "pro": {
        "ai_credits": 5_000,
        "machine_activations": 3,
    },
    "growth": {
        "ai_credits": 25_000,
        "machine_activations": 10,
    },
    "scale": {
        "ai_credits": 80_000,
        "machine_activations": 0,  # unlimited
    },
}
# Backward compat aliases
USAGE_LIMITS["business"] = USAGE_LIMITS["growth"]
USAGE_LIMITS["enterprise"] = USAGE_LIMITS["scale"]

# ── Overage pricing (per credit, by tier) ──
OVERAGE_RATES = {
    "pro": 0.018,
    "growth": 0.014,
    "scale": 0.010,
    "machine_activations": 49.0,
}
# Backward compat aliases
OVERAGE_RATES["business"] = OVERAGE_RATES["growth"]
OVERAGE_RATES["enterprise"] = OVERAGE_RATES["scale"]

# ── Standard pricing (post-founder) ──
# Quarterly = 10% off (3 × monthly × 0.9), Annual = 2 months free (10 × monthly)
PRICING = {
    # Platform tiers (all 10 products)
    "platform_pro": {"monthly": 99, "quarterly": 267, "yearly": 990},
    "platform_growth": {"monthly": 349, "quarterly": 942, "yearly": 3490},
    "platform_scale": {"monthly": 899, "quarterly": 2427, "yearly": 8990},
    # Single product
    "single_pro": {"monthly": 29, "quarterly": 78, "yearly": 290},
    "single_growth": {"monthly": 79, "quarterly": 213, "yearly": 790},
    # Bundles (2-3 products)
    "bundle_small_pro": {"monthly": 49, "quarterly": 132, "yearly": 490},
    "bundle_small_growth": {"monthly": 149, "quarterly": 402, "yearly": 1490},
    # Bundles (4-6 products)
    "bundle_medium_pro": {"monthly": 79, "quarterly": 213, "yearly": 790},
    "bundle_medium_growth": {"monthly": 249, "quarterly": 672, "yearly": 2490},
    # Arclane
    "arclane_pro": {"monthly": 99, "quarterly": 267, "yearly": 990},
}
# Backward compat aliases
PRICING["platform_business"] = PRICING["platform_growth"]
PRICING["platform_enterprise"] = PRICING["platform_scale"]
PRICING["single_business"] = PRICING["single_growth"]
PRICING["bundle_small_business"] = PRICING["bundle_small_growth"]
PRICING["bundle_medium_business"] = PRICING["bundle_medium_growth"]

# ── Pre-built themed bundles ──
BUNDLE_DEFINITIONS = {
    "developer": {
        "name": "Developer Bundle",
        "products": ["SC", "CS", "GO"],
        "size": "small",
    },
    "commerce": {
        "name": "Commerce Bundle",
        "products": ["SF", "BG", "TS"],
        "size": "small",
    },
    "intelligence": {
        "name": "Intelligence Bundle",
        "products": ["NXS", "SN"],
        "size": "small",
    },
    "ops_suite": {
        "name": "Ops Suite",
        "products": ["TP", "SN", "NXS", "GO"],
        "size": "medium",
    },
    "ai_builder": {
        "name": "AI Builder Bundle",
        "products": ["CS", "NXS", "SC", "GO"],
        "size": "medium",
    },
}


def _nxs_features(tier: str) -> dict[str, Any]:
    """nexus feature flags by tier."""
    if tier == "community":
        return {}

    pro = {
        "nxs.reasoning.advanced": True,
        "nxs.ensemble.multi_model": True,
    }
    if tier == "pro":
        return pro

    return {
        **pro,
        "nxs.discovery.intelligence": True,
        "nxs.strategic.analysis": True,
    }


def _agw_features(tier: str) -> dict[str, Any]:
    """ag3ntwerk feature flags by tier."""
    if tier == "community":
        return {}

    pro = {
        "agw.learning.pipeline": True,
        "agw.learning.facades": True,
        "agw.learning.self_architect": True,
        "agw.learning.meta_learner": True,
        "agw.learning.cascade_predictor": True,
    }
    if tier == "pro":
        return pro

    # growth/scale = pro + tier-1
    return {
        **pro,
        "agw.vls.pipeline": True,
        "agw.vls.evidence": True,
        "agw.vls.workflows": True,
        "agw.metacognition.advanced": True,
        "agw.distributed.fleet": True,
        "agw.swarm_bridge": True,
    }


def _zul_features(tier: str) -> dict[str, Any]:
    """zuultimate feature flags by tier."""
    if tier == "community":
        return {}

    pro = {
        "zul.rbac.matrix": True,
        "zul.compliance.reporter": True,
        "zul.sso.oidc": True,
    }
    if tier == "pro":
        return pro

    return {
        **pro,
        "zul.gateway.middleware": True,
        "zul.gateway.standalone": True,
        "zul.toolguard.pipeline": True,
        "zul.injection.patterns": True,
        "zul.redteam.tool": True,
    }


def _vnz_features(tier: str) -> dict[str, Any]:
    """vinzy-engine feature flags by tier."""
    if tier == "community":
        return {}

    pro = {
        "vnz.hmac.keyring": True,
        "vnz.hmac.rotation": True,
        "vnz.composition.cross_product": True,
        "vnz.anomaly.detection": True,
    }
    if tier == "pro":
        return pro

    return {
        **pro,
        "vnz.agents.entitlements": True,
        "vnz.agents.leases": True,
        "vnz.audit.chain": True,
        "vnz.tenants.multi": True,
    }


def _csm_features(tier: str) -> dict[str, Any]:
    """csuite-model feature flags by tier."""
    if tier == "community":
        return {}

    pro = {
        "csm.distillation.multi_teacher": True,
        "csm.distillation.training_phases": True,
        "csm.distillation.eval_suite": True,
    }
    if tier == "pro":
        return pro

    return {
        **pro,
        "csm.executives.personalities": True,
        "csm.executives.governance": True,
        "csm.executives.modelfiles": True,
    }


def _std_features(tier: str) -> dict[str, Any]:
    """standalone-bundle feature flags by tier (trendscope, shopforge, etc.)."""
    if tier == "community":
        return {}

    pro = {
        "std.trendscope.advanced": True,
        "std.shopforge.advanced": True,
        "std.brandguard.advanced": True,
        "std.taskpilot.advanced": True,
        "std.swarm.advanced": True,
        "std.sentinel.discovery": True,
        "std.shandorcode.metrics": True,
    }
    if tier == "pro":
        return pro

    return {
        **pro,
        "std.trendscope.enterprise": True,
        "std.shopforge.enterprise": True,
        "std.brandguard.enterprise": True,
        "std.taskpilot.enterprise": True,
        "std.swarm.enterprise": True,
        "std.sentinel.autonomous": True,
        "std.sentinel.topology": True,
        "std.shandorcode.ai_insights": True,
        "std.shandorcode.boundaries": True,
    }


# Master feature resolvers keyed by product code
_PRODUCT_FEATURE_RESOLVERS = {
    "AGW": _agw_features,
    "NXS": _nxs_features,
    "ZUL": _zul_features,
    "VNZ": _vnz_features,
    "CSM": _csm_features,
    "STD": _std_features,
}

# Canonical tier names and their legacy aliases
_TIER_ALIASES = {
    "business": "growth",
    "enterprise": "scale",
}
_VALID_TIERS = {"community", "pro", "growth", "scale", "business", "enterprise"}


def resolve_tier_features(product_code: str, tier: str) -> dict[str, Any]:
    """Resolve the full feature dict for a product code + tier.

    Args:
        product_code: Product code (AGW, ZUL, VNZ, CSM, STD, etc.).
        tier: One of 'community', 'pro', 'growth', 'scale'
              (legacy: 'business', 'enterprise').

    Returns:
        Dict of feature flags. Each key is a dotted feature path,
        value is True (enabled) or a dict with limit info.

    Raises:
        ValueError: If product_code or tier is unknown.
    """
    code = product_code.upper()
    tier = tier.lower()

    if code not in _PRODUCT_FEATURE_RESOLVERS:
        raise ValueError(f"Unknown product code: {code}")
    if tier not in _VALID_TIERS:
        raise ValueError(
            f"Unknown tier: {tier}. Must be community, pro, growth, or scale"
        )

    # Resolve aliases and map to internal resolver tier
    tier = _TIER_ALIASES.get(tier, tier)
    # growth and scale resolve to the same feature set (superset of pro)
    effective_tier = tier if tier in ("community", "pro") else "enterprise"
    return _PRODUCT_FEATURE_RESOLVERS[code](effective_tier)


def get_tier_limits(tier: str) -> dict[str, int]:
    """Get usage limits for a tier.

    Returns empty dict for community (no limits enforced).
    """
    tier = tier.lower()
    return dict(USAGE_LIMITS.get(tier, {}))


def get_machines_limit(tier: str) -> int:
    """Get machine activation limit for a tier.

    Returns:
        3 for pro, 10 for growth, 0 (unlimited) for scale, 1 for community.
    """
    tier = _TIER_ALIASES.get(tier.lower(), tier.lower())
    if tier == "scale":
        return 0
    if tier == "growth":
        return 10
    if tier == "pro":
        return 3
    return 1


# ── Product seed definitions ──
PRODUCT_SEEDS = [
    {
        "code": "AGW",
        "name": "ag3ntwerk",
        "description": "Multi-agent orchestration framework with learning, VLS, and distributed capabilities",
        "default_tier": "community",
    },
    {
        "code": "NXS",
        "name": "nexus",
        "description": "AI ensemble orchestrator with advanced reasoning, discovery, and strategic analysis",
        "default_tier": "community",
    },
    {
        "code": "ZUL",
        "name": "zuultimate",
        "description": "Enterprise identity, vault, zero-trust, and AI security platform",
        "default_tier": "community",
    },
    {
        "code": "VNZ",
        "name": "vinzy-engine",
        "description": "Cryptographic license key generator and manager",
        "default_tier": "community",
    },
    {
        "code": "CSM",
        "name": "csuite-model",
        "description": "LoRA fine-tuning pipeline for executive AI agents",
        "default_tier": "community",
    },
    {
        "code": "STD",
        "name": "standalone-bundle",
        "description": "Trendscope, Shopforge, Brandguard, Taskpilot, Claude Swarm, Sentinel, ShandorCode, GPU Orchestra",
        "default_tier": "community",
    },
    {
        "code": "ARC",
        "name": "arclane",
        "description": "AI-powered business builder with automated deployment and cycles",
        "default_tier": "community",
    },
]
