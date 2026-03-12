"""Tier definitions and feature flags for all GozerAI products.

Each product has three tiers: community, pro, enterprise.
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
    "ZUL": "zuultimate",
    "VNZ": "vinzy-engine",
    "CSM": "csuite-model",
    "STD": "standalone-bundle",
}

# ── Usage limits per tier ──
USAGE_LIMITS = {
    "pro": {
        "agent_operations": 100_000,
        "machine_activations": 3,
        "security_scans": 10_000,
    },
    "enterprise": {
        "agent_operations": 1_000_000,
        "machine_activations": 0,  # unlimited
        "vls_launches": 10,
        "security_scans": 100_000,
    },
}

# ── Overage pricing (informational, used by billing) ──
OVERAGE_RATES = {
    "agent_operations": 0.001,
    "machine_activations": 49.0,
    "vls_launches": 99.0,
    "security_scans": 0.01,
}

# ── Pricing (informational, stored on product metadata) ──
PRICING = {
    "pro": {"monthly": 149, "yearly": 1490},
    "enterprise": {"monthly": 499, "yearly": 4990},
    "bundle_pro": {"monthly": 499, "yearly": 4990},
    "bundle_enterprise": {"monthly": 1999, "yearly": 19990},
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

    # enterprise = pro + tier-1
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
    "ZUL": _zul_features,
    "VNZ": _vnz_features,
    "CSM": _csm_features,
    "STD": _std_features,
}


def resolve_tier_features(product_code: str, tier: str) -> dict[str, Any]:
    """Resolve the full feature dict for a product code + tier.

    Args:
        product_code: 3-char product code (AGW, ZUL, VNZ, CSM, STD).
        tier: One of 'community', 'pro', 'enterprise'.

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
    if tier not in ("community", "pro", "enterprise"):
        raise ValueError(f"Unknown tier: {tier}. Must be community, pro, or enterprise")

    return _PRODUCT_FEATURE_RESOLVERS[code](tier)


def get_tier_limits(tier: str) -> dict[str, int]:
    """Get usage limits for a tier.

    Returns empty dict for community (no limits enforced).
    """
    tier = tier.lower()
    return dict(USAGE_LIMITS.get(tier, {}))


def get_machines_limit(tier: str) -> int:
    """Get machine activation limit for a tier.

    Returns:
        3 for pro, 0 (unlimited) for enterprise, 1 for community.
    """
    tier = tier.lower()
    if tier == "enterprise":
        return 0
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
        "description": "Trendscope, Shopforge, Brandguard, Taskpilot, Claude Swarm",
        "default_tier": "community",
    },
]
